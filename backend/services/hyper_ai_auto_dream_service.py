"""Autonomous background dream consolidation for Hyper AI."""

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from database.models import HyperAiConversation, SystemConfig

logger = logging.getLogger(__name__)

AUTO_DREAM_JOB_ID = "hyper_ai_auto_dream"
LAST_CONSOLIDATED_KEY = "hyper_ai_auto_dream_last_consolidated_at"
STATUS_KEY = "hyper_ai_auto_dream_status"

_run_lock = threading.Lock()
_last_scan_at = 0.0


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def get_auto_dream_config() -> Dict[str, Any]:
    """Return runtime knobs for autonomous dream consolidation."""
    return {
        "enabled": _env_bool("HYPER_AI_AUTO_DREAM_ENABLED", True),
        "interval_seconds": _env_int("HYPER_AI_AUTO_DREAM_INTERVAL_SECONDS", 600, 60, 86400),
        "min_hours": _env_int("HYPER_AI_AUTO_DREAM_MIN_HOURS", 24, 1, 24 * 30),
        "min_conversations": _env_int("HYPER_AI_AUTO_DREAM_MIN_CONVERSATIONS", 5, 1, 500),
        "max_messages": _env_int("HYPER_AI_AUTO_DREAM_MAX_MESSAGES", 120, 20, 200),
        "max_conversations": _env_int("HYPER_AI_AUTO_DREAM_MAX_CONVERSATIONS", 50, 1, 500),
        "scan_throttle_seconds": _env_int("HYPER_AI_AUTO_DREAM_SCAN_THROTTLE_SECONDS", 600, 30, 86400),
    }


def _parse_datetime(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _read_config_value(db: Session, key: str) -> Optional[str]:
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    return row.value if row else None


def _write_config_value(db: Session, key: str, value: str, description: str) -> None:
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if row:
        row.value = value
        row.description = description
    else:
        db.add(SystemConfig(key=key, value=value, description=description))
    db.commit()


def _write_status(db: Session, payload: Dict[str, Any]) -> None:
    payload = {
        "updated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        **payload,
    }
    _write_config_value(
        db,
        STATUS_KEY,
        json.dumps(payload, ensure_ascii=False),
        "Hyper AI autonomous dream consolidation status",
    )


def _read_status(db: Session) -> Dict[str, Any]:
    raw = _read_config_value(db, STATUS_KEY)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"raw": raw}
    return parsed if isinstance(parsed, dict) else {"raw": raw}


def _read_last_consolidated_at(db: Session) -> Optional[datetime]:
    return _parse_datetime(_read_config_value(db, LAST_CONSOLIDATED_KEY))


def _write_last_consolidated_at(db: Session, when: datetime) -> None:
    _write_config_value(
        db,
        LAST_CONSOLIDATED_KEY,
        when.isoformat(timespec="seconds") + "Z",
        "Last successful Hyper AI autonomous dream consolidation",
    )


