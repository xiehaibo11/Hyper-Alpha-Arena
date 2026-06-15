"""Polymarket adapter — on-chain (Polygon/USDC) prediction market.

Offers 5-minute BTC/ETH/XRP "Up or Down" markets via the CLOB API.
Live trading needs a funded wallet + API credentials.
"""
from __future__ import annotations

import os

from .base import EventContractPlatform, PlatformCapabilities


class PolymarketPlatform(EventContractPlatform):
    name = "polymarket"
    capabilities = PlatformCapabilities(
        data=False,
        execution=True,
        durations=[5],
        mode="prediction",
        symbols=["BTC", "ETH", "XRP"],
        notes="On-chain Polygon/USDC. 5-min Up/Down. CLOB REST+WS. "
        "Needs wallet private key + API key/secret/passphrase.",
    )

    def is_configured(self) -> bool:
        return bool(
            os.getenv("POLYMARKET_API_KEY")
            and os.getenv("POLYMARKET_API_SECRET")
            and os.getenv("POLYMARKET_API_PASSPHRASE")
            and (os.getenv("POLYMARKET_WALLET_PRIVATE_KEY") or os.getenv("POLYMARKET_PROXY_ADDRESS"))
        )
