"""Onboarding stream parsing and profile extraction for Hyper AI."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, Generator, Optional

import requests
from sqlalchemy.orm import Session

from services.ai_decision_service import strip_thinking_tags
from services.ai_stream_service import format_sse_event

logger = logging.getLogger(__name__)


def parse_profile_data(content: str) -> Optional[Dict[str, str]]:
    patterns = [
        r"\[PROFILE_DATA\](.*?)\[COMPLETE\]",
        r"\[PROFILE_DATA\](.*?)\[/COMPLETE\]",
        r"\[PROFILE\](.*?)\[COMPLETE\]",
        r"\[PROFILE\](.*?)\[/PROFILE\]",
        r"```\s*\[PROFILE_DATA\](.*?)\[COMPLETE\]\s*```",
    ]

    block = None
    for pattern in patterns:
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            block = match.group(1).strip()
            break

    if not block:
        return None

    data = {}
    for line in block.split("\n"):
        line = line.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key in ["name", "nickname", "nick", "称呼", "昵称"]:
            key = "nickname"
        elif key in ["exp", "experience", "经验", "交易经验"]:
            key = "experience"
        elif key in ["risk", "risk_preference", "风险", "风险偏好"]:
            key = "risk"
        elif key in ["style", "trading_style", "风格", "交易风格"]:
            key = "style"
        data[key] = value

    return data if data else None


def strip_profile_markers(content: str) -> str:
    patterns = [
        r"\[PROFILE_DATA\].*?\[COMPLETE\]",
        r"\[PROFILE_DATA\].*?\[/COMPLETE\]",
        r"\[PROFILE\].*?\[COMPLETE\]",
        r"\[PROFILE\].*?\[/PROFILE\]",
        r"```\s*\[PROFILE_DATA\].*?\[COMPLETE\]\s*```",
    ]

    cleaned = content
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


def save_profile_from_onboarding(
    db: Session,
    profile_data: Dict[str, str],
    *,
    get_or_create_profile: Callable[[Session], Any],
) -> None:
    profile = get_or_create_profile(db)
    nickname = profile_data.get("nickname", "")
    if nickname:
        profile.nickname = nickname
    if profile_data.get("experience"):
        profile.experience_level = profile_data["experience"]
    if profile_data.get("risk"):
        profile.risk_preference = profile_data["risk"]
    if profile_data.get("style"):
        style = profile_data["style"]
        if style.lower() not in ["未提及", "not mentioned"]:
            profile.trading_style = style

    profile.onboarding_completed = True
    db.commit()
    logger.info("Saved onboarding profile: nickname=%s, experience=%s", nickname, profile.experience_level)


def process_onboarding_stream_response(
    db: Session,
    conversation_id: int,
    response: requests.Response,
    api_format: str,
    *,
    get_or_create_profile: Callable[[Session], Any],
    save_message: Callable[..., Any],
) -> Generator[str, None, None]:
    content_parts = []
    reasoning_parts = []

    try:
        for line in response.iter_lines():
            if not line:
                continue

            line_str = line.decode("utf-8")
            if not line_str.startswith("data: "):
                continue

            data_str = line_str[6:]
            if data_str == "[DONE]":
                break

            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            if api_format == "anthropic":
                delta = data.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        content_parts.append(text)
                        yield format_sse_event("content", {"text": text})
            else:
                choices = data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        content_parts.append(text)
                        yield format_sse_event("content", {"text": text})

                    reasoning = delta.get("reasoning_content", "")
                    if reasoning:
                        reasoning_parts.append(reasoning)
                        yield format_sse_event("reasoning", {"text": reasoning})

        full_content = "".join(content_parts)
        full_reasoning = "".join(reasoning_parts) if reasoning_parts else None
        full_content, tag_thinking = strip_thinking_tags(full_content)
        if tag_thinking:
            full_reasoning = (full_reasoning + "\n\n" + tag_thinking).strip() if full_reasoning else tag_thinking

        profile_data = parse_profile_data(full_content)
        onboarding_complete = False
        if profile_data:
            save_profile_from_onboarding(
                db,
                profile_data,
                get_or_create_profile=get_or_create_profile,
            )
            onboarding_complete = True
            display_content = strip_profile_markers(full_content)
        else:
            display_content = full_content

        if display_content:
            save_message(
                db,
                conversation_id,
                "assistant",
                display_content,
                reasoning_snapshot=full_reasoning,
                is_complete=True,
            )

        yield format_sse_event(
            "done",
            {
                "conversation_id": conversation_id,
                "content_length": len(display_content),
                "onboarding_complete": onboarding_complete,
            },
        )

    except Exception as exc:
        logger.error("Onboarding stream processing error: %s", exc, exc_info=True)
        yield format_sse_event("error", {"message": str(exc)})
