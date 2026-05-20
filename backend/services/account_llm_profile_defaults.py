"""Helpers for reusing Hyper AI LLM config in AI Trader accounts."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from sqlalchemy.orm import Session

from database.models import Account
from services.hyper_ai_config import get_llm_config


PLACEHOLDER_API_KEY = "default-key-please-update-in-settings"
LEGACY_DEFAULT_MODELS = {"gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"}
LEGACY_DEFAULT_BASE_URLS = {"https://api.openai.com/v1"}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def is_placeholder_api_key(value: Any) -> bool:
    key = _clean(value)
    return not key or key == PLACEHOLDER_API_KEY


def _is_legacy_model(value: Any) -> bool:
    model = _clean(value)
    return not model or model in LEGACY_DEFAULT_MODELS


def _is_legacy_base_url(value: Any) -> bool:
    base_url = _clean(value).rstrip("/")
    return not base_url or base_url in LEGACY_DEFAULT_BASE_URLS


def get_profile_llm_defaults(db: Session) -> Dict[str, str]:
    config = get_llm_config(db)
    if not config.get("configured"):
        return {}

    model = _clean(config.get("model"))
    base_url = _clean(config.get("base_url"))
    api_key = _clean(config.get("api_key"))
    if not model or not base_url or not api_key:
        return {}

    return {"model": model, "base_url": base_url, "api_key": api_key}


def apply_profile_llm_defaults(
    db: Session,
    payload: Dict[str, Any] | None,
) -> Tuple[Dict[str, Any], bool]:
    next_payload = dict(payload or {})
    defaults = get_profile_llm_defaults(db)
    if not defaults:
        return next_payload, False

    used = False
    if _is_legacy_model(next_payload.get("model")):
        next_payload["model"] = defaults["model"]
        used = True
    if _is_legacy_base_url(next_payload.get("base_url")):
        next_payload["base_url"] = defaults["base_url"]
        used = True
    if is_placeholder_api_key(next_payload.get("api_key")):
        next_payload["api_key"] = defaults["api_key"]
        used = True

    return next_payload, used


def sync_placeholder_accounts_with_profile(db: Session) -> int:
    defaults = get_profile_llm_defaults(db)
    if not defaults:
        return 0

    accounts = db.query(Account).filter(
        Account.account_type == "AI",
        Account.is_active == "true",
        Account.is_deleted != True,
    ).all()

    updated = 0
    for account in accounts:
        if not is_placeholder_api_key(account.api_key):
            continue

        changed = False
        if _is_legacy_model(account.model):
            account.model = defaults["model"]
            changed = True
        if _is_legacy_base_url(account.base_url):
            account.base_url = defaults["base_url"]
            changed = True

        account.api_key = defaults["api_key"]
        changed = True

        if changed:
            updated += 1

    if updated:
        db.commit()

    return updated
