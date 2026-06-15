from services.event_contract.config_store import merge_config, params_for_cfg


def test_merge_returns_defaults_when_no_overrides():
    cfg = merge_config(None)
    assert cfg["symbols"] == ["BTC", "ETH"]
    assert cfg["expiries"] == [5, 10]
    assert cfg["payout"] == 0.8
    assert cfg["default_signal"] == "of_cvd_fade"
    assert cfg["signal_params"]["BTC:5"] == {"window": 45, "thr": 1.5}


def test_merge_overrides_scalar_and_params():
    cfg = merge_config({"payout": 0.9, "signal_params": {"BTC:5": {"window": 60, "thr": 2.0}}})
    assert cfg["payout"] == 0.9
    assert cfg["signal_params"]["BTC:5"] == {"window": 60, "thr": 2.0}
    # untouched cells keep defaults
    assert cfg["signal_params"]["ETH:10"] == {"window": 20, "thr": 2.5}


def test_merge_ignores_none_values():
    cfg = merge_config({"payout": None})
    assert cfg["payout"] == 0.8


def test_params_for_cfg_falls_back():
    cfg = merge_config(None)
    assert params_for_cfg(cfg, "SOL", 5) == {"window": 30, "thr": 1.5}
