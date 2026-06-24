"""Order-flow signals & backtest for the event-contract system.

Uses market_trades_aggregated (15s taker buy/sell volume, notional, large-order
notional) — microstructure data that plain OHLCV can't see. Features are rolled
up to 1m bars; entry/settle prices come from 1m klines (timestamp lookup).
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

from database.connection import SessionLocal
from .data import CANDLE_SECONDS, load_klines


_OF_COLS = ["minute", "cvd", "buy_ratio", "large_imb", "volume"]


def _orderflow_from_klines_db(
    exchange: str, symbol: str, limit: int,
    start_ts: Optional[int], end_ts: Optional[int],
) -> pd.DataFrame:
    """Build 1m order-flow features from taker volume persisted in crypto_klines."""
    clauses = ["exchange = :ex", "symbol = :sym", "period = '1m'",
               "environment = 'mainnet'", "taker_buy_volume IS NOT NULL"]
    p: dict = {"ex": exchange, "sym": symbol, "lim": int(limit)}
    if start_ts is not None:
        clauses.append("timestamp >= :sts")
        p["sts"] = int(start_ts)
    if end_ts is not None:
        clauses.append("timestamp <= :ets")
        p["ets"] = int(end_ts)
    sql = text(
        f"""
        SELECT timestamp, taker_buy_volume, taker_sell_volume,
               taker_buy_notional, taker_sell_notional, volume
        FROM crypto_klines
        WHERE {' AND '.join(clauses)}
        ORDER BY timestamp DESC LIMIT :lim
        """
    )
    db = SessionLocal()
    try:
        rows = db.execute(sql, p).fetchall()
    finally:
        db.close()
    if not rows:
        return pd.DataFrame(columns=_OF_COLS)
    df = pd.DataFrame(rows, columns=["minute", "tbv", "tsv", "tbn", "tsn", "volume"])
    for c in ("tbv", "tsv", "tbn", "tsn", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["minute"] = df["minute"].astype("int64")
    df["cvd"] = df["tbv"] - df["tsv"]
    tot = (df["tbn"] + df["tsn"]).replace(0, np.nan)
    df["buy_ratio"] = df["tbn"] / tot
    df["large_imb"] = 0.0
    return (df[_OF_COLS].drop_duplicates("minute")
            .sort_values("minute").reset_index(drop=True))


def load_orderflow(
    exchange: str, symbol: str, limit: int = 60000,
    start_ts: Optional[int] = None, end_ts: Optional[int] = None,
) -> pd.DataFrame:
    """Load 15s aggregated trades rolled up to 1m order-flow features.

    start_ts/end_ts are in seconds (timestamp column is milliseconds).
    Columns: minute (int s), cvd, buy_ratio, large_imb, volume.

    When the exchange's klines carry taker buy/sell volume (e.g. Binance), derive
    the same features from 1m klines: prefer the persisted klines in crypto_klines
    (fast, long history for tuning), fall back to a live adapter REST fetch, and
    only then to the market_trades_aggregated WS pipeline (Hyperliquid-only).
    """
    from .orderflow_klines import load_orderflow_klines, supports_kline_orderflow
    if supports_kline_orderflow(exchange):
        dbdf = _orderflow_from_klines_db(exchange, symbol, limit, start_ts, end_ts)
        if len(dbdf) >= 120:
            return dbdf
        kdf = load_orderflow_klines(exchange, symbol, limit=limit,
                                    start_ts=start_ts, end_ts=end_ts)
        if not kdf.empty:
            return kdf

    clauses = ["exchange = :ex", "symbol = :sym"]
    p: dict = {"ex": exchange, "sym": symbol, "lim": limit}
    if start_ts is not None:
        clauses.append("timestamp >= :start_ms")
        p["start_ms"] = int(start_ts) * 1000
    if end_ts is not None:
        clauses.append("timestamp <= :end_ms")
        p["end_ms"] = int(end_ts) * 1000
    sql = text(
        f"""
        SELECT timestamp, taker_buy_volume, taker_sell_volume,
               taker_buy_notional, taker_sell_notional,
               large_buy_notional, large_sell_notional
        FROM market_trades_aggregated
        WHERE {' AND '.join(clauses)}
        ORDER BY timestamp DESC LIMIT :lim
        """
    )
    db = SessionLocal()
    try:
        rows = db.execute(sql, p).fetchall()
    finally:
        db.close()
    if not rows:
        return pd.DataFrame(columns=["minute", "cvd", "buy_ratio", "large_imb", "volume"])

    df = pd.DataFrame(rows, columns=[
        "ts", "buy_vol", "sell_vol", "buy_not", "sell_not", "lbuy", "lsell"])
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    # timestamp is milliseconds -> minute bucket in seconds
    df["minute"] = ((df["ts"] // 1000) // 60 * 60).astype("int64")
    g = df.groupby("minute").agg(
        buy_vol=("buy_vol", "sum"), sell_vol=("sell_vol", "sum"),
        buy_not=("buy_not", "sum"), sell_not=("sell_not", "sum"),
        lbuy=("lbuy", "sum"), lsell=("lsell", "sum"),
    ).reset_index().sort_values("minute").reset_index(drop=True)

    g["cvd"] = g["buy_vol"] - g["sell_vol"]
    tot_not = (g["buy_not"] + g["sell_not"]).replace(0, np.nan)
    g["buy_ratio"] = g["buy_not"] / tot_not
    g["large_imb"] = g["lbuy"] - g["lsell"]
    g["volume"] = g["buy_vol"] + g["sell_vol"]
    return g[["minute", "cvd", "buy_ratio", "large_imb", "volume"]]


# --- order-flow signal functions: (feat_df, params) -> 'long'|'short'|None ----

def of_cvd_trend(f: pd.DataFrame, p: dict) -> Optional[str]:
    """Aggressive taker flow continues: high CVD z-score -> long."""
    n, thr = p.get("window", 30), p.get("thr", 1.5)
    if len(f) < n + 1:
        return None
    cvd = f["cvd"]
    z = (cvd.iloc[-1] - cvd.rolling(n).mean().iloc[-1]) / (cvd.rolling(n).std().iloc[-1] or np.nan)
    if pd.isna(z):
        return None
    if z >= thr:
        return "long"
    if z <= -thr:
        return "short"
    return None


def of_cvd_fade(f: pd.DataFrame, p: dict) -> Optional[str]:
    """Fade exhausted aggressive flow: high CVD z-score -> short."""
    s = of_cvd_trend(f, p)
    return None if s is None else ("short" if s == "long" else "long")


def of_whale(f: pd.DataFrame, p: dict) -> Optional[str]:
    """Follow large-order (whale) imbalance."""
    n, thr = p.get("window", 30), p.get("thr", 1.5)
    if len(f) < n + 1:
        return None
    li = f["large_imb"]
    std = li.rolling(n).std().iloc[-1]
    if not std or pd.isna(std):
        return None
    z = (li.iloc[-1] - li.rolling(n).mean().iloc[-1]) / std
    if pd.isna(z):
        return None
    if z >= thr:
        return "long"
    if z <= -thr:
        return "short"
    return None


def of_taker_extreme(f: pd.DataFrame, p: dict) -> Optional[str]:
    """Extreme taker buy ratio -> follow (default) or fade."""
    hi, lo = p.get("hi", 0.65), p.get("lo", 0.35)
    fade = p.get("fade", False)
    r = f["buy_ratio"].iloc[-1]
    if pd.isna(r):
        return None
    if r >= hi:
        return "short" if fade else "long"
    if r <= lo:
        return "long" if fade else "short"
    return None


OF_SIGNALS: dict[str, Callable[[pd.DataFrame, dict], Optional[str]]] = {
    "of_cvd_trend": of_cvd_trend,
    "of_cvd_fade": of_cvd_fade,
    "of_whale": of_whale,
    "of_taker_follow": of_taker_extreme,
    "of_taker_fade": lambda f, p: of_taker_extreme(f, {**p, "fade": True}),
}

# Multi-agent consensus engine (framework borrowed from TradingAgents). Imported
# at the bottom so the OF signal functions above are already defined when the
# agents package wires them in — same pattern as strategies_advanced.
from .agents import agent_consensus as _agent_consensus  # noqa: E402

OF_SIGNALS["agent_consensus"] = _agent_consensus


def backtest_orderflow(
    exchange: str, symbol: str, expiry_minutes: int, signal: str,
    params: Optional[dict] = None, payout: float = 0.8,
    start_ts: Optional[int] = None, end_ts: Optional[int] = None,
) -> dict:
    fn = OF_SIGNALS.get(signal)
    if fn is None:
        raise ValueError(f"unknown order-flow signal: {signal}")
    feat = load_orderflow(exchange, symbol, start_ts=start_ts, end_ts=end_ts)
    kl = load_klines(exchange, symbol, start_ts=start_ts, end_ts=end_ts)
    if feat.empty or kl.empty:
        return {"signal": signal, "symbol": symbol, "expiry_minutes": expiry_minutes,
                "total": 0, "wins": 0, "win_rate": 0.0, "net_pnl": 0.0, "payout": payout}

    ts_open = dict(zip(kl["timestamp"].tolist(), kl["open"].tolist()))
    minutes = feat["minute"].tolist()
    expiry_s = expiry_minutes * 60
    total = wins = 0
    cum = 0.0
    # lookback must cover the signal's window (z-score over `window` bars); a
    # fixed 60 silently zeroes out any window > 60 — match the live simulator.
    lookback = max(60, int((params or {}).get("window", 30)) + 5)
    for i in range(lookback, len(feat)):
        sig = fn(feat.iloc[max(0, i - lookback): i + 1], params or {})
        if not sig:
            continue
        entry_ts = minutes[i] + CANDLE_SECONDS
        settle_ts = entry_ts + expiry_s
        ep, sp = ts_open.get(entry_ts), ts_open.get(settle_ts)
        if ep is None or sp is None:
            continue
        won = sp > ep if sig == "long" else sp < ep
        total += 1
        if won:
            wins += 1
            cum += payout
        else:
            cum -= 1.0
    return {
        "signal": signal, "symbol": symbol, "expiry_minutes": expiry_minutes,
        "total": total, "wins": wins,
        "win_rate": round(wins / total, 4) if total else 0.0,
        "net_pnl": round(cum, 4), "payout": payout,
    }


def compare_orderflow(exchange: str, symbol: str, expiry_minutes: int, **kw) -> list[dict]:
    res = [backtest_orderflow(exchange, symbol, expiry_minutes, s, **kw) for s in OF_SIGNALS]
    return sorted(res, key=lambda r: r["win_rate"], reverse=True)
