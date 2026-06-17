"""Live forward paper-simulator for the event-contract system.

Every cycle (scheduled ~once per minute):
1. evaluate the default order-flow signal on the last *closed* 1m minute,
2. open a pending simulated order (entry = current price, settle = +expiry),
3. settle any pending orders whose settle time has passed.

No real orders are placed (clients trade manually). Rows land in
event_contract_orders with mode='live'.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from database.connection import SessionLocal
from database.models_event_contract import EventContractOrder
from .config import DEFAULT_EXCHANGE
from . import config_store as cfg
from .data import load_klines
from .execution import get_execution_backend
from .orderflow import OF_SIGNALS, load_orderflow

logger = logging.getLogger(__name__)
_LOOKBACK = 60


def _utc(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _last_closed_signal(symbol: str, expiry: int, exchange: str) -> Optional[dict]:
    """Evaluate the default signal on the last closed minute. Returns dict or None."""
    feat = load_orderflow(exchange, symbol, limit=500)
    if feat.empty:
        return None
    now_minute = (int(time.time()) // 60) * 60
    closed = feat[feat["minute"] < now_minute]
    sig_name = cfg.default_signal()
    params = cfg.params_for(symbol, expiry)
    # lookback must cover the signal's window (e.g. cvd-fade z-score over `window`
    # bars); a fixed 60 would silently zero out any window > 60.
    lookback = max(_LOOKBACK, int(params.get("window", 30)) + 5)
    if len(closed) < lookback + 1:
        return None
    window = closed.tail(lookback)
    if sig_name == "ai_llm":
        # AI(LLM)大脑:对该空闲格出 long/short/none
        from . import ai_decision
        direction = ai_decision.decide(symbol, expiry, exchange).get("direction")
    elif cfg.adaptive() and sig_name == "agent_consensus":
        # run the multi-agent engine through the reflection/memory loop:
        # it learns from this cell's settled outcomes and vetoes losing setups.
        from .agents import adaptive_direction
        direction = adaptive_direction(window, params, symbol, expiry, exchange, cfg.payout())
    else:
        direction = OF_SIGNALS[sig_name](window, params)
    return {
        "symbol": symbol,
        "expiry": expiry,
        "signal_minute": int(closed["minute"].iloc[-1]),
        "direction": direction,  # 'long'|'short'|None
    }


def current_signals(exchange: str = DEFAULT_EXCHANGE) -> list[dict]:
    """Live signal board state for the UI: long/short/none per symbol+expiry.

    In ai_llm mode the board reflects the current open (pending) position per cell
    rather than re-evaluating — AI decisions are made (and cost tokens) only in the
    scheduled run_cycle, never on every UI poll.
    """
    out: list[dict] = []
    ai_mode = cfg.default_signal() == "ai_llm"
    db = SessionLocal() if ai_mode else None
    try:
        for symbol in cfg.symbols():
            kl = load_klines(exchange, symbol, limit=5)
            price = float(kl["close"].iloc[-1]) if not kl.empty else None
            for expiry in cfg.expiries():
                if ai_mode:
                    o = (db.query(EventContractOrder)
                         .filter(EventContractOrder.mode == "live",
                                 EventContractOrder.symbol == symbol,
                                 EventContractOrder.expiry_minutes == expiry,
                                 EventContractOrder.exchange == exchange,
                                 EventContractOrder.result == "pending")
                         .order_by(EventContractOrder.id.desc()).first())
                    direction = o.direction if o else "none"
                    signal_minute = int(o.signal_time.timestamp()) if o and o.signal_time else None
                else:
                    sig = _last_closed_signal(symbol, expiry, exchange)
                    direction = (sig or {}).get("direction") or "none"
                    signal_minute = (sig or {}).get("signal_minute")
                out.append({
                    "exchange": exchange,
                    "symbol": symbol,
                    "expiry_minutes": expiry,
                    "direction": direction,
                    "signal_minute": signal_minute,
                    "price": price,
                })
    finally:
        if db is not None:
            db.close()
    return out


def run_signal_cycle(exchange: str = DEFAULT_EXCHANGE) -> int:
    """Open pending simulated orders for any fired signal. Returns # opened."""
    opened = 0
    db = SessionLocal()
    try:
        kl_cache: dict[str, float] = {}
        for symbol in cfg.symbols():
            kl = load_klines(exchange, symbol, limit=5)
            if not kl.empty:
                kl_cache[symbol] = float(kl["close"].iloc[-1])
            for expiry in cfg.expiries():
                # one position at a time per cell: while an order is still open
                # (unsettled) for this symbol+expiry, do NOT open a new one — no
                # overlapping signals within an in-flight contract.
                open_exists = db.query(EventContractOrder.id).filter(
                    EventContractOrder.mode == "live",
                    EventContractOrder.symbol == symbol,
                    EventContractOrder.expiry_minutes == expiry,
                    EventContractOrder.exchange == exchange,
                    EventContractOrder.result == "pending",
                ).first()
                if open_exists:
                    continue
                sig = _last_closed_signal(symbol, expiry, exchange)
                if not sig or not sig["direction"]:
                    continue
                price = kl_cache.get(symbol)
                if price is None:
                    continue
                entry_min = sig["signal_minute"] + 60
                signal_dt = _utc(sig["signal_minute"])
                # dedupe: one order per (mode,symbol,expiry,signal_time)
                exists = db.query(EventContractOrder.id).filter(
                    EventContractOrder.mode == "live",
                    EventContractOrder.symbol == symbol,
                    EventContractOrder.expiry_minutes == expiry,
                    EventContractOrder.signal_time == signal_dt,
                ).first()
                if exists:
                    continue
                db.add(EventContractOrder(
                    mode="live", exchange=exchange, symbol=symbol,
                    strategy=cfg.default_signal(), direction=sig["direction"],
                    expiry_minutes=expiry, signal_time=signal_dt,
                    entry_time=_utc(entry_min), entry_price=price,
                    settle_time=_utc(entry_min + expiry * 60),
                    result="pending", payout=cfg.payout(),
                ))
                opened += 1
        if opened:
            db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"[event_contract] signal cycle error: {e}")
    finally:
        db.close()
    return opened


