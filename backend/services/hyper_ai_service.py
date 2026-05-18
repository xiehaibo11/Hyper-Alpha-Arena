"""
Hyper AI Service - Main Agent for Full-Site AI Intelligence

Hyper AI is the master agent that:
- Guides users through onboarding to collect trading preferences
- Maintains user profile and long-term memory across conversations
- Orchestrates sub-agents (Prompt AI, Program AI, Signal AI, Attribution AI)
- Implements context compression for long conversations
- Supports multiple LLM providers with user selection

Architecture:
- StreamBuffer-based async streaming (same as other AI services)
- Long-term memory auto-injected into system prompt alongside user profile
- Mem0-style batch deduplication for memory management
- Context compression at 70% of context window
- Memory extraction runs async in background thread during compression
"""
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional

import requests
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import (
    HyperAiProfile,
    HyperAiConversation,
    HyperAiMessage
)
from services.ai_decision_service import (
    build_chat_completion_endpoints,
    _extract_text_from_message,
    get_max_tokens,
    build_llm_payload,
    build_llm_headers,
    is_reasoning_model,
    extract_reasoning,
    convert_tools_to_anthropic,
    convert_messages_to_anthropic,
    strip_thinking_tags,
)
from services.ai_stream_service import (
    get_buffer_manager,
    generate_task_id,
    run_ai_task_in_background,
    format_sse_event,
    submit_ai_background_task,
)
from services.hyper_ai_config import (
    API_MAX_RETRIES,
    _get_retry_delay,
    _should_retry_api,
    get_llm_config,
    get_or_create_profile,
    load_onboarding_prompt,
    save_llm_config,
    test_llm_connection,
)
from services.hyper_ai_conversation_store import (
    get_conversation_messages,
    get_or_create_conversation,
    save_message,
)
from services.hyper_ai_message_context import (
    _build_user_storage_content,
    _normalize_chat_image_attachments,
    build_messages_for_api,
)
from services.hyper_ai_subagents import execute_subagent_tool
from services.hyper_ai_harness import (
    RISK_HIGH,
    TOOL_STATUS_BLOCKED,
    TOOL_STATUS_DOMAIN_ERROR,
    TOOL_STATUS_INFRA_ERROR,
    TOOL_STATUS_WARNING,
    SubAgentContractChecker,
    ToolFailureTracker,
    assess_tool_risk,
    blocked_meta,
    blocked_tool_result,
    classify_tool_result,
    circuit_breaker_result,
    execute_tool_with_meta,
    generate_confirmation_id,
    mask_tool_args,
)
from services.hyper_ai_tool_runtime import (
    CONCURRENCY_SAFE_TOOL_NAMES,
    format_tool_validation_errors,
    get_tool_runtime_spec,
    validate_tool_arguments,
)

logger = logging.getLogger(__name__)

# Maximum tool call iterations to prevent infinite loops
MAX_TOOL_ITERATIONS = 100

# Sub-agent tool names — these return generators instead of strings
SUBAGENT_TOOL_NAMES = {
    "coordinate_all_ai",
    "call_prompt_ai",
    "call_program_ai",
    "call_signal_ai",
    "call_attribution_ai",
}
FULL_RESULT_LOG_TOOLS = {"save_prompt", "save_program", "save_signal_pool", "create_ai_trader", "save_factor"}


def _max_parallel_readonly_tools() -> int:
    try:
        return max(1, int(os.getenv("HYPER_AI_MAX_PARALLEL_READONLY_TOOLS", "6")))
    except ValueError:
        return 6


MAX_PARALLEL_READONLY_TOOLS = _max_parallel_readonly_tools()


@dataclass
class _ToolCallRequest:
    name: str
    arguments: Any
    tool_call_id: str


@dataclass
class _ToolCallResult:
    request: _ToolCallRequest
    arguments: Dict[str, Any]
    result: str
    meta: Any
    duration_ms: int
    status: str
    error_severity: Optional[str] = None
    risk_assessment: Any = None
    parallel: bool = False


# Sub-agent tools are executed via execute_subagent_tool (generator, yields progress events).
# Normal tools are executed via execute_hyper_ai_tool (plain function, returns string).
# These two paths MUST stay separate - never wrap them in a single function that contains
# both yield and return, because Python turns ANY function with yield into a generator.


def _tool_error_event_data(meta, severity: str = None, duration_ms: Optional[int] = None) -> Dict[str, Any]:
    data = {
        "name": meta.tool_name,
        "status": meta.status,
        "severity": severity or meta.status,
        "code": meta.code,
        "message": meta.message,
        "retryable": meta.retryable,
    }
    if duration_ms is not None:
        data["duration_ms"] = duration_ms
    return data


