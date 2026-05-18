"""Leverage, cancellation, and raw open-order helpers for HyperliquidTradingClient."""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from services.exchanges.symbol_mapper import SymbolMapper

logger = logging.getLogger(__name__)

class HyperliquidOrderManagementMixin:
    def set_leverage(self, db: Session, symbol: str, leverage: int) -> bool:
        """
        Set leverage for a specific asset using Hyperliquid SDK

        Args:
            db: Database session
            symbol: Asset symbol (e.g., "BTC")
            leverage: Leverage to set (1-50)

        Returns:
            True if successful

        Raises:
            EnvironmentMismatchError: If environment validation fails
            ValueError: If leverage invalid
        """
        self._validate_environment(db)

        if leverage < 1 or leverage > 50:
            raise ValueError(f"Invalid leverage: {leverage}. Must be 1-50")
        hip3_error = self._hip3_trade_error(symbol)
        if hip3_error:
            self._record_exchange_action(
                action_type="set_leverage",
                status="error",
                symbol=symbol,
                leverage=leverage,
                request_payload={"symbol": symbol, "leverage": leverage},
                error_message=hip3_error,
            )
            return False

        try:
            exchange_symbol = self._get_exchange_symbol(symbol)
            logger.info(f"Setting leverage for {symbol} to {leverage}x on {self.environment}")

            result = self.sdk_exchange.update_leverage(leverage, exchange_symbol, is_cross=True)
            logger.debug(f"Set leverage result: {result}")

            self._record_exchange_action(
                action_type="set_leverage",
                status="success",
                symbol=symbol,
                leverage=leverage,
                request_payload={"symbol": exchange_symbol, "leverage": leverage},
                response_payload=result,
            )

            return True

        except Exception as e:
            logger.error(f"Failed to set leverage: {e}")
            self._record_exchange_action(
                action_type="set_leverage",
                status="error",
                symbol=symbol,
                leverage=leverage,
                request_payload={"symbol": symbol, "leverage": leverage},
                error_message=str(e),
            )
            raise

    def cancel_order(self, db: Session, order_id: Any, symbol: str) -> bool:
        """
        Cancel an open order using Hyperliquid SDK

        Args:
            db: Database session
            order_id: Hyperliquid order ID (oid) - can be int or string
            symbol: Asset symbol

        Returns:
            True if successful

        Raises:
            EnvironmentMismatchError: If environment validation fails
        """
        self._validate_environment(db)

        hip3_error = self._hip3_trade_error(symbol)
        if hip3_error:
            logger.warning("[CANCEL] Refusing HIP-3 cancel for %s: %s", symbol, hip3_error)
            self._record_exchange_action(
                action_type="cancel_order",
                status="error",
                symbol=symbol,
                request_payload={"order_id": order_id, "symbol": symbol},
                error_message=hip3_error,
            )
            return False

        try:
            # Ensure order_id is an integer (SDK requires int)
            if isinstance(order_id, str):
                order_id = int(order_id)
            exchange_symbol = self._get_exchange_symbol(symbol)

            logger.info(f"[CANCEL] Cancelling order {order_id} (type={type(order_id).__name__}) for {symbol} on {self.environment}")

            # Use SDK to cancel order
            result = self.sdk_exchange.cancel(exchange_symbol, order_id)

            logger.info(f"[CANCEL] SDK cancel result: {result}")

            # Check for success - SDK returns {"status": "ok", "response": {"type": "cancel", "data": {"statuses": ["success"]}}}
            if result.get("status") == "ok":
                response_data = result.get("response", {})
                if isinstance(response_data, dict):
                    statuses = response_data.get("data", {}).get("statuses", [])
                    if statuses and statuses[0] == "success":
                        logger.info(f"[CANCEL] Successfully cancelled order {order_id} for {symbol}")
                        self._record_exchange_action(
                            action_type="cancel_order",
                            status="success",
                            symbol=symbol,
                            request_payload={"order_id": order_id, "symbol": exchange_symbol},
                            response_payload=result,
                        )
                        return True
                    elif statuses and "error" in str(statuses[0]).lower():
                        error_msg = statuses[0]
                        logger.error(f"[CANCEL] Failed to cancel order {order_id}: {error_msg}")
                        self._record_exchange_action(
                            action_type="cancel_order",
                            status="error",
                            symbol=symbol,
                            request_payload={"order_id": order_id, "symbol": exchange_symbol},
                            response_payload=result,
                            error_message=str(error_msg),
                        )
                        return False

                # If we got here with status "ok", assume success
                logger.info(f"[CANCEL] Order {order_id} cancelled (status=ok)")
                self._record_exchange_action(
                    action_type="cancel_order",
                    status="success",
                    symbol=symbol,
                    request_payload={"order_id": order_id, "symbol": exchange_symbol},
                    response_payload=result,
                )
                return True
            else:
                error_msg = result.get("response", "Unknown error")
                self._record_exchange_action(
                    action_type="cancel_order",
                    status="error",
                    symbol=symbol,
                    request_payload={"order_id": order_id, "symbol": exchange_symbol},
                    response_payload=result,
                    error_message=str(error_msg),
                )
                logger.error(f"[CANCEL] Failed to cancel order {order_id}: {error_msg}")
                return False

        except ValueError as ve:
            logger.error(f"[CANCEL] Invalid order_id format: {order_id} - {ve}")
            self._record_exchange_action(
                action_type="cancel_order",
                status="error",
                symbol=symbol,
                request_payload={"order_id": order_id, "symbol": symbol},
                error_message=f"Invalid order_id format: {ve}",
            )
            return False
        except Exception as e:
            self._record_exchange_action(
                action_type="cancel_order",
                status="error",
                symbol=symbol,
                request_payload={"order_id": order_id, "symbol": symbol},
                error_message=str(e),
            )
            logger.error(f"[CANCEL] Failed to cancel order: {e}", exc_info=True)
            raise

    def _get_open_orders_raw(self, db: Session, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all open orders (including TP/SL trigger orders) from Hyperliquid - returns raw SDK data

        INTERNAL USE ONLY: This method returns raw SDK data format for TP/SL management.
        For formatted order data, use get_open_orders() instead.

        Args:
            db: Database session
            symbol: Optional symbol filter (e.g., "BTC"). If None, returns all symbols.

        Returns:
            List of open order dicts with raw SDK fields:
                - oid: Order ID
                - coin: Symbol name
                - side: "B" (buy) or "A" (sell/ask)
                - sz: Order size
                - limitPx: Limit price
                - orderType: Order type info
                - triggerPx: Trigger price (for TP/SL orders)
                - tpsl: "tp" or "sl" (for TP/SL orders)
                - reduceOnly: Whether order is reduce-only

        Raises:
            EnvironmentMismatchError: If environment validation fails
        """
        self._validate_environment(db)

        try:
            logger.info(f"Fetching raw open orders for wallet {self.query_address} on {self.environment}")

            # Use SDK Info to get open orders (frontend_open_orders includes trigger orders)
            # Must use query_address (master wallet) for agent_key mode
            open_orders = self._fetch_frontend_open_orders_with_hip3()

            logger.debug(f"Retrieved {len(open_orders)} open orders for wallet {self.query_address}")

            # Filter by symbol if specified
            if symbol:
                internal_symbol = SymbolMapper.to_internal(symbol, "hyperliquid")
                open_orders = [
                    o for o in open_orders
                    if SymbolMapper.to_internal(o.get('coin', ''), "hyperliquid") == internal_symbol
                ]
                logger.debug(f"Filtered to {len(open_orders)} orders for symbol {symbol}")

            self._record_exchange_action(
                action_type="fetch_open_orders_raw",
                status="success",
                symbol=symbol,
                request_payload={
                    "account_id": self.account_id,
                    "wallet_address": self.wallet_address,
                    "symbol_filter": symbol,
                },
                response_payload=None,
            )

            return open_orders

        except Exception as e:
            self._record_exchange_action(
                action_type="fetch_open_orders_raw",
                status="error",
                symbol=symbol,
                request_payload={
                    "account_id": self.account_id,
                    "wallet_address": self.wallet_address,
                    "symbol_filter": symbol,
                },
                error_message=str(e),
            )
            logger.error(f"Failed to get raw open orders: {e}", exc_info=True)
            raise
