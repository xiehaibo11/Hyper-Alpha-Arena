"""Program analytics query and fee helpers."""

import logging
from datetime import date, datetime
from typing import Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from database.models import ProgramExecutionLog
from database.snapshot_connection import SnapshotSessionLocal
from database.snapshot_models import HyperliquidTrade

logger = logging.getLogger(__name__)


def get_fees_for_program_logs(logs: List[ProgramExecutionLog]) -> Dict[int, float]:
    """
    Batch query HyperliquidTrade to get total fees for each program execution log.

    Returns a dict mapping log_id -> total_fee. PnL is read directly from
    ProgramExecutionLog.realized_pnl.
    """
    if not logs:
        return {}

    order_ids = set()
    log_orders: Dict[int, List[str]] = {}

    for log in logs:
        orders = []
        if log.hyperliquid_order_id:
            order_ids.add(log.hyperliquid_order_id)
            orders.append(log.hyperliquid_order_id)
        if log.tp_order_id:
            order_ids.add(log.tp_order_id)
            orders.append(log.tp_order_id)
        if log.sl_order_id:
            order_ids.add(log.sl_order_id)
            orders.append(log.sl_order_id)
        log_orders[log.id] = orders

    if not order_ids:
        return {log.id: 0.0 for log in logs}

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
    except Exception as e:
        logger.warning(f"Failed to fetch fees from HyperliquidTrade: {e}")
    finally:
        if snapshot_db is not None:
            snapshot_db.close()

    result: Dict[int, float] = {}
    for log in logs:
        total_fee = 0.0
        for oid in log_orders.get(log.id, []):
            total_fee += fee_map.get(oid, 0.0)
        result[log.id] = total_fee

    return result


def build_program_base_query(
    db: Session,
    start_date: Optional[date],
    end_date: Optional[date],
    environment: Optional[str],
    account_id: Optional[int],
    exchange: Optional[str] = None,
):
    """Build base query for program execution logs with common filters."""
    query = db.query(ProgramExecutionLog).filter(
        ProgramExecutionLog.success == True,
        ProgramExecutionLog.decision_action.in_(["buy", "sell", "close"]),
        or_(
            ProgramExecutionLog.realized_pnl.isnot(None),
            ProgramExecutionLog.hyperliquid_order_id.isnot(None),
            ProgramExecutionLog.tp_order_id.isnot(None),
            ProgramExecutionLog.sl_order_id.isnot(None),
        ),
    )

    if start_date:
        query = query.filter(ProgramExecutionLog.created_at >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.filter(ProgramExecutionLog.created_at <= datetime.combine(end_date, datetime.max.time()))
    if account_id:
        query = query.filter(ProgramExecutionLog.account_id == account_id)

    if environment and environment != "all":
        query = query.filter(ProgramExecutionLog.environment == environment)

    if exchange and exchange != "all":
        if exchange == "hyperliquid":
            query = query.filter(
                (ProgramExecutionLog.exchange == "hyperliquid") | (ProgramExecutionLog.exchange == None)
            )
        else:
            query = query.filter(ProgramExecutionLog.exchange == exchange)

    return query
