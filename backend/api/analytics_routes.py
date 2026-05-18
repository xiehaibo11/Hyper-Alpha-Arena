"""
Strategy Analytics API routes.
Provides multi-dimensional analysis of trading decisions and performance.
"""

from datetime import date
from typing import Optional, List, Dict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.analytics_trade_list_routes import router as analytics_trade_list_router
from api.analytics_trade_replay_routes import router as analytics_trade_replay_router
from database.connection import SessionLocal
from database.models import AIDecisionLog, Account, PromptTemplate, ProgramExecutionLog, TradingProgram
from services.analytics_ai_helpers import (
    build_base_query,
    calculate_metrics,
    get_fees_for_decisions,
    get_trigger_type,
)
from services.analytics_program_helpers import build_program_base_query, get_fees_for_program_logs

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
router.include_router(analytics_trade_list_router)
router.include_router(analytics_trade_replay_router)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============== Pydantic Models ==============

class MetricsResponse(BaseModel):
    total_pnl: float
    total_fee: float
    net_pnl: float
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: float
    avg_win: Optional[float]
    avg_loss: Optional[float]
    profit_factor: Optional[float]


class DataCompleteness(BaseModel):
    total_decisions: int
    with_strategy: int
    with_signal: int
    with_pnl: int


class TriggerTypeBreakdown(BaseModel):
    count: int
    net_pnl: float


# ============== API Endpoints ==============

@router.get("/summary")
def get_analytics_summary(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    account_id: Optional[int] = Query(None),
    exchange: Optional[str] = Query("all"),
    db: Session = Depends(get_db),
):
    """Get overall analytics summary (AI Decision + Program Decision combined)."""
    # === AI Decision data ===
    ai_query = build_base_query(db, start_date, end_date, environment, account_id, exchange)
    decisions = ai_query.all()
    fee_map = get_fees_for_decisions(decisions)

    ai_records = []
    ai_signal_records = []
    ai_scheduled_records = []
    ai_unknown_records = []

    with_strategy = 0
    with_signal = 0
    ai_with_pnl = 0

    for d in decisions:
        pnl = float(d.realized_pnl) if d.realized_pnl else 0
        fee = fee_map.get(d.id, 0.0)
        record = {"pnl": pnl, "fee": fee}
        ai_records.append(record)

        trigger_type = get_trigger_type(d)
        if trigger_type == "signal":
            ai_signal_records.append(record)
        elif trigger_type == "scheduled":
            ai_scheduled_records.append(record)
        else:
            ai_unknown_records.append(record)

        if d.prompt_template_id:
            with_strategy += 1
        if d.signal_trigger_id:
            with_signal += 1
        if d.realized_pnl:
            ai_with_pnl += 1

    # === Program Decision data ===
    prog_query = build_program_base_query(db, start_date, end_date, environment, account_id, exchange)
    prog_logs = prog_query.all()
    prog_fee_map = get_fees_for_program_logs(prog_logs)

    prog_records = []
    prog_signal_records = []
    prog_scheduled_records = []

    with_program = 0
    prog_with_signal = 0
    prog_with_pnl = 0

    for log in prog_logs:
        pnl = float(log.realized_pnl) if log.realized_pnl else 0
        fee = prog_fee_map.get(log.id, 0.0)

        if pnl == 0:
            continue

        record = {"pnl": pnl, "fee": fee}
        prog_records.append(record)

        trigger_type = log.trigger_type or "scheduled"
        if trigger_type == "signal":
            prog_signal_records.append(record)
        else:
            prog_scheduled_records.append(record)

        if log.program_id:
            with_program += 1
        if log.signal_pool_id:
            prog_with_signal += 1
        prog_with_pnl += 1

    # === Combined metrics ===
    all_records = ai_records + prog_records
    overview = calculate_metrics(all_records)

    return {
        "period": {
            "start": start_date.isoformat() if start_date else None,
            "end": end_date.isoformat() if end_date else None,
        },
        "overview": overview,
        "data_completeness": {
            "total_decisions": len(decisions),
            "total_program_executions": len(prog_logs),
            "with_strategy": with_strategy,
            "with_program": with_program,
            "with_signal": with_signal + prog_with_signal,
            "with_pnl": ai_with_pnl + prog_with_pnl,
        },
        "by_trigger_type": {
            "signal": {
                "count": len(ai_signal_records) + len(prog_signal_records),
                "net_pnl": round(sum(r["pnl"] - r["fee"] for r in ai_signal_records + prog_signal_records), 2),
            },
            "scheduled": {
                "count": len(ai_scheduled_records) + len(prog_scheduled_records),
                "net_pnl": round(sum(r["pnl"] - r["fee"] for r in ai_scheduled_records + prog_scheduled_records), 2),
            },
            "unknown": {
                "count": len(ai_unknown_records),
                "net_pnl": round(sum(r["pnl"] - r["fee"] for r in ai_unknown_records), 2),
            },
        },
        "by_source": {
            "ai_decision": {
                "count": len(ai_records),
                "net_pnl": round(sum(r["pnl"] - r["fee"] for r in ai_records), 2),
            },
            "program": {
                "count": len(prog_records),
                "net_pnl": round(sum(r["pnl"] - r["fee"] for r in prog_records), 2),
            },
        },
    }


