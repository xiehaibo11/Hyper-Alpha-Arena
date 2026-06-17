"""Adapter that exposes the multi-agent engine as a standard signal function.

`agent_consensus(feat_df, params) -> 'long'|'short'|None` matches the OF_SIGNALS
interface, so the existing live simulator, backtest harness and UI use the
multi-agent engine with zero changes — just select it as the signal.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .graph import run_signal_graph


def agent_consensus(f: pd.DataFrame, p: dict) -> Optional[str]:
    """Multi-agent consensus direction (None = abstain)."""
    return run_signal_graph(f, p).direction


def agent_consensus_decision(f: pd.DataFrame, p: dict):
    """Full SignalDecision (direction + conviction + analyst audit trail).

    Used by the UI/diagnostics to show *why* a signal fired or was withheld.
    """
    return run_signal_graph(f, p)
