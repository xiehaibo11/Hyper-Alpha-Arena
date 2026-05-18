"""Backtest Data AI snapshot builder for Arena context."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from database.models import (
    AccountProgramBinding,
    BacktestResult,
    BacktestTriggerLog,
    PromptBacktestTask,
)
from services.arena_ai_backtest_quality import build_backtest_data_quality

MODULE_BACKTEST = "backtest_data_ai"


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return None
        return result
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _format_number(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}"


def build_backtest_snapshot(
    db: Session,
    account_id: Optional[int],
    exchange: str,
    symbols: List[str],
    timeframe: str,
) -> Dict[str, Any]:
    result_query = db.query(BacktestResult).filter(BacktestResult.backtest_type == "program")
    if exchange == "hyperliquid":
        result_query = result_query.filter(
            (BacktestResult.exchange == exchange) | (BacktestResult.exchange.is_(None))
        )
    else:
        result_query = result_query.filter(BacktestResult.exchange == exchange)

    binding_ids: List[int] = []
    if account_id is not None:
        binding_query = db.query(AccountProgramBinding.id).filter(
            AccountProgramBinding.account_id == account_id,
            AccountProgramBinding.is_deleted != True,  # noqa: E712
        )
        if exchange == "hyperliquid":
            binding_query = binding_query.filter(
                (AccountProgramBinding.exchange == exchange) | (AccountProgramBinding.exchange.is_(None))
            )
        else:
            binding_query = binding_query.filter(AccountProgramBinding.exchange == exchange)
        binding_ids = [int(row[0]) for row in binding_query.all()]
        if binding_ids:
            result_query = result_query.filter(BacktestResult.binding_id.in_(binding_ids))
        else:
            result_query = result_query.filter(BacktestResult.binding_id == -1)

    recent_results = result_query.order_by(desc(BacktestResult.created_at)).limit(20).all()

    prompt_query = db.query(PromptBacktestTask)
    if account_id is not None:
        prompt_query = prompt_query.filter(PromptBacktestTask.account_id == account_id)
    prompt_tasks = prompt_query.order_by(desc(PromptBacktestTask.created_at)).limit(10).all()
    data_quality = build_backtest_data_quality(db, account_id, exchange, symbols, timeframe)

    if not recent_results and not prompt_tasks:
        self_check = data_quality["accuracy_self_check"]
        has_validation_inputs = (
            data_quality["kline_ready_count"] > 0
            or data_quality["flow_ready_count"] > 0
            or data_quality["live_trigger_count_24h"] > 0
            or data_quality["decision_count_7d"] > 0
        )
        status = "warning" if has_validation_inputs else "missing"
        risk_level = "high" if data_quality["closed_outcome_count_7d"] == 0 and data_quality["executed_decision_count_7d"] else "medium"
        return {
            "module": MODULE_BACKTEST,
            "status": status,
            "summary": (
                f"Backtest Data AI ({exchange}/{timeframe}): no completed program or prompt backtests yet. "
                f"Data readiness: kline={data_quality['kline_ready_count']}/{data_quality['symbol_count']} symbols, "
                f"market_flow={data_quality['flow_ready_count']}/{data_quality['symbol_count']} symbols, "
                f"signal_pools={data_quality['signal_pool_count']}, live_triggers_24h={data_quality['live_trigger_count_24h']}, "
                f"ai_decisions_7d={data_quality['decision_count_7d']}, closed_outcomes_7d={data_quality['closed_outcome_count_7d']}. "
                f"Accuracy self-check: kline={self_check['kline_coverage']}, flow={self_check['market_flow_freshness']}, "
                f"signals={self_check['signal_sample']}, outcomes={self_check['closed_trade_outcomes']}, "
                f"performance={self_check['performance_accuracy']}. "
                "Main AI must treat strategy performance as unvalidated until a completed backtest or enough closed trades exists."
            ),
            "direction": "neutral",
            "confidence": 0.22 if data_quality["backtest_readiness"] == "ready_for_backtest" else 0.12,
            "risk_level": risk_level,
            "raw_payload": {
                "account_id": account_id,
                "exchange": exchange,
                "symbols": symbols,
                "timeframe": timeframe,
                "completed_backtests": 0,
                "prompt_task_count": 0,
                "data_quality": data_quality,
            },
        }

    completed = [row for row in recent_results if row.status == "completed"]
    errored = [row for row in recent_results if row.status == "error"]
    running = [row for row in recent_results if row.status == "running"]
    latest = recent_results[0] if recent_results else None
    latest_completed = next((row for row in recent_results if row.status == "completed"), None)

    pnl_values = [
        value
        for value in (_to_float(row.total_pnl_percent) for row in completed)
        if value is not None
    ]
    avg_pnl_pct = sum(pnl_values) / len(pnl_values) if pnl_values else None
    latest_pnl_pct = _to_float(latest_completed.total_pnl_percent) if latest_completed else None
    latest_win_rate = _to_float(latest_completed.win_rate) if latest_completed else None
    latest_profit_factor = _to_float(latest_completed.profit_factor) if latest_completed else None
    max_drawdown_values = [
        abs(value)
        for value in (_to_float(row.max_drawdown_percent) for row in completed)
        if value is not None
    ]
    worst_drawdown_pct = max(max_drawdown_values) if max_drawdown_values else None

    trigger_symbols: List[str] = []
    if latest_completed:
        trigger_logs = (
            db.query(BacktestTriggerLog)
            .filter(BacktestTriggerLog.backtest_id == latest_completed.id)
            .order_by(desc(BacktestTriggerLog.trigger_index))
            .limit(120)
            .all()
        )
        seen_symbols = set()
        for log in trigger_logs:
            symbol = str(log.symbol or log.decision_symbol or "").upper()
            if symbol and symbol not in seen_symbols:
                seen_symbols.add(symbol)
                trigger_symbols.append(symbol)

    prompt_total_items = sum(int(task.total_count or 0) for task in prompt_tasks)
    prompt_completed_items = sum(int(task.completed_count or 0) for task in prompt_tasks)
    prompt_failed_items = sum(int(task.failed_count or 0) for task in prompt_tasks)
    prompt_fail_rate = (prompt_failed_items / prompt_total_items) if prompt_total_items else 0.0

    if avg_pnl_pct is not None:
        if avg_pnl_pct > 0 and (latest_pnl_pct is None or latest_pnl_pct >= 0):
            direction = "bullish"
        elif avg_pnl_pct < 0 or (latest_pnl_pct is not None and latest_pnl_pct < 0):
            direction = "bearish"
        else:
            direction = "neutral"
    else:
        direction = "neutral"

    risk_level = "low"
    if (
        len(errored) >= 2
        or (latest_pnl_pct is not None and latest_pnl_pct <= -5)
        or (worst_drawdown_pct is not None and worst_drawdown_pct >= 20)
        or prompt_fail_rate >= 0.3
    ):
        risk_level = "high"
    elif (
        errored
        or running
        or (latest_pnl_pct is not None and latest_pnl_pct < 0)
        or (worst_drawdown_pct is not None and worst_drawdown_pct >= 10)
        or prompt_fail_rate >= 0.1
    ):
        risk_level = "medium"

    confidence = _clamp(
        0.2 + min(len(completed), 10) * 0.055 + min(prompt_completed_items, 20) * 0.006,
        0.0,
        0.82,
    )
    if not completed:
        confidence = min(confidence, 0.25)
    if risk_level == "high":
        confidence *= 0.85

    status = "ok"
    if not completed:
        status = "missing" if not recent_results else "warning"
    elif errored or running or prompt_failed_items:
        status = "warning"

    latest_status = latest.status if latest else "none"
    latest_id = latest.id if latest else None
    summary = (
        f"Backtest Data AI ({exchange}/{timeframe}): {len(recent_results)} recent program backtests, "
        f"completed={len(completed)}, running={len(running)}, errors={len(errored)}. "
        f"Latest=#{latest_id or 'none'} status={latest_status}; latest_completed_pnl="
        f"{_format_number(latest_pnl_pct, 2)}%, avg_completed_pnl={_format_number(avg_pnl_pct, 2)}%, "
        f"win_rate={_format_number(latest_win_rate, 1)}%, profit_factor={_format_number(latest_profit_factor, 2)}, "
        f"worst_drawdown={_format_number(worst_drawdown_pct, 2)}%, trades="
        f"{latest_completed.total_trades if latest_completed else 'N/A'}, symbols={trigger_symbols[:6] or symbols[:6]}. "
        f"Prompt backtests: tasks={len(prompt_tasks)}, completed_items={prompt_completed_items}/{prompt_total_items}, "
        f"failed_items={prompt_failed_items}. "
        f"Data quality: kline={data_quality['kline_ready_count']}/{data_quality['symbol_count']}, "
        f"flow={data_quality['flow_ready_count']}/{data_quality['symbol_count']}, "
        f"closed_outcomes_7d={data_quality['closed_outcome_count_7d']}. "
        f"Accuracy self-check={data_quality['accuracy_self_check']}. "
        "Main AI should lower confidence when recent backtests are missing, negative, stale, or based on sparse data."
    )

    return {
        "module": MODULE_BACKTEST,
        "status": status,
        "summary": summary,
        "direction": direction,
        "confidence": confidence,
        "risk_level": risk_level,
        "raw_payload": {
            "account_id": account_id,
            "exchange": exchange,
            "symbols": symbols,
            "timeframe": timeframe,
            "recent_backtest_count": len(recent_results),
            "completed_count": len(completed),
            "running_count": len(running),
            "error_count": len(errored),
            "latest_backtest_id": latest_id,
            "latest_completed_id": latest_completed.id if latest_completed else None,
            "latest_pnl_percent": latest_pnl_pct,
            "average_pnl_percent": avg_pnl_pct,
            "latest_win_rate": latest_win_rate,
            "latest_profit_factor": latest_profit_factor,
            "worst_drawdown_percent": worst_drawdown_pct,
            "trigger_symbols": trigger_symbols,
            "prompt_task_count": len(prompt_tasks),
            "prompt_total_items": prompt_total_items,
            "prompt_completed_items": prompt_completed_items,
            "prompt_failed_items": prompt_failed_items,
            "prompt_fail_rate": prompt_fail_rate,
            "data_quality": data_quality,
        },
    }
