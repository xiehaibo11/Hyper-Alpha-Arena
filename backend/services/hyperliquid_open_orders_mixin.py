"""Open-order and TP/SL query helpers for HyperliquidTradingClient."""

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from services.exchanges.symbol_mapper import SymbolMapper
from services.hyperliquid_tpsl_cache import _get_cached_tpsl

logger = logging.getLogger(__name__)

class HyperliquidOpenOrdersMixin:
    def get_open_orders(self, db: Session, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get current open orders (unfilled/partially filled orders)

        This method uses Hyperliquid SDK's Info.frontend_open_orders() to retrieve
        all open orders with complete frontend information including trigger conditions,
        TP/SL flags, and order types.

        Args:
            db: Database session (for environment validation)
            symbol: Optional symbol filter (e.g., "BTC"). If None, returns all symbols.

        Returns:
            List of open order dicts with fields:
                - order_id: Order ID
                - symbol: Symbol name
                - side: "Buy" or "Sell"
                - direction: "Close Short", "Close Long", "Open Long", "Open Short"
                - order_type: Order type (e.g., "Stop Limit", "Take Profit Limit", "Limit")
                - size: Current remaining size
                - original_size: Original order size
                - price: Limit price
                - order_value: Calculated order value (size * price)
                - reduce_only: Whether this is a reduce-only order
                - is_trigger: Whether this is a trigger order
                - trigger_condition: Trigger condition string (e.g., "Price above 87500")
                - trigger_price: Trigger price
                - is_position_tpsl: Whether this is a position-level TP/SL
                - tif: Time in force (may be null for trigger orders)
                - order_time: Order placement time (UTC string)
                - timestamp: Order placement timestamp (milliseconds)

        Raises:
            EnvironmentMismatchError: If environment validation fails
        """
        self._validate_environment(db)

        try:
            logger.info(f"Fetching open orders for wallet {self.query_address} on {self.environment}")

            # Use SDK Info to get frontend open orders (includes trigger conditions, TP/SL info)
            # Must use query_address (master wallet) for agent_key mode
            raw_orders = self._fetch_frontend_open_orders_with_hip3()

            # Transform to simplified format for AI prompt
            orders = []
            for order in raw_orders:
                from datetime import datetime, timezone

                # Parse order timestamp
                timestamp_ms = order.get('timestamp', 0)
                utc_dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
                order_time = utc_dt.strftime('%Y-%m-%d %H:%M:%S UTC')

                # Determine direction based on side and reduce_only
                side_raw = order.get('side', '')
                reduce_only = order.get('reduceOnly', False)

                if side_raw == 'B':  # Buy
                    side = 'Buy'
                    direction = 'Close Short' if reduce_only else 'Open Long'
                else:  # 'A' = Ask/Sell
                    side = 'Sell'
                    direction = 'Close Long' if reduce_only else 'Open Short'

                # Calculate order value
                size = float(order.get('sz', 0))
                price = float(order.get('limitPx', 0))
                order_value = size * price

                # Extract trigger information
                trigger_condition = order.get('triggerCondition', '')
                trigger_price = order.get('triggerPx')

                order_symbol = SymbolMapper.to_internal(order.get('coin', ''), "hyperliquid")
                order_summary = {
                    'order_id': order.get('oid'),
                    'symbol': order_symbol,
                    'side': side,
                    'direction': direction,
                    'order_type': order.get('orderType', 'Limit'),
                    'size': size,
                    'original_size': float(order.get('origSz', 0)),
                    'price': price,
                    'order_value': order_value,
                    'reduce_only': reduce_only,
                    'is_trigger': order.get('isTrigger', False),
                    'trigger_condition': trigger_condition if trigger_condition else None,
                    'trigger_price': float(trigger_price) if trigger_price else None,
                    'is_position_tpsl': order.get('isPositionTpsl', False),
                    'tif': order.get('tif'),
                    'order_time': order_time,
                    'timestamp': timestamp_ms,
                }

                orders.append(order_summary)

            # Sort by timestamp (newest first)
            orders.sort(key=lambda x: x.get('timestamp', 0), reverse=True)

            # Filter by symbol if specified
            if symbol:
                internal_symbol = SymbolMapper.to_internal(symbol, "hyperliquid")
                orders = [o for o in orders if o.get('symbol') == internal_symbol]
                logger.debug(f"Filtered to {len(orders)} orders for symbol {symbol}")

            logger.info(f"Found {len(orders)} open orders")

            self._record_exchange_action(
                action_type="fetch_open_orders",
                status="success",
                symbol=symbol,
                request_payload={
                    "account_id": self.account_id,
                    "wallet_address": self.wallet_address,
                    "environment": self.environment,
                    "symbol_filter": symbol,
                },
                response_payload=None,
            )

            return orders

        except Exception as e:
            self._record_exchange_action(
                action_type="fetch_open_orders",
                status="error",
                symbol=symbol,
                request_payload={
                    "account_id": self.account_id,
                    "wallet_address": self.wallet_address,
                    "environment": self.environment,
                    "symbol_filter": symbol,
                },
                response_payload=None,
                error_message=str(e),
            )
            logger.error(f"Failed to get open orders: {e}", exc_info=True)
            return []
