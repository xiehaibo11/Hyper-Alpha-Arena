"""Optional LLM portfolio-manager judge — the TradingAgents 'deep-thinking PM'.

Mirrors the role of TradingAgents' Portfolio Manager: a final reviewer that can
*veto* a borderline trade. It is strictly a safety filter — it may turn a trade
into an abstain, but never flips long<->short and never invents a trade the
deterministic engine didn't already propose.

Disabled unless `params['use_llm']` is true AND env is configured:
    EVENT_CONTRACT_LLM_BASE_URL   (OpenAI-compatible /chat/completions base)
    EVENT_CONTRACT_LLM_API_KEY
    EVENT_CONTRACT_LLM_MODEL      (default: gpt-4o-mini)

Every failure path returns the original decision unchanged, so the live signal
loop is never blocked by the network. Off by default — keeps the deployed
server free of per-minute token cost and latency.
"""
from __future__ import annotations

import json
import logging
import os

from .state import SignalDecision

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are the risk-control portfolio manager for a 5/10-minute binary "
    "event-contract signal. You receive a proposed trade and the analyst votes. "
    "Your only job: confirm or veto. Reply with strict JSON "
    '{"confirm": true|false, "reason": "..."}. Veto (confirm=false) only when '
    "the evidence is internally contradictory or clearly too weak to favour the "
    "proposed side. Never suggest the opposite side."
)


def _enabled(params: dict) -> bool:
    return bool(params.get("use_llm")) and bool(os.getenv("EVENT_CONTRACT_LLM_API_KEY"))


def review(decision: SignalDecision, params: dict) -> SignalDecision:
    """Let an LLM veto a proposed trade. No-op if disabled or anything fails."""
    if decision.abstained or decision.direction is None or not _enabled(params):
        return decision
    try:
        import requests  # local import: only when the judge is actually used

        base = os.getenv("EVENT_CONTRACT_LLM_BASE_URL", "https://api.openai.com/v1")
        model = os.getenv("EVENT_CONTRACT_LLM_MODEL", "gpt-4o-mini")
        payload = {
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": json.dumps(decision.as_dict())},
            ],
        }
        resp = requests.post(
            f"{base.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('EVENT_CONTRACT_LLM_API_KEY')}"},
            json=payload, timeout=params.get("llm_timeout", 8),
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        verdict = json.loads(content)
        if not verdict.get("confirm", True):
            reason = f"LLM veto: {verdict.get('reason', 'low conviction')}"
            return SignalDecision(
                None, decision.conviction, True, reason,
                reports=decision.reports,
                bull_score=decision.bull_score, bear_score=decision.bear_score,
            )
    except Exception as e:  # never block the signal loop on the network
        logger.debug("[event_contract] LLM judge skipped: %s", e)
    return decision
