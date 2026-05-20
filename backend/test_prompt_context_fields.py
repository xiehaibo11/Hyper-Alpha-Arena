import json
from types import SimpleNamespace

import pytest

from services import ai_decision_service as decision_service
from services.prompt_validation_service import validate_prompt_template


def _account():
    return SimpleNamespace(
        id=1,
        name="Field Test Trader",
        model="test-model",
        created_at=None,
        initial_cash=10_000,
        current_cash=10_000,
        max_leverage=5,
        default_leverage=2,
    )


def test_prompt_context_exposes_structured_position_fields(monkeypatch):
    monkeypatch.setattr(decision_service, "_get_realtime_ticker_snapshot", lambda *args, **kwargs: {})
    monkeypatch.setattr(decision_service, "_calculate_total_return_percent", lambda account: "+0.00")

    context = decision_service._build_prompt_context(
        _account(),
        portfolio={},
        prices={"BTC": 50_000.0},
        news_section="No news",
        hyperliquid_state={
            "total_equity": 12_000,
            "available_balance": 9_500,
            "used_margin": 500,
            "margin_usage_percent": 4.2,
            "maintenance_margin": 75,
            "positions": [
                {
                    "coin": "BTC",
                    "szi": "0.25",
                    "entry_px": "48000",
                    "unrealized_pnl": "500",
                    "unrealized_pnl_pct": "4.1667",
                    "return_on_equity": "18.5",
                    "peak_pnl_pct": "22.1",
                    "leverage": "5",
                    "max_leverage": "20",
                    "margin_used": "2400",
                    "position_value": "12000",
                    "cum_funding_since_open": "-3.25",
                    "liquidation_px": "39000",
                    "leverage_type": "cross",
                    "opened_at_str": "2026-05-19 00:00 UTC",
                    "holding_duration_str": "2h 30m",
                }
            ],
        },
        symbol_metadata={"BTC": {"name": "Bitcoin", "type": "perp"}},
        symbol_order=["BTC"],
        environment="paper",
        template_text="{positions_structured_json} {open_orders_json} {recent_trades_json}",
    )

    positions = json.loads(context["positions_structured_json"])
    assert len(positions) == 1
    pos = positions[0]
    assert pos["symbol"] == "BTC"
    assert pos["side"] == "long"
    assert pos["entry_price"] == 48000.0
    assert pos["mark_price"] == 50000.0
    assert pos["unrealized_pnl_usd"] == 500.0
    assert pos["unrealized_pnl_pct"] == pytest.approx(4.1667)
    assert pos["peak_pnl_pct"] == 22.1
    assert pos["margin_used_usd"] == 2400.0
    assert pos["liquidation_price"] == 39000.0
    assert pos["holding_duration"] == "2h 30m"

    assert json.loads(context["open_orders_json"]) == []
    assert json.loads(context["recent_trades_json"]) == []
    assert json.loads(context["api_query_snapshot_json"])["note"].startswith("Preview/offline context")
    assert "Margin: $2,400.00" in context["positions_detail"]


def test_prompt_validation_allows_structured_context_fields():
    result = validate_prompt_template(
        "{positions_structured_json}\n"
        "{open_orders_json}\n"
        "{recent_trades_json}\n"
        "{api_query_snapshot_json}\n"
        "{output_format}"
    )

    assert result.is_valid
    assert result.invalid_variables == []


def test_prompt_validation_allows_runtime_output_format_append():
    result = validate_prompt_template("只使用我自己的交易策略提示词。")

    assert result.is_valid
    assert result.errors == []
    assert any("runtime will append" in warning for warning in result.warnings)


def test_prompt_validation_rejects_unknown_fields_and_reserved_tags():
    result = validate_prompt_template(
        "{positions_structured_json}\n"
        "{not_real_field}\n"
        "<reasoning>do not use this</reasoning>\n"
        "{output_format}"
    )

    assert not result.is_valid
    assert "not_real_field" in result.invalid_variables
    assert any("Reserved XML tags" in error for error in result.errors)
