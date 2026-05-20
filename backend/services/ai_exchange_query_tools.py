"""
Shared read-only exchange API query tools for AI services.

These tools intentionally expose market/account query data only. They do not
place orders, update configuration, or return API secrets.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SUPPORTED_EXCHANGE_QUERY_EXCHANGES = {"binance", "okx"}
SUPPORTED_EXCHANGE_QUERY_ALIASES = {"oke": "okx", "OKX": "okx"}


EXCHANGE_QUERY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_exchange_public_data",
            "description": (
                "Read live public futures/swap market data from Binance or OKX. "
                "Returns ticker/price, K-lines, orderbook, funding, open interest, "
                "sentiment/long-short data where supported, recent trades, and optional histories."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "exchange": {
                        "type": "string",
                        "enum": ["binance", "okx", "oke"],
                        "description": "Exchange to query. 'oke' is accepted as an alias for OKX."
                    },
                    "symbol": {"type": "string", "description": "Trading symbol, e.g. BTC or ETH"},
                    "period": {
                        "type": "string",
                        "enum": ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"],
                        "description": "K-line/history period. Default: 1h."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "K-line/history row limit. Default: 50, max: 200."
                    },
                    "depth": {
                        "type": "integer",
                        "description": "Orderbook depth. Default: 10, max: 50."
                    },
                    "trades": {
                        "type": "integer",
                        "description": "Recent public trades limit. Default: 50, max: 100."
                    },
                    "include_history": {
                        "type": "boolean",
                        "description": "Include funding/OI/sentiment/taker-volume history where supported. Default: true."
                    },
                    "environment": {
                        "type": "string",
                        "enum": ["mainnet", "testnet"],
                        "description": "Environment for the exchange adapter. Default: mainnet."
                    }
                },
                "required": ["exchange", "symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_exchange_instruments",
            "description": (
                "List available Binance futures or OKX swap instruments/tickers. "
                "Use this to discover valid symbols before querying market data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "exchange": {
                        "type": "string",
                        "enum": ["binance", "okx", "oke"],
                        "description": "Exchange to query. 'oke' is accepted as an alias for OKX."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of instruments/tickers to return. Default: 100, max: 500."
                    },
                    "inst_type": {
                        "type": "string",
                        "description": "OKX instrument type. Default: SWAP."
                    },
                    "uly": {
                        "type": "string",
                        "description": "Optional OKX underlying filter, e.g. BTC-USDT."
                    },
                    "inst_family": {
                        "type": "string",
                        "description": "Optional OKX instrument family filter."
                    }
                },
                "required": ["exchange"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_exchange_account_data",
            "description": (
                "Read configured exchange account data without exposing credentials. "
                "Currently supports Binance Futures wallets: account summary, balance, positions, "
                "open orders, recent closed trades, income history, trading stats, and API rate limits."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "exchange": {
                        "type": "string",
                        "enum": ["binance", "okx", "oke"],
                        "description": "Exchange account to query. OKX private account data is not configured yet."
                    },
                    "account_id": {"type": "integer", "description": "AI Trader account ID"},
                    "environment": {
                        "type": "string",
                        "enum": ["mainnet", "testnet"],
                        "description": "Trading environment. Defaults to global trading mode."
                    },
                    "symbol": {
                        "type": "string",
                        "description": "Optional symbol filter for open orders."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Recent trades/income limit. Default: 20, max: 100."
                    }
                },
                "required": ["exchange", "account_id"]
            }
        }
    },
]


EXCHANGE_QUERY_TOOL_NAMES = {
    tool["function"]["name"] for tool in EXCHANGE_QUERY_TOOLS
}


def merge_tool_definitions(*tool_lists: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge tool definition lists by function name while preserving order."""
    merged: List[Dict[str, Any]] = []
    seen = set()
    for tool_list in tool_lists:
        for tool in tool_list or []:
            name = (tool.get("function") or {}).get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            merged.append(tool)
    return merged


