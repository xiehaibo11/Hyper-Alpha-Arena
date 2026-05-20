from __future__ import annotations

import re
from dataclasses import dataclass, field
from string import Formatter
from typing import List


class PromptValidationError(ValueError):
    """Raised when an AI Trader prompt template violates platform rules."""


@dataclass
class PromptValidationResult:
    is_valid: bool
    variables: List[str] = field(default_factory=list)
    invalid_variables: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


AI_TRADER_BASE_VARIABLES = {
    # Legacy/default prompt variables
    "account_state",
    "market_snapshot",
    "session_context",
    "sampling_data",
    "decision_task",
    "output_format",
    "prices_json",
    "portfolio_json",
    "portfolio_positions_json",
    "news_section",
    "account_name",
    "model_name",
    # Alpha Arena style variables
    "runtime_minutes",
    "current_time_utc",
    "total_return_percent",
    "available_cash",
    "total_account_value",
    "holdings_detail",
    "market_prices",
    "selected_symbols_csv",
    "selected_symbols_detail",
    "selected_symbols_count",
    # Trading environment/risk variables
    "trading_environment",
    "real_trading_warning",
    "operational_constraints",
    "leverage_constraints",
    "margin_info",
    "environment",
    "max_leverage",
    "default_leverage",
    # Account state
    "total_equity",
    "available_balance",
    "used_margin",
    "margin_usage_percent",
    "maintenance_margin",
    "positions_detail",
    "positions_structured_json",
    "recent_trades_summary",
    "recent_trades_json",
    "open_orders_detail",
    "open_orders_json",
    "api_query_snapshot_json",
    "trigger_context",
    # Market regime
    "market_regime",
    "market_regime_description",
    "trigger_market_regime",
}


VALID_VARIABLE_PATTERNS = [
    # Multi-timeframe market regime variables
    r"market_regime(?:_(?:1m|3m|5m|15m|30m|1h|2h|4h|8h|12h|1d|3d|1w|1M))?",
    # Symbol-specific variables
    r"[A-Z][A-Z0-9]*_market_data",
    r"[A-Z][A-Z0-9]*_klines_(?:1m|3m|5m|15m|30m|1h|2h|4h|8h|12h|1d|3d|1w|1M)",
    r"[A-Z][A-Z0-9]*_market_regime(?:_(?:1m|3m|5m|15m|30m|1h|2h|4h|8h|12h|1d|3d|1w|1M))?",
    # Technical indicators
    r"[A-Z][A-Z0-9]*_(?:MA\d*|EMA\d*|RSI\d+|MACD|STOCH|BOLL|ATR\d+|VWAP|OBV)_(?:1m|3m|5m|15m|30m|1h|2h|4h|8h|12h|1d|3d|1w|1M)",
    # Flow indicators
    r"[A-Z][A-Z0-9]*_(?:CVD|TAKER|OI_DELTA|OI|FUNDING|DEPTH|IMBALANCE|PRICE_CHANGE|VOLATILITY)_(?:1m|3m|5m|15m|30m|1h|2h|4h|8h|12h|1d|3d|1w|1M)",
    # Factor variables: preferred {SYMBOL_factor_PERIOD_NAME}, legacy {SYMBOL_factor_NAME}
    r"[A-Z][A-Z0-9]*_factor_(?:1m|3m|5m|15m|30m|1h|2h|4h|8h|12h|1d|3d|1w|1M)_[A-Za-z][A-Za-z0-9_]*",
    r"[A-Z][A-Z0-9]*_factor_[A-Za-z][A-Za-z0-9_]*",
    # News variables
    r"[A-Z][A-Z0-9]*_news_(?:sentiment|headlines|detail)(?:_(?:1h|4h|12h|24h))?",
    r"(?:macro|crypto)_news(?:_(?:sentiment|headlines|detail))?(?:_(?:1h|4h|12h|24h))?",
]


PLACEHOLDER_RE = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})")
RESERVED_XML_TAG_RE = re.compile(r"</?\s*(reasoning|decision)\b[^>]*>", re.IGNORECASE)


class _ValidationFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return "N/A"


def _validate_variable(var_name: str) -> bool:
    if var_name in AI_TRADER_BASE_VARIABLES:
        return True
    return any(re.fullmatch(pattern, var_name) for pattern in VALID_VARIABLE_PATTERNS)


def _extract_variables_from_text(text: str) -> List[str]:
    if not text:
        return []
    return sorted(set(PLACEHOLDER_RE.findall(text)))


def _validate_format_syntax(template_text: str) -> List[str]:
    errors: List[str] = []
    try:
        for _literal, field_name, _format_spec, _conversion in Formatter().parse(template_text):
            if not field_name:
                continue
            root_name = field_name.split(".", 1)[0].split("[", 1)[0]
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", root_name):
                errors.append(
                    "Prompt contains a raw single-brace block that Python format cannot render. "
                    "Escape literal JSON/examples as '{{' and '}}', or remove manual JSON schemas and use {output_format}."
                )
                break
        template_text.format_map(_ValidationFormatDict())
    except (KeyError, IndexError, ValueError) as exc:
        errors.append(f"Prompt format syntax is invalid: {exc}")
    return errors


def validate_prompt_template(template_text: str) -> PromptValidationResult:
    errors: List[str] = []
    warnings: List[str] = []

    if not template_text or not template_text.strip():
        errors.append("Prompt template cannot be empty.")
        return PromptValidationResult(False, errors=errors)

    variables = _extract_variables_from_text(template_text)
    invalid_variables = [var for var in variables if not _validate_variable(var)]

    if "output_format" not in variables:
        warnings.append(
            "Prompt template does not include {output_format}; the runtime will append the platform output schema."
        )

    if invalid_variables:
        errors.append(f"Unknown prompt variables: {', '.join(invalid_variables)}")

    reserved_tags = sorted({match.group(1).lower() for match in RESERVED_XML_TAG_RE.finditer(template_text)})
    if reserved_tags:
        errors.append(
            "Reserved XML tags are not allowed in user prompts: "
            + ", ".join(f"<{tag}>" for tag in reserved_tags)
            + ". Use JSON string fields such as reason or trading_strategy instead."
        )

    errors.extend(_validate_format_syntax(template_text))

    return PromptValidationResult(
        is_valid=not errors,
        variables=variables,
        invalid_variables=invalid_variables,
        errors=errors,
        warnings=warnings,
    )


def format_prompt_validation_error(result: PromptValidationResult) -> str:
    if result.is_valid:
        return ""
    return "Prompt validation failed: " + " ".join(result.errors)


def assert_prompt_template_valid(template_text: str) -> None:
    result = validate_prompt_template(template_text)
    if not result.is_valid:
        raise PromptValidationError(format_prompt_validation_error(result))
