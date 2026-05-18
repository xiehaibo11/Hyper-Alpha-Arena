"""Trade display helpers for analytics routes."""

import json
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from database.models import AIDecisionLog


def get_exit_type(decision: AIDecisionLog) -> str:
    """Determine exit type based on operation and order IDs."""
    pnl = float(decision.realized_pnl or 0)
    if decision.operation in ("buy", "sell") and pnl == 0:
        return "OPEN"
    if decision.operation == "close":
        return "CLOSE"
    if decision.tp_order_id or decision.sl_order_id:
        if pnl > 0:
            return "TP"
        return "SL"
    return "OPEN" if decision.operation in ("buy", "sell") else "CLOSE"


def get_entry_type(decision: AIDecisionLog, db: Session) -> str:
    """Determine entry type (BUY/SELL/-).

    For close operations, look up the corresponding opening trade.
    """
    if decision.operation in ("buy", "sell"):
        return decision.operation.upper()

    if decision.operation == "close" and decision.symbol and decision.wallet_address:
        opening_trade = db.query(AIDecisionLog).filter(
            AIDecisionLog.symbol == decision.symbol,
            AIDecisionLog.wallet_address == decision.wallet_address,
            AIDecisionLog.operation.in_(["buy", "sell"]),
            AIDecisionLog.decision_time < decision.decision_time,
        ).order_by(AIDecisionLog.decision_time.desc()).first()

        if opening_trade:
            return opening_trade.operation.upper()

    return "-"


def get_entry_decision(decision: AIDecisionLog, db: Session) -> Optional[AIDecisionLog]:
    """Get the entry decision for a trade.

    For buy/sell operations, return the decision itself.
    For close operations, find the corresponding opening trade.
    """
    if decision.operation in ("buy", "sell"):
        return decision

    if decision.operation == "close" and decision.symbol and decision.wallet_address:
        return db.query(AIDecisionLog).filter(
            AIDecisionLog.symbol == decision.symbol,
            AIDecisionLog.wallet_address == decision.wallet_address,
            AIDecisionLog.operation.in_(["buy", "sell"]),
            AIDecisionLog.decision_time < decision.decision_time,
        ).order_by(AIDecisionLog.decision_time.desc()).first()

    return None


def calculate_trade_tags(
    decisions: List[AIDecisionLog],
    account_equity: float,
    equity_threshold: float = 0.05,
) -> Dict[int, List[str]]:
    """Calculate rule-based tags for each trade."""
    tags: Dict[int, List[str]] = {}
    loss_threshold = account_equity * equity_threshold if account_equity > 0 else 50.0

    sorted_decisions = sorted(decisions, key=lambda decision: decision.decision_time or datetime.min)

    consecutive_losses = 0
    consecutive_loss_ids = []

    for decision in sorted_decisions:
        decision_tags = []
        pnl = float(decision.realized_pnl) if decision.realized_pnl else 0

        if pnl < 0 and abs(pnl) > loss_threshold:
            decision_tags.append("large_loss")

        if decision.sl_order_id and pnl < 0:
            decision_tags.append("sl_triggered")

        if pnl < 0:
            consecutive_losses += 1
            consecutive_loss_ids.append(decision.id)
        else:
            if consecutive_losses >= 3:
                for loss_id in consecutive_loss_ids:
                    if loss_id not in tags:
                        tags[loss_id] = []
                    if "consecutive_loss" not in tags[loss_id]:
                        tags[loss_id].append("consecutive_loss")
            consecutive_losses = 0
            consecutive_loss_ids = []

        tags[decision.id] = decision_tags

    if consecutive_losses >= 3:
        for loss_id in consecutive_loss_ids:
            if "consecutive_loss" not in tags.get(loss_id, []):
                tags.setdefault(loss_id, []).append("consecutive_loss")

    return tags


def parse_decision_prices(decision: AIDecisionLog) -> dict:
    """Extract price info from decision_snapshot JSON."""
    prices = {"entry_price": None, "tp_price": None, "sl_price": None, "exit_price": None}
    if not decision.decision_snapshot:
        return prices

    try:
        snapshot = (
            json.loads(decision.decision_snapshot)
            if isinstance(decision.decision_snapshot, str)
            else decision.decision_snapshot
        )
        operation = snapshot.get("operation", decision.operation)

        if operation == "buy":
            prices["entry_price"] = snapshot.get("max_price") or snapshot.get("entry_price")
        elif operation == "sell":
            prices["entry_price"] = snapshot.get("min_price") or snapshot.get("entry_price")
        else:
            prices["entry_price"] = (
                snapshot.get("max_price") or snapshot.get("min_price") or snapshot.get("entry_price")
            )

        prices["tp_price"] = snapshot.get("take_profit_price") or snapshot.get("tp_price")
        prices["sl_price"] = snapshot.get("stop_loss_price") or snapshot.get("sl_price")
        prices["exit_price"] = snapshot.get("min_price") if operation == "close" else None
    except (TypeError, ValueError, AttributeError):
        pass

    return prices
