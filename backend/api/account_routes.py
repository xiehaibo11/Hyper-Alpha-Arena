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


@router.get("/list")
def list_all_accounts(include_hidden: bool = False, db: Session = Depends(get_db)):
    """Get all active accounts (for paper trading demo)

    Args:
        include_hidden: If True, include accounts with show_on_dashboard=False.
                       Default False (only show visible accounts for Dashboard).
    """
    start_threads = get_current_thread_count()
    start_time = time.monotonic()
    try:
        from database.models import User
        from eth_account import Account as EthAccount
        from services.hyperliquid_environment import decrypt_private_key

        query = db.query(Account).filter(Account.is_active == "true", Account.is_deleted != True)
        if not include_hidden:
            query = query.filter(Account.show_on_dashboard == True)
        accounts = query.all()

        result = []
        for account in accounts:
            user = db.query(User).filter(User.id == account.user_id).first()

            # Check if this is a Hyperliquid account
            hyperliquid_environment = getattr(account, "hyperliquid_environment", None)

            current_cash = float(account.current_cash)
            frozen_cash = float(account.frozen_cash)

            # For Hyperliquid accounts, fetch real-time balance
            if hyperliquid_environment in ["testnet", "mainnet"]:
                try:
                    cached_entry = get_cached_account_state(account.id, hyperliquid_environment)
                    if cached_entry:
                        account_state = cached_entry["data"]
                    else:
                        from services.hyperliquid_environment import get_hyperliquid_client

                        client = get_hyperliquid_client(db, account.id)
                        account_state = client.get_account_state(db)

                    current_cash = float(account_state.get('available_balance', current_cash))
                    frozen_cash = float(account_state.get('used_margin', frozen_cash))
                    logger.debug(
                        f"Account {account.name}: Using cached Hyperliquid balance data "
                        f"(available=${current_cash:.2f}, used_margin=${frozen_cash:.2f})"
                    )
                except Exception:
                    pass  # No wallet configured or fetch failed — use database values

            # Derive wallet_address for mainnet accounts
            # Check both old architecture (accounts table) and new architecture (hyperliquid_wallets table)
            wallet_address = None
            has_mainnet_wallet = False

            # First check new multi-wallet architecture (hyperliquid_wallets table)
            mainnet_wallet = db.query(HyperliquidWallet).filter(
                HyperliquidWallet.account_id == account.id,
                HyperliquidWallet.environment == "mainnet"
            ).first()

            if mainnet_wallet and mainnet_wallet.private_key_encrypted:
                has_mainnet_wallet = True
                try:
                    decrypted_key = decrypt_private_key(mainnet_wallet.private_key_encrypted)
                    if decrypted_key:
                        if not decrypted_key.startswith('0x'):
                            decrypted_key = '0x' + decrypted_key
                        eth_account = EthAccount.from_key(decrypted_key)
                        wallet_address = eth_account.address.lower()
                except Exception as wallet_err:
                    logger.warning(
                        f"Failed to derive wallet address from wallets table for account {account.id}: {wallet_err}"
                    )

            # Fallback to old architecture (accounts table field)
            if not has_mainnet_wallet:
                mainnet_private_key = getattr(account, "hyperliquid_mainnet_private_key", None)
                if mainnet_private_key:
                    has_mainnet_wallet = True
                    try:
                        decrypted_key = decrypt_private_key(mainnet_private_key)
                        if decrypted_key:
                            if not decrypted_key.startswith('0x'):
                                decrypted_key = '0x' + decrypted_key
                            eth_account = EthAccount.from_key(decrypted_key)
                            wallet_address = eth_account.address.lower()
                    except Exception as wallet_err:
                        logger.warning(
                            f"Failed to derive wallet address for account {account.id}: {wallet_err}"
                        )

            result.append({
                "id": account.id,
                "user_id": account.user_id,
                "username": user.username if user else "unknown",
                "name": account.name,
                "account_type": account.account_type,
                "initial_capital": float(account.initial_capital),
                "current_cash": current_cash,
                "frozen_cash": frozen_cash,
                "model": account.model,
                "base_url": account.base_url,
                "api_key": account.api_key,
                "is_active": account.is_active == "true",
                "auto_trading_enabled": account.auto_trading_enabled == "true",
                "wallet_address": wallet_address,
                "has_mainnet_wallet": has_mainnet_wallet,
                "show_on_dashboard": account.show_on_dashboard,
                "avatar_preset_id": account.avatar_preset_id
            })

        return result
    except Exception as e:
        logger.error(f"Failed to list accounts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list accounts: {str(e)}")
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
    """Get overview for a specific account"""
    try:
        # Get the specific account
        account = db.query(Account).filter(
            Account.id == account_id,
            Account.is_active == "true",
            Account.is_deleted != True
        ).first()

        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Calculate positions value for this specific account
        from services.asset_calculator import calc_positions_value
        positions_value = float(calc_positions_value(db, account.id) or 0.0)

        # Count positions and pending orders for this account
        positions_count = db.query(Position).filter(
            Position.account_id == account.id,
            Position.quantity > 0
        ).count()

        from database.models import Order
        pending_orders = db.query(Order).filter(
            Order.account_id == account.id,
            Order.status == "PENDING"
        ).count()

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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get account {account_id} overview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get account overview: {str(e)}")


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


