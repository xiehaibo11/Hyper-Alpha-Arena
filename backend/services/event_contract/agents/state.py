"""Shared state for the multi-agent signal engine.

Mirrors TradingAgents' AgentState/debate-state pattern (see the borrowed
framework in `开源项目，借鉴/TradingAgents`), specialised for the event-contract
domain: instead of long natural-language reports the agents exchange compact,
typed directional views over 1m order-flow features.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

Direction = Optional[str]  # 'long' | 'short' | None


@dataclass
class AnalystReport:
    """One analyst's directional view, the unit of evidence in the debate."""
    name: str
    direction: Direction          # 'long' | 'short' | None (no opinion)
    confidence: float             # 0..1, strength of this view
    rationale: str = ""

    @property
    def long_score(self) -> float:
        return self.confidence if self.direction == "long" else 0.0

    @property
    def short_score(self) -> float:
        return self.confidence if self.direction == "short" else 0.0


@dataclass
class DebateState:
    """Aggregated bull vs. bear case, the TradingAgents researcher layer."""
    bull_score: float = 0.0
    bear_score: float = 0.0
    bull_points: list[str] = field(default_factory=list)
    bear_points: list[str] = field(default_factory=list)
    regime_multiplier: float = 1.0  # confidence scaling from regime analysts

    @property
    def net(self) -> float:
        """Signed conviction: positive = long, negative = short."""
        return (self.bull_score - self.bear_score) * self.regime_multiplier


@dataclass
class SignalDecision:
    """The portfolio-manager output: trade or abstain, with an audit trail."""
    direction: Direction          # 'long' | 'short' | None (abstain)
    conviction: float             # |net| at decision time
    abstained: bool
    reason: str
    reports: list[AnalystReport] = field(default_factory=list)
    bull_score: float = 0.0
    bear_score: float = 0.0

    def as_dict(self) -> dict:
        return {
            "direction": self.direction,
            "conviction": round(self.conviction, 4),
            "abstained": self.abstained,
            "reason": self.reason,
            "bull_score": round(self.bull_score, 4),
            "bear_score": round(self.bear_score, 4),
            "reports": [
                {
                    "name": r.name,
                    "direction": r.direction,
                    "confidence": round(r.confidence, 4),
                    "rationale": r.rationale,
                }
                for r in self.reports
            ],
        }
