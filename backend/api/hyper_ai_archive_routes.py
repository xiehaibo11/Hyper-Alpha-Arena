"""Hyper AI conversation archive routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database.connection import get_db
from services.hyper_ai_conversation_archive import (
    archive_hyper_ai_conversation,
    list_hyper_ai_conversations,
    unarchive_hyper_ai_conversation,
)

router = APIRouter(prefix="/api/hyper-ai", tags=["Hyper AI Archive"])


@router.get("/conversations")
def list_conversations(
    archived: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List active or archived Hyper AI conversations."""
    return {
        "conversations": list_hyper_ai_conversations(
            db,
            archived=archived,
            limit=limit,
        )
    }


@router.post("/conversations/{conversation_id}/archive")
def archive_conversation(conversation_id: int, db: Session = Depends(get_db)):
    """Archive a conversation and upload a compressed training-data package."""
    try:
        return archive_hyper_ai_conversation(db, conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Archive failed: {exc}") from exc


@router.post("/conversations/{conversation_id}/unarchive")
def unarchive_conversation(conversation_id: int, db: Session = Depends(get_db)):
    """Restore an archived conversation to the active list."""
    try:
        return unarchive_hyper_ai_conversation(db, conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
