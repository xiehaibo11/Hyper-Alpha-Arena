"""Safe project health inspection and repair tools for Hyper AI.

These tools give Hyper AI a Claude-like troubleshooting loop without exposing
arbitrary shell or file-write access inside the live trading server.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _status_result(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default)


def _proc_snapshot() -> Dict[str, Any]:
    result: Dict[str, Any] = {"pid": os.getpid()}
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith(("State:", "Threads:", "VmRSS:", "VmSize:")):
                    key, value = line.split(":", 1)
                    result[key.lower()] = value.strip()
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _safe_call(label: str, fn) -> Dict[str, Any]:
    try:
        return {"ok": True, "value": fn()}
    except Exception as exc:
        return {"ok": False, "error": f"{label}: {exc}"}


def _load_watchlists() -> Dict[str, Any]:
    def _binance():
        from services.binance_symbol_service import get_selected_symbols

        return get_selected_symbols()

    def _hyperliquid():
        from services.hyperliquid_symbol_service import get_selected_symbols

        return get_selected_symbols()

    return {
        "binance": _safe_call("binance_watchlist", _binance),
        "hyperliquid": _safe_call("hyperliquid_watchlist", _hyperliquid),
    }


def _collector_state() -> Dict[str, Any]:
    state: Dict[str, Any] = {}

    try:
        from services.exchanges.binance_collector import binance_collector

        scheduler = getattr(binance_collector, "scheduler", None)
        state["binance_rest"] = {
            "running": bool(getattr(binance_collector, "running", False)),
            "symbols": list(getattr(binance_collector, "symbols", []) or []),
            "scheduler_running": bool(getattr(scheduler, "running", False)) if scheduler else False,
        }
    except Exception as exc:
        state["binance_rest"] = {"error": str(exc)}

    try:
        from services.exchanges.binance_ws_collector import binance_ws_collector

        thread = getattr(binance_ws_collector, "ws_thread", None)
        state["binance_trade_ws"] = {
            "running": bool(getattr(binance_ws_collector, "running", False)),
            "symbols": list(getattr(binance_ws_collector, "symbols", []) or []),
            "thread_alive": bool(thread and thread.is_alive()),
            "buffer_symbols": sorted(list(getattr(binance_ws_collector, "trade_buffers", {}) or {})),
        }
    except Exception as exc:
        state["binance_trade_ws"] = {"error": str(exc)}

    try:
        from services.exchanges.binance_kline_ws_collector import binance_kline_ws_collector

        with binance_kline_ws_collector._buffer_lock:
            closed_count = len(getattr(binance_kline_ws_collector, "_closed_klines", []) or [])
            open_count = len(getattr(binance_kline_ws_collector, "_open_klines", {}) or {})
        ws_threads = list(getattr(binance_kline_ws_collector, "ws_threads", []) or [])
        flush_thread = getattr(binance_kline_ws_collector, "flush_thread", None)
        state["binance_kline_ws"] = {
            "running": bool(getattr(binance_kline_ws_collector, "running", False)),
            "symbols": list(getattr(binance_kline_ws_collector, "symbols", []) or []),
            "active_symbols": sorted(list(getattr(binance_kline_ws_collector, "_active_symbol_set", set()) or set())),
            "intervals": list(getattr(binance_kline_ws_collector, "intervals", []) or []),
            "generation": getattr(binance_kline_ws_collector, "_generation", None),
            "ws_threads": len(ws_threads),
            "ws_threads_alive": sum(1 for thread in ws_threads if thread.is_alive()),
            "flush_thread_alive": bool(flush_thread and flush_thread.is_alive()),
            "closed_buffer_size": closed_count,
            "open_buffer_size": open_count,
        }
    except Exception as exc:
        state["binance_kline_ws"] = {"error": str(exc)}

    return state


def _watchlist_value(watchlists: Dict[str, Any], exchange: str) -> List[str]:
    item = watchlists.get(exchange) or {}
    if item.get("ok") and isinstance(item.get("value"), list):
        return [str(symbol).upper() for symbol in item["value"]]
    return []


def _compare_binance_symbols(watchlists: Dict[str, Any], collectors: Dict[str, Any]) -> Dict[str, Any]:
    watchlist = set(_watchlist_value(watchlists, "binance"))
    comparisons: Dict[str, Any] = {}
    for name in ("binance_rest", "binance_trade_ws", "binance_kline_ws"):
        symbols = collectors.get(name, {}).get("active_symbols")
        if symbols is None:
            symbols = collectors.get(name, {}).get("symbols", [])
        active = {str(symbol).upper() for symbol in symbols or []}
        comparisons[name] = {
            "matches_watchlist": active == watchlist,
            "missing": sorted(watchlist - active),
            "extra": sorted(active - watchlist),
            "active_count": len(active),
            "watchlist_count": len(watchlist),
        }
    return comparisons


def _recent_logs(limit: int) -> List[Dict[str, Any]]:
    try:
        from services.system_logger import system_logger

        return system_logger.get_logs(limit=limit, min_level="WARNING")
    except Exception as exc:
        return [{"level": "ERROR", "message": f"Unable to read system logs: {exc}"}]


def _classify_log_issues(logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    patterns = [
        (
            "binance_kline_ws_pressure",
            ("binance kline ws", "duplicate key", "uniqueviolation", "websocket closed"),
            "Binance Kline WebSocket may be overloaded, stale, or writing duplicate candles.",
            "restart_binance_kline_ws",
        ),
        (
            "ai_zero_quantity",
            ("quantity=0", "quantity 0", "non-positive", "target_portion_of_balance=0"),
            "AI decision output or sizing produced a zero-quantity order path.",
            "inspect_only",
        ),
        (
            "ai_tool_infra",
            ("timeout", "gateway timeout", "http 504", "service unavailable", "upstream"),
            "A tool or upstream API is timing out.",
            "inspect_only",
        ),
    ]
    findings: Dict[str, Dict[str, Any]] = {}
    for log in logs:
        message = str(log.get("message") or "").lower()
        for code, needles, summary, action in patterns:
            if any(needle in message for needle in needles):
                item = findings.setdefault(
                    code,
                    {"code": code, "summary": summary, "count": 0, "suggested_action": action, "examples": []},
                )
                item["count"] += 1
                if len(item["examples"]) < 3:
                    item["examples"].append(log.get("message"))
    return list(findings.values())


def _recent_execution_issues(db: Session) -> Dict[str, Any]:
    issues: Dict[str, Any] = {}
    since = datetime.utcnow() - timedelta(hours=24)
    try:
        from database.models import AIDecisionLog

        contradictory = db.query(AIDecisionLog).filter(
            AIDecisionLog.decision_time >= since,
            AIDecisionLog.operation.in_(["buy", "sell", "close"]),
            AIDecisionLog.target_portion <= 0,
        ).order_by(AIDecisionLog.decision_time.desc()).limit(10).all()
        issues["ai_zero_target_decisions_24h"] = [
            {
                "id": row.id,
                "time": row.decision_time,
                "account_id": row.account_id,
                "operation": row.operation,
                "symbol": row.symbol,
                "target_portion": row.target_portion,
                "executed": row.executed,
                "reason": (row.reason or "")[:240],
            }
            for row in contradictory
        ]
    except Exception as exc:
        issues["ai_zero_target_decisions_24h_error"] = str(exc)

    try:
        from database.models import ProgramExecutionLog

        failed = db.query(ProgramExecutionLog).filter(
            ProgramExecutionLog.success == False,  # noqa: E712
        ).order_by(ProgramExecutionLog.created_at.desc()).limit(10).all()
        issues["recent_program_errors"] = [
            {
                "id": row.id,
                "account_id": row.account_id,
                "program_id": row.program_id,
                "symbol": row.decision_symbol or row.trigger_symbol,
                "error": (row.error_message or "")[:240],
            }
            for row in failed
        ]
    except Exception as exc:
        issues["recent_program_errors_error"] = str(exc)

    return issues


def _suggest_actions(
    comparisons: Dict[str, Any],
    log_issues: List[Dict[str, Any]],
    execution_issues: Dict[str, Any],
) -> List[Dict[str, Any]]:
    suggestions: List[Dict[str, Any]] = []

    if any(not item.get("matches_watchlist") for item in comparisons.values()):
        suggestions.append({
            "action": "refresh_binance_collectors",
            "risk": "low_write",
            "why": "At least one Binance collector symbol set differs from the Binance watchlist.",
            "does": "Refreshes Binance REST, trade WebSocket, and K-line WebSocket collectors to the current watchlist.",
        })

    if any(item.get("code") == "binance_kline_ws_pressure" for item in log_issues):
        suggestions.append({
            "action": "restart_binance_kline_ws",
            "risk": "low_write",
            "why": "Recent logs indicate Binance K-line WebSocket pressure or duplicate writes.",
            "does": "Restarts only the Binance K-line WebSocket collector using the current Binance watchlist.",
        })

    if execution_issues.get("ai_zero_target_decisions_24h"):
        suggestions.append({
            "action": "inspect_only",
            "risk": "readonly",
            "why": "Recent historical AI decisions contain non-hold operations with target_portion <= 0.",
            "does": "No runtime repair needed if the current guard code is deployed; monitor new decisions.",
        })

    if not suggestions:
        suggestions.append({
            "action": "none",
            "risk": "readonly",
            "why": "No safe automatic repair action is currently indicated.",
            "does": "Keep monitoring logs and collectors.",
        })
    return suggestions


def execute_inspect_project_health(
    db: Session,
    scope: str = "all",
    include_logs: bool = True,
    log_limit: int = 30,
) -> str:
    """Inspect live project health and return safe repair recommendations."""
    log_limit = min(max(int(log_limit or 30), 1), 80)
    watchlists = _load_watchlists()
    collectors = _collector_state()
    comparisons = _compare_binance_symbols(watchlists, collectors)
    logs = _recent_logs(log_limit) if include_logs else []
    log_issues = _classify_log_issues(logs)
    execution_issues = _recent_execution_issues(db)

    return _status_result({
        "status": "ok",
        "scope": scope,
        "generated_at": datetime.utcnow(),
        "runtime": _proc_snapshot(),
        "watchlists": watchlists,
        "collectors": collectors,
        "binance_watchlist_comparison": comparisons,
        "recent_log_issues": log_issues,
        "recent_execution_issues": execution_issues,
        "suggested_repair_actions": _suggest_actions(comparisons, log_issues, execution_issues),
        "safety_boundary": {
            "can_do": [
                "inspect logs and runtime collector state",
                "refresh/restart Binance data collectors against the current watchlist",
                "report AI decision guard status",
                "use Operator Mode tools for non-secret file edits and verification commands when code repair is needed",
            ],
            "will_not_do": [
                "run destructive shell commands",
                "read or expose secrets",
                "change wallet credentials",
                "place trades",
                "switch testnet/mainnet",
            ],
        },
    })


def _refresh_binance_rest(watchlist: List[str], dry_run: bool) -> Dict[str, Any]:
    from services.exchanges.binance_collector import binance_collector

    before = list(getattr(binance_collector, "symbols", []) or [])
    if not dry_run:
        if getattr(binance_collector, "running", False):
            binance_collector.refresh_symbols(watchlist)
        else:
            binance_collector.start(watchlist)
    return {"collector": "binance_rest", "before": before, "after": watchlist, "executed": not dry_run}


def _refresh_binance_trade_ws(watchlist: List[str], dry_run: bool) -> Dict[str, Any]:
    from services.exchanges.binance_ws_collector import binance_ws_collector

    before = list(getattr(binance_ws_collector, "symbols", []) or [])
    if not dry_run:
        if getattr(binance_ws_collector, "running", False):
            binance_ws_collector.refresh_symbols(watchlist)
        else:
            binance_ws_collector.start(watchlist)
    return {"collector": "binance_trade_ws", "before": before, "after": watchlist, "executed": not dry_run}


def _refresh_binance_kline_ws(watchlist: List[str], dry_run: bool) -> Dict[str, Any]:
    from services.exchanges.binance_kline_ws_collector import binance_kline_ws_collector

    before = list(getattr(binance_kline_ws_collector, "symbols", []) or [])
    if not dry_run:
        if getattr(binance_kline_ws_collector, "running", False):
            binance_kline_ws_collector.refresh_symbols(watchlist)
        else:
            binance_kline_ws_collector.start(watchlist)
    return {"collector": "binance_kline_ws", "before": before, "after": watchlist, "executed": not dry_run}


def execute_run_safe_project_repair(
    db: Session,
    action: str,
    dry_run: bool = False,
    reason: Optional[str] = None,
) -> str:
    """Run a whitelisted low-risk runtime repair action."""
    from services.binance_symbol_service import get_selected_symbols as get_binance_selected_symbols

    action = str(action or "auto").strip().lower()
    allowed = {
        "auto",
        "refresh_binance_collectors",
        "restart_binance_kline_ws",
        "restart_binance_trade_ws",
    }
    if action not in allowed:
        return _status_result({
            "status": "blocked",
            "executed": False,
            "error": f"Unsupported repair action: {action}",
            "allowed_actions": sorted(allowed),
        })

    before = json.loads(execute_inspect_project_health(db, scope="repair_precheck", include_logs=True, log_limit=30))
    watchlist = [str(symbol).upper() for symbol in (get_binance_selected_symbols() or ["BTC"])]
    steps: List[Dict[str, Any]] = []

    if action in {"auto", "refresh_binance_collectors"}:
        steps.append(_refresh_binance_rest(watchlist, dry_run))
        steps.append(_refresh_binance_trade_ws(watchlist, dry_run))
        steps.append(_refresh_binance_kline_ws(watchlist, dry_run))
    elif action == "restart_binance_kline_ws":
        steps.append(_refresh_binance_kline_ws(watchlist, dry_run))
    elif action == "restart_binance_trade_ws":
        steps.append(_refresh_binance_trade_ws(watchlist, dry_run))

    after = json.loads(execute_inspect_project_health(db, scope="repair_postcheck", include_logs=False, log_limit=5))
    return _status_result({
        "status": "dry_run" if dry_run else "completed",
        "executed": not dry_run,
        "action": action,
        "reason": reason,
        "watchlist_used": watchlist,
        "steps": steps,
        "precheck_summary": {
            "collector_comparison": before.get("binance_watchlist_comparison"),
            "suggested_actions": before.get("suggested_repair_actions"),
        },
        "postcheck_summary": {
            "collector_comparison": after.get("binance_watchlist_comparison"),
            "collectors": after.get("collectors"),
        },
        "safety_boundary": "Whitelisted runtime repair only; operator tools handle non-secret code edits separately. No credential changes, environment switches, database wipes, or trades.",
    })
