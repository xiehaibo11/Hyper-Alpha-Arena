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


def load_klines(
    exchange: str,
    symbol: str,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    limit: Optional[int] = None,
    environment: str = "mainnet",
) -> pd.DataFrame:
    """Load ascending 1m candles as a DataFrame.

    Columns: timestamp (int seconds), open, high, low, close, volume.
    Returns an empty DataFrame if no rows match.
    """
    clauses = [
        "exchange = :exchange",
        "symbol = :symbol",
        "period = '1m'",
        "environment = :environment",
    ]
    params: dict = {"exchange": exchange, "symbol": symbol, "environment": environment}
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
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["timestamp"] = df["timestamp"].astype("int64")
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
    return df