def _tool_status_event_data(
    fn_name: str,
    status: str,
    duration_ms: Optional[int] = None,
    risk_assessment: Any = None,
    meta: Any = None,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    spec = get_tool_runtime_spec(fn_name)
    data: Dict[str, Any] = {
        "name": fn_name,
        "status": status,
    }
    if duration_ms is not None:
        data["duration_ms"] = duration_ms
    if risk_assessment:
        data["risk_level"] = risk_assessment.risk_level
        data["risk_reason"] = risk_assessment.reason
    elif spec:
        data["risk_level"] = spec.risk_level
    if spec:
        data["group"] = spec.group
        data["concurrency_safe"] = spec.concurrency_safe
        data["schema_validated"] = True
    if meta:
        data["result_status"] = meta.status
        data["code"] = meta.code
        data["retryable"] = meta.retryable
    if message:
        data["message"] = message
    return data


def _tool_log_result(fn_name: str, tool_result: str) -> str:
    if fn_name in FULL_RESULT_LOG_TOOLS:
        return tool_result
    return tool_result[:500] if len(tool_result) > 500 else tool_result


def _tool_result_status(meta: Any) -> str:
    if meta.status == TOOL_STATUS_WARNING:
        return "warning"
    if meta.status == TOOL_STATUS_BLOCKED:
        return "blocked"
    if meta.status in (TOOL_STATUS_INFRA_ERROR, TOOL_STATUS_DOMAIN_ERROR):
        return "failed"
    return "completed"


def _tool_error_severity(meta: Any) -> Optional[str]:
    if meta.status == TOOL_STATUS_INFRA_ERROR:
        return "infra_error"
    if meta.status in (TOOL_STATUS_BLOCKED, TOOL_STATUS_WARNING):
        return meta.status
    return None


def _is_concurrency_safe_tool(fn_name: str) -> bool:
    return fn_name in CONCURRENCY_SAFE_TOOL_NAMES and fn_name not in SUBAGENT_TOOL_NAMES


def _safe_tool_args(arguments: Any) -> Dict[str, Any]:
    return arguments if isinstance(arguments, dict) else {}


def _build_tool_call_log_entry(
    db: Session,
    fn_name: str,
    fn_args: Dict[str, Any],
    tool_result: str,
    duration_ms: Optional[int] = None,
    execution_mode: str = "serial",
) -> Dict[str, Any]:
    """Build a durable, masked tool trace entry for future context and UI inspection."""
    meta = classify_tool_result(fn_name, tool_result)
    spec = get_tool_runtime_spec(fn_name)
    try:
        risk = assess_tool_risk(db, fn_name, fn_args)
        risk_level = risk.risk_level
        risk_reason = risk.reason
    except Exception as exc:
        logger.warning("[HyperAI] Failed to classify tool risk for log: %s", exc)
        risk_level = "unknown"
        risk_reason = "classification_failed"

    entry = {
        "tool": fn_name,
        "args": mask_tool_args(fn_args),
        "result": _tool_log_result(fn_name, tool_result),
        "status": meta.status,
        "code": meta.code,
        "retryable": meta.retryable,
        "risk_level": risk_level,
        "risk_reason": risk_reason,
        "schema_validated": bool(spec),
        "concurrency_safe": spec.concurrency_safe if spec else False,
        "execution_mode": execution_mode,
    }
    if duration_ms is not None:
        entry["duration_ms"] = duration_ms
    if meta.message:
        entry["message"] = meta.message[:300]
    return entry


def _await_tool_confirmation(
    db: Session,
    assistant_msg: HyperAiMessage,
    task_id: Optional[str],
    fn_name: str,
    fn_args: Dict[str, Any],
    risk_assessment,
) -> Generator[str, None, tuple[bool, str]]:
    """Pause a high-risk tool call until the user confirms it."""
    if risk_assessment.risk_level != RISK_HIGH:
        return True, ""

    if not task_id:
        return False, blocked_tool_result(
            "High-risk operation was blocked because the streaming task ID is missing."
        )

    manager = get_buffer_manager()
    confirmation_id = generate_confirmation_id()
    if not manager.begin_confirmation(task_id, confirmation_id):
        return False, blocked_tool_result(
            "High-risk operation was blocked because another confirmation is pending or the task is no longer running."
        )

    assistant_msg.content = "[Waiting for user confirmation...]"
    db.commit()

    yield format_sse_event("confirmation_required", {
        "tool_name": fn_name,
        "args": mask_tool_args(fn_args),
        "description": risk_assessment.description,
        "reason": risk_assessment.reason,
        "confirmation_id": confirmation_id,
    })

    task = manager.get_task(task_id)
    if not task:
        manager.clear_confirmation(task_id, confirmation_id)
        return False, blocked_tool_result("High-risk operation was blocked because the task is no longer available.")

    try:
        confirmed = task.confirmation_event.wait(timeout=300)
        response = task.confirmation_response
    finally:
        manager.clear_confirmation(task_id, confirmation_id)

    if not confirmed or not response or not response.get("confirmed"):
        return False, blocked_tool_result(
            "User declined this operation. The tool was NOT executed. "
            "Do NOT retry or re-ask. Simply acknowledge the cancellation and move on."
        )

    return True, ""


def _execute_harnessed_tool_call(
    db: Session,
    assistant_msg: HyperAiMessage,
    task_id: Optional[str],
    fn_name: str,
    fn_args: Dict[str, Any],
    failure_tracker: ToolFailureTracker,
    llm_config: Dict[str, Any],
) -> Generator[str, None, str]:
    """Execute a Hyper AI tool with runtime harness guardrails."""
    started_at = time.perf_counter()

    validation = validate_tool_arguments(fn_name, fn_args)
    if not validation.ok:
        message = format_tool_validation_errors(validation)
        tool_result = blocked_tool_result(message)
        meta = blocked_meta(fn_name, message)
        meta.code = "invalid_tool_arguments"
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        yield format_sse_event("tool_status", _tool_status_event_data(
            fn_name,
            "blocked",
            duration_ms=duration_ms,
            meta=meta,
            message=message,
        ))
        yield format_sse_event("tool_error", _tool_error_event_data(
            meta,
            severity="invalid_tool_arguments",
            duration_ms=duration_ms,
        ))
        return tool_result

    fn_args.clear()
    fn_args.update(validation.arguments)

    if failure_tracker.is_tripped(fn_name):
        tool_result = circuit_breaker_result(fn_name)
        meta = blocked_meta(fn_name, "Tool is temporarily unavailable after repeated infrastructure failures.")
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        yield format_sse_event("tool_status", _tool_status_event_data(
            fn_name,
            "blocked",
            duration_ms=duration_ms,
            meta=meta,
            message=meta.message,
        ))
        yield format_sse_event("tool_error", _tool_error_event_data(
            meta,
            severity="circuit_breaker",
            duration_ms=duration_ms,
        ))
        return tool_result

    risk_assessment = assess_tool_risk(db, fn_name, fn_args)
    if risk_assessment.risk_level == RISK_HIGH:
        yield format_sse_event("tool_status", _tool_status_event_data(
            fn_name,
            "waiting_confirmation",
            risk_assessment=risk_assessment,
        ))

    confirmed, blocked_result = yield from _await_tool_confirmation(
        db=db,
        assistant_msg=assistant_msg,
        task_id=task_id,
        fn_name=fn_name,
        fn_args=fn_args,
        risk_assessment=risk_assessment,
    )
    if not confirmed:
        meta = blocked_meta(fn_name, "User confirmation was not received. The tool was not executed.")
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        yield format_sse_event("tool_status", _tool_status_event_data(
            fn_name,
            "blocked",
            duration_ms=duration_ms,
            risk_assessment=risk_assessment,
            meta=meta,
            message=meta.message,
        ))
        yield format_sse_event("tool_error", _tool_error_event_data(
            meta,
            severity="user_cancelled",
            duration_ms=duration_ms,
        ))
        return blocked_result

    yield format_sse_event("tool_status", _tool_status_event_data(
        fn_name,
        "running",
        risk_assessment=risk_assessment,
    ))

    if fn_name in SUBAGENT_TOOL_NAMES:
        tool_result = yield from execute_subagent_tool(db, fn_name, fn_args, user_id=1)
        meta = classify_tool_result(fn_name, tool_result)
        contract_ok, warning = SubAgentContractChecker.check(fn_name, tool_result)
        if not contract_ok:
            tool_result = f"{warning}\n{tool_result}"
            meta = blocked_meta(fn_name, warning)
            meta.status = TOOL_STATUS_DOMAIN_ERROR
            meta.code = "contract_fail"
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            yield format_sse_event("tool_status", _tool_status_event_data(
                fn_name,
                "failed",
                duration_ms=duration_ms,
                risk_assessment=risk_assessment,
                meta=meta,
                message=warning,
            ))
            yield format_sse_event("tool_error", _tool_error_event_data(
                meta,
                severity="contract_fail",
                duration_ms=duration_ms,
            ))
        else:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            yield format_sse_event("tool_status", _tool_status_event_data(
                fn_name,
                "completed",
                duration_ms=duration_ms,
                risk_assessment=risk_assessment,
                meta=meta,
            ))
        return tool_result

    tool_result, meta = execute_tool_with_meta(
        db,
        fn_name,
        fn_args,
        user_id=1,
        api_config=llm_config,
    )
    failure_tracker.record(meta)
    duration_ms = int((time.perf_counter() - started_at) * 1000)

    status = "completed"
    if meta.status == TOOL_STATUS_WARNING:
        status = "warning"
    elif meta.status == TOOL_STATUS_BLOCKED:
        status = "blocked"
    elif meta.status in (TOOL_STATUS_INFRA_ERROR, TOOL_STATUS_DOMAIN_ERROR):
        status = "failed"

    yield format_sse_event("tool_status", _tool_status_event_data(
        fn_name,
        status,
        duration_ms=duration_ms,
        risk_assessment=risk_assessment,
        meta=meta,
        message=meta.message or None,
    ))

    if meta.status in (TOOL_STATUS_INFRA_ERROR, TOOL_STATUS_BLOCKED, TOOL_STATUS_WARNING):
        severity = "infra_error" if meta.status == TOOL_STATUS_INFRA_ERROR else meta.status
        data = _tool_error_event_data(meta, severity=severity, duration_ms=duration_ms)
        if meta.status == TOOL_STATUS_INFRA_ERROR:
            data["failure_count"] = failure_tracker.failure_count(fn_name)
            data["circuit_breaker_tripped"] = failure_tracker.is_tripped(fn_name)
        yield format_sse_event("tool_error", data)

    return tool_result


def _run_concurrency_safe_tool_call(
    request: _ToolCallRequest,
    llm_config: Dict[str, Any],
) -> _ToolCallResult:
    """Run one read-only tool in a worker thread with its own DB session."""
    started_at = time.perf_counter()
    db = SessionLocal()
    fn_name = request.name
    fn_args: Any = dict(request.arguments) if isinstance(request.arguments, dict) else request.arguments
    risk_assessment = None

    try:
        validation = validate_tool_arguments(fn_name, fn_args)
        if not validation.ok:
            message = format_tool_validation_errors(validation)
            meta = blocked_meta(fn_name, message)
            meta.code = "invalid_tool_arguments"
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            return _ToolCallResult(
                request=request,
                arguments=_safe_tool_args(fn_args),
                result=blocked_tool_result(message),
                meta=meta,
                duration_ms=duration_ms,
                status="blocked",
                error_severity="invalid_tool_arguments",
                parallel=True,
            )

        fn_args = validation.arguments
        risk_assessment = assess_tool_risk(db, fn_name, fn_args)
        if risk_assessment.risk_level == RISK_HIGH:
            message = "Concurrency-safe tool was escalated to high risk and blocked before execution."
            meta = blocked_meta(fn_name, message)
            meta.code = "parallel_risk_escalated"
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            return _ToolCallResult(
                request=request,
                arguments=fn_args,
                result=blocked_tool_result(message),
                meta=meta,
                duration_ms=duration_ms,
                status="blocked",
                error_severity="high_risk_blocked",
                risk_assessment=risk_assessment,
                parallel=True,
            )

        tool_result, meta = execute_tool_with_meta(
            db,
            fn_name,
            fn_args,
            user_id=1,
            api_config=llm_config,
        )
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        return _ToolCallResult(
            request=request,
            arguments=_safe_tool_args(fn_args),
            result=tool_result,
            meta=meta,
            duration_ms=duration_ms,
            status=_tool_result_status(meta),
            error_severity=_tool_error_severity(meta),
            risk_assessment=risk_assessment,
            parallel=True,
        )
    except Exception as exc:
        logger.error("[HyperAI] Parallel tool %s failed: %s", fn_name, exc, exc_info=True)
        tool_result = json.dumps({"error": str(exc), "_error_class": type(exc).__name__}, ensure_ascii=False)
        meta = classify_tool_result(fn_name, tool_result)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        return _ToolCallResult(
            request=request,
            arguments=_safe_tool_args(fn_args),
            result=tool_result,
            meta=meta,
            duration_ms=duration_ms,
            status=_tool_result_status(meta),
            error_severity=_tool_error_severity(meta),
            risk_assessment=risk_assessment,
            parallel=True,
        )
    finally:
        db.close()


def _finalize_tool_call_result(
    db: Session,
    result: _ToolCallResult,
    failure_tracker: ToolFailureTracker,
    tool_calls_log: List[Dict[str, Any]],
    emit_status: bool,
    record_failure: bool,
) -> Generator[str, None, Dict[str, Any]]:
    """Persist and stream the common result events for one completed tool call."""
    fn_name = result.request.name
    if record_failure:
        failure_tracker.record(result.meta)

    if emit_status:
        yield format_sse_event("tool_status", _tool_status_event_data(
            fn_name,
            result.status,
            duration_ms=result.duration_ms,
            risk_assessment=result.risk_assessment,
            meta=result.meta,
            message=result.meta.message or None,
        ))

        severity = result.error_severity
        if severity:
            data = _tool_error_event_data(result.meta, severity=severity, duration_ms=result.duration_ms)
            if result.meta.status == TOOL_STATUS_INFRA_ERROR:
                data["failure_count"] = failure_tracker.failure_count(fn_name)
                data["circuit_breaker_tripped"] = failure_tracker.is_tripped(fn_name)
            yield format_sse_event("tool_error", data)

    if fn_name == "load_skill":
        yield format_sse_event("skill_loaded", {
            "skill_name": result.arguments.get("skill_name", "")
        })

    tool_calls_log.append(
        _build_tool_call_log_entry(
            db,
            fn_name,
            result.arguments,
            result.result,
            duration_ms=result.duration_ms,
            execution_mode="parallel" if result.parallel else "serial",
        )
    )
    yield format_sse_event("tool_result", {
        "name": fn_name,
        "result": result.result[:200] if len(result.result) > 200 else result.result,
        "status": result.meta.status,
        "code": result.meta.code,
        "duration_ms": result.duration_ms,
        "parallel": result.parallel,
    })
    return {
        "role": "tool",
        "tool_call_id": result.request.tool_call_id,
        "content": result.result,
    }


def _execute_serial_tool_request(
    db: Session,
    assistant_msg: HyperAiMessage,
    task_id: Optional[str],
    request: _ToolCallRequest,
    failure_tracker: ToolFailureTracker,
    llm_config: Dict[str, Any],
    tool_calls_log: List[Dict[str, Any]],
) -> Generator[str, None, Dict[str, Any]]:
    yield format_sse_event("tool_call", {"name": request.name, "args": request.arguments})
    tool_started_at = time.perf_counter()
    tool_result = yield from _execute_harnessed_tool_call(
        db=db,
        assistant_msg=assistant_msg,
        task_id=task_id,
        fn_name=request.name,
        fn_args=request.arguments,
        failure_tracker=failure_tracker,
        llm_config=llm_config,
    )
    duration_ms = int((time.perf_counter() - tool_started_at) * 1000)
    meta = classify_tool_result(request.name, tool_result)
    result = _ToolCallResult(
        request=request,
        arguments=_safe_tool_args(request.arguments),
        result=tool_result,
        meta=meta,
        duration_ms=duration_ms,
        status=_tool_result_status(meta),
        error_severity=_tool_error_severity(meta),
    )
    return (yield from _finalize_tool_call_result(
        db=db,
        result=result,
        failure_tracker=failure_tracker,
        tool_calls_log=tool_calls_log,
        emit_status=False,
        record_failure=False,
    ))


def _execute_parallel_tool_batch(
    db: Session,
    requests_batch: List[_ToolCallRequest],
    failure_tracker: ToolFailureTracker,
    llm_config: Dict[str, Any],
    tool_calls_log: List[Dict[str, Any]],
) -> Generator[str, None, List[Dict[str, Any]]]:
    max_workers = max(1, min(MAX_PARALLEL_READONLY_TOOLS, len(requests_batch)))
    for request in requests_batch:
        yield format_sse_event("tool_call", {
            "name": request.name,
            "args": request.arguments,
            "parallel": True,
        })
        yield format_sse_event("tool_status", _tool_status_event_data(
            request.name,
            "running",
            message=f"running in read-only parallel batch ({max_workers} workers)",
        ))

    tool_messages: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="hyper-ai-tool") as executor:
        futures = [
            executor.submit(_run_concurrency_safe_tool_call, request, llm_config)
            for request in requests_batch
        ]
        for future in futures:
            result = future.result()
            tool_message = yield from _finalize_tool_call_result(
                db=db,
                result=result,
                failure_tracker=failure_tracker,
                tool_calls_log=tool_calls_log,
                emit_status=True,
                record_failure=True,
            )
            tool_messages.append(tool_message)

    return tool_messages


