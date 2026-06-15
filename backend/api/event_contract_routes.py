"""Event-contract (binary up/down) signal system API."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from database.connection import SessionLocal
from database.models_event_contract import EventContractOrder
from services.event_contract import config as ec_config  # static defaults (DEFAULT_EXCHANGE)
from services.event_contract import config_store as ec_store
import os
from services.event_contract.backtest import compare_strategies, run_backtest
from services.event_contract.orderflow import OF_SIGNALS, backtest_orderflow, compare_orderflow
from services.event_contract.platforms import overview as platforms_overview
from services.event_contract.simulator import current_signals
from services.event_contract.stats import daily_stats
from services.event_contract.strategies import list_strategies

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/event-contract", tags=["event-contract"])


@router.get("/overview")
def overview():
    cfg = ec_store.get_config()
    return {
        "platforms": platforms_overview(),
        "symbols": cfg["symbols"],
        "expiries": cfg["expiries"],
        "default_exchange": ec_config.DEFAULT_EXCHANGE,
        "default_signal": cfg["default_signal"],
        "payout": cfg["payout"],
    }


@router.get("/strategies")
def strategies():
    return {"ta": list_strategies(), "order_flow": list(OF_SIGNALS.keys())}


@router.get("/signals/live")
def signals_live(exchange: str = Query(ec_config.DEFAULT_EXCHANGE)):
    return {"signals": current_signals(exchange)}


@router.get("/stats/daily")
def stats_daily(mode: str = Query("live")):
    return daily_stats(mode)


@router.get("/orders")
def orders(mode: str = Query("live"), limit: int = Query(50, le=500)):
    db = SessionLocal()
    try:
        rows = (
            db.query(EventContractOrder)
            .filter(EventContractOrder.mode == mode)
            .order_by(EventContractOrder.id.desc())
            .limit(limit)
            .all()
        )
        return {
            "orders": [
                {
                    "id": o.id, "symbol": o.symbol, "direction": o.direction,
                    "expiry_minutes": o.expiry_minutes,
                    "entry_time": o.entry_time.isoformat() if o.entry_time else None,
                    "entry_price": o.entry_price, "settle_price": o.settle_price,
                    "result": o.result, "pnl": o.pnl, "exchange": o.exchange,
                }
                for o in rows
            ]
        }
    finally:
        db.close()


class BacktestRequest(BaseModel):
    type: str = "order_flow"          # 'order_flow' | 'ta'
    exchange: str = ec_config.DEFAULT_EXCHANGE
    symbol: str = "BTC"
    expiry_minutes: int = 5
    signal: Optional[str] = None      # strategy / order-flow signal name
    params: Optional[dict] = None
    payout: float = ec_config.PAYOUT


@router.post("/backtest")
def backtest(req: BacktestRequest):
    if req.type == "ta":
        name = req.signal or "zscore_reversion"
        return run_backtest(req.exchange, req.symbol, req.expiry_minutes, name,
                            req.params, payout=req.payout)
    name = req.signal or ec_config.DEFAULT_SIGNAL
    return backtest_orderflow(req.exchange, req.symbol, req.expiry_minutes, name,
                              req.params, payout=req.payout)


@router.get("/backtest/compare")
def backtest_compare(
    exchange: str = Query(ec_config.DEFAULT_EXCHANGE),
    symbol: str = Query("BTC"),
    expiry_minutes: int = Query(5),
    payout: float = Query(ec_config.PAYOUT),
):
    return {
        "order_flow": compare_orderflow(exchange, symbol, expiry_minutes, payout=payout),
        "ta": compare_strategies(exchange, symbol, expiry_minutes, payout=payout),
    }


class EventContractConfigPatch(BaseModel):
    symbols: list[str] | None = None
    expiries: list[int] | None = None
    payout: float | None = None
    default_signal: str | None = None
    daily_reset_tz: str | None = None
    signal_params: dict | None = None


@router.get("/config")
def get_event_contract_config():
    return ec_store.get_config()


@router.put("/config")
def update_event_contract_config(patch: EventContractConfigPatch):
    return ec_store.save_config(patch.model_dump(exclude_none=True))


@router.get("/branding")
def get_branding():
    return {
        "site_name": os.getenv("SITE_NAME", "Hyper Alpha Arena"),
        "site_url": os.getenv("SITE_URL", "/"),
        "site_logo": os.getenv("SITE_LOGO", "/static/logo_app.png"),
    }
