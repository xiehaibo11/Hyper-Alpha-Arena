"""Trade list analytics routes."""

import logging
from datetime import date, datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import AIDecisionLog, ProgramExecutionLog
from database.snapshot_connection import SnapshotSessionLocal
from database.snapshot_models import HyperliquidAccountSnapshot, HyperliquidTrade
from services.analytics_ai_helpers import get_fees_for_decisions
from services.analytics_program_helpers import get_fees_for_program_logs
from services.analytics_trade_helpers import calculate_trade_tags, get_entry_decision, get_exit_type

logger = logging.getLogger(__name__)

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/trades")
def get_trade_details(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    account_id: Optional[int] = Query(None),
    exchange: Optional[str] = Query("all"),
    tag_filter: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    """Get trade details with rule-based tags for micro-analysis.

    Combines both AIDecisionLog and ProgramExecutionLog records.
    """

    def _apply_filters_ai(q):
        if start_date:
            q = q.filter(AIDecisionLog.decision_time >= datetime.combine(start_date, datetime.min.time()))
        if end_date:
            q = q.filter(AIDecisionLog.decision_time <= datetime.combine(end_date, datetime.max.time()))
        if environment and environment != "all":
            q = q.filter(AIDecisionLog.hyperliquid_environment == environment)
        if account_id:
            q = q.filter(AIDecisionLog.account_id == account_id)
        if exchange and exchange != "all":
            if exchange == "hyperliquid":
                q = q.filter((AIDecisionLog.exchange == "hyperliquid") | (AIDecisionLog.exchange == None))
            else:
                q = q.filter(AIDecisionLog.exchange == exchange)
        return q

    def _apply_filters_prog(q):
        if start_date:
            q = q.filter(ProgramExecutionLog.created_at >= datetime.combine(start_date, datetime.min.time()))
        if end_date:
            q = q.filter(ProgramExecutionLog.created_at <= datetime.combine(end_date, datetime.max.time()))
        if environment and environment != "all":
            q = q.filter(ProgramExecutionLog.environment == environment)
        if account_id:
            q = q.filter(ProgramExecutionLog.account_id == account_id)
        if exchange and exchange != "all":
            if exchange == "hyperliquid":
                q = q.filter((ProgramExecutionLog.exchange == "hyperliquid") | (ProgramExecutionLog.exchange == None))
            else:
                q = q.filter(ProgramExecutionLog.exchange == exchange)
        return q

    ai_query = db.query(AIDecisionLog).filter(
        AIDecisionLog.executed == "true",
        AIDecisionLog.operation.in_(["buy", "sell", "close"]),
        AIDecisionLog.hyperliquid_order_id.isnot(None),
    )
    ai_query = _apply_filters_ai(ai_query)
    ai_decisions = ai_query.order_by(AIDecisionLog.decision_time.desc()).all()

    prog_query = db.query(ProgramExecutionLog).filter(
        ProgramExecutionLog.success == True,
        ProgramExecutionLog.decision_action.in_(["buy", "sell", "close"]),
        ProgramExecutionLog.hyperliquid_order_id.isnot(None),
    )
    prog_query = _apply_filters_prog(prog_query)
    prog_logs = prog_query.order_by(ProgramExecutionLog.created_at.desc()).all()

    account_equity = 0.0
    first_acct = ai_decisions[0].account_id if ai_decisions else prog_logs[0].account_id if prog_logs else None
    if first_acct:
        env = environment if environment != "all" else "mainnet"
        try:
            snap_db = SnapshotSessionLocal()
            snapshot = snap_db.query(HyperliquidAccountSnapshot).filter(
                HyperliquidAccountSnapshot.account_id == first_acct,
                HyperliquidAccountSnapshot.environment == env,
            ).order_by(HyperliquidAccountSnapshot.created_at.desc()).first()
            if snapshot and snapshot.total_equity:
                account_equity = float(snapshot.total_equity)
            snap_db.close()
        except Exception as exc:
            logger.warning(f"Failed to get account equity: {exc}")

    ai_trade_tags = calculate_trade_tags(ai_decisions, account_equity)

    ai_fee_map = get_fees_for_decisions(ai_decisions)
    prog_fee_map = get_fees_for_program_logs(prog_logs)

    snapshot_db = SnapshotSessionLocal()
    unified: List[Dict] = []

    for decision in ai_decisions:
        pnl = float(decision.realized_pnl) if decision.realized_pnl else 0
        fee = ai_fee_map.get(decision.id, 0.0)

        entry_decision = get_entry_decision(decision, db)
        entry_time = (
            entry_decision.decision_time.isoformat()
            if entry_decision and entry_decision.decision_time
            else None
        )

        exit_type = get_exit_type(decision)
        exit_time = None
        if exit_type in ("TP", "SL"):
            tp_sl_order_id = decision.tp_order_id or decision.sl_order_id
            if tp_sl_order_id:
                hl_trade = snapshot_db.query(HyperliquidTrade).filter(
                    HyperliquidTrade.order_id == str(tp_sl_order_id)
                ).first()
                if hl_trade and hl_trade.trade_time:
                    exit_time = hl_trade.trade_time.isoformat()
            if not exit_time and decision.pnl_updated_at:
                exit_time = decision.pnl_updated_at.isoformat()
        if exit_type == "OPEN":
            exit_time = None
        elif not exit_time:
            exit_time = decision.decision_time.isoformat() if decision.decision_time else None

        unified.append({
            "id": decision.id,
            "source": "ai",
            "symbol": decision.symbol,
            "sort_time": decision.decision_time or datetime.min,
            "decision_time": decision.decision_time.isoformat() if decision.decision_time else None,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "entry_type": entry_decision.operation.upper() if entry_decision else "-",
            "exit_type": exit_type,
            "gross_pnl": round(pnl, 2),
            "fees": round(fee, 2),
            "net_pnl": round(pnl - fee, 2),
            "tags": ai_trade_tags.get(decision.id, []),
            "hyperliquid_order_id": decision.hyperliquid_order_id,
            "tp_order_id": decision.tp_order_id,
            "sl_order_id": decision.sl_order_id,
        })

    for program_log in prog_logs:
        pnl = float(program_log.realized_pnl) if program_log.realized_pnl else 0
        fee = prog_fee_map.get(program_log.id, 0.0)

        action = (program_log.decision_action or "").lower()
        if action in ("buy", "sell"):
            entry_type = action.upper()
        elif action == "close" and program_log.decision_symbol and program_log.wallet_address:
            opening = db.query(ProgramExecutionLog).filter(
                ProgramExecutionLog.decision_symbol == program_log.decision_symbol,
                ProgramExecutionLog.wallet_address == program_log.wallet_address,
                ProgramExecutionLog.decision_action.in_(["buy", "sell"]),
                ProgramExecutionLog.created_at < program_log.created_at,
            ).order_by(ProgramExecutionLog.created_at.desc()).first()
            entry_type = opening.decision_action.upper() if opening else "-"
        else:
            entry_type = "-"

        if action in ("buy", "sell") and pnl == 0:
            exit_type = "OPEN"
        elif action == "close":
            exit_type = "CLOSE"
        elif program_log.tp_order_id or program_log.sl_order_id:
            exit_type = "TP" if pnl > 0 else "SL"
        else:
            exit_type = "CLOSE"

        exit_time = None
        if exit_type in ("TP", "SL"):
            tp_sl_oid = program_log.tp_order_id or program_log.sl_order_id
            if tp_sl_oid:
                hl_trade = snapshot_db.query(HyperliquidTrade).filter(
                    HyperliquidTrade.order_id == str(tp_sl_oid)
                ).first()
                if hl_trade and hl_trade.trade_time:
                    exit_time = hl_trade.trade_time.isoformat()
        if exit_type == "OPEN":
            exit_time = None
        elif not exit_time:
            exit_time = program_log.created_at.isoformat() if program_log.created_at else None

        entry_time = None
        if action in ("buy", "sell"):
            entry_time = program_log.created_at.isoformat() if program_log.created_at else None
        elif action == "close" and program_log.decision_symbol and program_log.wallet_address:
            opening = db.query(ProgramExecutionLog).filter(
                ProgramExecutionLog.decision_symbol == program_log.decision_symbol,
                ProgramExecutionLog.wallet_address == program_log.wallet_address,
                ProgramExecutionLog.decision_action.in_(["buy", "sell"]),
                ProgramExecutionLog.created_at < program_log.created_at,
            ).order_by(ProgramExecutionLog.created_at.desc()).first()
            entry_time = opening.created_at.isoformat() if opening and opening.created_at else None

        program_tags = []
        loss_threshold = account_equity * 0.05 if account_equity > 0 else 50.0
        if pnl < 0 and abs(pnl) >= loss_threshold:
            program_tags.append("large_loss")
        if exit_type == "SL":
            program_tags.append("sl_triggered")

        unified.append({
            "id": program_log.id,
            "source": "program",
            "symbol": program_log.decision_symbol,
            "sort_time": program_log.created_at or datetime.min,
            "decision_time": program_log.created_at.isoformat() if program_log.created_at else None,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "entry_type": entry_type,
            "exit_type": exit_type,
            "gross_pnl": round(pnl, 2),
            "fees": round(fee, 2),
            "net_pnl": round(pnl - fee, 2),
            "tags": program_tags,
            "hyperliquid_order_id": program_log.hyperliquid_order_id,
            "tp_order_id": program_log.tp_order_id,
            "sl_order_id": program_log.sl_order_id,
        })

    snapshot_db.close()

    unified.sort(key=lambda trade: trade["sort_time"], reverse=True)

    if tag_filter:
        unified = [trade for trade in unified if tag_filter in trade.get("tags", [])]

    total_count = len(unified)
    paginated = unified[offset:offset + limit]

    for trade in paginated:
        trade.pop("sort_time", None)

    return {
        "trades": paginated,
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "account_equity": round(account_equity, 2),
        "loss_threshold": round(account_equity * 0.05, 2) if account_equity > 0 else 50.0,
    }
