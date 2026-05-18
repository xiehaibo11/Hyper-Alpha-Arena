"""Account asset curve API routes."""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import Account, Trade
from utils.runtime_diagnostics import get_current_thread_count, log_hot_path_delta

logger = logging.getLogger(__name__)
router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/asset-curve")
def get_asset_curve(
    timeframe: str = "5m",
    trading_mode: str = "testnet",
    environment: Optional[str] = None,
    wallet_address: Optional[str] = None,
    account_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get asset curve data for all accounts (or specific account) with specified timeframe and trading mode"""
    start_threads = get_current_thread_count()
    start_time = time.monotonic()
    try:
        from services.asset_curve_calculator import get_all_asset_curves_data_new
        data = get_all_asset_curves_data_new(
            db,
            timeframe=timeframe,
            trading_mode=trading_mode,
            environment=environment,
            wallet_address=wallet_address,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
        )
        return data
    except Exception as e:
        logger.error(f"Error fetching asset curve data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch asset curve data: {str(e)}")
    finally:
        log_hot_path_delta(
            logger,
            "account:asset-curve",
            "/api/account/asset-curve",
            start_threads,
            start_time,
            timeframe=timeframe,
            trading_mode=trading_mode,
            environment=environment,
            account_id=account_id,
        )


@router.get("/asset-curve/timeframe")
def get_asset_curve_by_timeframe(
    timeframe: str = "1d",
    db: Session = Depends(get_db)
):
    """Get asset curve data for all accounts within a specified timeframe (20 data points)

    Args:
        timeframe: Time period, options: 5m, 1h, 1d
    """
    try:
        # Validate timeframe
        valid_timeframes = ["5m", "1h", "1d"]
        if timeframe not in valid_timeframes:
            raise HTTPException(status_code=400, detail=f"Invalid timeframe. Must be one of: {', '.join(valid_timeframes)}")

        # Map timeframe to period for kline data
        timeframe_map = {
            "5m": "5m",
            "1h": "1h",
            "1d": "1d"
        }
        period = timeframe_map[timeframe]

        # Get all active accounts
        accounts = db.query(Account).filter(Account.is_active == "true", Account.is_deleted != True).all()
        if not accounts:
            return []

        # Get all unique symbols from all account positions and trades
        symbols_query = db.query(Trade.symbol, Trade.market).distinct().all()
        unique_symbols = set()
        for symbol, market in symbols_query:
            unique_symbols.add((symbol, market))

        if not unique_symbols:
            # No trades yet, return initial capital for all accounts
            now = datetime.now()
            return [{
                "timestamp": int(now.timestamp()),
                "datetime_str": now.isoformat(),
                "user_id": account.user_id,
                "username": account.name,
                "total_assets": float(account.initial_capital),
                "cash": float(account.current_cash),
                "positions_value": 0.0,
            } for account in accounts]

        # Fetch kline data for all symbols (20 points)
        from services.market_data import get_kline_data

        symbol_klines = {}
        for symbol, market in unique_symbols:
            try:
                klines = get_kline_data(symbol, market, period, 20)
                if klines:
                    symbol_klines[(symbol, market)] = klines
                    logger.info(f"Fetched {len(klines)} klines for {symbol}.{market}")
            except Exception as e:
                logger.warning(f"Failed to fetch klines for {symbol}.{market}: {e}")

        if not symbol_klines:
            raise HTTPException(status_code=500, detail="Failed to fetch market data")

        # Get timestamps from the first symbol's klines
        first_klines = next(iter(symbol_klines.values()))
        timestamps = [k['timestamp'] for k in first_klines]

        # Calculate asset value for each account at each timestamp
        result = []
        for account in accounts:
            account_id = account.id

            # Get all trades for this account
            trades = db.query(Trade).filter(
                Trade.account_id == account_id
            ).order_by(Trade.trade_time.asc()).all()

            if not trades:
                # No trades, return initial capital at all timestamps
                for i, ts in enumerate(timestamps):
                    result.append({
                        "timestamp": ts,
                        "datetime_str": first_klines[i]['datetime_str'],
                        "user_id": account.user_id,
                        "username": account.name,
                        "total_assets": float(account.initial_capital),
                        "cash": float(account.initial_capital),
                        "positions_value": 0.0,
                    })
                continue

            # Calculate holdings and cash at each timestamp
            for i, ts in enumerate(timestamps):
                ts_datetime = datetime.fromtimestamp(ts, tz=timezone.utc)

                # Calculate cash changes up to this timestamp
                cash_change = 0.0
                position_quantities = {}

                for trade in trades:
                    trade_time = trade.trade_time
                    if not trade_time.tzinfo:
                        trade_time = trade_time.replace(tzinfo=timezone.utc)

                    if trade_time <= ts_datetime:
                        # Update cash
                        trade_amount = float(trade.price) * float(trade.quantity) + float(trade.commission)
                        if trade.side == "BUY":
                            cash_change -= trade_amount
                        else:  # SELL
                            cash_change += trade_amount

                        # Update position
                        key = (trade.symbol, trade.market)
                        if key not in position_quantities:
                            position_quantities[key] = 0.0

                        if trade.side == "BUY":
                            position_quantities[key] += float(trade.quantity)
                        else:  # SELL
                            position_quantities[key] -= float(trade.quantity)

                current_cash = float(account.initial_capital) + cash_change

                # Calculate positions value using prices at this timestamp
                positions_value = 0.0
                for (symbol, market), quantity in position_quantities.items():
                    if quantity > 0 and (symbol, market) in symbol_klines:
                        klines = symbol_klines[(symbol, market)]
                        if i < len(klines):
                            price = klines[i]['close']
                            if price:
                                positions_value += float(price) * quantity

                total_assets = current_cash + positions_value

                result.append({
                    "timestamp": ts,
                    "datetime_str": first_klines[i]['datetime_str'],
                    "user_id": account.user_id,
                    "username": account.name,
                    "total_assets": total_assets,
                    "cash": current_cash,
                    "positions_value": positions_value,
                })

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get asset curve for timeframe: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get asset curve for timeframe: {str(e)}")
