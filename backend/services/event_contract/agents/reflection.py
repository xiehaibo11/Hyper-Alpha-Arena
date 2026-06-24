"""Reflection — the lesson half of the borrowed TradingAgents loop.

TradingAgents' Reflector turns a known outcome into a short prose lesson that is
re-injected into future decisions. Here reflection is mostly *deterministic*: it
reads the SignalMemory and states, in plain terms, which side is working and
whether a cooldown is warranted — cheap, always-on, and shown in the UI/logs.

An optional LLM reflection mirrors the original Reflector for richer prose; it is
off by default (no per-cycle token cost) and fully defensive.
"""
from __future__ import annotations

import json
import logging
import os

from .memory import SignalMemory

logger = logging.getLogger(__name__)


def summarize(memory: SignalMemory) -> str:
    """Deterministic lesson from accumulated outcomes (no LLM)."""
    be = memory.breakeven()
    bits: list[str] = []
    for d in ("long", "short"):
        wr = memory.directional_winrate(d)
        n = memory._dir[d].total
        if wr is None:
            bits.append(f"{d}: no settled samples")
        else:
            verdict = "above" if wr >= be else "below"
            bits.append(f"{d}: {wr:.0%} over {n} ({verdict} breakeven {be:.0%})")
    rw = memory.recent_winrate()
    if rw is not None:
        bits.append(f"recent: {rw:.0%}" + ("  [COOLDOWN]" if rw < be else ""))
    return " | ".join(bits)


def reflect_llm(memory: SignalMemory, last_decision_summary: str, params: dict) -> str | None:
    """Optional LLM prose lesson. Returns None unless enabled and successful.

    Enable with params['use_llm'] and env EVENT_CONTRACT_LLM_API_KEY (see
    llm_judge.py for the same env contract). Never raises.
    """
    if not params.get("use_llm") or not os.getenv("EVENT_CONTRACT_LLM_API_KEY"):
        return None
    try:
        import requests

        base = os.getenv("EVENT_CONTRACT_LLM_BASE_URL", "https://api.openai.com/v1")
        model = os.getenv("EVENT_CONTRACT_LLM_MODEL", "gpt-4o-mini")
        payload = {
            "model": model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": (
                    "You review a binary up/down signal's recent track record and "
                    "write exactly 1-2 sentences of plain prose: what is working, "
                    "what to avoid next. Be terse; this is re-read by the engine.")},
                {"role": "user", "content": json.dumps({
                    "stats": summarize(memory),
                    "last_decision": last_decision_summary,
                })},
            ],
        }
        resp = requests.post(
            f"{base.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('EVENT_CONTRACT_LLM_API_KEY')}"},
            json=payload, timeout=params.get("llm_timeout", 8),
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.debug("[event_contract] LLM reflection skipped: %s", e)
        return None
