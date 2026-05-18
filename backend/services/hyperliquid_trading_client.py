"""
Hyperliquid Trading Client - Real trading execution with environment isolation

This module provides authenticated trading client for Hyperliquid perpetual contracts.
Key features:
- Testnet/Mainnet environment isolation
- Strict environment validation on every API call
- Account state and position management
- Order placement with leverage support
"""
import logging
import time
import json
import math
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING, InvalidOperation, getcontext
from eth_account import Account as EthAccount
from eth_account.messages import encode_defunct, _hash_eip191_message
from eth_utils import keccak

# Try different function names across eth_account versions
encode_typed_data_func = None
try:
    # eth_account >= 0.6.0
    from eth_account.messages import encode_typed_data
    encode_typed_data_func = encode_typed_data
except ImportError:
    try:
        # Some versions use encode_structured_data
        from eth_account.messages import encode_structured_data
        encode_typed_data_func = encode_structured_data
    except ImportError:
        encode_typed_data_func = None

import ccxt
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import Account, HyperliquidExchangeAction
from services.hyperliquid_cache import (
    update_account_state_cache,
    update_positions_cache,
)
from services.exchanges.symbol_mapper import SymbolMapper
from services.hyperliquid_account_mixin import HyperliquidAccountMixin
from services.hyperliquid_connection_mixin import HyperliquidConnectionMixin
from services.hyperliquid_core_mixin import HyperliquidCoreMixin, UNIFIED_ACCOUNT_MODES
from services.hyperliquid_history_mixin import HyperliquidHistoryMixin
from services.hyperliquid_open_orders_mixin import HyperliquidOpenOrdersMixin
from services.hyperliquid_order_execution_mixin import HyperliquidOrderExecutionMixin
from services.hyperliquid_order_management_mixin import HyperliquidOrderManagementMixin
from services.hyperliquid_precision_mixin import HyperliquidPrecisionMixin
from services.hyperliquid_tpsl_execution_mixin import HyperliquidTpslExecutionMixin
from services.hyperliquid_tpsl_mixin import HyperliquidTpslMixin
from services.hyperliquid_tpsl_query_mixin import HyperliquidTpslQueryMixin

getcontext().prec = 28

logger = logging.getLogger(__name__)

# ============================================================================
# TPSL ORDER CACHE - In-memory cache to prevent duplicate TP/SL orders
# ============================================================================
# This cache tracks TP/SL orders that have been placed to avoid creating
# duplicates when the Hyperliquid API has latency in returning newly created orders.
# Structure: {(wallet_address, symbol): {"tp_price": float, "sl_price": float, "timestamp": int}}
# The cache is automatically cleared on server restart (desired behavior).
from services.hyperliquid_tpsl_cache import _clear_cached_tpsl, _get_cached_tpsl, _set_cached_tpsl


class EnvironmentMismatchError(Exception):
    """Raised when account environment doesn't match client environment"""
    pass


