from typing import Dict, List, Any
import logging
from .hyperliquid_market_data import (
    get_last_price_from_hyperliquid,
    get_kline_data_from_hyperliquid,
    get_market_status_from_hyperliquid,
    get_all_symbols_from_hyperliquid,
    get_ticker_data_from_hyperliquid,
    get_default_hyperliquid_client,
)

logger = logging.getLogger(__name__)


_PERIOD_SECONDS = {
    "1m": 60,
    "3m": 3 * 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
    "2h": 2 * 60 * 60,
    "4h": 4 * 60 * 60,
    "6h": 6 * 60 * 60,
    "8h": 8 * 60 * 60,
    "12h": 12 * 60 * 60,
    "1d": 24 * 60 * 60,
    "3d": 3 * 24 * 60 * 60,
    "1w": 7 * 24 * 60 * 60,
    "1M": 30 * 24 * 60 * 60,
}


def _load_local_exchange_klines(
    exchange: str,
    symbol: str,
    period: str,
    count: int,
    environment: str,
) -> List[Dict[str, Any]]:
    """Load persisted exchange K-lines before falling back to rate-limited REST."""
    import time
    from datetime import datetime, timezone
    from sqlalchemy import desc
    from database.connection import SessionLocal
    from database.models import CryptoKline

    with SessionLocal() as db:
        rows = (
            db.query(CryptoKline)
            .filter(
                CryptoKline.exchange == exchange,
                CryptoKline.symbol == symbol.upper(),
                CryptoKline.market == "CRYPTO",
                CryptoKline.period == period,
                CryptoKline.environment == environment,
            )
            .order_by(desc(CryptoKline.timestamp))
            .limit(max(1, count))
            .all()
        )

    if not rows:
        return []

    rows = list(reversed(rows))
    latest_ts = int(rows[-1].timestamp)
    period_seconds = _PERIOD_SECONDS.get(period, 60 * 60)
    if int(time.time()) - latest_ts > period_seconds * 3:
        logger.info(
            "Local %s K-lines stale for %s/%s: latest=%s",
            exchange,
            symbol,
            period,
            latest_ts,
        )
        return []

    data: List[Dict[str, Any]] = []
    for row in rows:
        dt = row.datetime_str or datetime.fromtimestamp(
            int(row.timestamp),
            tz=timezone.utc,
        ).isoformat()
        open_price = float(row.open_price) if row.open_price is not None else None
        close_price = float(row.close_price) if row.close_price is not None else None
        change = None
        percent = None
        if open_price not in (None, 0) and close_price is not None:
            change = close_price - open_price
            percent = change / open_price * 100

        data.append({
            "timestamp": int(row.timestamp),
            "datetime": dt,
            "open": open_price,
            "high": float(row.high_price) if row.high_price is not None else None,
            "low": float(row.low_price) if row.low_price is not None else None,
            "close": close_price,
            "volume": float(row.volume) if row.volume is not None else None,
            "amount": float(row.amount) if row.amount is not None else None,
            "chg": float(row.change) if row.change is not None else change,
            "percent": float(row.percent) if row.percent is not None else percent,
        })

    return data


def _load_local_binance_klines(
    symbol: str,
    period: str,
    count: int,
    environment: str,
) -> List[Dict[str, Any]]:
    """Load persisted Binance K-lines before falling back to rate-limited REST."""
    return _load_local_exchange_klines("binance", symbol, period, count, environment)


def get_last_price(symbol: str, market: str = "CRYPTO", environment: str = "mainnet") -> float:
    key = f"{symbol}.{market}.{environment}"

    # Check cache first (environment-specific)
    from .price_cache import get_cached_price, cache_price
    cached_price = get_cached_price(symbol, market, environment)
    if cached_price is not None:
        logger.debug(f"Using cached price for {key}: {cached_price}")
        return cached_price

    logger.info(f"Getting real-time price for {key} from API ({environment})...")

    if market.lower() == "binance":
        try:
            from services.exchanges.binance_adapter import BinanceAdapter
            adapter = BinanceAdapter(environment=environment)
            price = adapter.fetch_price(symbol)
            logger.info(f"Got real-time price for {key} from Binance ({environment}): {price}")
            cache_price(symbol, market, price, environment)
            return price
        except Exception as bn_err:
            logger.error(f"Failed to get price from Binance ({environment}): {bn_err}")
            raise Exception(f"Unable to get real-time price for {key}: {bn_err}")

    if market.lower() == "okx":
        try:
            from services.exchanges.okx_adapter import OKXAdapter
            adapter = OKXAdapter(environment=environment)
            price = adapter.fetch_price(symbol)
            logger.info(f"Got real-time price for {key} from OKX ({environment}): {price}")
            cache_price(symbol, market, price, environment)
            return price
        except Exception as okx_err:
            logger.error(f"Failed to get price from OKX ({environment}): {okx_err}")
            raise Exception(f"Unable to get real-time price for {key}: {okx_err}")

    try:
        price = get_last_price_from_hyperliquid(symbol, environment)
        if price and price > 0:
            logger.info(f"Got real-time price for {key} from Hyperliquid ({environment}): {price}")
            cache_price(symbol, market, price, environment)
            return price
        raise Exception(f"Hyperliquid returned invalid price: {price}")
    except Exception as hl_err:
        logger.error(f"Failed to get price from Hyperliquid ({environment}): {hl_err}")
        raise Exception(f"Unable to get real-time price for {key}: {hl_err}")


