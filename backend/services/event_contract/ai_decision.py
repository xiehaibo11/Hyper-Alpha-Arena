"""AI (LLM) event-contract decision brain.

For a free cell (symbol, expiry) it assembles a compact market context, asks an
OpenAI-compatible LLM whether price will be higher/lower after `expiry` minutes,
and returns 'long' | 'short' | None. Every failure path returns None so the
per-minute live loop is never blocked. Mirrors agents/llm_judge.py's call style.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def build_context(symbol: str, expiry: int, kl: pd.DataFrame, feat: pd.DataFrame) -> dict:
    """Compact, JSON-serialisable context for the LLM. Never raises."""
    if kl is None or kl.empty or feat is None or feat.empty:
        return {"symbol": symbol, "expiry_minutes": expiry, "available": False}
    try:
        closes = [round(float(c), 2) for c in kl["close"].tail(30).tolist()]
        price = float(kl["close"].iloc[-1])
        cvd = feat["cvd"]
        n = min(45, len(cvd) - 1)
        mean = cvd.rolling(n).mean().iloc[-1] if n > 1 else 0.0
        std = cvd.rolling(n).std().iloc[-1] if n > 1 else np.nan
        cvd_z = float((cvd.iloc[-1] - mean) / std) if std and not pd.isna(std) else 0.0
        buy_ratio = float(feat["buy_ratio"].iloc[-1]) if not pd.isna(feat["buy_ratio"].iloc[-1]) else 0.5
        traps: list = []
        try:
            from .agents.analysis import analyze
            rep = analyze(kl)
            d = rep.as_dict()
            traps = [t.get("name") for t in d.get("traps", [])]
            bias = d.get("bias")
        except Exception:
            bias = None
        return {
            "symbol": symbol, "expiry_minutes": expiry, "available": True,
            "price": price, "recent_closes": closes,
            "cvd_z": round(cvd_z, 3), "buy_ratio": round(buy_ratio, 3),
            "bias": bias, "traps": traps,
        }
    except Exception as e:  # context must never crash the loop
        logger.debug("[event_contract] build_context failed: %s", e)
        return {"symbol": symbol, "expiry_minutes": expiry, "available": False}


_SYSTEM = (
    "You trade a binary up/down event contract. At the current price you open a "
    "position; it settles after `expiry_minutes`. If price is ABOVE entry you win "
    "a 'long', if BELOW you win a 'short'. Given the context, answer strict JSON "
    '{"direction":"long"|"short"|"none","confidence":0..1,"reason":"..."}. Prefer '
    "trend continuation; if a high-severity trap is present, prefer none. Answer "
    "none when the edge is unclear."
)


def _load_data(exchange: str, symbol: str):
    """Load recent 1m klines + order-flow features. Separated for test stubbing."""
    from .data import load_klines
    from .orderflow import load_orderflow
    return load_klines(exchange, symbol, limit=120), load_orderflow(exchange, symbol, limit=500)


def _call_llm(ctx: dict) -> dict:
    """OpenAI-compatible chat call. Mirrors agents/llm_judge.py. Raises on failure."""
    import requests
    base = os.getenv("EVENT_CONTRACT_LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("EVENT_CONTRACT_LLM_MODEL", "gpt-4o-mini")
    payload = {
        "model": model, "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(ctx)},
        ],
    }
    resp = requests.post(
        f"{base.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {os.getenv('EVENT_CONTRACT_LLM_API_KEY', '')}"},
        json=payload, timeout=8,
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])


def decide(symbol: str, expiry: int, exchange: str) -> dict:
    """Return {'direction': 'long'|'short'|None, 'confidence': float, 'reason': str}."""
    fail = {"direction": None, "confidence": 0.0, "reason": ""}
    if not os.getenv("EVENT_CONTRACT_LLM_API_KEY"):
        return fail  # not configured -> no AI trade this tick
    try:
        kl, feat = _load_data(exchange, symbol)
        ctx = build_context(symbol, expiry, kl, feat)
        if not ctx.get("available"):
            return fail
        verdict = _call_llm(ctx)
        direction = verdict.get("direction")
        if direction not in ("long", "short"):
            return fail
        return {
            "direction": direction,
            "confidence": float(verdict.get("confidence", 0.0) or 0.0),
            "reason": str(verdict.get("reason", ""))[:200],
        }
    except Exception as e:
        logger.debug("[event_contract] ai_decision.decide failed: %s", e)
        return fail