class HyperliquidTradingClient(
    HyperliquidCoreMixin,
    HyperliquidAccountMixin,
    HyperliquidHistoryMixin,
    HyperliquidOpenOrdersMixin,
    HyperliquidOrderManagementMixin,
    HyperliquidOrderExecutionMixin,
    HyperliquidTpslQueryMixin,
    HyperliquidTpslMixin,
    HyperliquidConnectionMixin,
    HyperliquidPrecisionMixin,
    HyperliquidTpslExecutionMixin,
):
    """
    Hyperliquid trading client with environment isolation

    Supports both testnet and mainnet with strict validation to prevent
    accidental cross-environment operations.
    """

    def __init__(self, account_id: int, private_key: str, environment: str = "testnet", wallet_address: Optional[str] = None,
                 key_type: str = "private_key", master_wallet_address: Optional[str] = None):
        """
        Initialize trading client

        Args:
            account_id: Database account ID (for validation)
            private_key: Hyperliquid private key (0x... format) - master key or agent key
            environment: "testnet" or "mainnet"
            wallet_address: Ethereum wallet address (derived from private key if not provided)
            key_type: "private_key" (legacy) or "agent_key" (agent wallet mode)
            master_wallet_address: Required for agent_key mode - the master wallet address for queries

        Raises:
            ValueError: If environment is invalid
        """
        if environment not in ["testnet", "mainnet"]:
            raise ValueError(f"Invalid environment: {environment}. Must be 'testnet' or 'mainnet'")

        self.account_id = account_id
        self.environment = environment
        self.key_type = key_type

        # Ensure private key has 0x prefix for consistency
        if not private_key.startswith('0x'):
            private_key = '0x' + private_key
        self.private_key = private_key

        # Derive wallet address from private key if not provided
        if not wallet_address:
            try:
                from eth_account import Account as EthAccount
                eth_account = EthAccount.from_key(private_key)
                # Lowercase address as recommended by Hyperliquid docs
                self.wallet_address = eth_account.address.lower()
                logger.info(f"Derived wallet address from private key: {self.wallet_address}")
            except Exception as e:
                logger.error(f"Failed to derive wallet address from private key: {e}", exc_info=True)
                self.wallet_address = None
        else:
            # Lowercase address as recommended by Hyperliquid docs
            self.wallet_address = wallet_address.lower()
            logger.info(f"Using provided wallet address: {self.wallet_address}")

        if not self.wallet_address:
            raise ValueError("Wallet address could not be derived from private key. Please check key format.")

        # For agent_key mode, query_address is the master wallet address
        # For private_key mode, query_address is the same as wallet_address
        if key_type == "agent_key":
            if not master_wallet_address:
                raise ValueError("master_wallet_address is required for agent_key mode")
            self.query_address = master_wallet_address.lower()
            logger.info(f"Agent key mode: signing_address={self.wallet_address}, query_address={self.query_address}")
        else:
            self.query_address = self.wallet_address

        logger.info(f"[FINAL] Using wallet address: {self.wallet_address}, query_address: {self.query_address}")

        # Set API endpoint based on environment
        if environment == "testnet":
            self.api_url = "https://api.hyperliquid-testnet.xyz"
        else:
            self.api_url = "https://api.hyperliquid.xyz"

        # Initialize CCXT exchange with authentication (for balance/position queries)
        try:
            self.exchange = ccxt.hyperliquid({
                'sandbox': (environment == "testnet"),
                'enableRateLimit': True,
                'rateLimit': 100,  # 100ms between requests
                'privateKey': private_key,  # Signing key (master or agent)
                'walletAddress': self.query_address,  # Address for balance/position queries
                'options': {
                    'ref': 'HYPERSVIP',
                    'builderFee': False,
                    'fetchMarkets': {
                        'hip3': {
                            'dex': []  # Empty list to skip HIP3 DEX markets (we only need perp markets)
                        }
                    }
                }
            })
            self._disable_hip3_markets()

            # Skip load_markets() — we use SDK for balance/positions/orders now.
            # CCXT is kept as fallback but market loading crashes on testnet due to
            # inconsistent spot metadata from Hyperliquid API.

            logger.info(
                f"CCXT HyperliquidClient initialized (markets not loaded): account_id={account_id} "
                f"environment={environment.upper()} wallet={self.wallet_address}"
            )
        except Exception as e:
            logger.error(f"Failed to initialize CCXT Hyperliquid exchange: {e}")
            raise

        # Initialize official Hyperliquid SDK (for order placement)
        try:
            from hyperliquid.exchange import Exchange
            from hyperliquid.info import Info
            from eth_account import Account as EthAccount

            # Create eth_account wallet for SDK
            self.eth_wallet = EthAccount.from_key(private_key)

            try:
                # Include HIP-3 metadata, but do not let that optional metadata block
                # standard perp trading if the xyz DEX metadata fetch fails.
                self.sdk_exchange = Exchange(
                    wallet=self.eth_wallet,
                    base_url=self.api_url,
                    account_address=self.query_address,
                    spot_meta={"tokens": [], "universe": []},
                    perp_dexs=['', 'xyz'],
                )
                self.sdk_info = Info(
                    base_url=self.api_url,
                    skip_ws=True,
                    spot_meta={"tokens": [], "universe": []},
                    perp_dexs=['', 'xyz'],
                )
                self.hip3_sdk_enabled = True
            except Exception as hip3_err:
                logger.warning(
                    "Failed to load HIP-3 metadata for Hyperliquid SDK; "
                    "falling back to standard perps only: %s",
                    hip3_err,
                )
                self.sdk_exchange = Exchange(
                    wallet=self.eth_wallet,
                    base_url=self.api_url,
                    account_address=self.query_address,
                    spot_meta={"tokens": [], "universe": []},
                    perp_dexs=[''],
                )
                self.sdk_info = Info(
                    base_url=self.api_url,
                    skip_ws=True,
                    spot_meta={"tokens": [], "universe": []},
                    perp_dexs=[''],
                )
                self.hip3_sdk_enabled = False

            logger.info(
                f"Official SDK Exchange + Info initialized: account_id={account_id} "
                f"environment={environment.upper()} wallet={self.wallet_address}"
            )
        except Exception as e:
            logger.error(f"Failed to initialize Hyperliquid SDK: {e}")
            raise



