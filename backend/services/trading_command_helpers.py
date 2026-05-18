"""Shared helpers for AI trading command execution."""

import logging
import random
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from config.settings import BINANCE_DAILY_QUOTA_LIMIT
from database.models import (
    Account,
    AIDecisionLog,
    CRYPTO_COMMISSION_RATE,
    CRYPTO_MIN_COMMISSION,
    Position,
    ProgramExecutionLog,
)
from services.ai_decision_service import SUPPORTED_SYMBOLS
from services.market_data import get_last_price

logger = logging.getLogger(__name__)


AI_TRADING_SYMBOLS: List[str] = ["BTC"]  # Paper trading deprecated, keep minimal
ORACLE_PRICE_DEVIATION_LIMIT_PERCENT = 1.0


def _prepare_trigger_context_for_ai_decision(
    *,
    account: Account,
    exchange: str,
    symbols: Iterable[str],
    trigger_context: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Refresh Arena sub-AI snapshots before the main trading AI decision."""

    context_for_ai = dict(trigger_context or {})
    try:
        from services.ai_decision_context_preflight import (
            infer_decision_context_timeframe,
            refresh_decision_arena_context,
        )

        timeframe = infer_decision_context_timeframe(context_for_ai)
        preflight = refresh_decision_arena_context(
            account_id=account.id,
            exchange=exchange,
            symbols=symbols,
            timeframe=timeframe,
            reason=f"{exchange}_ai_decision",
        )
        context_for_ai["arena_context_timeframe"] = timeframe
        context_for_ai["arena_context_preflight"] = preflight
        if preflight.get("status") == "refreshed":
            logger.info(
                "[AI PREFLIGHT] %s account=%s refreshed %s sub-AI snapshots for %s/%s in %sms",
                exchange,
                account.name,
                preflight.get("snapshot_count"),
                ",".join(preflight.get("symbols") or []),
                timeframe,
                preflight.get("elapsed_ms"),
            )
        elif preflight.get("status") == "skipped_recent":
            logger.info(
                "[AI PREFLIGHT] %s account=%s using recent sub-AI snapshots for %s/%s age=%ss",
                exchange,
                account.name,
                ",".join(preflight.get("symbols") or []),
                timeframe,
                preflight.get("age_seconds"),
            )
        else:
            logger.warning(
                "[AI PREFLIGHT] %s account=%s sub-AI context status=%s error=%s",
                exchange,
                account.name,
                preflight.get("status"),
                preflight.get("error"),
            )
    except Exception as exc:
        logger.warning(
            "[AI PREFLIGHT] Failed to prepare sub-AI context for %s account=%s: %s",
            exchange,
            account.name,
            exc,
            exc_info=True,
        )
        context_for_ai["arena_context_preflight"] = {
            "enabled": True,
            "status": "failed",
            "exchange": exchange,
            "account_id": account.id,
            "error": str(exc),
        }
    return context_for_ai


def _is_premium_user(db: Session) -> bool:
    """Self-hosted deployment: advanced limits are unlocked locally."""
    return True


def _check_binance_daily_quota(db: Session, account_id: int) -> Tuple[bool, Dict[str, int]]:
    """
    Check if Binance mainnet daily quota is exceeded for an account.

    Returns:
        Tuple of (exceeded: bool, info: dict with used/limit/remaining)
    """
    # Check premium status first
    if _is_premium_user(db):
        return False, {"used": 0, "limit": BINANCE_DAILY_QUOTA_LIMIT, "remaining": BINANCE_DAILY_QUOTA_LIMIT}

    # Use UTC midnight for quota reset
    today_start_utc = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Count AIDecisionLog entries (only actual trades: buy/sell/close)
    ai_count = db.query(func.count(AIDecisionLog.id)).filter(
        AIDecisionLog.account_id == account_id,
        AIDecisionLog.exchange == "binance",
        AIDecisionLog.hyperliquid_environment == "mainnet",
        AIDecisionLog.created_at >= today_start_utc,
        AIDecisionLog.operation.in_(["buy", "sell", "close"]),
    ).scalar() or 0

    # Count ProgramExecutionLog entries (only actual trades: buy/sell/close)
    program_count = db.query(func.count(ProgramExecutionLog.id)).filter(
        ProgramExecutionLog.account_id == account_id,
        ProgramExecutionLog.exchange == "binance",
        ProgramExecutionLog.environment == "mainnet",
        ProgramExecutionLog.created_at >= today_start_utc,
        ProgramExecutionLog.decision_action.in_(["buy", "sell", "close"]),
    ).scalar() or 0

    used = ai_count + program_count
    remaining = max(0, BINANCE_DAILY_QUOTA_LIMIT - used)
    exceeded = used >= BINANCE_DAILY_QUOTA_LIMIT

    return exceeded, {"used": used, "limit": BINANCE_DAILY_QUOTA_LIMIT, "remaining": remaining}


def _enforce_price_bounds(
    *,
    symbol: str,
    account_name: str,
    operation: str,
    current_price: float,
    requested_price: float,
) -> Tuple[float, float, bool]:
    """Clamp requested price into ±1% oracle window and log adjustments."""

    if current_price <= 0 or requested_price <= 0:
        return requested_price, 0.0, False

    limit = ORACLE_PRICE_DEVIATION_LIMIT_PERCENT / 100
    lower_bound = current_price * (1 - limit)
    upper_bound = current_price * (1 + limit)

    clamped_price = max(min(requested_price, upper_bound), lower_bound)
    deviation_percent = abs(requested_price - current_price) / current_price * 100
    was_adjusted = clamped_price != requested_price

    if was_adjusted:
        logger.warning(
            f"[AI COMPLIANCE] {operation.upper()} {symbol} price from AI for {account_name} "
            f"violates Hyperliquid ±1% rule. market=${current_price:.2f}, "
            f"requested=${requested_price:.2f}, deviation={deviation_percent:.2f}%. "
            f"Adjusted to ${clamped_price:.2f}."
        )

    return clamped_price, deviation_percent, was_adjusted


def _get_symbol_name(symbol: str) -> str:
    return SUPPORTED_SYMBOLS.get(symbol, symbol)


def _estimate_buy_cash_needed(price: float, quantity: float) -> Decimal:
    """Estimate cash required for a BUY including commission."""
    notional = Decimal(str(price)) * Decimal(str(quantity))
    commission = max(
        notional * Decimal(str(CRYPTO_COMMISSION_RATE)),
        Decimal(str(CRYPTO_MIN_COMMISSION)),
    )
    return notional + commission


def _get_market_prices(symbols: List[str]) -> Dict[str, float]:
    """Get latest prices for given symbols"""
    prices = {}
    for symbol in symbols:
        try:
            price = float(get_last_price(symbol, "CRYPTO"))
            if price > 0:
                prices[symbol] = price
        except Exception as err:
            logger.warning(f"Failed to get price for {symbol}: {err}")
    return prices


def _get_realtime_ticker_snapshot(symbols: List[str], environment: str = "mainnet") -> Dict[str, Dict[str, Any]]:
    """Get a realtime ticker snapshot for prompt generation and price alignment."""
    from services.market_data import get_ticker_data

    tickers: Dict[str, Dict[str, Any]] = {}
    for symbol in symbols:
        try:
            ticker = get_ticker_data(symbol, "CRYPTO", environment)
            if ticker and float(ticker.get("price", 0) or 0) > 0:
                tickers[symbol] = ticker
        except Exception as err:
            logger.warning(f"Failed to get realtime ticker for {symbol}: {err}")
    return tickers


def _select_side(db: Session, account: Account, symbol: str, max_value: float) -> Optional[Tuple[str, int]]:
    """Select random trading side and quantity for legacy random trading"""
    market = "CRYPTO"
    try:
        price = float(get_last_price(symbol, market))
    except Exception as err:
        logger.warning("Cannot get price for %s: %s", symbol, err)
        return None

    if price <= 0:
        logger.debug("%s returned non-positive price %s", symbol, price)
        return None

    max_quantity_by_value = int(Decimal(str(max_value)) // Decimal(str(price)))
    position = (
        db.query(Position)
        .filter(Position.account_id == account.id, Position.symbol == symbol, Position.market == market)
        .first()
    )
    available_quantity = int(position.available_quantity) if position else 0

    choices = []

    if float(account.current_cash) >= price and max_quantity_by_value >= 1:
        choices.append(("BUY", max_quantity_by_value))

    if available_quantity > 0:
        max_sell_quantity = min(available_quantity, max_quantity_by_value if max_quantity_by_value >= 1 else available_quantity)
        if max_sell_quantity >= 1:
            choices.append(("SELL", max_sell_quantity))

    if not choices:
        return None

    side, max_qty = random.choice(choices)
    quantity = random.randint(1, max_qty)
    return side, quantity
