"""Prompt formatting helpers and constants for AI decision context."""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from database.models import Account

logger = logging.getLogger(__name__)

SUPPORTED_SYMBOLS: Dict[str, str] = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
    "DOGE": "Dogecoin",
    "XRP": "Ripple",
    "BNB": "Binance Coin",
}

def _format_currency(value: Optional[float], precision: int = 2, default: str = "N/A") -> str:
    try:
        if value is None:
            return default
        return f"{float(value):,.{precision}f}"
    except (TypeError, ValueError):
        return default


def _format_quantity(value: Optional[float], precision: int = 6, default: str = "0") -> str:
    try:
        if value is None:
            return default
        return f"{float(value):.{precision}f}"
    except (TypeError, ValueError):
        return default


def _get_metric_unit(metric: str) -> str:
    """Get the unit for a signal metric type."""
    # Percentage-based metrics
    percent_metrics = {
        "oi_delta", "price_change_percent", "volume_change_percent",
        "funding", "funding_rate"
    }
    # Ratio-based metrics (no unit, just a number)
    # taker_ratio is now log-transformed, symmetric around 0
    ratio_metrics = {"depth_ratio", "order_imbalance", "imbalance", "taker_ratio"}
    # USD-based metrics
    usd_metrics = {"oi", "cvd", "volume", "taker_volume"}

    metric_lower = metric.lower() if metric else ""
    if metric_lower in percent_metrics or "percent" in metric_lower:
        return "%"
    elif metric_lower in usd_metrics:
        return ""  # USD values are typically formatted separately
    elif metric_lower in ratio_metrics:
        return ""  # Ratios are dimensionless
    return ""


