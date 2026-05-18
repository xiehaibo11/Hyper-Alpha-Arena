"""Execution log routes for Program Trader."""

import json
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Account, ProgramExecutionLog, SignalPool, TradingProgram
from routes.program_schemas import ExecutionLogResponse

router = APIRouter()

@router.get("/executions/", response_model=List[ExecutionLogResponse])
def list_executions(
    account_id: Optional[int] = Query(None),
    program_id: Optional[int] = Query(None),
    environment: Optional[str] = Query(None, regex="^(testnet|mainnet)$"),
    before: Optional[str] = Query(None, description="ISO timestamp for pagination, returns logs before this time"),
    after: Optional[str] = Query(None, description="ISO timestamp, returns logs after this time"),
    action: Optional[str] = Query(None, regex="^(buy|sell|hold|close)$", description="Filter by decision action"),
    limit: int = Query(50, le=200),
    exchange: Optional[str] = Query(None, regex="^(hyperliquid|binance)$"),
    db: Session = Depends(get_db)
):
    """List program execution logs for Feed display."""
    query = db.query(ProgramExecutionLog)

    if account_id:
        query = query.filter(ProgramExecutionLog.account_id == account_id)
    if program_id:
        query = query.filter(ProgramExecutionLog.program_id == program_id)
    if environment:
        query = query.filter(ProgramExecutionLog.environment == environment)
    if before:
        from datetime import datetime
        before_dt = datetime.fromisoformat(before.replace('Z', '+00:00'))
        query = query.filter(ProgramExecutionLog.created_at < before_dt)
    if after:
        from datetime import datetime as dt_after
        after_dt = dt_after.fromisoformat(after.replace('Z', '+00:00'))
        query = query.filter(ProgramExecutionLog.created_at >= after_dt)
    if action:
        query = query.filter(ProgramExecutionLog.decision_action == action)
    if exchange:
        if exchange == "hyperliquid":
            # Include hyperliquid or NULL (legacy data)
            query = query.filter(
                (ProgramExecutionLog.exchange == "hyperliquid") | (ProgramExecutionLog.exchange == None)
            )
        else:
            query = query.filter(ProgramExecutionLog.exchange == exchange)

    logs = query.order_by(ProgramExecutionLog.created_at.desc()).limit(limit).all()

    result = []
    for log in logs:
        # Get account name
        account = db.query(Account).filter(Account.id == log.account_id).first()
        account_name = account.name if account else "Unknown"

        # Get program name
        program = db.query(TradingProgram).filter(TradingProgram.id == log.program_id).first()
        program_name = program.name if program else "Unknown"

        # Get signal pool name if applicable
        signal_pool_name = None
        if log.signal_pool_id:
            pool = db.query(SignalPool).filter(SignalPool.id == log.signal_pool_id).first()
            signal_pool_name = pool.pool_name if pool else None

        result.append(ExecutionLogResponse(
            id=log.id,
            binding_id=log.binding_id,
            account_id=log.account_id,
            account_name=account_name,
            program_id=log.program_id,
            program_name=program_name,
            trigger_type=log.trigger_type,
            trigger_symbol=log.trigger_symbol,
            signal_pool_id=log.signal_pool_id,
            signal_pool_name=signal_pool_name,
            wallet_address=log.wallet_address,
            success=log.success,
            decision_action=log.decision_action,
            decision_symbol=log.decision_symbol,
            decision_size_usd=log.decision_size_usd,
            decision_leverage=log.decision_leverage,
            decision_reason=log.decision_reason,
            error_message=log.error_message,
            execution_time_ms=log.execution_time_ms,
            market_context=json.loads(log.market_context) if log.market_context else None,
            params_snapshot=json.loads(log.params_snapshot) if log.params_snapshot else None,
            decision_json=json.loads(log.decision_json) if log.decision_json else None,
            created_at=log.created_at.isoformat() if log.created_at else "",
            # Exchange identifier (NULL treated as "hyperliquid" for backward compatibility)
            exchange=log.exchange or "hyperliquid",
        ))

    return result


# ============================================================================
