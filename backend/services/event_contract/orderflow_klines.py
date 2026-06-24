"""Derive order-flow features directly from 1m klines' taker volume.

A robust, multi-exchange alternative to the market_trades_aggregated WebSocket
pipeline: any exchange whose adapter fills ``UnifiedKline.taker_buy_volume``
(Binance does, at 1m granularity) yields CVD / buy_ratio from a plain REST call,
with no WS trade collector and no DB dependency.

Output columns match ``orderflow.load_orderflow`` exactly so the signal
functions are agnostic to the source:
    minute (int seconds), cvd, buy_ratio, large_imb, volume
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

_COLS = ["minute", "cvd", "buy_ratio", "large_imb", "volume"]
_MAX_PAGES = 40  # safety cap on backward/forward paging (40 * 1500 = 60k bars)


def _adapter(exchange: str):
    """Return a unified adapter whose fetch_klines fills taker_* fields, else None."""
    ex = (exchange or "").lower()
    if ex == "binance":
        from services.exchanges.binance_adapter import BinanceAdapter
        return BinanceAdapter()
    return None


def supports_kline_orderflow(exchange: str) -> bool:
    """True when this exchange's klines carry taker buy/sell volume for CVD."""
    return _adapter(exchange) is not None


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLS)


def _to_rows(klines) -> list[dict]:
    rows: list[dict] = []
    for k in klines:
        if k.taker_buy_volume is None or k.taker_sell_volume is None:
            continue
        tb = float(k.taker_buy_volume)
        ts_ = float(k.taker_sell_volume)
        bn = float(k.taker_buy_notional or 0.0)
        sn = float(k.taker_sell_notional or 0.0)
        tot = bn + sn
        rows.append({
            "minute": int(k.timestamp),
            "cvd": tb - ts_,                       # net aggressive taker volume
            "buy_ratio": (bn / tot) if tot else np.nan,
            "large_imb": 0.0,                      # no large-order data in klines
            "volume": float(k.volume),
        })
    return rows


def load_orderflow_klines(
    exchange: str, symbol: str, limit: int = 1500,
    start_ts: Optional[int] = None, end_ts: Optional[int] = None,
) -> pd.DataFrame:
    """Build 1m order-flow features from adapter klines (REST, taker-volume based).

    With a [start_ts, end_ts] range (backtest), pages forward through the range.
    Without a range (live), fetches the most recent ``limit`` 1m bars (paging
    backward when limit > 1500).
    """
    ad = _adapter(exchange)
    if ad is None:
        return _empty()

    rows: list[dict] = []
    seen: set[int] = set()
    try:
        if start_ts is not None:
            cursor = int(start_ts) * 1000
            end_ms = int(end_ts) * 1000 if end_ts is not None else None
            for _ in range(_MAX_PAGES):
                batch = ad.fetch_klines(symbol, "1m", limit=1500,
                                        start_time=cursor, end_time=end_ms)
                if not batch:
                    break
                fresh = [k for k in batch if int(k.timestamp) not in seen]
                if not fresh:
                    break
                for k in fresh:
                    seen.add(int(k.timestamp))
                rows.extend(_to_rows(fresh))
                newest = max(int(k.timestamp) for k in batch)
                cursor = (newest + 60) * 1000
                if len(batch) < 1500 or (end_ms and cursor >= end_ms):
                    break
        else:
            # cap REST paging for the "recent N" (live / rangeless) path so a
            # large default limit can't trigger runaway pagination.
            target = min(int(limit), 5000)
            cur_end: Optional[int] = None
            for _ in range(_MAX_PAGES):
                batch = ad.fetch_klines(symbol, "1m", limit=1500, end_time=cur_end)
                if not batch:
                    break
                fresh = [k for k in batch if int(k.timestamp) not in seen]
                if not fresh:
                    break
                for k in fresh:
                    seen.add(int(k.timestamp))
                rows.extend(_to_rows(fresh))
                if len(seen) >= target or len(batch) < 1500:
                    break
                oldest = min(int(k.timestamp) for k in batch)
                cur_end = oldest * 1000 - 1
    except Exception:
        if not rows:
            return _empty()

    if not rows:
        return _empty()
    df = pd.DataFrame(rows, columns=_COLS)
    return df.drop_duplicates("minute").sort_values("minute").reset_index(drop=True)
