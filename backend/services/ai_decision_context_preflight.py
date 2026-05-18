"""Pre-decision Arena context refresh for AI trading.

The main trading AI consumes Arena sub-AI snapshots as advisory context. This
module makes the trading loop refresh those snapshots before the main AI call,
instead of only enqueueing a background refresh after stale data is detected.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_PREFLIGHT_MIN_INTERVAL_SECONDS = 120
DEFAULT_PREFLIGHT_MAX_SYMBOLS = 16

_CACHE_LOCK = threading.Lock()
_LAST_REFRESH_STARTED_AT: Dict[Tuple[Optional[int], str, Tuple[str, ...], str], float] = {}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _env_int(name: str, default: int, *, minimum: int = 0, maximum: int = 3600) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def infer_decision_context_timeframe(
    trigger_context: Optional[Dict[str, Any]],
    default: str = "15m",
) -> str:
    """Use the signal timeframe when a signal triggered the decision."""

    configured = os.getenv("AI_DECISION_PREFLIGHT_TIMEFRAME")
    timeframe = str(configured or default or "15m")
    if not trigger_context:
        return timeframe

    direct = trigger_context.get("arena_context_timeframe") or trigger_context.get("timeframe")
    if direct:
        return str(direct)

    triggered_signals = trigger_context.get("triggered_signals") or []
    if isinstance(triggered_signals, list):
        for signal in triggered_signals:
            if not isinstance(signal, dict):
                continue
            candidate = signal.get("time_window") or signal.get("timeframe") or signal.get("period")
            if candidate:
                return str(candidate)

    return timeframe


def _normalize_preflight_symbols(exchange: str, symbols: Iterable[str], max_symbols: int) -> List[str]:
    try:
        from services.arena_ai_context_service import normalize_symbols

        return normalize_symbols(exchange, symbols, limit=max_symbols)
    except Exception:
        normalized: List[str] = []
        seen = set()
        for item in symbols or []:
            symbol = str(item or "").strip().upper().replace("-USD", "").replace("-PERP", "").replace("USDT", "")
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            normalized.append(symbol)
            if len(normalized) >= max_symbols:
                break
        return normalized


def refresh_decision_arena_context(
    *,
    account_id: Optional[int],
    exchange: str,
    symbols: Iterable[str],
    timeframe: Optional[str] = None,
    reason: str = "ai_decision",
    force: bool = False,
) -> Dict[str, Any]:
    """Synchronously refresh all Arena sub-AI snapshots before a trading AI call."""

    if not _env_bool("AI_DECISION_PREFLIGHT_CONTEXT_ENABLED", True):
        return {"enabled": False, "status": "disabled", "reason": reason}

    normalized_exchange = str(exchange or "binance").strip().lower()
    if normalized_exchange not in {"binance", "hyperliquid"}:
        normalized_exchange = "binance"

    max_symbols = _env_int(
        "AI_DECISION_PREFLIGHT_MAX_SYMBOLS",
        DEFAULT_PREFLIGHT_MAX_SYMBOLS,
        minimum=1,
        maximum=32,
    )
    symbol_list = _normalize_preflight_symbols(normalized_exchange, symbols, max_symbols)
    if not symbol_list:
        return {
            "enabled": True,
            "status": "skipped_no_symbols",
            "reason": reason,
            "account_id": account_id,
            "exchange": normalized_exchange,
        }

    selected_timeframe = str(timeframe or os.getenv("AI_DECISION_PREFLIGHT_TIMEFRAME") or "15m")
    min_interval = _env_int(
        "AI_DECISION_PREFLIGHT_MIN_INTERVAL_SECONDS",
        DEFAULT_PREFLIGHT_MIN_INTERVAL_SECONDS,
        minimum=0,
        maximum=3600,
    )
    key = (account_id, normalized_exchange, tuple(symbol_list), selected_timeframe)
    now = time.time()

    with _CACHE_LOCK:
        last_started_at = _LAST_REFRESH_STARTED_AT.get(key)
        if not force and last_started_at and now - last_started_at < min_interval:
            return {
                "enabled": True,
                "status": "skipped_recent",
                "reason": reason,
                "account_id": account_id,
                "exchange": normalized_exchange,
                "symbols": symbol_list,
                "timeframe": selected_timeframe,
                "age_seconds": round(now - last_started_at, 1),
                "min_interval_seconds": min_interval,
            }
        _LAST_REFRESH_STARTED_AT[key] = now

    started = time.perf_counter()
    try:
        from database.connection import SessionLocal
        from services.arena_ai_context_service import recompute_arena_ai_context

        db = SessionLocal()
        try:
            result = recompute_arena_ai_context(
                db,
                account_id=account_id,
                exchange=normalized_exchange,
                symbols=symbol_list,
                timeframe=selected_timeframe,
                commit=True,
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        snapshots = result.get("snapshots") or []
        module_counts: Dict[str, int] = {}
        status_counts: Dict[str, int] = {}
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                continue
            module = str(snapshot.get("module") or "unknown")
            status = str(snapshot.get("status") or "unknown")
            module_counts[module] = module_counts.get(module, 0) + 1
            status_counts[status] = status_counts.get(status, 0) + 1

        logger.info(
            "AI decision Arena context preflight refreshed account_id=%s exchange=%s timeframe=%s "
            "symbols=%s snapshots=%s elapsed_ms=%s reason=%s",
            account_id,
            normalized_exchange,
            selected_timeframe,
            symbol_list,
            len(snapshots),
            elapsed_ms,
            reason,
        )
        return {
            "enabled": True,
            "status": "refreshed",
            "reason": reason,
            "account_id": account_id,
            "exchange": normalized_exchange,
            "symbols": symbol_list,
            "timeframe": selected_timeframe,
            "snapshot_count": len(snapshots),
            "module_counts": module_counts,
            "status_counts": status_counts,
            "elapsed_ms": elapsed_ms,
        }
    except Exception as exc:
        with _CACHE_LOCK:
            _LAST_REFRESH_STARTED_AT.pop(key, None)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.warning(
            "AI decision Arena context preflight failed account_id=%s exchange=%s timeframe=%s "
            "symbols=%s elapsed_ms=%s error=%s",
            account_id,
            normalized_exchange,
            selected_timeframe,
            symbol_list,
            elapsed_ms,
            exc,
            exc_info=True,
        )
        return {
            "enabled": True,
            "status": "failed",
            "reason": reason,
            "account_id": account_id,
            "exchange": normalized_exchange,
            "symbols": symbol_list,
            "timeframe": selected_timeframe,
            "elapsed_ms": elapsed_ms,
            "error": str(exc),
        }
