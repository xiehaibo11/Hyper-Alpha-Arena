import pandas as pd
from services.event_contract import simulator, ai_decision
from services.event_contract import config_store as cs


def _of(n=80):
    return pd.DataFrame([{"minute": 1_700_000_000 + i*60, "cvd": i % 5,
                          "buy_ratio": 0.5, "large_imb": 0.0, "volume": 10.0} for i in range(n)])


def test_sim_uses_ai_llm_direction(monkeypatch):
    monkeypatch.setattr(cs, "default_signal", lambda: "ai_llm")
    monkeypatch.setattr(cs, "params_for", lambda s, e: {"window": 45, "thr": 1.5})
    monkeypatch.setattr(cs, "adaptive", lambda: False)
    monkeypatch.setattr(simulator, "load_orderflow", lambda ex, sym, limit=500: _of())
    captured = {}
    def fake_decide(symbol, expiry, exchange):
        captured["called"] = (symbol, expiry, exchange)
        return {"direction": "short", "confidence": 0.6, "reason": "x"}
    monkeypatch.setattr(ai_decision, "decide", fake_decide)
    sig = simulator._last_closed_signal("BTC", 5, "binance")
    assert sig is not None and sig["direction"] == "short"
    assert captured["called"] == ("BTC", 5, "binance")
