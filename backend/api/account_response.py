"""Shared account response helpers that never expose raw API keys."""

from __future__ import annotations

from typing import Any, Optional

from database.models import Account, User

DEFAULT_API_KEY_PLACEHOLDER = "default-key-please-update-in-settings"


def public_api_key(api_key: Optional[str]) -> str:
    """Return a display-safe API key value for frontend compatibility."""
    if not api_key:
        return ""
    if api_key == DEFAULT_API_KEY_PLACEHOLDER:
        return DEFAULT_API_KEY_PLACEHOLDER
    suffix = api_key[-4:] if len(api_key) >= 4 else ""
    return f"{'*' * 12}{suffix}" if suffix else "************"


def has_real_api_key(api_key: Optional[str]) -> bool:
    return bool(api_key and api_key != DEFAULT_API_KEY_PLACEHOLDER)


def is_public_api_key_mask(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if value == DEFAULT_API_KEY_PLACEHOLDER:
        return False
    stripped = value.strip()
    if len(stripped) < 8:
        return False
    prefix = stripped[:-4]
    return bool(prefix) and all(ch in {"*", "•"} for ch in prefix)


def serialize_account(
    account: Account,
    user: Optional[User] = None,
    *,
    current_cash: Optional[float] = None,
    frozen_cash: Optional[float] = None,
    wallet_address: Optional[str] = None,
    has_mainnet_wallet: bool = False,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    api_key = public_api_key(account.api_key)
    data = {
        "id": account.id,
        "user_id": account.user_id,
        "username": user.username if user else "unknown",
        "name": account.name,
        "account_type": account.account_type,
        "exchange": getattr(account, "exchange", None) or "binance",
        "initial_capital": float(account.initial_capital),
        "current_cash": current_cash if current_cash is not None else float(account.current_cash),
        "frozen_cash": frozen_cash if frozen_cash is not None else float(account.frozen_cash),
        "model": account.model,
        "base_url": account.base_url,
        "api_key": api_key,
        "api_key_masked": api_key,
        "has_api_key": has_real_api_key(account.api_key),
        "is_active": account.is_active == "true",
        "auto_trading_enabled": account.auto_trading_enabled == "true",
        "wallet_address": wallet_address,
        "has_mainnet_wallet": has_mainnet_wallet,
        "show_on_dashboard": account.show_on_dashboard,
        "avatar_preset_id": account.avatar_preset_id,
    }
    if extra:
        data.update(extra)
    return data
