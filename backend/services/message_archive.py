from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
import json
import logging
import os

from sqlalchemy import event

from database.models import (
    AiAttributionMessage,
    AiProgramMessage,
    AiPromptMessage,
    AiSignalMessage,
    HyperAiMessage,
)
from config.storage import get_upload_storage_settings
from services.upload_storage import UploadStorage, UploadStorageError

logger = logging.getLogger(__name__)

MESSAGE_MODELS = (
    HyperAiMessage,
    AiProgramMessage,
    AiPromptMessage,
    AiSignalMessage,
    AiAttributionMessage,
)

MESSAGE_TEXT_FIELDS = (
    "content",
    "reasoning_snapshot",
    "tool_calls_log",
    "subagent_calls_log",
    "prompt_result",
    "signal_configs",
    "diagnosis_result",
    "code_suggestion",
    "interrupt_reason",
)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="message-archive")
_registered = False


def message_archive_enabled() -> bool:
    return os.getenv("MESSAGE_ARCHIVE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def _prefix() -> str:
    return os.getenv("MESSAGE_ARCHIVE_PREFIX", "messages").strip().strip("/") or "messages"


def _archive_storage() -> UploadStorage:
    settings = get_upload_storage_settings()
    archive_bucket = os.getenv("MESSAGE_ARCHIVE_OSS_BUCKET", "").strip()
    if settings.mode == "oss" and archive_bucket:
        settings = settings.model_copy(
            update={
                "oss_bucket": archive_bucket,
                "public_base_url": None,
            }
        )
    return UploadStorage(settings)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _message_payload(target: Any, action: str) -> dict[str, Any]:
    text_fields = {
        field: getattr(target, field)
        for field in MESSAGE_TEXT_FIELDS
        if hasattr(target, field) and getattr(target, field) is not None
    }
    return {
        "archive_version": 1,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "table": target.__tablename__,
        "message_id": target.id,
        "conversation_id": getattr(target, "conversation_id", None),
        "role": getattr(target, "role", None),
        "is_complete": getattr(target, "is_complete", None),
        "token_count": getattr(target, "token_count", None),
        "created_at": getattr(target, "created_at", None),
        "text_fields": text_fields,
    }


def _archive_message(target: Any, action: str) -> None:
    if not message_archive_enabled():
        return

    payload = _message_payload(target, action)
    object_key = (
        f"{_prefix()}/{target.__tablename__}/"
        f"conversation-{payload['conversation_id']}/message-{target.id}.json"
    )
    data = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")

    try:
        _archive_storage().save_bytes(object_key, data, content_type="application/json; charset=utf-8")
    except UploadStorageError:
        logger.exception("Message archive storage is not configured for %s id=%s", target.__tablename__, target.id)
    except Exception:
        logger.exception("Failed to archive %s id=%s", target.__tablename__, target.id)


def _enqueue_archive(mapper, connection, target: Any) -> None:
    action = "insert" if not getattr(target, "_message_archive_seen", False) else "update"
    setattr(target, "_message_archive_seen", True)
    _executor.submit(_archive_message, target, action)


def register_message_archive_listeners() -> None:
    global _registered
    if _registered:
        return
    for model in MESSAGE_MODELS:
        event.listen(model, "after_insert", _enqueue_archive)
        event.listen(model, "after_update", _enqueue_archive)
    _registered = True
    logger.info("Message archive listeners registered for %s models", len(MESSAGE_MODELS))
