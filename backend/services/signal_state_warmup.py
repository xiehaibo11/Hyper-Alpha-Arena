"""Warm signal edge states during startup without firing callbacks."""

from __future__ import annotations

import logging
import time
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)


def warm_signal_pool_states(*, exchange: str = "binance", symbols: Optional[Iterable[str]] = None) -> dict[str, Any]:
    """Hydrate pool_states so startup does not turn existing conditions into new edges."""
    from services.signal_detection_service import PoolState, signal_detection_service

    normalized_exchange = str(exchange or "binance").lower()
    requested_symbols = _normalize_symbols(symbols)
    signal_detection_service._refresh_cache_if_needed()

    warmed = 0
    skipped = 0
    now = time.time()
    for pool in signal_detection_service._signal_pools_cache:
        if str(pool.get("exchange") or "").lower() != normalized_exchange:
            continue
        pool_symbols = _pool_symbols(pool, requested_symbols)
        for symbol in pool_symbols:
            signal_conditions = _evaluate_pool_signals(signal_detection_service, pool, symbol)
            if not signal_conditions:
                skipped += 1
                continue

            state_key = (pool["id"], symbol)
            state = signal_detection_service.pool_states.get(state_key)
            if state is None:
                state = PoolState(pool_id=pool["id"], symbol=symbol)
                signal_detection_service.pool_states[state_key] = state
            state.is_active = _is_pool_active(pool.get("logic"), signal_conditions)
            state.signal_conditions_met = signal_conditions
            state.last_check_time = now
            warmed += 1

    logger.info(
        "[SignalWarmup] exchange=%s warmed=%s skipped=%s symbols=%s",
        normalized_exchange,
        warmed,
        skipped,
        requested_symbols or "all",
    )
    return {"warmed": warmed, "skipped": skipped, "exchange": normalized_exchange}


def _evaluate_pool_signals(service: Any, pool: dict[str, Any], symbol: str) -> dict[int, bool]:
    signal_conditions: dict[int, bool] = {}
    for signal_id in pool.get("signal_ids") or []:
        signal_def = service._signals_cache.get(signal_id)
        if not signal_def or not signal_def.get("enabled"):
            continue
        try:
            result = service._check_signal_condition(signal_id, signal_def, symbol, {})
        except Exception as exc:
            logger.warning("[SignalWarmup] %s %s failed: %s", symbol, signal_id, exc, exc_info=True)
            continue
        if result is not None and result.get("condition_met") is not None:
            signal_conditions[signal_id] = bool(result["condition_met"])
    return signal_conditions


def _is_pool_active(logic: Optional[str], signal_conditions: dict[int, bool]) -> bool:
    if str(logic or "OR").upper() == "AND":
        return all(signal_conditions.values())
    return any(signal_conditions.values())


def _pool_symbols(pool: dict[str, Any], requested_symbols: list[str]) -> list[str]:
    configured = _normalize_symbols(pool.get("symbols") or [])
    if requested_symbols:
        return [symbol for symbol in configured if symbol in requested_symbols]
    return configured


def _normalize_symbols(symbols: Optional[Iterable[str]]) -> list[str]:
    if isinstance(symbols, str):
        symbols = symbols.split(",")
    result: list[str] = []
    for raw_symbol in symbols or []:
        symbol = str(raw_symbol or "").upper().replace("USDT", "").strip()
        if symbol and symbol not in result:
            result.append(symbol)
    return result
