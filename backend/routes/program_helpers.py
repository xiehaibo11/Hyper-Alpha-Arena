"""Shared helpers for Program Trader routes."""

import json
from typing import Any, Dict, List
from sqlalchemy.orm import Session

from database.models import TradingProgram, AccountProgramBinding, User, SignalPool
from routes.program_schemas import ProgramResponse, BindingResponse, WalletInfo, ErrorLocation

def get_default_user(db: Session) -> User:
    """Get or create default user."""
    user = db.query(User).filter(User.username == "default").first()
    if not user:
        user = User(username="default", email="default@local")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _program_to_response(program: TradingProgram, db: Session) -> ProgramResponse:
    """Convert TradingProgram to response model."""
    binding_count = db.query(AccountProgramBinding).filter(
        AccountProgramBinding.program_id == program.id,
        AccountProgramBinding.is_deleted != True
    ).count()

    return ProgramResponse(
        id=program.id,
        name=program.name,
        description=program.description,
        code=program.code,
        params=json.loads(program.params) if program.params else None,
        icon=program.icon,
        binding_count=binding_count,
        created_at=program.created_at.isoformat() if program.created_at else "",
        updated_at=program.updated_at.isoformat() if program.updated_at else "",
    )


def _binding_to_response(binding: AccountProgramBinding, db: Session) -> BindingResponse:
    """Convert AccountProgramBinding to response model."""
    pool_ids = []
    if binding.signal_pool_ids:
        try:
            pool_ids = json.loads(binding.signal_pool_ids)
        except:
            pass

    # Query signal pool names (include disabled pools for display)
    pool_names = []
    if pool_ids:
        pools = db.query(SignalPool).filter(SignalPool.id.in_(pool_ids), SignalPool.is_deleted != True).all()
        pool_map = {p.id: p.pool_name for p in pools}
        pool_names = [pool_map.get(pid, f"Pool #{pid}") for pid in pool_ids]

    params_override = None
    if binding.params_override:
        try:
            params_override = json.loads(binding.params_override)
        except:
            pass

    # Query wallets for this AI Trader based on exchange type
    from database.models import HyperliquidWallet, BinanceWallet
    from utils.encryption import decrypt_private_key
    from services.hyperliquid_environment import get_global_trading_mode

    wallets = []
    exchange = binding.exchange or "hyperliquid"
    environment = get_global_trading_mode(db)

    if exchange == "binance":
        # For Binance, show masked API Key (first 4 and last 4 chars)
        binance_wallets = db.query(BinanceWallet).filter(
            BinanceWallet.account_id == binding.account_id,
            BinanceWallet.environment == environment,
            BinanceWallet.is_active == "true"
        ).all()
        for w in binance_wallets:
            if w.api_key_encrypted:
                try:
                    api_key = decrypt_private_key(w.api_key_encrypted)
                    if len(api_key) >= 8:
                        masked_key = f"{api_key[:4]}...{api_key[-4:]}"
                    else:
                        masked_key = "****"
                except:
                    masked_key = "****"
                wallets.append(WalletInfo(environment=w.environment, address=masked_key))
    else:
        # For Hyperliquid, show wallet address
        wallet_rows = db.query(HyperliquidWallet).filter(
            HyperliquidWallet.account_id == binding.account_id,
            HyperliquidWallet.environment == environment,
            HyperliquidWallet.is_active == "true"
        ).all()
        for w in wallet_rows:
            if w.wallet_address:
                wallets.append(WalletInfo(environment=w.environment, address=w.wallet_address))

    return BindingResponse(
        id=binding.id,
        account_id=binding.account_id,
        account_name=binding.account.name if binding.account else "Unknown",
        program_id=binding.program_id,
        program_name=binding.program.name if binding.program else "Unknown",
        signal_pool_ids=pool_ids,
        signal_pool_names=pool_names,
        trigger_interval=binding.trigger_interval,
        scheduled_trigger_enabled=binding.scheduled_trigger_enabled,
        is_active=binding.is_active,
        last_trigger_at=binding.last_trigger_at.isoformat() if binding.last_trigger_at else None,
        params_override=params_override,
        exchange=binding.exchange or "hyperliquid",
        wallets=wallets,
        created_at=binding.created_at.isoformat() if binding.created_at else "",
        updated_at=binding.updated_at.isoformat() if binding.updated_at else "",
    )


# ============================================================================
# Test Run API (must be before /{program_id} routes)
# ============================================================================

def _parse_error_location(traceback_str: str, code: str) -> ErrorLocation:
    """Extract error location from traceback."""
    import re

    location = ErrorLocation()

    # Look for line number in <string>
    match = re.search(r'File "<string>", line (\d+)', traceback_str)
    if match:
        location.file = "<string>"
        location.line = int(match.group(1))

        # Extract the code context
        lines = code.split('\n')
        if 0 < location.line <= len(lines):
            location.code_context = lines[location.line - 1].strip()

    # Look for function name
    match = re.search(r'in (\w+)\n', traceback_str)
    if match:
        location.function = match.group(1)

    return location


