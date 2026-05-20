"""Authenticated manual intervention endpoints for live trading."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Account, BinanceWallet
from repositories.user_repo import verify_auth_session
from services.binance_trading_client import BinanceTradingClient
from services.hyperliquid_environment import get_global_trading_mode
from utils.encryption import decrypt_private_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/manual-trading", tags=["manual-trading"])


class ManualClosePositionRequest(BaseModel):
    account_id: int = Field(..., alias="accountId")
    exchange: str = Field("binance", pattern="^(binance)$")
    symbol: str = Field(..., min_length=1, max_length=20)
    position_side: Optional[str] = Field(None, alias="positionSide", pattern="^(LONG|SHORT)$")
    environment: Optional[str] = Field(None, pattern="^(testnet|mainnet)$")
    session_token: Optional[str] = Field(None, alias="sessionToken")

    class Config:
        populate_by_name = True


def _require_user_id(
    db: Session,
    body_token: Optional[str],
    cookie_token: Optional[str],
) -> int:
    token = body_token or cookie_token
    if not token:
        raise HTTPException(status_code=401, detail="Login required")
    user_id = verify_auth_session(db, token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Session expired")
    return user_id


def _get_owned_account(db: Session, account_id: int, user_id: int) -> Account:
    account = db.query(Account).filter(
        Account.id == account_id,
        Account.user_id == user_id,
        Account.account_type == "AI",
        Account.is_deleted != True,
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="AI Trader account not found")
    return account


def _get_binance_client(wallet: BinanceWallet) -> BinanceTradingClient:
    api_key = decrypt_private_key(wallet.api_key_encrypted)
    secret_key = decrypt_private_key(wallet.secret_key_encrypted)
    return BinanceTradingClient(
        api_key=api_key,
        secret_key=secret_key,
        environment=wallet.environment,
    )


@router.post("/close-position")
def close_manual_position(
    request: ManualClosePositionRequest,
    arena_session_token: Optional[str] = Cookie(None, alias="arena_session_token"),
    db: Session = Depends(get_db),
):
    """Close one existing Binance futures position with a reduce-only market order."""
    user_id = _require_user_id(db, request.session_token, arena_session_token)
    account = _get_owned_account(db, request.account_id, user_id)
    environment = request.environment or get_global_trading_mode(db)

    wallet = db.query(BinanceWallet).filter(
        BinanceWallet.account_id == account.id,
        BinanceWallet.environment == environment,
        BinanceWallet.is_active == "true",
    ).first()
    if not wallet:
        raise HTTPException(status_code=404, detail=f"No active Binance {environment} wallet configured")

    symbol = request.symbol.upper().replace("USDT", "")
    try:
        client = _get_binance_client(wallet)
        positions = client.get_positions()
        position = next((
            pos for pos in positions
            if pos.get("symbol") == symbol
            and (
                not request.position_side
                or pos.get("position_side") == request.position_side
                or pos.get("position_side") == "BOTH"
            )
        ), None)
        if not position or float(position.get("szi") or 0) == 0:
            raise HTTPException(status_code=404, detail=f"No open Binance position for {symbol}")

        size = abs(float(position.get("szi") or 0))
        close_side = "SELL" if float(position.get("szi") or 0) > 0 else "BUY"
        result = client.close_position(
            symbol,
            cancel_tpsl=True,
            position_side=request.position_side,
        )
        if result is None:
            raise HTTPException(status_code=404, detail=f"No open Binance position for {symbol}")

        logger.warning(
            "[ManualClose] user_id=%s account_id=%s exchange=binance environment=%s symbol=%s side=%s size=%s order_id=%s",
            user_id,
            account.id,
            environment,
            symbol,
            close_side,
            size,
            result.get("order_id"),
        )
        return {
            "success": True,
            "account_id": account.id,
            "account_name": account.name,
            "exchange": "binance",
            "environment": environment,
            "symbol": symbol,
            "position_side": position.get("position_side"),
            "close_side": close_side,
            "closed_size": size,
            "order_id": result.get("order_id"),
            "status": result.get("status"),
            "filled_qty": result.get("executed_qty"),
            "avg_price": result.get("avg_price"),
            "cancelled_algo_orders": result.get("cancelled_algo_orders"),
        }
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("[ManualClose] Failed to close %s for account %s: %s", symbol, account.id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