def _execute_tool_requests_for_round(
    db: Session,
    assistant_msg: HyperAiMessage,
    task_id: Optional[str],
    requests_list: List[_ToolCallRequest],
    failure_tracker: ToolFailureTracker,
    llm_config: Dict[str, Any],
    tool_calls_log: List[Dict[str, Any]],
) -> Generator[str, None, List[Dict[str, Any]]]:
    tool_messages: List[Dict[str, Any]] = []
    index = 0

    while index < len(requests_list):
        request = requests_list[index]
        can_parallelize = (
            MAX_PARALLEL_READONLY_TOOLS > 1
            and _is_concurrency_safe_tool(request.name)
            and not failure_tracker.is_tripped(request.name)
        )

        if not can_parallelize:
            tool_message = yield from _execute_serial_tool_request(
                db=db,
                assistant_msg=assistant_msg,
                task_id=task_id,
                request=request,
                failure_tracker=failure_tracker,
                llm_config=llm_config,
                tool_calls_log=tool_calls_log,
            )
            tool_messages.append(tool_message)
            index += 1
            continue

        batch = [request]
        next_index = index + 1
        while next_index < len(requests_list):
            next_request = requests_list[next_index]
            if (
                not _is_concurrency_safe_tool(next_request.name)
                or failure_tracker.is_tripped(next_request.name)
            ):
                break
            batch.append(next_request)
            next_index += 1

        if len(batch) == 1:
            tool_message = yield from _execute_serial_tool_request(
                db=db,
                assistant_msg=assistant_msg,
                task_id=task_id,
                request=request,
                failure_tracker=failure_tracker,
                llm_config=llm_config,
                tool_calls_log=tool_calls_log,
            )
            tool_messages.append(tool_message)
        else:
            batch_messages = yield from _execute_parallel_tool_batch(
                db=db,
                requests_batch=batch,
                failure_tracker=failure_tracker,
                llm_config=llm_config,
                tool_calls_log=tool_calls_log,
            )
            tool_messages.extend(batch_messages)

        index = next_index

    return tool_messages


