"""Crypto.com public market-data adapter (klines).

Public REST: https://api.crypto.com/exchange/v1/public/get-candlestick
Candles carry OHLCV but NO taker buy/sell volume, so this is a price/chart data
source only (it cannot drive the CVD order-flow signal — use Binance for that).

BTC/ETH map to USD-margined perpetuals: BTC -> BTCUSD-PERP, ETH -> ETHUSD-PERP.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

import requests

from .base_adapter import UnifiedKline

_BASE = "https://api.crypto.com/exchange/v1"
_INTERVAL = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "2h": "2h", "4h": "4h", "12h": "12h", "1d": "1D", "1w": "7D",
}


class CryptoComAdapter:
    """Minimal Crypto.com adapter exposing fetch_klines (UnifiedKline)."""

    exchange = "crypto_com"

    def _to_exchange_symbol(self, symbol: str) -> str:
        s = symbol.upper().replace("-", "").replace("_", "").replace("PERP", "")
        for q in ("USDT", "USDC", "USD"):
            if s.endswith(q):
                s = s[: -len(q)]
                break
        return f"{s}USD-PERP"

    def fetch_klines(
        self, symbol: str, interval: str, limit: int = 100,
        start_time: Optional[int] = None, end_time: Optional[int] = None,
    ) -> List[UnifiedKline]:
        params: dict = {
            "instrument_name": self._to_exchange_symbol(symbol),
            "timeframe": _INTERVAL.get(interval, "1m"),
            "count": min(int(limit), 300),  # Crypto.com max 300
        }
        if start_time:
            params["start_ts"] = int(start_time)
        if end_time:
            params["end_ts"] = int(end_time)
        resp = requests.get(f"{_BASE}/public/get-candlestick", params=params, timeout=10)
        resp.raise_for_status()
        rows = resp.json().get("result", {}).get("data", []) or []
        klines: List[UnifiedKline] = []
        for k in rows:
            klines.append(UnifiedKline(
                exchange=self.exchange,
                symbol=symbol,
                interval=interval,
                timestamp=int(k["t"]) // 1000,  # ms -> seconds
                open_price=Decimal(str(k["o"])),
                high_price=Decimal(str(k["h"])),
                low_price=Decimal(str(k["l"])),
                close_price=Decimal(str(k["c"])),
                volume=Decimal(str(k.get("v", "0"))),
                quote_volume=Decimal("0"),
            ))
        klines.sort(key=lambda x: x.timestamp)
        return klines

    def fetch_trades(self, symbol: str, limit: int = 200) -> List[dict]:
        """Return recent taker trades for CVD order-flow.

        [{'ts_ms':int, 'price':float, 'size':float(coin), 'side':'buy'|'sell',
          'notional':float}]. `side` is the taker direction. Returns [] on error.
        """
        try:
            params = {
                "instrument_name": self._to_exchange_symbol(symbol),
                "count": min(int(limit), 300),  # Crypto.com max 300
            }
            resp = requests.get(f"{_BASE}/public/get-trades", params=params, timeout=10)
            resp.raise_for_status()
            rows = resp.json().get("result", {}).get("data", []) or []
            out: List[dict] = []
            for t in rows:
                size = float(t["q"])
                price = float(t["p"])
                out.append({
                    "ts_ms": int(t["t"]),
                    "price": price,
                    "size": size,
                    "side": str(t["s"]).lower(),
                    "notional": size * price,
                })
            return out
        except Exception:
            return []