def get_kline_data(symbol: str, market: str = "CRYPTO", period: str = "1d", count: int = 100, environment: str = "mainnet", persist: bool = True) -> List[Dict[str, Any]]:
    key = f"{symbol}.{market}.{environment}"

    # Route to appropriate exchange based on market parameter
    if market.lower() == "binance":
        try:
            local_data = _load_local_binance_klines(symbol, period, count, environment)
        except Exception as local_err:
            logger.debug("Unable to load local Binance K-lines for %s/%s: %s", symbol, period, local_err)
            local_data = []
        if local_data:
            logger.info(
                "Got K-line data for %s from local Binance store (%s), total %d items",
                key,
                environment,
                len(local_data),
            )
            return local_data

        try:
            from services.exchanges.binance_adapter import BinanceAdapter
            from datetime import datetime

            adapter = BinanceAdapter(environment=environment)
            unified_klines = adapter.fetch_klines(symbol, period, limit=count)

            # Convert UnifiedKline to dict format expected by technical indicators
            data = []
            for kline in unified_klines:
                data.append({
                    'timestamp': kline.timestamp,  # Already in seconds from adapter
                    'datetime': datetime.fromtimestamp(kline.timestamp),
                    'open': float(kline.open_price),
                    'high': float(kline.high_price),
                    'low': float(kline.low_price),
                    'close': float(kline.close_price),
                    'volume': float(kline.volume),
                    'amount': float(kline.quote_volume),
                    'chg': None,
                    'percent': None
                })

            if data:
                if persist:
                    try:
                        from database.connection import SessionLocal
                        from services.exchanges.data_persistence import ExchangeDataPersistence

                        with SessionLocal() as db:
                            persistence = ExchangeDataPersistence(db)
                            persistence.save_klines(unified_klines, environment=environment)
                            try:
                                persistence.save_taker_volumes_from_klines(unified_klines)
                            except Exception as flow_err:
                                logger.debug(
                                    "Unable to persist taker-volume backup for %s/%s: %s",
                                    symbol,
                                    period,
                                    flow_err,
                                )
                    except Exception as persist_err:
                        logger.warning(
                            "Fetched Binance K-lines for %s/%s but failed to persist them: %s",
                            symbol,
                            period,
                            persist_err,
                        )
                logger.info(f"Got K-line data for {key} from Binance ({environment}), total {len(data)} items")
                return data
            raise Exception("Binance returned empty K-line data")
        except Exception as bn_err:
            logger.error(f"Failed to get K-line data from Binance ({environment}): {bn_err}")
            raise Exception(f"Unable to get K-line data for {key}: {bn_err}")
    elif market.lower() == "okx":
        try:
            local_data = _load_local_exchange_klines("okx", symbol, period, count, environment)
        except Exception as local_err:
            logger.debug("Unable to load local OKX K-lines for %s/%s: %s", symbol, period, local_err)
            local_data = []
        if local_data:
            logger.info(
                "Got K-line data for %s from local OKX store (%s), total %d items",
                key,
                environment,
                len(local_data),
            )
            return local_data

        try:
            from services.exchanges.okx_adapter import OKXAdapter
            from datetime import datetime

            adapter = OKXAdapter(environment=environment)
            unified_klines = adapter.fetch_klines(symbol, period, limit=count)

            data = []
            for kline in unified_klines:
                data.append({
                    'timestamp': kline.timestamp,
                    'datetime': datetime.fromtimestamp(kline.timestamp),
                    'open': float(kline.open_price),
                    'high': float(kline.high_price),
                    'low': float(kline.low_price),
                    'close': float(kline.close_price),
                    'volume': float(kline.volume),
                    'amount': float(kline.quote_volume),
                    'chg': None,
                    'percent': None
                })

            if data:
                if persist:
                    try:
                        from database.connection import SessionLocal
                        from services.exchanges.data_persistence import ExchangeDataPersistence

                        with SessionLocal() as db:
                            persistence = ExchangeDataPersistence(db)
                            persistence.save_klines(unified_klines, environment=environment)
                    except Exception as persist_err:
                        logger.warning(
                            "Fetched OKX K-lines for %s/%s but failed to persist them: %s",
                            symbol,
                            period,
                            persist_err,
                        )
                logger.info(f"Got K-line data for {key} from OKX ({environment}), total {len(data)} items")
                return data
            raise Exception("OKX returned empty K-line data")
        except Exception as okx_err:
            logger.error(f"Failed to get K-line data from OKX ({environment}): {okx_err}")
            raise Exception(f"Unable to get K-line data for {key}: {okx_err}")
    else:
        # Default to Hyperliquid
        try:
            data = get_kline_data_from_hyperliquid(symbol, period, count, persist=persist, environment=environment)
            if data:
                logger.info(f"Got K-line data for {key} from Hyperliquid ({environment}), total {len(data)} items")
                return data
            raise Exception("Hyperliquid returned empty K-line data")
        except Exception as hl_err:
            logger.error(f"Failed to get K-line data from Hyperliquid ({environment}): {hl_err}")
            raise Exception(f"Unable to get K-line data for {key}: {hl_err}")


