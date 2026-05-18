"""Trade replay analytics routes."""

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import AIDecisionLog
from database.snapshot_connection import SnapshotSessionLocal
from database.snapshot_models import HyperliquidTrade
from services.analytics_trade_helpers import get_exit_type, parse_decision_prices

logger = logging.getLogger(__name__)

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/trades/{trade_id}/replay")
def get_trade_replay(
    trade_id: int,
    db: Session = Depends(get_db),
):
    """Get trade replay data including decision chain and trade details."""
    trade = db.query(AIDecisionLog).filter(AIDecisionLog.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    is_entry = trade.operation in ("buy", "sell")

    entry_decision = None
    exit_decision = None
    entry_time = None
    exit_time = None

    tp_sl_trigger_time = None
    tp_sl_exit_type = None

    if is_entry and trade.realized_pnl:
        entry_decision = trade
        exit_decision = trade
        entry_time = trade.decision_time

        tp_sl_order_id = trade.tp_order_id or trade.sl_order_id
        if tp_sl_order_id:
            try:
                snapshot_db = SnapshotSessionLocal()
                hl_trade = snapshot_db.query(HyperliquidTrade).filter(
                    HyperliquidTrade.order_id == str(tp_sl_order_id)
                ).first()
                if hl_trade and hl_trade.trade_time:
                    tp_sl_trigger_time = hl_trade.trade_time
                    tp_sl_exit_type = "TP" if float(trade.realized_pnl) > 0 else "SL"
                snapshot_db.close()
            except Exception as exc:
                logger.warning(f"Failed to get TP/SL trigger time: {exc}")

        exit_time = tp_sl_trigger_time or trade.pnl_updated_at or trade.decision_time
    elif is_entry:
        entry_decision = trade
        entry_time = trade.decision_time
        exit_decision = db.query(AIDecisionLog).filter(
            AIDecisionLog.symbol == trade.symbol,
            AIDecisionLog.wallet_address == trade.wallet_address,
            AIDecisionLog.operation == "close",
            AIDecisionLog.decision_time > trade.decision_time,
        ).order_by(AIDecisionLog.decision_time.asc()).first()
        if exit_decision:
            exit_time = exit_decision.decision_time
    else:
        exit_decision = trade
        exit_time = trade.decision_time
        entry_decision = db.query(AIDecisionLog).filter(
            AIDecisionLog.symbol == trade.symbol,
            AIDecisionLog.wallet_address == trade.wallet_address,
            AIDecisionLog.operation.in_(["buy", "sell"]),
            AIDecisionLog.decision_time < trade.decision_time,
        ).order_by(AIDecisionLog.decision_time.desc()).first()
        if entry_decision:
            entry_time = entry_decision.decision_time

    decisions_chain = []
    if entry_time and exit_time:
        chain_query = db.query(AIDecisionLog).filter(
            AIDecisionLog.symbol == trade.symbol,
            AIDecisionLog.wallet_address == trade.wallet_address,
            AIDecisionLog.decision_time >= entry_time,
            AIDecisionLog.decision_time <= exit_time,
        ).order_by(AIDecisionLog.decision_time.asc()).all()

        for decision in chain_query:
            decisions_chain.append({
                "id": decision.id,
                "operation": decision.operation,
                "decision_time": decision.decision_time.isoformat() if decision.decision_time else None,
                "reason": decision.reason,
                "target_portion": float(decision.target_portion) if decision.target_portion else 0,
                "realized_pnl": float(decision.realized_pnl) if decision.realized_pnl else None,
            })

        if is_entry and trade.realized_pnl and (trade.tp_order_id or trade.sl_order_id):
            has_close_decision = any(decision["operation"] == "close" for decision in decisions_chain)
            if not has_close_decision:
                exit_type = tp_sl_exit_type or ("TP" if float(trade.realized_pnl) > 0 else "SL")
                close_time = tp_sl_trigger_time or trade.pnl_updated_at or trade.decision_time
                decisions_chain.append({
                    "id": -1,
                    "operation": "close",
                    "decision_time": close_time.isoformat() if close_time else None,
                    "reason": f"{exit_type} triggered",
                    "target_portion": 1.0,
                    "realized_pnl": float(trade.realized_pnl),
                })

    hold_duration = None
    if entry_time and exit_time:
        hold_duration = str(exit_time - entry_time)

    pnl = float(trade.realized_pnl) if trade.realized_pnl else 0

    return {
        "trade": {
            "id": trade.id,
            "symbol": trade.symbol,
            "operation": trade.operation,
            "decision_time": trade.decision_time.isoformat() if trade.decision_time else None,
            "wallet_address": trade.wallet_address,
            "hyperliquid_environment": trade.hyperliquid_environment,
            "account_id": trade.account_id,
        },
        "entry_decision": {
            "id": entry_decision.id,
            "operation": entry_decision.operation,
            "decision_time": entry_decision.decision_time.isoformat() if entry_decision.decision_time else None,
            "reason": entry_decision.reason,
        } if entry_decision else None,
        "exit_decision": {
            "id": exit_decision.id,
            "operation": exit_decision.operation,
            "decision_time": exit_decision.decision_time.isoformat() if exit_decision.decision_time else None,
            "reason": exit_decision.reason,
            "exit_type": get_exit_type(exit_decision),
        } if exit_decision else None,
        "decisions_chain": decisions_chain,
        "summary": {
            "entry_time": entry_time.isoformat() if entry_time else None,
            "exit_time": exit_time.isoformat() if exit_time else None,
            "hold_duration": hold_duration,
            "pnl": round(pnl, 2),
        },
        "kline_params": {
            "symbol": trade.symbol,
            "start_time": (entry_time - timedelta(hours=1)).isoformat() if entry_time else None,
            "end_time": (exit_time + timedelta(hours=1)).isoformat() if exit_time else None,
        } if entry_time and exit_time else None,
    }


@router.get("/trades/{trade_id}/kline")
def get_trade_replay_kline(
    trade_id: int,
    period: str = Query("5m", description="K-line period: 5m, 15m, 1h, 4h"),
    db: Session = Depends(get_db),
):
    """
    Get K-line data for trade replay with entry/exit markers.

    Returns historical K-line data centered around the trade's entry and exit times.
    """
    from services.hyperliquid_market_data import get_historical_kline_data_from_hyperliquid

    valid_periods = ["5m", "15m", "1h", "4h"]
    if period not in valid_periods:
        raise HTTPException(status_code=400, detail=f"Invalid period. Valid: {valid_periods}")

    trade = db.query(AIDecisionLog).filter(AIDecisionLog.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    is_entry = trade.operation in ("buy", "sell")

    entry_decision = None
    exit_decision = None
    entry_time = None
    exit_time = None
    tp_sl_trigger_time = None
    tp_sl_exit_type = None

    if is_entry and trade.realized_pnl:
        entry_decision = trade
        exit_decision = trade
        entry_time = trade.decision_time

        tp_sl_order_id = trade.tp_order_id or trade.sl_order_id
        if tp_sl_order_id:
            try:
                snapshot_db = SnapshotSessionLocal()
                hl_trade = snapshot_db.query(HyperliquidTrade).filter(
                    HyperliquidTrade.order_id == str(tp_sl_order_id)
                ).first()
                if hl_trade and hl_trade.trade_time:
                    tp_sl_trigger_time = hl_trade.trade_time
                    tp_sl_exit_type = "TP" if float(trade.realized_pnl) > 0 else "SL"
                snapshot_db.close()
            except Exception as exc:
                logger.warning(f"Failed to get TP/SL trigger time for kline: {exc}")

        exit_time = tp_sl_trigger_time or trade.pnl_updated_at or trade.decision_time
    elif is_entry:
        entry_decision = trade
        entry_time = trade.decision_time
        exit_decision = db.query(AIDecisionLog).filter(
            AIDecisionLog.symbol == trade.symbol,
            AIDecisionLog.wallet_address == trade.wallet_address,
            AIDecisionLog.operation == "close",
            AIDecisionLog.decision_time > trade.decision_time,
        ).order_by(AIDecisionLog.decision_time.asc()).first()
        if exit_decision:
            exit_time = exit_decision.decision_time
    else:
        exit_decision = trade
        exit_time = trade.decision_time
        entry_decision = db.query(AIDecisionLog).filter(
            AIDecisionLog.symbol == trade.symbol,
            AIDecisionLog.wallet_address == trade.wallet_address,
            AIDecisionLog.operation.in_(["buy", "sell"]),
            AIDecisionLog.decision_time < trade.decision_time,
        ).order_by(AIDecisionLog.decision_time.desc()).first()
        if entry_decision:
            entry_time = entry_decision.decision_time

    if not entry_time:
        raise HTTPException(status_code=400, detail="Trade has no entry time")

    period_buffer = {"5m": 30, "15m": 60, "1h": 120, "4h": 480}
    buffer_minutes = period_buffer.get(period, 30)

    start_time = entry_time - timedelta(minutes=buffer_minutes)
    if exit_time:
        end_time = exit_time + timedelta(minutes=buffer_minutes)
    else:
        end_time = entry_time + timedelta(hours=4)

    since_ms = int(start_time.timestamp() * 1000)
    until_ms = int(end_time.timestamp() * 1000)

    environment = trade.hyperliquid_environment or "mainnet"
    klines = get_historical_kline_data_from_hyperliquid(
        symbol=trade.symbol,
        period=period,
        since_ms=since_ms,
        until_ms=until_ms,
        environment=environment,
    )

    if not klines:
        from database.models import CryptoKline

        symbol_clean = trade.symbol.upper()
        if symbol_clean.endswith("-PERP"):
            symbol_clean = symbol_clean[:-5]

        local_klines = db.query(CryptoKline).filter(
            CryptoKline.symbol == symbol_clean,
            CryptoKline.period == period,
            CryptoKline.timestamp >= int(since_ms / 1000),
            CryptoKline.timestamp <= int(until_ms / 1000),
            CryptoKline.environment == environment,
        ).order_by(CryptoKline.timestamp).all()

        if local_klines:
            klines = []
            for kline in local_klines:
                open_p = float(kline.open_price) if kline.open_price else None
                close_p = float(kline.close_price) if kline.close_price else None
                chg = (close_p - open_p) if open_p and close_p else 0
                pct = (chg / open_p * 100) if open_p else 0
                klines.append({
                    "timestamp": kline.timestamp,
                    "datetime": kline.datetime_str,
                    "open": open_p,
                    "high": float(kline.high_price) if kline.high_price else None,
                    "low": float(kline.low_price) if kline.low_price else None,
                    "close": close_p,
                    "volume": float(kline.volume) if kline.volume else None,
                    "amount": float(kline.amount) if kline.amount else None,
                    "chg": chg,
                    "percent": pct,
                })
            logger.info(f"Using {len(klines)} local klines for {symbol_clean} {period}")

    if not klines:
        raise HTTPException(
            status_code=404,
            detail="Historical K-line data not available (exchange only keeps recent data)",
        )

    markers = []

    if entry_decision:
        entry_prices = parse_decision_prices(entry_decision)
        markers.append({
            "type": "entry",
            "time": entry_decision.decision_time.isoformat() if entry_decision.decision_time else None,
            "timestamp": int(entry_decision.decision_time.timestamp()) if entry_decision.decision_time else None,
            "operation": entry_decision.operation,
            "reason": entry_decision.reason,
            "target_portion": float(entry_decision.target_portion) if entry_decision.target_portion else None,
            "symbol": trade.symbol,
            "entry_price": entry_prices["entry_price"],
            "tp_price": entry_prices["tp_price"],
            "sl_price": entry_prices["sl_price"],
        })

    if exit_decision and exit_decision.id != entry_decision.id:
        exit_prices = parse_decision_prices(exit_decision)
        markers.append({
            "type": "exit",
            "time": exit_decision.decision_time.isoformat() if exit_decision.decision_time else None,
            "timestamp": int(exit_decision.decision_time.timestamp()) if exit_decision.decision_time else None,
            "operation": exit_decision.operation,
            "reason": exit_decision.reason,
            "exit_type": get_exit_type(exit_decision),
            "realized_pnl": float(trade.realized_pnl) if trade.realized_pnl else None,
            "symbol": trade.symbol,
            "exit_price": exit_prices["exit_price"] or exit_prices["entry_price"],
        })
    elif exit_decision and exit_decision.id == entry_decision.id and trade.realized_pnl:
        entry_prices = parse_decision_prices(entry_decision)
        actual_exit_time = tp_sl_trigger_time or trade.pnl_updated_at or trade.decision_time
        actual_exit_type = tp_sl_exit_type or ("TP" if float(trade.realized_pnl) > 0 else "SL")
        markers.append({
            "type": "exit",
            "time": actual_exit_time.isoformat(),
            "timestamp": int(actual_exit_time.timestamp()),
            "operation": "close",
            "reason": f"{actual_exit_type} triggered",
            "exit_type": actual_exit_type,
            "realized_pnl": float(trade.realized_pnl),
            "symbol": trade.symbol,
            "exit_price": entry_prices["tp_price"] if float(trade.realized_pnl) > 0 else entry_prices["sl_price"],
        })

    if entry_time and exit_time:
        hold_decisions = db.query(AIDecisionLog).filter(
            AIDecisionLog.symbol == trade.symbol,
            AIDecisionLog.wallet_address == trade.wallet_address,
            AIDecisionLog.operation == "hold",
            AIDecisionLog.decision_time > entry_time,
            AIDecisionLog.decision_time < exit_time,
        ).order_by(AIDecisionLog.decision_time.asc()).all()

        for hold in hold_decisions:
            markers.append({
                "type": "hold",
                "time": hold.decision_time.isoformat() if hold.decision_time else None,
                "timestamp": int(hold.decision_time.timestamp()) if hold.decision_time else None,
                "operation": "hold",
                "reason": hold.reason,
                "symbol": trade.symbol,
            })

    default_period = "5m"
    if entry_time and exit_time:
        hold_minutes = (exit_time - entry_time).total_seconds() / 60
        if hold_minutes > 1440:
            default_period = "4h"
        elif hold_minutes > 240:
            default_period = "1h"
        elif hold_minutes > 60:
            default_period = "15m"

    return {
        "symbol": trade.symbol,
        "period": period,
        "default_period": default_period,
        "klines": klines,
        "markers": markers,
        "time_range": {
            "start": start_time.isoformat(),
            "end": end_time.isoformat(),
        },
    }
