"""Diagnostics for strategy triggers that do not persist a decision log."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from database.models import Account, AIDecisionLog
from services.ai_decision_logging import save_ai_diagnostic_decision

logger = logging.getLogger(__name__)


def _as_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def get_latest_decision_id(
    db: Session,
    account_id: int,
    exchange: str,
) -> Optional[int]:
    latest = (
        db.query(AIDecisionLog.id)
        .filter(
            AIDecisionLog.account_id == account_id,
            AIDecisionLog.exchange == exchange,
        )
        .order_by(desc(AIDecisionLog.id))
        .first()
    )
    return int(latest[0]) if latest else None


def ensure_decision_log_for_trigger(
    db: Session,
    *,
    account_id: int,
    exchange: str,
    trigger_time: datetime,
    previous_decision_id: Optional[int],
    trigger_context: Optional[Dict[str, Any]] = None,
) -> bool:
    """Persist a diagnostic HOLD when a trigger produced no decision row."""
    trigger_time_naive = _as_naive_utc(trigger_time)
    query = db.query(AIDecisionLog.id).filter(
        AIDecisionLog.account_id == account_id,
        AIDecisionLog.exchange == exchange,
        AIDecisionLog.decision_time >= trigger_time_naive,
    )
    if previous_decision_id is not None:
        query = query.filter(AIDecisionLog.id > previous_decision_id)

    if query.order_by(desc(AIDecisionLog.id)).first():
        return False

    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.is_deleted != True)
        .first()
    )
    if not account:
        return False

    reason = (
        f"{exchange.capitalize()} strategy trigger completed without a persisted AI decision. "
        "This diagnostic HOLD was recorded so the dashboard can audit skipped or failed trigger paths."
    )
    save_ai_diagnostic_decision(
        db,
        account,
        {"cash": 0, "frozen_cash": 0, "positions": {}, "total_assets": 0},
        reason,
        trigger_context=trigger_context,
        symbol=(trigger_context or {}).get("trigger_symbol"),
        raw_detail={
            "exchange": exchange,
            "trigger_time": trigger_time_naive.isoformat(),
            "previous_decision_id": previous_decision_id,
        },
        exchange=exchange,
    )
    logger.warning(
        "Recorded diagnostic decision for account %s on %s after trigger without decision log",
        account_id,
        exchange,
    )
    return True