def get_market_status(symbol: str, market: str = "CRYPTO") -> Dict[str, Any]:
    key = f"{symbol}.{market}"
    normalized_market = (market or "").lower()

    def _now_ms() -> int:
        import time

        return int(time.time() * 1000)

    if normalized_market == "okx":
        try:
            from services.exchanges.okx_adapter import OKXAdapter

            adapter = OKXAdapter()
            ticker = adapter.fetch_ticker(symbol)
            inst_id = ticker.get("instId") or adapter._symbol_to_okx(symbol)
            timestamp = int(ticker.get("ts") or _now_ms())
            status = {
                "market_status": "OPEN",
                "is_trading": True,
                "symbol": inst_id,
                "market": "okx",
                "exchange": "OKX",
                "market_type": "crypto_perp",
                "base_currency": inst_id.split("-")[0] if "-" in inst_id else symbol.upper(),
                "quote_currency": "USDT",
                "active": True,
                "timestamp": timestamp,
            }
            logger.info(f"Retrieved market status for {key} from OKX: {status.get('market_status')}")
            return status
        except Exception as okx_err:
            logger.error(f"Failed to get OKX market status: {okx_err}")
            raise Exception(f"Unable to get market status for {key}: {okx_err}")

    try:
        status = get_market_status_from_hyperliquid(symbol)
        status.setdefault("timestamp", _now_ms())
        status.setdefault("market", market)
        logger.info(f"Retrieved market status for {key} from Hyperliquid: {status.get('market_status')}")
        return status
    except Exception as hl_err:
        logger.error(f"Failed to get market status: {hl_err}")
        raise Exception(f"Unable to get market status for {key}: {hl_err}")


def get_all_symbols() -> List[str]:
    """Get all available trading pairs"""
    try:
        symbols = get_all_symbols_from_hyperliquid()
        logger.info(f"Got {len(symbols)} trading pairs from Hyperliquid")
        return symbols
    except Exception as hl_err:
        logger.error(f"Failed to get trading pairs list: {hl_err}")
        return ['BTC/USD', 'ETH/USD', 'SOL/USD']  # default trading pairs


