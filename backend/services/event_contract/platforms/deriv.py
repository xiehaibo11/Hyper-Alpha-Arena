"""Deriv adapter — binary options broker (Rise/Fall).

Supports crypto Rise/Fall with selectable durations including 5 and 10 minutes.
WebSocket API for proposal/buy/sell; auth via app_id + token (OAuth2/PAT).
"""
from __future__ import annotations

import os

from .base import EventContractPlatform, PlatformCapabilities


class DerivPlatform(EventContractPlatform):
    name = "deriv"
    capabilities = PlatformCapabilities(
        data=False,
        execution=True,
        durations=[5, 10],
        mode="broker",
        symbols=["BTC", "ETH"],
        notes="Rise/Fall binary, 5/10-min durations. WebSocket buy/sell. "
        "Needs DERIV_APP_ID + DERIV_API_TOKEN.",
    )

    def is_configured(self) -> bool:
        return bool(os.getenv("DERIV_APP_ID") and os.getenv("DERIV_API_TOKEN"))
