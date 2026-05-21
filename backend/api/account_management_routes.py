"""Account management routes split from the legacy account module."""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.account_response import is_public_api_key_mask, serialize_account
from database.connection import SessionLocal
from database.models import Account, AccountAssetSnapshot, HyperliquidWallet, Position, User
from services.asset_curve_calculator import invalidate_asset_curve_cache
from services.entity_deletion_service import delete_trader
from services.hyperliquid_cache import get_cached_account_state
from utils.runtime_diagnostics import get_current_thread_count, log_hot_path_delta

logger = logging.getLogger(__name__)
router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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


def _reset_auto_trading_job_async(context: str) -> None:
    try:
        from services.scheduler import reset_auto_trading_job

        reset_auto_trading_job()
        logger.info("Auto trading job reset successfully after %s", context)
    except Exception as exc:
        logger.warning("Failed to reset auto trading job after %s: %s", context, exc)


def _get_default_user(db: Session) -> User:
    user = db.query(User).filter(User.username == "default").first() or db.query(User).first()
    if not user:
        raise HTTPException(status_code=404, detail="No user found")
    return user


def _account_wallet_summary(db: Session, account: Account) -> tuple[str | None, bool]:
    from eth_account import Account as EthAccount
    from services.hyperliquid_environment import decrypt_private_key

    wallet_address = None
    has_mainnet_wallet = False
    mainnet_wallet = (
        db.query(HyperliquidWallet)
        .filter(HyperliquidWallet.account_id == account.id, HyperliquidWallet.environment == "mainnet")
        .first()
    )
    encrypted_key = mainnet_wallet.private_key_encrypted if mainnet_wallet else None
    if not encrypted_key:
        encrypted_key = getattr(account, "hyperliquid_mainnet_private_key", None)
    if not encrypted_key:
        return wallet_address, has_mainnet_wallet

    has_mainnet_wallet = True
    try:
        decrypted_key = decrypt_private_key(encrypted_key)
        if decrypted_key:
            if not decrypted_key.startswith("0x"):
                decrypted_key = "0x" + decrypted_key
            wallet_address = EthAccount.from_key(decrypted_key).address.lower()
    except Exception as exc:
        logger.warning("Failed to derive wallet address for account %s: %s", account.id, exc)
    return wallet_address, has_mainnet_wallet


def _account_balance(db: Session, account: Account) -> tuple[float, float]:
    current_cash = float(account.current_cash)
    frozen_cash = float(account.frozen_cash)
    environment = getattr(account, "hyperliquid_environment", None)
    if environment not in {"testnet", "mainnet"}:
        return current_cash, frozen_cash
    try:
        cached_entry = get_cached_account_state(account.id, environment)
        if cached_entry:
            account_state = cached_entry["data"]
        else:
            from services.hyperliquid_environment import get_hyperliquid_client

            account_state = get_hyperliquid_client(db, account.id).get_account_state(db)
        return (
            float(account_state.get("available_balance", current_cash)),
            float(account_state.get("used_margin", frozen_cash)),
        )
    except Exception:
        return current_cash, frozen_cash


def _serialize_for_list(db: Session, account: Account) -> dict[str, Any]:
    user = db.query(User).filter(User.id == account.user_id).first()
    current_cash, frozen_cash = _account_balance(db, account)
    wallet_address, has_mainnet_wallet = _account_wallet_summary(db, account)
    return serialize_account(
        account,
        user,
        current_cash=current_cash,
        frozen_cash=frozen_cash,
        wallet_address=wallet_address,
        has_mainnet_wallet=has_mainnet_wallet,
    )


@router.get("/list")
def list_all_accounts(include_hidden: bool = False, db: Session = Depends(get_db)):
    start_threads = get_current_thread_count()
    start_time = time.monotonic()
    try:
        query = db.query(Account).filter(Account.is_active == "true", Account.is_deleted != True)
        if not include_hidden:
            query = query.filter(Account.show_on_dashboard == True)
        return [_serialize_for_list(db, account) for account in query.all()]
    except Exception as exc:
        logger.error("Failed to list accounts: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list accounts: {exc}") from exc
    finally:
        log_hot_path_delta(
            logger,
            "account:list",
            "/api/account/list",
            start_threads,
            start_time,
            include_hidden=include_hidden,
        )


