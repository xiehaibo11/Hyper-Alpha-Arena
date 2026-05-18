"""SSE program-binding backtest routes."""

import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import AccountProgramBinding, BacktestResult, BacktestTriggerLog, SignalPool, TradingProgram
from routes.program_schemas import ProgramBacktestRequest

router = APIRouter()

async def run_backtest(request: ProgramBacktestRequest, db: Session = Depends(get_db)):
    """
    Run backtest for a program binding with SSE progress updates.

    Returns Server-Sent Events with:
    - type: "init" - Initial trigger count
    - type: "progress" - Execution progress updates
    - type: "complete" - Final results
    - type: "error" - Error message
    """
    from backtest import (
        BacktestConfig, ProgramBacktestEngine,
        BacktestResult as BacktestResultData, TriggerEvent
    )
    from backtest.engine import INTERVAL_MS
    import time

    # Clamp end_time to current time (no future backtesting)
    now_ms = int(time.time() * 1000)
    if request.end_time_ms > now_ms:
        request.end_time_ms = now_ms

    # Validate time range
    if request.end_time_ms <= request.start_time_ms:
        raise HTTPException(status_code=400, detail="End time must be after start time")

    # Get binding info
    binding = db.query(AccountProgramBinding).filter(
        AccountProgramBinding.id == request.binding_id,
        AccountProgramBinding.is_deleted != True
    ).first()

    if not binding:
        raise HTTPException(status_code=404, detail="Binding not found")

    # Get program
    program = db.query(TradingProgram).filter(
        TradingProgram.id == binding.program_id,
        TradingProgram.is_deleted != True
    ).first()

    if not program:
        raise HTTPException(status_code=404, detail="Program not found")

    # Get exchange from binding (unified source for both execution and backtest)
    exchange = getattr(binding, 'exchange', None) or 'hyperliquid'

    # Get signal pool symbols
    signal_pool_ids = []
    symbols = set()

    if binding.signal_pool_ids:
        pool_ids = binding.signal_pool_ids
        if isinstance(pool_ids, str):
            pool_ids = json.loads(pool_ids)
        signal_pool_ids = pool_ids

        for pool_id in pool_ids:
            pool = db.query(SignalPool).filter(SignalPool.id == pool_id, SignalPool.is_deleted != True).first()
            if pool:
                if pool.symbols:
                    # symbols is a list field
                    pool_symbols = pool.symbols
                    if isinstance(pool_symbols, str):
                        pool_symbols = json.loads(pool_symbols)
                    for sym in pool_symbols:
                        symbols.add(sym)

    # Default to BTC if no symbols found
    if not symbols:
        symbols = {"BTC"}

    # Determine scheduled interval (in seconds)
    scheduled_interval_sec = None
    if binding.scheduled_trigger_enabled and binding.trigger_interval:
        scheduled_interval_sec = binding.trigger_interval  # Already in seconds

    # Create backtest config
    config = BacktestConfig(
        code=program.code,
        signal_pool_ids=signal_pool_ids,
        symbols=list(symbols),
        start_time_ms=request.start_time_ms,
        end_time_ms=request.end_time_ms,
        scheduled_interval_sec=scheduled_interval_sec,
        initial_balance=request.initial_balance,
        slippage_percent=request.slippage_percent,
        fee_rate=request.fee_rate,
        exchange=exchange,
    )

    async def generate_events():
        """Generate SSE events during backtest execution."""
        engine = ProgramBacktestEngine(db)
        backtest_record = None

        try:
            # Phase 1: Generate triggers (send calculating status)
            yield f"data: {json.dumps({'type': 'calculating', 'message': 'Calculating trigger points...'})}\n\n"
            await asyncio.sleep(0.01)

            triggers = engine._generate_trigger_events(config)

            # Allow backtest with no signal triggers if scheduled triggers are enabled
            if not triggers and not config.scheduled_interval_sec:
                yield f"data: {json.dumps({'type': 'error', 'message': 'No triggers generated. Add signal pools or enable scheduled trigger.'})}\n\n"
                return

            # Create backtest record in database
            backtest_record = BacktestResult(
                backtest_type="program",
                binding_id=request.binding_id,
                user_id=binding.account.user_id if binding.account else None,
                config=json.dumps({
                    "signal_pool_ids": signal_pool_ids,
                    "symbols": list(symbols),
                    "scheduled_interval_sec": scheduled_interval_sec,
                    "slippage_percent": request.slippage_percent,
                    "fee_rate": request.fee_rate,
                }),
                start_time=config.start_time,
                end_time=config.end_time,
                initial_balance=config.initial_balance,
                total_triggers=len(triggers),
                status="running",
                exchange=exchange,
            )
            db.add(backtest_record)
            db.commit()
            db.refresh(backtest_record)

            # Estimate total triggers including dynamic scheduled triggers
            estimated_total = engine.estimate_total_triggers(config, triggers)

            # Send init event with estimated trigger count and backtest_id
            yield f"data: {json.dumps({'type': 'init', 'total_triggers': estimated_total, 'backtest_id': backtest_record.id})}\n\n"
            await asyncio.sleep(0.01)

            # Phase 2: Run backtest with progress updates
            async for event in _run_backtest_with_progress(engine, config, triggers, db, backtest_record.id):
                yield event

        except Exception as e:
            if backtest_record:
                backtest_record.status = "error"
                backtest_record.error_message = str(e)
                db.commit()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


