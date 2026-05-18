"""Hyper AI prompt, profile, and LLM configuration helpers."""

import logging
import os
import random
from typing import Any, Dict, Optional

import requests
from sqlalchemy.orm import Session

from database.models import HyperAiProfile
from services.ai_decision_service import (
    build_llm_headers,
    build_llm_payload,
    detect_api_format,
)
from services.hyper_ai_llm_providers import get_provider
from utils.encryption import decrypt_private_key, encrypt_private_key

logger = logging.getLogger(__name__)

API_MAX_RETRIES = 5
API_BASE_DELAY = 1.0
API_MAX_DELAY = 16.0
RETRYABLE_STATUS_CODES = {502, 503, 504, 429}

SYSTEM_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "config",
    "hyper_ai_system_prompt.md",
)
ONBOARDING_PROMPT_EN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "config",
    "hyper_ai_onboarding_prompt.md",
)
ONBOARDING_PROMPT_ZH_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "config",
    "hyper_ai_onboarding_prompt_zh.md",
)

DEFAULT_ONBOARDING_PROMPT_EN = """You are Hyper AI, a friendly trading assistant helping a new user get started.

Your goal is to have a natural conversation to learn about the user's trading background and preferences.

Information to collect (through natural conversation, not interrogation):
- Trading experience level (beginner/intermediate/advanced)
- Risk preference (conservative/moderate/aggressive)
- Trading style (day trading/swing trading/position trading/scalping)
- Preferred trading symbols (BTC, ETH, SOL, etc.)

Be warm, conversational, and helpful. Ask follow-up questions naturally.
When you have enough information, let the user know they're all set to explore the system.
"""

DEFAULT_ONBOARDING_PROMPT_ZH = """你是 Hyper AI，一个友好的交易助手，正在帮助新用户入门。

你的目标是通过自然的对话了解用户的交易背景和偏好。

需要收集的信息（通过自然对话，而不是审问）：
- 交易经验水平（新手/有一定经验/资深）
- 风险偏好（保守/稳健/激进）
- 交易风格（日内交易/波段交易/趋势交易/超短线）
- 偏好的交易品种（BTC、ETH、SOL 等）

保持温暖、对话式的风格，自然地提出后续问题。
当你收集到足够的信息后，告诉用户他们已经准备好探索系统了。
"""


def should_retry_api(status_code: Optional[int], error: Optional[str]) -> bool:
    """Check if API error is retryable."""
    if status_code and status_code in RETRYABLE_STATUS_CODES:
        return True
    if error and any(text in error.lower() for text in ["timeout", "connection", "reset"]):
        return True
    return False


def get_retry_delay(attempt: int) -> float:
    """Calculate retry delay with exponential backoff and jitter."""
    delay = min(API_BASE_DELAY * (2 ** attempt), API_MAX_DELAY)
    jitter = random.uniform(0, delay * 0.1)
    return delay + jitter


def load_system_prompt() -> str:
    """Load the Hyper AI system prompt from markdown file."""
    try:
        with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as file:
            return file.read()
    except Exception as exc:
        logger.error(f"Failed to load Hyper AI system prompt: {exc}")
        return "You are Hyper AI, an intelligent trading assistant."


def load_onboarding_prompt(lang: str = "en") -> str:
    """Load the onboarding-specific system prompt based on language."""
    prompt_path = ONBOARDING_PROMPT_ZH_PATH if lang == "zh" else ONBOARDING_PROMPT_EN_PATH
    try:
        with open(prompt_path, "r", encoding="utf-8") as file:
            return file.read()
    except Exception as exc:
        logger.error(f"Failed to load onboarding prompt ({lang}): {exc}")
        if lang == "zh":
            return DEFAULT_ONBOARDING_PROMPT_ZH
        return DEFAULT_ONBOARDING_PROMPT_EN


def get_or_create_profile(db: Session) -> HyperAiProfile:
    """Get existing profile or create a new one (single-user system)."""
    profile = db.query(HyperAiProfile).first()
    if not profile:
        profile = HyperAiProfile()
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def get_llm_config(db: Session) -> Dict[str, Any]:
    """Get LLM configuration from user profile."""
    profile = get_or_create_profile(db)

    if not profile.llm_provider:
        return {"configured": False}

    provider = get_provider(profile.llm_provider)
    base_url = profile.llm_base_url or (provider.base_url if provider else "")
    model = profile.llm_model or (provider.models[0] if provider and provider.models else "")

    api_key = None
    if profile.llm_api_key_encrypted:
        try:
            api_key = decrypt_private_key(profile.llm_api_key_encrypted)
        except Exception as exc:
            logger.error(f"Failed to decrypt API key: {exc}")

    if profile.llm_provider == "custom" and base_url:
        _, api_format = detect_api_format(base_url)
        api_format = api_format or "openai"
    else:
        api_format = provider.api_format if provider else "openai"

    return {
        "configured": True,
        "provider": profile.llm_provider,
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "api_format": api_format,
    }


def test_llm_connection(
    provider: str,
    api_key: str,
    model: str,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Test LLM connection by making a simple API call.

    Returns {"success": True} or {"success": False, "error": "message"}.
    """
    provider_config = get_provider(provider)

    if provider == "custom":
        if not base_url:
            return {"success": False, "error": "Base URL is required for custom provider"}
        url, api_format = detect_api_format(base_url)
        if not url:
            return {"success": False, "error": "Invalid Base URL"}
        api_format = api_format or "openai"
    else:
        if not provider_config:
            return {"success": False, "error": f"Unknown provider: {provider}"}
        effective_base_url = base_url or provider_config.base_url
        api_format = provider_config.api_format
        if api_format == "anthropic":
            url = f"{effective_base_url.rstrip('/')}/messages"
        else:
            url = f"{effective_base_url.rstrip('/')}/chat/completions"

    if not model:
        model = provider_config.models[0] if provider_config and provider_config.models else "gpt-3.5-turbo"

    try:
        headers = build_llm_headers(api_format, api_key, url)
        payload = build_llm_payload(
            model=model,
            messages=[{"role": "user", "content": "Hi"}],
            api_format=api_format,
            max_tokens=10,
        )

        response = requests.post(url, headers=headers, json=payload, timeout=30)

        if response.status_code == 200:
            return {"success": True}

        error_msg = response.text[:200] if response.text else f"HTTP {response.status_code}"
        try:
            err_json = response.json()
            if "error" in err_json:
                if isinstance(err_json["error"], dict):
                    error_msg = err_json["error"].get("message", error_msg)
                else:
                    error_msg = str(err_json["error"])
        except Exception:
            pass
        return {"success": False, "error": error_msg}

    except requests.exceptions.Timeout:
        return {"success": False, "error": "Connection timeout"}
    except requests.exceptions.ConnectionError as exc:
        return {"success": False, "error": f"Connection failed: {str(exc)[:100]}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)[:200]}


def save_llm_config(
    db: Session,
    provider: str,
    api_key: str,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> HyperAiProfile:
    """Save LLM configuration to user profile."""
    profile = get_or_create_profile(db)
    profile.llm_provider = provider
    profile.llm_model = model
    profile.llm_base_url = base_url

    if api_key:
        profile.llm_api_key_encrypted = encrypt_private_key(api_key)

    db.commit()
    db.refresh(profile)
    return profile


_should_retry_api = should_retry_api
_get_retry_delay = get_retry_delay
