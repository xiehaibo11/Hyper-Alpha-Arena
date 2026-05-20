"""Live overrides that reuse Hyper AI LLM config for AI Trader accounts."""

from __future__ import annotations

import logging
import random
import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.account_llm_routes import test_llm_connection as test_llm_with_payload
from database.connection import get_db
from database.models import Account, AccountAssetSnapshot, User
from services.account_llm_profile_defaults import (
    apply_profile_llm_defaults,
    is_placeholder_api_key,
    sync_placeholder_accounts_with_profile,
)
from services.asset_curve_calculator import invalidate_asset_curve_cache

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/account", tags=["account"])


def _normalize_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "on"}
    return bool(value)


def _get_default_user(db: Session) -> User:
    user = db.query(User).filter(User.username == "default").first()
    if not user:
        user = db.query(User).first()
    if not user:
        raise HTTPException(status_code=404, detail="No user found")
    return user


def _reset_auto_trading_job_async() -> None:
    try:
        from services.scheduler import reset_auto_trading_job

        reset_auto_trading_job()
        logger.info("Auto trading job reset successfully after account change")
    except Exception as exc:
        logger.warning("Failed to reset auto trading job: %s", exc)


def _record_initial_snapshot(db: Session, account: Account) -> None:
    try:
        initial_total = Decimal(str(account.initial_capital))
        snapshot = AccountAssetSnapshot(
            account_id=account.id,
            total_assets=initial_total,
            cash=Decimal(str(account.current_cash)),
            positions_value=Decimal("0"),
            event_time=datetime.now(timezone.utc),
            trigger_symbol=None,
            trigger_market="CRYPTO",
        )
        db.add(snapshot)
        db.commit()
        invalidate_asset_curve_cache()
    except Exception as exc:
        db.rollback()
        logger.warning("Failed to create initial account snapshot for %s: %s", account.id, exc)


@router.post("/test-llm")
def test_llm_connection(payload: Dict[str, Any], db: Session = Depends(get_db)):
    payload, used_profile = apply_profile_llm_defaults(db, payload)
    result = test_llm_with_payload(payload)
    if used_profile:
        result["used_profile_llm_config"] = True
    return result


@router.post("/")
def create_new_account(payload: Dict[str, Any], db: Session = Depends(get_db)):
    try:
        user = _get_default_user(db)
        payload, used_profile = apply_profile_llm_defaults(db, payload)

        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Account name is required")

        account_type = payload.get("account_type", "AI")
        if account_type == "AI" and is_placeholder_api_key(payload.get("api_key")):
            raise HTTPException(
                status_code=400,
                detail="AI Trader LLM config is missing. Configure Hyper AI model settings first.",
            )

        initial_capital = float(payload.get("initial_capital", 10000.0))
        account = Account(
            user_id=user.id,
            version="v1",
            name=name,
            account_type=account_type,
            model=payload.get("model") or "gpt-4-turbo",
            base_url=payload.get("base_url") or "https://api.openai.com/v1",
            api_key=payload.get("api_key") or "",
            initial_capital=initial_capital,
            current_cash=initial_capital,
            frozen_cash=0.0,
            is_active="true",
            auto_trading_enabled="true" if _normalize_bool(payload.get("auto_trading_enabled")) else "false",
            avatar_preset_id=random.randint(1, 12),
        )
        db.add(account)
        db.commit()
        db.refresh(account)

        _record_initial_snapshot(db, account)
        threading.Thread(target=_reset_auto_trading_job_async, daemon=True).start()

        return {
            "id": account.id,
            "user_id": account.user_id,
            "username": user.username,
            "name": account.name,
            "account_type": account.account_type,
            "initial_capital": float(account.initial_capital),
            "current_cash": float(account.current_cash),
            "frozen_cash": float(account.frozen_cash),
            "model": account.model,
            "base_url": account.base_url,
            "api_key": account.api_key,
            "is_active": account.is_active == "true",
            "auto_trading_enabled": account.auto_trading_enabled == "true",
            "avatar_preset_id": account.avatar_preset_id,
            "used_profile_llm_config": used_profile,
        }
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Failed to create account with profile defaults: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create account: {exc}") from exc


@router.get("/list")
def list_all_accounts(include_hidden: bool = False, db: Session = Depends(get_db)):
    sync_placeholder_accounts_with_profile(db)

    from api.account_routes import list_all_accounts as original_list_all_accounts

    return original_list_all_accounts(include_hidden=include_hidden, db=db)
