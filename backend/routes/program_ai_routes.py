"""AI-assisted program coding routes."""

import json
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Account, User
from routes.program_schemas import (
    AiProgramChatRequest,
    ConversationResponse,
    MessageResponse,
    SaveSuggestionResponse,
)

router = APIRouter()

@router.post("/ai-chat")
async def ai_program_chat(
    request: AiProgramChatRequest,
    db: Session = Depends(get_db)
):
    """
    AI-assisted program coding with SSE streaming.
    Supports both SSE mode (default) and background task mode.
    """
    from fastapi.responses import StreamingResponse
    from services.ai_program_service import generate_program_with_ai_stream
    from services.ai_stream_service import (
        get_buffer_manager, run_ai_task_in_background, generate_task_id
    )
    from database.connection import SessionLocal

    user = db.query(User).first()
    user_id = user.id if user else 1

    # Background task mode: return task_id immediately
    if request.use_background_task:
        task_id = generate_task_id("program")
        manager = get_buffer_manager()
        manager.create_task(task_id, conversation_id=request.conversation_id)

        # Capture request params for background thread
        account_id = request.account_id
        user_message = request.message
        conversation_id = request.conversation_id
        program_id = request.program_id

        def generator_func():
            bg_db = SessionLocal()
            try:
                yield from generate_program_with_ai_stream(
                    db=bg_db,
                    account_id=account_id,
                    user_message=user_message,
                    conversation_id=conversation_id,
                    program_id=program_id,
                    user_id=user_id
                )
            finally:
                bg_db.close()

        run_ai_task_in_background(task_id, generator_func)
        return {"task_id": task_id, "status": "started"}

    # SSE mode (default): stream directly
    def event_generator():
        yield from generate_program_with_ai_stream(
            db=db,
            account_id=request.account_id,
            user_message=request.message,
            conversation_id=request.conversation_id,
            program_id=request.program_id,
            user_id=user_id
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/ai-conversations", response_model=List[ConversationResponse])
async def list_ai_conversations(
    program_id: Optional[int] = None,
    limit: int = Query(default=20, le=100),
    db: Session = Depends(get_db)
):
    """List AI program coding conversations."""
    from database.models import AiProgramConversation

    user = db.query(User).first()
    user_id = user.id if user else 1

    query = db.query(AiProgramConversation).filter(
        AiProgramConversation.user_id == user_id
    )

    if program_id:
        query = query.filter(AiProgramConversation.program_id == program_id)

    conversations = query.order_by(
        AiProgramConversation.updated_at.desc()
    ).limit(limit).all()

    return [
        ConversationResponse(
            id=c.id,
            program_id=c.program_id,
            title=c.title,
            created_at=c.created_at.isoformat() if c.created_at else "",
            updated_at=c.updated_at.isoformat() if c.updated_at else ""
        )
        for c in conversations
    ]


@router.get("/ai-conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: int,
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """Get messages for a specific conversation with compression points and token usage."""
    from database.models import AiProgramConversation, AiProgramMessage, HyperAiProfile
    from services.ai_context_compression_service import calculate_token_usage, restore_tool_calls_to_messages

    user = db.query(User).first()
    user_id = user.id if user else 1

    conversation = db.query(AiProgramConversation).filter(
        AiProgramConversation.id == conversation_id,
        AiProgramConversation.user_id == user_id
    ).first()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = db.query(AiProgramMessage).filter(
        AiProgramMessage.conversation_id == conversation_id
    ).order_by(AiProgramMessage.created_at).all()

    result = []
    for m in messages:
        # Parse code_suggestion JSON to saveSuggestion object
        save_suggestion = None
        if m.code_suggestion:
            try:
                parsed = json.loads(m.code_suggestion)
                if isinstance(parsed, dict) and "code" in parsed:
                    save_suggestion = SaveSuggestionResponse(
                        code=parsed.get("code", ""),
                        name=parsed.get("name", "Saved Code"),
                        description=parsed.get("description", "")
                    )
                else:
                    # Old format: just code string, construct default object
                    save_suggestion = SaveSuggestionResponse(
                        code=m.code_suggestion,
                        name="Saved Code",
                        description=""
                    )
            except json.JSONDecodeError:
                # Not JSON, treat as plain code string
                save_suggestion = SaveSuggestionResponse(
                    code=m.code_suggestion,
                    name="Saved Code",
                    description=""
                )

        result.append(MessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            saveSuggestion=save_suggestion,
            reasoning_snapshot=m.reasoning_snapshot,
            tool_calls_log=json.loads(m.tool_calls_log) if m.tool_calls_log else None,
            created_at=m.created_at.isoformat() if m.created_at else "",
            is_complete=m.is_complete if m.is_complete is not None else True
        ))

    # Get compression points
    compression_points = []
    if conversation.compression_points:
        try:
            compression_points = json.loads(conversation.compression_points)
        except (json.JSONDecodeError, TypeError):
            compression_points = []

    # Determine model for token calculation: prefer account model, fallback to global
    token_model = None
    api_format = "openai"
    if account_id:
        account = db.query(Account).filter(Account.id == account_id).first()
        if account and account.model:
            token_model = account.model
            from services.ai_decision_service import detect_api_format
            _, fmt = detect_api_format(account.base_url or "")
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
    if token_model and result:
        from services.ai_context_compression_service import get_last_compression_point

        cp = get_last_compression_point(conversation)
        cp_msg_id = cp.get("message_id", 0) if cp else 0
        filtered = [m for m in result if m.id > cp_msg_id]

        msg_list = restore_tool_calls_to_messages(
            [
                {
                    "role": m.role,
                    "content": m.content,
                    "tool_calls_log": m.tool_calls_log,
                    "reasoning_snapshot": m.reasoning_snapshot,
                }
                for m in filtered
            ],
            api_format,
            model=token_model or ""
        )
        if cp and cp.get("summary"):
            msg_list.insert(0, {"role": "system", "content": cp["summary"]})
        token_usage = calculate_token_usage(msg_list, token_model)

    return {
        "messages": result,
        "compression_points": compression_points,
        "token_usage": token_usage
    }
