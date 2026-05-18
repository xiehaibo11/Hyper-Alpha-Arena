"""AI analytics query, fee, and metric helpers."""

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from database.models import AIDecisionLog
from database.snapshot_connection import SnapshotSessionLocal
from database.snapshot_models import HyperliquidTrade

logger = logging.getLogger(__name__)


def get_fees_for_decisions(decisions: List[AIDecisionLog]) -> Dict[int, float]:
    """
    Batch query HyperliquidTrade to get total fees for each decision.

    Returns a dict mapping decision_id -> total_fee.
    """
    if not decisions:
        return {}

    order_ids = set()
    decision_orders: Dict[int, List[str]] = {}

    for decision in decisions:
        orders = []
        if decision.hyperliquid_order_id:
            order_ids.add(decision.hyperliquid_order_id)
            orders.append(decision.hyperliquid_order_id)
        if decision.tp_order_id:
            order_ids.add(decision.tp_order_id)
            orders.append(decision.tp_order_id)
        if decision.sl_order_id:
            order_ids.add(decision.sl_order_id)
            orders.append(decision.sl_order_id)
        decision_orders[decision.id] = orders

    if not order_ids:
        return {decision.id: 0.0 for decision in decisions}

    fee_map: Dict[str, float] = {}
    snapshot_db = None
    try:
        snapshot_db = SnapshotSessionLocal()
        trades = snapshot_db.query(HyperliquidTrade).filter(
            HyperliquidTrade.order_id.in_(list(order_ids))
        ).all()
        for trade in trades:
            if trade.order_id:
                fee_map[str(trade.order_id)] = float(trade.fee or 0)
    except Exception as exc:
        logger.warning(f"Failed to fetch fees from HyperliquidTrade: {exc}")
    finally:
        if snapshot_db is not None:
            snapshot_db.close()

    result: Dict[int, float] = {}
    for decision in decisions:
        total_fee = 0.0
        for order_id in decision_orders.get(decision.id, []):
            total_fee += fee_map.get(order_id, 0.0)
        result[decision.id] = total_fee

    return result


def calculate_metrics(records: List[Dict]) -> Dict[str, Any]:
    """Calculate standard metrics from a list of decision records."""
    if not records:
        return {
            "total_pnl": 0.0,
            "total_fee": 0.0,
            "net_pnl": 0.0,
            "trade_count": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": 0.0,
            "avg_win": None,
            "avg_loss": None,
            "profit_factor": None,
        }

    total_pnl = sum(record.get("pnl", 0) or 0 for record in records)
    total_fee = sum(record.get("fee", 0) or 0 for record in records)
    net_pnl = total_pnl - total_fee

    wins = [record for record in records if (record.get("pnl") or 0) > 0]
    losses = [record for record in records if (record.get("pnl") or 0) < 0]

    win_count = len(wins)
    loss_count = len(losses)
    trade_count = len(records)
    win_rate = win_count / trade_count if trade_count > 0 else 0.0

    total_win = sum(record.get("pnl", 0) or 0 for record in wins)
    total_loss = abs(sum(record.get("pnl", 0) or 0 for record in losses))

    avg_win = total_win / win_count if win_count > 0 else None
    avg_loss = -total_loss / loss_count if loss_count > 0 else None
    profit_factor = total_win / total_loss if total_loss > 0 else None

    return {
        "total_pnl": round(total_pnl, 2),
        "total_fee": round(total_fee, 2),
        "net_pnl": round(net_pnl, 2),
        "trade_count": trade_count,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 2) if avg_win else None,
        "avg_loss": round(avg_loss, 2) if avg_loss else None,
        "profit_factor": round(profit_factor, 2) if profit_factor else None,
    }


def get_trigger_type(decision: AIDecisionLog) -> str:
    """Determine trigger type for a decision."""
    if decision.signal_trigger_id is not None:
        return "signal"
    if decision.executed == "true" and decision.operation in ("buy", "sell", "close"):
        return "scheduled"
    return "unknown"


def build_base_query(
    db: Session,
    start_date: Optional[date],
    end_date: Optional[date],
    environment: Optional[str],
    account_id: Optional[int],
    exchange: Optional[str] = None,
):
    """Build base query with common filters.

    Includes executed trade decisions with order attribution. Open entries usually
    have realized_pnl=0 until TP/SL or an explicit close settles them, but they
    should still appear so Attribution Analysis shows active AI work.
    """
    query = db.query(AIDecisionLog).filter(
        AIDecisionLog.operation.in_(["buy", "sell", "close"]),
        AIDecisionLog.executed == "true",
        or_(
            AIDecisionLog.realized_pnl.isnot(None),
            AIDecisionLog.hyperliquid_order_id.isnot(None),
            AIDecisionLog.tp_order_id.isnot(None),
            AIDecisionLog.sl_order_id.isnot(None),
        ),
    )

    if start_date:
        query = query.filter(AIDecisionLog.decision_time >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.filter(AIDecisionLog.decision_time <= datetime.combine(end_date, datetime.max.time()))
    if environment and environment != "all":
        query = query.filter(AIDecisionLog.hyperliquid_environment == environment)
    if account_id:
        query = query.filter(AIDecisionLog.account_id == account_id)
    if exchange and exchange != "all":
        if exchange == "hyperliquid":
            query = query.filter(
                (AIDecisionLog.exchange == "hyperliquid") | (AIDecisionLog.exchange == None)
            )
        else:
            query = query.filter(AIDecisionLog.exchange == exchange)

    return query
