"""Account state and open-position helpers for HyperliquidTradingClient."""

import logging
import time
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from services.exchanges.symbol_mapper import SymbolMapper
from services.hyperliquid_cache import update_account_state_cache, update_positions_cache
from services.hyperliquid_core_mixin import UNIFIED_ACCOUNT_MODES

logger = logging.getLogger(__name__)

class HyperliquidAccountMixin:
    def get_account_state(self, db: Session) -> Dict[str, Any]:
        """
        Get current account state from Hyperliquid

        Returns account equity, available balance, margin usage, etc.

        Args:
            db: Database session

        Returns:
            Dict with:
                - environment: "testnet" or "mainnet"
                - account_id: Database account ID
                - total_equity: Total account value
                - available_balance: Available for new positions
                - used_margin: Margin currently used
                - maintenance_margin: Required maintenance margin
                - margin_usage_percent: Used margin / Total equity * 100
                - withdrawal_available: Amount available for withdrawal

        Raises:
            EnvironmentMismatchError: If environment validation fails
        """
        self._validate_environment(db)

        try:
            logger.info(f"Fetching account state for account {self.account_id} on {self.environment}")

            # Use SDK Info.user_state for perp state (positions, maintenance margin)
            user_state = self._fetch_user_state_with_hip3()
            margin_summary = user_state.get('crossMarginSummary') or user_state.get('marginSummary', {})

            total_equity = float(margin_summary.get('accountValue', 0) or 0)
            used_margin = float(margin_summary.get('totalMarginUsed', 0) or 0)
            available_balance = float(user_state.get('withdrawable', 0) or 0)

            # Detect account mode via userAbstraction API
            account_mode = self._detect_account_mode()
            if account_mode in UNIFIED_ACCOUNT_MODES:
                # In Unified/Portfolio mode, clearinghouseState returns 0 for balance fields.
                # Real balance lives in spotClearinghouseState.
                try:
                    spot_balance = self._get_spot_balance()
                    total_equity = spot_balance["total_equity"]
                    available_balance = spot_balance["available_balance"]
                    used_margin = spot_balance["used_margin"]
                    print(
                        f"[UNIFIED ACCOUNT] account {self.account_id}: "
                        f"equity=${total_equity:.2f}, available=${available_balance:.2f}, "
                        f"hold=${used_margin:.2f}",
                        flush=True
                    )
                except Exception as spot_err:
                    # Fallback: if spot query fails, use perp state (may be 0)
                    print(
                        f"[UNIFIED ACCOUNT] Failed to get spot balance for account "
                        f"{self.account_id}, falling back to perp state: {spot_err}",
                        flush=True
                    )

            # Calculate margin usage percentage (round to 2 decimal places)
            margin_usage_percent = round((used_margin / total_equity * 100), 2) if total_equity > 0 else 0

            result = {
                'environment': self.environment,
                'account_id': self.account_id,
                'total_equity': round(total_equity, 2),
                'available_balance': round(available_balance, 2),
                'used_margin': round(used_margin, 2),
                'maintenance_margin': round(used_margin * 0.5, 2),  # Estimate: maintenance = 50% of initial
                'margin_usage_percent': margin_usage_percent,
                'withdrawal_available': round(available_balance, 2),
                'wallet_address': self.wallet_address,
                'account_mode': account_mode,
                'timestamp': int(time.time() * 1000)
            }

            logger.debug(f"Account state: equity=${result['total_equity']:.2f}, available=${result['available_balance']:.2f}")
            update_account_state_cache(self.account_id, result, self.environment)
            self._record_exchange_action(
                action_type="fetch_account_state",
                status="success",
                symbol=None,
                request_payload={
                    "account_id": self.account_id,
                    "environment": self.environment,
                },
                response_payload=None,
            )

            return result

        except Exception as e:
            self._record_exchange_action(
                action_type="fetch_account_state",
                status="error",
                symbol=None,
                request_payload={
                    "account_id": self.account_id,
                    "environment": self.environment,
                },
                response_payload=None,
                error_message=str(e),
            )
            logger.error(f"Failed to get account state: {e}", exc_info=True)
            raise

    def get_positions(self, db: Session, include_timing: bool = False) -> List[Dict[str, Any]]:
        """
        Get all open positions from Hyperliquid

        Args:
            db: Database session
            include_timing: If True, fetch user_fills to calculate position opened times.
                           Only needed for AI decision prompts. Default False to save API calls.

        Returns:
            List of position dicts, each with:
                - coin: Symbol name (e.g., "BTC")
                - szi: Position size (signed: positive=long, negative=short)
                - entry_px: Average entry price
                - position_value: Current position value
                - unrealized_pnl: Unrealized profit/loss
                - margin_used: Margin used for this position
                - liquidation_px: Liquidation price
                - leverage: Current leverage
                - opened_at: Timestamp when position was opened (only if include_timing=True)
                - opened_at_str: Human-readable opened time (only if include_timing=True)
                - holding_duration_seconds: How long position has been held (only if include_timing=True)
                - holding_duration_str: Human-readable holding duration (only if include_timing=True)

        Raises:
            EnvironmentMismatchError: If environment validation fails
        """
        self._validate_environment(db)

        try:
            logger.info(f"Fetching positions for account {self.account_id} on {self.environment}")

            # Use SDK Info.user_state for positions (avoids CCXT spot market loading issues)
            user_state = self._fetch_user_state_with_hip3()
            asset_positions = user_state.get('assetPositions', [])

            # Get user fills to calculate position opened times (only when needed for AI prompts)
            user_fills = []
            if include_timing:
                try:
                    user_fills = self._get_user_fills(db)
                    logger.info(f"Retrieved {len(user_fills)} user fills for position timing calculation")
                except Exception as fills_error:
                    logger.warning(f"Failed to get user fills for position timing: {fills_error}")

            # Transform SDK positions to our format
            positions = []
            for asset_pos in asset_positions:
                pos_data = asset_pos.get('position', {})
                raw_size = pos_data.get('szi')
                try:
                    position_size = float(raw_size)
                except (TypeError, ValueError):
                    position_size = 0.0

                if abs(position_size) < 1e-8:
                    continue

                coin = SymbolMapper.to_internal(pos_data.get('coin') or "", "hyperliquid")
                side = 'Long' if position_size > 0 else 'Short'

                # Calculate position timing
                opened_at = None
                opened_at_str = None
                holding_duration_seconds = None
                holding_duration_str = None

                if user_fills and coin:
                    opened_at = self._calculate_position_opened_time(coin, position_size, user_fills)
                    if opened_at:
                        from datetime import datetime, timezone
                        import time as time_module

                        utc_dt = datetime.fromtimestamp(opened_at / 1000, tz=timezone.utc)
                        opened_at_str = utc_dt.strftime('%Y-%m-%d %H:%M:%S UTC')

                        current_time_ms = int(time_module.time() * 1000)
                        holding_duration_seconds = (current_time_ms - opened_at) / 1000

                        hours = int(holding_duration_seconds // 3600)
                        minutes = int((holding_duration_seconds % 3600) // 60)
                        if hours > 0:
                            holding_duration_str = f"{hours}h {minutes}m"
                        else:
                            holding_duration_str = f"{minutes}m"

                entry_px = float(pos_data.get('entryPx', 0) or 0)
                position_value = float(pos_data.get('positionValue', 0) or 0)

                positions.append({
                    'coin': coin,
                    'szi': position_size,
                    'entry_px': entry_px,
                    'position_value': position_value,
                    'unrealized_pnl': float(pos_data.get('unrealizedPnl', 0) or 0),
                    'margin_used': float(pos_data.get('marginUsed', 0) or 0),
                    'liquidation_px': float(pos_data.get('liquidationPx') or 0),
                    'leverage': float((pos_data.get('leverage') or {}).get('value', 0)),
                    'side': side,

                    'opened_at': opened_at,
                    'opened_at_str': opened_at_str,
                    'holding_duration_seconds': holding_duration_seconds,
                    'holding_duration_str': holding_duration_str,

                    'return_on_equity': float(pos_data.get('returnOnEquity', 0) or 0),
                    'max_leverage': float(pos_data.get('maxLeverage', 0) or 0),
                    'cum_funding_all_time': float((pos_data.get('cumFunding') or {}).get('allTime', 0)),
                    'cum_funding_since_open': float((pos_data.get('cumFunding') or {}).get('sinceOpen', 0)),
                    'leverage_type': (pos_data.get('leverage') or {}).get('type'),

                    'notional': position_value,
                    'percentage': float(pos_data.get('returnOnEquity', 0) or 0) * 100,
                    'contract_size': 1.0,
                    'margin_mode': (pos_data.get('leverage') or {}).get('type', 'cross')
                })

            logger.debug(f"Found {len(positions)} open positions")
            update_positions_cache(self.account_id, positions, self.environment)
            self._record_exchange_action(
                action_type="fetch_positions",
                status="success",
                symbol=None,
                request_payload={
                    "account_id": self.account_id,
                    "environment": self.environment,
                },
                response_payload=None,
            )

            return positions

        except Exception as e:
            self._record_exchange_action(
                action_type="fetch_positions",
                status="error",
                symbol=None,
                request_payload={
                    "account_id": self.account_id,
                    "environment": self.environment,
                },
                response_payload=None,
                error_message=str(e),
            )
            logger.error(f"Failed to get positions: {e}", exc_info=True)
            raise
