"""Prompt template variable parsing for AI decision context."""

import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _parse_kline_indicator_variables(template_text: str) -> Dict[str, Dict[str, Any]]:
    """
    Parse K-line and indicator variables from prompt template.

    Extracts variables like:
    - {BTC_klines_15m}(200) - K-line data
    - {BTC_RSI14_15m} - Technical indicators
    - {BTC_market_data} - Market ticker data
    - {BTC_CVD_15m} - Market flow indicators (CVD, TAKER, OI, FUNDING, DEPTH)

    Returns grouped by (symbol, period) for optimization:
    {
        ('BTC', '15m'): {
            'klines': {'count': 200},
            'indicators': ['RSI14', 'MACD'],
            'flow_indicators': ['CVD', 'TAKER'],
            'market_data': True
        },
        ('BTC', None): {
            'market_data': True
        }
    }
    """
    # Pattern for K-line variables: {SYMBOL_klines_PERIOD}(COUNT)
    kline_pattern = r'\{([A-Z]+)_klines_(\w+)\}(?:\((\d+)\))?'

    # Pattern for indicator variables: {SYMBOL_INDICATOR_PERIOD}
    # Supports: RSI14, RSI7, MACD, STOCH, MA, EMA, BOLL, ATR14, VWAP, OBV
    indicator_pattern = r'\{([A-Z]+)_(RSI\d+|MACD|STOCH|MA\d*|EMA\d*|BOLL|ATR\d+|VWAP|OBV)_(\w+)\}'

    # Pattern for market flow variables: {SYMBOL_FLOW_PERIOD}
    # Supports: CVD, TAKER, OI, OI_DELTA, FUNDING, DEPTH, IMBALANCE, PRICE_CHANGE, VOLATILITY
    # Note: OI_DELTA must come before OI in the pattern to match correctly
    flow_pattern = r'\{([A-Z]+)_(CVD|TAKER|OI_DELTA|OI|FUNDING|DEPTH|IMBALANCE|PRICE_CHANGE|VOLATILITY)_(\w+)\}'

    # Pattern for market data: {SYMBOL_market_data}
    market_data_pattern = r'\{([A-Z]+)_market_data\}'

    grouped = {}

    def _ensure_key(key):
        if key not in grouped:
            grouped[key] = {
                'klines': None,
                'indicators': [],
                'flow_indicators': [],
                'market_data': False
            }

    # Parse K-line variables
    for match in re.finditer(kline_pattern, template_text):
        symbol = match.group(1)
        if symbol == "SYMBOL":
            continue  # Skip documentation placeholder
        period = match.group(2)
        count = int(match.group(3)) if match.group(3) else 500  # Default 500

        key = (symbol, period)
        _ensure_key(key)
        grouped[key]['klines'] = {'count': count}

        logger.debug(f"Found K-line variable: {symbol}_klines_{period}({count})")

    # Parse indicator variables
    for match in re.finditer(indicator_pattern, template_text):
        symbol = match.group(1)
        if symbol == "SYMBOL":
            continue  # Skip documentation placeholder
        indicator = match.group(2)
        period = match.group(3)

        key = (symbol, period)
        _ensure_key(key)

        # Handle compound indicators (MA, EMA expand to multiple)
        if indicator == 'MA':
            grouped[key]['indicators'].extend(['MA5', 'MA10', 'MA20'])
        elif indicator == 'EMA':
            grouped[key]['indicators'].extend(['EMA20', 'EMA50', 'EMA100'])
        else:
            grouped[key]['indicators'].append(indicator)

        logger.debug(f"Found indicator variable: {symbol}_{indicator}_{period}")

    # Parse market flow variables
    for match in re.finditer(flow_pattern, template_text):
        symbol = match.group(1)
        if symbol == "SYMBOL":
            continue  # Skip documentation placeholder
        flow_indicator = match.group(2)
        period = match.group(3)

        key = (symbol, period)
        _ensure_key(key)
        grouped[key]['flow_indicators'].append(flow_indicator)

        logger.debug(f"Found flow indicator variable: {symbol}_{flow_indicator}_{period}")

    # Parse market data variables
    for match in re.finditer(market_data_pattern, template_text):
        symbol = match.group(1)
        if symbol == "SYMBOL":
            continue  # Skip documentation placeholder

        key = (symbol, None)
        _ensure_key(key)
        grouped[key]['market_data'] = True

        logger.debug(f"Found market data variable: {symbol}_market_data")

    # Remove duplicates from indicators and flow_indicators lists
    for key in grouped:
        grouped[key]['indicators'] = list(set(grouped[key]['indicators']))
        grouped[key]['flow_indicators'] = list(set(grouped[key]['flow_indicators']))

    logger.info(f"Parsed {len(grouped)} groups of K-line/indicator/flow/market-data variables")
    return grouped


def _parse_factor_variables(template_text: str) -> List[tuple]:
    """
    Parse factor variables from prompt template.
    Preferred format: {SYMBOL_factor_PERIOD_NAME}
    Legacy format: {SYMBOL_factor_NAME} -> defaults to 5m

    Returns list of (symbol, period, factor_name, var_name) tuples.
    """
    results = []
    seen = set()

    preferred_pattern = r'\{([A-Z][A-Z0-9]*)_factor_(1m|5m|15m|1h|4h|1d)_([A-Za-z][A-Za-z0-9_]*)\}'
    for match in re.finditer(preferred_pattern, template_text):
        symbol = match.group(1)
        period = match.group(2)
        factor_name = match.group(3)
        if symbol == "SYMBOL":
            continue
        key = (symbol, period, factor_name)
        if key not in seen:
            seen.add(key)
            var_name = f"{symbol}_factor_{period}_{factor_name}"
            results.append((symbol, period, factor_name, var_name))

    legacy_pattern = r'\{([A-Z][A-Z0-9]*)_factor_([A-Za-z][A-Za-z0-9_]*)\}'
    for match in re.finditer(legacy_pattern, template_text):
        symbol = match.group(1)
        factor_name = match.group(2)
        if symbol == "SYMBOL":
            continue
        key = (symbol, "5m", factor_name)
        if key not in seen:
            seen.add(key)
            var_name = f"{symbol}_factor_{factor_name}"
            results.append((symbol, "5m", factor_name, var_name))

    return results
