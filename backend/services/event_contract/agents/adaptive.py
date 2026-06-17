"""Adaptive layer — runs the consensus engine *with* the memory loop active.

Two entry points:
  • replay_adaptive(): online backtest that learns from its own simulated
    outcomes as it goes — the correct way to measure an adaptive strategy, and
    what the UI/route uses to show the client the effect.
  • gate_live(): for the live simulator — builds memory from recent settled
    EventContractOrder rows for the cell and vetoes a proposed trade. Best-effort
    and fully defensive: any DB issue returns the original decision unchanged.
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from .graph import run_signal_graph
from .memory import SignalMemory
from .state import SignalDecision

logger = logging.getLogger(__name__)


def replay_adaptive(
    feat_df: pd.DataFrame, ts_open: dict, params: dict,
    expiry_minutes: int, payout: float = 0.8, use_memory: bool = True,
) -> dict:
    """Replay agent_consensus over a feature frame, learning online."""
    mem = SignalMemory(payout=payout, recent_window=params.get("recent_window", 20))
    minutes = feat_df["minute"].tolist()
    look, total, wins, skipped = 60, 0, 0, 0
    cum = 0.0
    for i in range(40, len(feat_df)):
        dec = run_signal_graph(feat_df.iloc[max(0, i - look): i + 1], params)
        if use_memory:
            gated = mem.gate(dec, params)
            if gated.abstained and not dec.abstained:
                skipped += 1
            dec = gated
        if dec.direction is None:
            continue
        ep = ts_open.get(minutes[i] + 60)
        sp = ts_open.get(minutes[i] + 60 + expiry_minutes * 60)
        if ep is None or sp is None:
            continue
        won = sp > ep if dec.direction == "long" else sp < ep
        total += 1
        wins += int(won)
        cum += payout if won else -1.0
        mem.record(dec.direction, won)
    return {
        "total": total, "wins": wins,
        "win_rate": round(wins / total, 4) if total else 0.0,
        "net_pnl": round(cum, 4), "skipped_by_memory": skipped,
        "memory": None if not use_memory else {
            "long": mem.directional_winrate("long"),
            "short": mem.directional_winrate("short"),
            "recent": mem.recent_winrate(),
        },
    }


def _load_recent_orders(symbol: str, expiry: int, exchange: str, limit: int) -> list[dict]:
    """Most-recent settled orders for a cell, oldest-first (live use only)."""
    from database.connection import SessionLocal
    from database.models_event_contract import EventContractOrder
    db = SessionLocal()
    try:
        rows = (
            db.query(EventContractOrder)
            .filter(
                EventContractOrder.mode == "live",
                EventContractOrder.symbol == symbol,
                EventContractOrder.expiry_minutes == expiry,
                EventContractOrder.exchange == exchange,
                EventContractOrder.result.in_(("win", "loss")),
            )
            .order_by(EventContractOrder.settle_time.desc())
            .limit(limit)
            .all()
        )
        return [{"direction": r.direction, "result": r.result} for r in reversed(rows)]
    finally:
        db.close()


def gate_live(
    decision: SignalDecision, symbol: str, expiry: int,
    exchange: str, params: dict, payout: float = 0.8,
) -> SignalDecision:
    """Apply the memory gate using this cell's recent settled outcomes."""
    if decision.abstained or decision.direction is None:
        return decision
    try:
        orders = _load_recent_orders(
            symbol, expiry, exchange, params.get("mem_history_limit", 200))
        mem = SignalMemory.from_orders(
            orders, payout=payout, recent_window=params.get("recent_window", 20))
        return mem.gate(decision, params)
    except Exception as e:  # never block the live loop
        logger.debug("[event_contract] memory gate skipped: %s", e)
        return decision


def adaptive_direction(
    f: pd.DataFrame, params: dict, symbol: str, expiry: int,
    exchange: str, payout: float = 0.8,
) -> Optional[str]:
    """Live convenience: full consensus decision + memory gate -> direction."""
    dec = run_signal_graph(f, params)
    dec = gate_live(dec, symbol, expiry, exchange, params, payout)
    return dec.direction
