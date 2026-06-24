"""Pluggable directional strategies for the event-contract signal system.

Each strategy looks at a window of *closed* 1m candles (ascending by time, the
last row being the just-closed candle) and returns 'long', 'short', or None.
Strategies use only OHLCV so they work across any exchange's 1m klines.

Add a new strategy by writing a function and registering it in STRATEGIES.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd

Direction = Optional[str]  # 'long' | 'short' | None


@dataclass
class Strategy:
    name: str
    description: str
    fn: Callable[[pd.DataFrame, dict], Direction]
    default_params: dict = field(default_factory=dict)
    min_rows: int = 60  # candles of history required


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

def ema_cross(df: pd.DataFrame, params: dict) -> Direction:
    """Trend/momentum: fast EMA vs slow EMA on close."""
    fast, slow = params.get("fast", 9), params.get("slow", 21)
    c = df["close"].astype(float)
    ef, es = _ema(c, fast), _ema(c, slow)
    if len(c) < slow + 1:
        return None
    if ef.iloc[-1] > es.iloc[-1] and c.iloc[-1] > c.iloc[-2]:
        return "long"
    if ef.iloc[-1] < es.iloc[-1] and c.iloc[-1] < c.iloc[-2]:
        return "short"
    return None


def rsi_reversion(df: pd.DataFrame, params: dict) -> Direction:
    """Mean reversion: oversold -> long, overbought -> short."""
    period = params.get("period", 14)
    low, high = params.get("low", 30), params.get("high", 70)
    c = df["close"].astype(float)
    if len(c) < period + 1:
        return None
    r = _rsi(c, period).iloc[-1]
    if pd.isna(r):
        return None
    if r <= low:
        return "long"
    if r >= high:
        return "short"
    return None


def donchian_breakout(df: pd.DataFrame, params: dict) -> Direction:
    """Breakout: close breaks the prior N-candle high/low range."""
    n = params.get("window", 20)
    if len(df) < n + 1:
        return None
    prior = df.iloc[-(n + 1):-1]
    c = float(df["close"].iloc[-1])
    if c > float(prior["high"].max()):
        return "long"
    if c < float(prior["low"].min()):
        return "short"
    return None


def trend_pullback(df: pd.DataFrame, params: dict) -> Direction:
    """Higher-quality combo: trade pullbacks in the direction of the trend.

    Trend from slow EMA slope; entry when a short RSI dips/pops against trend.
    Fires less often but aims for a higher hit-rate (toward the 66% target).
    """
    slow = params.get("slow", 50)
    rsi_p = params.get("rsi_period", 7)
    pull_long = params.get("pull_long", 45)
    pull_short = params.get("pull_short", 55)
    c = df["close"].astype(float)
    if len(c) < slow + 2:
        return None
    es = _ema(c, slow)
    up = es.iloc[-1] > es.iloc[-3]
    down = es.iloc[-1] < es.iloc[-3]
    r = _rsi(c, rsi_p).iloc[-1]
    if pd.isna(r):
        return None
    if up and r <= pull_long:
        return "long"
    if down and r >= pull_short:
        return "short"
    return None


STRATEGIES: dict[str, Strategy] = {
    s.name: s
    for s in [
        Strategy("ema_cross", "EMA fast/slow momentum", ema_cross,
                 {"fast": 9, "slow": 21}, min_rows=30),
        Strategy("rsi_reversion", "RSI oversold/overbought reversion", rsi_reversion,
                 {"period": 14, "low": 30, "high": 70}, min_rows=20),
        Strategy("donchian_breakout", "N-candle range breakout", donchian_breakout,
                 {"window": 20}, min_rows=25),
        Strategy("trend_pullback", "Trend-following pullback (higher quality)", trend_pullback,
                 {"slow": 50, "rsi_period": 7, "pull_long": 45, "pull_short": 55}, min_rows=55),
    ]
}


def register(strategy: Strategy) -> None:
    """Register a strategy (used by strategies_advanced)."""
    STRATEGIES[strategy.name] = strategy


def list_strategies() -> list[dict]:
    return [
        {"name": s.name, "description": s.description, "default_params": s.default_params}
        for s in STRATEGIES.values()
    ]


def evaluate(name: str, df: pd.DataFrame, params: dict | None = None) -> Direction:
    """Run a registered strategy on a window of closed 1m candles."""
    strat = STRATEGIES.get(name)
    if strat is None:
        raise ValueError(f"Unknown strategy: {name}")
    if df is None or len(df) < strat.min_rows:
        return None
    merged = {**strat.default_params, **(params or {})}
    return strat.fn(df, merged)


# Register advanced strategies (import after registry/helpers are defined).
from . import strategies_advanced  # noqa: E402,F401
