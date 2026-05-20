"""Live signal-system snapshots for UI monitoring and AI decisions."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def build_signal_runtime_snapshot_payload(
    db: Optional[Session],
    *,
    symbols: Optional[Iterable[str]] = None,
    exchange: str = "binance",
    pool_id: Optional[int] = None,
    include_values: bool = True,
) -> dict[str, Any]:
    """Return current enabled signal-pool state plus fresh condition values."""
    from services.signal_detection_service import signal_detection_service

    normalized_exchange = str(exchange or "binance").lower()
    normalized_symbols = _normalize_symbols(symbols)
    now = time.time()

    signal_detection_service._refresh_cache_if_needed()
    pools = _matching_pools(
        signal_detection_service._signal_pools_cache,
        exchange=normalized_exchange,
        pool_id=pool_id,
    )
    last_triggers = _load_last_triggers(db)

    rows: list[dict[str, Any]] = []
    for pool in pools:
        pool_symbols = _pool_symbols(pool, normalized_symbols)
        for symbol in pool_symbols:
            state = signal_detection_service.pool_states.get((pool["id"], symbol))
            signal_rows = _build_signal_rows(
                signal_detection_service,
                pool,
                symbol,
                state,
                include_values=include_values,
            )
            computed_active = _pool_active(pool.get("logic"), signal_rows)
            detector_active = bool(getattr(state, "is_active", False))
            last_check_time = getattr(state, "last_check_time", 0) or None
            rows.append(
                {
                    "pool_id": pool["id"],
                    "pool_name": pool.get("pool_name"),
                    "exchange": pool.get("exchange") or normalized_exchange,
                    "symbol": symbol,
                    "logic": (pool.get("logic") or "OR").upper(),
                    "is_active": computed_active if computed_active is not None else detector_active,
                    "detector_active": detector_active,
                    "last_check_time": _epoch_to_iso(last_check_time),
                    "seconds_since_check": _age_seconds(now, last_check_time),
                    "last_triggered_at": _iso_datetime(last_triggers.get((pool["id"], symbol))),
                    "signals": signal_rows,
                }
            )

    return {
        "success": True,
        "exchange": normalized_exchange,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pools": rows,
    }


def build_signal_runtime_snapshot_text(
    db: Optional[Session],
    *,
    symbols: Iterable[str],
    exchange: str = "binance",
) -> str:
    """Build a compact live signal snapshot for an AI decision prompt."""
    payload = build_signal_runtime_snapshot_payload(
        db,
        symbols=symbols,
        exchange=exchange,
        include_values=True,
    )
    pools = payload.get("pools") or []
    if not pools:
        return ""

    lines = [
        "=== LIVE SIGNAL SYSTEM SNAPSHOT ===",
        "Source: SignalDetectionService live Binance pools; values re-evaluated at prompt time.",
        "This block is appended at runtime only; it is not saved into the Prompt Template.",
    ]
    for pool in pools:
        age = pool.get("seconds_since_check")
        age_text = f"{age:.1f}s" if isinstance(age, (int, float)) else "N/A"
        lines.append(
            f"- {pool['symbol']} {pool['pool_name']} pool_id={pool['pool_id']} "
            f"logic={pool['logic']} active={pool['is_active']} "
            f"detector_age={age_text} last_trigger={pool.get('last_triggered_at') or 'N/A'}"
        )
        for signal in pool.get("signals", []):
            value_text = _format_value(signal.get("current_value"))
            threshold = signal.get("threshold")
            threshold_text = threshold if threshold is not None else "N/A"
            lines.append(
                f"  - {signal.get('signal_name')} metric={signal.get('metric')} "
                f"period={signal.get('time_window')} value={value_text} "
                f"op={signal.get('operator') or 'event'} threshold={threshold_text} "
                f"met={signal.get('condition_met')}"
            )
    return "\n".join(lines)


def _matching_pools(pools: list[dict[str, Any]], *, exchange: str, pool_id: Optional[int]) -> list[dict[str, Any]]:
    matched = []
    for pool in pools:
        if pool_id is not None and int(pool.get("id") or 0) != pool_id:
            continue
        if str(pool.get("exchange") or "").lower() != exchange:
            continue
        matched.append(pool)
    return matched


def _pool_symbols(pool: dict[str, Any], requested: list[str]) -> list[str]:
    configured = _normalize_symbols(pool.get("symbols") or [])
    if requested:
        return [symbol for symbol in configured if symbol in requested]
    return configured


def _build_signal_rows(service: Any, pool: dict[str, Any], symbol: str, state: Any, *, include_values: bool) -> list[dict[str, Any]]:
    rows = []
    state_conditions = getattr(state, "signal_conditions_met", {}) or {}
    for signal_id in pool.get("signal_ids") or []:
        signal_def = service._signals_cache.get(signal_id)
        if not signal_def:
            continue
        detail = _safe_signal_detail(service, signal_id, signal_def, symbol) if include_values else None
        condition = signal_def.get("trigger_condition") or {}
        rows.append(_compact_signal_row(signal_id, signal_def, condition, detail, state_conditions))
    return rows


def _safe_signal_detail(service: Any, signal_id: int, signal_def: dict[str, Any], symbol: str) -> Optional[dict[str, Any]]:
    try:
        return service._check_signal_condition(signal_id, signal_def, symbol, {})
    except Exception as exc:
        logger.warning("[signal_runtime_snapshot] %s %s failed: %s", symbol, signal_id, exc, exc_info=True)
        return {"error": str(exc), "condition_met": None}


def _compact_signal_row(
    signal_id: int,
    signal_def: dict[str, Any],
    condition: dict[str, Any],
    detail: Optional[dict[str, Any]],
    state_conditions: dict[int, bool],
) -> dict[str, Any]:
    detail = detail or {}
    metric = detail.get("metric") or condition.get("metric")
    row = {
        "signal_id": signal_id,
        "signal_name": signal_def.get("signal_name"),
        "description": signal_def.get("description"),
        "metric": metric,
        "operator": detail.get("operator") or condition.get("operator"),
        "threshold": detail.get("threshold") or condition.get("threshold"),
        "time_window": detail.get("time_window") or condition.get("time_window"),
        "exchange": detail.get("exchange") or signal_def.get("exchange"),
        "current_value": _extract_current_value(detail),
        "condition_met": detail.get("condition_met", state_conditions.get(signal_id)),
        "direction": detail.get("direction"),
        "ratio": detail.get("ratio"),
        "buy": detail.get("buy"),
        "sell": detail.get("sell"),
        "total": detail.get("total"),
        "triggered_event": detail.get("triggered_event"),
        "error": detail.get("error"),
    }
    if isinstance(detail.get("values"), dict):
        row["values"] = {
            key: detail["values"].get(key)
            for key in ("macd", "signal", "histogram", "prev_histogram")
        }
    return row


def _pool_active(logic: Optional[str], signals: list[dict[str, Any]]) -> Optional[bool]:
    states = [signal.get("condition_met") for signal in signals if signal.get("condition_met") is not None]
    if not states:
        return None
    if str(logic or "OR").upper() == "AND":
        return all(bool(state) for state in states)
    return any(bool(state) for state in states)


def _load_last_triggers(db: Optional[Session]) -> dict[tuple[int, str], Any]:
    if db is None:
        return {}
    try:
        result = db.execute(
            text(
                """
                SELECT pool_id, symbol, MAX(triggered_at) AS triggered_at
                FROM signal_trigger_logs
                WHERE pool_id IS NOT NULL
                GROUP BY pool_id, symbol
                """
            )
        )
        return {(int(row[0]), str(row[1]).upper()): row[2] for row in result.fetchall()}
    except Exception as exc:
        logger.warning("[signal_runtime_snapshot] failed to load last triggers: %s", exc)
        return {}


def _normalize_symbols(symbols: Optional[Iterable[str]]) -> list[str]:
    if isinstance(symbols, str):
        symbols = symbols.split(",")
    result: list[str] = []
    for raw_symbol in symbols or []:
        symbol = str(raw_symbol or "").upper().replace("USDT", "").strip()
        if symbol and symbol not in result:
            result.append(symbol)
    return result


def _extract_current_value(detail: dict[str, Any]) -> Any:
    if "current_value" in detail:
        return detail.get("current_value")
    if detail.get("metric") == "taker_volume":
        return detail.get("ratio")
    values = detail.get("values")
    if isinstance(values, dict):
        return values.get("histogram") or values.get("macd")
    return None


def _age_seconds(now: float, epoch: Optional[float]) -> Optional[float]:
    if not epoch:
        return None
    return max(0.0, now - float(epoch))


def _epoch_to_iso(epoch: Optional[float]) -> Optional[str]:
    if not epoch:
        return None
    return datetime.fromtimestamp(float(epoch), timezone.utc).isoformat()


def _iso_datetime(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()
    return str(value)


def _format_value(value: Any) -> str:
    try:
        if value is None:
            return "N/A"
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return str(value)