@router.get("/by-strategy")
def get_analytics_by_strategy(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    account_id: Optional[int] = Query(None),
    exchange: Optional[str] = Query("all"),
    db: Session = Depends(get_db),
):
    """Get analytics grouped by strategy (prompt template)."""
    query = build_base_query(db, start_date, end_date, environment, account_id, exchange)
    decisions = query.all()

    # Get fees for all decisions
    fee_map = get_fees_for_decisions(decisions)

    # Group by strategy
    by_strategy: Dict[Optional[int], List[Dict]] = {}
    strategy_names: Dict[int, str] = {}

    for d in decisions:
        strategy_id = d.prompt_template_id
        pnl = float(d.realized_pnl) if d.realized_pnl else 0
        fee = fee_map.get(d.id, 0.0)
        record = {
            "pnl": pnl,
            "fee": fee,
            "trigger_type": get_trigger_type(d),
        }

        if strategy_id not in by_strategy:
            by_strategy[strategy_id] = []
        by_strategy[strategy_id].append(record)

    # Get strategy names
    strategy_ids = [sid for sid in by_strategy.keys() if sid is not None]
    if strategy_ids:
        templates = db.query(PromptTemplate).filter(
            PromptTemplate.id.in_(strategy_ids),
            PromptTemplate.is_deleted == "false"
        ).all()
        strategy_names = {t.id: t.name for t in templates}

    # Build response
    items = []
    for strategy_id, records in by_strategy.items():
        if strategy_id is None:
            continue

        signal_records = [r for r in records if r["trigger_type"] == "signal"]
        scheduled_records = [r for r in records if r["trigger_type"] == "scheduled"]

        items.append({
            "strategy_id": strategy_id,
            "strategy_name": strategy_names.get(strategy_id, f"Strategy {strategy_id}"),
            "metrics": calculate_metrics(records),
            "by_trigger_type": {
                "signal": {"count": len(signal_records), "net_pnl": round(sum(r["pnl"] - r["fee"] for r in signal_records), 2)},
                "scheduled": {"count": len(scheduled_records), "net_pnl": round(sum(r["pnl"] - r["fee"] for r in scheduled_records), 2)},
            },
        })

    # Sort by net_pnl descending
    items.sort(key=lambda x: x["metrics"]["net_pnl"], reverse=True)

    # Unattributed (no strategy)
    unattributed_records = by_strategy.get(None, [])

    return {
        "items": items,
        "unattributed": {
            "count": len(unattributed_records),
            "metrics": calculate_metrics(unattributed_records) if unattributed_records else None,
        },
    }


