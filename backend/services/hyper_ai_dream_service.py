"""Dream-style review and memory consolidation for Hyper AI."""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MAX_TRANSCRIPT_CHARS = 12000
MAX_MESSAGE_CHARS = 1600

_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret|private[_-]?key|token|password)\b\s*[:=]\s*[^\s,;]+"
)


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _redact_sensitive(text: str) -> str:
    """Remove obvious secrets before sending conversation snippets to memory extraction."""
    if not text:
        return ""
    return _SECRET_ASSIGNMENT_RE.sub(r"\1=[REDACTED]", text)


def _truncate(text: str, limit: int = MAX_MESSAGE_CHARS) -> str:
    text = _redact_sensitive((text or "").strip())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n[truncated]"


def _safe_json_loads(raw: Optional[str]) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None


def _tool_names_from_log(raw: Optional[str]) -> List[str]:
    parsed = _safe_json_loads(raw)
    if not isinstance(parsed, list):
        return []

    names: List[str] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = (
            item.get("name")
            or item.get("tool_name")
            or item.get("function_name")
        )
        if not name and isinstance(item.get("function"), dict):
            name = item["function"].get("name")
        if name:
            names.append(str(name))
    return names[:12]


def _load_recent_messages(
    db: Session,
    conversation_id: Optional[int],
    conversation_ids: Optional[List[int]],
    hours: int,
    max_messages: int,
) -> tuple[List[Any], bool]:
    from database.models import HyperAiConversation, HyperAiMessage

    query = db.query(HyperAiMessage).join(
        HyperAiConversation,
        HyperAiMessage.conversation_id == HyperAiConversation.id,
    )

    if conversation_id:
        query = query.filter(HyperAiMessage.conversation_id == conversation_id)
    elif conversation_ids:
        query = query.filter(HyperAiMessage.conversation_id.in_(conversation_ids))
    else:
        since = datetime.utcnow() - timedelta(hours=hours)
        query = query.filter(HyperAiMessage.created_at >= since)

    query = query.filter(HyperAiMessage.role.in_(["user", "assistant", "tool"]))
    messages = query.order_by(HyperAiMessage.created_at.desc()).limit(max_messages).all()

    fallback_used = False
    if not messages and not conversation_id:
        messages = (
            db.query(HyperAiMessage)
            .filter(HyperAiMessage.role.in_(["user", "assistant", "tool"]))
            .order_by(HyperAiMessage.created_at.desc())
            .limit(max_messages)
            .all()
        )
        fallback_used = bool(messages)

    return list(reversed(messages)), fallback_used


def _build_transcript(messages: List[Any]) -> str:
    parts: List[str] = []
    for message in messages:
        role = str(getattr(message, "role", "unknown") or "unknown").upper()
        content = _truncate(getattr(message, "content", "") or "")
        if content:
            parts.append(f"{role}: {content}")

        tool_names = _tool_names_from_log(getattr(message, "tool_calls_log", None))
        if tool_names:
            parts.append(f"TOOLS_USED: {', '.join(tool_names)}")

    transcript = "\n\n".join(parts)
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[-MAX_TRANSCRIPT_CHARS:].lstrip()
        transcript = "[older transcript omitted]\n" + transcript
    return transcript


def _conversation_context(db: Session, conversation_ids: List[int]) -> Dict[str, Any]:
    from database.models import HyperAiConversation

    if not conversation_ids:
        return {
            "conversation_count": 0,
            "summaries_present": 0,
            "compression_points": 0,
            "latest_compressed_at": None,
        }

    conversations = db.query(HyperAiConversation).filter(
        HyperAiConversation.id.in_(conversation_ids)
    ).all()

    compression_points = 0
    latest_compressed_at = None
    summaries_present = 0
    for conversation in conversations:
        if conversation.summary:
            summaries_present += 1
        if conversation.compressed_at and (
            latest_compressed_at is None or conversation.compressed_at > latest_compressed_at
        ):
            latest_compressed_at = conversation.compressed_at

        points = _safe_json_loads(conversation.compression_points)
        if isinstance(points, list):
            compression_points += len(points)

    return {
        "conversation_count": len(conversations),
        "summaries_present": summaries_present,
        "compression_points": compression_points,
        "latest_compressed_at": latest_compressed_at.isoformat() if latest_compressed_at else None,
    }


