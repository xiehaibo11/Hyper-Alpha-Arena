"""OKX symbol management utilities."""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import SystemConfig
from services.exchanges.okx_adapter import OKXAdapter

logger = logging.getLogger(__name__)

OKX_AVAILABLE_SYMBOLS_KEY = "okx_available_symbols"
OKX_SELECTED_SYMBOLS_KEY = "okx_selected_symbols"
SYMBOL_REFRESH_TASK_ID = "okx_symbol_refresh"


def _watchlist_limit() -> int:
    raw_value = os.getenv("OKX_MAX_WATCHLIST_SYMBOLS") or os.getenv("MARKET_DATA_MAX_WATCHLIST_SYMBOLS") or "200"
    try:
        return max(1, min(1000, int(raw_value)))
    except ValueError:
        return 200


MAX_WATCHLIST_SYMBOLS = _watchlist_limit()

DEFAULT_SYMBOLS: List[Dict[str, str]] = [
    {"symbol": "BTC", "name": "Bitcoin", "type": "perpetual"},
    {"symbol": "ETH", "name": "Ethereum", "type": "perpetual"},
    {"symbol": "SOL", "name": "Solana", "type": "perpetual"},
    {"symbol": "XRP", "name": "XRP", "type": "perpetual"},
]


def _load_config_value(db: Session, key: str) -> Optional[str]:
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    return row.value if row else None


def _save_config_value(db: Session, key: str, value: str) -> None:
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if row:
        row.value = value
    else:
        db.add(SystemConfig(key=key, value=value))
    db.commit()


def _parse_symbol_json(value: Optional[str]) -> List[Dict[str, str]]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        logger.warning("[OKX] Failed to decode stored symbols; falling back to defaults")
        return []
    if not isinstance(parsed, list):
        return []

    result: List[Dict[str, str]] = []
    seen = set()
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        symbol = str(entry.get("symbol") or "").upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        result.append(
            {
                "symbol": symbol,
                "name": entry.get("name") or symbol,
                "type": entry.get("type") or "perpetual",
                "instId": entry.get("instId") or f"{symbol}-USDT-SWAP",
            }
        )
    return result


def _serialize_symbols(symbols: List[Dict[str, str]]) -> str:
    sanitized: List[Dict[str, str]] = []
    seen = set()
    for entry in symbols:
        symbol = str(entry.get("symbol") or "").upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        sanitized.append(
            {
                "symbol": symbol,
                "name": entry.get("name") or symbol,
                "type": entry.get("type") or "perpetual",
                "instId": entry.get("instId") or f"{symbol}-USDT-SWAP",
            }
        )
    return json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))


def fetch_remote_symbols() -> List[Dict[str, str]]:
    """Fetch live USDT SWAP symbols from OKX public instruments API."""
    try:
        instruments = OKXAdapter().fetch_instruments(inst_type="SWAP")
    except Exception as exc:
        logger.warning("[OKX] Failed to fetch instruments: %s", exc)
        return []

    results: List[Dict[str, str]] = []
    seen = set()
    for entry in instruments:
        if not isinstance(entry, dict):
            continue
        if entry.get("state") != "live" or entry.get("settleCcy") != "USDT":
            continue
        inst_id = str(entry.get("instId") or "")
        if not inst_id.endswith("-USDT-SWAP"):
            continue
        symbol = inst_id.split("-", 1)[0].upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        results.append({"symbol": symbol, "name": symbol, "type": "perpetual", "instId": inst_id})

    logger.info("[OKX] Fetched %d USDT perpetual swap symbols", len(results))
    return results


