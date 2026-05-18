"""Hyper AI message and context assembly helpers."""

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from database.models import HyperAiConversation, HyperAiMessage, HyperAiProfile
from services.hyper_ai_config import get_or_create_profile, load_system_prompt
from services.hyper_ai_tools import HYPER_AI_TOOLS

MAX_CHAT_IMAGE_ATTACHMENTS = 4
MAX_CHAT_IMAGE_DATA_URL_CHARS = 9_000_000


def _normalize_chat_image_attachments(image_attachments: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in image_attachments or []:
        if len(normalized) >= MAX_CHAT_IMAGE_ATTACHMENTS:
            break
        if not isinstance(item, dict):
            continue
        data_url = str(item.get("data_url") or "").strip()
        mime_type = str(item.get("mime_type") or "").strip().lower()
        if not data_url.startswith("data:image/") or ";base64," not in data_url:
            continue
        if not mime_type.startswith("image/"):
            mime_type = data_url[5:].split(";", 1)[0].lower() or "image/png"
        if len(data_url) > MAX_CHAT_IMAGE_DATA_URL_CHARS:
            continue
        normalized.append(
            {
                "name": str(item.get("name") or f"image-{len(normalized) + 1}"),
                "mime_type": mime_type,
                "data_url": data_url,
                "size": item.get("size"),
            }
        )
    return normalized


def _build_user_storage_content(user_message: str, image_attachments: List[Dict[str, Any]]) -> str:
    if not image_attachments:
        return user_message
    lines = [user_message.strip(), "", "[Attached images]"]
    for index, image in enumerate(image_attachments, start=1):
        size = image.get("size")
        size_text = f", {round(float(size) / 1024)}KB" if isinstance(size, (int, float)) and size else ""
        lines.append(
            f"- {index}. {image.get('name') or 'pasted-image'} "
            f"({image.get('mime_type') or 'image'}{size_text})"
        )
    return "\n".join(line for line in lines if line is not None)


def _build_user_message_content(
    user_message: str,
    image_attachments: Optional[List[Dict[str, Any]]] = None,
) -> Any:
    images = _normalize_chat_image_attachments(image_attachments)
    if not images:
        return user_message
    blocks: List[Dict[str, Any]] = [{"type": "text", "text": user_message}]
    for image in images:
        blocks.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": image["data_url"],
                    "detail": "auto",
                },
            }
        )
    return blocks


