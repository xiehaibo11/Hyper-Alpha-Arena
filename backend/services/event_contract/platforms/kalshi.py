"""Kalshi adapter — US-regulated event-contract exchange.

Crypto Up/Down markets at 15-minute and hourly frequencies (not 5/10-min).
REST + WebSocket + FIX; auth via API key id + RSA private key. KYC required.
"""
from __future__ import annotations

import os

from .base import EventContractPlatform, PlatformCapabilities


class KalshiPlatform(EventContractPlatform):
    name = "kalshi"
    capabilities = PlatformCapabilities(
        data=False,
        execution=True,
        durations=[15, 60],
        mode="prediction",
        symbols=["BTC", "ETH", "SOL", "XRP"],
        notes="US-regulated, KYC. Shortest crypto Up/Down is 15-min (not 5/10). "
        "Needs KALSHI_API_KEY_ID + KALSHI_PRIVATE_KEY (RSA).",
    )

    def is_configured(self) -> bool:
        return bool(os.getenv("KALSHI_API_KEY_ID") and os.getenv("KALSHI_PRIVATE_KEY"))
