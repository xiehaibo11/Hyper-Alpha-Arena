"""Outcome memory — the learning half of the borrowed TradingAgents loop.

TradingAgents stores each decision, reflects once the outcome is known, and
recalls past lessons into future prompts (see reflection.py / memory.py in the
borrowed framework). In the event-contract domain the "decision log" already
exists as settled `EventContractOrder` rows (result = win/loss), so this learns
*deterministically* from them: realised win rate per direction and over a recent
window, then adapts the next decision.

Two adaptations, both pure and backtestable:
  • structural gate — if a direction's long-run win rate sits below breakeven
    (with enough samples), stop taking that side.
  • cooldown      — if the recent window is losing, demand higher conviction.

Graceful by design: with too little history it returns decisions unchanged, so
it never hurts and improves as orders accumulate. This protects realised win
rate against edge decay / regime shift — exactly what the reflection loop is for.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from .state import SignalDecision


@dataclass
class DirStats:
    wins: int = 0
    total: int = 0

    @property
    def winrate(self) -> float | None:
        return (self.wins / self.total) if self.total else None


class SignalMemory:
    """Online learner over settled outcomes (chronological)."""

    def __init__(self, payout: float = 0.8, recent_window: int = 20):
        self.payout = payout
        self._dir: dict[str, DirStats] = defaultdict(DirStats)
        self._recent: deque[bool] = deque(maxlen=recent_window)

    # --- learning -----------------------------------------------------------

    def record(self, direction: str, won: bool) -> None:
        s = self._dir[direction]
        s.total += 1
        s.wins += int(won)
        self._recent.append(bool(won))

    @classmethod
    def from_orders(cls, orders: list[dict], payout: float = 0.8,
                    recent_window: int = 20) -> "SignalMemory":
        """Build from settled order dicts (oldest first). Ignores pending."""
        m = cls(payout, recent_window)
        for o in orders:
            if o.get("result") in ("win", "loss") and o.get("direction"):
                m.record(o["direction"], o["result"] == "win")
        return m

    # --- recall -------------------------------------------------------------

    def breakeven(self) -> float:
        return 1.0 / (1.0 + self.payout)

    def directional_winrate(self, direction: str) -> float | None:
        return self._dir[direction].winrate

    def recent_winrate(self) -> float | None:
        return (sum(self._recent) / len(self._recent)) if self._recent else None

    # --- adapt --------------------------------------------------------------

    def gate(self, decision: SignalDecision, params: dict) -> SignalDecision:
        """Veto or hold a proposed trade based on learned outcomes."""
        if decision.abstained or decision.direction is None:
            return decision
        be = self.breakeven()
        d = decision.direction

        def _abstain(reason: str) -> SignalDecision:
            return SignalDecision(
                None, decision.conviction, True, reason,
                reports=decision.reports,
                bull_score=decision.bull_score, bear_score=decision.bear_score,
            )

        # structural gate: this direction is a long-run loser here
        min_samples = params.get("mem_min_samples", 20)
        margin = params.get("mem_margin", 0.0)
        s = self._dir[d]
        if s.total >= min_samples and s.winrate is not None and s.winrate < be + margin:
            return _abstain(f"memory: {d} win rate {s.winrate:.0%} < breakeven {be:.0%}")

        # cooldown: recent window losing -> demand higher conviction
        cd_n = params.get("mem_cooldown_window", 10)
        rw = self.recent_winrate()
        if rw is not None and len(self._recent) >= cd_n and rw < be:
            need = params.get("mem_cooldown_conviction",
                              params.get("conviction_threshold", 1.0) * 1.5)
            if decision.conviction < need:
                return _abstain(f"memory cooldown: recent {rw:.0%} < breakeven {be:.0%}")

        return decision
