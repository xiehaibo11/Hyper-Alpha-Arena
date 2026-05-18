"""In-memory TP/SL order cache for Hyperliquid trading clients."""

import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_tpsl_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}

def _get_cache_key(wallet_address: str, symbol: str) -> Tuple[str, str]:
    """Generate cache key for TPSL orders"""
    return (wallet_address.lower() if wallet_address else "", symbol.upper())

def _get_cached_tpsl(wallet_address: str, symbol: str) -> Optional[Dict[str, Any]]:
    """Get cached TPSL prices for a symbol"""
    key = _get_cache_key(wallet_address, symbol)
    return _tpsl_cache.get(key)

def _set_cached_tpsl(wallet_address: str, symbol: str, tp_price: Optional[float], sl_price: Optional[float]) -> None:
    """Update cached TPSL prices for a symbol"""
    key = _get_cache_key(wallet_address, symbol)
    _tpsl_cache[key] = {
        "tp_price": tp_price,
        "sl_price": sl_price,
        "timestamp": int(time.time() * 1000)
    }
    logger.info(f"[TPSL CACHE] Updated cache for {symbol}: TP={tp_price}, SL={sl_price}")

def _clear_cached_tpsl(wallet_address: str, symbol: str) -> None:
    """Clear cached TPSL prices for a symbol"""
    key = _get_cache_key(wallet_address, symbol)
    if key in _tpsl_cache:
        del _tpsl_cache[key]
        logger.info(f"[TPSL CACHE] Cleared cache for {symbol}")
