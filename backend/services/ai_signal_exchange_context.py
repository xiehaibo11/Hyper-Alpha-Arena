"""Runtime exchange context for AI signal generation."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from services.ai_exchange_query_tools import EXCHANGE_QUERY_TOOLS, EXCHANGE_QUERY_TOOL_NAMES, merge_tool_definitions

SUPPORTED_SIGNAL_EXCHANGES = {"binance", "hyperliquid"}


@dataclass(frozen=True)
class SignalExchangeContext:
    exchange: str
    label: str
    environment: str
    source: str
    account_id: Optional[int]
    account_name: Optional[str]
    user_id: Optional[int]


SIGNAL_SYSTEM_PROMPT_TEMPLATE = """You are an expert trading signal designer for cryptocurrency perpetual futures.
You have access to tools that query real market data. Use those tools before setting thresholds.

## CONFIGURED TRADING VENUE
- Current AI Trader: __ACCOUNT_LABEL__
- Bound exchange: __EXCHANGE_LABEL__ (`__DEFAULT_EXCHANGE__`)
- Environment: __ENVIRONMENT__
- Source: __EXCHANGE_SOURCE__

This exchange is already selected by the AI Trader/account binding. Do not ask the user to choose
a different venue. Use `__DEFAULT_EXCHANGE__` for market data tools and for every generated
`exchange` field.

## CORE CONCEPT: Signal Pools are TRIGGERS, not STRATEGIES
Signal pools detect market conditions and trigger the Trading AI to make decisions.
The Trading AI analyzes full market context and decides whether to buy/sell/hold.
Your job is to configure signals that detect the market conditions the user cares about.
Output one signal pool per request because the Trading AI can bind to one pool at a time.

## GUIDED CONVERSATION
Before using tools, ask only the missing strategy-design questions:
1. Direction: long, short, or both?
2. Timeframe and trigger frequency: e.g. 1m/3m, 5m/15m, 30m/1h; 1-4/day or more?
3. Market opportunity type: volume/OI surge, CVD/taker pressure, order book imbalance, volatility, or factors.

If the user already gave enough detail, proceed directly with tools. Do not ask which exchange to use.

## WORKFLOW
1. Use `get_indicators_batch` for 2-4 relevant indicators in one call.
2. Use `predict_signal_combination` before outputting a final config.
3. Optionally use `get_kline_context` to verify trigger quality.

Rules:
- Always pass `exchange="__DEFAULT_EXCHANGE__"` to signal tools.
- Always use the same exchange across all tool calls and output configs.
- Aim for 5-30 combined triggers over 7 days, roughly 1-4 triggers per day.
- If AND logic is too strict, relax thresholds or switch to OR.
- Never output signal configs without testing the combination first.

## AVAILABLE INDICATORS
Market flow indicators:
- oi_delta_percent: OI change percentage over a time window.
- funding_rate: funding-rate change in bps.
- cvd: cumulative volume delta, buyer/seller pressure.
- depth_ratio: bid/ask depth ratio.
- order_imbalance: normalized order book imbalance from -1 to +1.
- taker_buy_ratio: log(taker buy / taker sell), positive means buyers dominate.
- taker_volume: composite indicator with direction, ratio_threshold, and volume_threshold.
- price_change: percentage price change over the time window.
- volatility: high/low range percentage over the time window.

Factor indicators:
- Use `factor:<factor_name>` as the metric value.
- Factors are computed from K-line close data and trigger at K-line close boundaries.
- Good longer-timeframe examples include RSI, ADX, ATR, Bollinger, MA crossovers, and Z-score.

Operators:
- greater_than, less_than, greater_than_or_equal, less_than_or_equal, abs_greater_than.
- taker_volume uses direction + ratio_threshold + volume_threshold instead of operators.

Time windows:
- 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h.

Directional mapping:
- Long opportunities: buyer-dominated flow such as cvd > X, taker_buy_ratio > 0, order_imbalance > X.
- Short opportunities: seller-dominated flow such as cvd < -X, taker_buy_ratio < 0, order_imbalance < -X.
- Both directions: use abs_greater_than for magnitude-only activity.

## OUTPUT FORMAT

Single signal:
```signal-config
{
  "name": "BTC_OI_SURGE",
  "symbol": "BTC",
  "exchange": "__DEFAULT_EXCHANGE__",
  "description": "Detects significant OI increase",
  "trigger_condition": {
    "metric": "oi_delta_percent",
    "operator": "greater_than",
    "threshold": 1.0,
    "time_window": "5m"
  }
}
```