def execute_exchange_query_tool(db: Optional[Session], tool_name: str, arguments: Dict[str, Any]) -> str:
    """Dispatch shared exchange query tools."""
    try:
        if tool_name == "get_exchange_public_data":
            return get_exchange_public_data(
                exchange=arguments.get("exchange", "binance"),
                symbol=arguments.get("symbol", "BTC"),
                period=arguments.get("period", "1h"),
                limit=arguments.get("limit", 50),
                depth=arguments.get("depth", 10),
                trades=arguments.get("trades", 50),
                include_history=arguments.get("include_history", True),
                environment=arguments.get("environment", "mainnet"),
            )
        if tool_name == "list_exchange_instruments":
            return list_exchange_instruments(
                exchange=arguments.get("exchange", "binance"),
                limit=arguments.get("limit", 100),
                inst_type=arguments.get("inst_type", "SWAP"),
                uly=arguments.get("uly"),
                inst_family=arguments.get("inst_family"),
            )
        if tool_name == "get_exchange_account_data":
            if db is None:
                return json.dumps({"error": "Database session not available"}, ensure_ascii=False)
            return get_exchange_account_data(
                db=db,
                exchange=arguments.get("exchange", "binance"),
                account_id=arguments.get("account_id"),
                environment=arguments.get("environment"),
                symbol=arguments.get("symbol"),
                limit=arguments.get("limit", 20),
            )
        return json.dumps({"error": f"Unknown exchange query tool: {tool_name}"}, ensure_ascii=False)
    except Exception as exc:
        logger.error("[exchange_query_tool] %s failed: %s", tool_name, exc, exc_info=True)
        return json.dumps({"error": str(exc), "_error_class": type(exc).__name__}, ensure_ascii=False)


def get_exchange_public_data(
    exchange: str,
    symbol: str,
    period: str = "1h",
    limit: int = 50,
    depth: int = 10,
    trades: int = 50,
    include_history: bool = True,
    environment: str = "mainnet",
) -> str:
    exchange = _normalize_exchange(exchange)
    symbol = _normalize_symbol(symbol)
    limit = _bounded_int(limit, default=50, minimum=1, maximum=200)
    depth = _bounded_int(depth, default=10, minimum=1, maximum=50)
    trades = _bounded_int(trades, default=50, minimum=1, maximum=100)
    environment = environment if environment in {"mainnet", "testnet"} else "mainnet"

    if exchange == "binance":
        data = _get_binance_public_data(symbol, period, limit, depth, trades, include_history, environment)
    elif exchange == "okx":
        data = _get_okx_public_data(symbol, period, limit, depth, trades, include_history, environment)
    else:
        data = {"error": f"Unsupported exchange: {exchange}", "supported": sorted(SUPPORTED_EXCHANGE_QUERY_EXCHANGES)}

    return _json_dumps(data)


def list_exchange_instruments(
    exchange: str,
    limit: int = 100,
    inst_type: str = "SWAP",
    uly: Optional[str] = None,
    inst_family: Optional[str] = None,
) -> str:
    exchange = _normalize_exchange(exchange)
    limit = _bounded_int(limit, default=100, minimum=1, maximum=500)

    if exchange == "binance":
        from services.exchanges.binance_adapter import BinanceAdapter

        adapter = BinanceAdapter(environment="mainnet")
        exchange_info = _safe_call(lambda: adapter._request("/fapi/v1/exchangeInfo"))
        ticker_rows = _safe_call(lambda: adapter._request("/fapi/v1/ticker/24hr"))
        symbols = []
        if isinstance(exchange_info.get("data"), dict):
            for row in exchange_info["data"].get("symbols", [])[:limit]:
                if row.get("contractType") != "PERPETUAL":
                    continue
                symbols.append({
                    "symbol": row.get("symbol"),
                    "base_asset": row.get("baseAsset"),
                    "quote_asset": row.get("quoteAsset"),
                    "status": row.get("status"),
                    "onboard_date": row.get("onboardDate"),
                    "price_precision": row.get("pricePrecision"),
                    "quantity_precision": row.get("quantityPrecision"),
                })
        return _json_dumps({
            "exchange": "binance",
            "type": "USDS-M futures",
            "symbols": symbols,
            "symbols_count": len(symbols),
            "tickers_sample": (ticker_rows.get("data") or [])[:limit] if isinstance(ticker_rows.get("data"), list) else [],
            "errors": _collect_section_errors(exchange_info, ticker_rows),
        })

    if exchange == "okx":
        from services.exchanges.okx_adapter import OKXAdapter

        adapter = OKXAdapter(environment="mainnet")
        instruments = _safe_call(lambda: adapter.fetch_instruments(inst_type=inst_type, uly=uly, inst_family=inst_family))
        tickers = _safe_call(lambda: adapter.fetch_tickers(inst_type=inst_type, uly=uly))
        return _json_dumps({
            "exchange": "okx",
            "type": inst_type,
            "instruments": (instruments.get("data") or [])[:limit] if isinstance(instruments.get("data"), list) else [],
            "tickers": (tickers.get("data") or [])[:limit] if isinstance(tickers.get("data"), list) else [],
            "errors": _collect_section_errors(instruments, tickers),
        })

    return _json_dumps({"error": f"Unsupported exchange: {exchange}"})


