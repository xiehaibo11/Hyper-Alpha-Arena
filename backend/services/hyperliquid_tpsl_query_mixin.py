"""Take-profit and stop-loss query helpers for HyperliquidTradingClient."""

import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

class HyperliquidTpslQueryMixin:
    def get_tpsl_orders(self, db: Session, symbol: str) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Get current TP and SL orders for a specific symbol

        Args:
            db: Database session
            symbol: Asset symbol (e.g., "BTC")

        Returns:
            Dict with:
                - tp: TP order dict or None (most recent if multiple exist)
                - sl: SL order dict or None (most recent if multiple exist)
                - all_tp_orders: List of ALL TP orders found
                - all_sl_orders: List of ALL SL orders found
        """
        open_orders = self._get_open_orders_raw(db, symbol)

        # Debug: log all open orders to understand structure
        import sys
        print(f"[TPSL DEBUG] {symbol} - Found {len(open_orders)} open orders", file=sys.stderr, flush=True)
        logger.info(f"[TPSL DEBUG] {symbol} - Found {len(open_orders)} open orders")
        for i, order in enumerate(open_orders):
            print(f"[TPSL DEBUG] Order {i}: {order}", file=sys.stderr, flush=True)
            logger.info(f"[TPSL DEBUG] Order {i}: {order}")

        # Collect ALL TP and SL orders (not just the first one)
        all_tp_orders = []
        all_sl_orders = []

        for order in open_orders:
            order_type = order.get('orderType', {})
            is_trigger = order.get('isTrigger', False)
            trigger_px = order.get('triggerPx')
            trigger_condition = order.get('triggerCondition', '')

            # Debug: log order type structure
            logger.debug(f"[TPSL DEBUG] Order type: {order_type}, type={type(order_type)}, isTrigger={is_trigger}")

            # Determine if this is a TP or SL order
            # Support BOTH formats:
            # 1. Dict format: orderType = {"trigger": {"tpsl": "tp", "triggerPx": ...}}
            # 2. String format: orderType = "Take Profit Limit" or "Stop Limit"

            tpsl_type = None
            trigger_price = None

            # Format 1: Dict with trigger info
            if isinstance(order_type, dict) and 'trigger' in order_type:
                trigger_info = order_type.get('trigger', {})
                tpsl_type = trigger_info.get('tpsl')
                trigger_price = float(trigger_info.get('triggerPx', 0))
                logger.info(f"[TPSL DEBUG] Found dict trigger order: tpsl={tpsl_type}, trigger_price={trigger_price}")

            # Format 2: String orderType (from frontend_open_orders)
            elif isinstance(order_type, str) and is_trigger:
                # Parse orderType string: "Take Profit Limit" or "Stop Limit"
                order_type_lower = order_type.lower()
                if 'take profit' in order_type_lower:
                    tpsl_type = 'tp'
                elif 'stop' in order_type_lower and 'limit' in order_type_lower:
                    tpsl_type = 'sl'

                # Get trigger price from triggerPx field
                if trigger_px:
                    try:
                        trigger_price = float(trigger_px)
                    except (ValueError, TypeError):
                        trigger_price = 0

                logger.info(f"[TPSL DEBUG] Found string trigger order: orderType='{order_type}', tpsl={tpsl_type}, trigger_price={trigger_price}")

            # Format 3: Check triggerCondition as fallback
            elif is_trigger and trigger_condition:
                # Parse triggerCondition: "Price above 130" (TP) or "Price below 125.5" (SL)
                if 'above' in trigger_condition.lower():
                    tpsl_type = 'tp'
                elif 'below' in trigger_condition.lower():
                    tpsl_type = 'sl'

                if trigger_px:
                    try:
                        trigger_price = float(trigger_px)
                    except (ValueError, TypeError):
                        trigger_price = 0

                logger.info(f"[TPSL DEBUG] Found trigger by condition: condition='{trigger_condition}', tpsl={tpsl_type}, trigger_price={trigger_price}")

            # If we identified a TP or SL order, add it to the list
            if tpsl_type and trigger_price:
                order_dict = {
                    'oid': order.get('oid'),
                    'trigger_price': trigger_price,
                    'limit_price': float(order.get('limitPx', 0)),
                    'size': float(order.get('sz', 0)),
                    'side': order.get('side'),
                    'reduce_only': order.get('reduceOnly', True),
                    'timestamp': order.get('timestamp', 0),
                }

                if tpsl_type == 'tp':
                    all_tp_orders.append(order_dict)
                    logger.info(f"[TPSL DEBUG] Identified TP order: {order_dict}")
                elif tpsl_type == 'sl':
                    all_sl_orders.append(order_dict)
                    logger.info(f"[TPSL DEBUG] Identified SL order: {order_dict}")

        # Return the most recent order of each type (for backward compatibility)
        # but also include all orders for cleanup
        tp_order = all_tp_orders[0] if all_tp_orders else None
        sl_order = all_sl_orders[0] if all_sl_orders else None

        logger.info(f"[TPSL] {symbol} - Found {len(all_tp_orders)} TP orders, {len(all_sl_orders)} SL orders")
        logger.info(f"[TPSL] {symbol} - Primary TP={tp_order}, Primary SL={sl_order}")

        return {
            'tp': tp_order,
            'sl': sl_order,
            'all_tp_orders': all_tp_orders,
            'all_sl_orders': all_sl_orders,
        }
