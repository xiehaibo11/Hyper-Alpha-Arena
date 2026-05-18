"""Take-profit and stop-loss order helpers for HyperliquidTradingClient."""

import logging
import time
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from services.exchanges.symbol_mapper import SymbolMapper
from services.hyperliquid_tpsl_cache import _clear_cached_tpsl, _get_cached_tpsl, _set_cached_tpsl

logger = logging.getLogger(__name__)

class HyperliquidTpslMixin:
    def update_tpsl(
        self,
        db: Session,
        symbol: str,
        new_tp_price: Optional[float] = None,
        new_sl_price: Optional[float] = None,
        position_size: Optional[float] = None,
        is_long: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Update TP and/or SL orders for an existing position
        NOTE: Not currently used by any execution path (Program Trader or AI Trader).

        This method:
        1. Gets current TP/SL orders from Hyperliquid API FIRST
        2. Compares existing prices with requested prices
        3. If prices match (within 0.1%) → SKIP entirely (no duplicate orders)
        4. If prices differ → Cancel old orders and place new ones
        5. Updates in-memory cache after successful operations

        Args:
            db: Database session
            symbol: Asset symbol (e.g., "BTC")
            new_tp_price: New take profit price (None to keep current or skip)
            new_sl_price: New stop loss price (None to keep current or skip)
            position_size: Position size for new orders (required if placing new orders)
            is_long: True if position is long, False if short (required for order direction)

        Returns:
            Dict with:
                - success: Boolean indicating overall success
                - tp_updated: Boolean indicating if TP was updated
                - sl_updated: Boolean indicating if SL was updated
                - old_tp: Previous TP price (if existed)
                - old_sl: Previous SL price (if existed)
                - new_tp: New TP price (if updated)
                - new_sl: New SL price (if updated)
                - errors: List of error messages (if any)
        """
        self._validate_environment(db)

        result = {
            'success': True,
            'tp_updated': False,
            'sl_updated': False,
            'old_tp': None,
            'old_sl': None,
            'new_tp': None,
            'new_sl': None,
            'errors': [],
        }
        hip3_error = self._hip3_trade_error(symbol)
        if hip3_error:
            result['success'] = False
            result['errors'].append(hip3_error)
            return result

        exchange_symbol = self._get_exchange_symbol(symbol)
        internal_symbol = SymbolMapper.to_internal(symbol, "hyperliquid")

        # 0.1% threshold to account for rounding differences
        PRICE_CHANGE_THRESHOLD_PERCENT = 0.001  # 0.1%

        try:
            import sys

            # ============================================================
            # STEP 1: Get current TP/SL orders from Hyperliquid API FIRST
            # This is the source of truth - not the in-memory cache
            # ============================================================
            print(f"[TPSL UPDATE] {symbol} - Fetching current orders from Hyperliquid API...", file=sys.stderr, flush=True)
            logger.info(f"[TPSL UPDATE] {symbol} - Fetching current orders from Hyperliquid API")

            current_tpsl = self.get_tpsl_orders(db, symbol)
            current_tp = current_tpsl.get('tp')
            current_sl = current_tpsl.get('sl')
            all_tp_orders = current_tpsl.get('all_tp_orders', [])
            all_sl_orders = current_tpsl.get('all_sl_orders', [])

            # Extract current prices from API
            current_tp_price = current_tp.get('trigger_price') if current_tp else None
            current_sl_price = current_sl.get('trigger_price') if current_sl else None

            # Record old values
            result['old_tp'] = current_tp_price
            result['old_sl'] = current_sl_price

            print(f"[TPSL UPDATE] {symbol} - API returned: TP={current_tp_price}, SL={current_sl_price}", file=sys.stderr, flush=True)
            print(f"[TPSL UPDATE] {symbol} - Requested: TP={new_tp_price}, SL={new_sl_price}", file=sys.stderr, flush=True)
            print(f"[TPSL UPDATE] {symbol} - Found {len(all_tp_orders)} TP orders, {len(all_sl_orders)} SL orders", file=sys.stderr, flush=True)
            logger.info(f"[TPSL UPDATE] {symbol} - API: TP={current_tp_price}, SL={current_sl_price} | Requested: TP={new_tp_price}, SL={new_sl_price}")

            # ============================================================
            # STEP 2: Compare existing prices with requested prices
            # If they match within threshold → SKIP to avoid duplicates
            # ============================================================
            tp_matches_existing = False
            sl_matches_existing = False

            # Check if TP matches existing order
            if new_tp_price is not None and current_tp_price is not None and current_tp_price > 0:
                tp_diff_percent = abs(current_tp_price - new_tp_price) / current_tp_price
                if tp_diff_percent <= PRICE_CHANGE_THRESHOLD_PERCENT:
                    tp_matches_existing = True
                    print(f"[TPSL UPDATE] {symbol} TP MATCHES existing: {current_tp_price} ≈ {new_tp_price} (diff={tp_diff_percent:.4%}) - SKIP", file=sys.stderr, flush=True)
                    logger.info(f"[TPSL UPDATE] {symbol} TP matches existing order - SKIPPING to avoid duplicate")
                else:
                    print(f"[TPSL UPDATE] {symbol} TP DIFFERS: {current_tp_price} vs {new_tp_price} (diff={tp_diff_percent:.4%}) - WILL UPDATE", file=sys.stderr, flush=True)
                    logger.info(f"[TPSL UPDATE] {symbol} TP differs from existing - will update")
            elif new_tp_price is None:
                # No new TP requested, skip TP update
                tp_matches_existing = True
                print(f"[TPSL UPDATE] {symbol} No new TP requested - SKIP", file=sys.stderr, flush=True)

            # Check if SL matches existing order
            if new_sl_price is not None and current_sl_price is not None and current_sl_price > 0:
                sl_diff_percent = abs(current_sl_price - new_sl_price) / current_sl_price
                if sl_diff_percent <= PRICE_CHANGE_THRESHOLD_PERCENT:
                    sl_matches_existing = True
                    print(f"[TPSL UPDATE] {symbol} SL MATCHES existing: {current_sl_price} ≈ {new_sl_price} (diff={sl_diff_percent:.4%}) - SKIP", file=sys.stderr, flush=True)
                    logger.info(f"[TPSL UPDATE] {symbol} SL matches existing order - SKIPPING to avoid duplicate")
                else:
                    print(f"[TPSL UPDATE] {symbol} SL DIFFERS: {current_sl_price} vs {new_sl_price} (diff={sl_diff_percent:.4%}) - WILL UPDATE", file=sys.stderr, flush=True)
                    logger.info(f"[TPSL UPDATE] {symbol} SL differs from existing - will update")
            elif new_sl_price is None:
                # No new SL requested, skip SL update
                sl_matches_existing = True
                print(f"[TPSL UPDATE] {symbol} No new SL requested - SKIP", file=sys.stderr, flush=True)

            # ============================================================
            # STEP 3: If BOTH match existing orders → SKIP ENTIRELY
            # ============================================================
            if tp_matches_existing and sl_matches_existing:
                print(f"[TPSL UPDATE] {symbol} - BOTH TP and SL match existing orders - SKIPPING UPDATE ENTIRELY", file=sys.stderr, flush=True)
                logger.info(f"[TPSL UPDATE] {symbol} - Both TP and SL match existing orders, SKIPPING update entirely")

                # Update cache with current values from API
                _set_cached_tpsl(self.wallet_address, symbol, current_tp_price, current_sl_price)

                return result

            # Get position info if not provided
            if position_size is None or is_long is None:
                positions = self.get_positions(db)
                position = next(
                    (
                        p for p in positions
                        if SymbolMapper.to_internal(p.get('coin') or "", "hyperliquid") == internal_symbol
                    ),
                    None,
                )
                if position:
                    position_size = abs(position.get('szi', 0))
                    is_long = position.get('szi', 0) > 0
                else:
                    result['success'] = False
                    result['errors'].append(f"No position found for {symbol}")
                    return result

            if position_size <= 0:
                result['success'] = False
                result['errors'].append(f"Invalid position size: {position_size}")
                return result

            # Get precision for price rounding
            precision = self._get_asset_precision(symbol)
            price_tick = precision.get('price_tick')
            price_decimals = precision.get('price_decimals', 2)
            size_decimals = precision.get('size_decimals', 5)

            # ============================================================
            # STEP 4: Determine which orders need to be updated
            # At this point, we know at least one of TP or SL needs updating
            # ============================================================
            tp_needs_update = not tp_matches_existing and new_tp_price is not None
            sl_needs_update = not sl_matches_existing and new_sl_price is not None

            print(f"[TPSL UPDATE] {symbol} - Update decision: TP_update={tp_needs_update}, SL_update={sl_needs_update}", file=sys.stderr, flush=True)
            logger.info(f"[TPSL UPDATE] {symbol} - Update decision: TP_update={tp_needs_update}, SL_update={sl_needs_update}")

            # Cancel and replace TP if needed
            if tp_needs_update:
                # Cancel ALL existing TP orders first (not just the first one)
                tp_cancel_success = True
                all_tp_orders = current_tpsl.get('all_tp_orders', [])

                if all_tp_orders:
                    logger.info(f"[TPSL] Found {len(all_tp_orders)} existing TP orders to cancel for {symbol}")
                    for tp_order_to_cancel in all_tp_orders:
                        oid = tp_order_to_cancel.get('oid')
                        if oid:
                            try:
                                logger.info(f"[TPSL] Attempting to cancel TP order {oid} for {symbol}")
                                cancel_result = self.cancel_order(db, oid, symbol)
                                if cancel_result:
                                    logger.info(f"[TPSL] Successfully cancelled TP order {oid} for {symbol}")
                                else:
                                    logger.warning(f"[TPSL] Failed to cancel TP order {oid}")
                                    result['errors'].append(f"Failed to cancel TP order {oid}")
                            except Exception as cancel_err:
                                logger.warning(f"[TPSL] Exception cancelling TP order {oid}: {cancel_err}")
                                result['errors'].append(f"Failed to cancel TP {oid}: {str(cancel_err)}")

                    # Small delay to ensure exchange processes all cancellations
                    import time as time_module
                    time_module.sleep(0.5)
                elif current_tp and current_tp.get('oid'):
                    # Fallback: cancel single TP order if all_tp_orders not available
                    try:
                        logger.info(f"[TPSL] Attempting to cancel old TP order {current_tp['oid']} for {symbol}")
                        cancel_result = self.cancel_order(db, current_tp['oid'], symbol)
                        if cancel_result:
                            logger.info(f"[TPSL] Successfully cancelled old TP order {current_tp['oid']} for {symbol}")
                            import time as time_module
                            time_module.sleep(0.5)
                        else:
                            logger.warning(f"[TPSL] Failed to cancel old TP order {current_tp['oid']} - will not place new TP")
                            tp_cancel_success = False
                            result['errors'].append(f"Failed to cancel old TP order {current_tp['oid']}")
                    except Exception as cancel_err:
                        logger.warning(f"[TPSL] Exception cancelling old TP order: {cancel_err}")
                        tp_cancel_success = False
                        result['errors'].append(f"Failed to cancel old TP: {str(cancel_err)}")

                # Only place new TP order if cancellation succeeded (or there was no existing order)
                if tp_cancel_success:
                    try:
                        # Round TP price
                        rounded_tp = self._round_to_precision(
                            new_tp_price,
                            price_decimals,
                            size_decimals,
                            is_price=True,
                            price_tick=price_tick,
                            is_buy=not is_long,  # TP closes position (opposite direction)
                        )

                        tp_order_type = {"trigger": {
                            "triggerPx": rounded_tp,
                            "isMarket": False,
                            "tpsl": "tp"
                        }}

                        # Prepare order parameters
                        tp_order_params = {
                            "name": exchange_symbol,
                            "is_buy": not is_long,
                            "sz": position_size,
                            "limit_px": rounded_tp,
                            "order_type": tp_order_type,
                            "reduce_only": True
                        }

                        # Add builder params only for mainnet
                        builder_params = self._get_builder_params()
                        if builder_params:
                            tp_order_params["builder"] = builder_params

                        tp_result = self.sdk_exchange.order(**tp_order_params)

                        if tp_result.get("status") == "ok":
                            result['tp_updated'] = True
                            result['new_tp'] = rounded_tp
                            logger.info(f"[TPSL] Placed new TP order for {symbol} at ${rounded_tp}")
                        else:
                            error_msg = tp_result.get("response", "Unknown error")
                            result['errors'].append(f"Failed to place new TP: {error_msg}")
                            logger.error(f"[TPSL] Failed to place new TP order: {error_msg}")

                    except Exception as tp_err:
                        result['errors'].append(f"TP order error: {str(tp_err)}")
                        logger.error(f"[TPSL] Error placing TP order: {tp_err}", exc_info=True)

            # Cancel and replace SL if needed
            if sl_needs_update:
                # Cancel ALL existing SL orders first (not just the first one)
                sl_cancel_success = True
                all_sl_orders = current_tpsl.get('all_sl_orders', [])

                if all_sl_orders:
                    logger.info(f"[TPSL] Found {len(all_sl_orders)} existing SL orders to cancel for {symbol}")
                    for sl_order_to_cancel in all_sl_orders:
                        oid = sl_order_to_cancel.get('oid')
                        if oid:
                            try:
                                logger.info(f"[TPSL] Attempting to cancel SL order {oid} for {symbol}")
                                cancel_result = self.cancel_order(db, oid, symbol)
                                if cancel_result:
                                    logger.info(f"[TPSL] Successfully cancelled SL order {oid} for {symbol}")
                                else:
                                    logger.warning(f"[TPSL] Failed to cancel SL order {oid}")
                                    result['errors'].append(f"Failed to cancel SL order {oid}")
                            except Exception as cancel_err:
                                logger.warning(f"[TPSL] Exception cancelling SL order {oid}: {cancel_err}")
                                result['errors'].append(f"Failed to cancel SL {oid}: {str(cancel_err)}")

                    # Small delay to ensure exchange processes all cancellations
                    import time as time_module
                    time_module.sleep(0.5)
                elif current_sl and current_sl.get('oid'):
                    # Fallback: cancel single SL order if all_sl_orders not available
                    try:
                        logger.info(f"[TPSL] Attempting to cancel old SL order {current_sl['oid']} for {symbol}")
                        cancel_result = self.cancel_order(db, current_sl['oid'], symbol)
                        if cancel_result:
                            logger.info(f"[TPSL] Successfully cancelled old SL order {current_sl['oid']} for {symbol}")
                            import time as time_module
                            time_module.sleep(0.5)
                        else:
                            logger.warning(f"[TPSL] Failed to cancel old SL order {current_sl['oid']} - will not place new SL")
                            sl_cancel_success = False
                            result['errors'].append(f"Failed to cancel old SL order {current_sl['oid']}")
                    except Exception as cancel_err:
                        logger.warning(f"[TPSL] Exception cancelling old SL order: {cancel_err}")
                        sl_cancel_success = False
                        result['errors'].append(f"Failed to cancel old SL: {str(cancel_err)}")

                # Only place new SL order if cancellation succeeded (or there was no existing order)
                if sl_cancel_success:
                    try:
                        # Round SL price
                        rounded_sl = self._round_to_precision(
                            new_sl_price,
                            price_decimals,
                            size_decimals,
                            is_price=True,
                            price_tick=price_tick,
                            is_buy=not is_long,  # SL closes position (opposite direction)
                        )

                        sl_order_type = {"trigger": {
                            "triggerPx": rounded_sl,
                            "isMarket": False,
                            "tpsl": "sl"
                        }}

                        # Prepare order parameters
                        sl_order_params = {
                            "name": exchange_symbol,
                            "is_buy": not is_long,
                            "sz": position_size,
                            "limit_px": rounded_sl,
                            "order_type": sl_order_type,
                            "reduce_only": True
                        }

                        # Add builder params only for mainnet
                        builder_params = self._get_builder_params()
                        if builder_params:
                            sl_order_params["builder"] = builder_params

                        sl_result = self.sdk_exchange.order(**sl_order_params)

                        if sl_result.get("status") == "ok":
                            result['sl_updated'] = True
                            result['new_sl'] = rounded_sl
                            logger.info(f"[TPSL] Placed new SL order for {symbol} at ${rounded_sl}")
                        else:
                            error_msg = sl_result.get("response", "Unknown error")
                            result['errors'].append(f"Failed to place new SL: {error_msg}")
                            logger.error(f"[TPSL] Failed to place new SL order: {error_msg}")

                    except Exception as sl_err:
                        result['errors'].append(f"SL order error: {str(sl_err)}")
                        logger.error(f"[TPSL] Error placing SL order: {sl_err}", exc_info=True)

            # Set overall success based on errors
            if result['errors']:
                result['success'] = False

            # ============================================================
            # STEP 5: Update cache after successful operations
            # ============================================================
            # Determine final TP/SL prices to cache (use new prices if updated, otherwise keep old)
            final_tp_price = result['new_tp'] if result['tp_updated'] else result['old_tp']
            final_sl_price = result['new_sl'] if result['sl_updated'] else result['old_sl']

            # Update cache with current state
            if final_tp_price is not None or final_sl_price is not None:
                _set_cached_tpsl(self.wallet_address, symbol, final_tp_price, final_sl_price)
                print(f"[TPSL CACHE] {symbol} - Updated cache after operation: TP={final_tp_price}, SL={final_sl_price}", file=sys.stderr, flush=True)

            # Log summary
            logger.info(
                f"[TPSL] Update complete for {symbol}: "
                f"TP {result['old_tp']}→{result['new_tp']} (updated={result['tp_updated']}), "
                f"SL {result['old_sl']}→{result['new_sl']} (updated={result['sl_updated']})"
            )

            self._record_exchange_action(
                action_type="update_tpsl",
                status="success" if result['success'] else "partial",
                symbol=symbol,
                request_payload={
                    "symbol": exchange_symbol,
                    "new_tp_price": new_tp_price,
                    "new_sl_price": new_sl_price,
                    "position_size": position_size,
                    "is_long": is_long,
                },
                response_payload=result,
                error_message="; ".join(result['errors']) if result['errors'] else None,
            )

            return result

        except Exception as e:
            result['success'] = False
            result['errors'].append(str(e))
            self._record_exchange_action(
                action_type="update_tpsl",
                status="error",
                symbol=symbol,
                request_payload={
                    "symbol": symbol,
                    "new_tp_price": new_tp_price,
                    "new_sl_price": new_sl_price,
                },
                error_message=str(e),
            )
            logger.error(f"[TPSL] Failed to update TP/SL for {symbol}: {e}", exc_info=True)
            return result
