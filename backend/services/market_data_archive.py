from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
import gzip
import json
import logging
import os
import time

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from config.storage import get_upload_storage_settings
from services.upload_storage import UploadStorage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArchiveTable:
    name: str
    timestamp_column: str = "timestamp"
    timestamp_unit: str = "ms"
    exchange_column: Optional[str] = "exchange"
    exchanges: Optional[set[str]] = None


@dataclass
class ArchiveSummary:
    enabled: bool
    exchange: str
    retention_days: int
    archived_rows: int = 0
    deleted_rows: int = 0
    uploaded_objects: int = 0
    skipped_reason: Optional[str] = None

    @property
    def handled_cleanup(self) -> bool:
        return self.enabled and self.skipped_reason is None


ARCHIVE_TABLES: tuple[ArchiveTable, ...] = (
    ArchiveTable("market_trades_aggregated"),
    ArchiveTable("market_orderbook_snapshots"),
    ArchiveTable("market_asset_metrics"),
    ArchiveTable("market_sentiment_metrics", exchanges={"binance", "okx"}),
    ArchiveTable("crypto_klines", timestamp_unit="s"),
)


def _truthy_env(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def market_data_archive_enabled() -> bool:
    return _truthy_env("MARKET_DATA_ARCHIVE_ENABLED", "true")


def market_data_archive_requires_success() -> bool:
    return _truthy_env("MARKET_DATA_ARCHIVE_REQUIRE_SUCCESS", "true")


def market_data_archive_prefix() -> str:
    return os.getenv("MARKET_DATA_ARCHIVE_PREFIX", "market-data").strip().strip("/") or "market-data"


def market_data_archive_batch_size() -> int:
    try:
        return max(1, int(os.getenv("MARKET_DATA_ARCHIVE_BATCH_SIZE", "5000")))
    except ValueError:
        return 5000


def market_data_archive_max_batches_per_table() -> int:
    try:
        return max(1, int(os.getenv("MARKET_DATA_ARCHIVE_MAX_BATCHES_PER_TABLE", "20")))
    except ValueError:
        return 20


def default_market_data_retention_days() -> int:
    try:
        return max(1, int(os.getenv("MARKET_DATA_RETENTION_DEFAULT_DAYS", "1")))
    except ValueError:
        return 1


def kline_market_data_retention_days(default_retention_days: int) -> int:
    try:
        configured_days = int(os.getenv("MARKET_DATA_KLINE_RETENTION_DAYS", "45"))
    except ValueError:
        configured_days = 45
    return max(default_retention_days, configured_days, 1)


def _archive_storage() -> UploadStorage:
    settings = get_upload_storage_settings()
    archive_bucket = os.getenv("MARKET_DATA_ARCHIVE_OSS_BUCKET", "").strip()
    if settings.mode == "oss" and archive_bucket:
        settings = settings.model_copy(
            update={
                "oss_bucket": archive_bucket,
                "public_base_url": None,
                "oss_cache_control": os.getenv(
                    "MARKET_DATA_ARCHIVE_OSS_CACHE_CONTROL",
                    "private,max-age=31536000",
                ).strip(),
            }
        )
    return UploadStorage(settings)


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _ts_to_date(timestamp_value: int, unit: str) -> str:
    seconds = timestamp_value / 1000 if unit == "ms" else timestamp_value
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%d")


def _ts_to_iso(timestamp_value: int, unit: str) -> str:
    seconds = timestamp_value / 1000 if unit == "ms" else timestamp_value
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


class MarketDataArchiveService:
    """Archive old high-volume market data to OSS before deleting local rows."""

    def archive_expired_for_exchange(
        self,
        db: Session,
        exchange: str,
        retention_days: int,
    ) -> ArchiveSummary:
        exchange = exchange.strip().lower()
        summary = ArchiveSummary(
            enabled=market_data_archive_enabled(),
            exchange=exchange,
            retention_days=retention_days,
        )

        if not summary.enabled:
            summary.skipped_reason = "disabled"
            return summary

        storage = _archive_storage()
        if storage.settings.mode != "oss" or not storage.settings.is_oss_ready:
            summary.skipped_reason = "oss_not_configured"
            logger.warning(
                "Market data archive skipped for %s: OSS is not fully configured",
                exchange,
            )
            return summary

        batch_size = market_data_archive_batch_size()
        max_batches = market_data_archive_max_batches_per_table()

        for table in ARCHIVE_TABLES:
            if table.exchanges and exchange not in table.exchanges:
                continue

            table_retention_days = self._retention_days_for_table(table, retention_days)
            cutoff = self._cutoff_timestamp(table_retention_days, table.timestamp_unit)
            table_summary = self._archive_table(
                db=db,
                storage=storage,
                table=table,
                exchange=exchange,
                cutoff=cutoff,
                batch_size=batch_size,
                max_batches=max_batches,
            )
            summary.archived_rows += table_summary["archived_rows"]
            summary.deleted_rows += table_summary["deleted_rows"]
            summary.uploaded_objects += table_summary["uploaded_objects"]

        return summary

    def _archive_table(
        self,
        db: Session,
        storage: UploadStorage,
        table: ArchiveTable,
        exchange: str,
        cutoff: int,
        batch_size: int,
        max_batches: int,
    ) -> dict[str, int]:
        archived_rows = 0
        deleted_rows = 0
        uploaded_objects = 0

        for _ in range(max_batches):
            rows = self._fetch_batch(db, table, exchange, cutoff, batch_size)
            if not rows:
                break

            object_key = self._object_key(table, exchange, rows)
            payload = self._build_payload(table, exchange, cutoff, rows)

            try:
                storage.save_bytes(object_key, payload, content_type="application/gzip")
                deleted = self._delete_archived_rows(db, table.name, [row["id"] for row in rows])
                db.commit()
            except Exception:
                db.rollback()
                logger.exception(
                    "Market data archive failed: table=%s exchange=%s rows=%s",
                    table.name,
                    exchange,
                    len(rows),
                )
                raise

            archived_rows += len(rows)
            deleted_rows += deleted
            uploaded_objects += 1

            logger.info(
                "Archived market data to OSS: table=%s exchange=%s rows=%s deleted=%s object=%s",
                table.name,
                exchange,
                len(rows),
                deleted,
                object_key,
            )

            if len(rows) < batch_size:
                break

        return {
            "archived_rows": archived_rows,
            "deleted_rows": deleted_rows,
            "uploaded_objects": uploaded_objects,
        }

    def _fetch_batch(
        self,
        db: Session,
        table: ArchiveTable,
        exchange: str,
        cutoff: int,
        batch_size: int,
    ) -> list[dict[str, Any]]:
        where = f"{table.timestamp_column} < :cutoff"
        params: dict[str, Any] = {"cutoff": cutoff, "limit": batch_size}
        if table.exchange_column:
            where = f"{table.exchange_column} = :exchange AND {where}"
            params["exchange"] = exchange

        stmt = text(
            f"""
            SELECT *
            FROM {table.name}
            WHERE {where}
            ORDER BY {table.timestamp_column} ASC, id ASC
            LIMIT :limit
            """
        )
        return [dict(row) for row in db.execute(stmt, params).mappings().all()]

    def _delete_archived_rows(self, db: Session, table_name: str, ids: list[int]) -> int:
        if not ids:
            return 0
        stmt = text(f"DELETE FROM {table_name} WHERE id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        )
        result = db.execute(stmt, {"ids": ids})
        return int(result.rowcount or 0)

    def _build_payload(
        self,
        table: ArchiveTable,
        exchange: str,
        cutoff: int,
        rows: list[dict[str, Any]],
    ) -> bytes:
        first_ts = int(rows[0][table.timestamp_column])
        last_ts = int(rows[-1][table.timestamp_column])
        metadata = {
            "_archive_meta": {
                "archive_version": 1,
                "archived_at": datetime.now(timezone.utc).isoformat(),
                "table": table.name,
                "exchange": exchange,
                "row_count": len(rows),
                "retention_cutoff": cutoff,
                "first_timestamp": first_ts,
                "last_timestamp": last_ts,
                "first_time": _ts_to_iso(first_ts, table.timestamp_unit),
                "last_time": _ts_to_iso(last_ts, table.timestamp_unit),
            }
        }
        lines = [json.dumps(metadata, ensure_ascii=False, default=_json_default)]
        lines.extend(json.dumps(row, ensure_ascii=False, default=_json_default) for row in rows)
        return gzip.compress(("\n".join(lines) + "\n").encode("utf-8"))

    def _object_key(
        self,
        table: ArchiveTable,
        exchange: str,
        rows: list[dict[str, Any]],
    ) -> str:
        first_ts = int(rows[0][table.timestamp_column])
        last_ts = int(rows[-1][table.timestamp_column])
        date_part = _ts_to_date(first_ts, table.timestamp_unit)
        archived_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return (
            f"{market_data_archive_prefix()}/v1/{exchange}/{table.name}/dt={date_part}/"
            f"{table.name}-{first_ts}-{last_ts}-{archived_at}-{len(rows)}.jsonl.gz"
        )

    @staticmethod
    def _cutoff_timestamp(retention_days: int, unit: str) -> int:
        multiplier = 1000 if unit == "ms" else 1
        return int((time.time() - retention_days * 86400) * multiplier)

    @staticmethod
    def _retention_days_for_table(table: ArchiveTable, default_retention_days: int) -> int:
        if table.name == "crypto_klines":
            return kline_market_data_retention_days(default_retention_days)
        return default_retention_days


market_data_archive_service = MarketDataArchiveService()


def get_market_data_archive_status() -> dict[str, Any]:
    storage = _archive_storage()
    return {
        "enabled": market_data_archive_enabled(),
        "require_success_before_delete": market_data_archive_requires_success(),
        "storage_mode": storage.settings.mode,
        "oss_ready": storage.settings.is_oss_ready,
        "oss_bucket": storage.settings.oss_bucket,
        "prefix": market_data_archive_prefix(),
        "default_retention_days": default_market_data_retention_days(),
        "kline_retention_days": kline_market_data_retention_days(default_market_data_retention_days()),
        "batch_size": market_data_archive_batch_size(),
        "max_batches_per_table": market_data_archive_max_batches_per_table(),
    }
