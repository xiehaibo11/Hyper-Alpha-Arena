"""Researcher (debate) layer: bull vs. bear, the TradingAgents pattern.

The bull researcher tallies the long-leaning evidence, the bear the short. A
regime multiplier (from non-directional analysts) scales the whole debate so
thin-tape or choppy conditions shrink conviction. Output is a DebateState the
manager judges.
"""
from __future__ import annotations

from .state import AnalystReport, DebateState

# analysts whose confidence is a regime weight rather than a directional vote
_REGIME = {"volume_regime", "consistency"}


def bull_researcher(reports: list[AnalystReport]) -> tuple[float, list[str]]:
    """Sum long-leaning conviction and record the supporting points."""
    score = 0.0
    points: list[str] = []
    for r in reports:
        if r.name in _REGIME:
            continue
        if r.long_score > 0:
            score += r.long_score
            points.append(f"{r.name}: long ({r.confidence:.2f}) — {r.rationale}")
    return score, points


def bear_researcher(reports: list[AnalystReport]) -> tuple[float, list[str]]:
    """Sum short-leaning conviction and record the supporting points."""
    score = 0.0
    points: list[str] = []
    for r in reports:
        if r.name in _REGIME:
            continue
        if r.short_score > 0:
            score += r.short_score
            points.append(f"{r.name}: short ({r.confidence:.2f}) — {r.rationale}")
    return score, points


def _regime_multiplier(reports: list[AnalystReport]) -> float:
    """Product of regime weights (each in ~[0,1]); 1.0 if none present."""
    mult = 1.0
    found = False
    for r in reports:
        if r.name in _REGIME:
            mult *= max(0.1, r.confidence)
            found = True
    return mult if found else 1.0


def run_debate(reports: list[AnalystReport]) -> DebateState:
    bull_score, bull_points = bull_researcher(reports)
    bear_score, bear_points = bear_researcher(reports)
    return DebateState(
        bull_score=bull_score,
        bear_score=bear_score,
        bull_points=bull_points,
        bear_points=bear_points,
        regime_multiplier=_regime_multiplier(reports),
    )
