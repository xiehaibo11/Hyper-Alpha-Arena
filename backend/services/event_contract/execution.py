"""Execution backend seam for the event-contract product.

Phase 1 ships only the paper (simulation) backend — orders are recorded, not
sent to any exchange. A future LiveExecutionBackend can implement the same
Protocol and be returned by get_execution_backend() without touching simulator.
"""
from __future__ import annotations

from typing import Protocol

from database.models_event_contract import EventContractOrder


class ExecutionBackend(Protocol):
    def open_order(self, order: EventContractOrder) -> None: ...
    def settle_order(self, order: EventContractOrder, settle_price: float) -> None: ...


class PaperExecutionBackend:
    """No real orders. Settlement is decided by EventContractOrder.settle()."""

    def open_order(self, order: EventContractOrder) -> None:
        return None

    def settle_order(self, order: EventContractOrder, settle_price: float) -> None:
        order.settle(settle_price)


_BACKEND: ExecutionBackend = PaperExecutionBackend()


def get_execution_backend() -> ExecutionBackend:
    return _BACKEND
