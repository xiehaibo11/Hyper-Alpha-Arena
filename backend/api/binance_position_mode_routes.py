"""Live Binance position-mode compatibility route."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import BinanceWallet
from services.binance_trading_client import BinanceTradingClient
from services.hyperliquid_environment import get_global_trading_mode
from utils.encryption import decrypt_private_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/binance", tags=["binance"])


def _get_client(wallet: BinanceWallet) -> BinanceTradingClient:
    api_key = decrypt_private_key(wallet.api_key_encrypted)
    secret_key = decrypt_private_key(wallet.secret_key_encrypted)
    return BinanceTradingClient(
        api_key=api_key,
        secret_key=secret_key,
        environment=wallet.environment,
    )


@router.get("/accounts/{account_id}/position-mode")
def get_position_mode(
    account_id: int,
    environment: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Return Binance position mode; both One-way and Hedge are supported."""
    if not environment:
        environment = get_global_trading_mode(db)

    wallet = db.query(BinanceWallet).filter(
        BinanceWallet.account_id == account_id,
        BinanceWallet.environment == environment,
        BinanceWallet.is_active == "true",
    ).first()
    if not wallet:
        raise HTTPException(status_code=404, detail=f"No {environment} wallet configured")

    try:
        position_mode = _get_client(wallet).get_position_mode()
        is_hedge = bool(position_mode.get("dual_side_position"))
        return {
            **position_mode,
            "supported": True,
            "message": (
                "Binance Hedge Mode is active. Orders will be sent with LONG/SHORT positionSide parameters."
                if is_hedge
                else "Binance One-way Position Mode is active."
            ),
        }
    except Exception as exc:
        logger.error("Failed to get Binance position mode: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