@router.get("/by-account")
def get_analytics_by_account(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    exchange: Optional[str] = Query("all"),
    db: Session = Depends(get_db),
):
    """Get analytics grouped by account."""
    query = build_base_query(db, start_date, end_date, environment, None, exchange)
    decisions = query.all()

    # Get fees for all decisions
    fee_map = get_fees_for_decisions(decisions)

    # Group by account
    by_account: Dict[Optional[int], List[Dict]] = {}

    for d in decisions:
        account_id = d.account_id
        pnl = float(d.realized_pnl) if d.realized_pnl else 0
        fee = fee_map.get(d.id, 0.0)
        record = {"pnl": pnl, "fee": fee, "trigger_type": get_trigger_type(d)}

        if account_id not in by_account:
            by_account[account_id] = []
        by_account[account_id].append(record)

    # Get account info (name, current model)
    account_ids = [aid for aid in by_account.keys() if aid is not None]
    account_info: Dict[int, Dict] = {}
    if account_ids:
        accounts = db.query(Account).filter(
            Account.id.in_(account_ids),
            Account.is_deleted != True
        ).all()
        account_info = {
            a.id: {"name": a.name, "model": a.model, "environment": a.hyperliquid_environment}
            for a in accounts
        }

    # Build response
    items = []
    for account_id, records in by_account.items():
        if account_id is None:
            continue

        info = account_info.get(account_id, {})
        signal_records = [r for r in records if r["trigger_type"] == "signal"]
        scheduled_records = [r for r in records if r["trigger_type"] == "scheduled"]

        items.append({
            "account_id": account_id,
            "account_name": info.get("name", f"Account {account_id}"),
            "model": info.get("model"),
            "environment": info.get("environment"),
            "metrics": calculate_metrics(records),
            "by_trigger_type": {
                "signal": {"count": len(signal_records), "net_pnl": round(sum(r["pnl"] - r["fee"] for r in signal_records), 2)},
                "scheduled": {"count": len(scheduled_records), "net_pnl": round(sum(r["pnl"] - r["fee"] for r in scheduled_records), 2)},
            },
        })

    # Sort by net_pnl descending
    items.sort(key=lambda x: x["metrics"]["net_pnl"], reverse=True)

    # Unattributed (no account)
    unattributed_records = by_account.get(None, [])

    return {
        "items": items,
        "unattributed": {
            "count": len(unattributed_records),
            "metrics": calculate_metrics(unattributed_records) if unattributed_records else None,
        },
    }


@router.get("/by-symbol")
def get_analytics_by_symbol(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    account_id: Optional[int] = Query(None),
    exchange: Optional[str] = Query("all"),
    db: Session = Depends(get_db),
):
    """Get analytics grouped by trading symbol."""
    query = build_base_query(db, start_date, end_date, environment, account_id, exchange)
    decisions = query.all()

    # Get fees for all decisions
    fee_map = get_fees_for_decisions(decisions)

    # Group by symbol
    by_symbol: Dict[Optional[str], List[Dict]] = {}

    for d in decisions:
        symbol = d.symbol
        pnl = float(d.realized_pnl) if d.realized_pnl else 0
        fee = fee_map.get(d.id, 0.0)
        record = {"pnl": pnl, "fee": fee, "trigger_type": get_trigger_type(d)}

        if symbol not in by_symbol:
            by_symbol[symbol] = []
        by_symbol[symbol].append(record)

    # Build response
    items = []
    for symbol, records in by_symbol.items():
        if symbol is None:
            continue

        signal_records = [r for r in records if r["trigger_type"] == "signal"]
        scheduled_records = [r for r in records if r["trigger_type"] == "scheduled"]

        items.append({
            "symbol": symbol,
            "metrics": calculate_metrics(records),
            "by_trigger_type": {
                "signal": {"count": len(signal_records), "net_pnl": round(sum(r["pnl"] - r["fee"] for r in signal_records), 2)},
                "scheduled": {"count": len(scheduled_records), "net_pnl": round(sum(r["pnl"] - r["fee"] for r in scheduled_records), 2)},
            },
        })

    # Sort by net_pnl descending
    items.sort(key=lambda x: x["metrics"]["net_pnl"], reverse=True)

    # Unattributed (no symbol)
    unattributed_records = by_symbol.get(None, [])

    return {
        "items": items,
        "unattributed": {
            "count": len(unattributed_records),
            "metrics": calculate_metrics(unattributed_records) if unattributed_records else None,
        },
    }


