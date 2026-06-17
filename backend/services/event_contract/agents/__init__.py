"""Multi-agent signal engine for the event-contract system.

Framework borrowed from `开源项目，借鉴/TradingAgents` (analysts -> bull/bear
debate -> portfolio-manager synthesis), adapted to 1m order-flow features and
this repo's infrastructure. Exposed to the rest of the system as the
`agent_consensus` signal (see signal.py / orderflow.OF_SIGNALS).
"""
from .adaptive import adaptive_direction, gate_live, replay_adaptive
from .graph import run_signal_graph
from .memory import SignalMemory
from .reflection import summarize
from .signal import agent_consensus, agent_consensus_decision
from .state import AnalystReport, DebateState, SignalDecision

__all__ = [
    "run_signal_graph",
    "agent_consensus",
    "agent_consensus_decision",
    "AnalystReport",
    "DebateState",
    "SignalDecision",
    "SignalMemory",
    "summarize",
    "replay_adaptive",
    "gate_live",
    "adaptive_direction",
]
