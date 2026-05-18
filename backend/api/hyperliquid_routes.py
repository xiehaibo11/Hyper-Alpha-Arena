"""
Hyperliquid Management API Routes

Provides endpoints for:
- Account setup and configuration
- Environment switching (testnet/mainnet)
- Balance and position queries
- Manual order placement (for testing)
- Connection testing
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, case
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List
import logging
import time

from database.connection import get_db
from database.models import HyperliquidExchangeAction
from services.hyperliquid_environment import (
    setup_hyperliquid_account,
    get_hyperliquid_client,
    switch_hyperliquid_environment,
    get_account_hyperliquid_config,
    disable_hyperliquid_trading,
    enable_hyperliquid_trading,
)
from services.hyperliquid_symbol_service import (
    get_available_symbols_info,
    get_selected_symbols,
    update_selected_symbols,
    MAX_WATCHLIST_SYMBOLS,
)
from services.hyperliquid_cache import (
    get_cached_account_state,
    get_cached_positions,
)
from utils.runtime_diagnostics import get_current_thread_count, log_hot_path_delta
from api.hyperliquid_wallet_routes import router as hyperliquid_wallet_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hyperliquid", tags=["hyperliquid"])
router.include_router(hyperliquid_wallet_router)


def _ts_to_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


# Request/Response Models
class HyperliquidSetupRequest(BaseModel):
    """Request model for Hyperliquid account setup"""
    environment: str = Field(..., pattern="^(testnet|mainnet)$", description="Trading environment")
    private_key: str = Field(..., min_length=10, description="Hyperliquid private key (will be encrypted)", alias="privateKey")
    max_leverage: int = Field(3, ge=1, le=50, description="Maximum allowed leverage", alias="maxLeverage")
    default_leverage: int = Field(1, ge=1, le=50, description="Default leverage for orders", alias="defaultLeverage")

    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "environment": "testnet",
                "privateKey": "0x1234567890abcdef...",
                "maxLeverage": 3,
                "defaultLeverage": 1
            }
        }


class EnvironmentSwitchRequest(BaseModel):
    """Request model for environment switching"""
    target_environment: str = Field(..., pattern="^(testnet|mainnet)$")
    confirm_switch: bool = Field(False, description="Must be True to proceed (safety check)")

    class Config:
        json_schema_extra = {
            "example": {
                "target_environment": "mainnet",
                "confirm_switch": True
            }
        }


class ManualOrderRequest(BaseModel):
    """Request model for manual order placement"""
    symbol: str = Field(..., description="Asset symbol (e.g., 'BTC')")
    is_buy: bool = Field(..., description="True for long, False for short")
    size: float = Field(..., gt=0, description="Order size")
    price: float = Field(..., gt=0, description="Limit price for the order")
    time_in_force: str = Field("Ioc", pattern="^(Ioc|Gtc|Alo)$", description="Time in force: Ioc (market-like), Gtc (limit order), Alo (maker only)")
    leverage: int = Field(1, ge=1, le=50, description="Position leverage")
    reduce_only: bool = Field(False, description="Only close existing positions")
    take_profit_price: Optional[float] = Field(None, gt=0, description="Take profit trigger price")
    stop_loss_price: Optional[float] = Field(None, gt=0, description="Stop loss trigger price")
    environment: Optional[str] = Field(None, description="Environment override ('testnet' or 'mainnet')")

    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "BTC",
                "is_buy": True,
                "size": 0.01,
                "price": 50000.0,
                "time_in_force": "Ioc",
                "leverage": 2,
                "reduce_only": False,
                "take_profit_price": 55000.0,
                "stop_loss_price": 47500.0
            }
        }


class HyperliquidSymbolSelectionRequest(BaseModel):
    symbols: List[str] = Field(default_factory=list, description="Symbols to monitor")

    class Config:
        json_schema_extra = {
            "example": {
                "symbols": ["BTC", "ETH", "SOL"]
            }
        }


# API Endpoints

@router.post("/accounts/{account_id}/setup")
def setup_account(
    account_id: int,
    request: HyperliquidSetupRequest,
    db: Session = Depends(get_db)
):
    """
    Setup Hyperliquid trading for an account

    This endpoint:
    - Encrypts and stores the private key
    - Sets the trading environment (testnet or mainnet)
    - Configures leverage limits
    - Enables Hyperliquid trading

    **Note**: Private keys are encrypted using Fernet before storage.
    Ensure HYPERLIQUID_ENCRYPTION_KEY is set in environment.
    """
    try:
        result = setup_hyperliquid_account(
            db=db,
            account_id=account_id,
            environment=request.environment,
            private_key=request.private_key,
            max_leverage=request.max_leverage,
            default_leverage=request.default_leverage
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Setup failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Setup failed: {str(e)}")


@router.post("/accounts/{account_id}/switch-environment")
def switch_environment(
    account_id: int,
    request: EnvironmentSwitchRequest,
    db: Session = Depends(get_db)
):
    """
    Switch account between testnet and mainnet

    **Safety measures**:
    - Requires explicit confirmation (confirm_switch=True)
    - Blocks switch if open positions exist
    - Verifies target environment has credentials configured

    **Warning**: This is a critical operation. Ensure you understand
    the implications before switching environments.
    """
    try:
        result = switch_hyperliquid_environment(
            db=db,
            account_id=account_id,
            target_environment=request.target_environment,
            confirm_switch=request.confirm_switch
        )
        return result
    except ValueError as e:
        if "No wallet configured" in str(e):
            return {
                'account_id': account_id,
                'environment': environment,
                'positions': [],
                'count': 0,
                'source': 'not_configured',
                'cached_at': datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Environment switch failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Switch failed: {str(e)}")


@router.get("/accounts/{account_id}/config")
def get_config(
    account_id: int,
    db: Session = Depends(get_db)
):
    """
    Get Hyperliquid configuration for an account

    Returns:
    - Enabled status
    - Current environment
    - Leverage settings
    - Whether testnet/mainnet credentials are configured
    """
    try:
        config = get_account_hyperliquid_config(db, account_id)
        return config
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/accounts/{account_id}/balance")
def get_balance(
    account_id: int,
    force_refresh: bool = False,
    environment: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Get Hyperliquid account balance.

    Unless force_refresh is True, this endpoint returns the most recent cached
    snapshot captured by the backend. This avoids excessive direct calls to
    Hyperliquid when rendering dashboards.

    Args:
        account_id: Target account ID
        force_refresh: If True, fetch directly from Hyperliquid instead of cache
        environment: Optional environment override ("testnet" or "mainnet")
                    If not specified, uses global trading mode
    """
    start_threads = get_current_thread_count()
    start_time = time.monotonic()
    try:
        # Determine environment to use
        if environment is None:
            from services.hyperliquid_environment import get_global_trading_mode
            environment = get_global_trading_mode(db)

        if not force_refresh:
            cached_entry = get_cached_account_state(account_id, environment)
            if cached_entry:
                payload = dict(cached_entry["data"])
                payload["source"] = "cache"
                payload["cached_at"] = _ts_to_iso(cached_entry["timestamp"])
                return payload

        client = get_hyperliquid_client(db, account_id, override_environment=environment)
        balance = client.get_account_state(db)
        balance["source"] = "live"
        ts_ms = balance.get("timestamp")
        if isinstance(ts_ms, (int, float)):
            balance["cached_at"] = _ts_to_iso(ts_ms / 1000.0)
        else:
            balance["cached_at"] = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
        return balance
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get balance: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Balance query failed: {str(e)}")
    finally:
        log_hot_path_delta(
            logger,
            "hyperliquid:balance",
            "/api/hyperliquid/accounts/{account_id}/balance",
            start_threads,
            start_time,
            account_id=account_id,
            environment=environment,
            force_refresh=force_refresh,
        )


