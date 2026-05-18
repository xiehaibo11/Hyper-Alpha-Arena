"""Core helpers for HyperliquidTradingClient."""

import json
import logging
import requests
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import Account, HyperliquidExchangeAction
from services.exchanges.symbol_mapper import SymbolMapper

logger = logging.getLogger(__name__)

UNIFIED_ACCOUNT_MODES = ("unifiedAccount", "portfolioMargin")

class HyperliquidCoreMixin:
    def _get_exchange_symbol(self, symbol: str) -> str:
        return SymbolMapper.to_exchange(symbol, "hyperliquid")

    def _hip3_trade_error(self, symbol: str) -> Optional[str]:
        if not SymbolMapper.is_hip3_symbol(symbol):
            return None
        if self.environment == "testnet":
            return f"HIP-3 symbol {symbol} trading is currently only supported on mainnet"
        if not getattr(self, "hip3_sdk_enabled", False):
            return f"HIP-3 metadata unavailable; cannot trade {symbol}"
        return None

    def _fetch_user_state_with_hip3(self) -> Dict[str, Any]:
        """Fetch standard user state and append HIP-3 positions when available."""
        user_state = self.sdk_info.user_state(self.query_address)
        if not getattr(self, "hip3_sdk_enabled", False):
            return user_state
        try:
            hip3_state = self.sdk_info.user_state(self.query_address, dex="xyz")
            hip3_positions = hip3_state.get("assetPositions", []) if isinstance(hip3_state, dict) else []
            if hip3_positions:
                merged = dict(user_state)
                merged["assetPositions"] = list(user_state.get("assetPositions", [])) + hip3_positions
                return merged
        except Exception as hip3_err:
            logger.warning("Failed to fetch HIP-3 user state, using standard state only: %s", hip3_err)
        return user_state

    def _fetch_frontend_open_orders_with_hip3(self) -> List[Dict[str, Any]]:
        """Fetch standard open orders and append HIP-3 open orders when available."""
        open_orders = list(self.sdk_info.frontend_open_orders(self.query_address))
        if not getattr(self, "hip3_sdk_enabled", False):
            return open_orders
        try:
            hip3_orders = self.sdk_info.frontend_open_orders(self.query_address, dex="xyz")
            if hip3_orders:
                open_orders.extend(hip3_orders)
        except Exception as hip3_err:
            logger.warning("Failed to fetch HIP-3 open orders, using standard orders only: %s", hip3_err)
        return open_orders

    def _disable_hip3_markets(self) -> None:
        """Ensure HIP3 market fetching is disabled in ccxt."""
        try:
            fetch_markets_options = self.exchange.options.setdefault('fetchMarkets', {})
            hip3_options = fetch_markets_options.setdefault('hip3', {})
            hip3_options['enabled'] = False
            hip3_options['dex'] = []
            # Manually initialize hip3TokensByName to prevent KeyError in coin_to_market_id()
            self.exchange.options.setdefault('hip3TokensByName', {})
        except Exception as options_error:
            logger.debug(f"Unable to update HIP3 fetch options: {options_error}")

        if hasattr(self.exchange, 'fetch_hip3_markets'):
            def _skip_hip3_markets(exchange_self, params=None):
                logger.debug("Skipping HIP3 market fetch per deployment requirements")
                return []
            self.exchange.fetch_hip3_markets = _skip_hip3_markets.__get__(self.exchange, type(self.exchange))
            logger.info("HIP3 market fetch disabled for Hyperliquid exchange instance")

    def _serialize_payload(self, payload: Optional[Any]) -> Optional[str]:
        if payload is None:
            return None
        try:
            return json.dumps(payload, default=str)
        except Exception:
            return str(payload)

    def _get_builder_params(self) -> Optional[Dict[str, Any]]:
        """
        Get builder fee parameters for orders.

        Only returns builder params for mainnet environment to avoid
        unnecessary fees on testnet trading.

        Fee rates:
        - Self-hosted deployment: 0 (0% - FREE)

        Returns:
            Dict with builder address and fee rate for mainnet, None for testnet
            Format: {"b": "0x...", "f": 0 or 30} or None
        """
        # Only apply builder fee on mainnet, not on testnet
        if self.environment != "mainnet":
            return None

        from config.settings import HYPERLIQUID_BUILDER_CONFIG

        builder_fee = 0
        logger.info("[BUILDER FEE] Self-hosted deployment detected, using FREE fee: 0%")

        return {
            "b": HYPERLIQUID_BUILDER_CONFIG.builder_address,
            "f": builder_fee
        }

    def _record_exchange_action(
        self,
        action_type: str,
        status: str,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        leverage: Optional[int] = None,
        size: Optional[float] = None,
        price: Optional[float] = None,
        request_payload: Optional[Any] = None,
        response_payload: Optional[Any] = None,
        error_message: Optional[str] = None,
        request_weight: int = 1,
    ) -> None:
        session = SessionLocal()
        try:
            size_decimal = Decimal(str(size)) if size is not None else None
            price_decimal = Decimal(str(price)) if price is not None else None
            notional_decimal = (
                size_decimal * price_decimal if size_decimal is not None and price_decimal is not None else None
            )

            entry = HyperliquidExchangeAction(
                account_id=self.account_id,
                environment=self.environment,
                wallet_address=self.wallet_address,
                action_type=action_type,
                status=status,
                symbol=symbol,
                side=side,
                leverage=leverage,
                size=size_decimal,
                price=price_decimal,
                notional=notional_decimal,
                request_weight=request_weight,
                request_payload=self._serialize_payload(request_payload),
                response_payload=self._serialize_payload(response_payload),
                error_message=error_message[:2000] if error_message else None,
            )
            session.add(entry)
            session.commit()
        except Exception as log_err:
            session.rollback()
            logger.warning(f"Failed to record Hyperliquid exchange action ({action_type}): {log_err}")
        finally:
            session.close()

    def _validate_environment(self, db: Session) -> bool:
        """
        Validate that account has a wallet configured for this environment

        Multi-wallet architecture: Each account can have separate testnet and mainnet wallets.
        This validates that the wallet for the current environment exists and is active.

        Args:
            db: Database session

        Returns:
            True if validation passes

        Raises:
            ValueError: If account not found or wallet not configured for this environment
        """
        from database.models import HyperliquidWallet

        account = db.query(Account).filter(Account.id == self.account_id, Account.is_deleted != True).first()
        if not account:
            raise ValueError(f"Account {self.account_id} not found")

        # Check if wallet exists for this account and environment
        wallet = db.query(HyperliquidWallet).filter(
            HyperliquidWallet.account_id == self.account_id,
            HyperliquidWallet.environment == self.environment
        ).first()

        if not wallet:
            raise ValueError(
                f"No {self.environment} wallet configured for account {account.name}. "
                f"Please configure a wallet before trading."
            )

        return True

    def _detect_account_mode(self) -> str:
        """
        Detect Hyperliquid account mode via the userAbstraction API.

        Calls POST /info {"type": "userAbstraction", "user": query_address}.
        Returns "unifiedAccount", "portfolioMargin", or "disabled" (standard).

        No caching — this is called once per get_account_state() invocation.
        The API is lightweight and the result can change at any time.

        Returns:
            "unifiedAccount", "portfolioMargin", or "standard"
        """
        try:
            resp = requests.post(
                f"{self.api_url}/info",
                json={"type": "userAbstraction", "user": self.query_address},
                timeout=5,
            )
            resp.raise_for_status()
            mode = resp.json()
            # API returns a plain string: "unifiedAccount", "disabled", or "portfolioMargin"
            if isinstance(mode, str) and mode in UNIFIED_ACCOUNT_MODES:
                return mode
            return "standard"
        except Exception as e:
            print(f"[ACCOUNT MODE] userAbstraction API failed for {self.query_address}: {e}", flush=True)
            return "standard"

    def _get_spot_balance(self) -> Dict[str, float]:
        """
        Get balance from spotClearinghouseState for unified account mode.

        Returns:
            Dict with total_equity, available_balance, used_margin
        """
        spot_state = self.sdk_info.spot_user_state(self.query_address)
        balances = spot_state.get("balances", [])

        usdc_total = 0.0
        usdc_hold = 0.0
        for bal in balances:
            if bal.get("coin") == "USDC":
                usdc_total = float(bal.get("total", 0) or 0)
                usdc_hold = float(bal.get("hold", 0) or 0)
                break

        return {
            "total_equity": usdc_total,
            "available_balance": usdc_total - usdc_hold,
            "used_margin": usdc_hold,
        }
