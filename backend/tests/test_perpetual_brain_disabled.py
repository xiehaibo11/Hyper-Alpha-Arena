from services.ai_decision_service import perpetual_brain_enabled


def test_perpetual_disabled_by_default(monkeypatch):
    monkeypatch.delenv("PERPETUAL_BRAIN_ENABLED", raising=False)
    assert perpetual_brain_enabled() is False


def test_perpetual_can_reenable(monkeypatch):
    monkeypatch.setenv("PERPETUAL_BRAIN_ENABLED", "true")
    assert perpetual_brain_enabled() is True