def stream_chat_response(
    db: Session,
    conversation_id: int,
    user_message: str,
    task_id: Optional[str] = None,
    image_attachments: Optional[List[Dict[str, Any]]] = None,
) -> Generator[str, None, None]:
    """
    Stream chat response from LLM with tool calling support.

    ARCHITECTURE NOTE: This is a generator that yields SSE-formatted strings.
    It does NOT stream directly to the frontend. Instead:
    - start_chat_task() wraps this generator and passes it to run_ai_task_in_background()
    - run_ai_task_in_background() runs this in a background thread, parsing each yielded
      SSE event and storing it in StreamBufferManager (in-memory buffer)
    - Frontend polls /api/ai-stream/{task_id}?offset=N to pull events from the buffer
    - This means ANY event yielded here automatically reaches the frontend via polling,
      and survives frontend disconnects (buffer has 15-min expiry)

    For sub-agent calls (call_*_ai), the tool execution returns a generator instead of
    a string. This generator yields subagent_progress events (forwarded to frontend)
    and finally yields the result string for the main LLM to continue reasoning.
    """
    # Get LLM config
    llm_config = get_llm_config(db)
    if not llm_config.get("configured"):
        yield format_sse_event("error", {
            "message": "LLM not configured. Please complete onboarding first."
        })
        return

    normalized_images = _normalize_chat_image_attachments(image_attachments)

    # Save user message. Image bytes stay in the active task payload only; the
    # DB keeps auditable attachment metadata so history remains lightweight.
    save_message(db, conversation_id, "user", _build_user_storage_content(user_message, normalized_images))

    # Build messages (with automatic compression) and get tools
    messages, tools, command_skill = build_messages_for_api(
        db,
        conversation_id,
        user_message,
        llm_config,
        image_attachments=normalized_images,
    )

    # Emit skill_loaded event if /command mode was used
    if command_skill:
        yield format_sse_event("skill_loaded", {"skill_name": command_skill})

    # Prepare API call
    base_url = llm_config["base_url"]
    model = llm_config["model"]
    api_key = llm_config["api_key"]
    api_format = llm_config.get("api_format", "openai")

    # Build endpoints
    endpoints = build_chat_completion_endpoints(base_url, model)
    if not endpoints:
        yield format_sse_event("error", {"message": "Invalid API endpoint"})
        return

    # Use unified headers builder (see build_llm_headers in ai_decision_service)
    headers = build_llm_headers(api_format, api_key, base_url)

    # Create assistant message upfront with is_complete=False for interrupt recovery
    assistant_msg = HyperAiMessage(
        conversation_id=conversation_id,
        role="assistant",
        content="",
        is_complete=False
    )
    db.add(assistant_msg)
    db.flush()

    # Tool call loop variables
    tool_calls_log = []
    reasoning_snapshot = ""
    final_content = ""
    iteration = 0
    failure_tracker = ToolFailureTracker()

    try:
        while iteration < MAX_TOOL_ITERATIONS:
            iteration += 1
            is_last_round = (iteration == MAX_TOOL_ITERATIONS)

            # On last round, inject a system message forcing the AI to summarize
            if is_last_round:
                messages.append({
                    "role": "user",
                    "content": "[SYSTEM] You have reached the maximum tool call limit. You MUST now provide your final response to the user. Summarize all findings from your tool calls and answer the user's question. Do NOT attempt any more tool calls."
                })

            # Use unified payload builder (see build_llm_payload in ai_decision_service)
            if api_format == "anthropic":
                sys_prompt, anthropic_messages = convert_messages_to_anthropic(messages)
                anthropic_tools = convert_tools_to_anthropic(tools) if tools and not is_last_round else None
                body = build_llm_payload(
                    model=model,
                    messages=[{"role": "system", "content": sys_prompt}] + anthropic_messages,
                    api_format=api_format,
                    tools=anthropic_tools,
                )
            else:
                body = build_llm_payload(
                    model=model,
                    messages=messages,
                    api_format=api_format,
                    tools=tools if tools and not is_last_round else None,
                    tool_choice="auto" if tools and not is_last_round else None,
                )

            # Make API call with retry
            response = None
            last_error = None
            last_status_code = None
            last_response_text = None

            for attempt in range(API_MAX_RETRIES):
                for endpoint in endpoints:
                    try:
                        response = requests.post(
                            endpoint, headers=headers, json=body,
                            timeout=180  # Longer timeout for reasoning models
                        )
                        last_status_code = response.status_code
                        last_response_text = response.text[:2000] if response.text else None

                        if response.status_code == 200:
                            break
                        else:
                            last_error = f"HTTP {response.status_code}"
                            logger.warning(f"[HyperAI] Endpoint failed: {response.status_code} - {response.text[:500]}")
                    except requests.exceptions.Timeout as e:
                        last_error = f"Timeout: {str(e)}"
                        logger.warning(f"[HyperAI] Endpoint timeout: {e}")
                    except requests.exceptions.RequestException as e:
                        last_error = str(e)
                        logger.warning(f"[HyperAI] Request error: {e}")

                if response and response.status_code == 200:
                    break

                # Check if should retry
                if not _should_retry_api(last_status_code, last_error):
                    break

                if attempt < API_MAX_RETRIES - 1:
                    delay = _get_retry_delay(attempt)
                    yield format_sse_event("retry", {
                        "attempt": attempt + 2,
                        "max_retries": API_MAX_RETRIES
                    })
                    time.sleep(delay)

            # Check for failure
            if not response or response.status_code != 200:
                error_parts = []
                if last_error:
                    error_parts.append(f"error={last_error}")
                if last_status_code:
                    error_parts.append(f"status={last_status_code}")
                if last_response_text:
                    error_parts.append(f"response={last_response_text[:500]}")
                error_detail = "; ".join(error_parts) if error_parts else "No response from API"
                logger.error(f"[HyperAI] API failed at round {iteration}: {error_detail}")

                if tool_calls_log:
                    assistant_msg.content = f"[Interrupted at round {iteration}] {error_detail}"
                    assistant_msg.tool_calls_log = json.dumps(tool_calls_log)
                    assistant_msg.reasoning_snapshot = reasoning_snapshot if reasoning_snapshot else None
                    assistant_msg.interrupt_reason = f"Round {iteration}: {error_detail}"
                    db.commit()
                    yield format_sse_event("interrupted", {
                        "message_id": assistant_msg.id,
                        "round": iteration,
                        "error": error_detail,
                        "conversation_id": conversation_id
                    })
                else:
                    db.delete(assistant_msg)
                    db.commit()
                    yield format_sse_event("error", {"message": error_detail})
                return

            # Parse response
            try:
                resp_json = response.json()
            except Exception as e:
                logger.error(f"[HyperAI] Failed to parse response: {e}")
                yield format_sse_event("error", {"message": f"Failed to parse response: {e}"})
                return

            # Extract message based on API format
            if api_format == "anthropic":
                # Anthropic format
                content_blocks = resp_json.get("content", [])
                tool_uses = []
                content = ""
                reasoning_content = ""
                for block in content_blocks:
                    if block.get("type") == "text":
                        content += block.get("text", "")
                    elif block.get("type") == "tool_use":
                        tool_uses.append(block)
                    elif block.get("type") == "thinking":
                        t = block.get("thinking", "")
                        if t:
                            reasoning_content += t
                api_tool_calls = tool_uses
            else:
                # OpenAI format
                message = resp_json["choices"][0]["message"]
                api_tool_calls = message.get("tool_calls", [])
                reasoning_content = message.get("reasoning_content", "") or extract_reasoning(message)
                content = message.get("content", "")

            # Strip <thinking> text tags from content (some proxies embed them)
            content, tag_thinking = strip_thinking_tags(content)
            if tag_thinking and not reasoning_content:
                reasoning_content = tag_thinking

            # Send reasoning content if present
            if reasoning_content:
                yield format_sse_event("reasoning", {"content": reasoning_content})
                reasoning_snapshot += f"\n[Round {iteration}]\n{reasoning_content}"

            # Send content if present
            if content:
                yield format_sse_event("content", {"text": content})

            if api_tool_calls:
                # Process tool calls - build assistant message with reasoning_content for DeepSeek
                if api_format == "anthropic":
                    # Anthropic format - store tool_use_blocks for convert_messages_to_anthropic
                    messages.append({
                        "role": "assistant",
                        "content": content or "",
                        "tool_use_blocks": content_blocks
                    })
                    tool_requests = []
                    for tu in api_tool_calls:
                        fn_args = tu.get("input", {})
                        if fn_args == "":
                            fn_args = {}
                        tool_requests.append(
                            _ToolCallRequest(
                                name=tu.get("name", ""),
                                arguments=fn_args,
                                tool_call_id=tu.get("id", ""),
                            )
                        )
                    tool_messages = yield from _execute_tool_requests_for_round(
                        db=db,
                        assistant_msg=assistant_msg,
                        task_id=task_id,
                        requests_list=tool_requests,
                        failure_tracker=failure_tracker,
                        llm_config=llm_config,
                        tool_calls_log=tool_calls_log,
                    )
                    messages.extend(tool_messages)
                else:
                    # OpenAI format - MUST include reasoning_content for DeepSeek Reasoner
                    assistant_msg_dict = {
                        "role": "assistant",
                        "content": content or "",
                        "tool_calls": api_tool_calls
                    }
                    if reasoning_content:
                        assistant_msg_dict["reasoning_content"] = reasoning_content
                    messages.append(assistant_msg_dict)

                    tool_requests = []
                    for tc in api_tool_calls:
                        fn_name = tc["function"]["name"]
                        try:
                            fn_args = json.loads(tc["function"]["arguments"])
                        except json.JSONDecodeError:
                            fn_args = {}
                        tool_requests.append(
                            _ToolCallRequest(
                                name=fn_name,
                                arguments=fn_args,
                                tool_call_id=tc["id"],
                            )
                        )
                    tool_messages = yield from _execute_tool_requests_for_round(
                        db=db,
                        assistant_msg=assistant_msg,
                        task_id=task_id,
                        requests_list=tool_requests,
                        failure_tracker=failure_tracker,
                        llm_config=llm_config,
                        tool_calls_log=tool_calls_log,
                    )
                    messages.extend(tool_messages)

                # Save progress after each round (for retry support)
                if tool_calls_log:
                    assistant_msg.content = f"[Processing round {iteration}...]"
                    assistant_msg.tool_calls_log = json.dumps(tool_calls_log)
                    assistant_msg.reasoning_snapshot = reasoning_snapshot if reasoning_snapshot else None
                    db.commit()
            else:
                # No tool calls - final response
                final_content = content or ""
                break

        # Handle case where final_content is empty (AI ended with tool calls)
        if not final_content:
            if api_format != "anthropic" and 'message' in dir() and message:
                last_content = message.get("content", "")
                if last_content:
                    final_content = last_content
            if not final_content:
                final_content = "Processing completed."

        # Update assistant message and mark as complete
        assistant_msg.content = final_content
        assistant_msg.reasoning_snapshot = reasoning_snapshot if reasoning_snapshot else None
        assistant_msg.tool_calls_log = json.dumps(tool_calls_log) if tool_calls_log else None
        assistant_msg.is_complete = True

        # Update conversation message count for assistant message
        conv = db.query(HyperAiConversation).filter(
            HyperAiConversation.id == conversation_id
        ).first()
        if conv:
            conv.message_count = (conv.message_count or 0) + 1
        db.commit()

        # Calculate fresh token usage and compression points for frontend
        done_data = {
            "conversation_id": conversation_id,
            "content": final_content,
            "tool_calls_count": len(tool_calls_log),
            "tool_calls_log": tool_calls_log if tool_calls_log else None,
            "reasoning_snapshot": reasoning_snapshot if reasoning_snapshot else None,
        }
        try:
            from services.ai_context_compression_service import (
                calculate_token_usage, restore_tool_calls_to_messages,
                get_last_compression_point
            )
            import json as json_mod
            profile = db.query(HyperAiProfile).first()
            if profile and profile.llm_model and conv:
                llm_cfg = get_llm_config(db)
                af = llm_cfg.get("api_format", "openai")
                cp = get_last_compression_point(conv)
                cp_mid = cp.get("message_id", 0) if cp else 0
                h_orm = db.query(HyperAiMessage).filter(
                    HyperAiMessage.conversation_id == conversation_id,
                    HyperAiMessage.id > cp_mid
                ).order_by(HyperAiMessage.created_at).all()
                md = [
                    {
                        "role": m.role,
                        "content": m.content,
                        "tool_calls_log": m.tool_calls_log,
                        "reasoning_snapshot": m.reasoning_snapshot,
                    }
                    for m in h_orm
                ]
                ml = restore_tool_calls_to_messages(md, af, model=profile.llm_model or "")
                if cp and cp.get("summary"):
                    ml.insert(0, {"role": "system", "content": cp["summary"]})
                done_data["token_usage"] = calculate_token_usage(ml, profile.llm_model)
            if conv and conv.compression_points:
                done_data["compression_points"] = json_mod.loads(conv.compression_points)
        except Exception as te:
            logger.warning(f"[HyperAI] Token calc in done event failed: {te}")

        yield format_sse_event("done", done_data)

    except Exception as e:
        logger.error(f"[HyperAI] Error: {e}", exc_info=True)
        if tool_calls_log:
            assistant_msg.content = f"[Error during processing] {str(e)}"
            assistant_msg.tool_calls_log = json.dumps(tool_calls_log)
            assistant_msg.reasoning_snapshot = reasoning_snapshot if reasoning_snapshot else None
            assistant_msg.interrupt_reason = f"Error: {str(e)}"
            db.commit()
            yield format_sse_event("interrupted", {
                "message_id": assistant_msg.id,
                "error": str(e),
                "conversation_id": conversation_id
            })
        else:
            db.delete(assistant_msg)
            db.commit()
            yield format_sse_event("error", {"message": str(e)})