def get_exchange_account_data(
    db: Session,
    exchange: str,
    account_id: Optional[int],
    environment: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 20,
) -> str:
    exchange = _normalize_exchange(exchange)
    limit = _bounded_int(limit, default=20, minimum=1, maximum=100)

    if not account_id:
        return _json_dumps({"error": "account_id is required"})

    if exchange != "binance":
        return _json_dumps({
            "exchange": exchange,
            "account_id": account_id,
            "error": "Only Binance private account queries are configured. OKX currently exposes public market data only.",
        })

    from database.models import Account, BinanceWallet
    from services.binance_trading_client import BinanceTradingClient
    from services.hyperliquid_environment import get_global_trading_mode
    from utils.encryption import decrypt_private_key

    environment = environment or get_global_trading_mode(db)
    account = db.query(Account).filter(Account.id == account_id).first()
    wallet = db.query(BinanceWallet).filter(
        BinanceWallet.account_id == account_id,
        BinanceWallet.environment == environment,
        BinanceWallet.is_active == "true",
    ).first()
    if not wallet:
        return _json_dumps({
            "exchange": "binance",
            "account_id": account_id,
            "environment": environment,
            "error": f"No active Binance wallet for account {account_id} in {environment}",
        })

    client = BinanceTradingClient(
        api_key=decrypt_private_key(wallet.api_key_encrypted),
        secret_key=decrypt_private_key(wallet.secret_key_encrypted),
        environment=wallet.environment,
    )

    balance = _safe_call(client.get_balance)
    positions = _safe_call(lambda: client.get_positions(db, include_timing=True))
    open_orders = _safe_call(lambda: client.get_open_orders(db, symbol=symbol))
    recent_closed_trades = _safe_call(lambda: client.get_recent_closed_trades(db, limit=limit))
    income_history = _safe_call(lambda: client.get_income_history(limit=limit))
    trading_stats = _safe_call(lambda: client.get_trading_stats(db))
    rate_limit = _safe_call(client.get_rate_limit)

    return _json_dumps({
        "exchange": "binance",
        "account_id": account_id,
        "account_name": getattr(account, "name", None),
        "environment": environment,
        "wallet": {
            "configured": True,
            "max_leverage": getattr(wallet, "max_leverage", None),
            "default_leverage": getattr(wallet, "default_leverage", None),
            "rebate_working": getattr(wallet, "rebate_working", None),
        },
        "balance": balance.get("data"),
        "positions": positions.get("data") or [],
        "open_orders": open_orders.get("data") or [],
        "recent_closed_trades": recent_closed_trades.get("data") or [],
        "income_history": income_history.get("data") or [],
        "trading_stats": trading_stats.get("data"),
        "rate_limit": rate_limit.get("data"),
        "errors": _collect_section_errors(balance, positions, open_orders, recent_closed_trades, income_history, trading_stats, rate_limit),
    })