def get_ticker_data(symbol: str, market: str = "CRYPTO", environment: str = "mainnet") -> Dict[str, Any]:
    """Get complete ticker data including 24h change and volume"""
    key = f"{symbol}.{market}.{environment}"
    logger.info(f"[DEBUG] get_ticker_data called for {key} in {environment}")

    # Route to Binance if market is binance
    if market.lower() == "binance":
        try:
            from services.exchanges.binance_adapter import BinanceAdapter
            adapter = BinanceAdapter(environment=environment)
            exchange_symbol = adapter._to_exchange_symbol(symbol)

            # Fetch 24h ticker data from Binance
            ticker = adapter._request("/fapi/v1/ticker/24hr", {"symbol": exchange_symbol})

            # Fetch OI
            oi_data = adapter.fetch_open_interest(symbol)
            open_interest_value = float(oi_data.open_interest) * float(ticker.get('lastPrice', 0)) if oi_data else 0

            # Fetch real-time funding rate using premiumIndex API
            funding_rate = 0
            try:
                premium_data = adapter.fetch_premium_index(symbol)
                funding_rate = float(premium_data["funding_rate"]) if premium_data else 0
            except Exception as e:
                logger.warning(f"Failed to fetch premium index for {symbol}: {e}")

            return {
                'symbol': symbol,
                'price': float(ticker.get('lastPrice', 0)),
                'oracle_price': float(ticker.get('lastPrice', 0)),  # Binance doesn't have oracle price
                'change24h': float(ticker.get('priceChange', 0)),
                'volume24h': float(ticker.get('quoteVolume', 0)),
                'percentage24h': float(ticker.get('priceChangePercent', 0)),
                'open_interest': open_interest_value,
                'funding_rate': funding_rate,
            }
        except Exception as e:
            logger.error(f"Failed to get ticker data from Binance ({environment}): {e}")
            raise Exception(f"Unable to get ticker data for {key}: {e}")

    if market.lower() == "okx":
        try:
            from services.exchanges.okx_adapter import OKXAdapter

            adapter = OKXAdapter(environment=environment)
            ticker = adapter.fetch_ticker(symbol)
            last_price = float(ticker.get("last") or 0)
            open_24h = float(ticker.get("open24h") or 0)
            change_24h = last_price - open_24h if open_24h else 0
            pct_24h = (change_24h / open_24h * 100) if open_24h else 0

            open_interest_value = 0
            funding_rate = 0
            mark_price = 0
            index_price = 0
            try:
                oi_data = adapter.fetch_open_interest(symbol)
                open_interest_value = float(oi_data.open_interest_value or 0)
                if not open_interest_value and last_price:
                    open_interest_value = float(oi_data.open_interest) * last_price
            except Exception as oi_err:
                logger.warning(f"Failed to fetch OKX open interest for {symbol}: {oi_err}")

            try:
                funding_data = adapter.fetch_funding_rate(symbol)
                funding_rate = float(funding_data.funding_rate) if funding_data else 0
                mark_price = float(funding_data.mark_price or 0) if funding_data else 0
            except Exception as funding_err:
                logger.warning(f"Failed to fetch OKX funding for {symbol}: {funding_err}")

            try:
                mark = adapter.fetch_mark_price(symbol)
                mark_price = float(mark.get("markPx") or mark_price or 0)
            except Exception as mark_err:
                logger.debug(f"Failed to fetch OKX mark price for {symbol}: {mark_err}")

            try:
                index = adapter.fetch_index_ticker(symbol)
                index_price = float(index.get("idxPx") or 0)
            except Exception as index_err:
                logger.debug(f"Failed to fetch OKX index ticker for {symbol}: {index_err}")

            return {
                'symbol': symbol,
                'price': last_price,
                'oracle_price': index_price or mark_price or last_price,
                'change24h': change_24h,
                'volume24h': float(ticker.get("volCcy24h") or ticker.get("vol24h") or 0),
                'percentage24h': pct_24h,
                'open_interest': open_interest_value,
                'funding_rate': funding_rate,
                'mark_price': mark_price,
                'index_price': index_price,
            }
        except Exception as e:
            logger.error(f"Failed to get ticker data from OKX ({environment}): {e}")
            raise Exception(f"Unable to get ticker data for {key}: {e}")

    try:
        logger.info(f"[DEBUG] Calling get_ticker_data_from_hyperliquid for {symbol} in {environment}")
        ticker_data = get_ticker_data_from_hyperliquid(symbol, environment)
        logger.info(f"[DEBUG] get_ticker_data_from_hyperliquid returned: {ticker_data}")
        if ticker_data:
            logger.info(f"Got ticker data for {key}: price={ticker_data['price']}, change24h={ticker_data['change24h']}")
            return ticker_data
        raise Exception("Hyperliquid returned empty ticker data")
    except Exception as hl_err:
        logger.error(f"Failed to get ticker data from Hyperliquid ({environment}): {hl_err}")
        # Fallback to price-only data
        logger.info(f"[DEBUG] Falling back to price-only data for {key}")
        try:
            price = get_last_price(symbol, market, environment)
            fallback_data = {
                'symbol': symbol,
                'price': price,
                'change24h': 0,
                'volume24h': 0,
                'percentage24h': 0,
            }
            logger.info(f"[DEBUG] Returning fallback data for {key}: {fallback_data}")
            return fallback_data
        except Exception:
            raise Exception(f"Unable to get ticker data for {key}: {hl_err}")
