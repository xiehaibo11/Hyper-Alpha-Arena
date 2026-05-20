"""Read-only Binance USDS-M Futures API tools for Hyper AI."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

BINANCE_INTERVALS = [
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1M",
]

PUBLIC_GET_ENDPOINTS = {
    "/fapi/v1/aggTrades",
    "/fapi/v1/assetIndex",
    "/fapi/v1/constituents",
    "/fapi/v1/continuousKlines",
    "/fapi/v1/depth",
    "/fapi/v1/exchangeInfo",
    "/fapi/v1/fundingInfo",
    "/fapi/v1/fundingRate",
    "/fapi/v1/historicalTrades",
    "/fapi/v1/indexPriceKlines",
    "/fapi/v1/klines",
    "/fapi/v1/markPriceKlines",
    "/fapi/v1/openInterest",
    "/fapi/v1/ping",
    "/fapi/v1/premiumIndex",
    "/fapi/v1/ticker/24hr",
    "/fapi/v1/ticker/bookTicker",
    "/fapi/v1/ticker/price",
    "/fapi/v1/time",
    "/fapi/v1/trades",
    "/futures/data/basis",
    "/futures/data/globalLongShortAccountRatio",
    "/futures/data/openInterestHist",
    "/futures/data/takerlongshortRatio",
    "/futures/data/topLongShortAccountRatio",
    "/futures/data/topLongShortPositionRatio",
}

SIGNED_READ_ENDPOINTS = {
    "/fapi/v1/accountConfig",
    "/fapi/v1/adlQuantile",
    "/fapi/v1/allAlgoOrders",
    "/fapi/v1/allOrders",
    "/fapi/v1/apiTradingStatus",
    "/fapi/v1/commissionRate",
    "/fapi/v1/forceOrders",
    "/fapi/v1/income",
    "/fapi/v1/leverageBracket",
    "/fapi/v1/openAlgoOrders",
    "/fapi/v1/openOrders",
    "/fapi/v1/order",
    "/fapi/v1/positionSide/dual",
    "/fapi/v1/rateLimit/order",
    "/fapi/v1/symbolConfig",
    "/fapi/v1/userTrades",
    "/fapi/v2/account",
    "/fapi/v2/balance",
    "/fapi/v2/positionRisk",
    "/fapi/v3/account",
    "/fapi/v3/balance",
    "/fapi/v3/positionRisk",
}

ALL_READ_ENDPOINTS = sorted(PUBLIC_GET_ENDPOINTS | SIGNED_READ_ENDPOINTS)

BINANCE_FULL_API_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_binance_api",
            "description": (
                "Query a read-only Binance USDS-M Futures GET API endpoint. Supports public market "
                "endpoints and signed account read endpoints. It never places orders, cancels "
                "orders, changes leverage, changes margin mode, or exposes API secrets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "endpoint": {
                        "type": "string",
                        "enum": ALL_READ_ENDPOINTS,
                        "description": "Exact Binance Futures API path to query.",
                    },
                    "params": {
                        "type": "object",
                        "description": "Query parameters for Binance. Use Binance symbols like BTCUSDT.",
                    },
                    "account_id": {
                        "type": "integer",
                        "description": "Required only for signed account read endpoints.",
                    },
                    "environment": {
                        "type": "string",
                        "enum": ["mainnet", "testnet"],
                        "description": "Exchange environment. Default: mainnet.",
                    },
                },
                "required": ["endpoint"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_binance_klines",
            "description": (
                "Fetch Binance USDS-M Futures K-lines using the complete Binance interval set: "
                "1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M. "
                "Supports standard, mark price, index price, and continuous contract K-lines."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Symbol such as BTC or BTCUSDT."},
                    "interval": {"type": "string", "enum": BINANCE_INTERVALS},
                    "limit": {"type": "integer", "description": "Rows to fetch. Max: 1500."},
                    "kline_type": {
                        "type": "string",
                        "enum": ["standard", "mark_price", "index_price", "continuous"],
                    },
                    "contract_type": {
                        "type": "string",
                        "enum": ["PERPETUAL", "CURRENT_MONTH", "NEXT_MONTH", "CURRENT_QUARTER", "NEXT_QUARTER"],
                        "description": "Only used for continuous K-lines.",
                    },
                    "start_time": {"type": "integer", "description": "Optional startTime in ms."},
                    "end_time": {"type": "integer", "description": "Optional endTime in ms."},
                    "environment": {"type": "string", "enum": ["mainnet", "testnet"]},
                },
                "required": ["symbol"],
            },
        },
    },
]

BINANCE_FULL_API_TOOL_NAMES = {
    tool["function"]["name"] for tool in BINANCE_FULL_API_TOOLS
}


def execute_binance_full_api_tool(db: Session, tool_name: str, arguments: Dict[str, Any]) -> str:
    if tool_name == "query_binance_api":
        return query_binance_api(db, arguments or {})
    if tool_name == "get_binance_klines":
        return get_binance_klines(arguments or {})
    return _json_dumps({"error": f"Unknown Binance API tool: {tool_name}"})


def query_binance_api(db: Session, arguments: Dict[str, Any]) -> str:
    endpoint = _normalize_endpoint(arguments.get("endpoint"))
    params = _normalize_params(arguments.get("params") or {})
    environment = _normalize_environment(arguments.get("environment"))

    if endpoint not in PUBLIC_GET_ENDPOINTS and endpoint not in SIGNED_READ_ENDPOINTS:
        return _json_dumps({
            "error": "Endpoint is not in the read-only Binance Futures whitelist.",
            "endpoint": endpoint,
            "allowed_endpoints": ALL_READ_ENDPOINTS,
        })

    params = _normalize_binance_symbols(params)
    signed = endpoint in SIGNED_READ_ENDPOINTS

    if signed:
        account_id = arguments.get("account_id")
        client = _get_signed_client(db, account_id, environment)
        data = client._request("GET", endpoint, params, signed=True)
        rate_limit = client.get_rate_limit()
    else:
        from services.exchanges.binance_adapter import BinanceAdapter

        adapter = BinanceAdapter(environment=environment)
        data = adapter._request(endpoint, params)
        rate_limit = None

    return _json_dumps({
        "exchange": "binance",
        "market": "USDS-M Futures",
        "environment": environment,
        "method": "GET",
        "endpoint": endpoint,
        "signed": signed,
        "params": params,
        "data": data,
        "rate_limit": rate_limit,
        "safety": "read_only_no_order_or_account_mutation",
    })


def get_binance_klines(arguments: Dict[str, Any]) -> str:
    symbol = _to_exchange_symbol(arguments.get("symbol") or "BTC")
    interval = str(arguments.get("interval") or "1h")
    if interval not in BINANCE_INTERVALS:
        return _json_dumps({"error": "Unsupported Binance interval", "supported": BINANCE_INTERVALS})

    limit = _bounded_int(arguments.get("limit"), default=200, minimum=1, maximum=1500)
    kline_type = str(arguments.get("kline_type") or "standard")
    environment = _normalize_environment(arguments.get("environment"))

    endpoint = {
        "standard": "/fapi/v1/klines",
        "mark_price": "/fapi/v1/markPriceKlines",
        "index_price": "/fapi/v1/indexPriceKlines",
        "continuous": "/fapi/v1/continuousKlines",
    }.get(kline_type)
    if not endpoint:
        return _json_dumps({"error": "Unsupported kline_type"})

    params: Dict[str, Any] = {"interval": interval, "limit": limit}
    if kline_type == "continuous":
        params["pair"] = symbol
        params["contractType"] = arguments.get("contract_type") or "PERPETUAL"
    elif kline_type == "index_price":
        params["pair"] = symbol
    else:
        params["symbol"] = symbol

    if arguments.get("start_time"):
        params["startTime"] = int(arguments["start_time"])
    if arguments.get("end_time"):
        params["endTime"] = int(arguments["end_time"])

    from services.exchanges.binance_adapter import BinanceAdapter

    adapter = BinanceAdapter(environment=environment)
    raw_rows = adapter._request(endpoint, params)

    return _json_dumps({
        "exchange": "binance",
        "market": "USDS-M Futures",
        "environment": environment,
        "endpoint": endpoint,
        "symbol": symbol,
        "interval": interval,
        "kline_type": kline_type,
        "count": len(raw_rows) if isinstance(raw_rows, list) else 0,
        "klines": _parse_kline_rows(raw_rows if isinstance(raw_rows, list) else []),
        "safety": "read_only_public_market_data",
    })


def _get_signed_client(db: Session, account_id: Optional[int], environment: str):
    if not account_id:
        raise ValueError("account_id is required for signed Binance read endpoints")

    from database.models import BinanceWallet
    from services.binance_trading_client import BinanceTradingClient
    from utils.encryption import decrypt_private_key

    wallet = db.query(BinanceWallet).filter(
        BinanceWallet.account_id == int(account_id),
        BinanceWallet.environment == environment,
        BinanceWallet.is_active == "true",
    ).first()
    if not wallet:
        raise ValueError(f"No active Binance wallet for account {account_id} in {environment}")

    return BinanceTradingClient(
        api_key=decrypt_private_key(wallet.api_key_encrypted),
        secret_key=decrypt_private_key(wallet.secret_key_encrypted),
        environment=wallet.environment,
    )


def _normalize_endpoint(endpoint: Any) -> str:
    text = str(endpoint or "").strip()
    return text if text.startswith("/") else f"/{text}"


def _normalize_environment(value: Any) -> str:
    return str(value or "mainnet").lower() if str(value or "mainnet").lower() in {"mainnet", "testnet"} else "mainnet"


def _normalize_params(params: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key, value in params.items():
        if key in {"signature", "timestamp", "recvWindow"}:
            continue
        if value is None:
            continue
        if key == "limit":
            normalized[key] = _bounded_int(value, default=100, minimum=1, maximum=1500)
        else:
            normalized[str(key)] = value
    return normalized


def _normalize_binance_symbols(params: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(params)
    for key in ("symbol", "pair"):
        if key in normalized:
            normalized[key] = _to_exchange_symbol(normalized[key])
    return normalized


def _to_exchange_symbol(symbol: Any) -> str:
    text = str(symbol or "BTC").strip().upper().replace("-", "")
    if text.endswith("USDT"):
        return text
    return f"{text}USDT"


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _parse_kline_rows(rows: list) -> list:
    parsed = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        parsed.append({
            "open_time": row[0],
            "open": row[1],
            "high": row[2],
            "low": row[3],
            "close": row[4],
            "volume": row[5],
            "close_time": row[6] if len(row) > 6 else None,
            "quote_volume": row[7] if len(row) > 7 else None,
            "trade_count": row[8] if len(row) > 8 else None,
            "taker_buy_base_volume": row[9] if len(row) > 9 else None,
            "taker_buy_quote_volume": row[10] if len(row) > 10 else None,
        })
    return parsed


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(_to_jsonable(value), ensure_ascii=False, indent=2, sort_keys=True, default=str)