def build_messages_for_api(
    db: Session,
    conversation_id: int,
    user_message: str,
    api_config: Dict[str, Any],
    include_tools: bool = True,
    image_attachments: Optional[List[Dict[str, Any]]] = None,
) -> tuple[List[Dict[str, Any]], Optional[List[Dict]], Optional[str]]:
    """
    Build message list for LLM API call with automatic compression.

    Uses compression_points to skip already-compressed messages.
    Returns (messages, tools, command_skill) tuple.
    command_skill is set when user used /command mode.
    """
    from services.ai_context_compression_service import (
        compress_messages,
        filter_messages_by_compression,
        get_last_compression_point,
        restore_tool_calls_to_messages,
        update_compression_points,
    )

    messages = []

    profile = get_or_create_profile(db)
    system_prompt = load_system_prompt()

    from services.hyper_ai_skill_engine import (
        build_skills_metadata_prompt,
        get_enabled_skills,
        scan_all_skills,
    )

    all_skills = scan_all_skills()
    enabled_skills = get_enabled_skills(all_skills, profile.enabled_skills)
    skills_prompt = build_skills_metadata_prompt(enabled_skills)
    system_prompt = system_prompt.replace("{available_skills}", skills_prompt)

    command_skill = None
    skill_injection = None
    skill_lookup = {}
    for skill in enabled_skills:
        skill_lookup[skill["name"]] = skill["name"]
        if skill.get("shortcut"):
            skill_lookup[skill["shortcut"]] = skill["name"]
    if user_message.startswith("/"):
        parts = user_message.split(None, 1)
        candidate = parts[0][1:]
        resolved_name = skill_lookup.get(candidate)
        if resolved_name:
            from services.hyper_ai_skill_engine import load_skill

            skill_result = load_skill(resolved_name)
            if skill_result.get("success"):
                command_skill = resolved_name
                skill_injection = (
                    f"[Active Skill: {resolved_name}]\n"
                    f"The user triggered this skill via /{candidate} command. "
                    f"You MUST follow the workflow below step by step, "
                    f"executing ALL phases and checkpoints.\n\n"
                    f"{skill_result['content']}"
                )
                user_message = parts[1].strip() if len(parts) > 1 else "Please start this skill workflow."

    messages.append({"role": "system", "content": system_prompt})

    if profile.onboarding_completed:
        profile_context = _build_profile_context(profile)
        if profile_context:
            messages.append({
                "role": "system",
                "content": f"User Profile:\n{profile_context}",
            })

    memory_context = _build_memory_context(db)
    if memory_context:
        messages.append({
            "role": "system",
            "content": memory_context,
        })

    conversation = db.query(HyperAiConversation).filter(
        HyperAiConversation.id == conversation_id
    ).first()
    cp = get_last_compression_point(conversation) if conversation else None

    if cp and cp.get("summary"):
        messages.append({
            "role": "system",
            "content": f"[Previous conversation summary]\n{cp['summary']}",
        })

    history_orm = db.query(HyperAiMessage).filter(
        HyperAiMessage.conversation_id == conversation_id
    ).order_by(HyperAiMessage.created_at).limit(100).all()
    history_orm = filter_messages_by_compression(history_orm, cp)
    last_message_id = history_orm[-1].id if history_orm else None

    api_format = api_config.get("api_format", "openai")
    history_dicts = [
        {
            "role": message.role,
            "content": message.content,
            "tool_calls_log": message.tool_calls_log,
            "reasoning_snapshot": message.reasoning_snapshot,
        }
        for message in history_orm
    ]
    restored_history = restore_tool_calls_to_messages(
        history_dicts,
        api_format,
        model=api_config.get("model", ""),
    )
    messages.extend(restored_history)

    current_user_content = _build_user_message_content(user_message, image_attachments)
    if messages and messages[-1].get("role") == "user":
        messages[-1]["content"] = current_user_content
    else:
        messages.append({"role": "user", "content": current_user_content})

    if skill_injection:
        user_msg = messages.pop()
        messages.append({"role": "system", "content": skill_injection})
        messages.append(user_msg)

    result = compress_messages(messages, api_config, db=db)
    messages = result["messages"]

    if result["compressed"] and result["summary"] and last_message_id and conversation:
        update_compression_points(
            conversation,
            last_message_id,
            result["summary"],
            result["compressed_at"],
            db,
        )

    tools = HYPER_AI_TOOLS if include_tools else None

    return messages, tools, command_skill


def _build_profile_context(profile: HyperAiProfile) -> str:
    """Build profile context string for system prompt."""
    parts = []
    if profile.trading_style:
        parts.append(f"Trading Style: {profile.trading_style}")
    if profile.risk_preference:
        parts.append(f"Risk Preference: {profile.risk_preference}")
    if profile.experience_level:
        parts.append(f"Experience Level: {profile.experience_level}")
    if profile.preferred_symbols:
        parts.append(f"Preferred Symbols: {profile.preferred_symbols}")
    if profile.preferred_timeframe:
        parts.append(f"Preferred Timeframe: {profile.preferred_timeframe}")
    if profile.capital_scale:
        parts.append(f"Capital Scale: {profile.capital_scale}")
    return "\n".join(parts)


def _build_memory_context(db: Session) -> str:
    """
    Build long-term memory context for system prompt injection.

    Groups memories by category for readability.
    """
    from services.hyper_ai_memory_service import MAX_MEMORIES, get_memories

    memories = get_memories(db, limit=MAX_MEMORIES)
    if not memories:
        return ""

    groups: Dict[str, List[str]] = {}
    category_labels = {
        "preference": "Trading Preferences",
        "decision": "Key Decisions",
        "lesson": "Lessons Learned",
        "insight": "Market Insights",
        "context": "Context",
    }

    for memory in memories:
        category = memory.get("category", "context")
        label = category_labels.get(category, category.title())
        if label not in groups:
            groups[label] = []
        groups[label].append(memory["content"])

    parts = ["Long-term Memory (insights from past conversations):"]
    for label, items in groups.items():
        parts.append(f"\n[{label}]")
        for item in items:
            parts.append(f"- {item}")

    return "\n".join(parts)