def _generate_suggestions(error_type: str, error_msg: str, traceback_str: str) -> List[str]:
    """Generate AI-friendly suggestions based on error type."""
    suggestions = []

    if error_type == "ImportError":
        suggestions.append("Check if the module/function name is spelled correctly")
        if "calculate_indicator" in error_msg:
            suggestions.append("Available indicator functions: get_indicator(symbol, indicator, period)")
        if "services" in error_msg:
            suggestions.append("Use MarketData methods instead of direct service imports")

    elif error_type == "SyntaxError":
        suggestions.append("Check for missing colons, parentheses, or indentation errors")
        suggestions.append("Ensure proper Python 3 syntax")

    elif error_type == "NameError":
        suggestions.append("Check if the variable/function is defined before use")
        suggestions.append("Available in sandbox: MarketData, Decision, ActionType, math functions")

    elif error_type == "AttributeError":
        suggestions.append("Check if the method/attribute exists on the object")
        suggestions.append("MarketData methods: get_price(), get_indicator(), get_klines(), get_flow()")

    elif error_type == "TypeError":
        suggestions.append("Check function arguments - wrong number or type of arguments")

    elif error_type == "KeyError":
        suggestions.append("Check if the dictionary key exists before accessing")
        suggestions.append("Use .get(key, default) for safe dictionary access")

    elif error_type == "ValidationError":
        suggestions.append("Ensure your class has a should_trade(self, data: MarketData) method")
        suggestions.append("should_trade must return a Decision object")

    elif error_type == "TimeoutError":
        suggestions.append("Strategy execution took too long (>5 seconds)")
        suggestions.append("Avoid infinite loops or expensive computations")

    return suggestions


def _get_available_apis() -> Dict[str, Any]:
    """Return documentation of available APIs for AI reference."""
    return {
        "MarketData_properties": {
            "data.trigger_symbol": "Symbol that triggered this evaluation",
            "data.trigger_type": "Trigger type: 'signal' or 'scheduled'",
            "data.signal_source_type": "Optional signal source subtype: 'wallet_tracking' for Hyper Insight wallet signals, None for market signals",
            "data.wallet_event": "Optional wallet signal payload (dict). Present when signal_source_type='wallet_tracking'. Structure: {source, source_type, address, event_type, event_level, tier, summary, detail, event_timestamp}",
            "data.wallet_event.detail (position_change common)": "{action, direction, start_position, end_position, old_value, new_value, notional_value, entry_price, leverage, unrealized_pnl, liquidation_price}",
            "data.wallet_event.detail (realtime extras)": "{fills_count, total_size, average_price, closed_pnl, fills[]}",
            "data.wallet_event.detail (polling extras)": "{absolute_change, relative_change, current_position, previous_position, source_event_type}",
            "data.wallet_event.detail.action": "open, close, add, reduce, flip, update",
            "data.wallet_event.detail.direction": "long, short, flat",
            "data.available_balance": "Available balance in USD",
            "data.total_equity": "Total account equity",
            "data.positions": "Dict[str, Position] of current open positions",
        },
        "Position_fields": {
            "symbol": "Trading symbol",
            "side": "'long' or 'short'",
            "size": "Position size",
            "entry_price": "Entry price",
            "unrealized_pnl": "Unrealized PnL",
            "leverage": "Leverage used",
            "liquidation_price": "Liquidation price",
        },
        "MarketData_methods": {
            "get_market_data(symbol)": "Returns {symbol, price, oracle_price, change24h, volume24h, percentage24h, open_interest, funding_rate}",
            "get_indicator(symbol, indicator, period)": "Indicators: RSI14, RSI7, MA5, MA10, MA20, EMA20, EMA50, EMA100, MACD, BOLL, ATR14, VWAP, STOCH, OBV",
            "get_klines(symbol, period, count=50)": "Returns list of Kline(timestamp, open, high, low, close, volume)",
            "get_flow(symbol, metric, period)": "Metrics: CVD, OI, OI_DELTA, TAKER, FUNDING, DEPTH, IMBALANCE",
            "get_regime(symbol, period)": "Returns RegimeInfo(regime, conf, direction, reason, indicators)",
            "get_price_change(symbol, period)": "Returns {change_percent, change_usd}",
        },
        "Decision_fields": {
            "operation": "Required: 'buy', 'sell', 'hold', 'close'",
            "symbol": "Required: Trading symbol string",
            "target_portion_of_balance": "Required for buy/sell/close: 0.1-1.0",
            "leverage": "Required for buy/sell/close: 1-50 (default: 10)",
            "max_price": "Required for buy or close short: maximum entry price",
            "min_price": "Required for sell or close long: minimum entry price",
            "time_in_force": "Optional: 'Ioc', 'Gtc', 'Alo' (default: 'Ioc')",
            "take_profit_price": "Optional: TP trigger price",
            "stop_loss_price": "Optional: SL trigger price",
            "tp_execution": "Optional: 'market' or 'limit' (default: 'limit')",
            "sl_execution": "Optional: 'market' or 'limit' (default: 'limit')",
            "reason": "Optional: Explanation string",
            "trading_strategy": "Optional: Entry thesis, risk controls",
        },
        "operation_values": ["buy", "sell", "hold", "close"],
        "supported_periods": ["1m", "5m", "15m", "1h", "4h", "1d"],
        "math_functions": {
            "usage": "Call via math.xxx (e.g., math.pow(10, 2))",
            "functions": ["sqrt", "log", "log10", "exp", "pow", "floor", "ceil", "fabs"],
        },
        "available_builtins": ["abs", "min", "max", "sum", "len", "round", "int", "float", "str", "bool", "list", "dict", "range", "enumerate", "zip", "sorted", "any", "all"],
        "debug_function": "log(message) - Print debug output",
    }
