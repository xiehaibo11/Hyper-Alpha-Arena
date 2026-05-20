"""Wallet status tool implementation for Hyper AI."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def execute_get_wallet_status(db: Session, exchange: str = "all", environment: str = "all") -> str:
    """Get wallet balance and open-position summary using live exchange APIs."""
    from database.models import Account, BinanceWallet, HyperliquidWallet
    from services.binance_trading_client import BinanceTradingClient
    from services.hyperliquid_environment import get_hyperliquid_client
    from utils.encryption import decrypt_private_key

    try:
        normalized_exchange = (exchange or "all").lower()
        normalized_environment = (environment or "all").lower()
        wallets = []

        if normalized_exchange in {"all", "hyperliquid"}:
            query = db.query(HyperliquidWallet, Account).join(
                Account, HyperliquidWallet.account_id == Account.id
            ).filter(HyperliquidWallet.is_active == "true")
            if normalized_environment != "all":
                query = query.filter(HyperliquidWallet.environment == normalized_environment)

            for wallet, account in query.all():
                wallets.append(_load_hyperliquid_wallet(db, wallet, account, get_hyperliquid_client))

        if normalized_exchange in {"all", "binance"}:
            query = db.query(BinanceWallet, Account).join(
                Account, BinanceWallet.account_id == Account.id
            ).filter(BinanceWallet.is_active == "true")
            if normalized_environment != "all":
                query = query.filter(BinanceWallet.environment == normalized_environment)

            for wallet, account in query.all():
                wallets.append(
                    _load_binance_wallet(wallet, account, BinanceTradingClient, decrypt_private_key)
                )

        return json.dumps({"wallets": wallets}, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.error("[get_wallet_status] Error: %s", exc, exc_info=True)
        return json.dumps({"error": str(exc), "_error_class": type(exc).__name__})


def _load_hyperliquid_wallet(db: Session, wallet: Any, account: Any, client_factory: Any) -> Dict[str, Any]:
    try:
        client = client_factory(db, account.id, override_environment=wallet.environment)
        account_state = client.get_account_state(db)
        positions = [
            mapped for pos in account_state.get("positions", [])
            if (mapped := _map_position(pos)) is not None
        ]
        return {
            "exchange": "hyperliquid",
            "environment": wallet.environment,
            "wallet_address": _mask_address(wallet.wallet_address),
            "trader_id": account.id,
            "trader_name": account.name,
            "balance": {
                "total_equity": _to_float(account_state.get("total_equity")),
                "available_balance": _to_float(account_state.get("available_balance")),
                "used_margin": _to_float(account_state.get("used_margin")),
            },
            "positions": positions,
            "position_count": len(positions),
            "last_updated": "real-time",
        }
    except Exception as exc:
        logger.warning("[get_wallet_status] Failed Hyperliquid wallet %s: %s", account.name, exc)
        return _error_wallet("hyperliquid", wallet.environment, account, str(exc), wallet.wallet_address)


def _load_binance_wallet(
    wallet: Any,
    account: Any,
    client_class: Any,
    decrypt_private_key: Any,
) -> Dict[str, Any]:
    try:
        client = client_class(
            decrypt_private_key(wallet.api_key_encrypted),
            decrypt_private_key(wallet.secret_key_encrypted),
            wallet.environment,
        )
        balance = client.get_balance()
        positions = [
            mapped for pos in client.get_positions()
            if (mapped := _map_position(pos)) is not None
        ]
        return {
            "exchange": "binance",
            "environment": wallet.environment,
            "trader_id": account.id,
            "trader_name": account.name,
            "balance": {
                "total_equity": _to_float(balance.get("total_equity")),
                "available_balance": _to_float(balance.get("available_balance")),
                "used_margin": _to_float(balance.get("used_margin")),
                "unrealized_pnl": _to_float(balance.get("unrealized_pnl")),
            },
            "positions": positions,
            "position_count": len(positions),
            "last_updated": "real-time",
        }
    except Exception as exc:
        logger.warning("[get_wallet_status] Failed Binance wallet %s: %s", account.name, exc)
        return _error_wallet("binance", wallet.environment, account, str(exc))


def _map_position(pos: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    signed_size = _to_float(pos.get("szi") or pos.get("positionAmt") or pos.get("size"))
    if signed_size == 0:
        quantity = _to_float(pos.get("quantity") or pos.get("position_size"))
        side_text = str(pos.get("side") or "").lower()
        signed_size = -quantity if side_text == "short" else quantity
    if abs(signed_size) <= 1e-12:
        return None

    side = str(pos.get("side") or "").lower()
    if side not in {"long", "short"}:
        side = "long" if signed_size > 0 else "short"

    return {
        "symbol": pos.get("coin") or pos.get("symbol") or "",
        "size": abs(signed_size),
        "side": side,
        "entry_price": _to_float(pos.get("entry_px") or pos.get("entryPx") or pos.get("entry_price")),
        "mark_price": _to_float(pos.get("mark_price") or pos.get("markPx")),
        "position_value": _to_float(pos.get("position_value") or pos.get("positionValue")),
        "unrealized_pnl": _to_float(pos.get("unrealized_pnl") or pos.get("unrealizedPnl")),
        "leverage": _to_float(pos.get("leverage")),
        "liquidation_price": _to_float(pos.get("liquidation_px") or pos.get("liquidationPx")),
        "margin_used": _to_float(pos.get("margin_used") or pos.get("marginUsed")),
        "margin_mode": pos.get("leverage_type") or pos.get("margin_mode"),
    }


def _error_wallet(
    exchange: str,
    environment: str,
    account: Any,
    error: str,
    wallet_address: str | None = None,
) -> Dict[str, Any]:
    payload = {
        "exchange": exchange,
        "environment": environment,
        "trader_id": account.id,
        "trader_name": account.name,
        "balance": {"total_equity": 0, "available_balance": 0, "used_margin": 0},
        "positions": [],
        "position_count": 0,
        "error": error,
    }
    if wallet_address:
        payload["wallet_address"] = _mask_address(wallet_address)
    return payload


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _mask_address(address: str | None) -> str | None:
    if not address:
        return None
    if len(address) <= 16:
        return address
    return f"{address[:10]}...{address[-6:]}"
