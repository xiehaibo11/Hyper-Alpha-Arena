"""Combined entry + TP/SL order helper for HyperliquidTradingClient."""

import logging
import time
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from services.exchanges.symbol_mapper import SymbolMapper
from services.hyperliquid_tpsl_cache import _set_cached_tpsl

logger = logging.getLogger(__name__)

class HyperliquidTpslExecutionMixin:
    def place_order_with_tpsl(
        self,
        db: Session,
        symbol: str,
        is_buy: bool,
        size: float,
        price: float,
        leverage: int = 1,
        time_in_force: str = "Ioc",
        reduce_only: bool = False,
        take_profit_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        tp_execution: str = "limit",
        sl_execution: str = "limit",
    ) -> Dict[str, Any]:
        """
        Place order with take profit and stop loss using Hyperliquid official SDK

        Args:
            db: Database session
            symbol: Asset symbol (e.g., "BTC")
            is_buy: True for long, False for short
            size: Order quantity
            price: Order price
            leverage: Position leverage (1-50)
            time_in_force: Order time in force - "Ioc" (market-like), "Gtc" (limit), "Alo" (maker only)
            reduce_only: Only close existing positions
            take_profit_price: Optional take profit trigger price
            stop_loss_price: Optional stop loss trigger price
            tp_execution: TP execution mode - "limit" (attempts maker with offset) or "market" (immediate fill)
            sl_execution: SL execution mode - "limit" (may save fees) or "market" (guarantees execution)

        Returns:
            Dict with order results including TP/SL order IDs
        """
        import sys
        print(f"[DEBUG ENTRY] place_order_with_tpsl called: symbol={symbol}, price={price}, size={size}, TP={take_profit_price}, SL={stop_loss_price}", file=sys.stderr, flush=True)

        self._validate_environment(db)

        # Validate parameters
        if leverage < 1 or leverage > 50:
            raise ValueError(f"Invalid leverage: {leverage}. Must be 1-50")
        if size <= 0 or not isinstance(size, (int, float)) or size != size:  # Check for NaN
            raise ValueError(f"Invalid size: {size}. Must be a positive number")
        if price <= 0 or not isinstance(price, (int, float)) or price != price:  # Check for NaN
            raise ValueError(f"Invalid price: {price}. Must be a positive number")

        # Validate time_in_force
        valid_tif = ["Ioc", "Gtc", "Alo"]
        if time_in_force not in valid_tif:
            raise ValueError(f"Invalid time_in_force: {time_in_force}. Must be one of {valid_tif}")

        # Validate tp_execution and sl_execution
        valid_execution = ["market", "limit"]
        if tp_execution not in valid_execution:
            raise ValueError(f"Invalid tp_execution: {tp_execution}. Must be one of {valid_execution}")
        if sl_execution not in valid_execution:
            raise ValueError(f"Invalid sl_execution: {sl_execution}. Must be one of {valid_execution}")

        hip3_error = self._hip3_trade_error(symbol)
        if hip3_error:
            return {
                "status": "error",
                "error": hip3_error,
                "environment": self.environment,
                "symbol": symbol,
            }
        exchange_symbol = self._get_exchange_symbol(symbol)

        # ===== Dynamic Precision Handling =====
        # Fetch asset-specific precision requirements from Hyperliquid
        # This works for ALL assets (BTC, ETH, SOL, etc.) and handles AI-generated imprecise numbers
        print(f"[PRECISION] Fetching precision for {symbol}...", file=sys.stderr, flush=True)

        precision = self._get_asset_precision(symbol)
        price_decimals = precision['price_decimals']
        size_decimals = precision['size_decimals']
        price_tick = precision.get('price_tick')
        size_step = precision.get('size_step')

        print(
            f"[PRECISION] {symbol} - price_decimals: {price_decimals}, size_decimals: {size_decimals}, "
            f"price_tick: {price_tick}, size_step: {size_step}",
            file=sys.stderr,
            flush=True,
        )
        print(f"[PRECISION] Original values - price: {price}, size: {size}, TP: {take_profit_price}, SL: {stop_loss_price}", file=sys.stderr, flush=True)

        # Round price to tick precision
        original_price = price
        is_ioc_order = time_in_force.lower() == "ioc"

        price = self._round_to_precision(
            price,
            price_decimals,
            size_decimals,
            is_price=True,
            price_tick=price_tick,
            size_step=size_step,
            is_buy=is_buy,
            force_aggressive=is_ioc_order,
        )
        print(f"[PRECISION] Price adjusted: {original_price} -> {price}", file=sys.stderr, flush=True)

        # Round size using official step
        original_size = size
        size = self._round_to_precision(
            size,
            price_decimals,
            size_decimals,
            is_price=False,
            price_tick=price_tick,
            size_step=size_step,
        )
        print(f"[PRECISION] Size adjusted: {original_size} -> {size}", file=sys.stderr, flush=True)

        # Round TP/SL prices if provided
        if take_profit_price is not None:
            original_tp = take_profit_price
            take_profit_price = self._round_to_precision(
                take_profit_price,
                price_decimals,
                size_decimals,
                is_price=True,
                price_tick=price_tick,
                size_step=size_step,
                is_buy=not is_buy,
            )
            print(f"[PRECISION] TP adjusted: {original_tp} -> {take_profit_price}", file=sys.stderr, flush=True)

        if stop_loss_price is not None:
            original_sl = stop_loss_price
            stop_loss_price = self._round_to_precision(
                stop_loss_price,
                price_decimals,
                size_decimals,
                is_price=True,
                price_tick=price_tick,
                size_step=size_step,
                is_buy=not is_buy,
            )
            print(f"[PRECISION] SL adjusted: {original_sl} -> {stop_loss_price}", file=sys.stderr, flush=True)

        logger.info(
            f"[SDK] Placing order on {self.environment.upper()}: "
            f"{symbol} {'BUY' if is_buy else 'SELL'} size={size} price={price} "
            f"leverage={leverage}x TIF={time_in_force} TP={take_profit_price} SL={stop_loss_price}"
        )

        try:
            # Set leverage before placing order
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

            # Prepare order type with TIF
            order_type = {"limit": {"tif": time_in_force}}

            # Place main order using SDK
            logger.info(f"[SDK] Placing main order: {symbol} {'BUY' if is_buy else 'SELL'} {size}@{price} TIF={time_in_force}")

            # Prepare order parameters
            main_order_params = {
                "name": exchange_symbol,
                "is_buy": is_buy,
                "sz": size,
                "limit_px": price,
                "order_type": order_type,
                "reduce_only": reduce_only
            }

            # Add builder params only for mainnet
            builder_params = self._get_builder_params()
            if builder_params:
                main_order_params["builder"] = builder_params

            main_result = self.sdk_exchange.order(**main_order_params)

            logger.info(f"[SDK] Main order result: {main_result}")

            # Parse main order result
            order_status = main_result.get("status", "error")
            order_id = None
            filled_amount = 0
            average_price = 0
            error_msg = None

            if order_status == "ok":
                data = main_result.get("response", {}).get("data", {})
                statuses = data.get("statuses", [])

                if statuses:
                    main_status = statuses[0]

                    if "filled" in main_status:
                        filled_info = main_status["filled"]
                        order_id = str(filled_info.get("oid", ""))
                        filled_amount = float(filled_info.get("totalSz", 0))
                        average_price = float(filled_info.get("avgPx", 0))
                        status = "filled"
                    elif "resting" in main_status:
                        resting_info = main_status["resting"]
                        order_id = str(resting_info.get("oid", ""))
                        status = "resting"
                    elif "error" in main_status:
                        error_msg = main_status["error"]
                        status = "error"
                    else:
                        status = "error"
                        error_msg = f"Unknown status in response: {main_status}"
                else:
                    status = "error"
                    error_msg = "No statuses in response"
            else:
                status = "error"
                error_msg = main_result.get("response", "Unknown error")

            # Place TP/SL orders if main order succeeded and prices provided
            tp_order_id = None
            sl_order_id = None

            if status in ["filled", "resting"] and (take_profit_price or stop_loss_price):
                # Place TP order
                if take_profit_price:
                    try:
                        logger.info(f"[SDK] Placing TP order: {symbol} {'SELL' if is_buy else 'BUY'} {size}@{take_profit_price} execution={tp_execution}")

                        # Calculate TP limit price based on execution mode
                        if tp_execution == "market":
                            # Market execution: trigger as market order
                            tp_is_market = True
                            tp_limit_px = take_profit_price
                        else:  # "limit"
                            # Limit execution: attempt maker with 0.05% offset
                            tp_is_market = False
                            if is_buy:  # Long position, TP sells higher
                                tp_limit_px = take_profit_price * 1.0005
                            else:  # Short position, TP buys lower
                                tp_limit_px = take_profit_price * 0.9995

                            # Round the offset limit price
                            tp_limit_px = self._round_to_precision(
                                tp_limit_px,
                                price_decimals,
                                size_decimals,
                                is_price=True,
                                price_tick=price_tick,
                                size_step=size_step,
                                is_buy=not is_buy,
                            )
                            logger.info(f"[SDK] TP limit mode: trigger={take_profit_price}, limit={tp_limit_px} (0.05% offset)")

                        tp_order_type = {"trigger": {
                            "triggerPx": take_profit_price,
                            "isMarket": tp_is_market,
                            "tpsl": "tp"
                        }}

                        # Prepare order parameters
                        tp_order_params = {
                            "name": exchange_symbol,
                            "is_buy": not is_buy,
                            "sz": size,
                            "limit_px": tp_limit_px,
                            "order_type": tp_order_type,
                            "reduce_only": True
                        }

                        # Add builder params only for mainnet
                        builder_params = self._get_builder_params()
                        if builder_params:
                            tp_order_params["builder"] = builder_params

                        tp_result = self.sdk_exchange.order(**tp_order_params)

                        logger.info(f"[SDK] TP order result: {tp_result}")

                        if tp_result.get("status") == "ok":
                            tp_statuses = tp_result.get("response", {}).get("data", {}).get("statuses", [])
                            if tp_statuses:
                                tp_status = tp_statuses[0]
                                if "resting" in tp_status:
                                    tp_order_id = str(tp_status["resting"].get("oid", ""))
                                elif "filled" in tp_status:
                                    tp_order_id = str(tp_status["filled"].get("oid", ""))
                    except Exception as tp_err:
                        logger.error(f"[SDK] Failed to place TP order: {tp_err}", exc_info=True)

                # Place SL order
                if stop_loss_price:
                    try:
                        logger.info(f"[SDK] Placing SL order: {symbol} {'SELL' if is_buy else 'BUY'} {size}@{stop_loss_price} execution={sl_execution}")

                        # Calculate SL limit price based on execution mode
                        if sl_execution == "market":
                            # Market execution: trigger as market order
                            sl_is_market = True
                            sl_limit_px = stop_loss_price
                        else:  # "limit"
                            # Limit execution: may save fees but has execution risk
                            sl_is_market = False
                            sl_limit_px = stop_loss_price
                            logger.info(f"[SDK] SL limit mode: trigger={stop_loss_price}, limit={sl_limit_px} (no offset for stop loss)")

                        sl_order_type = {"trigger": {
                            "triggerPx": stop_loss_price,
                            "isMarket": sl_is_market,
                            "tpsl": "sl"
                        }}

                        # Prepare SL order parameters
                        sl_order_params = {
                            "name": exchange_symbol,
                            "is_buy": not is_buy,  # Opposite direction
                            "sz": size,
                            "limit_px": sl_limit_px,
                            "order_type": sl_order_type,
                            "reduce_only": True
                        }

                        # Add builder params only for mainnet
                        builder_params = self._get_builder_params()
                        if builder_params:
                            sl_order_params["builder"] = builder_params

                        sl_result = self.sdk_exchange.order(**sl_order_params)

                        logger.info(f"[SDK] SL order result: {sl_result}")

                        if sl_result.get("status") == "ok":
                            sl_statuses = sl_result.get("response", {}).get("data", {}).get("statuses", [])
                            if sl_statuses:
                                sl_status = sl_statuses[0]
                                if "resting" in sl_status:
                                    sl_order_id = str(sl_status["resting"].get("oid", ""))
                                elif "filled" in sl_status:
                                    sl_order_id = str(sl_status["filled"].get("oid", ""))
                    except Exception as sl_err:
                        logger.error(f"[SDK] Failed to place SL order: {sl_err}", exc_info=True)

            # Construct result
            order_result = {
                "status": status,
                "environment": self.environment,
                "symbol": symbol,
                "is_buy": is_buy,
                "size": size,
                "leverage": leverage,
                "order_id": order_id,
                "filled_amount": filled_amount,
                "average_price": average_price,
                "wallet_address": self.wallet_address,
                "timestamp": int(time.time() * 1000),
                # TP/SL specific fields
                "tp_order_id": tp_order_id,
                "tp_trigger_price": take_profit_price,
                "sl_order_id": sl_order_id,
                "sl_trigger_price": stop_loss_price,
            }

            if error_msg:
                order_result["error"] = error_msg

            # Update TPSL cache after successful order placement with TP/SL
            if status in ["filled", "resting"] and (take_profit_price or stop_loss_price):
                _set_cached_tpsl(self.wallet_address, symbol, take_profit_price, stop_loss_price)
                print(f"[TPSL CACHE] {symbol} - Cached new TP/SL from place_order_with_tpsl: TP={take_profit_price}, SL={stop_loss_price}", file=sys.stderr, flush=True)

            logger.info(
                f"[SDK] Order result: status={status} order_id={order_id} "
                f"filled={filled_amount}/{size} avg_price={average_price} "
                f"TP={tp_order_id} SL={sl_order_id}"
            )

            self._record_exchange_action(
                action_type="create_order_with_tpsl",
                status="success" if status != "error" else "error",
                symbol=symbol,
                side="buy" if is_buy else "sell",
                leverage=leverage,
                size=size,
                price=price,
                request_payload={
                    "symbol": exchange_symbol,
                    "is_buy": is_buy,
                    "size": size,
                    "price": price,
                    "leverage": leverage,
                    "time_in_force": time_in_force,
                    "take_profit_price": take_profit_price,
                    "stop_loss_price": stop_loss_price
                },
                response_payload=main_result,
                error_message=error_msg,
            )

            return order_result

        except Exception as e:
            logger.error(f"[SDK] Failed to place order: {e}", exc_info=True)
            self._record_exchange_action(
                action_type="create_order_with_tpsl",
                status="error",
                symbol=symbol,
                side="buy" if is_buy else "sell",
                leverage=leverage,
                size=size,
                price=price,
                request_payload={
                    "symbol": symbol,
                    "is_buy": is_buy,
                    "size": size,
                    "price": price
                },
                response_payload=None,
                error_message=str(e),
            )
            return {
                "status": "error",
                "error": str(e),
                "environment": self.environment,
                "symbol": symbol
            }