Signal pool, preferred for combined signals:
```signal-pool-config
{
  "name": "BTC_5M_MOMENTUM_SURGE",
  "symbol": "BTC",
  "exchange": "__DEFAULT_EXCHANGE__",
  "description": "Detects strong momentum with multiple confirmations",
  "logic": "AND",
  "signals": [
    {"metric": "cvd", "operator": "greater_than", "threshold": 10000000, "time_window": "5m"},
    {"metric": "order_imbalance", "operator": "greater_than", "threshold": 0.99, "time_window": "5m"},
    {"metric": "oi_delta_percent", "operator": "greater_than", "threshold": 0.3, "time_window": "5m"}
  ]
}
```

Taker-volume composite signal:
```signal-config
{
  "name": "BTC_TAKER_SURGE",
  "symbol": "BTC",
  "exchange": "__DEFAULT_EXCHANGE__",
  "description": "Detects strong taker volume dominance",
  "trigger_condition": {
    "metric": "taker_volume",
    "direction": "buy",
    "ratio_threshold": 1.5,
    "volume_threshold": 100000,
    "time_window": "5m"
  }
}
```

Factor signal:
```signal-config
{
  "name": "BTC_RSI_OVERSOLD",
  "symbol": "BTC",
  "exchange": "__DEFAULT_EXCHANGE__",
  "description": "RSI21 drops below 30",
  "trigger_condition": {
    "metric": "factor:RSI21",
    "operator": "less_than",
    "threshold": 30,
    "time_window": "1h"
  }
}
```