def build_decision_exchange_snapshot(
    symbols: Sequence[str],
    exchanges: Sequence[str] = ("binance", "okx"),
    period: str = "1h",
    per_symbol_limit: int = 20,
    max_symbols: int = 5,
    environment: str = "mainnet",
) -> Dict[str, Any]:
    """Build a bounded public API snapshot for AI Trader decision context."""
    normalized_symbols = []
    seen = set()
    for symbol in symbols or []:
        sym = _normalize_symbol(symbol)
        if not sym or sym in seen:
            continue
        seen.add(sym)
        normalized_symbols.append(sym)
        if len(normalized_symbols) >= max_symbols:
            break

    snapshot = {
        "generated_at_ms": int(time.time() * 1000),
        "note": (
            "Read-only public Binance/OKX API snapshot. Use this as supplemental market evidence; "
            "it contains no order placement capability and may be partially populated if an endpoint fails."
        ),
        "symbols": normalized_symbols,
        "exchanges": {},
    }

    for raw_exchange in exchanges:
        exchange = _normalize_exchange(raw_exchange)
        if exchange not in SUPPORTED_EXCHANGE_QUERY_EXCHANGES:
            continue
        exchange_data: Dict[str, Any] = {}
        for symbol in normalized_symbols:
            try:
                payload = json.loads(get_exchange_public_data(
                    exchange=exchange,
                    symbol=symbol,
                    period=period,
                    limit=per_symbol_limit,
                    depth=10,
                    trades=20,
                    include_history=True,
                    environment=environment,
                ))
            except Exception as exc:
                payload = {"error": str(exc), "_error_class": type(exc).__name__}
            exchange_data[symbol] = payload
        snapshot["exchanges"][exchange] = exchange_data

    return snapshot


def _get_binance_public_data(
    symbol: str,
    period: str,
    limit: int,
    depth: int,
    trades: int,
    include_history: bool,
    environment: str,
) -> Dict[str, Any]:
    from services.exchanges.binance_adapter import BinanceAdapter

    adapter = BinanceAdapter(environment=environment)
    exchange_symbol = adapter._to_exchange_symbol(symbol)

    price = _safe_call(lambda: adapter.fetch_price(symbol))
    ticker_24h = _safe_call(lambda: adapter._request("/fapi/v1/ticker/24hr", {"symbol": exchange_symbol}))
    premium_index = _safe_call(lambda: adapter.fetch_premium_index(symbol))
    klines = _safe_call(lambda: adapter.fetch_klines(symbol, period, limit=limit))
    orderbook = _safe_call(lambda: adapter.fetch_orderbook(symbol, depth=_normalize_binance_depth(depth)))
    funding = _safe_call(lambda: adapter.fetch_funding_rate(symbol))
    open_interest = _safe_call(lambda: adapter.fetch_open_interest(symbol))
    sentiment = _safe_call(lambda: adapter.fetch_sentiment(symbol))
    recent_trades = _safe_call(lambda: adapter._request("/fapi/v1/aggTrades", {"symbol": exchange_symbol, "limit": trades}))

    payload = {
        "exchange": "binance",
        "environment": environment,
        "symbol": symbol,
        "exchange_symbol": exchange_symbol,
        "price": price.get("data"),
        "ticker_24h": ticker_24h.get("data"),
        "premium_index": premium_index.get("data"),
        "klines": klines.get("data") or [],
        "orderbook": orderbook.get("data"),
        "funding": funding.get("data"),
        "open_interest": open_interest.get("data"),
        "sentiment": sentiment.get("data"),
        "recent_trades": recent_trades.get("data") or [],
    }

    history_sections = []
    if include_history:
        funding_history = _safe_call(lambda: adapter.fetch_funding_history(symbol, limit=limit))
        oi_history = _safe_call(lambda: adapter.fetch_open_interest_history(symbol, period, limit=limit))
        sentiment_history = _safe_call(lambda: adapter.fetch_sentiment_history(symbol, period, limit=limit))
        payload.update({
            "funding_history": funding_history.get("data") or [],
            "open_interest_history": oi_history.get("data") or [],
            "sentiment_history": sentiment_history.get("data") or [],
        })
        history_sections = [funding_history, oi_history, sentiment_history]

    payload["errors"] = _collect_section_errors(
        price, ticker_24h, premium_index, klines, orderbook, funding,
        open_interest, sentiment, recent_trades, *history_sections,
    )
    return payload


