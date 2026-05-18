"""Read-only planning helpers for goal-driven Hyper AI workflows."""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from database.models import SystemConfig

logger = logging.getLogger(__name__)


def _coerce_optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        if match:
            return float(match.group(0))
    return None


def _coerce_goal_days(days: Any, horizon_text: Optional[str] = None) -> Optional[float]:
    if isinstance(days, (int, float)):
        return float(days)

    text_value = str(days or horizon_text or "").strip().lower()
    if not text_value:
        return None

    if "half" in text_value and ("month" in text_value or "mo" in text_value):
        return 15.0
    if "半个月" in text_value or "半月" in text_value:
        return 15.0

    parsed = _coerce_optional_float(text_value)
    if parsed is None:
        return None

    if any(unit in text_value for unit in ("month", "months", "mo", "个月", "月")):
        return parsed * 30.0
    if any(unit in text_value for unit in ("week", "weeks", "wk", "周", "星期")):
        return parsed * 7.0
    if any(unit in text_value for unit in ("year", "years", "yr", "年")):
        return parsed * 365.0
    return parsed


def _classify_goal_risk(start: float, target: float, days: float) -> tuple[Dict[str, Any], str, str]:
    multiple = target / start
    total_return_pct = (multiple - 1.0) * 100.0
    daily_compounded_return_pct = ((multiple ** (1.0 / days)) - 1.0) * 100.0
    metrics = {
        "starting_capital": round(start, 8),
        "target_capital": round(target, 8),
        "time_horizon_days": round(days, 4),
        "target_multiple": round(multiple, 4),
        "total_return_pct": round(total_return_pct, 2),
        "required_daily_compounded_return_pct": round(daily_compounded_return_pct, 2),
    }

    if target <= start:
        return metrics, "low", "capital_preservation_or_drawdown_goal"
    if multiple >= 10 or daily_compounded_return_pct >= 10 or total_return_pct >= 500:
        return metrics, "extreme", "not_reasonable_to_promise"
    if multiple >= 3 or daily_compounded_return_pct >= 5 or total_return_pct >= 200:
        return metrics, "very_high", "speculative"
    if daily_compounded_return_pct >= 2 or total_return_pct >= 50:
        return metrics, "high", "aggressive"
    if daily_compounded_return_pct >= 0.5 or total_return_pct >= 10:
        return metrics, "elevated", "possible_but_uncertain"
    return metrics, "moderate", "within_planning_range"


def _build_required_questions(
    missing_required_fields: List[str],
    environment: str,
    risk_level: str,
    existing_trader_id: Optional[int],
) -> List[str]:
    questions = []
    if "exchange" in missing_required_fields:
        questions.append("Which exchange should be used: Binance or Hyperliquid?")
    if "environment" in missing_required_fields:
        questions.append("Should this be prepared for testnet/paper mode or mainnet real funds?")
    if "max_loss" in missing_required_fields:
        questions.append("What is the maximum USDT loss you accept before the system must stop or reduce risk?")
    if "risk_mode" in missing_required_fields:
        questions.append("Which risk mode should be used: conservative, balanced, or aggressive?")
    if "preferred_symbols" in missing_required_fields:
        questions.append("Which symbols may be traded?")
    if "strategy_type" in missing_required_fields:
        questions.append("Do you want a Prompt strategy, Program strategy, or should Hyper AI recommend one after inspection?")
    if not existing_trader_id:
        questions.append("Should Hyper AI reuse an existing AI Trader or create a new one after LLM credentials are available?")

    if environment == "mainnet" or risk_level in {"high", "very_high", "extreme"}:
        questions.append("Please explicitly confirm you understand this can lose funds and that the target is not guaranteed.")
    return questions