def settle_due_orders(exchange: str = DEFAULT_EXCHANGE) -> int:
    """Settle pending orders whose settle_time has passed. Returns # settled."""
    settled = 0
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        due = db.query(EventContractOrder).filter(
            EventContractOrder.mode == "live",
            EventContractOrder.result == "pending",
            EventContractOrder.settle_time <= now,
        ).all()
        if not due:
            return 0
        price_maps: dict[str, dict] = {}
        for o in due:
            if o.symbol not in price_maps:
                kl = load_klines(o.exchange or exchange, o.symbol, limit=1200)
                price_maps[o.symbol] = dict(zip(kl["timestamp"].tolist(), kl["open"].tolist())) if not kl.empty else {}
            settle_ts = int(o.settle_time.timestamp())
            sp = price_maps[o.symbol].get(settle_ts)
            if sp is None:
                # fallback: nearest available candle at/after settle time
                later = [t for t in price_maps[o.symbol] if t >= settle_ts]
                if not later:
                    continue
                sp = price_maps[o.symbol][min(later)]
            get_execution_backend().settle_order(o, float(sp))
            settled += 1
        if settled:
            db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"[event_contract] settle error: {e}")
    finally:
        db.close()
    return settled


def run_cycle(exchange: str = DEFAULT_EXCHANGE) -> dict:
    """One full tick: persist latest klines, settle due first, then open signals.
    Settling first frees a just-expired cell so the no-overlap guard allows a
    fresh entry."""
    try:
        # keep the DB order-flow / price history fresh & growing for tuning
        from .backfill import refresh_recent
        refresh_recent(exchange)
    except Exception as e:
        logger.debug(f"[event_contract] refresh_recent skipped: {e}")
    settled = settle_due_orders(exchange)
    opened = run_signal_cycle(exchange)
    if opened or settled:
        logger.info(f"[event_contract] cycle: opened={opened} settled={settled}")
    return {"opened": opened, "settled": settled}