def _get_okx_public_data(
    symbol: str,
    period: str,
    limit: int,
    depth: int,
    trades: int,
    include_history: bool,
    environment: str,
) -> Dict[str, Any]:
    from services.exchanges.okx_adapter import OKXAdapter

    adapter = OKXAdapter(environment=environment)
    exchange_symbol = adapter._to_exchange_symbol(symbol)

    ticker = _safe_call(lambda: adapter.fetch_ticker(symbol))
    mark_price = _safe_call(lambda: adapter.fetch_mark_price(symbol))
    index_ticker = _safe_call(lambda: adapter.fetch_index_ticker(symbol))
    klines = _safe_call(lambda: adapter.fetch_klines(symbol, period, limit=limit))
    orderbook = _safe_call(lambda: adapter.fetch_orderbook(symbol, depth=depth))
    funding = _safe_call(lambda: adapter.fetch_funding_rate(symbol))
    open_interest = _safe_call(lambda: adapter.fetch_open_interest(symbol))
    sentiment = _safe_call(lambda: adapter.fetch_sentiment(symbol))
    recent_trades = _safe_call(lambda: adapter.fetch_recent_trades(symbol, limit=trades))

    payload = {
        "exchange": "okx",
        "environment": environment,
        "symbol": symbol,
        "exchange_symbol": exchange_symbol,
        "ticker": ticker.get("data"),
        "mark_price": mark_price.get("data"),
        "index_ticker": index_ticker.get("data"),
        "klines": klines.get("data") or [],
        "orderbook": orderbook.get("data"),
        "funding": funding.get("data"),
        "open_interest": open_interest.get("data"),
        "sentiment": sentiment.get("data"),
        "recent_trades": recent_trades.get("data") or [],
    }

    history_sections = []
    if include_history:
        funding_history = _safe_call(lambda: adapter.fetch_funding_history(symbol, limit=limit))
        oi_history = _safe_call(lambda: adapter.fetch_open_interest_history(symbol, period, limit=limit))
        sentiment_history = _safe_call(lambda: adapter.fetch_sentiment_history(symbol, period, limit=limit))
        taker_volume = _safe_call(lambda: adapter.fetch_taker_volume_history(symbol, period, limit=limit))
        payload.update({
            "funding_history": funding_history.get("data") or [],
            "open_interest_history": oi_history.get("data") or [],
            "sentiment_history": sentiment_history.get("data") or [],
            "taker_volume_history": taker_volume.get("data") or [],
        })
        history_sections = [funding_history, oi_history, sentiment_history, taker_volume]

    payload["errors"] = _collect_section_errors(
        ticker, mark_price, index_ticker, klines, orderbook, funding,
        open_interest, sentiment, recent_trades, *history_sections,
    )
    return payload


def _safe_call(func) -> Dict[str, Any]:
    try:
        return {"data": _to_jsonable(func())}
    except Exception as exc:
        logger.warning("[exchange_query] section failed: %s", exc)
        return {"error": str(exc), "_error_class": type(exc).__name__}


def _collect_section_errors(*sections: Dict[str, Any]) -> List[Dict[str, str]]:
    errors = []
    for section in sections:
        if not isinstance(section, dict) or "error" not in section:
            continue
        errors.append({
            "error": str(section.get("error")),
            "_error_class": str(section.get("_error_class") or "Exception"),
        })
    return errors


def _normalize_exchange(exchange: str) -> str:
    value = str(exchange or "").strip().lower()
    return SUPPORTED_EXCHANGE_QUERY_ALIASES.get(value, value)


def _normalize_symbol(symbol: str) -> str:
    value = str(symbol or "BTC").strip().upper()
    if value.endswith("USDT"):
        value = value[:-4]
    if value.endswith("-USDT-SWAP"):
        value = value[:-10]
    return value or "BTC"


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _normalize_binance_depth(depth: int) -> int:
    """Binance depth endpoint accepts fixed buckets only."""
    for bucket in (5, 10, 20, 50, 100, 500, 1000):
        if depth <= bucket:
            return bucket
    return 1000


def _to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(_to_jsonable(value), indent=2, sort_keys=True, ensure_ascii=False, default=str)
