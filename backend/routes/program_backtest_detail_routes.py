"""Backtest result detail query routes."""

import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import BacktestResult, BacktestTriggerLog

router = APIRouter()

@router.get("/backtest/history")
def get_backtest_history(
    binding_id: int = Query(..., description="Binding ID to get history for"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Get backtest history for a specific binding.

    Returns a list of past backtest results (summary only, no equity curve).
    """
    query = db.query(BacktestResult).filter(
        BacktestResult.binding_id == binding_id,
        BacktestResult.backtest_type == 'program'
    ).order_by(BacktestResult.created_at.desc())

    total = query.count()
    backtests = query.offset(offset).limit(limit).all()

    results = []
    for bt in backtests:
        config = bt.config
        if isinstance(config, str):
            config = json.loads(config)

        results.append({
            "id": bt.id,
            "config": config,
            "start_time": bt.start_time.isoformat() if bt.start_time else None,
            "end_time": bt.end_time.isoformat() if bt.end_time else None,
            "initial_balance": bt.initial_balance,
            "final_equity": bt.final_equity,
            "total_pnl": bt.total_pnl,
            "total_pnl_percent": bt.total_pnl_percent,
            "max_drawdown_percent": bt.max_drawdown_percent,
            "total_triggers": bt.total_triggers,
            "total_trades": bt.total_trades,
            "win_rate": bt.win_rate,
            "status": bt.status,
            "created_at": bt.created_at.isoformat() + "Z" if bt.created_at else None,
        })

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "results": results
    }


@router.get("/backtest/{backtest_id}")
def get_backtest_result(backtest_id: int, db: Session = Depends(get_db)):
    """
    Get backtest result summary by ID.

    Returns the backtest result without trigger logs (use /triggers endpoint for logs).
    """
    backtest = db.query(BacktestResult).filter(BacktestResult.id == backtest_id).first()
    if not backtest:
        raise HTTPException(status_code=404, detail="Backtest not found")

    # Parse equity_curve if stored as JSON string
    equity_curve = backtest.equity_curve
    if isinstance(equity_curve, str):
        equity_curve = json.loads(equity_curve)

    # Parse config if stored as JSON string
    config = backtest.config
    if isinstance(config, str):
        config = json.loads(config)

    return {
        "id": backtest.id,
        "backtest_type": backtest.backtest_type,
        "binding_id": backtest.binding_id,
        "prompt_id": backtest.prompt_id,
        "user_id": backtest.user_id,
        "config": config,
        "start_time": backtest.start_time.isoformat() if backtest.start_time else None,
        "end_time": backtest.end_time.isoformat() if backtest.end_time else None,
        "initial_balance": backtest.initial_balance,
        "final_equity": backtest.final_equity,
        "total_pnl": backtest.total_pnl,
        "total_pnl_percent": backtest.total_pnl_percent,
        "max_drawdown": backtest.max_drawdown,
        "max_drawdown_percent": backtest.max_drawdown_percent,
        "total_triggers": backtest.total_triggers,
        "total_trades": backtest.total_trades,
        "winning_trades": backtest.winning_trades,
        "losing_trades": backtest.losing_trades,
        "win_rate": backtest.win_rate,
        "profit_factor": backtest.profit_factor,
        "sharpe_ratio": backtest.sharpe_ratio,
        "equity_curve": equity_curve,
        "execution_time_ms": backtest.execution_time_ms,
        "status": backtest.status,
        "error_message": backtest.error_message,
        "created_at": backtest.created_at.isoformat() if backtest.created_at else None,
        "completed_at": backtest.completed_at.isoformat() if backtest.completed_at else None,
    }


@router.get("/backtest/{backtest_id}/triggers")
def get_backtest_triggers(
    backtest_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    action_filter: Optional[str] = Query(None, description="Filter by action: buy, sell, close, hold"),
    db: Session = Depends(get_db)
):
    """
    Get trigger logs for a backtest (summary list).

    Returns paginated list of trigger logs without full decision_input/output.
    Use /triggers/{trigger_id} for full details.
    """
    backtest = db.query(BacktestResult).filter(BacktestResult.id == backtest_id).first()
    if not backtest:
        raise HTTPException(status_code=404, detail="Backtest not found")

    query = db.query(BacktestTriggerLog).filter(
        BacktestTriggerLog.backtest_id == backtest_id
    )

    if action_filter:
        query = query.filter(BacktestTriggerLog.decision_action == action_filter)

    total = query.count()
    triggers = query.order_by(BacktestTriggerLog.trigger_index).offset(offset).limit(limit).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "triggers": [
            {
                "id": t.id,
                "trigger_index": t.trigger_index,
                "trigger_type": t.trigger_type,
                "trigger_time": t.trigger_time.isoformat() + "Z" if t.trigger_time else None,
                "symbol": t.symbol,
                "decision_action": t.decision_action,
                "decision_symbol": t.decision_symbol,
                "decision_side": t.decision_side,
                "decision_size": t.decision_size,
                "decision_reason": t.decision_reason,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "fee": t.fee,
                "unrealized_pnl": t.unrealized_pnl,
                "realized_pnl": t.realized_pnl,
                "equity_before": t.equity_before,
                "equity_after": t.equity_after,
                "execution_error": t.execution_error,
            }
            for t in triggers
        ]
    }


@router.get("/backtest/{backtest_id}/markers")
def get_backtest_markers(backtest_id: int, db: Session = Depends(get_db)):
    """
    Get chart markers for a backtest.

    Returns all non-HOLD triggers with minimal data for chart display.
    """
    backtest = db.query(BacktestResult).filter(BacktestResult.id == backtest_id).first()
    if not backtest:
        raise HTTPException(status_code=404, detail="Backtest not found")

    triggers = db.query(
        BacktestTriggerLog.trigger_index,
        BacktestTriggerLog.decision_action,
        BacktestTriggerLog.trigger_type
    ).filter(
        BacktestTriggerLog.backtest_id == backtest_id,
        BacktestTriggerLog.decision_action != 'hold'
    ).order_by(BacktestTriggerLog.trigger_index).all()

    return {
        "total": len(triggers),
        "markers": [
            {
                "index": t.trigger_index,
                "action": t.decision_action,
                "trigger_type": t.trigger_type
            }
            for t in triggers
        ]
    }


@router.get("/backtest/trigger/{trigger_id}")
def get_trigger_detail(trigger_id: int, db: Session = Depends(get_db)):
    """
    Get full details for a single trigger log.

    Returns complete decision_input and decision_output for debugging.
    """
    trigger = db.query(BacktestTriggerLog).filter(BacktestTriggerLog.id == trigger_id).first()
    if not trigger:
        raise HTTPException(status_code=404, detail="Trigger log not found")

    # Parse JSON fields
    decision_input = trigger.decision_input
    if isinstance(decision_input, str):
        decision_input = json.loads(decision_input)

    decision_output = trigger.decision_output
    if isinstance(decision_output, str) and decision_output:
        decision_output = json.loads(decision_output)

    data_queries = trigger.data_queries
    if isinstance(data_queries, str) and data_queries:
        data_queries = json.loads(data_queries)

    execution_logs = trigger.execution_logs
    if isinstance(execution_logs, str) and execution_logs:
        execution_logs = json.loads(execution_logs)

    return {
        "id": trigger.id,
        "backtest_id": trigger.backtest_id,
        "trigger_index": trigger.trigger_index,
        "trigger_type": trigger.trigger_type,
        "trigger_time": trigger.trigger_time.isoformat() + "Z" if trigger.trigger_time else None,
        "symbol": trigger.symbol,
        "decision_type": trigger.decision_type,
        "decision_action": trigger.decision_action,
        "decision_symbol": trigger.decision_symbol,
        "decision_side": trigger.decision_side,
        "decision_size": trigger.decision_size,
        "decision_reason": trigger.decision_reason,
        "entry_price": trigger.entry_price,
        "exit_price": trigger.exit_price,
        "pnl": trigger.pnl,
        "fee": trigger.fee,
        "unrealized_pnl": trigger.unrealized_pnl,
        "realized_pnl": trigger.realized_pnl,
        "equity_before": trigger.equity_before,
        "equity_after": trigger.equity_after,
        "decision_input": decision_input,
        "decision_output": decision_output,
        "data_queries": data_queries,
        "execution_logs": execution_logs,
        "execution_error": trigger.execution_error,
        "created_at": trigger.created_at.isoformat() if trigger.created_at else None,
    }