@router.get("/overview")
def get_account_overview(db: Session = Depends(get_db)):
    """Get overview for the default account (for paper trading demo)"""
    try:
        # Get the first active account (default account)
        account = db.query(Account).filter(Account.is_active == "true", Account.is_deleted != True).first()

        if not account:
            raise HTTPException(status_code=404, detail="No active account found")

        # Calculate positions value
        from services.asset_calculator import calc_positions_value
        positions_value = float(calc_positions_value(db, account.id) or 0.0)

        # Count positions and pending orders
        positions_count = db.query(Position).filter(
            Position.account_id == account.id,
            Position.quantity > 0
        ).count()

        from database.models import Order
        pending_orders = db.query(Order).filter(
            Order.account_id == account.id,
            Order.status == "PENDING"
        ).count()

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
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get overview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get overview: {str(e)}")


@router.post("/")
def create_new_account(payload: dict, db: Session = Depends(get_db)):
    """Create a new account for the default user (for paper trading demo)"""
    try:
        from database.models import User

        # Get the default user (or first user)
        user = db.query(User).filter(User.username == "default").first()
        if not user:
            user = db.query(User).first()

        if not user:
            raise HTTPException(status_code=404, detail="No user found")

        # Validate required fields
        if "name" not in payload or not payload["name"]:
            raise HTTPException(status_code=400, detail="Account name is required")

        # Create new account
        auto_trading_enabled = _normalize_bool(payload.get("auto_trading_enabled", True))
        auto_trading_value = "true" if auto_trading_enabled else "false"

        import random
        avatar_preset_id = random.randint(1, 12)

        new_account = Account(
            user_id=user.id,
            version="v1",
            name=payload["name"],
            account_type=payload.get("account_type", "AI"),
            model=payload.get("model", "gpt-4-turbo"),
            base_url=payload.get("base_url", "https://api.openai.com/v1"),
            api_key=payload.get("api_key", ""),
            initial_capital=float(payload.get("initial_capital", 10000.0)),
            current_cash=float(payload.get("initial_capital", 10000.0)),
            frozen_cash=0.0,
            is_active="true",
            auto_trading_enabled=auto_trading_value,
            avatar_preset_id=avatar_preset_id
        )

        db.add(new_account)
        db.commit()
        db.refresh(new_account)

        # Record initial snapshot so asset curves start at the configured capital
        try:
            now_utc = datetime.now(timezone.utc)
            initial_total = Decimal(str(new_account.initial_capital))
            snapshot = AccountAssetSnapshot(
                account_id=new_account.id,
                total_assets=initial_total,
                cash=Decimal(str(new_account.current_cash)),
                positions_value=Decimal("0"),
                event_time=now_utc,
                trigger_symbol=None,
                trigger_market="CRYPTO",
            )
            db.add(snapshot)
            db.commit()
            invalidate_asset_curve_cache()
        except Exception as snapshot_err:
            db.rollback()
            logger.warning(
                "Failed to create initial account snapshot for account %s: %s",
                new_account.id,
                snapshot_err,
            )

        # Reset auto trading job after creating new account (async in background to avoid blocking response)
        import threading
        def reset_job_async():
            try:
                from services.scheduler import reset_auto_trading_job
                reset_auto_trading_job()
                logger.info("Auto trading job reset successfully after account creation")
            except Exception as e:
                logger.warning(f"Failed to reset auto trading job: {e}")

        # Run reset in background thread to not block API response
        reset_thread = threading.Thread(target=reset_job_async, daemon=True)
        reset_thread.start()
        logger.info("Auto trading job reset initiated in background")

        return {
            "id": new_account.id,
            "user_id": new_account.user_id,
            "username": user.username,
            "name": new_account.name,
            "account_type": new_account.account_type,
            "initial_capital": float(new_account.initial_capital),
            "current_cash": float(new_account.current_cash),
            "frozen_cash": float(new_account.frozen_cash),
            "model": new_account.model,
            "base_url": new_account.base_url,
            "api_key": new_account.api_key,
            "is_active": new_account.is_active == "true",
            "auto_trading_enabled": new_account.auto_trading_enabled == "true",
            "avatar_preset_id": new_account.avatar_preset_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create account: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create account: {str(e)}")


@router.put("/{account_id}")
def update_account_settings(account_id: int, payload: dict, db: Session = Depends(get_db)):
    """Update account settings (for paper trading demo)"""
    try:
        logger.info(f"Updating account {account_id} with payload: {payload}")

        account = db.query(Account).filter(
            Account.id == account_id,
            Account.is_active == "true",
            Account.is_deleted != True
        ).first()

        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Update fields if provided (allow empty strings for api_key and base_url)
        if "name" in payload:
            if payload["name"]:
                account.name = payload["name"]
                logger.info(f"Updated name to: {payload['name']}")
            else:
                raise HTTPException(status_code=400, detail="Account name cannot be empty")

        if "model" in payload:
            account.model = payload["model"] if payload["model"] else None
            logger.info(f"Updated model to: {account.model}")

        if "base_url" in payload:
            account.base_url = payload["base_url"]
            logger.info(f"Updated base_url to: {account.base_url}")

        if "api_key" in payload:
            account.api_key = payload["api_key"]
            logger.info(f"Updated api_key (length: {len(payload['api_key']) if payload['api_key'] else 0})")

        if "auto_trading_enabled" in payload:
            auto_trading_enabled = _normalize_bool(payload.get("auto_trading_enabled"))
            account.auto_trading_enabled = "true" if auto_trading_enabled else "false"
            logger.info(f"Updated auto_trading_enabled to: {account.auto_trading_enabled}")

        db.commit()
        db.refresh(account)
        logger.info(f"Account {account_id} updated successfully")

        # Reset auto trading job after account update (async in background to avoid blocking response)
        import threading
        def reset_job_async():
            try:
                from services.scheduler import reset_auto_trading_job
                reset_auto_trading_job()
                logger.info("Auto trading job reset successfully after account update")
            except Exception as e:
                logger.warning(f"Failed to reset auto trading job: {e}")

        # Run reset in background thread to not block API response
        reset_thread = threading.Thread(target=reset_job_async, daemon=True)
        reset_thread.start()
        logger.info("Auto trading job reset initiated in background")

        from database.models import User
        user = db.query(User).filter(User.id == account.user_id).first()

        return {
            "id": account.id,
            "user_id": account.user_id,
            "username": user.username if user else "unknown",
            "name": account.name,
            "account_type": account.account_type,
            "initial_capital": float(account.initial_capital),
            "current_cash": float(account.current_cash),
            "frozen_cash": float(account.frozen_cash),
            "model": account.model,
            "base_url": account.base_url,
            "api_key": account.api_key,
            "is_active": account.is_active == "true",
            "auto_trading_enabled": account.auto_trading_enabled == "true"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update account: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update account: {str(e)}")


@router.delete("/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db)):
    """Soft-delete an AI Trader with dependency checking."""
    result = delete_trader(db, account_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Trader not found"))
    return result
