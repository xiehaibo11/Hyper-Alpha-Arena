"""
OKX public market-data adapter.

This adapter uses OKX API v5 public REST endpoints and converts responses into
the unified exchange dataclasses used by the rest of the project.
"""

from __future__ import annotations

import logging
import os
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

import requests

from .base_adapter import (
    BaseExchangeAdapter,
    UnifiedFunding,
    UnifiedKline,
    UnifiedOpenInterest,
    UnifiedOrderbook,
    UnifiedSentiment,
    UnifiedTrade,
)
from .symbol_mapper import SymbolMapper

logger = logging.getLogger(__name__)


class OKXAdapter(BaseExchangeAdapter):
    """OKX API v5 public market-data adapter."""

    BASE_URL = "https://www.okx.com"
    DEMO_URL = "https://www.okx.com"

    INTERVAL_MAP = {
        "1m": "1m",
        "3m": "3m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1H",
        "2h": "2H",
        "4h": "4H",
        "6h": "6H",
        "12h": "12H",
        "1d": "1Dutc",
        "3d": "3Dutc",
        "1w": "1Wutc",
        "1M": "1Mutc",
    }

    def __init__(self, environment: str = "mainnet"):
        super().__init__(environment)
        configured_url = os.getenv("OKX_BASE_URL", "").strip().rstrip("/")
        self.base_url = configured_url or (self.DEMO_URL if environment == "testnet" else self.BASE_URL)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Hyper-Alpha-Arena/okx-public-data",
            }
        )
        if environment == "testnet":
            self.session.headers.update({"x-simulated-trading": "1"})

    def _get_exchange_name(self) -> str:
        return "okx"

    def _to_exchange_symbol(self, symbol: str) -> str:
        return SymbolMapper.to_exchange(symbol, "okx")

    def _to_internal_symbol(self, symbol: str) -> str:
        return SymbolMapper.to_internal(symbol, "okx")

    def _request(self, endpoint: str, params: Optional[dict] = None) -> List[Any]:
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.get(url, params=params or {}, timeout=12)
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.RequestException as exc:
            logger.error("OKX API request failed: %s params=%s error=%s", endpoint, params, exc)
            raise

        code = str(payload.get("code", ""))
        if code != "0":
            message = payload.get("msg") or payload.get("error_message") or "unknown OKX error"
            raise ValueError(f"OKX API error {code} for {endpoint}: {message}")
        data = payload.get("data")
        return data if isinstance(data, list) else []

    @staticmethod
    def _decimal(value: Any, default: str = "0") -> Decimal:
        if value is None or value == "":
            value = default
        return Decimal(str(value))

    @staticmethod
    def _int_ms(value: Any) -> int:
        if value is None or value == "":
            return int(time.time() * 1000)
        return int(float(value))

    @staticmethod
    def _coin_from_symbol(symbol: str) -> str:
        internal = SymbolMapper.to_internal(symbol, "okx")
        return str(internal or symbol).split("-")[0].upper()

    def _interval_to_okx(self, interval: str) -> str:
        if interval == "8h":
            return "4H"
        if interval not in self.INTERVAL_MAP:
            raise ValueError(f"Unsupported OKX kline interval: {interval}")
        return self.INTERVAL_MAP[interval]

    # ==================== Instruments ====================

    def fetch_instruments(
        self,
        inst_type: str = "SWAP",
        uly: Optional[str] = None,
        inst_family: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"instType": inst_type}
        if uly:
            params["uly"] = uly
        if inst_family:
            params["instFamily"] = inst_family
        return self._request("/api/v5/public/instruments", params)

    # ==================== Price and Ticker ====================

    def fetch_price(self, symbol: str) -> float:
        ticker = self.fetch_ticker(symbol)
        price = float(ticker.get("last") or 0)
        if price <= 0:
            raise ValueError(f"OKX returned invalid price for {symbol}: {price}")
        return price

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        inst_id = self._to_exchange_symbol(symbol)
        data = self._request("/api/v5/market/ticker", {"instId": inst_id})
        if not data:
            raise ValueError(f"No OKX ticker data for {inst_id}")
        return data[0]

    def fetch_tickers(self, inst_type: str = "SWAP", uly: Optional[str] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"instType": inst_type}
        if uly:
            params["uly"] = uly
        return self._request("/api/v5/market/tickers", params)

    def fetch_mark_price(self, symbol: str) -> Dict[str, Any]:
        inst_id = self._to_exchange_symbol(symbol)
        data = self._request("/api/v5/public/mark-price", {"instType": "SWAP", "instId": inst_id})
        return data[0] if data else {}

    def fetch_index_ticker(self, symbol: str) -> Dict[str, Any]:
        base = self._coin_from_symbol(symbol)
        inst_id = f"{base}-USDT"
        data = self._request("/api/v5/market/index-tickers", {"instId": inst_id})
        return data[0] if data else {}

    # ==================== K-lines ====================

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[UnifiedKline]:
        if interval == "8h":
            return self._fetch_aggregated_8h_klines(symbol, limit, start_time, end_time)

        inst_id = self._to_exchange_symbol(symbol)
        bar = self._interval_to_okx(interval)
        requested = max(1, min(2000, int(limit or 100)))
        remaining = requested
        after: Optional[str] = str(end_time) if end_time else None
        rows: List[list] = []

        while remaining > 0:
            chunk_limit = min(300, remaining)
            params: Dict[str, Any] = {
                "instId": inst_id,
                "bar": bar,
                "limit": str(chunk_limit),
            }
            if after:
                params["after"] = after
            if start_time:
                params["before"] = str(start_time)

            chunk = self._request("/api/v5/market/history-candles", params)
            if not chunk:
                break
            rows.extend(chunk)
            remaining = requested - len(rows)
            oldest_ts = chunk[-1][0] if isinstance(chunk[-1], list) and chunk[-1] else None
            if not oldest_ts or remaining <= 0:
                break
            after = str(oldest_ts)
            if len(chunk) < chunk_limit:
                break

        return self._parse_klines(rows[:requested], symbol, interval)

    def _fetch_aggregated_8h_klines(
        self,
        symbol: str,
        limit: int,
        start_time: Optional[int],
        end_time: Optional[int],
    ) -> List[UnifiedKline]:
        source = self.fetch_klines(
            symbol,
            "4h",
            limit=max(2, min(500, int(limit or 100) * 2 + 2)),
            start_time=start_time,
            end_time=end_time,
        )
        buckets: Dict[int, List[UnifiedKline]] = {}
        for kline in source:
            bucket_ts = (kline.timestamp // (8 * 3600)) * (8 * 3600)
            buckets.setdefault(bucket_ts, []).append(kline)

        aggregated: List[UnifiedKline] = []
        for bucket_ts in sorted(buckets):
            items = sorted(buckets[bucket_ts], key=lambda item: item.timestamp)
            if not items:
                continue
            open_price = items[0].open_price
            close_price = items[-1].close_price
            high_price = max(item.high_price for item in items)
            low_price = min(item.low_price for item in items)
            volume = sum((item.volume for item in items), Decimal("0"))
            quote_volume = sum((item.quote_volume for item in items), Decimal("0"))
            aggregated.append(
                UnifiedKline(
                    exchange="okx",
                    symbol=symbol.upper(),
                    interval="8h",
                    timestamp=bucket_ts,
                    open_price=open_price,
                    high_price=high_price,
                    low_price=low_price,
                    close_price=close_price,
                    volume=volume,
                    quote_volume=quote_volume,
                )
            )
        return aggregated[-max(1, int(limit or 100)) :]

    def _parse_klines(self, raw_data: List[list], symbol: str, interval: str) -> List[UnifiedKline]:
        klines: List[UnifiedKline] = []
        for item in raw_data:
            if not isinstance(item, list) or len(item) < 6:
                continue
            # OKX candle format: [ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]
            ts_ms = self._int_ms(item[0])
            volume = self._decimal(item[6] if len(item) > 6 and item[6] != "" else item[5])
            quote_volume = self._decimal(
                item[7] if len(item) > 7 and item[7] != "" else item[6] if len(item) > 6 else item[5]
            )
            klines.append(
                UnifiedKline(
                    exchange="okx",
                    symbol=symbol.upper(),
                    interval=interval,
                    timestamp=ts_ms // 1000,
                    open_price=self._decimal(item[1]),
                    high_price=self._decimal(item[2]),
                    low_price=self._decimal(item[3]),
                    close_price=self._decimal(item[4]),
                    volume=volume,
                    quote_volume=quote_volume,
                )
            )
        klines.sort(key=lambda item: item.timestamp)
        return klines

    # ==================== Order Book and Trades ====================

    def fetch_orderbook(self, symbol: str, depth: int = 10) -> UnifiedOrderbook:
        inst_id = self._to_exchange_symbol(symbol)
        data = self._request("/api/v5/market/books", {"instId": inst_id, "sz": str(min(depth, 400))})
        if not data:
            raise ValueError(f"No OKX orderbook data for {inst_id}")
        return self._parse_orderbook(data[0], symbol)

    def _parse_orderbook(self, raw_data: Dict[str, Any], symbol: str) -> UnifiedOrderbook:
        bids = raw_data.get("bids") or []
        asks = raw_data.get("asks") or []
        best_bid = self._decimal(bids[0][0]) if bids else Decimal("0")
        best_ask = self._decimal(asks[0][0]) if asks else Decimal("0")
        bid_depth_sum = sum((self._decimal(row[1]) for row in bids[:10]), Decimal("0"))
        ask_depth_sum = sum((self._decimal(row[1]) for row in asks[:10]), Decimal("0"))
        spread = best_ask - best_bid
        mid_price = (best_ask + best_bid) / Decimal("2")
        spread_bps = (spread / mid_price * Decimal("10000")) if mid_price > 0 else Decimal("0")
        return UnifiedOrderbook(
            exchange="okx",
            symbol=symbol.upper(),
            timestamp=self._int_ms(raw_data.get("ts")),
            best_bid=best_bid,
            best_ask=best_ask,
            bid_depth_sum=bid_depth_sum,
            ask_depth_sum=ask_depth_sum,
            spread=spread,
            spread_bps=spread_bps,
        )

    def fetch_recent_trades(self, symbol: str, limit: int = 100) -> List[UnifiedTrade]:
        inst_id = self._to_exchange_symbol(symbol)
        data = self._request("/api/v5/market/trades", {"instId": inst_id, "limit": str(min(limit, 500))})
        trades: List[UnifiedTrade] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            trades.append(
                UnifiedTrade(
                    exchange="okx",
                    symbol=symbol.upper(),
                    timestamp=self._int_ms(item.get("ts")),
                    price=self._decimal(item.get("px")),
                    size=self._decimal(item.get("sz")),
                    side=str(item.get("side") or "").lower(),
                    trade_id=str(item.get("tradeId") or ""),
                )
            )
        trades.sort(key=lambda item: item.timestamp)
        return trades

    # ==================== Funding, OI, Sentiment ====================

    def fetch_funding_rate(self, symbol: str) -> UnifiedFunding:
        inst_id = self._to_exchange_symbol(symbol)
        data = self._request("/api/v5/public/funding-rate", {"instId": inst_id})
        if not data:
            raise ValueError(f"No OKX funding data for {inst_id}")
        item = data[0]
        mark_price = None
        try:
            mark = self.fetch_mark_price(symbol)
            if mark.get("markPx"):
                mark_price = self._decimal(mark["markPx"])
        except Exception as exc:
            logger.debug("OKX mark price unavailable for %s while fetching funding: %s", symbol, exc)
        return UnifiedFunding(
            exchange="okx",
            symbol=symbol.upper(),
            timestamp=self._int_ms(item.get("ts") or item.get("fundingTime")),
            funding_rate=self._decimal(item.get("fundingRate")),
            next_funding_time=self._int_ms(item.get("fundingTime") or item.get("nextFundingTime")),
            mark_price=mark_price,
        )

    def fetch_funding_history(
        self,
        symbol: str,
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[UnifiedFunding]:
        inst_id = self._to_exchange_symbol(symbol)
        params: Dict[str, Any] = {"instId": inst_id, "limit": str(min(limit, 100))}
        if start_time:
            params["before"] = str(start_time)
        if end_time:
            params["after"] = str(end_time)
        data = self._request("/api/v5/public/funding-rate-history", params)
        results: List[UnifiedFunding] = []
        for item in data:
            rate = item.get("realizedRate") or item.get("fundingRate")
            results.append(
                UnifiedFunding(
                    exchange="okx",
                    symbol=symbol.upper(),
                    timestamp=self._int_ms(item.get("fundingTime")),
                    funding_rate=self._decimal(rate),
                )
            )
        results.sort(key=lambda item: item.timestamp)
        return results

    def fetch_open_interest(self, symbol: str) -> UnifiedOpenInterest:
        inst_id = self._to_exchange_symbol(symbol)
        data = self._request("/api/v5/public/open-interest", {"instType": "SWAP", "instId": inst_id})
        if not data:
            raise ValueError(f"No OKX open-interest data for {inst_id}")
        item = data[0]
        return UnifiedOpenInterest(
            exchange="okx",
            symbol=symbol.upper(),
            timestamp=self._int_ms(item.get("ts")),
            open_interest=self._decimal(item.get("oiCcy") or item.get("oi")),
            open_interest_value=self._decimal(item.get("oiUsd")) if item.get("oiUsd") else None,
        )

    def fetch_open_interest_history(
        self,
        symbol: str,
        interval: str = "5m",
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[UnifiedOpenInterest]:
        coin = self._coin_from_symbol(symbol)
        period = self._rubik_period(interval)
        params: Dict[str, Any] = {"ccy": coin, "period": period}
        data = self._request("/api/v5/rubik/stat/contracts/open-interest-volume", params)
        results: List[UnifiedOpenInterest] = []
        for item in data[:limit]:
            if not isinstance(item, list) or len(item) < 2:
                continue
            ts = self._int_ms(item[0])
            if start_time and ts < start_time:
                continue
            if end_time and ts > end_time:
                continue
            oi_usd = self._decimal(item[1])
            results.append(
                UnifiedOpenInterest(
                    exchange="okx",
                    symbol=symbol.upper(),
                    timestamp=ts,
                    open_interest=oi_usd,
                    open_interest_value=oi_usd,
                )
            )
        results.sort(key=lambda item: item.timestamp)
        return results

    def fetch_sentiment(self, symbol: str) -> Optional[UnifiedSentiment]:
        history = self.fetch_sentiment_history(symbol, interval="5m", limit=1)
        return history[-1] if history else None

    def fetch_sentiment_history(
        self,
        symbol: str,
        interval: str = "5m",
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[UnifiedSentiment]:
        coin = self._coin_from_symbol(symbol)
        period = self._rubik_period(interval)
        data = self._request(
            "/api/v5/rubik/stat/contracts/long-short-account-ratio",
            {"ccy": coin, "period": period},
        )
        results: List[UnifiedSentiment] = []
        for item in data[:limit]:
            if not isinstance(item, list) or len(item) < 2:
                continue
            ts = self._int_ms(item[0])
            if start_time and ts < start_time:
                continue
            if end_time and ts > end_time:
                continue
            ratio = self._decimal(item[1])
            denominator = Decimal("1") + ratio
            long_ratio = ratio / denominator if denominator > 0 else Decimal("0")
            short_ratio = Decimal("1") / denominator if denominator > 0 else Decimal("0")
            results.append(
                UnifiedSentiment(
                    exchange="okx",
                    symbol=symbol.upper(),
                    timestamp=ts,
                    long_ratio=long_ratio,
                    short_ratio=short_ratio,
                    long_short_ratio=ratio,
                )
            )
        results.sort(key=lambda item: item.timestamp)
        return results

    def fetch_taker_volume_history(
        self,
        symbol: str,
        interval: str = "5m",
        limit: int = 100,
    ) -> List[Dict[str, Decimal | int | str]]:
        """Fetch OKX trading-stat taker volume for contracts.

        OKX returns rows as [timestamp, sell volume, buy volume]. Volumes are
        notional amounts for the requested currency and period.
        """
        coin = self._coin_from_symbol(symbol)
        period = self._rubik_period(interval)
        data = self._request(
            "/api/v5/rubik/stat/taker-volume",
            {"ccy": coin, "instType": "CONTRACTS", "period": period},
        )
        results: List[Dict[str, Decimal | int | str]] = []
        for item in data[:limit]:
            if not isinstance(item, list) or len(item) < 3:
                continue
            results.append(
                {
                    "exchange": "okx",
                    "symbol": symbol.upper(),
                    "timestamp": self._int_ms(item[0]),
                    "taker_sell_notional": self._decimal(item[1]),
                    "taker_buy_notional": self._decimal(item[2]),
                }
            )
        results.sort(key=lambda item: int(item["timestamp"]))
        return results

    @staticmethod
    def _rubik_period(interval: str) -> str:
        supported = {"5m", "1H", "1D"}
        normalized = {"5m": "5m", "15m": "5m", "30m": "5m", "1h": "1H", "4h": "1H", "1d": "1D"}.get(
            interval,
            interval,
        )
        if normalized not in supported:
            return "5m"
        return normalized

    def get_supported_intervals(self) -> List[str]:
        return ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"]
