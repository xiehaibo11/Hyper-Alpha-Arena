"""
On-demand K-line history backfill for indicator/Arena calculations.

The regular collectors keep watchlist data fresh, but a symbol or timeframe can
still be sparse right after deployment, after retention cleanup, or when a new
symbol enters the Arena. This module performs a bounded public REST fetch before
an indicator calculation gives up.
"""

from __future__ import annotations

import logging
import threading
import time
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import desc
from sqlalchemy.orm import Session

from database.models import CryptoKline
from services.exchanges.binance_adapter import BinanceAdapter
from services.exchanges.data_persistence import ExchangeDataPersistence
from services.exchanges.okx_adapter import OKXAdapter
from services.technical_indicators import get_required_kline_count

logger = logging.getLogger(__name__)

SUPPORTED_BINANCE_PERIODS = {
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1M",
}
SUPPORTED_OKX_PERIODS = {
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1M",
}
DEFAULT_LOOKBACK = 180
FETCH_COOLDOWN_SECONDS = 45
MAX_FETCH_LIMIT = 500

_fetch_lock = threading.Lock()
_last_fetch_attempt: Dict[Tuple[str, str, str, str], float] = {}


def _decimal_to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rows_to_dicts(rows: Iterable[CryptoKline]) -> List[Dict[str, Any]]:
    data: List[Dict[str, Any]] = []
    for row in rows:
        close = _decimal_to_float(row.close_price)
        open_price = _decimal_to_float(row.open_price)
        high = _decimal_to_float(row.high_price)
        low = _decimal_to_float(row.low_price)
        if close is None or open_price is None or high is None or low is None:
            continue
        data.append(
            {
                "timestamp": int(row.timestamp),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": _decimal_to_float(row.volume) or 0.0,
                "amount": _decimal_to_float(row.amount),
            }
        )
    return data


def _query_local_klines(
    db: Session,
    exchange: str,
    symbol: str,
    period: str,
    environment: str,
    limit: int,
) -> List[CryptoKline]:
    return (
        db.query(CryptoKline)
        .filter(
            CryptoKline.exchange == exchange,
            CryptoKline.symbol == symbol,
            CryptoKline.market == "CRYPTO",
            CryptoKline.period == period,
            CryptoKline.environment == environment,
        )
        .order_by(desc(CryptoKline.timestamp))
        .limit(limit)
        .all()
    )


def _should_fetch(exchange: str, symbol: str, period: str, environment: str) -> bool:
    key = (exchange, symbol, period, environment)
    now = time.time()
    with _fetch_lock:
        last = _last_fetch_attempt.get(key, 0)
        if now - last < FETCH_COOLDOWN_SECONDS:
            return False
        _last_fetch_attempt[key] = now
        return True


def _fetch_binance_klines(
    db: Session,
    symbol: str,
    period: str,
    environment: str,
    limit: int,
) -> dict:
    adapter = BinanceAdapter(environment="mainnet")
    klines = adapter.fetch_klines(symbol, period, limit=limit)
    if not klines:
        return {"inserted": 0, "updated": 0, "fetched": 0}

    persistence = ExchangeDataPersistence(db)
    result = persistence.save_klines(klines, environment=environment)
    try:
        persistence.save_taker_volumes_from_klines(klines)
    except Exception as exc:
        logger.debug("Unable to persist Binance taker-volume backup for %s/%s: %s", symbol, period, exc)
    result["fetched"] = len(klines)
    return result


def _fetch_okx_klines(
    db: Session,
    symbol: str,
    period: str,
    environment: str,
    limit: int,
) -> dict:
    adapter = OKXAdapter(environment=environment)
    klines = adapter.fetch_klines(symbol, period, limit=limit)
    if not klines:
        return {"inserted": 0, "updated": 0, "fetched": 0}

    persistence = ExchangeDataPersistence(db)
    result = persistence.save_klines(klines, environment=environment)
    result["fetched"] = len(klines)
    return result


def ensure_indicator_klines(
    db: Session,
    symbol: str,
    period: str,
    indicators: Optional[List[str]] = None,
    exchange: str = "binance",
    environment: str = "mainnet",
    min_count: Optional[int] = None,
    limit: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], str, bool]:
    """
    Return enough candles for indicator calculation, fetching Binance public data if needed.

    Returns:
        (kline_dicts, source_exchange, fetched)
    """
    symbol = symbol.upper()
    exchange = (exchange or "binance").lower()
    environment = environment or "mainnet"
    required = max(min_count or 1, get_required_kline_count(indicators or []))
    query_limit = min(MAX_FETCH_LIMIT, max(limit or DEFAULT_LOOKBACK, required, DEFAULT_LOOKBACK))

    local_rows = _query_local_klines(db, exchange, symbol, period, environment, query_limit)
    if len(local_rows) >= required:
        return _rows_to_dicts(reversed(local_rows)), exchange, False

    fallback_exchange = "okx" if exchange == "okx" else "binance"
    supported_periods = SUPPORTED_OKX_PERIODS if fallback_exchange == "okx" else SUPPORTED_BINANCE_PERIODS
    if period not in supported_periods:
        logger.debug("No %s auto-fill for unsupported period %s", fallback_exchange, period)
        return _rows_to_dicts(reversed(local_rows)), exchange, False

    if _should_fetch(fallback_exchange, symbol, period, environment):
        try:
            if fallback_exchange == "okx":
                result = _fetch_okx_klines(db, symbol, period, environment, query_limit)
            else:
                result = _fetch_binance_klines(db, symbol, period, environment, query_limit)
            logger.info(
                "[KLineAutoFill] fetched %s klines for %s/%s: %s",
                fallback_exchange,
                symbol,
                period,
                result,
            )
        except Exception as exc:
            logger.warning("[KLineAutoFill] %s fetch failed for %s/%s: %s", fallback_exchange, symbol, period, exc)

    fallback_rows = _query_local_klines(db, fallback_exchange, symbol, period, environment, query_limit)
    if len(fallback_rows) >= required:
        return _rows_to_dicts(reversed(fallback_rows)), fallback_exchange, True

    if fallback_rows and len(fallback_rows) > len(local_rows):
        return _rows_to_dicts(reversed(fallback_rows)), fallback_exchange, True
    return _rows_to_dicts(reversed(local_rows)), exchange, False
