"""Unified event-contract platform adapter interface.

Two kinds of capability:
- data: can supply the underlying price / klines for signals & backtest.
- execution: can place a real 5/10-min up/down (binary) order and settle it.

Live order placement requires per-platform credentials supplied by the operator
(env vars). Without them, adapters report not-configured and refuse to trade.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


class NotConfigured(Exception):
    """Raised when a platform action needs credentials that are not set."""


@dataclass
class PlatformCapabilities:
    data: bool                      # provides price/kline data
    execution: bool                 # can place real up/down orders
    durations: list[int]            # supported expiry minutes (e.g. [5, 10])
    mode: str                       # 'cex' | 'prediction' | 'broker'
    symbols: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class PlacedOrder:
    platform: str
    order_ref: str
    symbol: str
    direction: str                  # 'long' | 'short'
    expiry_minutes: int
    stake: float
    raw: dict = field(default_factory=dict)


class EventContractPlatform(ABC):
    """Base class every platform adapter implements."""

    name: str = "base"
    capabilities: PlatformCapabilities

    @abstractmethod
    def is_configured(self) -> bool:
        """True when credentials for live actions are present."""

    # ----- data (optional) -------------------------------------------------
    def get_underlying_price(self, symbol: str) -> Optional[float]:
        """Latest underlying price, if this platform can provide it."""
        return None

    def list_markets(self, symbol: str, expiry_minutes: int) -> list[dict]:
        """Open up/down markets for symbol+expiry, if applicable."""
        return []

    # ----- execution (gated on credentials) --------------------------------
    def place_order(
        self, symbol: str, direction: str, expiry_minutes: int, stake: float
    ) -> PlacedOrder:
        raise NotConfigured(
            f"{self.name}: live order placement requires credentials. "
            f"Set the platform's API keys, then enable execution explicitly."
        )

    def get_order_result(self, order_ref: str) -> dict:
        raise NotConfigured(f"{self.name}: not configured for execution.")

    # ----- metadata --------------------------------------------------------
    def info(self) -> dict:
        c = self.capabilities
        return {
            "name": self.name,
            "mode": c.mode,
            "data": c.data,
            "execution": c.execution,
            "durations": c.durations,
            "symbols": c.symbols,
            "configured": self.is_configured(),
            "notes": c.notes,
        }
