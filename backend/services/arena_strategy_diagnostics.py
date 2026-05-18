"""Arena strategy diagnostics and prompt repair helpers."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from database.models import Account, AccountPromptBinding, AIDecisionLog, PromptTemplate
from repositories import prompt_repo

PATCH_BEGIN = "=== ARENA STRATEGY DIAGNOSTIC PATCH ==="
PATCH_END = "=== END ARENA STRATEGY DIAGNOSTIC PATCH ==="


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_exchange(exchange: Optional[str]) -> str:
    normalized = (exchange or "binance").strip().lower()
    return normalized if normalized in {"binance", "hyperliquid"} else "binance"


def _decision_query(db: Session, account_id: Optional[int], exchange: str):
    query = db.query(AIDecisionLog)
    if account_id is not None:
        query = query.filter(AIDecisionLog.account_id == account_id)
    if exchange == "hyperliquid":
        query = query.filter(or_(AIDecisionLog.exchange == "hyperliquid", AIDecisionLog.exchange.is_(None)))
    else:
        query = query.filter(AIDecisionLog.exchange == exchange)
    return query


def _summarize_decision(row: AIDecisionLog) -> Dict[str, Any]:
    pnl = _as_float(row.realized_pnl, 0.0) if row.realized_pnl is not None else None
    operation = (row.operation or "hold").lower()
    reason = (row.reason or "").strip()
    if len(reason) > 180:
        reason = f"{reason[:177]}..."
    return {
        "id": row.id,
        "time": row.decision_time.isoformat() if row.decision_time else None,
        "symbol": row.symbol,
        "operation": operation,
        "executed": row.executed == "true",
        "target_portion": _as_float(row.target_portion),
        "prev_portion": _as_float(row.prev_portion),
        "realized_pnl": pnl,
        "summary": f"{row.symbol or 'GLOBAL'} {operation.upper()}: {reason or 'No reason recorded.'}",
    }


def _current_prompt(db: Session, account_id: Optional[int]) -> tuple[Optional[PromptTemplate], Optional[AccountPromptBinding]]:
    if account_id is None:
        return None, None
    binding = prompt_repo.get_binding_by_account(db, account_id)
    if not binding:
        return None, None
    template = db.get(PromptTemplate, binding.prompt_template_id)
    if not template or template.is_deleted == "true":
        return None, binding
    return template, binding


def _build_patch_text(diagnostics: Dict[str, Any]) -> str:
    issues = diagnostics.get("issues") or ["No critical issue detected."]
    optimizations = diagnostics.get("optimizations") or ["Keep current risk controls and continue monitoring."]
    stats = diagnostics.get("stats") or {}
    generated_at = diagnostics.get("generated_at") or _utcnow().isoformat()
    issue_lines = "\n".join(f"- {item}" for item in issues[:6])
    optimization_lines = "\n".join(f"- {item}" for item in optimizations[:6])
    return (
        f"{PATCH_BEGIN}\n"
        f"Generated: {generated_at}\n"
        "Purpose: cooperate with Arena Strategy Diagnosis AI, Attribution AI, Backtest Data AI, Signal AI, "
        "K-Line AI, Market Data AI, Wallet AI, and Trader Management AI before every trade.\n\n"
        "Current diagnosis:\n"
        f"- decisions={stats.get('decision_count', 0)}, executed={stats.get('executed_count', 0)}, "
        f"hold_rate={stats.get('hold_rate', 0):.1%}, realized_pnl={stats.get('realized_pnl', 0):+.4f}\n"
        f"{issue_lines}\n\n"
        "Required behavior from now on:\n"
        "- For every symbol, summarize why BUY/SELL/CLOSE/HOLD is chosen in one concrete sentence.\n"
        "- For every executed or recently closed trade, compare the outcome with the prior decision reason and tighten the next decision if the premise failed.\n"
        "- If HOLD is chosen, state the missing trigger condition and the next price/indicator condition to watch.\n"
        "- Treat Strategy Diagnosis AI and Attribution AI warnings as hard review gates; do not trade when they conflict with live K-line/flow evidence.\n"
        "- Reduce target_portion or stay flat after repeated losses, missing backtest evidence, stale data, or conflicting sub-AI votes.\n\n"
        "Optimization priorities:\n"
        f"{optimization_lines}\n"
        f"{PATCH_END}"
    )


def _merge_prompt_patch(template_text: str, patch_text: str) -> str:
    text = template_text or ""
    begin = text.find(PATCH_BEGIN)
    end = text.find(PATCH_END)
    if begin != -1 and end != -1 and end > begin:
        end += len(PATCH_END)
        return f"{text[:begin].rstrip()}\n\n{patch_text}\n\n{text[end:].lstrip()}".rstrip()
    return f"{text.rstrip()}\n\n{patch_text}".strip()


def build_strategy_diagnostics(
    db: Session,
    *,
    account_id: Optional[int],
    exchange: str = "binance",
    limit: int = 50,
    include_prompt: bool = True,
) -> Dict[str, Any]:
    exchange = _normalize_exchange(exchange)
    limit = max(5, min(int(limit or 50), 200))
    account = db.get(Account, account_id) if account_id is not None else None

    decisions = (
        _decision_query(db, account_id, exchange)
        .order_by(desc(AIDecisionLog.decision_time))
        .limit(limit)
        .all()
    )
    summaries = [_summarize_decision(row) for row in decisions]

    op_counts = Counter((row.operation or "hold").lower() for row in decisions)
    by_symbol: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"decisions": 0, "ops": Counter(), "realized_pnl": 0.0})
    realized_values: List[float] = []
    for row in decisions:
        symbol = row.symbol or "GLOBAL"
        by_symbol[symbol]["decisions"] += 1
        by_symbol[symbol]["ops"][(row.operation or "hold").lower()] += 1
        if row.realized_pnl is not None:
            pnl = _as_float(row.realized_pnl)
            by_symbol[symbol]["realized_pnl"] += pnl
            realized_values.append(pnl)

    decision_count = len(decisions)
    executed_count = sum(1 for row in decisions if row.executed == "true")
    hold_count = op_counts.get("hold", 0)
    hold_rate = hold_count / decision_count if decision_count else 0.0
    realized_pnl = sum(realized_values)
    win_count = sum(1 for value in realized_values if value > 0)
    loss_count = sum(1 for value in realized_values if value < 0)
    win_rate = win_count / len(realized_values) if realized_values else None

    hold_streak = 0
    for row in decisions:
        if (row.operation or "").lower() == "hold":
            hold_streak += 1
        else:
            break

    issues: List[str] = []
    optimizations: List[str] = []
    if not account:
        issues.append("No active AI trader account was resolved for this diagnosis.")
    if not decisions:
        issues.append("No decision logs found; the strategy cannot be evaluated yet.")
        optimizations.append("Verify prompt binding, wallet readiness, strategy interval, and signal pool linkage before trading.")
    if decision_count >= 10 and hold_rate >= 0.85:
        issues.append(f"High HOLD concentration: {hold_count}/{decision_count} recent decisions are HOLD.")
        optimizations.append("Make HOLD reasons explicit and define the exact missing entry condition per symbol.")
    if hold_streak >= 8:
        issues.append(f"Current HOLD streak is {hold_streak}; the prompt may be too restrictive or market filters conflict.")
        optimizations.append("Ask the prompt to separate valid no-trade conditions from over-filtering and watch one trigger per symbol.")
    if realized_values and realized_pnl < 0:
        issues.append(f"Recent closed-outcome PnL is negative ({realized_pnl:+.4f}).")
        optimizations.append("Lower target_portion after losses and require stronger K-line/flow agreement before re-entry.")
    if decision_count >= 10 and not realized_values:
        issues.append("No realized PnL is attached to recent decisions, so optimization confidence is limited.")
        optimizations.append("Run PnL refresh and backtest before treating performance conclusions as reliable.")

    template, binding = _current_prompt(db, account_id)
    if account_id is not None and not binding:
        issues.append("No active prompt binding found for this trader.")
        optimizations.append("Bind a prompt template before expecting automatic prompt repair to affect live decisions.")
    elif binding and not template:
        issues.append("Prompt binding exists but the template is missing or deleted.")

    if not optimizations:
        optimizations.append("Continue using the current strategy, but keep requiring sub-AI agreement and post-trade summaries.")

    risk_level = "low"
    if any("negative" in item or "No active" in item or "missing" in item for item in issues):
        risk_level = "high"
    elif issues:
        risk_level = "medium"

    score = 100
    score -= min(35, len(issues) * 12)
    if hold_rate >= 0.85 and decision_count >= 10:
        score -= 12
    if realized_values and realized_pnl < 0:
        score -= 18
    if decision_count == 0:
        score = min(score, 35)
    score = max(0, min(100, score))

    by_symbol_payload = {
        symbol: {
            "decisions": data["decisions"],
            "ops": dict(data["ops"]),
            "realized_pnl": round(data["realized_pnl"], 6),
        }
        for symbol, data in sorted(by_symbol.items())
    }

    generated_at = _utcnow().isoformat()
    stats = {
        "decision_count": decision_count,
        "executed_count": executed_count,
        "operation_counts": dict(op_counts),
        "hold_rate": hold_rate,
        "hold_streak": hold_streak,
        "realized_pnl": round(realized_pnl, 6),
        "win_rate": win_rate,
        "win_count": win_count,
        "loss_count": loss_count,
        "symbols": sorted(by_symbol_payload.keys()),
    }
    summary = (
        f"Strategy Diagnosis AI ({exchange}): {decision_count} recent decisions, "
        f"ops={dict(op_counts)}, hold_rate={hold_rate:.1%}, realized_pnl={realized_pnl:+.4f}. "
        f"Issues={issues or ['none']}. Optimizations={optimizations[:3]}."
    )

    diagnostics: Dict[str, Any] = {
        "account_id": account_id,
        "account_name": account.name if account else None,
        "exchange": exchange,
        "generated_at": generated_at,
        "status": "ok" if not issues else "warning",
        "health_score": score,
        "risk_level": risk_level,
        "summary": summary,
        "issues": issues,
        "optimizations": optimizations,
        "stats": stats,
        "by_symbol": by_symbol_payload,
        "trade_summaries": summaries,
        "prompt_template": (
            {
                "id": template.id,
                "key": template.key,
                "name": template.name,
                "description": template.description,
                "updated_at": template.updated_at.isoformat() if template.updated_at else None,
            }
            if template
            else None
        ),
        "can_apply_prompt_fix": bool(template and account_id is not None),
    }

    patch_text = _build_patch_text(diagnostics)
    diagnostics["prompt_patch"] = patch_text
    if include_prompt and template:
        diagnostics["proposed_prompt"] = _merge_prompt_patch(template.template_text, patch_text)
    else:
        diagnostics["proposed_prompt"] = None

    return diagnostics


def build_strategy_diagnostics_snapshot(
    db: Session,
    *,
    account_id: Optional[int],
    exchange: str,
    symbols: Iterable[str],
    timeframe: str,
) -> Dict[str, Any]:
    diagnostics = build_strategy_diagnostics(
        db,
        account_id=account_id,
        exchange=exchange,
        limit=50,
        include_prompt=False,
    )
    stats = diagnostics["stats"]
    return {
        "module": "strategy_diagnostics_ai",
        "status": diagnostics["status"],
        "summary": diagnostics["summary"],
        "direction": "neutral",
        "confidence": max(0.2, min(0.9, diagnostics["health_score"] / 100)),
        "risk_level": diagnostics["risk_level"],
        "raw_payload": {
            "symbols": list(symbols),
            "timeframe": timeframe,
            "health_score": diagnostics["health_score"],
            "issues": diagnostics["issues"],
            "optimizations": diagnostics["optimizations"],
            "stats": stats,
            "by_symbol": diagnostics["by_symbol"],
            "trade_summaries": diagnostics["trade_summaries"][:20],
            "prompt_patch": diagnostics["prompt_patch"],
        },
    }


def apply_strategy_prompt_fix(
    db: Session,
    *,
    account_id: int,
    exchange: str = "binance",
    limit: int = 50,
) -> Dict[str, Any]:
    diagnostics = build_strategy_diagnostics(
        db,
        account_id=account_id,
        exchange=exchange,
        limit=limit,
        include_prompt=True,
    )
    template_info = diagnostics.get("prompt_template")
    proposed_prompt = diagnostics.get("proposed_prompt")
    if not template_info or not proposed_prompt:
        raise ValueError("No active prompt template is available for automatic repair.")

    source = db.get(PromptTemplate, int(template_info["id"]))
    if not source:
        raise ValueError("Prompt template disappeared before repair could be applied.")

    timestamp = _utcnow().strftime("%Y%m%d%H%M%S")
    base_key = (source.key or "prompt")[:70].rstrip("-")
    new_template = PromptTemplate(
        key=f"{base_key}-arena-fix-{timestamp}",
        name=f"{(source.name or 'Prompt')[:160]} - Arena Auto Fix {timestamp}",
        description="Auto-generated by Arena Strategy Diagnosis AI. Source template was preserved.",
        template_text=proposed_prompt,
        system_template_text=proposed_prompt,
        is_system="false",
        is_deleted="false",
        created_by="arena_strategy_diagnostics_ai",
        updated_by="arena_strategy_diagnostics_ai",
    )
    db.add(new_template)
    db.flush()

    binding = prompt_repo.upsert_binding(
        db,
        account_id=account_id,
        prompt_template_id=new_template.id,
        updated_by="arena_strategy_diagnostics_ai",
    )
    db.refresh(new_template)
    updated_diagnostics = build_strategy_diagnostics(
        db,
        account_id=account_id,
        exchange=exchange,
        limit=limit,
        include_prompt=True,
    )
    return {
        "success": True,
        "account_id": account_id,
        "exchange": _normalize_exchange(exchange),
        "source_prompt_template_id": source.id,
        "new_prompt_template_id": new_template.id,
        "new_prompt_template_name": new_template.name,
        "binding_id": binding.id,
        "diagnostics": updated_diagnostics,
    }