@router.get("/by-operation")
def get_analytics_by_operation(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    account_id: Optional[int] = Query(None),
    exchange: Optional[str] = Query("all"),
    db: Session = Depends(get_db),
):
    """Get analytics grouped by operation type (buy/sell/close)."""
    query = build_base_query(db, start_date, end_date, environment, account_id, exchange)
    decisions = query.all()

    # Get fees for all decisions
    fee_map = get_fees_for_decisions(decisions)

    # Group by operation
    by_operation: Dict[str, List[Dict]] = {}

    for d in decisions:
        operation = d.operation or "unknown"
        pnl = float(d.realized_pnl) if d.realized_pnl else 0
        fee = fee_map.get(d.id, 0.0)
        record = {"pnl": pnl, "fee": fee, "trigger_type": get_trigger_type(d)}

        if operation not in by_operation:
            by_operation[operation] = []
        by_operation[operation].append(record)

    # Build response
    items = []
    for operation, records in by_operation.items():
        signal_records = [r for r in records if r["trigger_type"] == "signal"]
        scheduled_records = [r for r in records if r["trigger_type"] == "scheduled"]

        items.append({
            "operation": operation,
            "metrics": calculate_metrics(records),
            "by_trigger_type": {
                "signal": {"count": len(signal_records), "net_pnl": round(sum(r["pnl"] - r["fee"] for r in signal_records), 2)},
                "scheduled": {"count": len(scheduled_records), "net_pnl": round(sum(r["pnl"] - r["fee"] for r in scheduled_records), 2)},
            },
        })

    # Sort by trade_count descending
    items.sort(key=lambda x: x["metrics"]["trade_count"], reverse=True)

    return {"items": items}


@router.get("/by-trigger-type")
def get_analytics_by_trigger_type(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    account_id: Optional[int] = Query(None),
    exchange: Optional[str] = Query("all"),
    db: Session = Depends(get_db),
):
    """Get analytics grouped by trigger type (signal/scheduled/unknown)."""
    query = build_base_query(db, start_date, end_date, environment, account_id, exchange)
    decisions = query.all()

    # Get fees for all decisions
    fee_map = get_fees_for_decisions(decisions)

    # Group by trigger type
    by_trigger: Dict[str, List[Dict]] = {"signal": [], "scheduled": [], "unknown": []}

    for d in decisions:
        trigger_type = get_trigger_type(d)
        pnl = float(d.realized_pnl) if d.realized_pnl else 0
        fee = fee_map.get(d.id, 0.0)
        record = {"pnl": pnl, "fee": fee}
        by_trigger[trigger_type].append(record)

    # Build response
    items = []
    for trigger_type in ["signal", "scheduled", "unknown"]:
        records = by_trigger[trigger_type]
        if records:
            items.append({
                "trigger_type": trigger_type,
                "metrics": calculate_metrics(records),
            })

    # Sort by trade_count descending
    items.sort(key=lambda x: x["metrics"]["trade_count"], reverse=True)

    return {"items": items}


