"""Portfolio-manager layer: turn the debate into trade-or-abstain.

This is where win rate is bought. Three gates must all pass to fire a trade;
otherwise the manager abstains (returns direction=None). Abstaining on conflicted
or thin setups is the whole point — fewer signals, higher hit-rate.

Gates:
  1. conviction: |net| >= conviction_threshold
  2. consensus : at least `min_agree` directional analysts on the winning side
  3. primary   : the primary edge (cvd_fade) must agree, or at least not oppose
"""
from __future__ import annotations

from .analysts import PRIMARY_ANALYST
from .state import AnalystReport, DebateState, SignalDecision

_REGIME = {"volume_regime", "consistency"}


def _agree_count(reports: list[AnalystReport], side: str) -> int:
    return sum(
        1 for r in reports
        if r.name not in _REGIME and r.direction == side and r.confidence > 0
    )


def decide(reports: list[AnalystReport], debate: DebateState, params: dict) -> SignalDecision:
    threshold = params.get("conviction_threshold", 1.0)
    min_agree = params.get("min_agree", 2)
    require_primary = params.get("require_primary", True)

    net = debate.net
    direction = "long" if net > 0 else ("short" if net < 0 else None)
    conviction = abs(net)

    base = dict(reports=reports,
                bull_score=debate.bull_score, bear_score=debate.bear_score)

    if direction is None:
        return SignalDecision(None, conviction, True, "no directional edge", **base)

    # gate 1: conviction
    if conviction < threshold:
        return SignalDecision(None, conviction, True,
                              f"low conviction {conviction:.2f}<{threshold}", **base)

    # gate 2: consensus breadth
    agree = _agree_count(reports, direction)
    if agree < min_agree:
        return SignalDecision(None, conviction, True,
                              f"thin consensus {agree}<{min_agree}", **base)

    # gate 3: primary edge alignment
    if require_primary:
        primary = next((r for r in reports if r.name == PRIMARY_ANALYST), None)
        if primary is not None and primary.direction is not None \
                and primary.direction != direction:
            return SignalDecision(None, conviction, True,
                                  "primary edge opposes consensus", **base)

    return SignalDecision(direction, conviction, False,
                          f"{direction} conviction={conviction:.2f} agree={agree}", **base)