def execute_plan_trading_goal(
    db: Session,
    starting_capital: Any = None,
    target_capital: Any = None,
    time_horizon_days: Any = None,
    time_horizon_text: Optional[str] = None,
    exchange: str = "unknown",
    environment: str = "unknown",
    max_loss: Any = None,
    risk_mode: str = "unknown",
    preferred_symbols: Optional[List[str]] = None,
    strategy_type: str = "unknown",
    existing_trader_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> str:
    """Plan a goal-driven trading automation workflow without changing state."""
    try:
        start = _coerce_optional_float(starting_capital)
        target = _coerce_optional_float(target_capital)
        days = _coerce_goal_days(time_horizon_days, time_horizon_text)
        max_loss_value = _coerce_optional_float(max_loss)
        exchange = (exchange or "unknown").lower()
        environment = (environment or "unknown").lower()
        risk_mode = (risk_mode or "unknown").lower()
        strategy_type = (strategy_type or "unknown").lower()
        symbols = [str(symbol).upper().strip() for symbol in (preferred_symbols or []) if str(symbol).strip()]

        current_environment = None
        try:
            config = db.query(SystemConfig).filter(
                SystemConfig.key == "hyperliquid_trading_mode"
            ).first()
            if config and config.value in {"testnet", "mainnet"}:
                current_environment = config.value
        except Exception:
            current_environment = None

        missing_required_fields = []
        if start is None:
            missing_required_fields.append("starting_capital")
        if target is None:
            missing_required_fields.append("target_capital")
        if days is None:
            missing_required_fields.append("time_horizon_days")
        if exchange not in {"hyperliquid", "binance"}:
            missing_required_fields.append("exchange")
        if environment not in {"testnet", "mainnet"}:
            missing_required_fields.append("environment")
        if max_loss_value is None:
            missing_required_fields.append("max_loss")
        if risk_mode not in {"conservative", "balanced", "aggressive"}:
            missing_required_fields.append("risk_mode")
        if not symbols:
            missing_required_fields.append("preferred_symbols")
        if strategy_type not in {"prompt", "program"}:
            missing_required_fields.append("strategy_type")

        metrics: Dict[str, Any] = {}
        invalid_fields = []
        if start is not None and start <= 0:
            invalid_fields.append("starting_capital must be > 0")
        if target is not None and target <= 0:
            invalid_fields.append("target_capital must be > 0")
        if days is not None and days <= 0:
            invalid_fields.append("time_horizon_days must be > 0")

        risk_level = "unknown"
        feasibility = "needs_more_constraints"
        if not invalid_fields and start and target and days:
            metrics, risk_level, feasibility = _classify_goal_risk(start, target, days)

        result = {
            "ok": True,
            "tool": "plan_trading_goal",
            "metrics": metrics,
            "risk_level": risk_level,
            "feasibility": feasibility,
            "invalid_fields": invalid_fields,
            "missing_required_fields": missing_required_fields,
            "required_user_questions": _build_required_questions(
                missing_required_fields,
                environment,
                risk_level,
                existing_trader_id,
            ),
            "current_system_environment": current_environment,
            "requested_context": {
                "exchange": exchange,
                "environment": environment,
                "risk_mode": risk_mode,
                "strategy_type": strategy_type,
                "preferred_symbols": symbols,
                "existing_trader_id": existing_trader_id,
                "max_loss": max_loss_value,
                "notes": notes,
            },
            "can_prepare_components_after_questions": not invalid_fields,
            "requires_runtime_confirmation_before_binding": True,
            "manual_security_steps": [
                "Wallet/API credential binding",
                "Prompt Trader Start Trading toggle",
                "Program Binding activation switch",
                "Environment switching",
            ],
            "safety_rules": [
                "Never promise the target profit will be reached.",
                "Treat high-return goals as risk-controlled experiments, not guaranteed outcomes.",
                "Use max_loss and position sizing as hard constraints before building strategy logic.",
                "Use mainnet only after explicit confirmation.",
                "The main decision AI must continue to read positions, attribution, backtest data quality, and decision logs.",
            ],
            "recommended_workflow": [
                "1. For broad goals, call coordinate_all_ai so every module/sub-AI receives the same objective.",
                "2. Confirm exchange, environment, allowed symbols, maximum loss, and strategy type.",
                "3. Read system state: wallet status, watchlist, existing traders, existing strategies, and recent logs.",
                "4. Verify market data readiness for selected symbols: klines, market flow, OI/CVD freshness, signal availability, and factor candidates.",
                "5. Ask Signal AI to design trigger conditions instead of guessing thresholds.",
                "6. Ask Prompt AI and/or Program AI to create the strategy logic. If the user requests all AI, run both as drafts.",
                "7. Ask Attribution AI to evaluate existing decision/trade evidence and define monitoring feedback.",
                "8. Save drafts only after the generated signal/prompt/program are complete and internally consistent.",
                "9. Bind strategy to the selected AI Trader only after runtime confirmation, because this changes live automation.",
                "10. Require the user to bind wallet credentials and activate trading controls manually where the security boundary requires it.",
                "11. Monitor the loop through ai_decision_logs, attribution, backtest data quality, wallet/position status, and system logs.",
                "12. Feed outcomes back into the main decision AI context so future decisions see positions, attribution, and backtest/data-quality notes.",
            ],
            "next_tool_sequence": [
                "coordinate_all_ai",
                "get_trading_environment",
                "get_wallet_status",
                "get_watchlist",
                "list_traders",
                "list_signal_pools",
                "list_strategies",
                "get_system_logs",
                "get_klines",
                "get_market_flow",
                "call_signal_ai",
                "call_prompt_ai or call_program_ai",
                "save_signal_pool",
                "save_prompt or save_program",
                "bind_prompt_to_trader or bind_program_to_trader",
                "diagnose_trader_issues",
                "call_attribution_ai",
            ],
        }

        if risk_level == "extreme":
            result["warning"] = (
                "The requested return profile is extreme. Hyper AI may help build a monitored automation workflow, "
                "but must not represent this as achievable or safe."
            )

        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error("[plan_trading_goal] Error: %s", e)
        return json.dumps({"error": str(e)})
