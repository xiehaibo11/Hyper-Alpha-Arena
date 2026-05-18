"""All-agent coordination workflow for Hyper AI.

This module gives the main Hyper AI a single tool for broad user goals. It
collects system state, starts Dashboard context recompute, and asks the core
specialist AIs to work from one shared objective.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Generator, Iterable, List, Optional

from sqlalchemy.orm import Session

from services.ai_stream_service import format_sse_event

logger = logging.getLogger(__name__)


ALL_AI_COORDINATION_TOOL = {
    "type": "function",
    "function": {
        "name": "coordinate_all_ai",
        "description": (
            "Coordinate all Hyper Alpha Arena AI modules for a broad user command or capital goal. "
            "Use this when the user asks Hyper AI to make every sub-AI work together, create an "
            "automatic plan, calculate a goal such as 178 USDT to 5000 USDT, or coordinate across "
            "AI Traders, Prompt Strategy, Program Trading, Signal System, Attribution, Factor "
            "Library, Manual Trading, and K-Line Charts. This tool performs analysis and drafts; "
            "state-changing saves/bindings still use their normal tools and confirmations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "objective": {
                    "type": "string",
                    "description": "User's full objective or command."
                },
                "starting_capital": {
                    "type": "number",
                    "description": "Starting capital in USDT/USD if provided."
                },
                "target_capital": {
                    "type": "number",
                    "description": "Target capital in USDT/USD if provided."
                },
                "time_horizon_days": {
                    "type": "number",
                    "description": "Goal horizon in days if known."
                },
                "time_horizon_text": {
                    "type": "string",
                    "description": "Raw horizon text when ambiguous, e.g. half month."
                },
                "exchange": {
                    "type": "string",
                    "enum": ["binance", "hyperliquid", "okx", "unknown"],
                    "description": "Requested exchange. Default unknown."
                },
                "environment": {
                    "type": "string",
                    "enum": ["testnet", "mainnet", "unknown"],
                    "description": "Requested environment. Default unknown."
                },
                "max_loss": {
                    "type": "number",
                    "description": "Maximum accepted loss if provided."
                },
                "risk_mode": {
                    "type": "string",
                    "enum": ["conservative", "balanced", "aggressive", "unknown"],
                    "description": "Risk preference. Default unknown."
                },
                "preferred_symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Symbols the workflow should cover."
                },
                "strategy_type": {
                    "type": "string",
                    "enum": ["prompt", "program", "both", "unknown"],
                    "description": "Preferred strategy type. Use both/unknown when all AIs should calculate."
                },
                "account_id": {
                    "type": "integer",
                    "description": "Optional AI Trader account id to focus on."
                },
                "timeframe": {
                    "type": "string",
                    "description": "Analysis timeframe. Default 15m."
                },
                "run_specialists": {
                    "type": "boolean",
                    "description": "Whether to call Prompt/Program/Signal/Attribution AI. Default true.",
                    "default": True
                }
            },
            "required": ["objective"]
        },
    },
}


def _json_loads(raw: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"content": raw}
    except Exception:
        return {"content": raw}


def _compact(value: Any, limit: int = 1600) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "...[truncated]"
    if isinstance(value, list):
        return [_compact(item, limit=limit) for item in value[:20]]
    if isinstance(value, dict):
        return {key: _compact(item, limit=limit) for key, item in value.items()}
    return value


def _safe_tool_json(label: str, fn) -> Dict[str, Any]:
    try:
        return _json_loads(fn())
    except Exception as exc:
        logger.warning("[coordinate_all_ai] %s failed: %s", label, exc, exc_info=True)
        return {"error": str(exc), "_label": label}


def _symbols_from_args(args: Dict[str, Any], watchlist_payload: Dict[str, Any], exchange: str) -> List[str]:
    raw_symbols = args.get("preferred_symbols") or []
    symbols = [str(symbol).upper().strip() for symbol in raw_symbols if str(symbol).strip()]
    if symbols:
        return symbols

    try:
        selected = watchlist_payload.get(exchange, {}).get("selected")
        if isinstance(selected, list):
            return [str(symbol).upper() for symbol in selected if str(symbol).strip()]
    except Exception:
        pass
    return ["BTC", "ETH", "SOL", "BNB"]


def _shared_brief(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    goal = context.get("goal_plan", {})
    symbols = context.get("symbols", [])
    return (
        f"Objective: {args.get('objective')}\n"
        f"Exchange: {context.get('exchange')}; Environment: {context.get('environment')}; "
        f"Symbols: {', '.join(symbols)}; Timeframe: {context.get('timeframe')}\n"
        f"Goal metrics: {json.dumps(goal.get('metrics', {}), ensure_ascii=False)}\n"
        f"Risk level: {goal.get('risk_level')} / feasibility: {goal.get('feasibility')}\n"
        f"Missing constraints: {goal.get('missing_required_fields', [])}\n"
        "All outputs are advisory drafts. Do not place trades, bind strategies, or claim profit is guaranteed."
    )


def _build_specialist_tasks(args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, str]:
    brief = _shared_brief(args, context)
    symbols = ", ".join(context.get("symbols", []))
    return {
        "call_signal_ai": (
            f"{brief}\n\n"
            "Signal AI task: design candidate signal pools and trigger conditions for the selected symbols. "
            "Use market-flow, K-line, and factor-aware triggers. Include thresholds, time windows, exchange, "
            "risk notes, and what should be backtested before activation."
        ),
        "call_prompt_ai": (
            f"{brief}\n\n"
            "Prompt AI task: draft a main decision prompt for the AI Trader. It must use all Dashboard AI "
            "contexts, open positions, attribution feedback, signal triggers, K-line indicators, and hard risk "
            "limits. Include explicit hold/zero-position consistency rules."
        ),
        "call_program_ai": (
            f"{brief}\n\n"
            "Program AI task: draft deterministic Python strategy logic for the selected symbols. It should "
            "read market data through the supported Program APIs, enforce max loss/risk caps, and return only "
            "valid buy/sell/hold/close decisions. Include test/backtest requirements."
        ),
        "call_attribution_ai": (
            f"{brief}\n\n"
            "Attribution AI task: review existing decisions, completed outcomes, and risk behavior for this "
            f"exchange/symbol set ({symbols}). Identify what historical evidence is missing before trusting "
            "automation and what monitoring feedback should be fed back to the main decision AI."
        ),
    }


def _run_one_specialist(
    db: Session,
    tool_name: str,
    task: str,
    user_id: int,
) -> Generator[str, None, Dict[str, Any]]:
    from services.hyper_ai_subagents import execute_subagent_tool

    yield format_sse_event("subagent_progress", {
        "subagent": "All AI Coordinator",
        "step": "tool_call",
        "tool": tool_name,
    })
    result_text = yield from execute_subagent_tool(db, tool_name, {"task": task}, user_id=user_id)
    result = _json_loads(result_text)
    yield format_sse_event("subagent_progress", {
        "subagent": "All AI Coordinator",
        "step": "tool_result",
        "tool": tool_name,
    })
    return result


def execute_coordinate_all_ai(
    db: Session,
    arguments: Dict[str, Any],
    user_id: int = 1,
) -> Generator[str, None, str]:
    """Coordinate all advisory modules and specialist sub-agents."""
    try:
        from services.hyper_ai_goal_planner import execute_plan_trading_goal
        from services.hyper_ai_listing_tools import (
            execute_list_signal_pools,
            execute_list_strategies,
            execute_list_traders,
        )
        from services.hyper_ai_status_tools import (
            execute_get_system_logs,
            execute_get_system_overview,
            execute_get_trading_environment,
            execute_get_wallet_status,
            execute_get_watchlist,
        )

        args = dict(arguments or {})
        exchange = str(args.get("exchange") or "unknown").lower()
        if exchange not in {"binance", "hyperliquid", "okx"}:
            exchange = "binance"
        environment = str(args.get("environment") or "unknown").lower()
        timeframe = str(args.get("timeframe") or "15m")

        yield format_sse_event("subagent_progress", {
            "subagent": "All AI Coordinator",
            "step": "reasoning",
            "content": "Planning the goal and collecting shared system state.",
        })

        goal_plan = _json_loads(execute_plan_trading_goal(
            db,
            starting_capital=args.get("starting_capital"),
            target_capital=args.get("target_capital"),
            time_horizon_days=args.get("time_horizon_days"),
            time_horizon_text=args.get("time_horizon_text"),
            exchange=exchange,
            environment=environment,
            max_loss=args.get("max_loss"),
            risk_mode=args.get("risk_mode", "unknown"),
            preferred_symbols=args.get("preferred_symbols"),
            strategy_type="unknown" if args.get("strategy_type") == "both" else args.get("strategy_type", "unknown"),
            existing_trader_id=args.get("account_id"),
            notes=args.get("objective"),
        ))
        watchlist = _safe_tool_json("get_watchlist", lambda: execute_get_watchlist(db))
        symbols = _symbols_from_args(args, watchlist, exchange)

        context: Dict[str, Any] = {
            "objective": args.get("objective"),
            "exchange": exchange,
            "environment": environment,
            "symbols": symbols,
            "timeframe": timeframe,
            "goal_plan": goal_plan,
            "system_overview": _safe_tool_json("get_system_overview", lambda: execute_get_system_overview(db)),
            "trading_environment": _safe_tool_json("get_trading_environment", lambda: execute_get_trading_environment(db)),
            "wallet_status": _safe_tool_json("get_wallet_status", lambda: execute_get_wallet_status(db, exchange=exchange, environment="all")),
            "watchlist": watchlist,
            "traders": _safe_tool_json("list_traders", lambda: execute_list_traders(db, trader_id=args.get("account_id"))),
            "signal_pools": _safe_tool_json("list_signal_pools", lambda: execute_list_signal_pools(db)),
            "strategies": _safe_tool_json("list_strategies", lambda: execute_list_strategies(db)),
            "system_logs": _safe_tool_json("get_system_logs", lambda: execute_get_system_logs(db, level="warning", limit=20, trader_id=args.get("account_id"))),
        }

        try:
            from services.arena_ai_context_service import get_context_payload

            context["arena_context"] = get_context_payload(
                db,
                account_id=args.get("account_id"),
                exchange=exchange,
                symbols=symbols,
                timeframe=timeframe,
                recompute=True,
            )
        except Exception as exc:
            context["arena_context"] = {"error": str(exc)}

        try:
            from services.hyper_ai_factor_tools import execute_get_factor_functions, execute_query_factors

            context["factor_library"] = _json_loads(execute_get_factor_functions(category=None))
            context["factor_candidates"] = _json_loads(execute_query_factors(
                db,
                exchange=exchange,
                symbol=symbols[0] if symbols else None,
                days=30,
            ))
        except Exception as exc:
            context["factor_library"] = {"error": str(exc)}

        specialist_results: Dict[str, Any] = {}
        if args.get("run_specialists", True):
            yield format_sse_event("subagent_progress", {
                "subagent": "All AI Coordinator",
                "step": "reasoning",
                "content": "Dispatching Signal, Prompt, Program, and Attribution AI with a shared brief.",
            })
            for tool_name, task in _build_specialist_tasks(args, context).items():
                specialist_results[tool_name] = yield from _run_one_specialist(db, tool_name, task, user_id)

        modules = {
            "ai_trader_management": "list_traders + trader_management_ai context",
            "prompt_strategy": "call_prompt_ai",
            "program_trading": "call_program_ai",
            "signal_system": "call_signal_ai + signal pool inventory",
            "attribution_analysis": "call_attribution_ai + attribution context",
            "factor_library": "factor function library + factor candidates",
            "manual_trading": "wallet/position status only; no automatic manual order placement",
            "kline_charts": "arena kline_ai context recompute + K-line advisory context",
        }

        content = (
            "All-agent coordination completed. The main Hyper AI should now synthesize these module outputs into "
            "one user-facing plan, ask only for missing risk/security confirmations, and use normal save/bind tools "
            "if the user confirms deployment."
        )
        return json.dumps({
            "status": "success",
            "subagent": "all_ai_coordinator",
            "content": content,
            "objective": args.get("objective"),
            "modules_engaged": modules,
            "shared_context": _compact(context),
            "specialist_results": _compact(specialist_results, limit=3200),
            "next_actions": [
                "Summarize feasibility and risk without promising profit.",
                "If constraints are missing, ask only those concrete questions.",
                "If user confirms, save candidate signal/prompt/program drafts with normal tools.",
                "Use high-risk confirmation before binding or activating live automation.",
                "Continue monitoring via arena context, attribution, decision logs, and wallet status.",
            ],
        }, ensure_ascii=False)
    except Exception as exc:
        logger.error("[coordinate_all_ai] Error: %s", exc, exc_info=True)
        return json.dumps({
            "status": "failed",
            "subagent": "all_ai_coordinator",
            "content": f"All-agent coordination failed: {exc}",
            "error": str(exc),
        }, ensure_ascii=False)