async def _run_backtest_with_progress(engine, config, signal_triggers, db, backtest_id):
    """
    Run backtest event loop with progress updates and database logging.

    Uses engine.run_event_loop_generator for core logic (including dynamic scheduled triggers).
    This function only handles SSE progress updates and database logging.
    """
    from backtest import VirtualAccount, ExecutionSimulator, HistoricalDataProvider, TriggerExecutionResult
    from datetime import datetime, timezone
    import time

    start_time = time.time()

    # Initialize components (passed to engine generator)
    account = VirtualAccount(initial_balance=config.initial_balance)
    simulator = ExecutionSimulator(
        slippage_percent=config.slippage_percent,
        fee_rate=config.fee_rate,
    )
    data_provider = HistoricalDataProvider(
        db=engine.db,
        symbols=config.symbols,
        start_time_ms=config.start_time_ms,
        end_time_ms=config.end_time_ms,
        exchange=config.exchange,
    )

    trades = []
    equity_curve = []
    all_triggers = []
    trigger_log_index = 0

    # Estimate total triggers for progress (signal + estimated scheduled)
    # This is approximate since scheduled triggers are dynamic
    estimated_total = len(signal_triggers)
    if config.scheduled_interval_sec:
        interval_ms = config.scheduled_interval_sec * 1000
        if interval_ms > 0:
            duration_ms = config.end_time_ms - config.start_time_ms
            estimated_total += int(duration_ms / interval_ms)

    progress_interval = max(1, estimated_total // 50)
    processed_count = 0

    # Use engine's generator for core logic
    for exec_result in engine.run_event_loop_generator(
        config, signal_triggers, account, simulator, data_provider
    ):
        trigger = exec_result.trigger
        all_triggers.append(trigger)

        # Record TP/SL trades (each trade has its own equity_after calculated immediately after execution)
        for tp_sl_trade in exec_result.tp_sl_trades:
            trades.append(tp_sl_trade)
            tp_sl_time = datetime.fromtimestamp(tp_sl_trade.exit_timestamp / 1000, tz=timezone.utc)
            tp_sl_log = BacktestTriggerLog(
                backtest_id=backtest_id,
                trigger_index=trigger_log_index,
                trigger_type=tp_sl_trade.exit_reason,
                trigger_time=tp_sl_time,
                symbol=tp_sl_trade.symbol,
                decision_type="program",
                decision_action="close",
                decision_symbol=tp_sl_trade.symbol,
                decision_side=tp_sl_trade.side,
                decision_size=tp_sl_trade.size,
                decision_reason=tp_sl_trade.reason,
                entry_price=tp_sl_trade.entry_price,
                exit_price=tp_sl_trade.exit_price,
                pnl=0,
                fee=tp_sl_trade.fee,
                unrealized_pnl=0,
                realized_pnl=tp_sl_trade.pnl,
                equity_before=exec_result.equity_before,
                equity_after=tp_sl_trade.equity_after,  # Use trade's own equity_after
                decision_input=json.dumps({
                    "trigger": tp_sl_trade.exit_reason.upper(),
                    "entry_price": tp_sl_trade.entry_price,
                    "exit_price": tp_sl_trade.exit_price,
                }),
                decision_output=None,
            )
            db.add(tp_sl_log)
            trigger_log_index += 1
            # Add equity_curve point for TP/SL trigger
            equity_curve.append({
                "timestamp": tp_sl_trade.exit_timestamp,
                "equity": tp_sl_trade.equity_after,  # Use trade's own equity_after
                "balance": account.balance,
                "trigger_type": tp_sl_trade.exit_reason,  # "tp" or "sl"
            })

        # Record main trigger
        if exec_result.trade:
            trades.append(exec_result.trade)

        equity_curve.append({
            "timestamp": trigger.timestamp,
            "equity": exec_result.equity_after,
            "balance": account.balance,
            "trigger_type": trigger.trigger_type,  # "signal" or "scheduled"
        })

        # Build trigger log data
        trigger_time = datetime.fromtimestamp(trigger.timestamp / 1000, tz=timezone.utc)
        result = exec_result.executor_result
        trade = exec_result.trade

        decision_action = "hold"
        decision_symbol = exec_result.trigger_symbol
        decision_side = None
        decision_size = None
        decision_reason = ""
        entry_price = exec_result.prices.get(exec_result.trigger_symbol, 0)
        trade_fee = 0.0
        trade_realized_pnl = 0.0
        execution_error = None

        # Use snapshots from BEFORE strategy execution
        decision_input = {
            "balance": exec_result.balance_before,
            "equity": exec_result.equity_after_tp_sl,  # Equity after TP/SL but before strategy
            "used_margin": exec_result.used_margin_before,
            "margin_usage_percent": exec_result.margin_usage_percent_before,
            "trigger_type": trigger.trigger_type,
            "trigger_symbol": exec_result.trigger_symbol,
            "prices": exec_result.prices,
            "positions": exec_result.positions_before,
            "signal_pool_name": trigger.pool_name or "",
            "pool_logic": trigger.pool_logic or "OR",
            "triggered_signals": trigger.triggered_signals or [],
            "trigger_market_regime": trigger.market_regime,
        }

        for pos in decision_input.get("positions", {}).values():
            opened_at = pos.get("opened_at")
            if opened_at:
                utc_dt = datetime.fromtimestamp(opened_at / 1000, tz=timezone.utc)
                pos["opened_at_str"] = utc_dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                holding_duration_seconds = max(0.0, (trigger.timestamp - opened_at) / 1000)
                pos["holding_duration_seconds"] = holding_duration_seconds
                hours = int(holding_duration_seconds // 3600)
                minutes = int((holding_duration_seconds % 3600) // 60)
                pos["holding_duration_str"] = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"

        decision_output = None
        if result and result.success and result.decision:
            decision = result.decision
            decision_action = decision.operation
            decision_symbol = decision.symbol or exec_result.trigger_symbol
            decision_reason = decision.reason
            decision_output = decision.to_dict() if hasattr(decision, 'to_dict') else {
                "operation": decision.operation,
                "symbol": decision.symbol,
                "reason": decision.reason,
            }
            if trade:
                decision_side = trade.side
                decision_size = trade.size
                entry_price = trade.entry_price
                trade_fee = trade.fee
                trade_realized_pnl = trade.pnl if trade.operation == "close" else 0
        elif result and not result.success:
            execution_error = result.error

        execution_logs = result.logs if result else []

        trigger_log = BacktestTriggerLog(
            backtest_id=backtest_id,
            trigger_index=trigger_log_index,
            trigger_type=trigger.trigger_type,
            trigger_time=trigger_time,
            symbol=exec_result.trigger_symbol,
            decision_type="program",
            decision_action=decision_action,
            decision_symbol=decision_symbol,
            decision_side=decision_side,
            decision_size=decision_size,
            decision_reason=decision_reason,
            entry_price=entry_price,
            pnl=0,
            fee=trade_fee,
            unrealized_pnl=exec_result.unrealized_pnl,
            realized_pnl=trade_realized_pnl,
            equity_before=exec_result.equity_before,
            equity_after=exec_result.equity_after,
            decision_input=json.dumps(decision_input),
            decision_output=json.dumps(decision_output) if decision_output else None,
            data_queries=json.dumps(exec_result.data_queries) if exec_result.data_queries else None,
            execution_logs=json.dumps(execution_logs) if execution_logs else None,
            execution_error=execution_error,
        )
        db.add(trigger_log)
        trigger_log_index += 1

        if trigger_log_index % 100 == 0:
            db.commit()

        processed_count += 1
        if processed_count % progress_interval == 0:
            yield f"data: {json.dumps({'type': 'progress', 'current': processed_count, 'total': estimated_total, 'equity': exec_result.equity_after})}\n\n"
            await asyncio.sleep(0.001)

    db.commit()

    # Calculate final statistics using all_triggers (includes dynamic scheduled)
    calc_result = engine._calculate_result(trades, equity_curve, all_triggers, account, config)
    calc_result.execution_time_ms = (time.time() - start_time) * 1000

    # Update backtest record
    backtest_record = db.query(BacktestResult).filter(BacktestResult.id == backtest_id).first()
    if backtest_record:
        backtest_record.final_equity = account.equity
        backtest_record.total_pnl = calc_result.total_pnl
        backtest_record.total_pnl_percent = calc_result.total_pnl_percent
        backtest_record.max_drawdown = calc_result.max_drawdown
        backtest_record.max_drawdown_percent = calc_result.max_drawdown_percent
        backtest_record.total_trades = calc_result.total_trades
        backtest_record.winning_trades = calc_result.winning_trades
        backtest_record.losing_trades = calc_result.losing_trades
        backtest_record.win_rate = calc_result.win_rate
        backtest_record.profit_factor = calc_result.profit_factor
        backtest_record.sharpe_ratio = calc_result.sharpe_ratio
        backtest_record.equity_curve = json.dumps(equity_curve)
        backtest_record.execution_time_ms = int(calc_result.execution_time_ms)
        backtest_record.total_triggers = calc_result.total_triggers  # Update with actual count
        backtest_record.status = "completed"
        backtest_record.completed_at = datetime.now(timezone.utc)
        db.commit()

    complete_data = {
        "type": "complete",
        "backtest_id": backtest_id,
        "success": calc_result.success,
        "total_pnl": calc_result.total_pnl,
        "total_pnl_percent": calc_result.total_pnl_percent,
        "max_drawdown": calc_result.max_drawdown,
        "max_drawdown_percent": calc_result.max_drawdown_percent,
        "sharpe_ratio": calc_result.sharpe_ratio,
        "total_trades": calc_result.total_trades,
        "winning_trades": calc_result.winning_trades,
        "losing_trades": calc_result.losing_trades,
        "win_rate": calc_result.win_rate,
        "profit_factor": calc_result.profit_factor,
        "avg_win": calc_result.avg_win,
        "avg_loss": calc_result.avg_loss,
        "largest_win": calc_result.largest_win,
        "largest_loss": calc_result.largest_loss,
        "total_triggers": calc_result.total_triggers,
        "signal_triggers": calc_result.signal_triggers,
        "scheduled_triggers": calc_result.scheduled_triggers,
        "execution_time_ms": calc_result.execution_time_ms,
        "equity_curve": calc_result.equity_curve,
        "trades": [_trade_to_dict(t) for t in calc_result.trades],
    }
    yield f"data: {json.dumps(complete_data)}\n\n"


def _trade_to_dict(trade):
    """Convert BacktestTradeRecord to dict."""
    return {
        "timestamp": trade.timestamp,
        "trigger_type": trade.trigger_type,
        "symbol": trade.symbol,
        "operation": trade.operation,
        "side": trade.side,
        "entry_price": trade.entry_price,
        "size": trade.size,
        "leverage": trade.leverage,
        "exit_price": trade.exit_price,
        "exit_timestamp": trade.exit_timestamp,
        "exit_reason": trade.exit_reason,
        "pnl": trade.pnl,
        "pnl_percent": trade.pnl_percent,
        "fee": trade.fee,
        "reason": trade.reason,
        "pool_name": trade.pool_name,
        "triggered_signals": trade.triggered_signals,
    }


# ============================================================================
