"""Order status, connection test, and rate-limit helpers for HyperliquidTradingClient."""

import logging
from typing import Any, Dict

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

class HyperliquidConnectionMixin:
    def get_order_status(self, db: Session, order_id: int) -> Dict[str, Any]:
        """
        Query order status

        Args:
            db: Database session
            order_id: Hyperliquid order ID (oid)

        Returns:
            Order status dict

        Raises:
            EnvironmentMismatchError: If environment validation fails
        """
        self._validate_environment(db)

        try:
            logger.debug(f"Querying order status for {order_id} on {self.environment}")

            # TODO: Implement actual order status query

            return {
                'order_id': order_id,
                'status': 'unknown',
                'environment': self.environment
            }

        except Exception as e:
            logger.error(f"Failed to get order status: {e}")
            raise

    def test_connection(self, db: Session) -> Dict[str, Any]:
        """
        Test API connection and authentication.

        Args:
            db: Database session

        Returns:
            Connection test result
        """
        try:
            self._validate_environment(db)
            account_state = self.get_account_state(db)

            return {
                'success': True,
                'connected': True,
                'environment': self.environment,
                'address': self.wallet_address,
                'account_id': self.account_id,
                'balance': account_state.get('available_balance'),
                'total_equity': account_state.get('total_equity'),
                'account_mode': account_state.get('account_mode', 'standard'),
                'api_url': self.api_url
            }
        except Exception as e:
            return {
                'success': False,
                'connected': False,
                'environment': self.environment,
                'message': str(e),
                'error': str(e)
            }

    def get_user_rate_limit(self, db: Session) -> Dict[str, Any]:
        """
        Query user's API request rate limit status

        This endpoint queries Hyperliquid's userRateLimit to check the address-based
        request quota. Users get a base quota of 10,000 requests, plus 1 additional
        request per USDC of cumulative trading volume.

        Args:
            db: Database session

        Returns:
            Dict containing:
                - cumVlm: Cumulative trading volume (USDC)
                - nRequestsUsed: Number of requests already consumed
                - nRequestsCap: Maximum requests allowed (10000 + cumVlm)
                - nRequestsSurplus: Reserved quota surplus (usually 0)
                - remaining: Calculated remaining requests (cap - used)
                - usagePercent: Usage percentage (0-100+)
                - isOverLimit: Boolean indicating if quota is exceeded

        Raises:
            EnvironmentMismatchError: If environment validation fails
            Exception: If API request fails
        """
        self._validate_environment(db)

        try:
            import requests

            # Select API endpoint based on environment
            info_url = f"{self.api_url}/info"

            # Construct payload for userRateLimit query
            payload = {
                "type": "userRateLimit",
                "user": self.query_address
            }

            logger.info(f"Querying rate limit for {self.query_address} on {self.environment}")

            # Call Hyperliquid Info API (disable proxy to avoid connection issues)
            proxies = {
                'http': None,
                'https': None
            }
            response = requests.post(info_url, json=payload, timeout=10, proxies=proxies)
            response.raise_for_status()

            data = response.json()

            # Parse response fields
            cum_vlm = float(data.get('cumVlm', 0))
            n_requests_used = int(data.get('nRequestsUsed', 0))
            n_requests_cap = int(data.get('nRequestsCap', 10000))
            n_requests_surplus = int(data.get('nRequestsSurplus', 0))

            # Calculate additional metrics
            remaining = n_requests_cap - n_requests_used
            usage_percent = (n_requests_used / n_requests_cap * 100) if n_requests_cap > 0 else 0
            is_over_limit = n_requests_used > n_requests_cap

            result = {
                'cumVlm': cum_vlm,
                'nRequestsUsed': n_requests_used,
                'nRequestsCap': n_requests_cap,
                'nRequestsSurplus': n_requests_surplus,
                'remaining': remaining,
                'usagePercent': round(usage_percent, 2),
                'isOverLimit': is_over_limit,
                'environment': self.environment,
                'walletAddress': self.wallet_address
            }

            logger.info(
                f"Rate limit status: {n_requests_used}/{n_requests_cap} requests "
                f"({usage_percent:.1f}%), Volume: ${cum_vlm:.2f}"
            )

            if is_over_limit:
                shortage = n_requests_used - n_requests_cap
                logger.warning(
                    f"⚠️ Rate limit EXCEEDED by {shortage} requests! "
                    f"Need to trade ${shortage} USDC to free up quota."
                )

            return result

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to query rate limit: {e}")
            raise Exception(f"Rate limit query failed: {str(e)}")
        except Exception as e:
            logger.error(f"Error processing rate limit data: {e}")
            raise
