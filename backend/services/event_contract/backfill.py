"""Persist 1m klines (with taker volume) into crypto_klines.

This is the storage foundation for serious signal tuning: once Binance 1m bars
— including taker buy/sell volume/notional — are in the DB, order-flow backtests
read straight from Postgres instead of paging the exchange REST API every call.

Only exchanges whose adapter fills UnifiedKline.taker_* (currently Binance) are
backfilled with order-flow; others would store OHLCV-only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from database.connection import SessionLocal
from . import config as ec_config
from .orderflow_klines import _adapter

logger = logging.getLogger(__name__)

_UPSERT = text(
    """
    INSERT INTO crypto_klines
      (exchange, symbol, market, period, timestamp, datetime_str, environment,
       open_price, high_price, low_price, close_price, volume,
       taker_buy_volume, taker_sell_volume, taker_buy_notional, taker_sell_notional)
    VALUES
      (:exchange, :symbol, 'CRYPTO', :period, :timestamp, :datetime_str, 'mainnet',
       :open, :high, :low, :close, :volume, :tbv, :tsv, :tbn, :tsn)
    ON CONFLICT (exchange, symbol, market, period, timestamp, environment)
    DO UPDATE SET
       open_price=EXCLUDED.open_price, high_price=EXCLUDED.high_price,
       low_price=EXCLUDED.low_price, close_price=EXCLUDED.close_price,
       volume=EXCLUDED.volume,
       taker_buy_volume=EXCLUDED.taker_buy_volume,
       taker_sell_volume=EXCLUDED.taker_sell_volume,
       taker_buy_notional=EXCLUDED.taker_buy_notional,
       taker_sell_notional=EXCLUDED.taker_sell_notional
    """
)


def _row(exchange: str, symbol: str, period: str, k) -> dict:
    dt = datetime.fromtimestamp(int(k.timestamp), tz=timezone.utc)

    def _f(v):
        return float(v) if v is not None else None

    return {
        "exchange": exchange, "symbol": symbol, "period": period,
        "timestamp": int(k.timestamp),
        "datetime_str": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "open": float(k.open_price), "high": float(k.high_price),
        "low": float(k.low_price), "close": float(k.close_price),
        "volume": float(k.volume),
        "tbv": _f(k.taker_buy_volume), "tsv": _f(k.taker_sell_volume),
        "tbn": _f(k.taker_buy_notional), "tsn": _f(k.taker_sell_notional),
    }


def backfill_symbol(exchange: str, symbol: str, bars: int = 5000,
                    period: str = "1m", fetch_limit: int = 1500) -> int:
    """Page backward from now, upserting up to ``bars`` candles with taker data.

    ``fetch_limit`` bounds the per-request batch size — small for incremental
    refresh (just the newest bars), large (1500) for a deep historical backfill.
    """
    ad = _adapter(exchange)
    if ad is None:
        return 0
    written = 0
    seen: set[int] = set()
    cur_end = None
    page_size = max(1, min(int(fetch_limit), 1500))
    pages = max(1, (int(bars) + page_size - 1) // page_size)
    db = SessionLocal()
    try:
        for _ in range(pages):
            batch = ad.fetch_klines(symbol, period, limit=page_size, end_time=cur_end)
            if not batch:
                break
            fresh = [k for k in batch if int(k.timestamp) not in seen]
            if not fresh:
                break
            for k in fresh:
                seen.add(int(k.timestamp))
                db.execute(_UPSERT, _row(exchange, symbol, period, k))
                written += 1
            cur_end = min(int(k.timestamp) for k in batch) * 1000 - 1
            if len(batch) < page_size or len(seen) >= bars:
                break
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"[event_contract] backfill {exchange}/{symbol} error: {e}")
    finally:
        db.close()
    return written


def backfill_all(bars: int = 5000, exchange: str | None = None, period: str = "1m") -> dict:
    """Backfill every configured event-contract symbol. Returns {symbol: written}."""
    ex = exchange or ec_config.DEFAULT_EXCHANGE
    return {sym: backfill_symbol(ex, sym, bars=bars, period=period)
            for sym in ec_config.SYMBOLS}


def refresh_recent(exchange: str | None = None, period: str = "1m", bars: int = 10) -> dict:
    """Keep the DB fresh: upsert just the latest few 1m bars (incremental updater)."""
    ex = exchange or ec_config.DEFAULT_EXCHANGE
    return {sym: backfill_symbol(ex, sym, bars=bars, period=period, fetch_limit=bars)
            for sym in ec_config.SYMBOLS}
