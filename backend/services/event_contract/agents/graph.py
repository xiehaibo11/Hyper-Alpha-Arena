"""Orchestrator — the TradingAgents `trading_graph` equivalent.

Wires the layers end-to-end for one decision:

    features -> analysts -> bull/bear debate -> manager -> (optional LLM judge)
             -> SignalDecision (trade or abstain)

Kept as a lightweight sequential pipeline (no LangGraph: this repo calls LLMs
directly and runs the engine every minute, so a heavy graph runtime would add
dependency weight and latency for no benefit). The structure — typed shared
state, analyst factories, a bull/bear research debate, and a manager synthesis
with an abstain path — is copied faithfully from the borrowed framework.
"""
from __future__ import annotations

import pandas as pd

from . import manager
from .analysts import run_analysts
from .config import merge_params
from .llm_judge import review
from .researchers import run_debate
from .state import SignalDecision


def run_signal_graph(f: pd.DataFrame, params: dict | None = None) -> SignalDecision:
    """Run the full multi-agent flow over a window of 1m order-flow features."""
    p = merge_params(params)
    if f is None or len(f) < p["window"] + 1:
        return SignalDecision(None, 0.0, True, "insufficient history", [])

    reports = run_analysts(f, p)        # analyst layer
    debate = run_debate(reports)        # researcher (bull/bear) layer
    decision = manager.decide(reports, debate, p)  # portfolio-manager layer
    decision = review(decision, p)      # optional LLM veto
    return decision
