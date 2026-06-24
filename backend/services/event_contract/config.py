"""Defaults for the event-contract signal system.

Signal = order-flow CVD-fade (validated ~58-60% out-of-sample on Hyperliquid).
Per (symbol, expiry) params come from the backtest sweep + first/second-half
validation. Tweak here to retune the live signal.
"""
from __future__ import annotations

import os

SYMBOLS = ["BTC", "ETH"]
EXPIRIES = [5, 10]
# Binance is the default data source: its 1m klines carry taker buy/sell volume
# directly (CVD without a WS trade feed) and are reachable on this host.
# Override per deployment with EVENT_CONTRACT_EXCHANGE (e.g. okx, bybit).
DEFAULT_EXCHANGE = os.getenv("EVENT_CONTRACT_EXCHANGE", "binance")
DEFAULT_SIGNAL = "of_cvd_fade"
PAYOUT = 0.8                        # binary payout on win (breakeven win rate 55.6%)
DAILY_RESET_TZ = "Asia/Hong_Kong"  # panel resets at local midnight

# Per-cell params (window, thr) for of_cvd_fade, tuned on Binance 1m + taker
# order-flow (2026-06-17) with a first/second-half stability split:
#   BTC 5m  w45/thr2.5  -> 60.5% (h1 63.2 / h2 57.4), stable, net+
#   ETH 5m  w120/thr3.0 -> 63.9% (h1 70.0 / h2 56.7), stable, net+
#   ETH 10m w120/thr3.0 -> 60.0% (h1 62.9 / h2 56.7), stable, net+
#   BTC 10m -> NO stable edge on the current ~4-day sample for any (w,thr); set
#             to a high threshold to minimise exposure. Re-tune as data grows.
SIGNAL_PARAMS: dict[tuple[str, int], dict] = {
    ("BTC", 5): {"window": 45, "thr": 2.5},
    ("BTC", 10): {"window": 150, "thr": 3.5},
    ("ETH", 5): {"window": 120, "thr": 3.0},
    ("ETH", 10): {"window": 120, "thr": 3.0},
}


def params_for(symbol: str, expiry: int) -> dict:
    return SIGNAL_PARAMS.get((symbol, expiry), {"window": 30, "thr": 1.5})
