"""Advanced, more selective strategies for the event-contract system.

Goal: push binary up/down win rate above the ~50% baseline by being pickier —
multi-factor confluence, volatility-regime filtering, and order-flow proxies
derived from OHLCV. Registered into the shared STRATEGIES registry.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .strategies import Direction, Strategy, _ema, _rsi, register


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def extreme_reversion(df: pd.DataFrame, params: dict) -> Direction:
    """Fade only *extreme* RSI readings backed by an outsized candle."""
    period = params.get("period", 14)
    low, high = params.get("low", 20), params.get("high", 80)
    body_atr = params.get("body_atr", 1.2)
    c = df["close"].astype(float)
    if len(c) < period + 2:
        return None
    r = _rsi(c, period).iloc[-1]
    atr = _atr(df, period).iloc[-1]
    if pd.isna(r) or pd.isna(atr) or atr == 0:
        return None
    body = abs(float(df["close"].iloc[-1]) - float(df["open"].iloc[-1]))
    if body < body_atr * atr:
        return None
    if r <= low:
        return "long"
    if r >= high:
        return "short"
    return None


def zscore_reversion(df: pd.DataFrame, params: dict) -> Direction:
    """Fade price when it deviates >thr standard deviations from its mean."""
    n = params.get("window", 20)
    thr = params.get("thr", 2.0)
    c = df["close"].astype(float)
    if len(c) < n + 1:
        return None
    mean = c.rolling(n).mean().iloc[-1]
    std = c.rolling(n).std().iloc[-1]
    if pd.isna(std) or std == 0:
        return None
    z = (c.iloc[-1] - mean) / std
    if z <= -thr:
        return "long"
    if z >= thr:
        return "short"
    return None


def confluence(df: pd.DataFrame, params: dict) -> Direction:
    """Multi-factor: trend + RSI pullback + last-candle body must all agree."""
    slow = params.get("slow", 50)
    rsi_p = params.get("rsi_period", 7)
    pull_long = params.get("pull_long", 40)
    pull_short = params.get("pull_short", 60)
    c = df["close"].astype(float)
    if len(c) < slow + 3:
        return None
    es = _ema(c, slow)
    up = es.iloc[-1] > es.iloc[-3]
    down = es.iloc[-1] < es.iloc[-3]
    r = _rsi(c, rsi_p).iloc[-1]
    if pd.isna(r):
        return None
    bull_candle = float(df["close"].iloc[-1]) > float(df["open"].iloc[-1])
    if up and r <= pull_long and bull_candle:
        return "long"
    if down and r >= pull_short and not bull_candle:
        return "short"
    return None


def range_reversion(df: pd.DataFrame, params: dict) -> Direction:
    """Mean-revert only in a low-volatility (range-bound) regime."""
    n = params.get("window", 20)
    k = params.get("band_k", 2.0)
    c = df["close"].astype(float)
    if len(c) < n * 3:
        return None
    mean = c.rolling(n).mean()
    std = c.rolling(n).std()
    width = (std / mean)
    # regime: current band width below its recent median => range-bound
    if pd.isna(width.iloc[-1]) or width.iloc[-1] > width.rolling(n * 2).median().iloc[-1]:
        return None
    upper = mean.iloc[-1] + k * std.iloc[-1]
    lower = mean.iloc[-1] - k * std.iloc[-1]
    price = c.iloc[-1]
    if price <= lower:
        return "long"
    if price >= upper:
        return "short"
    return None


def momentum_burst(df: pd.DataFrame, params: dict) -> Direction:
    """Order-flow proxy: N consecutive same-direction candles + volume surge."""
    run = params.get("run", 3)
    vol_k = params.get("vol_k", 1.5)
    vol_n = params.get("vol_n", 20)
    if len(df) < max(run, vol_n) + 1:
        return None
    closes = df["close"].astype(float)
    opens = df["open"].astype(float)
    last = df.iloc[-run:]
    bull = all(last["close"].values > last["open"].values)
    bear = all(last["close"].values < last["open"].values)
    vol = df["volume"].astype(float)
    vol_ma = vol.rolling(vol_n).mean().iloc[-1]
    if pd.isna(vol_ma) or vol_ma == 0 or vol.iloc[-1] < vol_k * vol_ma:
        return None
    if bull:
        return "long"
    if bear:
        return "short"
    return None


for _s in [
    Strategy("extreme_reversion", "Fade extreme RSI + outsized candle", extreme_reversion,
             {"period": 14, "low": 20, "high": 80, "body_atr": 1.2}, min_rows=20),
    Strategy("zscore_reversion", "Fade >thr sigma deviation", zscore_reversion,
             {"window": 20, "thr": 2.0}, min_rows=25),
    Strategy("confluence", "Trend + RSI pullback + body agreement", confluence,
             {"slow": 50, "rsi_period": 7, "pull_long": 40, "pull_short": 60}, min_rows=55),
    Strategy("range_reversion", "Range-regime band reversion", range_reversion,
             {"window": 20, "band_k": 2.0}, min_rows=60),
    Strategy("momentum_burst", "Consecutive candles + volume surge", momentum_burst,
             {"run": 3, "vol_k": 1.5, "vol_n": 20}, min_rows=25),
]:
    register(_s)
