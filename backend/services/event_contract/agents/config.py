"""Defaults for the multi-agent signal engine.

These merge *under* the per-cell params the simulator/backtest already pass
(`{window, thr}` from event_contract/config.py), so the agent engine reuses the
validated order-flow window/threshold and adds its own consensus controls.

Tune `conviction_threshold` / `min_agree` up to trade less but win more.
"""
from __future__ import annotations

DEFAULT_AGENT_PARAMS: dict = {
    # inherited edge params (overridden by per-cell params when provided)
    "window": 30,
    "thr": 1.5,
    # consensus controls (the win-rate levers)
    "conviction_threshold": 1.0,   # require |net| >= this to fire
    "min_agree": 2,                # directional analysts that must agree
    "require_primary": True,       # cvd_fade must not oppose the consensus
    # optional LLM portfolio-manager judge (off by default; see llm_judge.py)
    "use_llm": False,
}


def merge_params(params: dict | None) -> dict:
    return {**DEFAULT_AGENT_PARAMS, **(params or {})}
