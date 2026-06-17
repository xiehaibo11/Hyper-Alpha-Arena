import pandas as pd
from services.event_contract.ai_decision import build_context
from services.event_contract import ai_decision


def _kl(n=60):
    base = 65000.0
    rows = [{"timestamp": 1_700_000_000 + i*60, "open": base+i, "high": base+i+5,
             "low": base+i-5, "close": base+i+1, "volume": 10.0} for i in range(n)]
    return pd.DataFrame(rows)


def _of(n=60):
    rows = [{"minute": 1_700_000_000 + i*60, "cvd": (-1)**i * (i % 7),
             "buy_ratio": 0.5, "large_imb": 0.0, "volume": 10.0} for i in range(n)]
    return pd.DataFrame(rows)


def test_build_context_has_core_fields():
    ctx = build_context("BTC", 5, _kl(), _of())
    assert ctx["symbol"] == "BTC"
    assert ctx["expiry_minutes"] == 5
    assert "price" in ctx and ctx["price"] > 0
    assert "cvd_z" in ctx
    assert "recent_closes" in ctx and len(ctx["recent_closes"]) <= 30
    assert isinstance(ctx.get("traps"), list)


def test_build_context_handles_empty():
    ctx = build_context("ETH", 10, pd.DataFrame(), pd.DataFrame())
    assert ctx["available"] is False


def test_decide_parses_long(monkeypatch):
    monkeypatch.setattr(ai_decision, "_load_data", lambda ex, sym: (_kl(), _of()))
    monkeypatch.setattr(ai_decision, "_call_llm", lambda ctx: {"direction": "long", "confidence": 0.7, "reason": "uptrend"})
    monkeypatch.setenv("EVENT_CONTRACT_LLM_API_KEY", "test")
    out = ai_decision.decide("BTC", 5, "binance")
    assert out["direction"] == "long" and out["confidence"] == 0.7


def test_decide_none_on_llm_failure(monkeypatch):
    monkeypatch.setattr(ai_decision, "_load_data", lambda ex, sym: (_kl(), _of()))
    def boom(ctx): raise RuntimeError("network")
    monkeypatch.setattr(ai_decision, "_call_llm", boom)
    monkeypatch.setenv("EVENT_CONTRACT_LLM_API_KEY", "test")
    out = ai_decision.decide("BTC", 5, "binance")
    assert out["direction"] is None


def test_decide_none_when_no_data(monkeypatch):
    monkeypatch.setattr(ai_decision, "_load_data", lambda ex, sym: (pd.DataFrame(), pd.DataFrame()))
    monkeypatch.setenv("EVENT_CONTRACT_LLM_API_KEY", "test")
    out = ai_decision.decide("BTC", 5, "binance")
    assert out["direction"] is None


def test_decide_rejects_bad_direction(monkeypatch):
    monkeypatch.setattr(ai_decision, "_load_data", lambda ex, sym: (_kl(), _of()))
    monkeypatch.setattr(ai_decision, "_call_llm", lambda ctx: {"direction": "sideways"})
    monkeypatch.setenv("EVENT_CONTRACT_LLM_API_KEY", "test")
    out = ai_decision.decide("BTC", 5, "binance")
    assert out["direction"] is None
