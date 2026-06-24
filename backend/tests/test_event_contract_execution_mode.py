from services.event_contract import execution


def test_paper_backend_default(monkeypatch):
    monkeypatch.delenv("EVENT_CONTRACT_EXECUTION_MODE", raising=False)
    assert execution.get_execution_backend().mode == "paper"


def test_live_falls_back_without_credentials(monkeypatch):
    monkeypatch.setenv("EVENT_CONTRACT_EXECUTION_MODE", "live")
    monkeypatch.setattr(execution, "_configured_platform", lambda: None)
    b = execution.get_execution_backend()
    assert b.mode == "live" and b.effective_mode == "paper"
