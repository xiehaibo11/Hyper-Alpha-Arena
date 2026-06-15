"""Defaults for the event-contract signal system.

Signal = order-flow CVD-fade (validated ~58-60% out-of-sample on Hyperliquid).
Per (symbol, expiry) params come from the backtest sweep + first/second-half
validation. Tweak here to retune the live signal.
"""
from __future__ import annotations

SYMBOLS = ["BTC", "ETH"]
EXPIRIES = [5, 10]
DEFAULT_EXCHANGE = "hyperliquid"   # richest 1m + order-flow data on this host
DEFAULT_SIGNAL = "of_cvd_fade"
PAYOUT = 0.8                        # binary payout on win (breakeven win rate 55.6%)
DAILY_RESET_TZ = "Asia/Hong_Kong"  # panel resets at local midnight

# Validated per-cell params (window, thr) for of_cvd_fade.
SIGNAL_PARAMS: dict[tuple[str, int], dict] = {
    ("BTC", 5): {"window": 45, "thr": 1.5},
    ("BTC", 10): {"window": 45, "thr": 1.25},
    ("ETH", 5): {"window": 30, "thr": 2.0},
    ("ETH", 10): {"window": 20, "thr": 2.5},
}


def params_for(symbol: str, expiry: int) -> dict:
    return SIGNAL_PARAMS.get((symbol, expiry), {"window": 30, "thr": 1.5})