@router.get("/{account_id}/overview")
def get_specific_account_overview(account_id: int, db: Session = Depends(get_db)):
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.is_active == "true", Account.is_deleted != True)
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    from database.models import Order
    from services.asset_calculator import calc_positions_value

    positions_value = float(calc_positions_value(db, account.id) or 0.0)
    positions_count = db.query(Position).filter(Position.account_id == account.id, Position.quantity > 0).count()
    pending_orders = db.query(Order).filter(Order.account_id == account.id, Order.status == "PENDING").count()
    return {
        "account": {
            "id": account.id,
            "name": account.name,
            "account_type": account.account_type,
            "current_cash": float(account.current_cash),
            "frozen_cash": float(account.frozen_cash),
        },
        "total_assets": positions_value + float(account.current_cash),
        "positions_value": positions_value,
        "positions_count": positions_count,
        "pending_orders": pending_orders,
    }


@router.get("/overview")
def get_account_overview(db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.is_active == "true", Account.is_deleted != True).first()
    if not account:
        raise HTTPException(status_code=404, detail="No active account found")

    from database.models import Order
    from services.asset_calculator import calc_positions_value

    positions_value = float(calc_positions_value(db, account.id) or 0.0)
    positions_count = db.query(Position).filter(Position.account_id == account.id, Position.quantity > 0).count()
    pending_orders = db.query(Order).filter(Order.account_id == account.id, Order.status == "PENDING").count()
    return {
        "account": {
            "id": account.id,
            "name": account.name,
            "account_type": account.account_type,
            "current_cash": float(account.current_cash),
            "frozen_cash": float(account.frozen_cash),
        },
        "portfolio": {
            "total_assets": positions_value + float(account.current_cash),
            "positions_value": positions_value,
            "positions_count": positions_count,
            "pending_orders": pending_orders,
        },
    }


@router.post("/")
def create_new_account(payload: dict, db: Session = Depends(get_db)):
    try:
        user = _get_default_user(db)
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Account name is required")

        initial_capital = float(payload.get("initial_capital", 10000.0))
        new_account = Account(
            user_id=user.id,
            version="v1",
            name=name,
            account_type=payload.get("account_type", "AI"),
            model=payload.get("model", "gpt-4-turbo"),
            base_url=payload.get("base_url", "https://api.openai.com/v1"),
            api_key=payload.get("api_key", ""),
            initial_capital=initial_capital,
            current_cash=initial_capital,
            frozen_cash=0.0,
            is_active="true",
            auto_trading_enabled="true" if _normalize_bool(payload.get("auto_trading_enabled")) else "false",
            avatar_preset_id=random.randint(1, 12),
        )
        db.add(new_account)
        db.commit()
        db.refresh(new_account)

        snapshot = AccountAssetSnapshot(
            account_id=new_account.id,
            total_assets=Decimal(str(new_account.initial_capital)),
            cash=Decimal(str(new_account.current_cash)),
            positions_value=Decimal("0"),
            event_time=datetime.now(timezone.utc),
            trigger_symbol=None,
            trigger_market="CRYPTO",
        )
        db.add(snapshot)
        db.commit()
        invalidate_asset_curve_cache()
        threading.Thread(target=_reset_auto_trading_job_async, args=("account creation",), daemon=True).start()
        return serialize_account(new_account, user)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Failed to create account: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create account: {exc}") from exc


@router.put("/{account_id}")
def update_account_settings(account_id: int, payload: dict, db: Session = Depends(get_db)):
    try:
        safe_payload = {k: v for k, v in payload.items() if k != "api_key"}
        logger.info("Updating account %s with payload keys: %s", account_id, sorted(safe_payload.keys()))
        account = (
            db.query(Account)
            .filter(Account.id == account_id, Account.is_active == "true", Account.is_deleted != True)
            .first()
        )
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        if "name" in payload:
            name = str(payload.get("name") or "").strip()
            if not name:
                raise HTTPException(status_code=400, detail="Account name cannot be empty")
            account.name = name
        if "model" in payload:
            account.model = payload.get("model") or None
        if "base_url" in payload:
            account.base_url = payload.get("base_url")
        if "api_key" in payload and not is_public_api_key_mask(payload.get("api_key")):
            account.api_key = payload.get("api_key") or ""
        if "auto_trading_enabled" in payload:
            account.auto_trading_enabled = "true" if _normalize_bool(payload.get("auto_trading_enabled")) else "false"

        db.commit()
        db.refresh(account)
        threading.Thread(target=_reset_auto_trading_job_async, args=("account update",), daemon=True).start()
        user = db.query(User).filter(User.id == account.user_id).first()
        return serialize_account(account, user)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Failed to update account: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update account: {exc}") from exc


@router.delete("/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db)):
    result = delete_trader(db, account_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Trader not found"))
    return result
