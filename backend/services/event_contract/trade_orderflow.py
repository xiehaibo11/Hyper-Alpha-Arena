"""Trade-aggregation order-flow for exchanges without kline taker splits.

Crypto.com and Gate.io publish no taker buy/sell volume on their candles, so we
reconstruct CVD from the public per-trade feed: pull recent taker trades, bucket
them by minute, and UPSERT taker buy/sell volume + notional into
market_trades_aggregated. The event-contract `load_orderflow` SQL path then reads
that table and CVD works for these exchanges just like Binance.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from database.connection import SessionLocal

logger = logging.getLogger(__name__)


def _adapter(exchange):
    ex = (exchange or "").lower()
    if ex in ("crypto_com", "cryptocom"):
        from services.exchanges.crypto_com_adapter import CryptoComAdapter
        return CryptoComAdapter()
    if ex in ("gate", "gateio"):
        from services.exchanges.gate_adapter import GateAdapter
        return GateAdapter()
    return None


def supports_trade_orderflow(exchange) -> bool:
    return _adapter(exchange) is not None


def aggregate_trades(trades: list[dict]) -> dict:
    """Bucket taker trades by minute.

    Returns {minute_ms: {tbv, tsv, tbc, tsc, tbn, tsn, high, low}} where the
    minute key is the floored start-of-minute in milliseconds. Buy-side taker
    trades feed tbv/tbn/tbc, sell-side feed tsv/tsn/tsc.
    """
    buckets: dict[int, dict] = {}
    for t in trades or []:
        try:
            ts_ms = int(t["ts_ms"])
            price = float(t["price"])
            size = float(t["size"])
            notional = float(t.get("notional", size * price))
            side = str(t.get("side", "")).lower()
        except (KeyError, TypeError, ValueError):
            continue
        minute_ms = (ts_ms // 60000) * 60000
        b = buckets.get(minute_ms)
        if b is None:
            b = {"tbv": 0.0, "tsv": 0.0, "tbc": 0, "tsc": 0,
                 "tbn": 0.0, "tsn": 0.0, "high": price, "low": price}
            buckets[minute_ms] = b
        if side == "buy":
            b["tbv"] += size
            b["tbn"] += notional
            b["tbc"] += 1
        else:
            b["tsv"] += size
            b["tsn"] += notional
            b["tsc"] += 1
        if price > b["high"]:
            b["high"] = price
        if price < b["low"]:
            b["low"] = price
    return buckets


_UPSERT = text(
    """
    INSERT INTO market_trades_aggregated
        (exchange, symbol, timestamp, taker_buy_volume, taker_sell_volume,
         taker_buy_count, taker_sell_count, taker_buy_notional, taker_sell_notional,
         vwap, high_price, low_price, large_buy_notional, large_sell_notional,
         large_buy_count, large_sell_count)
    VALUES
        (:ex, :sym, :ts, :tbv, :tsv, :tbc, :tsc, :tbn, :tsn,
         :vwap, :high, :low, 0, 0, 0, 0)
    ON CONFLICT (exchange, symbol, timestamp) DO UPDATE SET
        taker_buy_volume = EXCLUDED.taker_buy_volume,
        taker_sell_volume = EXCLUDED.taker_sell_volume,
        taker_buy_count = EXCLUDED.taker_buy_count,
        taker_sell_count = EXCLUDED.taker_sell_count,
        taker_buy_notional = EXCLUDED.taker_buy_notional,
        taker_sell_notional = EXCLUDED.taker_sell_notional,
        vwap = EXCLUDED.vwap,
        high_price = EXCLUDED.high_price,
        low_price = EXCLUDED.low_price
    """
)


def poll_and_store(exchange: str, symbol: str) -> int:
    """Fetch recent trades, aggregate per minute, UPSERT into the agg table.

    `symbol` is the internal format (BTC/ETH). Returns the number of minute
    buckets written. Never raises — returns 0 on any error.
    """
    try:
        ad = _adapter(exchange)
        if ad is None:
            return 0
        trades = ad.fetch_trades(symbol, limit=1000)
        buckets = aggregate_trades(trades)
        if not buckets:
            return 0
        ex_l = (exchange or "").lower()
        db = SessionLocal()
        try:
            for minute_ms, b in buckets.items():
                vol = b["tbv"] + b["tsv"]
                notion = b["tbn"] + b["tsn"]
                vwap = (notion / vol) if vol else 0.0
                db.execute(_UPSERT, {
                    "ex": ex_l, "sym": symbol, "ts": int(minute_ms),
                    "tbv": b["tbv"], "tsv": b["tsv"],
                    "tbc": b["tbc"], "tsc": b["tsc"],
                    "tbn": b["tbn"], "tsn": b["tsn"],
                    "vwap": vwap, "high": b["high"], "low": b["low"],
                })
            db.commit()
            return len(buckets)
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"[event_contract] poll_and_store failed {exchange}/{symbol}: {e}")
        return 0
