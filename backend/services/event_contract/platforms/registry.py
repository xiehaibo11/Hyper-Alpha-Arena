"""Registry of event-contract platforms and market-data sources.

- Execution platforms: can place real 5/10-min up/down orders (need creds).
- Data sources: exchanges whose 1m klines we already collect, used to drive
  signals and backtests (no order execution for binary contracts there).
"""
from __future__ import annotations

from typing import Optional

from .base import EventContractPlatform
from .deriv import DerivPlatform
from .kalshi import KalshiPlatform
from .polymarket import PolymarketPlatform

_EXECUTION_PLATFORMS: dict[str, EventContractPlatform] = {
    p.name: p for p in [DerivPlatform(), PolymarketPlatform(), KalshiPlatform()]
}

# Exchanges we already ingest 1m klines from (see crypto_klines.exchange).
DATA_SOURCES: list[dict] = [
    {
        "name": "binance", "mode": "cex", "data": True, "execution": False,
        "durations": [5, 10], "symbols": ["BTC", "ETH", "SOL", "BNB"],
        "configured": True, "notes": "1m klines for signals & backtest",
    },
    {
        "name": "hyperliquid", "mode": "cex", "data": True, "execution": False,
        "durations": [5, 10], "symbols": ["BTC", "ETH", "SOL"],
        "configured": True, "notes": "Richest/most-current 1m klines on this host",
    },
    {
        "name": "okx", "mode": "cex", "data": True, "execution": False,
        "durations": [5, 10], "symbols": ["BTC", "ETH", "SOL", "BNB"],
        "configured": True, "notes": "1m klines for signals & backtest",
    },
]


def list_execution_platforms() -> list[dict]:
    return [p.info() for p in _EXECUTION_PLATFORMS.values()]


def get_execution_platform(name: str) -> Optional[EventContractPlatform]:
    return _EXECUTION_PLATFORMS.get(name)


def list_data_sources() -> list[dict]:
    return DATA_SOURCES


def overview() -> dict:
    return {
        "execution_platforms": list_execution_platforms(),
        "data_sources": list_data_sources(),
    }