def _ensure_watchlist_valid(db: Session, available: List[Dict[str, str]]) -> None:
    available_set = {item["symbol"] for item in available}
    raw_value = _load_config_value(db, OKX_SELECTED_SYMBOLS_KEY)

    if not raw_value:
        for source_key in ("binance_selected_symbols", "hyperliquid_selected_symbols"):
            source_raw = _load_config_value(db, source_key)
            if not source_raw:
                continue
            try:
                source_symbols = json.loads(source_raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(source_symbols, list):
                valid = [str(item).upper() for item in source_symbols if str(item).upper() in available_set]
                if valid:
                    _save_config_value(db, OKX_SELECTED_SYMBOLS_KEY, json.dumps(valid[:MAX_WATCHLIST_SYMBOLS]))
                    logger.info("[OKX] Initialized watchlist from %s: %s", source_key, valid[:MAX_WATCHLIST_SYMBOLS])
                    return

        default = [entry["symbol"] for entry in DEFAULT_SYMBOLS if entry["symbol"] in available_set]
        _save_config_value(db, OKX_SELECTED_SYMBOLS_KEY, json.dumps(default or [entry["symbol"] for entry in available[:3]]))
        return

    try:
        symbols = json.loads(raw_value)
        if not isinstance(symbols, list):
            raise ValueError("selection is not a list")
    except Exception:
        default = [entry["symbol"] for entry in DEFAULT_SYMBOLS if entry["symbol"] in available_set]
        _save_config_value(db, OKX_SELECTED_SYMBOLS_KEY, json.dumps(default))
        logger.warning("[OKX] Invalid stored watchlist; reset to defaults")
        return

    filtered = [str(item).upper() for item in symbols if str(item).upper() in available_set]
    if len(filtered) != len(symbols):
        removed = set(str(item).upper() for item in symbols) - set(filtered)
        logger.warning("[OKX] Removed invalid symbols from watchlist: %s", removed)
        _save_config_value(db, OKX_SELECTED_SYMBOLS_KEY, json.dumps(filtered[:MAX_WATCHLIST_SYMBOLS]))


def refresh_okx_symbols() -> List[Dict[str, str]]:
    remote_symbols = fetch_remote_symbols()
    with SessionLocal() as db:
        if remote_symbols:
            _save_config_value(db, OKX_AVAILABLE_SYMBOLS_KEY, _serialize_symbols(remote_symbols))
            _ensure_watchlist_valid(db, remote_symbols)
        else:
            stored = _parse_symbol_json(_load_config_value(db, OKX_AVAILABLE_SYMBOLS_KEY))
            if not stored:
                _save_config_value(db, OKX_AVAILABLE_SYMBOLS_KEY, _serialize_symbols(DEFAULT_SYMBOLS))
                _ensure_watchlist_valid(db, DEFAULT_SYMBOLS)
    return get_available_symbols()


def get_available_symbols() -> List[Dict[str, str]]:
    with SessionLocal() as db:
        symbols = _parse_symbol_json(_load_config_value(db, OKX_AVAILABLE_SYMBOLS_KEY))
        return symbols or DEFAULT_SYMBOLS.copy()


def get_available_symbols_info() -> Dict[str, object]:
    symbols = get_available_symbols()
    return {"symbols": symbols, "count": len(symbols)}


def get_selected_symbols() -> List[str]:
    with SessionLocal() as db:
        raw_value = _load_config_value(db, OKX_SELECTED_SYMBOLS_KEY)
        if not raw_value:
            _ensure_watchlist_valid(db, get_available_symbols())
            raw_value = _load_config_value(db, OKX_SELECTED_SYMBOLS_KEY)
        try:
            symbols = json.loads(raw_value or "[]")
            if isinstance(symbols, list) and symbols:
                return [str(item).upper() for item in symbols]
        except json.JSONDecodeError:
            logger.warning("[OKX] Failed to parse watchlist; returning defaults")
        default = [entry["symbol"] for entry in DEFAULT_SYMBOLS]
        _save_config_value(db, OKX_SELECTED_SYMBOLS_KEY, json.dumps(default))
        return default


def update_selected_symbols(symbols: List[str]) -> List[str]:
    available_set = {item["symbol"] for item in get_available_symbols()}
    unique_symbols: List[str] = []
    seen = set()
    for symbol in symbols:
        sym = str(symbol).upper()
        if not sym or sym in seen or sym not in available_set:
            continue
        seen.add(sym)
        unique_symbols.append(sym)
    unique_symbols = unique_symbols[:MAX_WATCHLIST_SYMBOLS]

    with SessionLocal() as db:
        _save_config_value(db, OKX_SELECTED_SYMBOLS_KEY, json.dumps(unique_symbols))

    try:
        from services.exchanges.okx_collector import okx_collector

        if okx_collector.running:
            okx_collector.refresh_symbols(unique_symbols)
    except Exception as exc:
        logger.warning("[OKX] Unable to refresh collector symbols: %s", exc)

    return unique_symbols


def get_symbol_map() -> Dict[str, Dict[str, str]]:
    return {item["symbol"]: item for item in get_available_symbols()}


def schedule_symbol_refresh_task(interval_seconds: int = 7200) -> None:
    from services.scheduler import task_scheduler

    def _task() -> None:
        try:
            refreshed = refresh_okx_symbols()
            logger.debug("[OKX] Symbol refresh task ran; %d symbols available", len(refreshed))
        except Exception as exc:
            logger.warning("[OKX] Symbol refresh failed: %s", exc)

    task_scheduler.remove_task(SYMBOL_REFRESH_TASK_ID)
    task_scheduler.add_interval_task(
        task_func=_task,
        interval_seconds=interval_seconds,
        task_id=SYMBOL_REFRESH_TASK_ID,
    )
    logger.info("[OKX] Symbol refresh task scheduled (interval: %ds)", interval_seconds)
