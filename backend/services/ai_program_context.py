"""Conversation and message context helpers for AI program generation."""

from typing import Any, Dict, Optional, Tuple
from sqlalchemy.orm import Session

from database.models import AiProgramConversation, AiProgramMessage, TradingProgram, Account
from services.ai_decision_service import detect_api_format
from services.ai_program_prompt import PROGRAM_SYSTEM_PROMPT


def prepare_program_generation_context(
    db: Session,
    account_id: Optional[int],
    user_message: str,
    conversation_id: Optional[int],
    program_id: Optional[int],
    user_id: int,
    llm_config: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], AiProgramConversation, bool, list]:
    """Resolve API config, persist the user message, and build compressed LLM messages."""
    if llm_config:
        api_config = {
            "base_url": llm_config.get("base_url"),
            "api_key": llm_config.get("api_key"),
            "model": llm_config.get("model"),
            "api_format": llm_config.get("api_format", "openai"),
        }
    else:
        account = db.query(Account).filter(
            Account.id == account_id,
            Account.account_type == "AI",
            Account.is_deleted != True,
        ).first()
        if not account:
            raise ValueError("AI account not found")
        api_config = {
            "base_url": account.base_url,
            "api_key": account.api_key,
            "model": account.model,
            "api_format": detect_api_format(account.base_url)[1] or "openai",
        }

    conversation = None
    if conversation_id:
        conversation = db.query(AiProgramConversation).filter(
            AiProgramConversation.id == conversation_id,
            AiProgramConversation.user_id == user_id,
        ).first()

    created = False
    if not conversation:
        title = user_message[:50] + "..." if len(user_message) > 50 else user_message
        conversation = AiProgramConversation(user_id=user_id, program_id=program_id, title=title)
        db.add(conversation)
        db.flush()
        created = True

    user_msg = AiProgramMessage(conversation_id=conversation.id, role="user", content=user_message)
    db.add(user_msg)
    db.flush()

    system_prompt = _build_dynamic_program_prompt(db, program_id, user_id)
    messages = _build_compressed_program_messages(db, conversation, user_msg, user_message, system_prompt, api_config)
    return api_config, conversation, created, messages


def _build_dynamic_program_prompt(db: Session, program_id: Optional[int], user_id: int) -> str:
    system_prompt = PROGRAM_SYSTEM_PROMPT
    if program_id:
        program = db.query(TradingProgram).filter(
            TradingProgram.id == program_id,
            TradingProgram.user_id == user_id,
            TradingProgram.is_deleted != True,
        ).first()
        if program:
            return system_prompt + f"""
You are editing an existing program:
- **Program ID**: {program.id}
- **Program Name**: {program.name}
- **Description**: {program.description or 'No description'}

**IMPORTANT**: Before making any changes, you MUST first call `get_current_code` to understand the existing implementation. Then modify the code based on user's requirements while preserving the overall structure unless explicitly asked to rewrite.
"""

    return system_prompt + """

## CURRENT CONTEXT
You are creating a new program. Start fresh and design the strategy based on user's requirements.
"""


def _build_compressed_program_messages(
    db: Session,
    conversation: AiProgramConversation,
    user_msg: AiProgramMessage,
    user_message: str,
    system_prompt: str,
    api_config: Dict[str, Any],
) -> list:
    from services.ai_context_compression_service import (
        compress_messages,
        update_compression_points,
        restore_tool_calls_to_messages,
        get_last_compression_point,
        filter_messages_by_compression,
    )

    messages = [{"role": "system", "content": system_prompt}]
    cp = get_last_compression_point(conversation)
    if cp and cp.get("summary"):
        messages.append({"role": "system", "content": f"[Previous conversation summary]\n{cp['summary']}"})

    history = db.query(AiProgramMessage).filter(
        AiProgramMessage.conversation_id == conversation.id,
        AiProgramMessage.id != user_msg.id,
    ).order_by(AiProgramMessage.created_at).limit(100).all()
    history = filter_messages_by_compression(history, cp)
    last_message_id = history[-1].id if history else None

    history_dicts = [
        {
            "role": m.role,
            "content": m.content,
            "tool_calls_log": m.tool_calls_log,
            "reasoning_snapshot": m.reasoning_snapshot,
        }
        for m in history
    ]
    restored = restore_tool_calls_to_messages(
        history_dicts,
        api_config.get("api_format", "openai"),
        model=api_config.get("model", ""),
    )
    messages.extend(restored)
    messages.append({"role": "user", "content": user_message})

    result = compress_messages(messages, api_config, db=db)
    if result["compressed"] and result["summary"] and last_message_id:
        update_compression_points(conversation, last_message_id, result["summary"], result["compressed_at"], db)
    return result["messages"]
