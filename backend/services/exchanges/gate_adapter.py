"""Gate.io USDT-perpetual public market-data adapter (klines).

Public REST: https://api.gateio.ws/api/v4/futures/usdt/candlesticks
Candle fields: o/h/l/c (price), v (volume in CONTRACTS), sum (quote/USDT amount),
t (unix seconds). Base-coin volume = v * quanto_multiplier (BTC 0.0001, ETH 0.01).
No taker buy/sell split, so this is a price/chart source only (not CVD order-flow).

BTC/ETH map to USDT perps: BTC -> BTC_USDT, ETH -> ETH_USDT.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

import requests

from .base_adapter import UnifiedKline

_BASE = "https://api.gateio.ws/api/v4/futures/usdt"
_QUANTO = {"BTC": Decimal("0.0001"), "ETH": Decimal("0.01"), "SOL": Decimal("1"), "BNB": Decimal("0.01")}
_INTERVAL = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "4h", "8h": "8h", "1d": "1d", "1w": "7d",
}


class GateAdapter:
    """Minimal Gate.io USDT-futures adapter exposing fetch_klines (UnifiedKline)."""

    exchange = "gate"

    def _to_exchange_symbol(self, symbol: str) -> str:
        s = symbol.upper().replace("-", "").replace("_", "").replace("PERP", "")
        for q in ("USDT", "USDC", "USD"):
            if s.endswith(q):
                s = s[: -len(q)]
                break
        return f"{s}_USDT"

    def _multiplier(self, symbol: str) -> Decimal:
        base = self._to_exchange_symbol(symbol).split("_")[0]
        return _QUANTO.get(base, Decimal("1"))

    def fetch_klines(
        self, symbol: str, interval: str, limit: int = 100,
        start_time: Optional[int] = None, end_time: Optional[int] = None,
    ) -> List[UnifiedKline]:
        params: dict = {
            "contract": self._to_exchange_symbol(symbol),
            "interval": _INTERVAL.get(interval, "1m"),
            "limit": min(int(limit), 2000),  # Gate max 2000
        }
        # Gate uses unix SECONDS for from/to; adapter callers pass milliseconds.
        if start_time:
            params["from"] = int(start_time) // 1000 if int(start_time) > 1_000_000_000_000 else int(start_time)
        if end_time:
            params["to"] = int(end_time) // 1000 if int(end_time) > 1_000_000_000_000 else int(end_time)
        resp = requests.get(f"{_BASE}/candlesticks", params=params, timeout=10)
        resp.raise_for_status()
        rows = resp.json() or []
        mult = self._multiplier(symbol)
        klines: List[UnifiedKline] = []
        for k in rows:
            klines.append(UnifiedKline(
                exchange=self.exchange,
                symbol=symbol,
                interval=interval,
                timestamp=int(k["t"]),  # already seconds
                open_price=Decimal(str(k["o"])),
                high_price=Decimal(str(k["h"])),
                low_price=Decimal(str(k["l"])),
                close_price=Decimal(str(k["c"])),
                volume=Decimal(str(k.get("v", "0"))) * mult,  # contracts -> coin
                quote_volume=Decimal(str(k.get("sum", "0"))),
            ))
        klines.sort(key=lambda x: x.timestamp)
        return klines
