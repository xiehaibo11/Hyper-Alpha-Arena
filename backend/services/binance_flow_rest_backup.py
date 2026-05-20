"""Lightweight Binance taker-flow fallback backed by 1m futures klines."""

import logging
import os
from typing import Iterable, Optional

from database.connection import SessionLocal
from services.binance_symbol_service import get_selected_symbols
from services.exchanges.binance_adapter import BinanceAdapter
from services.exchanges.data_persistence import ExchangeDataPersistence

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 5
MAX_LIMIT = 1500


def _enabled() -> bool:
    raw_value = os.getenv("BINANCE_FLOW_REST_BACKUP_ENABLED", "true").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _normalize_symbols(symbols: Optional[Iterable[str]]) -> list[str]:
    normalized: list[str] = []
    for symbol in symbols or []:
        value = str(symbol or "").strip().upper()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def sync_binance_flow_from_klines(
    symbols: Optional[Iterable[str]] = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """Fetch recent Binance 1m klines and persist taker buy/sell flow rows."""
    if not _enabled():
        logger.info("[Binance] REST flow backup disabled by BINANCE_FLOW_REST_BACKUP_ENABLED")
        return {"enabled": False, "symbols": [], "results": {}, "errors": {}}

    selected_symbols = _normalize_symbols(symbols)
    if not selected_symbols:
        selected_symbols = _normalize_symbols(get_selected_symbols() or ["BTC"])

    safe_limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    adapter = BinanceAdapter(environment="mainnet")
    results: dict[str, dict] = {}
    errors: dict[str, str] = {}

    with SessionLocal() as db:
        persistence = ExchangeDataPersistence(db)
        for symbol in selected_symbols:
            try:
                klines = adapter.fetch_klines(symbol, "1m", limit=safe_limit)
                saved = persistence.save_taker_volumes_from_klines(klines)
                results[symbol] = {"fetched": len(klines), "saved": saved}
            except Exception as exc:
                logger.warning("[Binance] REST flow backup failed for %s: %s", symbol, exc, exc_info=True)
                errors[symbol] = str(exc)

    if results:
        logger.info("[Binance] REST flow backup synced: %s", results)
    return {"enabled": True, "symbols": selected_symbols, "results": results, "errors": errors}
