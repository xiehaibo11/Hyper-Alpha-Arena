"""Event-contract (binary up/down) signal system models.

Kept in its own module so the oversized legacy models.py does not grow.
Imported at startup (main.py) so SQLAlchemy registers the table for create_all.
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Index
from sqlalchemy.sql import func

from .connection import Base


class EventContractOrder(Base):
    """One simulated binary up/down event-contract order.

    Lifecycle: a strategy fires on a closed 1m candle -> we open at the next
    candle's open price -> after `expiry_minutes` we read the settle price and
    decide win/loss. Both historical backtest rows and live paper-sim rows live
    here, distinguished by `mode`.
    """

    __tablename__ = "event_contract_orders"

    id = Column(Integer, primary_key=True, index=True)

    # 'backtest' or 'live'
    mode = Column(String(16), nullable=False, default="live")
    exchange = Column(String(32), nullable=False, default="binance")
    symbol = Column(String(32), nullable=False)
    strategy = Column(String(64), nullable=False)

    # 'long' (up) or 'short' (down)
    direction = Column(String(8), nullable=False)
    expiry_minutes = Column(Integer, nullable=False)  # 5 or 10

    # Signal confirmed at the close of this 1m candle.
    signal_time = Column(DateTime(timezone=True), nullable=False)
    # Entry = open of the next 1m candle.
    entry_time = Column(DateTime(timezone=True), nullable=False)
    entry_price = Column(Float, nullable=False)
    # Settlement = price `expiry_minutes` after entry.
    settle_time = Column(DateTime(timezone=True), nullable=False)
    settle_price = Column(Float, nullable=True)

    # 'win' | 'loss' | 'pending'
    result = Column(String(8), nullable=False, default="pending")
    payout = Column(Float, nullable=False, default=0.8)  # binary payout on win
    pnl = Column(Float, nullable=True)  # per 1-unit flat stake

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index(
            "ix_event_contract_lookup",
            "mode",
            "symbol",
            "expiry_minutes",
            "entry_time",
        ),
        Index("ix_event_contract_settle", "result", "settle_time"),
    )

    def settle(self, settle_price: float) -> str:
        """Fill the settle price and decide win/loss + pnl. Returns the result."""
        self.settle_price = settle_price
        if self.direction == "long":
            won = settle_price > self.entry_price
        else:
            won = settle_price < self.entry_price
        self.result = "win" if won else "loss"
        self.pnl = self.payout if won else -1.0
        return self.result
