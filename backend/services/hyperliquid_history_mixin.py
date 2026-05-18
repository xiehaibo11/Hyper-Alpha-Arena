"""Fill, historical-order, and trade-stat helpers for HyperliquidTradingClient."""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from services.exchanges.symbol_mapper import SymbolMapper

logger = logging.getLogger(__name__)

class HyperliquidHistoryMixin:
    def _get_user_fills(self, db: Session) -> List[Dict[str, Any]]:
        """
        Get all user fills (trade executions) from Hyperliquid SDK

        This method uses Hyperliquid SDK's Info.user_fills() to retrieve
        ALL historical trade executions for this wallet address.

        Args:
            db: Database session (for environment validation)

        Returns:
            List of fill dicts with fields:
                - coin: Symbol name
                - side: "A" (ask/sell) or "B" (bid/buy)
                - px: Execution price
                - sz: Size filled
                - time: Execution timestamp (milliseconds)
                - startPosition: Position before this fill
                - dir: Direction ("Open Long", "Close Long", etc.)
                - closedPnl: Realized PnL if position closed
                - oid: Order ID

        Raises:
            EnvironmentMismatchError: If environment validation fails
        """
        self._validate_environment(db)

        try:
            logger.info(f"Fetching user fills for wallet {self.query_address} on {self.environment}")

            # Use SDK Info to get all user fills
            # Must use query_address (master wallet) instead of wallet_address (agent key)
            # because fills are associated with the master wallet on Hyperliquid
            fills = self.sdk_info.user_fills(self.query_address)
            for fill in fills:
                if isinstance(fill, dict) and fill.get('coin'):
                    fill['coin'] = SymbolMapper.to_internal(fill.get('coin'), "hyperliquid")

            logger.debug(f"Retrieved {len(fills)} fills for wallet {self.query_address}")

            self._record_exchange_action(
                action_type="fetch_user_fills",
                status="success",
                symbol=None,
                request_payload={
                    "account_id": self.account_id,
                    "wallet_address": self.wallet_address,
                    "environment": self.environment,
                },
                response_payload=None,
            )

            return fills

        except Exception as e:
            self._record_exchange_action(
                action_type="fetch_user_fills",
                status="error",
                symbol=None,
                request_payload={
                    "account_id": self.account_id,
                    "wallet_address": self.wallet_address,
                    "environment": self.environment,
                },
                response_payload=None,
                error_message=str(e),
            )
            logger.error(f"Failed to get user fills: {e}", exc_info=True)
            raise

    def query_order_by_oid(self, db: Session, order_id: int) -> Optional[Dict[str, Any]]:
        """
        Query order details by order ID from Hyperliquid API.

        Args:
            db: Database session (for environment validation)
            order_id: The order ID to query

        Returns:
            Order dict with status and statusTimestamp if found, None otherwise
        """
        self._validate_environment(db)

        try:
            logger.debug(f"Querying order {order_id} for wallet {self.query_address}")
            result = self.sdk_info.query_order_by_oid(self.query_address, order_id)
            return result
        except Exception as e:
            logger.warning(f"Failed to query order {order_id}: {e}")
            return None

    def get_order_trigger_time(self, db: Session, order_id: int) -> Optional[datetime]:
        """
        Get the actual trigger/fill time for an order.

        Args:
            db: Database session
            order_id: The order ID to query

        Returns:
            datetime of when the order was filled/triggered, or None if not available
        """
        result = self.query_order_by_oid(db, order_id)
        if not result:
            return None

        # Extract statusTimestamp from the response
        # Response format: {'status': 'order', 'order': {'order': {...}, 'status': 'filled', 'statusTimestamp': 1767580190625}}
        order_data = result.get("order", {})
        status_timestamp = order_data.get("statusTimestamp")

        if status_timestamp:
            try:
                # statusTimestamp is in milliseconds, return UTC without timezone info
                # to match database datetime format (all stored as UTC without tzinfo)
                return datetime.utcfromtimestamp(status_timestamp / 1000)
            except Exception as e:
                logger.warning(f"Failed to parse statusTimestamp {status_timestamp}: {e}")
                return None

        return None

    def _get_historical_orders(self, db: Session) -> List[Dict[str, Any]]:
        """
        Get historical orders from Hyperliquid SDK

        This method uses Hyperliquid SDK's Info.historical_orders() to retrieve
        up to 2000 most recent orders for this wallet address.

        Args:
            db: Database session (for environment validation)

        Returns:
            List of order dicts with status, fills, and execution details

        Raises:
            EnvironmentMismatchError: If environment validation fails
        """
        self._validate_environment(db)

        try:
            logger.info(f"Fetching historical orders for wallet {self.query_address} on {self.environment}")

            # Use SDK Info to get historical orders (up to 2000 most recent)
            # Must use query_address (master wallet) for agent_key mode
            orders = self.sdk_info.historical_orders(self.query_address)

            logger.debug(f"Retrieved {len(orders)} historical orders for wallet {self.query_address}")

            self._record_exchange_action(
                action_type="fetch_historical_orders",
                status="success",
                symbol=None,
                request_payload={
                    "account_id": self.account_id,
                    "wallet_address": self.wallet_address,
                    "environment": self.environment,
                },
                response_payload=None,
            )

            return orders

        except Exception as e:
            self._record_exchange_action(
                action_type="fetch_historical_orders",
                status="error",
                symbol=None,
                request_payload={
                    "account_id": self.account_id,
                    "wallet_address": self.wallet_address,
                    "environment": self.environment,
                },
                response_payload=None,
                error_message=str(e),
            )
            logger.error(f"Failed to get historical orders: {e}", exc_info=True)
            raise

    def _calculate_position_opened_time(self, symbol: str, current_position_size: float, fills: List[Dict[str, Any]]) -> Optional[int]:
        """
        Calculate when a position was opened based on user fills

        This method walks backwards through fills starting from the current position,
        subtracting each fill's effect until we reach the point where the position
        was first opened (when going back further would cross zero or change direction).

        Args:
            symbol: Asset symbol (e.g., "BTC")
            current_position_size: Current position size (signed: positive=long, negative=short)
            fills: List of all user fills (from _get_user_fills)

        Returns:
            Timestamp in milliseconds when position was first opened,
            or None if no fills found for this symbol
        """
        if not fills or abs(current_position_size) < 1e-8:
            return None

        # Filter fills for this symbol and sort by time (newest first)
        symbol_fills = [f for f in fills if f.get('coin') == symbol]
        symbol_fills.sort(key=lambda x: x.get('time', 0), reverse=True)

        if not symbol_fills:
            return None

        # Start from current position and walk backwards
        # Subtract each fill's effect to find when position started
        position_tracker = current_position_size
        earliest_time = None

        for fill in symbol_fills:
            sz = float(fill.get('sz', 0))
            side = fill.get('side', '')

            # Calculate what the position was BEFORE this fill
            # side "B" = buy (adds to position), "A" = sell (reduces position)
            if side == "B":
                position_before = position_tracker - sz
            elif side == "A":
                position_before = position_tracker + sz
            else:
                continue

            # Check if going back past this fill would cross zero or change direction
            # If so, this fill is where the current position started
            if abs(position_before) < 1e-8:
                # Position was zero before this fill - this is the opening fill
                earliest_time = fill.get('time')
                break
            elif (position_tracker > 0 and position_before < 0) or (position_tracker < 0 and position_before > 0):
                # Position changed direction - this fill opened the current position
                earliest_time = fill.get('time')
                break
            else:
                # This fill is part of the current position, keep going back
                earliest_time = fill.get('time')
                position_tracker = position_before

        return earliest_time

    def get_recent_closed_trades(self, db: Session, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Get recent closed trades summary from historical orders

        This method analyzes historical orders to find recently closed positions
        and returns a summary with:
        - Symbol
        - Entry/exit time and prices
        - Holding duration
        - Realized PnL
        - Direction (long/short)

        Args:
            db: Database session (for environment validation)
            limit: Maximum number of closed trades to return (default 5)

        Returns:
            List of closed trade summaries, sorted by close time (most recent first)

        Raises:
            EnvironmentMismatchError: If environment validation fails
        """
        self._validate_environment(db)

        try:
            # Get user fills which contain closedPnl information
            fills = self._get_user_fills(db)

            # Filter for fills that closed positions (have closedPnl)
            closed_fills = []
            for fill in fills:
                closed_pnl = fill.get('closedPnl')
                if closed_pnl and closed_pnl != '0.0':
                    closed_fills.append(fill)

            # Sort by time (newest first) and limit
            closed_fills.sort(key=lambda x: x.get('time', 0), reverse=True)
            closed_fills = closed_fills[:limit]

            # Build trade summaries
            trades = []
            for fill in closed_fills:
                from datetime import datetime, timezone

                close_time_ms = fill.get('time', 0)
                # Use UTC time (consistent with session context display)
                utc_dt = datetime.fromtimestamp(close_time_ms / 1000, tz=timezone.utc)
                close_time = utc_dt.strftime('%Y-%m-%d %H:%M:%S UTC')

                trade = {
                    'symbol': fill.get('coin'),
                    'side': 'Long' if fill.get('side') == 'A' else 'Short',  # Closing long = selling (A)
                    'close_price': float(fill.get('px', 0)),
                    'size': float(fill.get('sz', 0)),
                    'close_time': close_time,
                    'close_timestamp': close_time_ms,
                    'realized_pnl': float(fill.get('closedPnl', 0)),
                    'direction': fill.get('dir', ''),
                }

                trades.append(trade)

            logger.info(f"Found {len(trades)} recent closed trades")
            return trades

        except Exception as e:
            logger.error(f"Failed to get recent closed trades: {e}", exc_info=True)
            return []

    def get_trading_stats(self, db: Session) -> Dict[str, Any]:
        """
        Get trading statistics including win rate, profit factor, etc.

        Uses official Hyperliquid portfolio API for accurate all-time PNL
        (includes fees and funding), combined with fills data for win/loss stats.

        Args:
            db: Database session (for environment validation)

        Returns:
            Dict with trading statistics

        Raises:
            EnvironmentMismatchError: If environment validation fails
        """
        self._validate_environment(db)

        try:
            # Get official portfolio data for accurate PNL (includes fees/funding)
            portfolio_pnl = 0.0
            portfolio_volume = 0.0
            try:
                portfolio_data = self.sdk_info.portfolio(self.query_address)
                # Find allTime or perpAllTime data
                for item in portfolio_data:
                    if item[0] == 'allTime':
                        pnl_history = item[1].get('pnlHistory', [])
                        if pnl_history:
                            portfolio_pnl = float(pnl_history[-1][1])
                        portfolio_volume = float(item[1].get('vlm', 0))
                        break
            except Exception as e:
                logger.warning(f"Failed to get portfolio data: {e}")

            # Get fills for win/loss statistics
            fills = self._get_user_fills(db)
            closed_fills = []
            for fill in fills:
                closed_pnl = fill.get('closedPnl')
                if closed_pnl and closed_pnl != '0.0':
                    closed_fills.append({
                        'pnl': float(closed_pnl),
                        'time': fill.get('time', 0),
                        'symbol': fill.get('coin'),
                    })

            if not closed_fills:
                return {
                    'total_trades': 0,
                    'wins': 0,
                    'losses': 0,
                    'win_rate': 0.0,
                    'total_pnl': round(portfolio_pnl, 2),
                    'volume': round(portfolio_volume, 2),
                    'avg_win': 0.0,
                    'avg_loss': 0.0,
                    'profit_factor': 0.0,
                    'gross_profit': 0.0,
                    'gross_loss': 0.0,
                }

            # Calculate win/loss statistics from fills
            wins = [t for t in closed_fills if t['pnl'] > 0]
            losses = [t for t in closed_fills if t['pnl'] < 0]

            total_trades = len(closed_fills)
            win_count = len(wins)
            loss_count = len(losses)

            win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0.0
            gross_profit = sum(t['pnl'] for t in wins) if wins else 0.0
            gross_loss = abs(sum(t['pnl'] for t in losses)) if losses else 0.0
            avg_win = gross_profit / win_count if win_count > 0 else 0.0
            avg_loss = -gross_loss / loss_count if loss_count > 0 else 0.0
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

            stats = {
                'total_trades': total_trades,
                'wins': win_count,
                'losses': loss_count,
                'win_rate': round(win_rate, 1),
                'total_pnl': round(portfolio_pnl, 2),  # Official PNL (includes fees)
                'volume': round(portfolio_volume, 2),
                'avg_win': round(avg_win, 2),
                'avg_loss': round(avg_loss, 2),
                'profit_factor': round(profit_factor, 2),
                'gross_profit': round(gross_profit, 2),
                'gross_loss': round(gross_loss, 2),
            }

            logger.info(f"Trading stats: {win_count}W/{loss_count}L, PNL=${portfolio_pnl:.2f}")
            return stats

        except Exception as e:
            logger.error(f"Failed to get trading stats: {e}", exc_info=True)
            return {
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'volume': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0,
                'gross_profit': 0.0,
                'gross_loss': 0.0,
                'error': str(e),
            }
