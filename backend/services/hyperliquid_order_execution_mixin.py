"""Order placement, leverage, and cancellation helpers for HyperliquidTradingClient."""

import logging
import time
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from services.exchanges.symbol_mapper import SymbolMapper

logger = logging.getLogger(__name__)

class HyperliquidOrderExecutionMixin:
    def place_order(
        self,
        db: Session,
        symbol: str,
        is_buy: bool,
        size: float,
        order_type: str = "market",
        price: Optional[float] = None,
        reduce_only: bool = False,
        leverage: int = 1
    ) -> Dict[str, Any]:
        """
        Place order on Hyperliquid

        Args:
            db: Database session
            symbol: Asset symbol (e.g., "BTC")
            is_buy: True for long, False for short
            size: Order quantity (absolute value)
            order_type: "market" or "limit"
            price: Limit price (required for limit orders)
            reduce_only: Only close existing positions
            leverage: Position leverage (1-50)

        Returns:
            Dict with:
                - status: "resting" | "filled" | "error"
                - oid: Order ID (if resting)
                - filled: Execution details (if filled)
                - error: Error message (if error)

        Raises:
            EnvironmentMismatchError: If environment validation fails
            ValueError: If parameters invalid
        """
        self._validate_environment(db)

        # Validate parameters
        if order_type not in ["market", "limit"]:
            raise ValueError(f"Invalid order_type: {order_type}")

        if order_type == "limit" and price is None:
            raise ValueError("Limit orders require price parameter")

        if leverage < 1 or leverage > 50:
            raise ValueError(f"Invalid leverage: {leverage}. Must be 1-50")
        hip3_error = self._hip3_trade_error(symbol)
        if hip3_error:
            self._record_exchange_action(
                action_type="create_order",
                status="error",
                symbol=symbol,
                side="buy" if is_buy else "sell",
                leverage=leverage,
                size=size,
                price=price,
                request_payload={"symbol": symbol, "order_type": order_type, "reduce_only": reduce_only},
                response_payload=None,
                error_message=hip3_error,
            )
            return {
                'status': 'error',
                'error': hip3_error,
                'environment': self.environment,
                'symbol': symbol,
            }
        exchange_symbol = self._get_exchange_symbol(symbol)
        is_hip3 = SymbolMapper.is_hip3_symbol(symbol)

        if size <= 0:
            raise ValueError(f"Invalid size: {size}. Must be positive")

        # Log order attempt with environment
        logger.warning(
            f"PLACING ORDER on {self.environment.upper()}: "
            f"account={self.account_id} {symbol} {'BUY' if is_buy else 'SELL'} "
            f"size={size} leverage={leverage}x type={order_type} reduce_only={reduce_only}"
        )

        action_payload: Optional[Dict[str, Any]] = None

        try:
            # Set leverage before placing order (if different from current)
            try:
                result = self.sdk_exchange.update_leverage(leverage, exchange_symbol, is_cross=True)
                logger.debug(f"Set leverage to {leverage}x for {symbol}, result: {result}")
                self._record_exchange_action(
                    action_type="set_leverage",
                    status="success",
                    symbol=symbol,
                    leverage=leverage,
                    request_payload={"symbol": exchange_symbol, "leverage": leverage},
                    response_payload=result,
                )
            except Exception as lev_err:
                logger.warning(f"Failed to set leverage (may already be set): {lev_err}")
                self._record_exchange_action(
                    action_type="set_leverage",
                    status="error",
                    symbol=symbol,
                    leverage=leverage,
                    request_payload={"symbol": exchange_symbol, "leverage": leverage},
                    error_message=str(lev_err),
                )

            if is_hip3:
                if order_type == "market" and price is None:
                    last_price = get_last_price_from_hyperliquid(symbol, environment="mainnet")
                    if not last_price:
                        raise ValueError(f"Market order requires price parameter or valid market price for {symbol}")
                    price = last_price

                precision = self._get_asset_precision(symbol)
                price_decimals = precision.get('price_decimals', 1)
                size_decimals = precision.get('size_decimals', 5)
                price_tick = precision.get('price_tick')
                size_step = precision.get('size_step')

                is_ioc_order = order_type == "market"
                sdk_price = self._round_to_precision(
                    price,
                    price_decimals,
                    size_decimals,
                    is_price=True,
                    price_tick=price_tick,
                    size_step=size_step,
                    is_buy=is_buy,
                    force_aggressive=is_ioc_order,
                )
                sdk_size = self._round_to_precision(
                    size,
                    price_decimals,
                    size_decimals,
                    is_price=False,
                    price_tick=price_tick,
                    size_step=size_step,
                )
                sdk_order_type = {"limit": {"tif": "Ioc" if is_ioc_order else "Gtc"}}
                side = "buy" if is_buy else "sell"
                action_payload = {
                    "symbol": exchange_symbol,
                    "side": side,
                    "amount": sdk_size,
                    "price": sdk_price,
                    "order_type": sdk_order_type,
                    "reduce_only": reduce_only,
                }

                sdk_order_params = {
                    "name": exchange_symbol,
                    "is_buy": is_buy,
                    "sz": sdk_size,
                    "limit_px": sdk_price,
                    "order_type": sdk_order_type,
                    "reduce_only": reduce_only,
                }
                builder_params = self._get_builder_params()
                if builder_params:
                    sdk_order_params["builder"] = builder_params

                order = self.sdk_exchange.order(**sdk_order_params)
                order_id = None
                status = "error"
                error_msg = None
                filled_amount = 0
                average_price = None

                if order.get("status") == "ok":
                    statuses = order.get("response", {}).get("data", {}).get("statuses", [])
                    if statuses:
                        main_status = statuses[0]
                        if "filled" in main_status:
                            filled_info = main_status["filled"]
                            order_id = str(filled_info.get("oid", ""))
                            filled_amount = float(filled_info.get("totalSz", 0) or 0)
                            average_price = float(filled_info.get("avgPx", 0) or 0)
                            status = "filled"
                        elif "resting" in main_status:
                            resting_info = main_status["resting"]
                            order_id = str(resting_info.get("oid", ""))
                            status = "resting"
                        elif "error" in main_status:
                            error_msg = main_status["error"]
                        else:
                            error_msg = f"Unknown status in response: {main_status}"
                    else:
                        error_msg = "No statuses in response"
                else:
                    error_msg = order.get("response", "Unknown error")

                result = {
                    'status': status,
                    'environment': self.environment,
                    'symbol': symbol,
                    'is_buy': is_buy,
                    'size': sdk_size,
                    'leverage': leverage,
                    'order_type': order_type,
                    'reduce_only': reduce_only,
                    'order_id': order_id,
                    'filled_amount': filled_amount,
                    'average_price': average_price,
                    'raw_order': order,
                    'wallet_address': self.wallet_address,
                    'timestamp': int(time.time() * 1000),
                }
                if error_msg:
                    result['error'] = error_msg

                self._record_exchange_action(
                    action_type="create_order",
                    status="success" if status != 'error' else 'error',
                    symbol=symbol,
                    side=side,
                    leverage=leverage,
                    size=sdk_size,
                    price=sdk_price,
                    request_payload=action_payload,
                    response_payload=order,
                    error_message=result.get('error'),
                )
                return result

            # Prepare CCXT order parameters
            # Hyperliquid perpetual contract format: BASE/QUOTE:SETTLE
            ccxt_symbol = f"{symbol}/USDC:USDC"  # Hyperliquid perpetual format
            logger.debug(f"Using symbol format: {ccxt_symbol}")
            ccxt_type = order_type  # "market" or "limit"
            ccxt_side = "buy" if is_buy else "sell"
            ccxt_amount = size

            # Hyperliquid market orders require price parameter to calculate slippage protection
            # CCXT will use price * (1 +/- 5% slippage) as the max acceptable execution price
            # For limit orders, price is the exact limit price
            # For market orders, price is the reference price for slippage calculation
            if order_type == "market" and price is None:
                # If no price provided for market order, fetch current market price
                try:
                    ticker = self.exchange.fetch_ticker(ccxt_symbol)
                    price = ticker['last']
                    logger.debug(f"Fetched current price for market order: {price}")
                except Exception as e:
                    raise ValueError(f"Market order requires price parameter or valid market price. Error: {e}")

            ccxt_price = price

            # Additional parameters for Hyperliquid
            params = {
                'reduceOnly': reduce_only
            }

            logger.debug(
                f"CCXT order params: symbol={ccxt_symbol} type={ccxt_type} "
                f"side={ccxt_side} amount={ccxt_amount} price={ccxt_price} params={params}"
            )

            action_payload = {
                'symbol': ccxt_symbol,
                'side': ccxt_side,
                'amount': ccxt_amount,
                'price': ccxt_price,
                'order_type': ccxt_type,
                'params': params
            }

            # Place order via CCXT
            order = self.exchange.create_order(
                symbol=ccxt_symbol,
                type=ccxt_type,
                side=ccxt_side,
                amount=ccxt_amount,
                price=ccxt_price,
                params=params
            )

            # DEBUG: Print raw CCXT order response
            logger.warning(f"[DEBUG] CCXT Raw Order Response: {order}")

            # Parse CCXT order response
            order_id = order.get('id')
            order_status = order.get('status')  # "open", "closed", "canceled"
            filled_amount = float(order.get('filled') or 0)
            average_price = float(order.get('average') or 0) if order.get('average') else None

            # Map CCXT status to our status
            # First check for Hyperliquid-specific errors
            hyperliquid_info = order.get('info', {})
            hyperliquid_response = hyperliquid_info.get('response', {})
            hyperliquid_data = hyperliquid_response.get('data', {})
            hyperliquid_statuses = hyperliquid_data.get('statuses', [])

            # Check for errors in Hyperliquid response
            hyperliquid_error = None
            if hyperliquid_statuses:
                for status_item in hyperliquid_statuses:
                    if 'error' in status_item:
                        hyperliquid_error = status_item['error']
                        break

            if hyperliquid_error:
                # Hyperliquid returned an error
                status = 'error'
                error_msg = hyperliquid_error
            else:
                # Check for successful execution
                hyperliquid_filled = hyperliquid_info.get('filled')
                logger.warning(f"[DEBUG] hyperliquid_filled: {hyperliquid_filled}")

                if hyperliquid_filled and hyperliquid_filled.get('totalSz'):
                    # Hyperliquid shows filled info, order was executed
                    status = 'filled'
                    error_msg = None
                    # Update filled_amount and average_price from Hyperliquid data
                    filled_amount = float(hyperliquid_filled.get('totalSz', 0))
                    average_price = float(hyperliquid_filled.get('avgPx', 0))
                elif order_status == 'closed' or (filled_amount > 0 and filled_amount >= ccxt_amount * 0.99):
                    # CCXT shows closed or nearly fully filled
                    status = 'filled'
                    error_msg = None
                elif order_status == 'open':
                    # Order is on the book
                    status = 'resting'
                    error_msg = None
                elif order_status == 'canceled':
                    # Order was canceled
                    status = 'canceled'
                    error_msg = None
                else:
                    # Unknown status
                    status = 'error'
                    error_msg = f"Unknown order status: {order_status}"

            result = {
                'status': status,
                'environment': self.environment,
                'symbol': symbol,
                'is_buy': is_buy,
                'size': size,
                'leverage': leverage,
                'order_type': order_type,
                'reduce_only': reduce_only,
                'order_id': order_id,
                'filled_amount': filled_amount,
                'average_price': average_price,
                'raw_order': order,  # Full CCXT response for debugging
                'wallet_address': self.wallet_address,
                'timestamp': int(time.time() * 1000)
            }

            # Add error message if present
            if error_msg:
                result['error'] = error_msg

            logger.info(
                f"Order result: status={status} order_id={order_id} "
                f"filled={filled_amount}/{size} avg_price={average_price}"
            )

            self._record_exchange_action(
                action_type="create_order",
                status="success" if status != 'error' else 'error',
                symbol=symbol,
                side=ccxt_side,
                leverage=leverage,
                size=ccxt_amount,
                price=ccxt_price,
                request_payload=action_payload,
                response_payload=order,
                error_message=result.get('error'),
            )

            return result

        except Exception as e:
            self._record_exchange_action(
                action_type="create_order",
                status="error",
                symbol=symbol,
                side="buy" if is_buy else "sell",
                leverage=leverage,
                size=size,
                price=price,
                request_payload=locals().get('action_payload'),
                response_payload=None,
                error_message=str(e),
            )
            logger.error(f"Failed to place order: {e}", exc_info=True)
            return {
                'status': 'error',
                'error': str(e),
                'environment': self.environment,
                'symbol': symbol
            }