Always wrap final configurations in either ```signal-config or ```signal-pool-config.
"""


BASE_SIGNAL_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_kline_context",
            "description": "Get K-line price data around timestamps to verify whether triggers align with meaningful price movement.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Trading symbol, e.g., BTC, ETH"},
                    "timestamps": {"type": "array", "items": {"type": "integer"}, "description": "Unix timestamps in milliseconds"},
                    "time_window": {"type": "string", "enum": ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h"]},
                    "exchange": {"type": "string", "enum": ["hyperliquid", "binance"], "description": "Configured exchange for this AI Trader."},
                },
                "required": ["symbol", "timestamps", "time_window"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_indicators_batch",
            "description": "Get statistical distributions for multiple indicators from the configured exchange's market data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Trading symbol, e.g., BTC, ETH"},
                    "indicators": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Indicator names. Standard: oi_delta_percent, funding_rate, cvd, depth_ratio, order_imbalance, taker_buy_ratio, taker_volume, price_change, volatility. Factor: factor:<name>.",
                    },
                    "time_window": {"type": "string", "enum": ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h"]},
                    "exchange": {"type": "string", "enum": ["hyperliquid", "binance"], "description": "Configured exchange for this AI Trader."},
                },
                "required": ["symbol", "indicators", "time_window"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "predict_signal_combination",
            "description": "Predict trigger count for a proposed signal combination over the last 7 days on the configured exchange.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Trading symbol"},
                    "signals": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "indicator": {"type": "string", "description": "Metric name, including factor:<name> for factors."},
                                "operator": {"type": "string", "description": "For standard indicators only."},
                                "threshold": {"type": "number", "description": "For standard indicators only."},
                                "time_window": {"type": "string"},
                                "direction": {"type": "string", "enum": ["buy", "sell", "any"], "description": "For taker_volume only."},
                                "ratio_threshold": {"type": "number", "description": "For taker_volume only."},
                                "volume_threshold": {"type": "number", "description": "For taker_volume only."},
                            },
                            "required": ["indicator", "time_window"],
                        },
                    },
                    "logic": {"type": "string", "enum": ["AND", "OR"]},
                    "exchange": {"type": "string", "enum": ["hyperliquid", "binance"], "description": "Configured exchange for this AI Trader."},
                },
                "required": ["symbol", "signals", "logic"],
            },
        },
    },
]


def resolve_signal_exchange_context(
    db: Session,
    account: Optional[Any] = None,
    user_id: Optional[int] = None,
) -> SignalExchangeContext:
    from database.models import AccountStrategyConfig, BinanceWallet, HyperliquidWallet, UserExchangeConfig

    account_id = getattr(account, "id", None)
    account_user_id = getattr(account, "user_id", None)
    context_user_id = account_user_id or user_id
    exchange = None
    source = "default"

    if account_id:
        strategy = db.query(AccountStrategyConfig).filter(AccountStrategyConfig.account_id == account_id).first()
        exchange = _normalize_exchange(getattr(strategy, "exchange", None))
        if exchange:
            source = "AI Trader strategy binding"

    if not exchange and context_user_id:
        config = db.query(UserExchangeConfig).filter(UserExchangeConfig.user_id == context_user_id).first()
        exchange = _normalize_exchange(getattr(config, "selected_exchange", None))
        if exchange:
            source = "user selected exchange"

    has_binance_wallet = False
    has_hyperliquid_wallet = False
    environment = "mainnet"

    if account_id:
        binance_wallets = db.query(BinanceWallet).filter(
            BinanceWallet.account_id == account_id,
            BinanceWallet.is_active == "true",
        ).all()
        hyper_wallets = db.query(HyperliquidWallet).filter(
            HyperliquidWallet.account_id == account_id,
            HyperliquidWallet.is_active == "true",
        ).all()
        has_binance_wallet = bool(binance_wallets)
        has_hyperliquid_wallet = bool(hyper_wallets)

        wallet_for_exchange = None
        if exchange == "binance" and binance_wallets:
            wallet_for_exchange = _prefer_mainnet(binance_wallets)
        elif exchange == "hyperliquid" and hyper_wallets:
            wallet_for_exchange = _prefer_mainnet(hyper_wallets)
        elif not exchange and binance_wallets:
            exchange = "binance"
            source = "active Binance wallet"
            wallet_for_exchange = _prefer_mainnet(binance_wallets)
        elif not exchange and hyper_wallets:
            exchange = "hyperliquid"
            source = "active Hyperliquid wallet"
            wallet_for_exchange = _prefer_mainnet(hyper_wallets)

        if wallet_for_exchange and getattr(wallet_for_exchange, "environment", None):
            environment = wallet_for_exchange.environment

    if not exchange:
        exchange = "binance"
        source = "system default"

    label = "Binance USDS-M perpetual futures" if exchange == "binance" else "Hyperliquid perpetual futures"
    if exchange == "binance" and has_binance_wallet:
        label += " (live account configured)"
    elif exchange == "hyperliquid" and has_hyperliquid_wallet:
        label += " (wallet configured)"

    return SignalExchangeContext(
        exchange=exchange,
        label=label,
        environment=environment,
        source=source,
        account_id=account_id,
        account_name=getattr(account, "name", None),
        user_id=context_user_id,
    )


def build_signal_system_prompt(context: SignalExchangeContext) -> str:
    account_label = "none"
    if context.account_id:
        account_label = f"{context.account_name or 'AI Trader'} (id={context.account_id})"
    return (
        SIGNAL_SYSTEM_PROMPT_TEMPLATE
        .replace("__DEFAULT_EXCHANGE__", context.exchange)
        .replace("__EXCHANGE_LABEL__", context.label)
        .replace("__ENVIRONMENT__", context.environment)
        .replace("__EXCHANGE_SOURCE__", context.source)
        .replace("__ACCOUNT_LABEL__", account_label)
    )


def build_signal_tools(default_exchange: str) -> List[Dict[str, Any]]:
    signal_tools = copy.deepcopy(BASE_SIGNAL_TOOLS)
    exchange = _normalize_exchange(default_exchange) or "binance"
    for tool in signal_tools:
        props = ((tool.get("function") or {}).get("parameters") or {}).get("properties") or {}
        exchange_prop = props.get("exchange")
        if exchange_prop:
            exchange_prop["enum"] = [exchange]
            exchange_prop["description"] = f"Use the configured exchange: {exchange}."
    if exchange == "binance":
        query_tools = copy.deepcopy(EXCHANGE_QUERY_TOOLS)
        for tool in query_tools:
            props = ((tool.get("function") or {}).get("parameters") or {}).get("properties") or {}
            exchange_prop = props.get("exchange")
            if exchange_prop:
                exchange_prop["enum"] = ["binance"]
                exchange_prop["description"] = "Use the configured exchange: binance."
        return merge_tool_definitions(signal_tools, query_tools)
    return signal_tools


def prepare_signal_tool_arguments(
    tool_name: str,
    arguments: Optional[Dict[str, Any]],
    context: SignalExchangeContext,
) -> Dict[str, Any]:
    prepared = dict(arguments or {})
    if tool_name in {"get_kline_context", "get_indicators_batch", "predict_signal_combination"}:
        prepared["exchange"] = context.exchange
    elif tool_name in EXCHANGE_QUERY_TOOL_NAMES and context.exchange == "binance":
        prepared["exchange"] = "binance"
        prepared.setdefault("environment", context.environment)
        if tool_name == "get_exchange_account_data" and context.account_id is not None:
            prepared["account_id"] = context.account_id
    return prepared


def _normalize_exchange(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    exchange = str(value).strip().lower()
    return exchange if exchange in SUPPORTED_SIGNAL_EXCHANGES else None


def _prefer_mainnet(wallets: List[Any]) -> Any:
    for wallet in wallets:
        if getattr(wallet, "environment", None) == "mainnet":
            return wallet
    return wallets[0]