def _memory_context(db: Session) -> Dict[str, Any]:
    from database.models import HyperAiMemory

    active_count = db.query(HyperAiMemory).filter(HyperAiMemory.is_active == True).count()
    latest_updated_at = db.query(func.max(HyperAiMemory.updated_at)).filter(
        HyperAiMemory.is_active == True
    ).scalar()

    return {
        "active_memories": int(active_count or 0),
        "latest_memory_updated_at": latest_updated_at.isoformat() if latest_updated_at else None,
    }


def _recent_user_intents(messages: List[Any]) -> List[Dict[str, Any]]:
    intents = []
    for message in messages:
        if getattr(message, "role", "") != "user":
            continue
        content = _truncate(getattr(message, "content", "") or "", limit=240)
        if not content:
            continue
        intents.append(
            {
                "conversation_id": getattr(message, "conversation_id", None),
                "message_id": getattr(message, "id", None),
                "created_at": (
                    message.created_at.isoformat()
                    if getattr(message, "created_at", None)
                    else None
                ),
                "content": content,
            }
        )
    return intents[-5:]


def _compact_architecture(db: Session) -> Dict[str, Any]:
    from services.hyper_ai_robot_architecture import collect_robot_architecture

    snapshot = collect_robot_architecture(db, include_recent_activity=False)
    architecture = snapshot.get("hyper_ai_architecture", {})
    tools = architecture.get("tools", {})
    components = architecture.get("components", {})

    return {
        "readiness": snapshot.get("readiness", {}),
        "tool_count": tools.get("total"),
        "risk_counts": tools.get("risk_counts", {}),
        "missing_risk_metadata": tools.get("missing_risk_metadata", []),
        "stale_risk_metadata": tools.get("stale_risk_metadata", []),
        "dream_review_component": components.get("dream_review", {}),
        "claude_patterns": [
            {
                "pattern": item.get("pattern"),
                "status": item.get("status"),
            }
            for item in snapshot.get("claude_patterns_applied", [])
        ],
    }


def _extract_and_save_dream_memories(
    db: Session,
    transcript: str,
    api_config: Dict[str, Any],
) -> int:
    from services.hyper_ai_memory_service import (
        MEMORY_CATEGORIES,
        batch_dedup_memories,
        extract_memories_from_conversation,
    )

    memories = extract_memories_from_conversation(transcript, api_config)
    valid = []
    for memory in memories:
        if not isinstance(memory, dict):
            continue
        category = memory.get("category", "context")
        content = _redact_sensitive(str(memory.get("content", "")).strip())
        if category not in MEMORY_CATEGORIES or len(content) < 10:
            continue
        valid.append(
            {
                "category": category,
                "content": content,
                "importance": memory.get("importance", 0.5),
            }
        )

    if not valid:
        return 0

    count = batch_dedup_memories(db, valid, api_config, source="dream_review")
    logger.warning("[DreamReview] Processed %s memories from dream review", count)
    return count


def _run_dream_memory_job(transcript: str, api_config: Dict[str, Any]) -> int:
    from database.connection import SessionLocal

    bg_db = SessionLocal()
    try:
        return _extract_and_save_dream_memories(bg_db, transcript, api_config)
    except Exception as exc:
        logger.warning(
            "[DreamReview] Background memory extraction failed: %s: %s",
            type(exc).__name__,
            exc,
        )
        return 0
    finally:
        bg_db.close()