def _build_session_context(account: Account) -> str:
    """Build session context (legacy format for backward compatibility)"""
    now = datetime.utcnow()
    runtime_minutes = "N/A"

    created_at = getattr(account, "created_at", None)
    if isinstance(created_at, datetime):
        created = created_at.replace(tzinfo=None) if created_at.tzinfo else created_at
        runtime_minutes = str(max(0, int((now - created).total_seconds() // 60)))

    lines = [
        f"TRADER_ID: {account.name}",
        f"MODEL: {account.model or 'N/A'}",
        f"RUNTIME_MINUTES: {runtime_minutes}",
        "INVOCATION_COUNT: N/A",
        f"CURRENT_TIME_UTC: {now.isoformat()}",
    ]
    return "\n".join(lines)


def _calculate_runtime_minutes(account: Account) -> str:
    """Calculate runtime minutes for Alpha Arena style prompts"""
    created_at = getattr(account, "created_at", None)
    if isinstance(created_at, datetime):
        now = datetime.utcnow()
        created = created_at.replace(tzinfo=None) if created_at.tzinfo else created_at
        return str(max(0, int((now - created).total_seconds() // 60)))
    return "0"


def _calculate_total_return_percent(account: Account) -> str:
    """Calculate total return percentage"""
    initial_cash = float(getattr(account, "initial_cash", 0) or 10000)
    current_total = float(getattr(account, "current_cash", 0))

    # Add positions value if available
    try:
        from services.asset_calculator import calc_positions_value
        from database.connection import SessionLocal
        db = SessionLocal()
        try:
            positions_value = calc_positions_value(db, account.id)
            current_total += positions_value
        finally:
            db.close()
    except Exception:
        pass

    if initial_cash > 0:
        return_pct = ((current_total - initial_cash) / initial_cash) * 100
        return f"{return_pct:+.2f}"
    return "0.00"


def _build_holdings_detail(positions: Dict[str, Dict[str, Any]]) -> str:
    """Build detailed holdings list for Alpha Arena style prompts"""
    if not positions:
        return "- None (all cash)"

    lines = []
    for symbol, data in positions.items():
        qty = data.get('quantity', 0)
        avg_cost = data.get('avg_cost', 0)
        current_value = data.get('current_value', 0)

        lines.append(
            f"- {symbol}: {_format_quantity(qty)} units @ ${_format_currency(avg_cost, precision=4)} avg "
            f"(current value: ${_format_currency(current_value)})"
        )

    return "\n".join(lines)


def _build_market_prices(
    prices: Dict[str, float],
    symbol_order: Optional[List[str]] = None,
    symbol_names: Optional[Dict[str, str]] = None,
) -> str:
    """Build simple market prices list for Alpha Arena style prompts"""
    order = symbol_order or list(SUPPORTED_SYMBOLS.keys())
    lines = []
    for symbol in order:
        price = prices.get(symbol)
        display_name = (symbol_names or {}).get(symbol)
        label = symbol if not display_name or display_name == symbol else f"{symbol} ({display_name})"
        if price:
            lines.append(f"{label}: ${_format_currency(price, precision=4)}")
        else:
            lines.append(f"{label}: N/A")

    return "\n".join(lines)


def _get_realtime_ticker_snapshot(
    symbols: List[str],
    environment: str = "mainnet",
    exchange: str = "hyperliquid",
) -> Dict[str, Dict[str, Any]]:
    """Fetch a single realtime ticker snapshot for all symbols in this prompt build."""
    from services.market_data import get_ticker_data

    market_param = exchange if exchange in {"binance", "okx"} else "CRYPTO"
    snapshot: Dict[str, Dict[str, Any]] = {}

    for symbol in symbols:
        try:
            ticker = get_ticker_data(symbol, market_param, environment)
            if ticker and float(ticker.get("price", 0) or 0) > 0:
                snapshot[symbol] = ticker
        except Exception as err:
            logger.warning(f"Failed to fetch realtime ticker for {symbol} ({exchange}/{environment}): {err}")

    return snapshot


def _format_market_data_block(symbol: str, ticker: Dict[str, Any]) -> str:
    """Format {SYMBOL_market_data} from one ticker snapshot."""
    market_data_lines = [
        f"Symbol: {symbol}",
        f"Price: ${ticker['price']:.2f}",
        f"24h Change: {ticker['change24h']:+.2f} ({ticker['percentage24h']:+.2f}%)",
        f"24h Volume: ${ticker['volume24h']:,.0f}",
    ]
    if 'open_interest' in ticker:
        market_data_lines.append(f"Open Interest: ${ticker['open_interest']:,.0f}")
    if 'funding_rate' in ticker:
        market_data_lines.append(f"Funding Rate: {ticker['funding_rate'] * 100:.4f}%")
    return "\n".join(market_data_lines)


def _normalize_symbol_metadata(
    symbol_metadata: Optional[Dict[str, Any]],
    fallback_symbols: List[str],
) -> Dict[str, Dict[str, Optional[str]]]:
    """Normalize symbol metadata into a consistent mapping."""
    normalized: Dict[str, Dict[str, Optional[str]]] = {}

    if symbol_metadata:
        for raw_symbol, meta in symbol_metadata.items():
            symbol = str(raw_symbol).upper()
            if isinstance(meta, dict):
                normalized[symbol] = {
                    "name": meta.get("name") or meta.get("display_name") or symbol,
                    "type": meta.get("type") or meta.get("category"),
                }
            else:
                display = str(meta).strip()
                normalized[symbol] = {
                    "name": display or symbol,
                    "type": None,
                }

    for symbol in fallback_symbols:
        normalized.setdefault(
            symbol,
            {
                "name": SUPPORTED_SYMBOLS.get(symbol, symbol),
                "type": None,
            },
        )

    if not normalized:
        for symbol, display in SUPPORTED_SYMBOLS.items():
            normalized[symbol] = {"name": display, "type": None}

    return normalized


def _build_account_state(portfolio: Dict[str, Any]) -> str:
    positions: Dict[str, Dict[str, Any]] = portfolio.get("positions", {})
    lines = [
        f"Available Cash (USD): {_format_currency(portfolio.get('cash'))}",
        f"Frozen Cash (USD): {_format_currency(portfolio.get('frozen_cash'))}",
        f"Total Assets (USD): {_format_currency(portfolio.get('total_assets'))}",
        "",
        "Open Positions:",
    ]

    if positions:
        for symbol, data in positions.items():
            lines.append(
                f"- {symbol}: qty={_format_quantity(data.get('quantity'))}, "
                f"avg_cost={_format_currency(data.get('avg_cost'))}, "
                f"current_value={_format_currency(data.get('current_value'))}"
            )
    else:
        lines.append("- None")

    return "\n".join(lines)


def _build_sampling_data(samples: Optional[List], target_symbol: Optional[str], sampling_interval: Optional[int] = None) -> str:
    """Build sampling pool data section for Alpha Arena style prompts (single symbol)"""
    if not samples or not target_symbol:
        return "No sampling data available."

    interval_text = f"{sampling_interval}-second intervals" if sampling_interval else "unknown intervals"
    lines = [
        f"Multi-timeframe price data for {target_symbol} ({interval_text}, oldest to newest):",
        f"Total samples: {len(samples)}",
        ""
    ]

    # Format samples in Alpha Arena style - chronological order (oldest to newest)
    for i, sample in enumerate(samples):
        timestamp = sample.get('datetime', 'N/A')
        price = sample.get('price', 0)
        # Format timestamp to be more readable
        if timestamp != 'N/A':
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                time_str = dt.strftime('%H:%M:%S')
            except:
                time_str = timestamp
        else:
            time_str = 'N/A'

        lines.append(f"T-{len(samples)-i-1}: ${price:.6f} ({time_str})")

    # Calculate price momentum and trend
    if len(samples) >= 2:
        first_price = samples[0].get('price', 0)
        last_price = samples[-1].get('price', 0)
        if first_price > 0:
            change_pct = ((last_price - first_price) / first_price) * 100
            trend = "BULLISH" if change_pct > 0 else "BEARISH" if change_pct < 0 else "NEUTRAL"
            lines.append("")
            lines.append(f"Price momentum: {change_pct:+.3f}% ({trend})")
            lines.append(f"Range: ${first_price:.6f} → ${last_price:.6f}")

    return "\n".join(lines)


def _build_multi_symbol_sampling_data(symbols: List[str], sampling_pool, sampling_interval: Optional[int] = None) -> str:
    """Build sampling pool data for multiple symbols (Alpha Arena style)"""
    if not symbols:
        return "No symbols selected for sampling data."

    sections = []
    interval_text = f"{sampling_interval}-second intervals" if sampling_interval else "unknown intervals"

    for symbol in symbols:
        samples = sampling_pool.get_samples(symbol)
        if not samples:
            sections.append(f"{symbol}: No sampling data available")
            continue

        lines = [
            f"{symbol} ({interval_text}, oldest to newest):",
            f"Total samples: {len(samples)}",
            ""
        ]

        # Format samples
        for i, sample in enumerate(samples):
            timestamp = sample.get('datetime', 'N/A')
            price = sample.get('price', 0)
            if timestamp != 'N/A':
                try:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    time_str = dt.strftime('%H:%M:%S')
                except:
                    time_str = timestamp
            else:
                time_str = 'N/A'

            lines.append(f"T-{len(samples)-i-1}: ${price:.6f} ({time_str})")

        # Calculate momentum
        if len(samples) >= 2:
            first_price = samples[0].get('price', 0)
            last_price = samples[-1].get('price', 0)
            if first_price > 0:
                change_pct = ((last_price - first_price) / first_price) * 100
                trend = "BULLISH" if change_pct > 0 else "BEARISH" if change_pct < 0 else "NEUTRAL"
                lines.append("")
                lines.append(f"Price momentum: {change_pct:+.3f}% ({trend})")
                lines.append(f"Range: ${first_price:.6f} → ${last_price:.6f}")

        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def _build_market_snapshot(
    prices: Dict[str, float],
    positions: Dict[str, Dict[str, Any]],
    symbol_order: Optional[List[str]] = None,
) -> str:
    lines: List[str] = []
    order = symbol_order or list(SUPPORTED_SYMBOLS.keys())
    for symbol in order:
        price = prices.get(symbol)
        position = positions.get(symbol, {})

        parts = [f"{symbol}: price={_format_currency(price, precision=4)}"]
        if position:
            parts.append(f"qty={_format_quantity(position.get('quantity'))}")
            parts.append(f"avg_cost={_format_currency(position.get('avg_cost'), precision=4)}")
            parts.append(f"position_value={_format_currency(position.get('current_value'))}")
        else:
            parts.append("position=flat")

        lines.append(", ".join(parts))

    return "\n".join(lines) if lines else "No market data available."


SYMBOL_PLACEHOLDER = "__SYMBOL_SET__"
OUTPUT_FORMAT_JSON = (
    '{\n'
    '  "decisions": [\n'
    '    {\n'
    '      "operation": "buy" | "sell" | "hold" | "close",\n'
    '      "symbol": "<' + SYMBOL_PLACEHOLDER + '>",\n'
    '      "target_portion_of_balance": <float 0.0-1.0>,\n'
    '      "leverage": <integer 1-20>,\n'
    '      "max_price": <number, required for "buy" operations>,\n'
    '      "min_price": <number, required for "sell"/"close" operations>,\n'
    '      "time_in_force": "Ioc" | "Gtc" | "Alo",\n'
    '      "take_profit_price": <number, optional, take profit trigger price>,\n'
    '      "stop_loss_price": <number, optional, stop loss trigger price>,\n'
    '      "tp_execution": "market" | "limit",\n'
    '      "sl_execution": "market" | "limit",\n'
    '      "reason": "<string explaining primary signals>",\n'
    '      "trading_strategy": "<string covering thesis, risk controls, and exit plan>"\n'
    '    }\n'
    '  ]\n'
    '}'
)

# Placeholder for max leverage in output format template
MAX_LEVERAGE_PLACEHOLDER = "__MAX_LEVERAGE__"

# Complete OUTPUT FORMAT template with all requirements and examples
# Uses double-brace escaping for JSON literals to avoid format_map() conflicts
OUTPUT_FORMAT_COMPLETE = """Respond with ONLY a JSON object using this schema (always emitting the `decisions` array even if it is empty):
{{
  "decisions": [
    {{
      "operation": "buy" | "sell" | "hold" | "close",
      "symbol": "<__SYMBOL_SET__>",
      "target_portion_of_balance": <float 0.0-1.0>,
      "leverage": <integer 1-__MAX_LEVERAGE__>,
      "max_price": <number, required for "buy" operations>,
      "min_price": <number, required for "sell"/"close" operations>,
      "time_in_force": "Ioc" | "Gtc" | "Alo",
      "take_profit_price": <number, optional>,
      "stop_loss_price": <number, optional>,
      "tp_execution": "market" | "limit",
      "sl_execution": "market" | "limit",
      "reason": "<string explaining primary signals>",
      "trading_strategy": "<string covering thesis, risk controls, and exit plan>"
    }}
  ]
}}

CRITICAL OUTPUT REQUIREMENTS:
- Output MUST be a single, valid JSON object only
- NO markdown code blocks (no ```json``` wrappers)
- NO explanatory text before or after the JSON
- NO comments or additional content outside the JSON object
- Ensure all JSON fields are properly quoted and formatted
- Double-check JSON syntax before responding
- HARD CONSISTENCY RULE: if target_portion_of_balance is 0.0, operation MUST be "hold" and leverage MUST be 0
- HARD CONSISTENCY RULE: if operation is "buy", "sell", or "close", target_portion_of_balance MUST be greater than 0.0
- HARD CONSISTENCY RULE: never output "buy" or "sell" with leverage 0

Example output with multiple simultaneous orders:
{{
  "decisions": [
    {{
      "operation": "buy",
      "symbol": "BTC",
      "target_portion_of_balance": 0.3,
      "leverage": 3,
      "max_price": 49500,
      "time_in_force": "Ioc",
      "take_profit_price": 52000,
      "stop_loss_price": 47500,
      "tp_execution": "limit",
      "sl_execution": "market",
      "reason": "Strong bullish momentum with support holding at $48k, RSI recovering from oversold",
      "trading_strategy": "Opening 3x leveraged long position with 30% balance. Take profit at $52k resistance (+5%), stop loss below $47.5k swing low (-4%). Using IOC for immediate execution."
    }},
    {{
      "operation": "sell",
      "symbol": "ETH",
      "target_portion_of_balance": 0.2,
      "leverage": 2,
      "min_price": 3125,
      "reason": "ETH perp funding flipped elevated negative while momentum weakens",
      "trading_strategy": "Initiating small short hedge until ETH regains strength vs BTC pair. Stop if ETH closes back above $3.2k structural pivot."
    }}
  ]
}}

FIELD TYPE REQUIREMENTS:
- decisions: array (one entry per supported symbol; include HOLD entries with zero allocation when you choose not to act)
- operation: string ("buy" for long, "sell" for short, "hold", or "close")
- symbol: string (exactly one of: __SYMBOL_SET__)
- target_portion_of_balance: number (0.0 ONLY for hold; 0.1 to 1.0 for buy/sell/close)
- leverage: integer (0 ONLY for hold; 1 to __MAX_LEVERAGE__ for buy/sell/close, REQUIRED field)
- max_price: number (required for "buy" operations and closing SHORT positions. This is the maximum price you are willing to pay.)
- min_price: number (required for "sell" operations and closing LONG positions. This is the minimum price you are willing to receive.)
- time_in_force: string (optional, default "Ioc") - Order time in force: "Ioc" (immediate or cancel, taker-focused), "Gtc" (good til canceled, may become maker), "Alo" (add liquidity only, maker-only)
- take_profit_price: number (optional but recommended, trigger price for profit taking)
- stop_loss_price: number (optional but recommended, trigger price for loss protection)
- tp_execution: string (optional, default "limit") - TP execution mode: "limit" (attempts maker with 0.05% offset, may save fees but has fill risk), "market" (immediate execution, guarantees fill)
- sl_execution: string (optional, default "limit") - SL execution mode: "limit" (may save fees), "market" (guarantees stop loss execution)
- reason: string explaining the key catalyst, risk, or signal (no strict length limit, but stay focused)
- trading_strategy: string covering entry thesis, leverage reasoning, liquidation awareness, and exit plan

FIELD CLASSIFICATION:
- ALWAYS REQUIRED: operation, symbol, reason, trading_strategy
- REQUIRED FOR buy/sell: target_portion_of_balance, leverage, max_price (buy) or min_price (sell)
- REQUIRED FOR close: target_portion_of_balance, max_price (close short) or min_price (close long)
- OPTIONAL WITH DEFAULTS: time_in_force (default "Ioc"), tp_execution (default "limit"), sl_execution (default "limit")
- OPTIONAL BUT RECOMMENDED: take_profit_price, stop_loss_price

FIELD DEPENDENCIES:
- tp_execution only applies when take_profit_price is set (ignored otherwise)
- sl_execution only applies when stop_loss_price is set (ignored otherwise)"""


DECISION_TASK_TEXT = (
    "You are a systematic trader operating on the Hyper Alpha Arena sandbox (no real funds at risk).\n"
    "- Review every open position and decide: buy_to_enter, sell_to_enter, hold, or close_position.\n"
    "- Avoid pyramiding or increasing size unless an exit plan explicitly allows it.\n"
    "- Respect risk: keep new exposure within reasonable fractions of available cash (default ≤ 0.2).\n"
    "- Close positions when invalidation conditions are met or risk is excessive.\n"
    "- When data is missing (marked N/A), acknowledge uncertainty before deciding.\n"
)
