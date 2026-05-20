"""Binance account, balance, and position helpers."""

import logging
import time
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BinanceAccountMixin:
    HEDGE_MODE_UNSUPPORTED_MESSAGE = (
        "Binance Hedge Mode is active. Orders will be sent with LONG/SHORT "
        "positionSide parameters."
    )

    # ==================== Account Methods ====================

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        Get current price ticker for a symbol.

        Args:
            symbol: Trading pair (e.g., 'BTC')

        Returns:
            Dict with price info:
            - symbol: Trading pair
            - price: Current price
        """
        binance_symbol = self._to_binance_symbol(symbol)
        result = self._request("GET", "/fapi/v1/ticker/price", {"symbol": binance_symbol})
        return {
            "symbol": symbol,
            "price": float(result.get("price", 0)),
            "binance_symbol": binance_symbol
        }

    def get_account(self) -> Dict[str, Any]:
        """
        Get full account information including balances and positions.

        Returns:
            Account info dict with assets and positions arrays
        """
        return self._request("GET", "/fapi/v3/account", signed=True)

    def get_position_mode(self) -> Dict[str, Any]:
        """
        Get Binance Futures position mode.

        Binance returns dualSidePosition=true for Hedge Mode and false for
        One-way Mode. The trading engine currently models one signed position
        per symbol, so Hedge Mode is intentionally rejected before order entry.
        """
        now = time.time()
        cached = getattr(self, "_position_mode_cache", None)
        cached_at = getattr(self, "_position_mode_timestamp", 0)
        ttl = getattr(self, "_position_mode_ttl", 30)
        if cached is not None and (now - cached_at) < ttl:
            return cached

        result = self._request("GET", "/fapi/v1/positionSide/dual", signed=True)
        raw_dual = result.get("dualSidePosition", False)
        dual_side_position = str(raw_dual).lower() == "true" if isinstance(raw_dual, str) else bool(raw_dual)
        mode = "hedge" if dual_side_position else "one_way"

        parsed = {
            "dual_side_position": dual_side_position,
            "mode": mode,
            "is_one_way": not dual_side_position,
            "raw_response": result,
        }
        self._position_mode_cache = parsed
        self._position_mode_timestamp = now
        return parsed

    def ensure_one_way_position_mode(self) -> Dict[str, Any]:
        """Backward-compatible mode check; both One-way and Hedge are supported."""
        return self.get_position_mode()

    def resolve_order_position_side(
        self,
        side: str,
        reduce_only: bool = False,
        position_side: Optional[str] = None,
    ) -> Optional[str]:
        """Return Binance positionSide for Hedge Mode, otherwise None."""
        mode = self.get_position_mode()
        if not mode.get("dual_side_position"):
            return None

        if position_side:
            normalized = position_side.upper()
            if normalized not in {"LONG", "SHORT"}:
                raise ValueError("position_side must be LONG or SHORT in Binance Hedge Mode")
            return normalized

        side_upper = side.upper()
        if side_upper not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if reduce_only:
            return "SHORT" if side_upper == "BUY" else "LONG"
        return "LONG" if side_upper == "BUY" else "SHORT"

    def get_balance(self) -> Dict[str, Any]:
        """
        Get account balance summary.

        Returns:
            Dict with balance fields mapped to unified format:
            - total_equity: Total wallet balance + unrealized PnL
            - available_balance: Available for trading
            - used_margin: Total initial margin
            - maintenance_margin: Total maintenance margin
            - unrealized_pnl: Total unrealized profit
            - margin_usage_percent: Margin usage percentage
        """
        account = self.get_account()

        total_equity = float(account.get("totalMarginBalance", 0))
        used_margin = float(account.get("totalInitialMargin", 0))
        margin_usage_percent = (used_margin / total_equity * 100) if total_equity > 0 else 0.0

        return {
            "environment": self.environment,
            "total_equity": total_equity,
            "available_balance": float(account.get("availableBalance", 0)),
            "used_margin": used_margin,
            "maintenance_margin": float(account.get("totalMaintMargin", 0)),
            "unrealized_pnl": float(account.get("totalUnrealizedProfit", 0)),
            "total_wallet_balance": float(account.get("totalWalletBalance", 0)),
            "margin_usage_percent": round(margin_usage_percent, 1),
            "timestamp": self._get_timestamp(),
            "source": "live"
        }

    def get_positions(self, db=None, include_timing: bool = False) -> List[Dict[str, Any]]:
        """
        Get all open positions with unified field format (compatible with Hyperliquid).

        Uses /fapi/v3/positionRisk endpoint which provides complete position data
        including entryPrice, markPrice, and liquidationPrice.

        Args:
            db: Database session (unused, for Hyperliquid API compatibility)
            include_timing: Include position timing info (unused, for compatibility)

        Returns:
            List of position dicts with unified format matching Hyperliquid:
            - coin: Symbol without suffix (e.g., "BTC")
            - szi: Signed size (positive=long, negative=short)
            - entry_px: Average entry price
            - position_value: Notional value
            - unrealized_pnl: Position PnL
            - leverage: Position leverage (calculated from notional/margin)
            - liquidation_px: Estimated liquidation price
            - margin_used: Initial margin
            - leverage_type: "cross" or "isolated"
        """
        # Use positionRisk endpoint for complete position data
        position_risk = self._request("GET", "/fapi/v3/positionRisk", signed=True)
        positions = []
        user_fills: List[Dict[str, Any]] = []

        if include_timing:
            try:
                user_fills = self.get_user_fills(limit=1000)
            except Exception as e:
                logger.warning(f"[BINANCE] Failed to get user fills for position timing: {e}")

        # Build max leverage map from leverageBracket API (one call for all symbols)
        max_leverage_map = {}
        open_positions = [p for p in position_risk if float(p.get("positionAmt", 0)) != 0]
        if open_positions:
            try:
                brackets = self._request("GET", "/fapi/v1/leverageBracket", signed=True)
                for item in brackets:
                    symbol = item.get("symbol", "")
                    bracket_list = item.get("brackets", [])
                    if bracket_list:
                        # First bracket has the highest allowed leverage
                        max_lev = bracket_list[0].get("initialLeverage", 0)
                        # Store with USDT suffix removed
                        clean_symbol = symbol[:-4] if symbol.endswith("USDT") else symbol
                        max_leverage_map[clean_symbol] = max_lev
            except Exception as e:
                logger.warning(f"[BINANCE] Failed to fetch leverage brackets: {e}")

        for pos in position_risk:
            position_amt = float(pos.get("positionAmt", 0))
            if position_amt == 0:
                continue  # Skip empty positions

            symbol = pos.get("symbol", "")
            # Remove USDT suffix for internal format
            if symbol.endswith("USDT"):
                symbol = symbol[:-4]

            entry_price = float(pos.get("entryPrice", 0))
            notional = abs(float(pos.get("notional", 0)))
            initial_margin = float(pos.get("initialMargin", 0))

            # Calculate leverage from notional / initialMargin
            leverage = 1
            if initial_margin > 0:
                leverage = round(notional / initial_margin)

            # Determine margin type from isolatedMargin field
            isolated_margin = float(pos.get("isolatedMargin", 0))
            leverage_type = "isolated" if isolated_margin > 0 else "cross"

            # Determine side from position amount (positive=Long, negative=Short)
            side = "Long" if position_amt > 0 else "Short"

            opened_at = None
            opened_at_str = None
            holding_duration_seconds = None
            holding_duration_str = None

            if include_timing and user_fills and symbol:
                opened_at = self._calculate_position_opened_time(symbol, position_amt, user_fills)
                if opened_at:
                    utc_dt = datetime.utcfromtimestamp(opened_at / 1000)
                    opened_at_str = utc_dt.strftime('%Y-%m-%d %H:%M:%S UTC')

                    current_time_ms = self._get_timestamp()
                    holding_duration_seconds = (current_time_ms - opened_at) / 1000
                    hours = int(holding_duration_seconds // 3600)
                    minutes = int((holding_duration_seconds % 3600) // 60)
                    if hours > 0:
                        holding_duration_str = f"{hours}h {minutes}m"
                    else:
                        holding_duration_str = f"{minutes}m"

            positions.append({
                # Unified fields (Hyperliquid-compatible)
                "coin": symbol,
                "szi": position_amt,
                "entry_px": entry_price,
                "position_value": notional,
                "unrealized_pnl": float(pos.get("unRealizedProfit", 0)),
                "leverage": leverage,
                "liquidation_px": float(pos.get("liquidationPrice", 0)),
                "margin_used": initial_margin,
                "leverage_type": leverage_type,
                "side": side,  # Added: position direction for compatibility
                # Additional Binance-specific fields (for reference)
                "symbol": symbol,  # Alias for coin
                "mark_price": float(pos.get("markPrice", 0)),
                "maint_margin": float(pos.get("maintMargin", 0)),
                "position_side": pos.get("positionSide", "BOTH"),
                "max_leverage": max_leverage_map.get(symbol, 0),
                "opened_at": opened_at,
                "opened_at_str": opened_at_str,
                "holding_duration_seconds": holding_duration_seconds,
                "holding_duration_str": holding_duration_str,
            })

        return positions

    def _calculate_position_opened_time(
        self,
        symbol: str,
        current_position_size: float,
        fills: List[Dict[str, Any]]
    ) -> Optional[int]:
        """
        Calculate when the current position was opened based on user fills.

        Mirrors Hyperliquid's timing logic so Program Trader gets the same
        timing semantics across exchanges.
        """
        if not fills or abs(current_position_size) < 1e-8:
            return None

        symbol_fills = [f for f in fills if f.get("coin") == symbol]
        symbol_fills.sort(key=lambda x: x.get("time", 0), reverse=True)

        if not symbol_fills:
            return None

        position_tracker = current_position_size
        earliest_time = None

        for fill in symbol_fills:
            sz = float(fill.get("sz", 0) or 0)
            side = fill.get("side", "")

            if side == "B":
                position_before = position_tracker - sz
            elif side == "A":
                position_before = position_tracker + sz
            else:
                continue

            if abs(position_before) < 1e-8:
                earliest_time = fill.get("time")
                break
            elif (position_tracker > 0 and position_before < 0) or (position_tracker < 0 and position_before > 0):
                earliest_time = fill.get("time")
                break
            else:
                earliest_time = fill.get("time")
                position_tracker = position_before

        return earliest_time
