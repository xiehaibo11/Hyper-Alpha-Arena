"""Local crypto K-line reads and persistence helpers."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text

from database.connection import SessionLocal

logger = logging.getLogger(__name__)


def load_local_klines(
    *,
    symbol: str,
    exchange: str,
    period: str,
    count: int,
    environment: str = "mainnet",
) -> list[dict[str, Any]]:
    """Load recent K-lines from crypto_klines without hitting exchange APIs."""
    limit = max(1, min(int(count or 100), 5000))
    params = {
        "exchange": exchange.lower(),
        "symbol": symbol.upper(),
        "period": period,
        "environment": environment,
        "limit": limit,
    }

    query = text(
        """
        SELECT timestamp, open_price, high_price, low_price, close_price,
               volume, amount, change, percent
        FROM crypto_klines
        WHERE exchange = :exchange
          AND symbol = :symbol
          AND period = :period
          AND environment = :environment
        ORDER BY timestamp DESC
        LIMIT :limit
        """
    )

    try:
        with SessionLocal() as db:
            rows = db.execute(query, params).fetchall()
    except Exception as exc:
        logger.warning(
            "Failed to read local K-lines for %s/%s/%s: %s",
            exchange,
            symbol,
            period,
            exc,
        )
        return []

    return [_row_to_kline(row) for row in reversed(rows)]


def save_unified_klines(klines: list[Any], *, environment: str = "mainnet") -> None:
    """Persist exchange adapter K-lines to crypto_klines."""
    if not klines:
        return

    try:
        from services.exchanges.data_persistence import ExchangeDataPersistence

        with SessionLocal() as db:
            ExchangeDataPersistence(db).save_klines(klines, environment=environment)
    except Exception as exc:
        logger.warning("Failed to persist fetched K-lines: %s", exc)


def _row_to_kline(row: Any) -> dict[str, Any]:
    timestamp = int(row[0])
    return {
        "timestamp": timestamp,
        "datetime": datetime.fromtimestamp(timestamp),
        "open": _to_float(row[1]),
        "high": _to_float(row[2]),
        "low": _to_float(row[3]),
        "close": _to_float(row[4]),
        "volume": _to_float(row[5]),
        "amount": _to_float(row[6]),
        "chg": _to_float(row[7]),
        "percent": _to_float(row[8]),
    }


def _to_float(value: Any) -> float | None:
    return None if value is None else float(value)