@router.get("/accounts/{account_id}/positions")
def get_positions(
    account_id: int,
    force_refresh: bool = False,
    environment: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Get all open positions for an account.

    By default, this uses the latest cached snapshot taken by the backend.
    Set force_refresh=true to fetch directly from Hyperliquid.

    Args:
        account_id: Target account ID
        force_refresh: If True, fetch directly from Hyperliquid instead of cache
        environment: Optional environment override ("testnet" or "mainnet")
                    If not specified, uses global trading mode
    """
    try:
        # Determine environment to use
        if environment is None:
            from services.hyperliquid_environment import get_global_trading_mode
            environment = get_global_trading_mode(db)

        if not force_refresh:
            cached_entry = get_cached_positions(account_id, environment)
            if cached_entry:
                return {
                    'account_id': account_id,
                    'environment': environment,
                    'positions': cached_entry["data"],
                    'count': len(cached_entry["data"]),
                    'source': 'cache',
                    'cached_at': _ts_to_iso(cached_entry["timestamp"]),
                }

        client = get_hyperliquid_client(db, account_id, override_environment=environment)
        positions = client.get_positions(db)
        return {
            'account_id': account_id,
            'environment': client.environment,
            'positions': positions,
            'count': len(positions),
            'source': 'live',
            'cached_at': datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    except ValueError as e:
        if "No wallet configured" in str(e):
            return {
                'account_id': account_id,
                'environment': environment,
                'positions': [],
                'count': 0,
                'source': 'not_configured',
                'cached_at': datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get positions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Positions query failed: {str(e)}")


@router.post("/accounts/{account_id}/orders/manual")
def place_manual_order(
    account_id: int,
    request: ManualOrderRequest,
    db: Session = Depends(get_db)
):
    """
    Manually place a Hyperliquid order

    **Use cases**:
    - Testing order placement
    - Manual intervention during trading
    - Emergency position closing

    **Warning**: This bypasses AI decision-making. Use with caution.

    Args:
        account_id: Target account ID
        request: Order request with optional environment override
    """
    try:
        client = get_hyperliquid_client(db, account_id, override_environment=request.environment)

        # Validate leverage against wallet limits (uses unified leverage getter)
        from services.hyperliquid_environment import get_leverage_settings, get_global_trading_mode

        # Determine actual environment being used
        actual_environment = request.environment if request.environment else get_global_trading_mode(db)

        # Get leverage settings from wallet (or Account table fallback)
        leverage_settings = get_leverage_settings(db, account_id, actual_environment)
        max_leverage = leverage_settings["max_leverage"]

        if request.leverage > max_leverage:
            raise HTTPException(
                status_code=400,
                detail=f"Leverage {request.leverage}x exceeds account maximum {max_leverage}x for {actual_environment} environment"
            )

        # Place order using native Hyperliquid API with TP/SL support
        result = client.place_order_with_tpsl(
            db=db,
            symbol=request.symbol,
            is_buy=request.is_buy,
            size=request.size,
            price=request.price,
            leverage=request.leverage,
            time_in_force=request.time_in_force,
            reduce_only=request.reduce_only,
            take_profit_price=request.take_profit_price,
            stop_loss_price=request.stop_loss_price
        )

        return {
            'account_id': account_id,
            'environment': client.environment,
            'order_result': result
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Manual order failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Order placement failed: {str(e)}")


@router.post("/accounts/{account_id}/disable")
def disable_trading(
    account_id: int,
    db: Session = Depends(get_db)
):
    """
    Disable Hyperliquid trading for an account

    **Note**: This does NOT delete stored credentials, only disables trading.
    Credentials remain encrypted in database for potential re-enable.
    """
    try:
        result = disable_hyperliquid_trading(db, account_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to disable trading: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/accounts/{account_id}/enable")
def enable_trading(
    account_id: int,
    db: Session = Depends(get_db)
):
    """
    Re-enable Hyperliquid trading for an account

    Requires account to have environment and credentials already configured.
    """
    try:
        result = enable_hyperliquid_trading(db, account_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to enable trading: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/accounts/{account_id}/test-connection")
def test_connection(
    account_id: int,
    db: Session = Depends(get_db)
):
    """
    Test Hyperliquid API connection

    This endpoint:
    - Validates account configuration
    - Tests API authentication
    - Fetches basic account info
    - Returns connection status

    Use this to verify setup before enabling automated trading.
    """
    try:
        client = get_hyperliquid_client(db, account_id)
        result = client.test_connection(db)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Connection test failed: {e}", exc_info=True)
        return {
            'connected': False,
            'error': str(e),
            'account_id': account_id
        }


@router.get("/accounts/{account_id}/snapshots")
def get_account_snapshots(
    account_id: int,
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of snapshots to return"),
    db: Session = Depends(get_db)
):
    """
    Get historical account snapshots for Hyperliquid account

    Returns time-series data of account equity, available balance, and used margin.
    Used for asset curve visualization in the frontend.

    Query Parameters:
    - limit: Maximum number of snapshots (default: 100, max: 1000)

    Returns:
    - Array of snapshot objects with timestamp, equity, balance, and margin data
    """
    from database.models import Account
    from database.snapshot_connection import SnapshotSessionLocal
    from database.snapshot_models import HyperliquidAccountSnapshot

    # Verify account exists and has Hyperliquid environment configured
    account = db.query(Account).filter(Account.id == account_id, Account.is_deleted != True).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if not account.hyperliquid_environment:
        raise HTTPException(
            status_code=400,
            detail="Hyperliquid environment is not configured for this account"
        )

    # Query snapshots from snapshot database
    snapshot_db = SnapshotSessionLocal()
    try:
        snapshots = snapshot_db.query(HyperliquidAccountSnapshot).filter(
            HyperliquidAccountSnapshot.account_id == account_id
        ).order_by(
            HyperliquidAccountSnapshot.created_at.desc()
        ).limit(limit).all()
    finally:
        snapshot_db.close()

    # Convert to response format (reverse to oldest first for charting)
    result = []
    for snapshot in reversed(snapshots):
        result.append({
            'account_id': snapshot.account_id,
            'environment': snapshot.environment,
            'snapshot_time': snapshot.created_at.isoformat(),
            'total_equity': float(snapshot.total_equity),
            'available_balance': float(snapshot.available_balance),
            'used_margin': float(snapshot.used_margin),
            'maintenance_margin': float(snapshot.maintenance_margin),
            'trigger_event': snapshot.trigger_event
        })

    return {
        'account_id': account_id,
        'account_name': account.name,
        'environment': account.hyperliquid_environment,
        'snapshot_count': len(result),
        'snapshots': result
    }


@router.get("/symbols/available")
def list_available_symbols():
    """Return cached Hyperliquid tradable symbols (refreshed periodically)."""
    info = get_available_symbols_info()
    return {
        "symbols": info.get("symbols", []),
        "updated_at": info.get("updated_at"),
        "max_symbols": MAX_WATCHLIST_SYMBOLS,
    }


@router.get("/symbols/watchlist")
def get_symbol_watchlist():
    """Return the currently configured global Hyperliquid watchlist."""
    symbols = get_selected_symbols()
    return {
        "symbols": symbols,
        "max_symbols": MAX_WATCHLIST_SYMBOLS,
    }


@router.put("/symbols/watchlist")
def update_symbol_watchlist(payload: HyperliquidSymbolSelectionRequest):
    """Update global Hyperliquid watchlist (max 10 symbols)."""
    try:
        symbols = update_selected_symbols(payload.symbols)
        logger.info(f"[Hyperliquid] Watchlist updated to: {symbols}")
        return {
            "symbols": symbols,
            "max_symbols": MAX_WATCHLIST_SYMBOLS,
        }
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        logger.error(f"Failed to update Hyperliquid watchlist: {err}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update Hyperliquid watchlist")


@router.get("/actions/summary")
def get_action_summary(
    window_minutes: int = 1440,
    account_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """
    Summarize Hyperliquid exchange actions recorded by the backend.

    Parameters:
    - window_minutes: Lookback window (default 24h)
    - account_id: Optional filter for a single account
    """
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
        query = db.query(
            HyperliquidExchangeAction.action_type.label("action_type"),
            func.count(HyperliquidExchangeAction.id).label("count"),
            func.sum(
                case((HyperliquidExchangeAction.status == "error", 1), else_=0)
            ).label("errors"),
            func.max(HyperliquidExchangeAction.created_at).label("last_ts"),
        ).filter(HyperliquidExchangeAction.created_at >= cutoff)

        if account_id is not None:
            query = query.filter(HyperliquidExchangeAction.account_id == account_id)

        rows = query.group_by(HyperliquidExchangeAction.action_type).all()
        total_actions = sum(row.count for row in rows)
        latest_event = max((row.last_ts for row in rows if row.last_ts), default=None)

        summary = {
            "window_minutes": window_minutes,
            "account_id": account_id,
            "total_actions": total_actions,
            "generated_at": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
            "latest_action_at": latest_event.isoformat().replace("+00:00", "Z") if latest_event else None,
            "by_action": [
                {
                    "action_type": row.action_type,
                    "count": row.count,
                    "errors": int(row.errors or 0),
                    "last_occurrence": row.last_ts.isoformat().replace("+00:00", "Z") if row.last_ts else None,
                }
                for row in rows
            ],
        }
        return summary
    except Exception as err:
        logger.error(f"Failed to summarize Hyperliquid actions: {err}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to summarize Hyperliquid actions")


@router.get("/accounts/{account_id}/rate-limit")
def get_account_rate_limit(
    account_id: int,
    environment: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Get API request rate limit status for Hyperliquid account

    Returns the address-based request quota information including:
    - Cumulative trading volume
    - Requests used vs cap
    - Remaining quota
    - Over-limit status

    This helps users understand if they need to increase trading volume
    to avoid "Too many requests" errors when placing orders.

    Args:
        account_id: Account ID
        environment: Optional environment override ("testnet" or "mainnet")
                    If not specified, uses global trading mode
        db: Database session

    Returns:
        Rate limit status with usage metrics

    Raises:
        HTTPException: If account not found or Hyperliquid not enabled
    """
    try:
        # Determine environment to use
        if environment is None:
            from services.hyperliquid_environment import get_global_trading_mode
            environment = get_global_trading_mode(db)

        # Get Hyperliquid client for this account with environment override
        client = get_hyperliquid_client(db, account_id, override_environment=environment)

        if not client:
            raise HTTPException(
                status_code=400,
                detail="Hyperliquid trading is not enabled for this account"
            )

        # Query rate limit status
        rate_limit = client.get_user_rate_limit(db)

        return {
            'success': True,
            'accountId': account_id,
            'rateLimit': rate_limit
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get rate limit for account {account_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query rate limit: {str(e)}"
        )


@router.get("/accounts/{account_id}/trading-stats")
def get_account_trading_stats(
    account_id: int,
    environment: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Get trading statistics for Hyperliquid account

    Returns win rate, profit factor, and other trading metrics based on
    historical closed trades.

    Args:
        account_id: Account ID
        environment: Optional environment override ("testnet" or "mainnet")
                    If not specified, uses global trading mode
        db: Database session

    Returns:
        Trading statistics including win rate, total trades, PnL metrics

    Raises:
        HTTPException: If account not found or Hyperliquid not enabled
    """
    try:
        # Determine environment to use
        if environment is None:
            from services.hyperliquid_environment import get_global_trading_mode
            environment = get_global_trading_mode(db)

        # Get Hyperliquid client for this account with environment override
        client = get_hyperliquid_client(db, account_id, override_environment=environment)

        if not client:
            raise HTTPException(
                status_code=400,
                detail="Hyperliquid trading is not enabled for this account"
            )

        # Query trading stats
        stats = client.get_trading_stats(db)

        return {
            'success': True,
            'accountId': account_id,
            'environment': environment,
            'stats': stats
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get trading stats for account {account_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query trading stats: {str(e)}"
        )


@router.get("/health")
def health_check():
    """
    Hyperliquid service health check

    Returns service status and configuration info.
    """
    import os
    return {
        'status': 'healthy',
        'service': 'hyperliquid',
        'encryption_configured': bool(os.getenv('HYPERLIQUID_ENCRYPTION_KEY')),
        'endpoints': {
            'setup': '/api/hyperliquid/accounts/{id}/setup',
            'balance': '/api/hyperliquid/accounts/{id}/balance',
            'positions': '/api/hyperliquid/accounts/{id}/positions',
            'snapshots': '/api/hyperliquid/accounts/{id}/snapshots',
            'test': '/api/hyperliquid/accounts/{id}/test-connection',
            'wallet': '/api/hyperliquid/accounts/{id}/wallet'
        }
    }
