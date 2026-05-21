"""Conversation-level archive export for Hyper AI chats."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import gzip
import json
import os

from sqlalchemy import text
from sqlalchemy.orm import Session

from config.storage import get_upload_storage_settings
from services.upload_storage import UploadStorage


def list_hyper_ai_conversations(db: Session, *, archived: bool, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(text(
        """
        SELECT id, title, message_count, is_bot_conversation, created_at, updated_at,
               COALESCE(is_archived, FALSE) AS is_archived, archived_at, archive_url
        FROM hyper_ai_conversations
        WHERE COALESCE(is_onboarding, FALSE) = FALSE
          AND COALESCE(is_archived, FALSE) = :archived
        ORDER BY is_bot_conversation DESC, updated_at DESC
        LIMIT :limit
        """
    ), {"archived": archived, "limit": limit}).fetchall()

    return [
        {
            "id": row[0],
            "title": row[1],
            "message_count": row[2],
            "is_bot_conversation": bool(row[3]),
            "created_at": _iso(row[4]),
            "updated_at": _iso(row[5]),
            "is_archived": bool(row[6]),
            "archived_at": _iso(row[7]),
            "archive_url": row[8],
        }
        for row in rows
    ]


def archive_hyper_ai_conversation(db: Session, conversation_id: int) -> dict[str, Any]:
    conversation = _load_conversation(db, conversation_id)
    if not conversation:
        raise ValueError("Conversation not found")
    if conversation.get("is_onboarding"):
        raise ValueError("Onboarding conversation cannot be archived")

    payload = _conversation_payload(db, conversation)
    data = gzip.compress(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
    object_key = _archive_object_key(conversation_id)
    archive_url = _archive_storage().save_bytes(
        object_key,
        data,
        content_type="application/gzip",
    )

    db.execute(text(
        """
        UPDATE hyper_ai_conversations
        SET is_archived = TRUE,
            archived_at = CURRENT_TIMESTAMP,
            archive_object_key = :object_key,
            archive_url = :archive_url,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = :id
        """
    ), {"id": conversation_id, "object_key": object_key, "archive_url": archive_url})
    db.commit()

    return {
        "success": True,
        "conversation_id": conversation_id,
        "archive_object_key": object_key,
        "archive_url": archive_url,
    }


def unarchive_hyper_ai_conversation(db: Session, conversation_id: int) -> dict[str, Any]:
    result = db.execute(text(
        """
        UPDATE hyper_ai_conversations
        SET is_archived = FALSE,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = :id
        RETURNING id
        """
    ), {"id": conversation_id}).fetchone()
    if not result:
        raise ValueError("Conversation not found")
    db.commit()
    return {"success": True, "conversation_id": conversation_id}


def _load_conversation(db: Session, conversation_id: int) -> dict[str, Any] | None:
    row = db.execute(text(
        """
        SELECT id, title, summary, compression_points, message_count, total_tokens,
               is_bot_conversation, bot_platform, is_onboarding, created_at, updated_at
        FROM hyper_ai_conversations
        WHERE id = :id
        """
    ), {"id": conversation_id}).fetchone()
    return dict(row._mapping) if row else None


def _conversation_payload(db: Session, conversation: dict[str, Any]) -> dict[str, Any]:
    messages = db.execute(text(
        """
        SELECT id, role, content, reasoning_snapshot, tool_calls_log,
               subagent_calls_log, is_complete, interrupt_reason, token_count, created_at
        FROM hyper_ai_messages
        WHERE conversation_id = :id
        ORDER BY created_at ASC, id ASC
        """
    ), {"id": conversation["id"]}).fetchall()

    return {
        "archive_version": 1,
        "export_type": "hyper_ai_conversation_training_archive",
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "conversation": {key: _json_value(value) for key, value in conversation.items()},
        "messages": [
            {
                "id": row[0],
                "role": row[1],
                "content": row[2],
                "reasoning_snapshot": row[3],
                "tool_calls_log": row[4],
                "subagent_calls_log": row[5],
                "is_complete": row[6],
                "interrupt_reason": row[7],
                "token_count": row[8],
                "created_at": _iso(row[9]),
            }
            for row in messages
        ],
    }


def _archive_object_key(conversation_id: int) -> str:
    prefix = os.getenv("MESSAGE_ARCHIVE_PREFIX", "messages").strip().strip("/") or "messages"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}/hyper_ai_conversations/conversation-{conversation_id}/archive-{stamp}.json.gz"


def _archive_storage() -> UploadStorage:
    settings = get_upload_storage_settings()
    archive_bucket = os.getenv("MESSAGE_ARCHIVE_OSS_BUCKET", "").strip()
    if settings.mode == "oss" and archive_bucket:
        settings = settings.model_copy(update={"oss_bucket": archive_bucket, "public_base_url": None})
    return UploadStorage(settings)


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _json_value(value: Any) -> Any:
    return _iso(value)