@router.get("/by-factor")
def get_analytics_by_factor(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    account_id: Optional[int] = Query(None),
    exchange: Optional[str] = Query("all"),
    db: Session = Depends(get_db),
):
    """Get analytics grouped by factor signal triggers."""
    from database.models import SignalTriggerLog

    query = build_base_query(db, start_date, end_date, environment, account_id, exchange)
    decisions = query.all()
    fee_map = get_fees_for_decisions(decisions)

    # Collect decision IDs that have signal_trigger_id
    trigger_ids = set()
    decision_by_trigger: Dict[int, List] = {}
    for d in decisions:
        if d.signal_trigger_id:
            trigger_ids.add(d.signal_trigger_id)
            decision_by_trigger.setdefault(d.signal_trigger_id, []).append(d)

    if not trigger_ids:
        return {"items": []}

    # Batch load signal trigger logs that have factor data
    triggers = db.query(SignalTriggerLog).filter(
        SignalTriggerLog.id.in_(list(trigger_ids)),
    ).all()

    # Group by factor name (extracted from trigger_value JSON)
    import json as _json
    by_factor: Dict[str, List[Dict]] = {}
    for trig in triggers:
        # Parse trigger_value JSON to find factor info
        if not trig.trigger_value:
            continue
        try:
            tv = trig.trigger_value if isinstance(trig.trigger_value, dict) else _json.loads(trig.trigger_value)
        except (ValueError, TypeError):
            continue
        # Extract factor name from signals_triggered entries
        for sig in tv.get("signals_triggered", []):
            factor_name = sig.get("signal_name") or sig.get("metric")
            if not factor_name:
                continue
        for d in decision_by_trigger.get(trig.id, []):
            pnl = float(d.realized_pnl) if d.realized_pnl else 0
            fee = fee_map.get(d.id, 0.0)
            by_factor.setdefault(factor_name, []).append({"pnl": pnl, "fee": fee})

    items = []
    for factor_name, records in by_factor.items():
        items.append({
            "factor_name": factor_name,
            "metrics": calculate_metrics(records),
        })

    items.sort(key=lambda x: x["metrics"]["trade_count"], reverse=True)
    return {"items": items}


# ============== AI Attribution Analysis Routes ==============

from fastapi.responses import StreamingResponse
from pydantic import BaseModel as PydanticBaseModel
from services.ai_attribution_service import (
    generate_attribution_analysis_stream,
    get_attribution_conversations,
    get_attribution_messages
)


class AiAttributionChatRequest(PydanticBaseModel):
    accountId: int
    userMessage: str
    conversationId: Optional[int] = None
    # SSE direct streaming is unstable (frontend disconnect = task abort). Do NOT set to False.
    useBackgroundTask: bool = True


