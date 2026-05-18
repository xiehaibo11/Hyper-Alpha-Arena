"""K-line and indicator prompt-context builders for AI decisions."""

import logging
import time
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from services.ai_decision_indicator_formatters import _format_flow_indicator, _format_single_indicator

logger = logging.getLogger(__name__)


def _format_market_data_block(symbol: str, ticker: Dict[str, Any]) -> str:
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

def _build_klines_and_indicators_context(
    variable_groups: Dict[str, Dict[str, Any]],
    db: Session,
    environment: str = "mainnet",
    exchange: str = "hyperliquid",
) -> Dict[str, str]:
    """
    Build K-line and indicator context for prompt filling.

    Uses parallel fetching for improved performance when multiple symbols/periods
    are requested. Each (symbol, period) combination is processed concurrently.

    Args:
        variable_groups: Parsed variable groups from _parse_kline_indicator_variables
        db: Database session
        environment: Trading environment (mainnet/testnet)
        exchange: Exchange to use for market data ("hyperliquid" or "binance")

    Returns:
        Dict mapping variable names to formatted strings
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    context = {}

    # If only one group, process directly without threading overhead
    if len(variable_groups) <= 1:
        for (symbol, period), requirements in variable_groups.items():
            result = _process_single_symbol_period(
                symbol,
                period,
                requirements,
                environment,
                exchange,
            )
            context.update(result)
        logger.info(f"Built context with {len(context)} variables for environment: {environment}")
        return context

    # Use thread pool for parallel fetching
    # Limit workers to avoid overwhelming the API
    max_workers = min(len(variable_groups), 4)

    start_time = time.time()
    logger.info(f"[PARALLEL] Starting parallel fetch for {len(variable_groups)} symbol/period groups with {max_workers} workers")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_key = {}
        for (symbol, period), requirements in variable_groups.items():
            future = executor.submit(
                _process_single_symbol_period,
                symbol, period, requirements, environment, exchange
            )
            future_to_key[future] = (symbol, period)

        # Collect results as they complete
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                result = future.result()
                context.update(result)
                logger.debug(f"[PARALLEL] Completed {key[0]} {key[1]}: {len(result)} variables")
            except Exception as e:
                logger.error(f"[PARALLEL] Error processing {key[0]} {key[1]}: {e}", exc_info=True)

    elapsed = time.time() - start_time
    logger.info(f"[PARALLEL] Built context with {len(context)} variables in {elapsed:.2f}s for environment: {environment}")
    return context


def _process_single_symbol_period(
    symbol: str,
    period: Optional[str],
    requirements: Dict[str, Any],
    environment: str,
    exchange: str = "hyperliquid",
) -> Dict[str, str]:
    """
    Process a single (symbol, period) combination and return context variables.

    This function is designed to be called in parallel for different symbol/period
    combinations. It handles K-line fetching, indicator calculation, and formatting.

    Args:
        symbol: Trading symbol (e.g., "BTC")
        period: Time period (e.g., "5m", "1h") or None for market data
        requirements: Dict with 'klines', 'indicators', 'flow_indicators', 'market_data' keys
        environment: Trading environment (mainnet/testnet)
        exchange: Exchange to use for market data ("hyperliquid" or "binance")

    Returns:
        Dict mapping variable names to formatted strings
    """
    from services.market_data import get_kline_data, get_ticker_data

    context = {}
    # Determine market parameter based on exchange
    market_param = "binance" if exchange == "binance" else "CRYPTO"

    try:
        # Handle market data (no period)
        if period is None and requirements.get('market_data'):
            logger.info(f"Processing market data for {symbol} in {environment} (exchange: {exchange})")
            try:
                ticker = get_ticker_data(symbol, market_param, environment)
                if ticker:
                    var_name = f"{symbol}_market_data"
                    context[var_name] = _format_market_data_block(symbol, ticker)
                    logger.debug(f"Added market data variable: {var_name}")
            except Exception as ticker_err:
                logger.warning(f"Failed to get ticker data for {symbol}: {ticker_err}")
            return context

        # Process K-lines and indicators (has period)
        logger.info(f"Processing {symbol} {period} for environment: {environment} (exchange: {exchange})")
        from services.technical_indicators import calculate_indicators
        from services.kline_ai_analysis_service import _format_klines_summary

        # Always fetch 500 candles for accurate indicator calculation
        # Skip persistence for prompt generation (real-time data only, no DB write overhead)
        kline_data = get_kline_data(
            symbol=symbol,
            market=market_param,
            period=period,
            count=500,
            environment=environment,
            persist=False
        )

        if not kline_data:
            logger.warning(f"No K-line data for {symbol} {period} in {environment}")
            return context

        # Process K-line variables
        if requirements.get('klines'):
            count = requirements['klines']['count']
            # Take last N candles for display
            display_klines = kline_data[-count:] if len(kline_data) >= count else kline_data
            formatted_klines = _format_klines_summary(display_klines)

            # Variable name: {BTC_klines_15m}
            var_name = f"{symbol}_klines_{period}"
            context[var_name] = formatted_klines
            logger.debug(f"Added K-line variable: {var_name} ({len(display_klines)} candles)")

        # Calculate and process indicators
        if requirements.get('indicators'):
            indicators_to_calc = requirements['indicators']
            calculated = calculate_indicators(kline_data, indicators_to_calc)

            # Track compound indicators (MA, EMA) for merged output
            ma_indicators = []
            ema_indicators = []

            for indicator_name in indicators_to_calc:
                indicator_data = calculated.get(indicator_name)
                formatted = _format_single_indicator(indicator_name, indicator_data)

                # Variable name: {BTC_RSI14_15m}
                var_name = f"{symbol}_{indicator_name}_{period}"
                context[var_name] = formatted
                logger.debug(f"Added indicator variable: {var_name}")

                # Track for compound output
                if indicator_name.startswith('MA') and indicator_name[2:].isdigit():
                    ma_indicators.append((indicator_name, formatted))
                elif indicator_name.startswith('EMA') and indicator_name[3:].isdigit():
                    ema_indicators.append((indicator_name, formatted))

            # Generate compound MA variable: {BTC_MA_15m}
            if ma_indicators:
                ma_lines = []
                for ind_name, ind_formatted in sorted(ma_indicators):
                    ma_lines.append(f"**{ind_name}**")
                    ma_lines.append(ind_formatted)
                    ma_lines.append("")
                compound_var = f"{symbol}_MA_{period}"
                context[compound_var] = "\n".join(ma_lines).strip()
                logger.debug(f"Added compound MA variable: {compound_var}")

            # Generate compound EMA variable: {BTC_EMA_15m}
            if ema_indicators:
                ema_lines = []
                for ind_name, ind_formatted in sorted(ema_indicators):
                    ema_lines.append(f"**{ind_name}**")
                    ema_lines.append(ind_formatted)
                    ema_lines.append("")
                compound_var = f"{symbol}_EMA_{period}"
                context[compound_var] = "\n".join(ema_lines).strip()
                logger.debug(f"Added compound EMA variable: {compound_var}")

        # Process market flow indicators
        # Note: flow indicators need db session, create a new one for thread safety
        if requirements.get('flow_indicators'):
            from services.market_flow_indicators import get_flow_indicators_for_prompt
            from database.connection import SessionLocal

            flow_indicators_to_calc = requirements['flow_indicators']
            with SessionLocal() as thread_db:
                flow_data = get_flow_indicators_for_prompt(
                    db=thread_db,
                    symbol=symbol,
                    period=period,
                    indicators=flow_indicators_to_calc,
                    exchange=exchange
                )

            for flow_name in flow_indicators_to_calc:
                flow_indicator_data = flow_data.get(flow_name)
                formatted = _format_flow_indicator(flow_name, flow_indicator_data, symbol=symbol, period=period, exchange=exchange)

                # Variable name: {BTC_CVD_15m}
                var_name = f"{symbol}_{flow_name}_{period}"
                context[var_name] = formatted
                logger.debug(f"Added flow indicator variable: {var_name}")

    except Exception as e:
        logger.error(f"Error processing {symbol} {period}: {e}", exc_info=True)

    return context
