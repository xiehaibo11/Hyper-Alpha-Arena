"""Runtime architecture diagnostics for the Hyper AI main robot."""

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from sqlalchemy.orm import Session


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLAUDE_ARCHITECTURE_ROOT = PROJECT_ROOT / "claude架构"


def _tool_names(tools: List[Dict[str, Any]]) -> List[str]:
    names = []
    for item in tools:
        function = item.get("function") if isinstance(item, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if name:
            names.append(name)
    return names


def _safe_count(db: Session, model: Any, *filters: Any) -> int:
    try:
        query = db.query(model)
        if filters:
            query = query.filter(*filters)
        return int(query.count())
    except Exception:
        return 0


def _path_status(paths: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    result = {}
    for key, relative_path in paths.items():
        path = BACKEND_ROOT / relative_path
        result[key] = {
            "path": f"backend/{relative_path}",
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() else 0,
        }
    return result


def _collect_claude_reference() -> Dict[str, Any]:
    files = {
        "agent_loop": "src/query.ts",
        "query_engine": "src/QueryEngine.ts",
        "tool_contract": "src/Tool.ts",
        "task_state": "src/Task.ts",
        "context_builder": "src/context.ts",
        "history": "src/history.ts",
        "cost_tracker": "src/cost-tracker.ts",
    }
    reviewed_files = {}
    for key, relative_path in files.items():
        path = CLAUDE_ARCHITECTURE_ROOT / relative_path
        reviewed_files[key] = {
            "path": str(path.relative_to(PROJECT_ROOT)) if path.exists() else relative_path,
            "exists": path.exists(),
        }

    return {
        "present": CLAUDE_ARCHITECTURE_ROOT.exists(),
        "root": str(CLAUDE_ARCHITECTURE_ROOT),
        "reviewed_files": reviewed_files,
        "patterns_to_keep": [
            "single main loop that alternates LLM responses and tool results",
            "central tool registry with metadata, read/write risk, validation, and permission gates",
            "explicit task lifecycle state for long-running work",
            "context builders that inject system, user, memory, and project state before each turn",
            "persistent history plus compaction to keep long conversations usable",
            "dream-style background tasks that consolidate memory without interrupting foreground work",
            "tool execution traces that survive failures and can be inspected later",
        ],
    }


def _collect_tool_inventory() -> Dict[str, Any]:
    from services.hyper_ai_tool_definitions import HYPER_AI_TOOLS
    from services.hyper_ai_tool_defs_factor import FACTOR_TOOLS
    from services.hyper_ai_tool_defs_read import READ_ONLY_TOOLS
    from services.hyper_ai_tool_defs_write import WRITE_TOOLS
    from services.hyper_ai_tool_definitions import EXTERNAL_TOOLS, SKILL_TOOLS
    from services.hyper_ai_subagents import SUBAGENT_TOOLS
    from services.hyper_ai_harness import HIGH_RISK_TOOLS, LOW_WRITE_TOOLS, READONLY_TOOLS
    from services.hyper_ai_tool_runtime import get_tool_runtime_snapshot

    all_names = _tool_names(HYPER_AI_TOOLS)
    group_names = {
        "read_only_definitions": _tool_names(READ_ONLY_TOOLS),
        "write_definitions": _tool_names(WRITE_TOOLS),
        "factor_definitions": _tool_names(FACTOR_TOOLS),
        "external_definitions": _tool_names(EXTERNAL_TOOLS),
        "skill_definitions": _tool_names(SKILL_TOOLS),
        "subagent_definitions": _tool_names(SUBAGENT_TOOLS),
    }
    all_name_set = set(all_names)
    risk_sets = {
        "readonly": set(READONLY_TOOLS),
        "low_write": set(LOW_WRITE_TOOLS),
        "high_risk": set(HIGH_RISK_TOOLS),
    }
    classified = set().union(*risk_sets.values())
    missing_risk_metadata = sorted(all_name_set - classified)
    stale_risk_metadata = sorted(classified - all_name_set)

    return {
        "total": len(all_names),
        "duplicates": sorted(name for name, count in Counter(all_names).items() if count > 1),
        "groups": {key: len(value) for key, value in group_names.items()},
        "subagents": group_names["subagent_definitions"],
        "risk_counts": {key: len(value & all_name_set) for key, value in risk_sets.items()},
        "missing_risk_metadata": missing_risk_metadata,
        "stale_risk_metadata": stale_risk_metadata,
        "runtime_contract": get_tool_runtime_snapshot(),
        "all_tools": sorted(all_names),
    }


def _collect_runtime_status() -> Dict[str, Any]:
    try:
        from services.ai_stream_service import get_ai_runtime_stats

        runtime = get_ai_runtime_stats()
    except Exception as exc:
        runtime = {"error": str(exc)}

    return {
        "streaming": runtime,
        "max_tool_iterations": 100,
        "task_lifecycle": ["running", "completed", "error"],
        "buffer_retention": "15 minutes after completion; stuck running tasks cleaned after about 30 minutes",
    }


def _collect_auto_dream_status(db: Session) -> Dict[str, Any]:
    try:
        from services.hyper_ai_auto_dream_service import get_auto_dream_status

        return get_auto_dream_status(db, include_scan=True)
    except Exception as exc:
        return {
            "enabled": False,
            "error": str(exc),
            "reason": "auto_dream_status_unavailable",
        }


def _collect_model_status(db: Session) -> Dict[str, Any]:
    from database.models import HyperAiProfile

    profile = db.query(HyperAiProfile).first()
    if not profile:
        return {
            "configured": False,
            "reason": "missing_hyper_ai_profile",
        }

    host = ""
    if profile.llm_base_url:
        parsed = urlparse(profile.llm_base_url)
        host = parsed.netloc or profile.llm_base_url

    enabled_skills = None
    if profile.enabled_skills:
        try:
            parsed_skills = json.loads(profile.enabled_skills)
            enabled_skills = len(parsed_skills) if isinstance(parsed_skills, list) else None
        except (json.JSONDecodeError, TypeError):
            enabled_skills = "invalid_json"

    return {
        "configured": bool(profile.llm_provider and profile.llm_model and profile.llm_api_key_encrypted),
        "provider": profile.llm_provider,
        "model": profile.llm_model,
        "base_url_host": host,
        "api_key_configured": bool(profile.llm_api_key_encrypted),
        "onboarding_completed": bool(profile.onboarding_completed),
        "enabled_skill_count": enabled_skills if enabled_skills is not None else "all_enabled",
    }


def _collect_persistence_status(db: Session) -> Dict[str, Any]:
    from database.models import (
        AIDecisionLog,
        Account,
        AccountProgramBinding,
        AccountPromptBinding,
        HyperAiConversation,
        HyperAiMemory,
        HyperAiMessage,
    )

    since = datetime.utcnow() - timedelta(hours=24)
    recent_assistant_messages = _safe_count(
        db,
        HyperAiMessage,
        HyperAiMessage.role == "assistant",
        HyperAiMessage.created_at >= since,
    )
    recent_tool_messages = _safe_count(
        db,
        HyperAiMessage,
        HyperAiMessage.tool_calls_log.isnot(None),
        HyperAiMessage.created_at >= since,
    )
    recent_decisions = _safe_count(db, AIDecisionLog, AIDecisionLog.decision_time >= since)

    return {
        "hyper_ai_conversations": _safe_count(db, HyperAiConversation),
        "hyper_ai_messages": _safe_count(db, HyperAiMessage),
        "active_memories": _safe_count(db, HyperAiMemory, HyperAiMemory.is_active == True),
        "recent_24h": {
            "assistant_messages": recent_assistant_messages,
            "messages_with_tool_traces": recent_tool_messages,
            "ai_decision_logs": recent_decisions,
        },
        "traders": {
            "total_active": _safe_count(db, Account, Account.is_active == "true", Account.is_deleted != True),
            "auto_trading_enabled": _safe_count(
                db,
                Account,
                Account.is_active == "true",
                Account.auto_trading_enabled == "true",
                Account.is_deleted != True,
            ),
            "prompt_bindings": _safe_count(db, AccountPromptBinding, AccountPromptBinding.is_deleted != True),
            "program_bindings_active": _safe_count(
                db,
                AccountProgramBinding,
                AccountProgramBinding.is_active == True,
                AccountProgramBinding.is_deleted != True,
            ),
        },
        "durability": {
            "chat_messages": "database",
            "tool_call_traces": "database field hyper_ai_messages.tool_calls_log",
            "stream_buffers": "memory only",
            "trading_decisions": "database table ai_decision_logs",
        },
    }


def _collect_component_status() -> Dict[str, Dict[str, Any]]:
    return _path_status(
        {
            "main_agent_loop": "services/hyper_ai_service.py",
            "runtime_harness": "services/hyper_ai_harness.py",
            "tool_definitions": "services/hyper_ai_tool_definitions.py",
            "stream_tasks": "services/ai_stream_service.py",
            "context_compression": "services/ai_context_compression_service.py",
            "auto_dream": "services/hyper_ai_auto_dream_service.py",
            "dream_review": "services/hyper_ai_dream_service.py",
            "long_term_memory": "services/hyper_ai_memory_service.py",
            "subagent_bridge": "services/hyper_ai_subagents.py",
            "decision_logging": "services/ai_decision_logging.py",
            "arena_context": "services/arena_ai_context_service.py",
            "market_data_archive": "services/market_data_archive.py",
            "aliyun_oss_storage": "services/upload_storage.py",
        }
    )


def collect_robot_architecture(db: Session, include_recent_activity: bool = True) -> Dict[str, Any]:
    """Return an inspectable architecture snapshot for the Hyper AI robot."""
    claude_reference = _collect_claude_reference()
    tool_inventory = _collect_tool_inventory()
    runtime_status = _collect_runtime_status()
    auto_dream_status = _collect_auto_dream_status(db)
    try:
        model_status = _collect_model_status(db)
    except Exception as exc:
        model_status = {
            "configured": False,
            "error": str(exc),
            "reason": "database_or_profile_lookup_failed",
        }
    component_status = _collect_component_status()
    if include_recent_activity:
        try:
            persistence_status = _collect_persistence_status(db)
        except Exception as exc:
            persistence_status = {
                "error": str(exc),
                "durability": {
                    "chat_messages": "database",
                    "tool_call_traces": "database field hyper_ai_messages.tool_calls_log",
                    "stream_buffers": "memory only",
                    "trading_decisions": "database table ai_decision_logs",
                },
            }
    else:
        persistence_status = {}

    blocking_issues = []
    warnings = []

    if not claude_reference["present"]:
        warnings.append("Claude architecture reference folder is missing.")
    if not model_status.get("configured"):
        blocking_issues.append("Hyper AI LLM profile is not fully configured.")
    if model_status.get("error"):
        blocking_issues.append("Database/profile lookup failed during robot self-check.")
    if auto_dream_status.get("error"):
        warnings.append("Auto Dream status is unavailable.")
    if persistence_status.get("error"):
        warnings.append("Persistence activity counts are unavailable because database lookup failed.")
    if tool_inventory["duplicates"]:
        warnings.append(f"Duplicate tool definitions: {', '.join(tool_inventory['duplicates'])}.")
    if tool_inventory["missing_risk_metadata"]:
        warnings.append(
            "Tools missing explicit risk metadata: "
            + ", ".join(tool_inventory["missing_risk_metadata"])
        )
    if tool_inventory["stale_risk_metadata"]:
        warnings.append(
            "Risk metadata references unknown tools: "
            + ", ".join(tool_inventory["stale_risk_metadata"])
        )

    missing_components = [
        key for key, status in component_status.items() if not status.get("exists")
    ]
    if missing_components:
        blocking_issues.append("Missing architecture components: " + ", ".join(missing_components))

    streaming = runtime_status.get("streaming", {})
    if isinstance(streaming, dict) and streaming.get("task_queue", 0) > streaming.get("task_max_workers", 0):
        warnings.append("AI task queue is larger than the configured worker pool.")

    score = 100
    score -= 25 * len(blocking_issues)
    score -= 5 * len(warnings)
    score = max(0, min(100, score))

    return {
        "tool": "get_robot_architecture",
        "generated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "readiness": {
            "score": score,
            "blocking_issues": blocking_issues,
            "warnings": warnings,
        },
        "claude_architecture_reference": claude_reference,
        "hyper_ai_architecture": {
            "agent_loop": [
                "build context from system prompt, profile, memory, chat history, and skill injection",
                "send messages plus tool registry to the selected LLM provider",
                "execute returned tool calls through the harness",
                "append tool results back into the conversation and continue",
                "after completed turns, let Auto Dream gate and queue background memory consolidation",
                "allow manual dream review only as an override/debug path",
                "persist final answer, reasoning snapshot, and tool trace",
            ],
            "model": model_status,
            "runtime": runtime_status,
            "auto_dream": auto_dream_status,
            "tools": tool_inventory,
            "components": component_status,
            "persistence": persistence_status,
        },
        "claude_patterns_applied": [
            {
                "pattern": "tool metadata and risk gates",
                "status": "implemented",
                "evidence": "hyper_ai_tool_runtime.py validates tool schemas; hyper_ai_harness.py classifies read-only, low-write, and high-risk tools before execution.",
            },
            {
                "pattern": "streaming task lifecycle",
                "status": "implemented",
                "evidence": "ai_stream_service.py decouples frontend polling from backend AI execution.",
            },
            {
                "pattern": "context and memory injection",
                "status": "implemented",
                "evidence": "hyper_ai_service.py injects system prompt, profile, memories, skills, and compressed history.",
            },
            {
                "pattern": "dream-style background memory consolidation",
                "status": "implemented",
                "evidence": "hyper_ai_auto_dream_service.py registers a scheduler job and chat-complete gate; hyper_ai_dream_service.py performs the safe consolidation pass.",
            },
            {
                "pattern": "sub-agent orchestration",
                "status": "implemented",
                "evidence": "hyper_ai_subagents.py lets the main AI call Prompt, Program, Signal, and Attribution AI.",
            },
            {
                "pattern": "durable tool traces",
                "status": "improved",
                "evidence": "tool_calls_log records result status, risk level, retryability, duration, concurrency safety, schema validation, and masked arguments.",
            },
            {
                "pattern": "read-only tool concurrency",
                "status": "implemented",
                "evidence": "hyper_ai_service.py batches consecutive schema-validated concurrency-safe tools and executes them with isolated DB sessions while preserving tool_result order.",
            },
        ],
        "recommended_next_steps": [
            "Use this self-check before large automation requests or when users ask whether the robot is working.",
            "For trading health, combine this with wallet status, trader listing, decision logs, and system logs.",
            "Keep Auto Dream enabled for autonomous memory consolidation; use run_dream_review only to force or debug one pass.",
            "Keep new tools registered in the explicit risk metadata sets so the main AI can reason about safety.",
            "Tune HYPER_AI_MAX_PARALLEL_READONLY_TOOLS if database or upstream API pressure changes.",
            "Add provider usage/cost persistence if exact model cost reporting is required.",
        ],
    }
