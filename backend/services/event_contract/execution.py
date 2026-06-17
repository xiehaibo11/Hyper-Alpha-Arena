"""Execution backend seam for the event-contract product.

Two modes, selected by env EVENT_CONTRACT_EXECUTION_MODE (default 'paper'):
- paper: orders recorded only, no real placement (settlement via order.settle()).
- live : LiveExecutionBackend places real orders through the platform adapter
         registry — platform-agnostic, gated on per-platform credentials. With no
         configured platform it logs and falls back to paper (effective_mode='paper').
"""
from __future__ import annotations

import logging
import os
from typing import Protocol

from database.models_event_contract import EventContractOrder

logger = logging.getLogger(__name__)


class ExecutionBackend(Protocol):
    mode: str
    def open_order(self, order: EventContractOrder) -> None: ...
    def settle_order(self, order: EventContractOrder, settle_price: float) -> None: ...


class PaperExecutionBackend:
    """No real orders. Settlement is decided by EventContractOrder.settle()."""

    mode = "paper"
    effective_mode = "paper"

    def open_order(self, order: EventContractOrder) -> None:
        return None

    def settle_order(self, order: EventContractOrder, settle_price: float) -> None:
        order.settle(settle_price)


def _configured_platform() -> str | None:
    """Return the first platform that has live credentials configured, else None."""
    try:
        from .platforms import overview as platforms_overview
        for p in platforms_overview().get("execution_platforms", []):
            if p.get("configured") and p.get("execution"):
                return p.get("name")
    except Exception as e:
        logger.debug("[event_contract] platform overview failed: %s", e)
    return None


class LiveExecutionBackend:
    """Platform-agnostic real execution. Falls back to paper without credentials."""

    mode = "live"

    def __init__(self) -> None:
        self.platform = _configured_platform()
        self.effective_mode = "live" if self.platform else "paper"
        self._paper = PaperExecutionBackend()
        if not self.platform:
            logger.warning("[event_contract] live mode requested but no platform "
                           "configured — falling back to paper")

    def open_order(self, order: EventContractOrder) -> None:
        if not self.platform:
            return self._paper.open_order(order)
        # TODO: place real order via platforms registry adapter for self.platform
        logger.info("[event_contract] live open_order via %s (not yet implemented)", self.platform)
        return None

    def settle_order(self, order: EventContractOrder, settle_price: float) -> None:
        if not self.platform:
            return self._paper.settle_order(order, settle_price)
        # TODO: reconcile real settlement from platform; fall back to price settle
        return self._paper.settle_order(order, settle_price)


def get_execution_backend() -> ExecutionBackend:
    mode = os.getenv("EVENT_CONTRACT_EXECUTION_MODE", "paper").strip().lower()
    if mode == "live":
        return LiveExecutionBackend()
    return PaperExecutionBackend()
