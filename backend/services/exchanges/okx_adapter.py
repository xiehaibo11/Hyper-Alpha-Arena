"""OKX public market-data adapter."""

from __future__ import annotations

import logging
import os
import threading
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

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
    _request_lock = threading.Lock()
    _cache_lock = threading.Lock()
    _last_request_at = 0.0
    _cooldown_until: Dict[str, float] = {}
    _cache: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], Tuple[float, List[Any]]] = {}
    _CACHE_MAX_ITEMS = 512

    def __init__(self, environment: str = "mainnet"):
        super().__init__(environment)
        self.base_url = os.getenv("OKX_BASE_URL", self.BASE_URL).strip().rstrip("/")
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
        return SymbolMapper.to_internal(symbol, "okx").split("-")[0].upper()

    @staticmethod
    def _float_env(name: str, default: float) -> float:
        try:
            return max(0.0, float(os.getenv(name, str(default))))
        except ValueError:
            return default

    def _request_interval_seconds(self, endpoint: str) -> float:
        if endpoint == "/api/v5/market/history-candles":
            return self._float_env("OKX_HISTORY_CANDLES_MIN_INTERVAL_SECONDS", 0.35)
        return self._float_env("OKX_PUBLIC_REQUEST_MIN_INTERVAL_SECONDS", 0.12)

    def _cache_ttl_seconds(self, endpoint: str) -> float:
        if endpoint == "/api/v5/market/history-candles":
            return self._float_env("OKX_HISTORY_CANDLES_CACHE_TTL_SECONDS", 55.0)
        if endpoint in {"/api/v5/market/ticker", "/api/v5/market/books", "/api/v5/market/trades"}:
            return self._float_env("OKX_FAST_ENDPOINT_CACHE_TTL_SECONDS", 2.0)
        if endpoint == "/api/v5/public/instruments":
            return self._float_env("OKX_INSTRUMENTS_CACHE_TTL_SECONDS", 300.0)
        return self._float_env("OKX_PUBLIC_ENDPOINT_CACHE_TTL_SECONDS", 10.0)

    @staticmethod
    def _cache_key(endpoint: str, params: Optional[dict]) -> Tuple[str, Tuple[Tuple[str, str], ...]]:
        normalized = tuple(sorted((str(key), str(value)) for key, value in (params or {}).items()))
        return endpoint, normalized

    def _get_cached_response(self, endpoint: str, params: Optional[dict]) -> Optional[List[Any]]:
        ttl = self._cache_ttl_seconds(endpoint)
        if ttl <= 0:
            return None
        key = self._cache_key(endpoint, params)
        now = time.monotonic()
        with self._cache_lock:
            cached = self._cache.get(key)
            if not cached:
                return None
            expires_at, data = cached
            if expires_at <= now:
                self._cache.pop(key, None)
                return None
            return list(data)

    def _set_cached_response(self, endpoint: str, params: Optional[dict], data: List[Any]) -> None:
        ttl = self._cache_ttl_seconds(endpoint)
        if ttl <= 0:
            return
        key = self._cache_key(endpoint, params)
        with self._cache_lock:
            if len(self._cache) >= self._CACHE_MAX_ITEMS:
                oldest_key = next(iter(self._cache))
                self._cache.pop(oldest_key, None)
            self._cache[key] = (time.monotonic() + ttl, list(data))

    def _respect_rate_limit(self, endpoint: str) -> None:
        with self._request_lock:
            now = time.monotonic()
            cooldown_until = max(
                self._cooldown_until.get("*", 0.0),
                self._cooldown_until.get(endpoint, 0.0),
            )
            next_allowed = max(cooldown_until, self._last_request_at + self._request_interval_seconds(endpoint))
            wait_seconds = next_allowed - now
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            self.__class__._last_request_at = time.monotonic()

    def _set_rate_limit_cooldown(self, endpoint: str) -> None:
        cooldown = self._float_env("OKX_RATE_LIMIT_COOLDOWN_SECONDS", 12.0)
        with self._request_lock:
            self._cooldown_until[endpoint] = time.monotonic() + cooldown

    def _request(self, endpoint: str, params: Optional[dict] = None) -> List[Any]:
        cached = self._get_cached_response(endpoint, params)
        if cached is not None:
            return cached

        url = f"{self.base_url}{endpoint}"
        try:
            self._respect_rate_limit(endpoint)
            response = self.session.get(url, params=params or {}, timeout=12)
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code == 429:
                self._set_rate_limit_cooldown(endpoint)
                logger.warning("OKX rate limited: endpoint=%s params=%s error=%s", endpoint, params, exc)
            else:
                logger.error("OKX request failed: endpoint=%s params=%s error=%s", endpoint, params, exc)
            raise
        except requests.exceptions.RequestException as exc:
            logger.error("OKX request failed: endpoint=%s params=%s error=%s", endpoint, params, exc)
            raise

        if str(payload.get("code", "")) != "0":
            message = payload.get("msg") or "unknown OKX error"
            if str(payload.get("code")) in {"50011", "51000"} or "rate" in str(message).lower():
                self._set_rate_limit_cooldown(endpoint)
            raise ValueError(f"OKX API error {payload.get('code')} for {endpoint}: {message}")
        data = payload.get("data")
        rows = data if isinstance(data, list) else []
        self._set_cached_response(endpoint, params, rows)
        return rows

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
        inst_id = f"{self._coin_from_symbol(symbol)}-USDT"
        data = self._request("/api/v5/market/index-tickers", {"instId": inst_id})
        return data[0] if data else {}

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[UnifiedKline]:
        bar = self.INTERVAL_MAP.get(interval)
        if not bar:
            raise ValueError(f"Unsupported OKX kline interval: {interval}")
        params: Dict[str, Any] = {
            "instId": self._to_exchange_symbol(symbol),
            "bar": bar,
            "limit": str(max(1, min(300, int(limit or 100)))),
        }
        if start_time:
            params["before"] = str(start_time)
        if end_time:
            params["after"] = str(end_time)
        return self._parse_klines(self._request("/api/v5/market/history-candles", params), symbol, interval)

    def _parse_klines(self, rows: List[list], symbol: str, interval: str) -> List[UnifiedKline]:
        klines: List[UnifiedKline] = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 6:
                continue
            volume = self._decimal(row[6] if len(row) > 6 and row[6] != "" else row[5])
            quote_volume = self._decimal(row[7] if len(row) > 7 and row[7] != "" else row[5])
            klines.append(
                UnifiedKline(
                    exchange="okx",
                    symbol=symbol.upper(),
                    interval=interval,
                    timestamp=self._int_ms(row[0]) // 1000,
                    open_price=self._decimal(row[1]),
                    high_price=self._decimal(row[2]),
                    low_price=self._decimal(row[3]),
                    close_price=self._decimal(row[4]),
                    volume=volume,
                    quote_volume=quote_volume,
                )
            )
        klines.sort(key=lambda item: item.timestamp)
        return klines

    def fetch_orderbook(self, symbol: str, depth: int = 10) -> UnifiedOrderbook:
        inst_id = self._to_exchange_symbol(symbol)
        data = self._request("/api/v5/market/books", {"instId": inst_id, "sz": str(min(depth, 400))})
        if not data:
            raise ValueError(f"No OKX orderbook data for {inst_id}")
        raw = data[0]
        bids = raw.get("bids") or []
        asks = raw.get("asks") or []
        best_bid = self._decimal(bids[0][0]) if bids else Decimal("0")
        best_ask = self._decimal(asks[0][0]) if asks else Decimal("0")
        bid_depth = sum((self._decimal(row[1]) for row in bids[:10]), Decimal("0"))
        ask_depth = sum((self._decimal(row[1]) for row in asks[:10]), Decimal("0"))
        mid = (best_bid + best_ask) / Decimal("2")
        spread = best_ask - best_bid
        return UnifiedOrderbook(
            exchange="okx",
            symbol=symbol.upper(),
            timestamp=self._int_ms(raw.get("ts")),
            best_bid=best_bid,
            best_ask=best_ask,
            bid_depth_sum=bid_depth,
            ask_depth_sum=ask_depth,
            spread=spread,
            spread_bps=(spread / mid * Decimal("10000")) if mid > 0 else Decimal("0"),
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

    def fetch_funding_rate(self, symbol: str) -> UnifiedFunding:
        inst_id = self._to_exchange_symbol(symbol)
        data = self._request("/api/v5/public/funding-rate", {"instId": inst_id})
        if not data:
            raise ValueError(f"No OKX funding data for {inst_id}")
        item = data[0]
        mark_price = None
        try:
            mark_price = self._decimal(self.fetch_mark_price(symbol).get("markPx"))
        except Exception:
            pass
        return UnifiedFunding(
            exchange="okx",
            symbol=symbol.upper(),
            timestamp=self._int_ms(item.get("ts") or item.get("fundingTime")),
            funding_rate=self._decimal(item.get("fundingRate")),
            next_funding_time=self._int_ms(item.get("nextFundingTime") or item.get("fundingTime")),
            mark_price=mark_price,
        )

    def fetch_funding_history(
        self,
        symbol: str,
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[UnifiedFunding]:
        params: Dict[str, Any] = {"instId": self._to_exchange_symbol(symbol), "limit": str(min(limit, 100))}
        if start_time:
            params["before"] = str(start_time)
        if end_time:
            params["after"] = str(end_time)
        results = [
            UnifiedFunding(
                exchange="okx",
                symbol=symbol.upper(),
                timestamp=self._int_ms(item.get("fundingTime")),
                funding_rate=self._decimal(item.get("realizedRate") or item.get("fundingRate")),
            )
            for item in self._request("/api/v5/public/funding-rate-history", params)
            if isinstance(item, dict)
        ]
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
        data = self._request(
            "/api/v5/rubik/stat/contracts/open-interest-volume",
            {"ccy": self._coin_from_symbol(symbol), "period": self._rubik_period(interval)},
        )
        results: List[UnifiedOpenInterest] = []
        for row in data[:limit]:
            if not isinstance(row, list) or len(row) < 2:
                continue
            ts = self._int_ms(row[0])
            if start_time and ts < start_time:
                continue
            if end_time and ts > end_time:
                continue
            oi_usd = self._decimal(row[1])
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
        data = self._request(
            "/api/v5/rubik/stat/contracts/long-short-account-ratio",
            {"ccy": self._coin_from_symbol(symbol), "period": self._rubik_period(interval)},
        )
        results: List[UnifiedSentiment] = []
        for row in data[:limit]:
            if not isinstance(row, list) or len(row) < 2:
                continue
            ts = self._int_ms(row[0])
            if start_time and ts < start_time:
                continue
            if end_time and ts > end_time:
                continue
            ratio = self._decimal(row[1])
            denominator = Decimal("1") + ratio
            results.append(
                UnifiedSentiment(
                    exchange="okx",
                    symbol=symbol.upper(),
                    timestamp=ts,
                    long_ratio=ratio / denominator if denominator > 0 else Decimal("0"),
                    short_ratio=Decimal("1") / denominator if denominator > 0 else Decimal("0"),
                    long_short_ratio=ratio,
                )
            )
        results.sort(key=lambda item: item.timestamp)
        return results

    def fetch_taker_volume_history(self, symbol: str, interval: str = "5m", limit: int = 100) -> List[Dict[str, Any]]:
        data = self._request(
            "/api/v5/rubik/stat/taker-volume",
            {"ccy": self._coin_from_symbol(symbol), "instType": "CONTRACTS", "period": self._rubik_period(interval)},
        )
        results: List[Dict[str, Any]] = []
        for row in data[:limit]:
            if not isinstance(row, list) or len(row) < 3:
                continue
            results.append(
                {
                    "exchange": "okx",
                    "symbol": symbol.upper(),
                    "timestamp": self._int_ms(row[0]),
                    "taker_sell_notional": self._decimal(row[1]),
                    "taker_buy_notional": self._decimal(row[2]),
                }
            )
        results.sort(key=lambda item: int(item["timestamp"]))
        return results

    @staticmethod
    def _rubik_period(interval: str) -> str:
        return {"5m": "5m", "15m": "5m", "30m": "5m", "1h": "1H", "4h": "1H", "1d": "1D"}.get(
            interval,
            "5m",
        )

    def get_supported_intervals(self) -> List[str]:
        return ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "3d", "1w", "1M"]