def start_chat_task(
    db: Session,
    conversation_id: int,
    user_message: str,
    lang: str = None,
    image_attachments: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Start a chat task in background and return task_id."""
    task_id = generate_task_id("hyper")
    manager = get_buffer_manager()
    manager.create_task(task_id, conversation_id)

    def generator_func():
        from database.connection import SessionLocal
        task_db = SessionLocal()
        try:
            yield from stream_chat_response(
                task_db,
                conversation_id,
                user_message,
                task_id=task_id,
                image_attachments=image_attachments,
            )
        finally:
            task_db.close()

    def on_complete(_task):
        try:
            from services.hyper_ai_auto_dream_service import maybe_run_auto_dream

            maybe_run_auto_dream(trigger="chat_complete")
        except Exception as exc:
            logger.warning("[AutoDream] chat-complete gate failed: %s: %s", type(exc).__name__, exc)

    run_ai_task_in_background(task_id, generator_func, on_complete=on_complete)
    return task_id


def stream_onboarding_response(
    db: Session,
    conversation_id: int,
    user_message: str,
    lang: str = "en"
) -> Generator[str, None, None]:
    """Stream onboarding chat response - simplified version for profile collection."""
    llm_config = get_llm_config(db)
    if not llm_config.get("configured"):
        yield format_sse_event("error", {"message": "LLM not configured"})
        return

    # Handle greeting request - AI initiates conversation
    is_greeting = user_message == "__GREETING__"
    if is_greeting:
        user_message = "请用中文介绍你自己并开始引导对话。" if lang == "zh" else "Please introduce yourself and start the onboarding conversation."
    else:
        # Save user message (don't save the greeting trigger)
        save_message(db, conversation_id, "user", user_message)

    # Build messages with onboarding prompt (language-specific)
    messages = []
    system_prompt = load_onboarding_prompt(lang)
    messages.append({"role": "system", "content": system_prompt})

    # Get conversation history (skip for greeting)
    if not is_greeting:
        history = get_conversation_messages(db, conversation_id, limit=20)
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_message})

    # Make API call (reuse existing logic)
    base_url = llm_config["base_url"]
    model = llm_config["model"]
    api_key = llm_config["api_key"]
    api_format = llm_config.get("api_format", "openai")

    endpoints = build_chat_completion_endpoints(base_url, model)
    if not endpoints:
        yield format_sse_event("error", {"message": "Invalid API endpoint"})
        return

    # Use unified headers/payload builders (see build_llm_payload in ai_decision_service)
    headers = build_llm_headers(api_format, api_key, base_url)

    body = build_llm_payload(
        model=model,
        messages=messages,
        api_format=api_format,
        stream=True,
    )

    response = None
    for attempt in range(API_MAX_RETRIES):
        for endpoint in endpoints:
            try:
                response = requests.post(
                    endpoint, headers=headers, json=body,
                    stream=True, timeout=120
                )
                if response.status_code == 200:
                    break
            except requests.exceptions.RequestException:
                continue
        if response and response.status_code == 200:
            break
        time.sleep(_get_retry_delay(attempt))

    if not response or response.status_code != 200:
        yield format_sse_event("error", {"message": "API request failed"})
        return

    yield from _process_onboarding_stream_response(db, conversation_id, response, api_format)


def start_onboarding_chat_task(
    db: Session,
    conversation_id: int,
    user_message: str,
    lang: str = None
) -> str:
    """Start an onboarding chat task in background."""
    task_id = generate_task_id("onboard")
    manager = get_buffer_manager()
    manager.create_task(task_id, conversation_id)

    # Default to English if not specified
    effective_lang = lang or "en"

    def generator_func():
        from database.connection import SessionLocal
        task_db = SessionLocal()
        try:
            yield from stream_onboarding_response(task_db, conversation_id, user_message, effective_lang)
        finally:
            task_db.close()

    run_ai_task_in_background(task_id, generator_func)
    return task_id


def enrich_insight_context(db: Session, context: Dict[str, Any]) -> Dict[str, Any]:
    from services.hyper_ai_insight import enrich_insight_context as _impl

    return _impl(db, context)


def stream_insight_response(
    db: Session,
    context: Dict[str, Any],
    selected_event: Optional[Dict[str, Any]] = None,
    lang: str = "en",
) -> Generator[str, None, None]:
    from services.hyper_ai_insight import stream_insight_response as _impl

    yield from _impl(
        db,
        context,
        get_llm_config=get_llm_config,
        selected_event=selected_event,
        lang=lang,
    )


def start_insight_task(
    db: Session,
    context: Dict[str, Any],
    selected_event: Optional[Dict[str, Any]] = None,
    lang: Optional[str] = None,
) -> str:
    from services.hyper_ai_insight import start_insight_task as _impl

    return _impl(
        db,
        context,
        get_llm_config=get_llm_config,
        selected_event=selected_event,
        lang=lang,
    )


def _process_onboarding_stream_response(
    db: Session,
    conversation_id: int,
    response: requests.Response,
    api_format: str
) -> Generator[str, None, None]:
    from services.hyper_ai_onboarding_stream import process_onboarding_stream_response

    yield from process_onboarding_stream_response(
        db,
        conversation_id,
        response,
        api_format,
        get_or_create_profile=get_or_create_profile,
        save_message=save_message,
    )


def get_suggestions_context(db: Session) -> Dict[str, Any]:
    from services.hyper_ai_suggestions import get_suggestions_context as _impl

    return _impl(db, get_or_create_profile=get_or_create_profile)


def build_suggestions_prompt(context: Dict[str, Any]) -> str:
    from services.hyper_ai_suggestions import build_suggestions_prompt as _impl

    return _impl(context)


def generate_suggested_questions(db: Session) -> List[str]:
    from services.hyper_ai_suggestions import generate_suggested_questions as _impl

    return _impl(
        db,
        get_llm_config=get_llm_config,
        get_or_create_profile=get_or_create_profile,
    )


def get_or_update_suggestions(db: Session) -> Dict[str, Any]:
    from services.hyper_ai_suggestions import get_or_update_suggestions as _impl

    return _impl(
        db,
        get_llm_config=get_llm_config,
        get_or_create_profile=get_or_create_profile,
    )
