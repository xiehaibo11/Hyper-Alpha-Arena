"""Hyper AI conversation persistence helpers."""

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from database.models import HyperAiConversation, HyperAiMessage


def get_or_create_conversation(
    db: Session,
    conversation_id: Optional[int] = None,
    is_onboarding: bool = False,
) -> HyperAiConversation:
    """Get existing conversation or create a new one."""
    if conversation_id:
        conversation = db.query(HyperAiConversation).filter(
            HyperAiConversation.id == conversation_id
        ).first()
        if conversation:
            return conversation

    conversation = HyperAiConversation(title="Hyper AI Chat", is_onboarding=is_onboarding)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def get_conversation_messages(
    db: Session,
    conversation_id: int,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Get recent messages from a conversation."""
    messages = db.query(HyperAiMessage).filter(
        HyperAiMessage.conversation_id == conversation_id
    ).order_by(HyperAiMessage.created_at.desc()).limit(limit).all()

    return [
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "reasoning_snapshot": message.reasoning_snapshot,
            "tool_calls_log": message.tool_calls_log,
            "is_complete": message.is_complete,
            "created_at": message.created_at.isoformat() if message.created_at else None,
        }
        for message in reversed(messages)
    ]


def save_message(
    db: Session,
    conversation_id: int,
    role: str,
    content: str,
    reasoning_snapshot: Optional[str] = None,
    tool_calls_log: Optional[str] = None,
    is_complete: bool = True,
    interrupt_reason: Optional[str] = None,
) -> HyperAiMessage:
    """Save a message to the conversation."""
    message = HyperAiMessage(
        conversation_id=conversation_id,
        role=role,
        content=content,
        reasoning_snapshot=reasoning_snapshot,
        tool_calls_log=tool_calls_log,
        is_complete=is_complete,
        interrupt_reason=interrupt_reason,
    )
    db.add(message)

    conversation = db.query(HyperAiConversation).filter(
        HyperAiConversation.id == conversation_id
    ).first()
    if conversation:
        conversation.message_count = (conversation.message_count or 0) + 1
        if role == "user" and conversation.title == "Hyper AI Chat" and content:
            conversation.title = content[:50] + ("..." if len(content) > 50 else "")

    db.commit()
    db.refresh(message)
    return message