@router.post("/ai-attribution/chat-stream")
async def ai_attribution_chat_stream(
    request: AiAttributionChatRequest,
    db: Session = Depends(get_db)
):
    """
    SSE streaming endpoint for AI attribution analysis chat.

    Supports two modes:
    - SSE streaming (default): Returns Server-Sent Events directly
    - Background task (useBackgroundTask=true): Returns task_id for polling
    """
    from services.ai_stream_service import get_buffer_manager, generate_task_id, run_ai_task_in_background
    from database.connection import SessionLocal

    # Background task mode
    if request.useBackgroundTask:
        task_id = generate_task_id("attribution")
        manager = get_buffer_manager()

        # Check for existing running task
        if request.conversationId:
            existing = manager.get_pending_task_for_conversation(request.conversationId)
            if existing:
                return {"task_id": existing.task_id, "status": "already_running"}

        manager.create_task(task_id, conversation_id=request.conversationId)

        # Capture request data
        account_id = request.accountId
        user_message = request.userMessage
        conversation_id = request.conversationId

        def generator_func():
            bg_db = SessionLocal()
            try:
                yield from generate_attribution_analysis_stream(
                    db=bg_db,
                    account_id=account_id,
                    user_message=user_message,
                    conversation_id=conversation_id
                )
            finally:
                bg_db.close()

        run_ai_task_in_background(task_id, generator_func)
        return {"task_id": task_id, "status": "started"}

    # SSE streaming mode (default)
    return StreamingResponse(
        generate_attribution_analysis_stream(
            db=db,
            account_id=request.accountId,
            user_message=request.userMessage,
            conversation_id=request.conversationId
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/ai-attribution/conversations")
async def list_attribution_conversations(db: Session = Depends(get_db)):
    """Get list of AI attribution analysis conversations."""
    conversations = get_attribution_conversations(db)
    return {"conversations": conversations}


@router.get("/ai-attribution/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: int,
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """Get messages for a specific conversation with compression points and token usage."""
    import json as json_module
    from database.models import AiAttributionConversation, HyperAiProfile
    from services.ai_context_compression_service import calculate_token_usage, restore_tool_calls_to_messages

    messages = get_attribution_messages(db, conversation_id)

    # Get compression points from conversation
    compression_points = []
    conversation = db.query(AiAttributionConversation).filter(
        AiAttributionConversation.id == conversation_id
    ).first()
    if conversation and conversation.compression_points:
        try:
            compression_points = json_module.loads(conversation.compression_points)
        except (json_module.JSONDecodeError, TypeError):
            compression_points = []

    # Determine model for token calculation: prefer account model, fallback to global
    from database.models import AiAttributionMessage, Account
    from services.ai_context_compression_service import get_last_compression_point
    token_model = None
    api_format = "openai"
    if account_id:
        acct = db.query(Account).filter(Account.id == account_id, Account.is_deleted != True).first()
        if acct and acct.model:
            token_model = acct.model
            from services.ai_decision_service import detect_api_format
            _, fmt = detect_api_format(acct.base_url or "")
            api_format = fmt or "openai"
    if not token_model:
        profile = db.query(HyperAiProfile).first()
        if profile and profile.llm_model:
            token_model = profile.llm_model
            from services.hyper_ai_service import get_llm_config
            llm_config = get_llm_config(db)
            api_format = llm_config.get("api_format", "openai")

    # Calculate token usage (only messages after compression point + summary)
    token_usage = None
    if token_model and messages:
        cp = get_last_compression_point(conversation) if conversation else None
        cp_msg_id = cp.get("message_id", 0) if cp else 0

        history_orm = db.query(AiAttributionMessage).filter(
            AiAttributionMessage.conversation_id == conversation_id,
            AiAttributionMessage.id > cp_msg_id
        ).order_by(AiAttributionMessage.created_at).all()

        msg_dicts = [
            {
                "role": m.role,
                "content": m.content,
                "tool_calls_log": m.tool_calls_log,
                "reasoning_snapshot": m.reasoning_snapshot,
            }
            for m in history_orm
        ]
        msg_list = restore_tool_calls_to_messages(msg_dicts, api_format, model=token_model or "")
        if cp and cp.get("summary"):
            msg_list.insert(0, {"role": "system", "content": cp["summary"]})
        token_usage = calculate_token_usage(msg_list, token_model)

    return {
        "messages": messages,
        "compression_points": compression_points,
        "token_usage": token_usage
    }


# ============== Trade Analytics Subroutes ==============

# /trades endpoints are mounted from analytics_trade_list_routes.py and
# analytics_trade_replay_routes.py.

# ============== Program Analytics API Endpoints ==============

@router.get("/program-summary")
def get_program_analytics_summary(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    account_id: Optional[int] = Query(None),
    exchange: Optional[str] = Query("all"),
    db: Session = Depends(get_db),
):
    """Get overall program analytics summary."""
    query = build_program_base_query(db, start_date, end_date, environment, account_id, exchange)
    logs = query.all()

    # Get fees for all logs (PnL is read from log.realized_pnl)
    fee_map = get_fees_for_program_logs(logs)

    records = []
    signal_records = []
    scheduled_records = []

    with_program = 0
    with_signal = 0

    for log in logs:
        pnl = float(log.realized_pnl) if log.realized_pnl else 0
        fee = fee_map.get(log.id, 0.0)
        record = {"pnl": pnl, "fee": fee}
        records.append(record)

        trigger_type = log.trigger_type or "unknown"
        if trigger_type == "signal":
            signal_records.append(record)
        else:
            scheduled_records.append(record)

        if log.program_id:
            with_program += 1
        if log.signal_pool_id:
            with_signal += 1

    overview = calculate_metrics(records)

    return {
        "period": {
            "start": start_date.isoformat() if start_date else None,
            "end": end_date.isoformat() if end_date else None,
        },
        "overview": overview,
        "data_completeness": {
            "total_executions": len(logs),
            "with_program": with_program,
            "with_signal": with_signal,
            "with_pnl": len(records),
        },
        "by_trigger_type": {
            "signal": {
                "count": len(signal_records),
                "net_pnl": round(sum(r["pnl"] - r["fee"] for r in signal_records), 2),
            },
            "scheduled": {
                "count": len(scheduled_records),
                "net_pnl": round(sum(r["pnl"] - r["fee"] for r in scheduled_records), 2),
            },
        },
    }


@router.get("/program-by-symbol")
def get_program_analytics_by_symbol(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    account_id: Optional[int] = Query(None),
    exchange: Optional[str] = Query("all"),
    db: Session = Depends(get_db),
):
    """Get program analytics grouped by trading symbol."""
    query = build_program_base_query(db, start_date, end_date, environment, account_id, exchange)
    logs = query.all()

    fee_map = get_fees_for_program_logs(logs)

    # Group by symbol
    by_symbol: Dict[Optional[str], List[Dict]] = {}

    for log in logs:
        pnl = float(log.realized_pnl) if log.realized_pnl else 0
        fee = fee_map.get(log.id, 0.0)

        symbol = log.decision_symbol
        record = {"pnl": pnl, "fee": fee, "trigger_type": log.trigger_type or "scheduled"}

        if symbol not in by_symbol:
            by_symbol[symbol] = []
        by_symbol[symbol].append(record)

    # Build response
    items = []
    for symbol, records in by_symbol.items():
        if symbol is None:
            continue

        signal_records = [r for r in records if r["trigger_type"] == "signal"]
        scheduled_records = [r for r in records if r["trigger_type"] != "signal"]

        items.append({
            "symbol": symbol,
            "metrics": calculate_metrics(records),
            "by_trigger_type": {
                "signal": {"count": len(signal_records), "net_pnl": round(sum(r["pnl"] - r["fee"] for r in signal_records), 2)},
                "scheduled": {"count": len(scheduled_records), "net_pnl": round(sum(r["pnl"] - r["fee"] for r in scheduled_records), 2)},
            },
        })

    items.sort(key=lambda x: x["metrics"]["net_pnl"], reverse=True)

    unattributed_records = by_symbol.get(None, [])

    return {
        "items": items,
        "unattributed": {
            "count": len(unattributed_records),
            "metrics": calculate_metrics(unattributed_records) if unattributed_records else None,
        },
    }


@router.get("/program-by-program")
def get_program_analytics_by_program(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    account_id: Optional[int] = Query(None),
    exchange: Optional[str] = Query("all"),
    db: Session = Depends(get_db),
):
    """Get program analytics grouped by trading program."""
    query = build_program_base_query(db, start_date, end_date, environment, account_id, exchange)
    logs = query.all()

    fee_map = get_fees_for_program_logs(logs)

    by_program: Dict[Optional[int], List[Dict]] = {}
    program_names: Dict[int, str] = {}

    for log in logs:
        pnl = float(log.realized_pnl) if log.realized_pnl else 0
        fee = fee_map.get(log.id, 0.0)

        program_id = log.program_id
        record = {"pnl": pnl, "fee": fee, "trigger_type": log.trigger_type or "scheduled"}

        if program_id not in by_program:
            by_program[program_id] = []
        by_program[program_id].append(record)

        if program_id and log.program_name:
            program_names[program_id] = log.program_name

    program_ids = [pid for pid in by_program.keys() if pid is not None]
    if program_ids:
        programs = db.query(TradingProgram).filter(
            TradingProgram.id.in_(program_ids),
            TradingProgram.is_deleted != True
        ).all()
        for p in programs:
            program_names[p.id] = p.name

    items = []
    for program_id, records in by_program.items():
        if program_id is None:
            continue

        signal_records = [r for r in records if r["trigger_type"] == "signal"]
        scheduled_records = [r for r in records if r["trigger_type"] != "signal"]

        items.append({
            "program_id": program_id,
            "program_name": program_names.get(program_id, f"Program {program_id}"),
            "metrics": calculate_metrics(records),
            "by_trigger_type": {
                "signal": {"count": len(signal_records), "net_pnl": round(sum(r["pnl"] - r["fee"] for r in signal_records), 2)},
                "scheduled": {"count": len(scheduled_records), "net_pnl": round(sum(r["pnl"] - r["fee"] for r in scheduled_records), 2)},
            },
        })

    items.sort(key=lambda x: x["metrics"]["net_pnl"], reverse=True)
    unattributed_records = by_program.get(None, [])

    return {
        "items": items,
        "unattributed": {
            "count": len(unattributed_records),
            "metrics": calculate_metrics(unattributed_records) if unattributed_records else None,
        },
    }


@router.get("/program-by-trigger-type")
def get_program_analytics_by_trigger_type(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    account_id: Optional[int] = Query(None),
    exchange: Optional[str] = Query("all"),
    db: Session = Depends(get_db),
):
    """Get program analytics grouped by trigger type."""
    query = build_program_base_query(db, start_date, end_date, environment, account_id, exchange)
    logs = query.all()

    fee_map = get_fees_for_program_logs(logs)

    by_trigger: Dict[str, List[Dict]] = {"signal": [], "scheduled": []}

    for log in logs:
        pnl = float(log.realized_pnl) if log.realized_pnl else 0
        fee = fee_map.get(log.id, 0.0)

        trigger_type = log.trigger_type if log.trigger_type == "signal" else "scheduled"
        record = {"pnl": pnl, "fee": fee}
        by_trigger[trigger_type].append(record)

    items = []
    for trigger_type in ["signal", "scheduled"]:
        records = by_trigger[trigger_type]
        if records:
            items.append({
                "trigger_type": trigger_type,
                "metrics": calculate_metrics(records),
            })

    items.sort(key=lambda x: x["metrics"]["trade_count"], reverse=True)

    return {"items": items}


@router.get("/program-by-operation")
def get_program_analytics_by_operation(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    account_id: Optional[int] = Query(None),
    exchange: Optional[str] = Query("all"),
    db: Session = Depends(get_db),
):
    """Get program analytics grouped by operation type."""
    query = build_program_base_query(db, start_date, end_date, environment, account_id, exchange)
    logs = query.all()

    fee_map = get_fees_for_program_logs(logs)

    by_operation: Dict[str, List[Dict]] = {}

    for log in logs:
        pnl = float(log.realized_pnl) if log.realized_pnl else 0
        fee = fee_map.get(log.id, 0.0)

        operation = log.decision_action or "unknown"
        record = {"pnl": pnl, "fee": fee, "trigger_type": log.trigger_type or "scheduled"}

        if operation not in by_operation:
            by_operation[operation] = []
        by_operation[operation].append(record)

    items = []
    for operation, records in by_operation.items():
        signal_records = [r for r in records if r["trigger_type"] == "signal"]
        scheduled_records = [r for r in records if r["trigger_type"] != "signal"]

        items.append({
            "operation": operation,
            "metrics": calculate_metrics(records),
            "by_trigger_type": {
                "signal": {"count": len(signal_records), "net_pnl": round(sum(r["pnl"] - r["fee"] for r in signal_records), 2)},
                "scheduled": {"count": len(scheduled_records), "net_pnl": round(sum(r["pnl"] - r["fee"] for r in scheduled_records), 2)},
            },
        })

    items.sort(key=lambda x: x["metrics"]["trade_count"], reverse=True)

    return {"items": items}
