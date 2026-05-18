"""Hyperliquid wallet selection and trading-mode API routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.connection import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


# ========== Global Trading Mode Management ==========

class TradingModeRequest(BaseModel):
    """Request model for trading mode update"""
    mode: str = Field(..., pattern="^(testnet|mainnet)$", description="Trading environment mode")


@router.get("/trading-mode")
def get_trading_mode(db: Session = Depends(get_db)):
    """
    Get global Hyperliquid trading mode

    Returns the current trading environment (testnet or mainnet) that all AI Traders use.
    """
    from services.hyperliquid_environment import get_global_trading_mode

    try:
        mode = get_global_trading_mode(db)

        return {
            'success': True,
            'mode': mode,
            'description': 'Testnet (paper trading)' if mode == 'testnet' else 'Mainnet (real funds)'
        }

    except Exception as e:
        logger.error(f"Failed to get trading mode: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get trading mode: {str(e)}")


@router.post("/trading-mode")
def set_trading_mode(
    request: TradingModeRequest,
    db: Session = Depends(get_db)
):
    """
    Set global Hyperliquid trading mode

    WARNING: Switching to mainnet will use real funds for all AI Traders.
    This change affects all active AI Traders immediately.
    """
    from database.models import SystemConfig

    try:
        # Check if config exists
        config = db.query(SystemConfig).filter(
            SystemConfig.key == "hyperliquid_trading_mode"
        ).first()

        old_mode = config.value if config else "testnet"
        new_mode = request.mode

        if old_mode == new_mode:
            return {
                'success': True,
                'mode': new_mode,
                'changed': False,
                'message': f'Trading mode already set to {new_mode}'
            }

        # Update or create config
        if config:
            config.value = new_mode
        else:
            config = SystemConfig(
                key="hyperliquid_trading_mode",
                value=new_mode,
                description="Global Hyperliquid trading environment: 'testnet' or 'mainnet'"
            )
            db.add(config)

        db.commit()

        logger.warning(f"GLOBAL TRADING MODE CHANGED: {old_mode} -> {new_mode}")

        # Clear all Hyperliquid caches when environment changes
        # This ensures fresh data is fetched from the new environment
        from services.hyperliquid_cache import clear_all_caches
        clear_all_caches()
        logger.info("Cleared all Hyperliquid caches after trading mode switch")

        return {
            'success': True,
            'mode': new_mode,
            'changed': True,
            'oldMode': old_mode,
            'message': f'Trading mode switched from {old_mode} to {new_mode}'
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to set trading mode: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to set trading mode: {str(e)}")




@router.get("/wallets/all")
def get_all_wallets(db: Session = Depends(get_db)):
    """
    Get all Hyperliquid wallets (both testnet and mainnet) across all AI Trader accounts

    Used by the Trade page wallet selector to display all available wallets
    regardless of the current global trading mode.

    Returns:
        List of wallet objects with account information, sorted by account name and environment
    """
    from database.models import HyperliquidWallet, Account

    try:
        wallets = db.query(HyperliquidWallet, Account).join(
            Account, HyperliquidWallet.account_id == Account.id
        ).filter(
            Account.is_active == "true"
        ).order_by(
            Account.name.asc(),
            HyperliquidWallet.environment.asc()
        ).all()

        result = []
        for w, a in wallets:
            key_type = getattr(w, 'key_type', 'private_key') or 'private_key'
            # For agent_key mode, display master wallet address (the one users recognize)
            display_address = w.master_wallet_address if key_type == "agent_key" and w.master_wallet_address else w.wallet_address
            result.append({
                "wallet_id": w.id,
                "account_id": w.account_id,
                "account_name": a.name,
                "model": a.model,
                "wallet_address": display_address,
                "environment": w.environment,
                "is_active": w.is_active == "true",
                "max_leverage": w.max_leverage,
                "default_leverage": w.default_leverage
            })
        return result

    except Exception as e:
        logger.error(f"Failed to get all wallets: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get wallets: {str(e)}")
