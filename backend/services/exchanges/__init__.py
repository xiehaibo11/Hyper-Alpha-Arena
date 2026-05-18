"""
Exchange adapters for multi-exchange support.

This module provides a unified interface for interacting with different
cryptocurrency exchanges. Each exchange has its own adapter that handles
data fetching, format conversion, and order execution.

Supported exchanges:
- Hyperliquid (existing, native implementation)
- Binance (new, via adapter)
- OKX (public market data, via adapter)
"""

from .base_adapter import BaseExchangeAdapter
from .symbol_mapper import SymbolMapper
from .binance_adapter import BinanceAdapter
from .okx_adapter import OKXAdapter
from .data_persistence import ExchangeDataPersistence
from .binance_collector import BinanceCollector, binance_collector
from .binance_kline_ws_collector import BinanceKlineWSCollector, binance_kline_ws_collector
from .okx_collector import OKXCollector, okx_collector

__all__ = [
    "BaseExchangeAdapter",
    "SymbolMapper",
    "BinanceAdapter",
    "OKXAdapter",
    "ExchangeDataPersistence",
    "BinanceCollector",
    "binance_collector",
    "BinanceKlineWSCollector",
    "binance_kline_ws_collector",
    "OKXCollector",
    "okx_collector",
]