def _build_recommendations(
    context_health: Dict[str, Any],
    architecture: Dict[str, Any],
    memory_status: Dict[str, Any],
) -> List[str]:
    recommendations = [
        "Use dream review after long strategy-design, debugging, or architecture sessions to consolidate durable lessons.",
        "Keep dream review limited to memory and architecture reflection; do not let it place trades or change trader bindings.",
    ]

    if memory_status.get("queued"):
        recommendations.append("Memory extraction is queued in the AI background executor and will deduplicate against existing memories.")
    elif memory_status.get("processed_count") is not None:
        recommendations.append("Memory extraction completed inline; review future answers for newly injected long-term context.")

    if context_health.get("compression_points", 0) == 0:
        recommendations.append("No compression points were found in the reviewed scope; current context is still mostly recent-message based.")

    readiness = architecture.get("readiness", {})
    warnings = readiness.get("warnings") or []
    if warnings:
        recommendations.append("Resolve architecture self-check warnings before expanding automation scope.")

    if architecture.get("missing_risk_metadata"):
        recommendations.append("Add explicit risk metadata for every new tool before exposing it to the main robot loop.")

    return recommendations


def execute_run_dream_review(
    db: Session,
    conversation_id: Optional[int] = None,
    conversation_ids: Optional[List[int]] = None,
    hours: int = 24,
    max_messages: int = 80,
    save_memories: bool = True,
    wait_for_memory_write: bool = False,
    api_config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Run a Claude-inspired dream review.

    The tool reviews recent Hyper AI conversation context, reports architecture/context
    health, and optionally starts memory extraction. It never trades or mutates trader
    configuration; the only allowed write is long-term memory when save_memories=True.
    """
    try:
        hours = _clamp_int(hours, default=24, minimum=1, maximum=168)
        max_messages = _clamp_int(max_messages, default=80, minimum=10, maximum=200)
        if conversation_ids:
            conversation_ids = [
                int(cid)
                for cid in conversation_ids[:50]
                if isinstance(cid, int) or (isinstance(cid, str) and cid.isdigit())
            ]

        messages, fallback_used = _load_recent_messages(
            db,
            conversation_id,
            conversation_ids,
            hours,
            max_messages,
        )
        transcript = _build_transcript(messages)
        conversation_ids = sorted({int(m.conversation_id) for m in messages if m.conversation_id})
        estimated_tokens = sum(
            int(m.token_count or max(1, len(getattr(m, "content", "") or "") // 4))
            for m in messages
        )

        context_health = {
            "messages_examined": len(messages),
            "estimated_tokens_examined": estimated_tokens,
            **_conversation_context(db, conversation_ids),
            **_memory_context(db),
        }
        architecture = _compact_architecture(db)

        memory_status: Dict[str, Any] = {
            "requested": bool(save_memories),
            "queued": False,
            "mode": "none",
        }

        if save_memories:
            if not transcript:
                memory_status["reason"] = "no_recent_conversation_text"
            elif not api_config or not api_config.get("api_key"):
                memory_status["reason"] = "llm_config_unavailable"
            elif wait_for_memory_write:
                count = _extract_and_save_dream_memories(db, transcript, dict(api_config))
                memory_status.update(
                    {
                        "mode": "inline",
                        "processed_count": count,
                    }
                )
            else:
                from services.ai_stream_service import submit_ai_background_task

                submit_ai_background_task(_run_dream_memory_job, transcript, dict(api_config))
                memory_status.update(
                    {
                        "queued": True,
                        "mode": "background",
                    }
                )

        result = {
            "success": True,
            "tool": "run_dream_review",
            "generated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "scope": {
                "conversation_id": conversation_id,
                "conversation_ids": conversation_ids or None,
                "hours": hours,
                "max_messages": max_messages,
                "conversation_ids_reviewed": conversation_ids,
                "fallback_used": fallback_used,
            },
            "context_health": context_health,
            "recent_user_intents": _recent_user_intents(messages),
            "memory_consolidation": memory_status,
            "architecture": architecture,
            "recommendations": _build_recommendations(context_health, architecture, memory_status),
            "safety": {
                "trading_actions": "none",
                "allowed_mutation": "long_term_memory_only_when_save_memories_is_true",
                "secret_handling": "obvious key/token/password assignments are redacted before memory extraction",
            },
        }

        return json.dumps(result, indent=2, ensure_ascii=False)

    except Exception as exc:
        logger.error("[run_dream_review] Error: %s", exc, exc_info=True)
        return json.dumps({"error": str(exc), "_error_class": type(exc).__name__})
