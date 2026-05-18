"""Binance symbol precision and ticker helpers."""

import logging
import time
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BinancePrecisionMixin:
    def _get_exchange_info(self) -> Dict[str, Any]:
        """
        Get exchange info with caching.

        Returns:
            Exchange info dict with symbols and filters
        """
        now = time.time()
        if self._exchange_info_cache and (now - self._exchange_info_timestamp) < self._cache_ttl:
            return self._exchange_info_cache

        self._exchange_info_cache = self._request("GET", "/fapi/v1/exchangeInfo")
        self._exchange_info_timestamp = now
        return self._exchange_info_cache

    def _get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get symbol-specific info including precision filters.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')

        Returns:
            Symbol info dict or None if not found
        """
        exchange_info = self._get_exchange_info()
        for sym_info in exchange_info.get("symbols", []):
            if sym_info["symbol"] == symbol:
                return sym_info
        return None

    def _get_precision(self, symbol: str) -> Dict[str, Any]:
        """
        Get price and quantity precision for a symbol.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')

        Returns:
            Dict with tick_size, step_size, min_qty, min_notional
        """
        sym_info = self._get_symbol_info(symbol)
        if not sym_info:
            # Default conservative values
            return {
                "tick_size": Decimal("0.01"),
                "step_size": Decimal("0.001"),
                "min_qty": Decimal("0.001"),
                "min_notional": Decimal("5")
            }

        result = {
            "tick_size": Decimal("0.01"),
            "step_size": Decimal("0.001"),
            "min_qty": Decimal("0.001"),
            "min_notional": Decimal("5")
        }

        for f in sym_info.get("filters", []):
            if f["filterType"] == "PRICE_FILTER":
                result["tick_size"] = Decimal(f["tickSize"])
            elif f["filterType"] == "LOT_SIZE":
                result["step_size"] = Decimal(f["stepSize"])
                result["min_qty"] = Decimal(f["minQty"])
            elif f["filterType"] == "MIN_NOTIONAL":
                result["min_notional"] = Decimal(f["notional"])

        return result

    def _round_price(self, price: float, tick_size: Decimal) -> Decimal:
        """Round price to tick size."""
        price_dec = Decimal(str(price))
        return (price_dec / tick_size).quantize(Decimal("1"), rounding=ROUND_DOWN) * tick_size

    def _round_quantity(self, quantity: float, step_size: Decimal) -> Decimal:
        """Round quantity to step size."""
        qty_dec = Decimal(str(quantity))
        return (qty_dec / step_size).quantize(Decimal("1"), rounding=ROUND_DOWN) * step_size

    def _to_binance_symbol(self, symbol: str) -> str:
        """
        Convert internal symbol to Binance format.

        Args:
            symbol: Internal symbol (e.g., 'BTC' or 'BTCUSDT')

        Returns:
            Binance symbol (e.g., 'BTCUSDT')
        """
        symbol = symbol.upper()
        if not symbol.endswith("USDT"):
            symbol = f"{symbol}USDT"
        return symbol

    def _to_internal_symbol(self, binance_symbol: str) -> str:
        """
        Convert Binance symbol to internal format.

        Args:
            binance_symbol: Binance symbol (e.g., 'BTCUSDT')

        Returns:
            Internal symbol (e.g., 'BTC')
        """
        if binance_symbol.endswith("USDT"):
            return binance_symbol[:-4]
        return binance_symbol
