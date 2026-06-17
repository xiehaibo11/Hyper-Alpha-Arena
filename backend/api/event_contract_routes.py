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


@router.get("/knowledge")
def knowledge():
    """高级交易知识库：指标说明（含每个指标的"坑"）+ 陷阱图条目。"""
    from services.event_contract.agents.knowledge import INDICATOR_CATALOG, TRAP_LIBRARY
    return {"indicators": INDICATOR_CATALOG,
            "traps": [{"id": k, **v} for k, v in TRAP_LIBRARY.items()]}


@router.get("/analysis")
def analysis(
    symbol: str = Query("BTC"),
    exchange: str = Query(ec_config.DEFAULT_EXCHANGE),
    period: str = Query("1m"),
    limit: int = Query(300, ge=60, le=1000),
):
    """左侧分析面板：当前 K 线高级解读、做多/做空理由、踩中的陷阱（坑）。"""
    from services.event_contract.agents.analysis import analyze
    from services.event_contract.data import load_klines
    kl = load_klines(exchange, symbol, limit=limit, period=period)
    if kl.empty or len(kl) < 30:
        return {"symbol": symbol, "exchange": exchange, "period": period,
                "available": False, "report": None}
    rep = analyze(kl)
    return {"symbol": symbol, "exchange": exchange, "period": period,
            "available": True, "report": rep.as_dict()}


@router.get("/klines/history")
def klines_history(
    symbol: str = Query("BTC"),
    exchange: str = Query(ec_config.DEFAULT_EXCHANGE),
    period: str = Query("1d"),
    limit: int = Query(365, ge=1, le=1500),
):
    """历史 K 线（默认日线，limit=365 ≈ 过去一年走势）。"""
    from services.event_contract.data import load_klines
    kl = load_klines(exchange, symbol, limit=limit, period=period)
    candles = [
        {"time": int(r.timestamp), "open": float(r.open), "high": float(r.high),
         "low": float(r.low), "close": float(r.close), "volume": float(r.volume)}
        for r in kl.itertuples()
    ]
    return {"symbol": symbol, "exchange": exchange, "period": period,
            "count": len(candles), "candles": candles}


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


@router.get("/signals/history")
def signals_history(
    symbol: str = Query("BTC"),
    expiry_minutes: int = Query(5),
    exchange: str = Query(ec_config.DEFAULT_EXCHANGE),
    limit: int = Query(180, le=600),
):
    """Closed 1m candles + non-repainting signal arrows for the chart.

    Markers come from EventContractOrder (mode='live'), which the simulator
    only writes when a 1m candle CLOSES and a signal is confirmed. They never
    move, so arrows never repaint. The arrow sits on the signal candle; entry
    happens on the next candle's open.
    """
    from datetime import datetime, timezone
    from services.event_contract.data import load_klines

    kl = load_klines(exchange, symbol, limit=limit)
    candles = []
    if not kl.empty:
        for row in kl.itertuples(index=False):
            candles.append({
                "time": int(row.timestamp), "open": float(row.open),
                "high": float(row.high), "low": float(row.low),
                "close": float(row.close),
            })

    markers = []
    if candles:
        first_dt = datetime.fromtimestamp(candles[0]["time"], tz=timezone.utc)
        db = SessionLocal()
        try:
            rows = (
                db.query(EventContractOrder)
                .filter(
                    EventContractOrder.mode == "live",
                    EventContractOrder.symbol == symbol,
                    EventContractOrder.expiry_minutes == expiry_minutes,
                    EventContractOrder.exchange == exchange,
                    EventContractOrder.signal_time >= first_dt,
                )
                .order_by(EventContractOrder.signal_time.asc())
                .all()
            )
            for o in rows:
                markers.append({
                    "time": int(o.signal_time.timestamp()),
                    "direction": o.direction, "result": o.result,
                    "entry_price": o.entry_price, "settle_price": o.settle_price,
                })
        finally:
            db.close()

    return {
        "exchange": exchange, "symbol": symbol, "expiry_minutes": expiry_minutes,
        "candles": candles, "markers": markers,
    }


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
