"""
Account and Asset Curve API Routes (Cleaned)
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import logging
import time

from database.connection import SessionLocal
from database.models import Account, Position, Trade, CryptoPrice, AccountAssetSnapshot, HyperliquidWallet, AccountPromptBinding
from services.asset_curve_calculator import invalidate_asset_curve_cache
from services.ai_decision_service import (
    build_chat_completion_endpoints,
    build_llm_headers,
    detect_api_format,
    is_new_openai_model,
    is_reasoning_model,
    _extract_text_from_message,
)
from schemas.account import StrategyConfig, StrategyConfigUpdate
from repositories.strategy_repo import get_strategy_by_account, upsert_strategy
from services.trading_strategy import hyper_strategy_manager
from services.hyperliquid_cache import get_cached_account_state
from services.entity_deletion_service import delete_trader
from utils.runtime_diagnostics import get_current_thread_count, log_hot_path_delta
from api.account_asset_routes import router as account_asset_router, get_asset_curve, get_asset_curve_by_timeframe
from api.account_llm_routes import router as account_llm_router, test_llm_connection
from api.account_trade_routes import router as account_trade_router, trigger_ai_trade
from api.account_management_routes import router as account_management_router
from api.account_builder_routes import (
    router as account_builder_router,
    approve_builder_fee,
    check_builder_authorization,
    check_mainnet_accounts,
    disable_trading,
    update_dashboard_visibility,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/account", tags=["account"])
router.include_router(account_asset_router)
router.include_router(account_llm_router)
router.include_router(account_trade_router)
router.include_router(account_builder_router)
router.include_router(account_management_router)
DEFAULT_STRATEGY_TRIGGER_INTERVAL_SECONDS = 180


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _normalize_bool(value, default=True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "on"}
    return bool(value)


def _serialize_strategy(account: Account, strategy, db: Session = None) -> StrategyConfig:
    """Convert database strategy config to API schema."""
    from repositories.strategy_repo import parse_signal_pool_ids

    last_trigger = strategy.last_trigger_at
    if last_trigger:
        if last_trigger.tzinfo is None:
            last_iso = last_trigger.replace(tzinfo=timezone.utc).isoformat()
        else:
            last_iso = last_trigger.astimezone(timezone.utc).isoformat()
    else:
        last_iso = None

    # Get signal pool IDs (new format with fallback)
    pool_ids = parse_signal_pool_ids(strategy)

    # Get signal pool names if bound
    signal_pool_name = None  # Deprecated: for backward compatibility
    signal_pool_names = []
    if pool_ids and db:
        from sqlalchemy import text
        result = db.execute(
            text("SELECT id, pool_name FROM signal_pools WHERE id = ANY(:ids) AND (is_deleted IS NULL OR is_deleted = false)"),
            {"ids": pool_ids}
        ).fetchall()
        pool_name_map = {row[0]: row[1] for row in result}
        signal_pool_names = [pool_name_map.get(pid) for pid in pool_ids if pool_name_map.get(pid)]
        # Backward compatibility: use first pool name
        signal_pool_name = signal_pool_names[0] if signal_pool_names else None

    # Check if prompt binding exists when triggers are enabled
    warning = None
    has_trigger_enabled = strategy.scheduled_trigger_enabled or pool_ids
    if has_trigger_enabled and db:
        prompt_binding = db.query(AccountPromptBinding).filter(
            AccountPromptBinding.account_id == account.id,
            AccountPromptBinding.is_deleted != True
        ).first()
        if not prompt_binding:
            warning = "No prompt template bound. Automatic triggers will not execute until a prompt is configured."

    return StrategyConfig(
        trigger_mode="unified",
        interval_seconds=strategy.trigger_interval or DEFAULT_STRATEGY_TRIGGER_INTERVAL_SECONDS,
        tick_batch_size=1,
        enabled=(strategy.enabled == "true" and account.auto_trading_enabled == "true"),
        scheduled_trigger_enabled=bool(strategy.scheduled_trigger_enabled),
        exchange=getattr(strategy, 'exchange', None) or "hyperliquid",
        last_trigger_at=last_iso,
        price_threshold=strategy.price_threshold or 1.0,
        signal_pool_id=pool_ids[0] if pool_ids else None,  # Deprecated
        signal_pool_ids=pool_ids if pool_ids else None,
        signal_pool_name=signal_pool_name,  # Deprecated
        signal_pool_names=signal_pool_names if signal_pool_names else None,
        warning=warning,
    )


@router.get("/{account_id}/strategy", response_model=StrategyConfig)
def get_account_strategy(account_id: int, db: Session = Depends(get_db)):
    """Fetch AI trading strategy configuration for an account."""
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.is_active == "true", Account.is_deleted != True)
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    strategy = get_strategy_by_account(db, account_id)
    if not strategy:
        # Check if account has a Binance wallet to determine default exchange
        from database.models import BinanceWallet
        has_binance = db.query(BinanceWallet).filter(
            BinanceWallet.account_id == account_id,
            BinanceWallet.is_active == "true"
        ).first()
        default_exchange = "binance" if has_binance else "hyperliquid"
        strategy = upsert_strategy(
            db,
            account_id=account_id,
            price_threshold=1.0,
            trigger_interval=DEFAULT_STRATEGY_TRIGGER_INTERVAL_SECONDS,
            enabled=(account.auto_trading_enabled == "true"),
            scheduled_trigger_enabled=False,
            exchange=default_exchange,
        )
        # Reload strategies after creation
        hyper_strategy_manager._load_strategies()

    return _serialize_strategy(account, strategy, db)


@router.put("/{account_id}/strategy", response_model=StrategyConfig)
def update_account_strategy(
    account_id: int,
    payload: StrategyConfigUpdate,
    db: Session = Depends(get_db),
):
    """Update AI trading strategy configuration for an account."""
    print(f"Backend received payload for account {account_id}: {payload}")
    account = (
        db.query(Account)
        .filter(Account.id == account_id, Account.is_active == "true", Account.is_deleted != True)
        .first()
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Validate price threshold
    if hasattr(payload, 'price_threshold') and payload.price_threshold is not None:
        if payload.price_threshold <= 0 or payload.price_threshold > 10:
            raise HTTPException(
                status_code=400,
                detail="price_threshold must be between 0.1 and 10.0",
            )
        price_threshold = payload.price_threshold
    else:
        price_threshold = 1.0

    # Validate trigger interval
    if hasattr(payload, 'interval_seconds') and payload.interval_seconds is not None:
        if payload.interval_seconds < 30:
            raise HTTPException(
                status_code=400,
                detail="trigger_interval must be >= 30 seconds",
            )
        trigger_interval = payload.interval_seconds
    else:
        trigger_interval = DEFAULT_STRATEGY_TRIGGER_INTERVAL_SECONDS

    strategy = upsert_strategy(
        db,
        account_id=account_id,
        price_threshold=price_threshold,
        trigger_interval=trigger_interval,
        enabled=payload.enabled,
        scheduled_trigger_enabled=payload.scheduled_trigger_enabled,
        signal_pool_id=payload.signal_pool_id,  # Deprecated: for backward compatibility
        signal_pool_ids=payload.signal_pool_ids,  # New: list of pool IDs
        exchange=payload.exchange,
    )

    # Reload strategies after update
    hyper_strategy_manager._load_strategies()
    return _serialize_strategy(account, strategy, db)
