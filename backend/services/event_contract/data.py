"""Shared 1m kline loading for the event-contract system.

Reads from crypto_klines (timestamp is Unix seconds, 1m spacing = 60s).
Used by both the backtest and the live simulator.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
from sqlalchemy import text

from database.connection import SessionLocal

CANDLE_SECONDS = 60


def _price_adapter(exchange: str):
    """Unified adapter for OHLCV price fallback when crypto_klines is empty."""
    ex = (exchange or "").lower()
    if ex == "binance":
        from services.exchanges.binance_adapter import BinanceAdapter
        return BinanceAdapter()
    if ex == "okx":
        from services.exchanges.okx_adapter import OKXAdapter
        return OKXAdapter()
    if ex in ("crypto_com", "cryptocom", "crypto.com"):
        from services.exchanges.crypto_com_adapter import CryptoComAdapter
        return CryptoComAdapter()
    if ex in ("gate", "gateio", "gate.io", "gate_io"):
        from services.exchanges.gate_adapter import GateAdapter
        return GateAdapter()
    return None


def _klines_from_adapter(
    exchange: str, symbol: str, start_ts, end_ts, limit, period: str
) -> pd.DataFrame:
    """Fetch OHLCV straight from the exchange adapter (REST) as a DB fallback."""
    ad = _price_adapter(exchange)
    if ad is None:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    try:
        kls = ad.fetch_klines(
            symbol, period, limit=min(int(limit or 1500), 1500),
            start_time=int(start_ts) * 1000 if start_ts else None,
            end_time=int(end_ts) * 1000 if end_ts else None,
        )
    except Exception:
        kls = []
    rows = [{
        "timestamp": int(k.timestamp), "open": float(k.open_price),
        "high": float(k.high_price), "low": float(k.low_price),
        "close": float(k.close_price), "volume": float(k.volume),
    } for k in kls]
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows)
    return df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def load_klines(
    exchange: str,
    symbol: str,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    limit: Optional[int] = None,
    environment: str = "mainnet",
    period: str = "1m",
) -> pd.DataFrame:
    """Load ascending candles as a DataFrame.

    `period` selects the candle size (default '1m' for signals; use '1d'/'1h'
    for the historical chart). Columns: timestamp (int seconds), open, high,
    low, close, volume. Returns an empty DataFrame if no rows match.
    """
    clauses = [
        "exchange = :exchange",
        "symbol = :symbol",
        "period = :period",
        "environment = :environment",
    ]
    params: dict = {"exchange": exchange, "symbol": symbol,
                    "environment": environment, "period": period}
    if start_ts is not None:
        clauses.append("timestamp >= :start_ts")
        params["start_ts"] = int(start_ts)
    if end_ts is not None:
        clauses.append("timestamp <= :end_ts")
        params["end_ts"] = int(end_ts)

    where = " AND ".join(clauses)
    # Newest-first with optional limit, then we re-sort ascending below.
    limit_sql = f" LIMIT {int(limit)}" if limit else ""
    sql = text(
        f"""
        SELECT timestamp,
               open_price  AS open,
               high_price  AS high,
               low_price   AS low,
               close_price AS close,
               volume      AS volume
        FROM crypto_klines
        WHERE {where}
        ORDER BY timestamp DESC{limit_sql}
        """
    )

    db = SessionLocal()
    try:
        rows = db.execute(sql, params).fetchall()
    finally:
        db.close()

    if not rows:
        # DB has no candles for this cell yet — fall back to the exchange adapter
        # (REST) so signals/backtests work before the collector has backfilled.
        return _klines_from_adapter(exchange, symbol, start_ts, end_ts, limit, period)

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["timestamp"] = df["timestamp"].astype("int64")
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
    return df
