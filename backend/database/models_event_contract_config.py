"""Runtime-editable config for the event-contract product.

Single-row table holding client overrides as a JSON string (TEXT, matching the
project's JSON-as-TEXT convention). Defaults live in
services/event_contract/config.py; config_store.py merges defaults + this row.
"""
from sqlalchemy import Column, Integer, Text, DateTime
from sqlalchemy.sql import func

from .connection import Base


class EventContractConfig(Base):
    __tablename__ = "event_contract_config"

    id = Column(Integer, primary_key=True)
    # JSON string of override keys: symbols, expiries, payout, default_signal,
    # daily_reset_tz, signal_params ({"BTC:5": {"window":45,"thr":1.5}, ...})
    data = Column(Text, nullable=False, default="{}")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
