"""Deprecated per-program backtest route."""

import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import TradingProgram
from program_trader import BacktestEngine
from program_trader.models import Kline
from routes.program_helpers import get_default_user
from routes.program_schemas import LegacyBacktestRequest, LegacyBacktestResponse

router = APIRouter()

@router.post("/{program_id}/backtest", response_model=LegacyBacktestResponse)
def run_legacy_backtest(program_id: int, request: LegacyBacktestRequest, db: Session = Depends(get_db)):
    """Run backtest on a trading program.

    Deprecated legacy endpoint. Do not add new backtest functionality here.
    The active Program Trader backtest flow uses POST /api/programs/backtest
    with backend/backtest/engine.py and HistoricalDataProvider.
    """
    from database.models import CryptoKline
    from datetime import datetime, timedelta

    user = get_default_user(db)
    program = db.query(TradingProgram).filter(
        TradingProgram.id == program_id,
        TradingProgram.user_id == user.id,
        TradingProgram.is_deleted != True
    ).first()

    if not program:
        raise HTTPException(status_code=404, detail="Program not found")

    # Convert datetime to seconds timestamp for comparison with CryptoKline.timestamp
    start_time_s = int((datetime.utcnow() - timedelta(days=request.days)).timestamp())
    rows = db.query(CryptoKline).filter(
        CryptoKline.symbol == request.symbol,
        CryptoKline.period == request.period,
        CryptoKline.timestamp >= start_time_s,
    ).order_by(CryptoKline.timestamp).all()

    if len(rows) < 100:
        raise HTTPException(status_code=400, detail="Insufficient historical data")

    klines = [
        Kline(
            timestamp=int(row.timestamp) * 1000,  # Convert seconds to milliseconds
            open=float(row.open_price) if row.open_price else 0.0,
            high=float(row.high_price) if row.high_price else 0.0,
            low=float(row.low_price) if row.low_price else 0.0,
            close=float(row.close_price) if row.close_price else 0.0,
            volume=float(row.volume) if row.volume else 0.0,
        )
        for row in rows
    ]

    engine = BacktestEngine(initial_balance=request.initial_balance)
    kline_dict = {f"{request.symbol}_{request.period}": klines}
    params = json.loads(program.params) if program.params else {}

    result = engine.run(
        code=program.code,
        klines=kline_dict,
        symbol=request.symbol,
        period=request.period,
        params=params,
    )

    program.last_backtest_result = json.dumps({
        "total_trades": result.total_trades,
        "win_rate": result.win_rate,
        "total_pnl": result.total_pnl,
        "max_drawdown": result.max_drawdown,
    })
    program.last_backtest_at = datetime.utcnow()
    db.commit()

    return LegacyBacktestResponse(
        success=result.success,
        error=result.error,
        total_trades=result.total_trades,
        winning_trades=result.winning_trades,
        losing_trades=result.losing_trades,
        win_rate=result.win_rate,
        total_pnl=result.total_pnl,
        max_drawdown=result.max_drawdown,
        equity_curve=result.equity_curve[-100:] if result.equity_curve else [],
    )


# ============================================================================