# Factory function for creating clients
def create_hyperliquid_client(
    account_id: int,
    private_key: str,
    environment: str,
    wallet_address: str = None,
    key_type: str = "private_key",
    master_wallet_address: str = None
) -> HyperliquidTradingClient:
    """
    Factory function to create Hyperliquid trading client

    Args:
        account_id: Database account ID
        private_key: Hyperliquid private key
        environment: "testnet" or "mainnet"
        wallet_address: Optional wallet address (if not provided, derived from private key)
        key_type: "private_key" or "agent_key"
        master_wallet_address: Required for agent_key mode

    Returns:
        Initialized HyperliquidTradingClient
    """
    return HyperliquidTradingClient(
        account_id=account_id,
        private_key=private_key,
        wallet_address=wallet_address,
        environment=environment,
        key_type=key_type,
        master_wallet_address=master_wallet_address
    )


# ============================================================================
# TRADING CLIENT CACHE - Reuse initialized clients to avoid 8s cold start
# ============================================================================
# Cache key: (account_id, environment)
# The CCXT exchange initialization takes ~8 seconds due to market loading.
# By caching clients, subsequent requests can reuse the initialized exchange.
#
# Cache invalidation:
# - Manual: call clear_trading_client_cache() when wallet config changes
# - No TTL: REST API clients are stateless, cache persists until server restart
#   or wallet config changes
# ============================================================================

from typing import Tuple
import threading

_trading_client_cache: Dict[Tuple[int, str], Dict[str, Any]] = {}
_trading_client_cache_lock = threading.Lock()


def get_cached_trading_client(
    account_id: int,
    private_key: str,
    environment: str,
    wallet_address: str = None,
    key_type: str = "private_key",
    master_wallet_address: str = None
) -> HyperliquidTradingClient:
    """
    Get or create a cached HyperliquidTradingClient.

    This function caches initialized clients to avoid the ~8 second cold start
    time for CCXT exchange initialization. Clients are cached by (account_id, environment).

    Args:
        account_id: Database account ID
        private_key: Hyperliquid private key
        environment: "testnet" or "mainnet"
        wallet_address: Optional wallet address
        key_type: "private_key" or "agent_key"
        master_wallet_address: Required for agent_key mode

    Returns:
        Cached or newly created HyperliquidTradingClient
    """
    cache_key = (account_id, environment)
    current_time = time.time()

    with _trading_client_cache_lock:
        # Check if we have a cached client (no TTL - REST clients are stateless)
        if cache_key in _trading_client_cache:
            cached = _trading_client_cache[cache_key]
            logger.debug(f"[CLIENT CACHE] Hit for account {account_id}/{environment}")
            return cached["client"]

        # Create new client
        logger.info(f"[CLIENT CACHE] Creating new client for account {account_id}/{environment}")
        start_time = time.time()

        client = HyperliquidTradingClient(
            account_id=account_id,
            private_key=private_key,
            wallet_address=wallet_address,
            environment=environment,
            key_type=key_type,
            master_wallet_address=master_wallet_address
        )

        elapsed = time.time() - start_time
        logger.info(f"[CLIENT CACHE] Client created in {elapsed:.2f}s for account {account_id}/{environment}")

        # Cache the client
        _trading_client_cache[cache_key] = {
            "client": client,
            "created_at": current_time
        }

        return client


def clear_trading_client_cache(account_id: int = None, environment: str = None) -> int:
    """
    Clear trading client cache.

    Call this when wallet configuration changes (e.g., new private key).

    Args:
        account_id: If specified, only clear cache for this account
        environment: If specified, only clear cache for this environment

    Returns:
        Number of cache entries cleared
    """
    cleared = 0
    with _trading_client_cache_lock:
        if account_id is None and environment is None:
            # Clear all
            cleared = len(_trading_client_cache)
            _trading_client_cache.clear()
            logger.info(f"[CLIENT CACHE] Cleared all {cleared} cached clients")
        else:
            # Selective clear
            keys_to_remove = []
            for key in _trading_client_cache:
                acc_id, env = key
                if (account_id is None or acc_id == account_id) and \
                   (environment is None or env == environment):
                    keys_to_remove.append(key)

            for key in keys_to_remove:
                del _trading_client_cache[key]
                cleared += 1

            logger.info(f"[CLIENT CACHE] Cleared {cleared} cached clients for account={account_id}, env={environment}")

    return cleared


def get_trading_client_cache_stats() -> Dict[str, Any]:
    """
    Get cache statistics for monitoring.

    Returns:
        Dict with cache stats
    """
    with _trading_client_cache_lock:
        current_time = time.time()
        entries = []
        for key, value in _trading_client_cache.items():
            acc_id, env = key
            age = current_time - value["created_at"]
            entries.append({
                "account_id": acc_id,
                "environment": env,
                "age_seconds": round(age, 1)
            })

        return {
            "total_cached": len(_trading_client_cache),
            "entries": entries
        }