def _list_conversations_touched_since(
    db: Session,
    since: Optional[datetime],
    limit: int,
) -> List[int]:
    query = db.query(HyperAiConversation).filter(HyperAiConversation.is_onboarding != True)
    if since:
        query = query.filter(HyperAiConversation.updated_at > since)
    conversations = (
        query.order_by(HyperAiConversation.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [int(conversation.id) for conversation in conversations]


def get_auto_dream_status(db: Session, include_scan: bool = False) -> Dict[str, Any]:
    """Inspect the autonomous dream scheduler state."""
    cfg = get_auto_dream_config()
    last_at = _read_last_consolidated_at(db)
    status = _read_status(db)
    result = {
        "enabled": cfg["enabled"],
        "job_id": AUTO_DREAM_JOB_ID,
        "running": _run_lock.locked(),
        "config": cfg,
        "last_consolidated_at": last_at.isoformat() + "Z" if last_at else None,
        "last_status": status,
    }
    if include_scan:
        conversations = _list_conversations_touched_since(db, last_at, cfg["max_conversations"])
        result["scan"] = {
            "touched_conversations_since_last": len(conversations),
            "sample_conversation_ids": conversations[:10],
        }
    return result


def _run_auto_dream_job(
    conversation_ids: List[int],
    hours_since: float,
    cfg: Dict[str, Any],
    trigger: str,
) -> None:
    from database.connection import SessionLocal
    from services.hyper_ai_dream_service import execute_run_dream_review
    from services.hyper_ai_service import get_llm_config

    db = SessionLocal()
    started_at = datetime.utcnow()
    try:
        api_config = get_llm_config(db)
        if not api_config.get("configured") or not api_config.get("api_key"):
            _write_status(
                db,
                {
                    "status": "skipped",
                    "reason": "llm_config_unavailable",
                    "trigger": trigger,
                    "conversation_count": len(conversation_ids),
                },
            )
            return

        _write_status(
            db,
            {
                "status": "running",
                "trigger": trigger,
                "started_at_utc": started_at.isoformat(timespec="seconds") + "Z",
                "conversation_count": len(conversation_ids),
                "conversation_ids": conversation_ids[:20],
                "hours_since_last": round(hours_since, 2),
            },
        )

        raw = execute_run_dream_review(
            db,
            conversation_ids=conversation_ids,
            hours=max(1, min(168, int(hours_since) + 1)),
            max_messages=cfg["max_messages"],
            save_memories=True,
            wait_for_memory_write=True,
            api_config=api_config,
        )
        result = json.loads(raw)
        if result.get("error"):
            raise RuntimeError(result["error"])

        memory_status = result.get("memory_consolidation", {})
        context_health = result.get("context_health", {})
        finished_at = datetime.utcnow()
        _write_last_consolidated_at(db, finished_at)
        _write_status(
            db,
            {
                "status": "completed",
                "trigger": trigger,
                "started_at_utc": started_at.isoformat(timespec="seconds") + "Z",
                "finished_at_utc": finished_at.isoformat(timespec="seconds") + "Z",
                "conversation_count": len(conversation_ids),
                "conversation_ids": conversation_ids[:20],
                "messages_examined": context_health.get("messages_examined"),
                "memories_processed": memory_status.get("processed_count", 0),
            },
        )
        logger.warning(
            "[AutoDream] completed: conversations=%s messages=%s memories=%s",
            len(conversation_ids),
            context_health.get("messages_examined"),
            memory_status.get("processed_count", 0),
        )
    except Exception as exc:
        db.rollback()
        logger.warning("[AutoDream] failed: %s: %s", type(exc).__name__, exc)
        try:
            _write_status(
                db,
                {
                    "status": "failed",
                    "trigger": trigger,
                    "started_at_utc": started_at.isoformat(timespec="seconds") + "Z",
                    "error": str(exc),
                    "_error_class": type(exc).__name__,
                },
            )
        except Exception:
            logger.exception("[AutoDream] failed to persist failure status")
    finally:
        db.close()
        _run_lock.release()


def maybe_run_auto_dream(trigger: str = "scheduler") -> Dict[str, Any]:
    """
    Gate and enqueue an autonomous dream pass.

    Mirrors Claude's Auto Dream shape: cheap enabled/time/session gates first,
    then a single-process lock, then background execution.
    """
    global _last_scan_at

    cfg = get_auto_dream_config()
    if not cfg["enabled"]:
        return {"status": "skipped", "reason": "disabled", "trigger": trigger}

    now_monotonic = time.monotonic()
    if trigger == "scheduler" and now_monotonic - _last_scan_at < cfg["scan_throttle_seconds"]:
        return {"status": "skipped", "reason": "scan_throttle", "trigger": trigger}
    _last_scan_at = now_monotonic

    if not _run_lock.acquire(blocking=False):
        return {"status": "skipped", "reason": "already_running", "trigger": trigger}

    from database.connection import SessionLocal
    from services.ai_stream_service import submit_ai_background_task

    db = SessionLocal()
    try:
        last_at = _read_last_consolidated_at(db)
        if last_at:
            hours_since = (datetime.utcnow() - last_at).total_seconds() / 3600
        else:
            hours_since = cfg["min_hours"]

        if last_at and hours_since < cfg["min_hours"]:
            _run_lock.release()
            return {
                "status": "skipped",
                "reason": "time_gate",
                "trigger": trigger,
                "hours_since_last": round(hours_since, 2),
                "min_hours": cfg["min_hours"],
            }

        conversation_ids = _list_conversations_touched_since(db, last_at, cfg["max_conversations"])
        if len(conversation_ids) < cfg["min_conversations"]:
            _run_lock.release()
            _write_status(
                db,
                {
                    "status": "skipped",
                    "reason": "conversation_gate",
                    "trigger": trigger,
                    "conversation_count": len(conversation_ids),
                    "min_conversations": cfg["min_conversations"],
                },
            )
            return {
                "status": "skipped",
                "reason": "conversation_gate",
                "trigger": trigger,
                "conversation_count": len(conversation_ids),
                "min_conversations": cfg["min_conversations"],
            }

        submit_ai_background_task(
            _run_auto_dream_job,
            conversation_ids,
            hours_since,
            cfg,
            trigger,
        )
        return {
            "status": "queued",
            "trigger": trigger,
            "conversation_count": len(conversation_ids),
            "conversation_ids": conversation_ids[:20],
        }
    except Exception:
        _run_lock.release()
        raise
    finally:
        db.close()


def schedule_auto_dream_task() -> Dict[str, Any]:
    """Register autonomous dream consolidation with the shared scheduler."""
    from services.scheduler import task_scheduler

    cfg = get_auto_dream_config()
    if not cfg["enabled"]:
        logger.info("[AutoDream] disabled by HYPER_AI_AUTO_DREAM_ENABLED")
        return {"scheduled": False, "reason": "disabled", "config": cfg}

    task_scheduler.add_interval_task(
        task_func=maybe_run_auto_dream,
        interval_seconds=cfg["interval_seconds"],
        task_id=AUTO_DREAM_JOB_ID,
        trigger="scheduler",
    )
    logger.info(
        "[AutoDream] scheduled: interval=%ss min_hours=%s min_conversations=%s",
        cfg["interval_seconds"],
        cfg["min_hours"],
        cfg["min_conversations"],
    )
    return {"scheduled": True, "config": cfg}
