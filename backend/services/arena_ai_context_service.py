"""Arena AI context bus.

This module keeps sub-AI output as an advisory context layer. The main trading
AI still builds its own live market context through ai_decision_service; this
service only adds normalized, auditable summaries from the surrounding modules.
"""

from __future__ import annotations

import json
import logging
import math
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from database.models import (
    Account,
    AccountProgramBinding,
    AccountPromptBinding,
    AccountStrategyConfig,
    AIDecisionLog,
    AiAttributionMessage,
    ArenaAIContextSnapshot,
    ProgramExecutionLog,
    SignalDefinition,
    SignalPool,
    SignalTriggerLog,
)
from services.arena_ai_backtest_context import build_backtest_snapshot as _build_backtest_snapshot
from services.arena_ai_insight_context import build_insight_snapshot as _build_insight_snapshot
from services.arena_ai_kline_context import build_kline_snapshot as _build_kline_snapshot
from services.arena_ai_kline_coverage_context import (
    build_kline_coverage_snapshot as _build_kline_coverage_snapshot,
)

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = ["BTC", "ETH", "SOL", "BNB"]
DEFAULT_TIMEFRAME = "15m"
DEFAULT_CONTEXT_TTL_SECONDS = 900
PROMPT_CONTEXT_STALE_SECONDS = 180
MODULE_KLINE = "kline_ai"
MODULE_INSIGHT = "insight_ai"
MODULE_MARKET = "market_data_ai"
MODULE_SIGNAL = "signal_ai"
MODULE_WALLET = "wallet_tracking_ai"
MODULE_ATTRIBUTION = "attribution_ai"
MODULE_TRADER = "trader_management_ai"
MODULE_BACKTEST = "backtest_data_ai"
MODULE_SUPERVISOR = "supervisor_ai"
MODULE_STRATEGY_DIAGNOSTICS = "strategy_diagnostics_ai"
MODULE_KLINE_COVERAGE = "kline_coverage_ai"

MODULE_ORDER = [
    MODULE_SUPERVISOR,
    MODULE_KLINE,
    MODULE_KLINE_COVERAGE,
    MODULE_INSIGHT,
    MODULE_MARKET,
    MODULE_SIGNAL,
    MODULE_WALLET,
    MODULE_TRADER,
    MODULE_BACKTEST,
    MODULE_STRATEGY_DIAGNOSTICS,
    MODULE_ATTRIBUTION,
]

MODULE_RESPONSIBILITIES: Dict[str, Dict[str, Any]] = {
    MODULE_SUPERVISOR: {
        "display_name": "AI Decision Supervisor",
        "responsibility": (
            "Merge all Dashboard sub-AI snapshots, surface conflicts/data gaps, and hand a compact "
            "advisory layer to the main trading AI. It does not execute trades."
        ),
        "data_contract": ["module_votes", "symbol_directions", "conflicts", "data_gaps", "risk_votes"],
        "freshness_seconds": PROMPT_CONTEXT_STALE_SECONDS,
    },
    MODULE_KLINE: {
        "display_name": "K-Line Charts AI",
        "responsibility": (
            "Work from the K-Line Charts page data: timely market ticker fields, mark/oracle price, "
            "24h change/volume, open interest, funding, full technical indicators, flow overlays, "
            "and latest chart AI notes."
        ),
        "data_contract": [
            "price/oracle_price",
            "change24h/volume24h",
            "open_interest/funding_rate",
            "MA5/MA10/MA20",
            "EMA20/EMA50/EMA100",
            "VWAP/OBV",
            "RSI14/RSI7/STOCH/MACD",
            "BOLL/ATR14",
            "CVD/TAKER/OI/OI_DELTA/FUNDING/DEPTH/IMBALANCE",
        ],
        "freshness_seconds": PROMPT_CONTEXT_STALE_SECONDS,
    },
    MODULE_INSIGHT: {
        "display_name": "Dashboard Insight AI",
        "responsibility": (
            "Work from the Dashboard Insight page data: market-intelligence snapshot, recent news, "
            "whale-flow zones, OI/funding, event tone, and chart-window reaction context. It compresses "
            "those fast event signals for the main decision layer."
        ),
        "data_contract": [
            "4h_flow_summary",
            "news_items",
            "large_order_zones",
            "OI/funding",
            "event_sentiment",
            "selected_event",
            "chart_window",
        ],
        "freshness_seconds": PROMPT_CONTEXT_STALE_SECONDS,
    },
    MODULE_MARKET: {
        "display_name": "Market Data AI",
        "responsibility": (
            "Process timely market microstructure data: CVD, taker volume, open interest, funding, "
            "depth, orderbook imbalance, and price change."
        ),
        "data_contract": ["CVD", "TAKER", "OI", "OI_DELTA", "FUNDING", "DEPTH", "IMBALANCE"],
        "freshness_seconds": 120,
    },
    MODULE_SIGNAL: {
        "display_name": "Signal System AI",
        "responsibility": (
            "Report enabled signal pools, recent triggers, trigger direction hints, and signal coverage "
            "for the selected symbol universe."
        ),
        "data_contract": ["signal_pools", "signal_definitions", "trigger_count_24h", "latest_trigger"],
        "freshness_seconds": PROMPT_CONTEXT_STALE_SECONDS,
    },
    MODULE_WALLET: {
        "display_name": "Wallet Tracking AI",
        "responsibility": (
            "Track synced smart-wallet status and latest wallet-flow triggers so main AI can treat them "
            "as external behavior signals."
        ),
        "data_contract": ["runtime_status", "synced_addresses", "wallet_signal_pools", "latest_wallet_trigger"],
        "freshness_seconds": 300,
    },
    MODULE_TRADER: {
        "display_name": "AI Trader Management AI",
        "responsibility": (
            "Check trader readiness: active status, auto-trading flag, prompt/program bindings, trigger "
            "intervals, exchange alignment, and recent execution health."
        ),
        "data_contract": ["active_traders", "bindings", "trigger_config", "latest_decision", "warnings"],
        "freshness_seconds": PROMPT_CONTEXT_STALE_SECONDS,
    },
    MODULE_BACKTEST: {
        "display_name": "Backtest Data AI",
        "responsibility": (
            "Validate strategy evidence: program/prompt backtest results, data quality, closed outcomes, "
            "win rate, drawdown, profit factor, and readiness warnings."
        ),
        "data_contract": ["program_backtests", "prompt_backtests", "data_quality", "closed_outcomes", "risk"],
        "freshness_seconds": 900,
    },
    MODULE_STRATEGY_DIAGNOSTICS: {
        "display_name": "Strategy Diagnosis AI",
        "responsibility": (
            "Summarize every recent trade/decision, identify strategy drift, produce optimization priorities, "
            "and generate an auditable prompt-repair patch for the active AI Trader."
        ),
        "data_contract": [
            "decision_summary",
            "trade_summaries",
            "hold_rate",
            "realized_pnl",
            "issues",
            "optimizations",
            "prompt_patch",
        ],
        "freshness_seconds": PROMPT_CONTEXT_STALE_SECONDS,
    },
    MODULE_KLINE_COVERAGE: {
        "display_name": "数据.md K-Line Coverage AI",
        "responsibility": (
            "Every 3 minutes, check and refresh the Binance K-line coverage requested in 数据.md across "
            "1m/3m/5m/15m/30m/1h/2h/4h/8h/12h/1d/3d/1w/1M, then report missing, stale, or partial "
            "technical/flow indicator coverage for the decision layer."
        ),
        "data_contract": [
            "symbols",
            "periods",
            "kline_count/latest_age",
            "MA/EMA/VWAP/OBV/RSI/BOLL/ATR/STOCH/MACD coverage",
            "CVD/FUNDING/TAKER/DEPTH/OI_DELTA/IMBALANCE coverage",
            "request_budget",
            "issues",
        ],
        "freshness_seconds": 180,
    },
    MODULE_ATTRIBUTION: {
        "display_name": "Attribution AI",
        "responsibility": (
            "Review recent AI decisions and realized outcomes to explain whether the strategy is behaving "
            "well or drifting."
        ),
        "data_contract": ["decision_logs", "execution_count", "realized_pnl", "win_rate", "latest_note"],
        "freshness_seconds": 900,
    },
}

_RECOMPUTE_LOCK = threading.Lock()
_RECOMPUTE_IN_PROGRESS: set[tuple[Any, ...]] = set()
_RECOMPUTE_SUBPROCESS_CODE = r"""
import json
import os
import traceback

from database.connection import SessionLocal
from services.arena_ai_context_service import recompute_arena_ai_context

payload = json.loads(os.environ["ARENA_AI_CONTEXT_RECOMPUTE_PAYLOAD"])
db = SessionLocal()
try:
    recompute_arena_ai_context(
        db,
        account_id=payload.get("account_id"),
        exchange=payload.get("exchange") or "binance",
        symbols=payload.get("symbols"),
        timeframe=payload.get("timeframe") or "15m",
    )
except Exception:
    db.rollback()
    traceback.print_exc()
    raise
finally:
    db.close()
"""


def _utcnow() -> datetime:
    return datetime.utcnow()


def _parse_json_text(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return None
        return result
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _short_text(value: Any, limit: int = 320) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _module_role(module: str) -> Dict[str, Any]:
    return MODULE_RESPONSIBILITIES.get(
        module,
        {
            "display_name": module,
            "responsibility": "Provide advisory context to the main trading AI.",
            "data_contract": [],
            "freshness_seconds": DEFAULT_CONTEXT_TTL_SECONDS,
        },
    )


def _snapshot_age_seconds(row: ArenaAIContextSnapshot, now: Optional[datetime] = None) -> Optional[float]:
    if not row.generated_at:
        return None
    now = now or _utcnow()
    return max(0.0, (now - row.generated_at).total_seconds())


def _freshness_status(row: ArenaAIContextSnapshot, now: Optional[datetime] = None) -> str:
    age = _snapshot_age_seconds(row, now)
    if age is None:
        return "unknown"
    role = _module_role(row.module)
    target = float(role.get("freshness_seconds") or DEFAULT_CONTEXT_TTL_SECONDS)
    if age <= target:
        return "fresh"
    if row.expires_at and row.expires_at >= (now or _utcnow()):
        return "stale_but_usable"
    return "expired"


def _format_number(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}"


def _format_usd(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    sign = "+" if value >= 0 else "-"
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{sign}${abs_value / 1_000_000_000:.2f}B"
    if abs_value >= 1_000_000:
        return f"{sign}${abs_value / 1_000_000:.2f}M"
    if abs_value >= 1_000:
        return f"{sign}${abs_value / 1_000:.1f}K"
    return f"{sign}${abs_value:.0f}"


def _direction_from_score(score: float, neutral_band: float = 0.35) -> str:
    if score > neutral_band:
        return "bullish"
    if score < -neutral_band:
        return "bearish"
    return "neutral"


def _normalize_exchange(exchange: Optional[str]) -> str:
    normalized = (exchange or "binance").strip().lower()
    if normalized not in {"binance", "hyperliquid", "okx"}:
        return "binance"
    return normalized


def normalize_symbols(exchange: str, symbols: Optional[Iterable[str]] = None, limit: int = 16) -> List[str]:
    if symbols:
        raw_symbols = symbols
    else:
        raw_symbols = []
        try:
            if exchange == "binance":
                from services.binance_symbol_service import get_selected_symbols
            elif exchange == "okx":
                from services.okx_symbol_service import get_selected_symbols
            else:
                from services.hyperliquid_symbol_service import get_selected_symbols
            raw_symbols = get_selected_symbols() or []
        except Exception as exc:
            logger.debug("Failed to load %s watchlist for AI context: %s", exchange, exc)

    normalized: List[str] = []
    seen = set()
    for item in raw_symbols or []:
        symbol = str(item or "").strip().upper()
        if not symbol:
            continue
        symbol = symbol.replace("-USD", "").replace("-PERP", "").replace("USDT", "")
        if symbol and symbol not in seen:
            seen.add(symbol)
            normalized.append(symbol)
        if len(normalized) >= limit:
            break

    if not normalized:
        normalized = DEFAULT_SYMBOLS[:limit]
    return normalized


def _serialize_snapshot(row: ArenaAIContextSnapshot) -> Dict[str, Any]:
    now = _utcnow()
    role = _module_role(row.module)
    return {
        "id": row.id,
        "account_id": row.account_id,
        "exchange": row.exchange,
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "module": row.module,
        "display_name": role.get("display_name", row.module),
        "responsibility": role.get("responsibility", ""),
        "data_contract": role.get("data_contract", []),
        "status": row.status,
        "summary": row.summary,
        "direction": row.direction,
        "confidence": row.confidence,
        "risk_level": row.risk_level,
        "age_seconds": _snapshot_age_seconds(row, now),
        "freshness": _freshness_status(row, now),
        "target_freshness_seconds": role.get("freshness_seconds"),
        "raw_payload": _parse_json_text(row.raw_payload, {}),
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


def save_context_snapshot(
    db: Session,
    *,
    module: str,
    account_id: Optional[int],
    exchange: str,
    symbol: Optional[str],
    timeframe: Optional[str],
    status: str,
    summary: str,
    direction: Optional[str] = None,
    confidence: Optional[float] = None,
    risk_level: Optional[str] = None,
    raw_payload: Optional[Dict[str, Any]] = None,
    ttl_seconds: int = DEFAULT_CONTEXT_TTL_SECONDS,
) -> ArenaAIContextSnapshot:
    now = _utcnow()
    row = ArenaAIContextSnapshot(
        module=module,
        account_id=account_id,
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
    )
    row.status = status
    row.summary = summary or ""
    row.direction = direction
    row.confidence = None if confidence is None else round(_clamp(float(confidence), 0.0, 1.0), 3)
    row.risk_level = risk_level
    row.raw_payload = _json_dumps(raw_payload or {})
    row.generated_at = now
    row.expires_at = now + timedelta(seconds=max(60, ttl_seconds))
    row.updated_at = now
    db.add(row)
    db.flush()
    return row


def _build_market_snapshot(db: Session, exchange: str, symbol: str, timeframe: str) -> Dict[str, Any]:
    try:
        from services.market_flow_indicators import get_flow_indicators_for_prompt

        flow = get_flow_indicators_for_prompt(
            db,
            symbol,
            timeframe,
            ["CVD", "TAKER", "OI", "OI_DELTA", "FUNDING", "DEPTH", "IMBALANCE", "PRICE_CHANGE"],
            exchange=exchange,
        )
    except Exception as exc:
        logger.warning("Failed to build market flow context for %s/%s: %s", symbol, exchange, exc)
        flow = {}

    cvd = flow.get("CVD") or {}
    taker = flow.get("TAKER") or {}
    oi = flow.get("OI") or {}
    oi_delta = flow.get("OI_DELTA") or {}
    funding = flow.get("FUNDING") or {}
    depth = flow.get("DEPTH") or {}
    imbalance = flow.get("IMBALANCE") or {}
    price_change = flow.get("PRICE_CHANGE") or {}

    cvd_current = _to_float(cvd.get("current"))
    cvd_cumulative = _to_float(cvd.get("cumulative"))
    taker_ratio = _to_float(taker.get("ratio"))
    oi_current = _to_float(oi.get("current"))
    oi_absolute_current = _to_float(oi.get("absolute_current"))
    oi_absolute_current_usd = _to_float(oi.get("absolute_current_usd"))
    oi_delta_current = _to_float(oi_delta.get("current"))
    funding_pct = _to_float(funding.get("current_pct"))
    depth_ratio = _to_float(depth.get("ratio"))
    imbalance_current = _to_float(imbalance.get("current"))
    price_change_pct = _to_float(price_change.get("current"))

    available_points = [
        value
        for value in [
            cvd_current,
            taker_ratio,
            oi_delta_current,
            funding_pct,
            depth_ratio,
            imbalance_current,
            price_change_pct,
        ]
        if value is not None
    ]

    if not available_points:
        return {
            "module": MODULE_MARKET,
            "status": "missing",
            "summary": f"{symbol}/{timeframe}: no market flow snapshot available for {exchange}.",
            "direction": "neutral",
            "confidence": 0.0,
            "risk_level": "unknown",
            "raw_payload": {"flow": flow},
        }

    score = 0.0
    if cvd_current is not None:
        score += 0.8 if cvd_current > 0 else -0.8
    if cvd_cumulative is not None:
        score += 0.4 if cvd_cumulative > 0 else -0.4
    if taker_ratio is not None:
        if taker_ratio > 1.15:
            score += 0.9
        elif taker_ratio < 0.87:
            score -= 0.9
    if oi_delta_current is not None:
        if oi_delta_current > 0.05:
            score += 0.35 if score >= 0 else -0.15
        elif oi_delta_current < -0.05:
            score -= 0.25 if score < 0 else 0.1
    if depth_ratio is not None:
        if depth_ratio > 1.05:
            score += 0.3
        elif depth_ratio < 0.95:
            score -= 0.3
    if imbalance_current is not None:
        if imbalance_current > 0.08:
            score += 0.45
        elif imbalance_current < -0.08:
            score -= 0.45
    if price_change_pct is not None and abs(price_change_pct) > 0.03:
        score += 0.25 if price_change_pct > 0 else -0.25

    direction = _direction_from_score(score)
    confidence = _clamp(0.3 + abs(score) * 0.13, 0.0, 0.9)
    funding_abs = abs(funding_pct or 0.0)
    risk_level = "low"
    if funding_abs >= 0.08 or abs(imbalance_current or 0.0) >= 0.35 or abs(oi_delta_current or 0.0) >= 5:
        risk_level = "high"
    elif funding_abs >= 0.03 or abs(imbalance_current or 0.0) >= 0.18 or abs(oi_delta_current or 0.0) >= 1.5:
        risk_level = "medium"

    summary = (
        f"{symbol}/{timeframe}: {direction} flow, CVD={_format_usd(cvd_current)}, "
        f"taker_ratio={_format_number(taker_ratio, 2)}, OI_delta={_format_number(oi_delta_current, 3)}%, "
        f"funding={_format_number(funding_pct, 4)}%, depth={_format_number(depth_ratio, 2)}, "
        f"imbalance={_format_number(imbalance_current, 3)}, price_change={_format_number(price_change_pct, 3)}%. "
        f"Advisory confidence={confidence:.2f}, risk={risk_level}."
    )

    return {
        "module": MODULE_MARKET,
        "status": "ok",
        "summary": summary,
        "direction": direction,
        "confidence": confidence,
        "risk_level": risk_level,
        "raw_payload": {
            "cvd_current": cvd_current,
            "cvd_cumulative": cvd_cumulative,
            "taker_ratio": taker_ratio,
            "oi_current": oi_current,
            "oi_absolute_current": oi_absolute_current,
            "oi_absolute_current_usd": oi_absolute_current_usd,
            "oi_status": oi.get("status"),
            "oi_delta_current": oi_delta_current,
            "oi_delta_status": oi_delta.get("status"),
            "funding_pct": funding_pct,
            "depth_ratio": depth_ratio,
            "imbalance_current": imbalance_current,
            "price_change_pct": price_change_pct,
            "flow": flow,
        },
    }


def _pool_symbols_match(pool: SignalPool, symbol: str) -> bool:
    symbols = _parse_json_text(pool.symbols, [])
    if not symbols:
        return True
    return symbol.upper() in {str(item).upper() for item in symbols}


def _infer_direction_from_text(*parts: Any) -> str:
    text = " ".join(str(part or "") for part in parts).lower()
    bearish_terms = ["short", "sell", "bear", "down", "空", "做空", "看跌"]
    bullish_terms = ["long", "buy", "bull", "up", "多", "做多", "看涨"]
    bearish = any(term in text for term in bearish_terms)
    bullish = any(term in text for term in bullish_terms)
    if bullish and not bearish:
        return "bullish"
    if bearish and not bullish:
        return "bearish"
    return "neutral"


def _build_signal_snapshot(db: Session, exchange: str, symbol: str, timeframe: str) -> Dict[str, Any]:
    pools = (
        db.query(SignalPool)
        .filter(
            SignalPool.exchange == exchange,
            SignalPool.enabled == True,  # noqa: E712
            SignalPool.is_deleted != True,  # noqa: E712
            SignalPool.source_type == "market_signals",
        )
        .order_by(SignalPool.id)
        .all()
    )
    matching_pools = [pool for pool in pools if _pool_symbols_match(pool, symbol)]

    pool_ids = [pool.id for pool in matching_pools]
    recent_logs: List[SignalTriggerLog] = []
    if pool_ids:
        recent_logs = (
            db.query(SignalTriggerLog)
            .filter(
                SignalTriggerLog.pool_id.in_(pool_ids),
                SignalTriggerLog.symbol == symbol,
                SignalTriggerLog.triggered_at >= _utcnow() - timedelta(hours=24),
            )
            .order_by(desc(SignalTriggerLog.triggered_at))
            .limit(20)
            .all()
        )

    definitions_by_id: Dict[int, SignalDefinition] = {}
    signal_ids: List[int] = []
    for pool in matching_pools:
        signal_ids.extend(int(item) for item in _parse_json_text(pool.signal_ids, []) if str(item).isdigit())
    if signal_ids:
        for definition in (
            db.query(SignalDefinition)
            .filter(
                SignalDefinition.id.in_(sorted(set(signal_ids))),
                SignalDefinition.is_deleted != True,  # noqa: E712
            )
            .all()
        ):
            definitions_by_id[definition.id] = definition

    latest_log = recent_logs[0] if recent_logs else None
    latest_trigger = _parse_json_text(latest_log.trigger_value, {}) if latest_log else {}
    pool_names = [pool.pool_name for pool in matching_pools[:5]]
    direction = _infer_direction_from_text(*(pool_names + [latest_trigger]))
    trigger_count = len(recent_logs)
    confidence = _clamp(0.25 + min(trigger_count, 6) * 0.09 + min(len(matching_pools), 4) * 0.04, 0, 0.82)

    status = "ok" if matching_pools else "missing"
    risk_level = "medium" if trigger_count >= 4 else "low"
    if not matching_pools:
        risk_level = "unknown"

    signal_names = [
        definitions_by_id[sid].signal_name
        for sid in sorted(definitions_by_id.keys())[:6]
    ]
    summary = (
        f"{symbol}: {len(matching_pools)} enabled {exchange} signal pools, "
        f"{trigger_count} triggers in 24h. Pools={pool_names or ['none']}. "
        f"Signals={signal_names or ['none']}. Latest_trigger="
        f"{latest_log.triggered_at.isoformat() if latest_log and latest_log.triggered_at else 'none'}. "
        f"Direction hint={direction}; this is advisory and must be checked against live module data."
    )

    return {
        "module": MODULE_SIGNAL,
        "status": status,
        "summary": summary,
        "direction": direction,
        "confidence": confidence if matching_pools else 0.0,
        "risk_level": risk_level,
        "raw_payload": {
            "pool_count": len(matching_pools),
            "pool_ids": pool_ids,
            "pool_names": pool_names,
            "signal_names": signal_names,
            "trigger_count_24h": trigger_count,
            "latest_trigger_id": latest_log.id if latest_log else None,
            "latest_trigger_value": latest_trigger,
            "timeframe": timeframe,
        },
    }


def _build_wallet_snapshot(db: Session, account_id: Optional[int], exchange: str) -> Dict[str, Any]:
    try:
        from services.hyper_insight_wallet_service import hyper_insight_wallet_service

        runtime = hyper_insight_wallet_service.get_status_snapshot()
    except Exception as exc:
        runtime = {"status": "error", "last_error": str(exc), "enabled": False}

    wallet_pools = (
        db.query(SignalPool)
        .filter(
            SignalPool.enabled == True,  # noqa: E712
            SignalPool.is_deleted != True,  # noqa: E712
            SignalPool.source_type == "wallet_tracking",
        )
        .order_by(SignalPool.id)
        .all()
    )
    pool_ids = [pool.id for pool in wallet_pools]
    latest_log = None
    if pool_ids:
        latest_log = (
            db.query(SignalTriggerLog)
            .filter(SignalTriggerLog.pool_id.in_(pool_ids))
            .order_by(desc(SignalTriggerLog.triggered_at))
            .first()
        )

    latest_value = _parse_json_text(latest_log.trigger_value, {}) if latest_log else {}
    detail = latest_value.get("detail") if isinstance(latest_value, dict) else {}
    direction = "neutral"
    if isinstance(detail, dict):
        direction = _infer_direction_from_text(detail.get("direction"), detail.get("action"), latest_value.get("summary"))
    elif isinstance(latest_value, dict):
        direction = _infer_direction_from_text(latest_value.get("summary"), latest_value.get("event_type"))

    status = str(runtime.get("status") or "unknown")
    configured_statuses = {"connected", "configured"}
    risk_level = "low" if status in configured_statuses else "medium" if runtime.get("enabled") else "unknown"
    confidence = 0.65 if status == "connected" else 0.45 if status == "configured" else 0.35 if runtime.get("enabled") else 0.1

    summary = (
        f"Wallet tracking: status={status}, enabled={runtime.get('enabled')}, "
        f"active_pools={len(wallet_pools)}, synced_addresses={len(runtime.get('synced_addresses') or [])}, "
        f"last_event={runtime.get('last_event_at') or 'none'}, latest_direction={direction}."
    )
    if runtime.get("last_error"):
        summary += f" Last error: {_short_text(runtime.get('last_error'), 180)}"

    return {
        "module": MODULE_WALLET,
        "status": "ok" if status in configured_statuses else status,
        "summary": summary,
        "direction": direction,
        "confidence": confidence,
        "risk_level": risk_level,
        "raw_payload": {
            "runtime": runtime,
            "wallet_pool_ids": pool_ids,
            "latest_trigger_id": latest_log.id if latest_log else None,
            "latest_trigger": latest_value,
            "account_id": account_id,
            "exchange": exchange,
        },
    }


def _build_trader_snapshot(db: Session, account_id: Optional[int], exchange: str) -> Dict[str, Any]:
    account_query = db.query(Account).filter(
        Account.account_type == "AI",
        Account.is_deleted != True,  # noqa: E712
    )
    if account_id is not None:
        account_query = account_query.filter(Account.id == account_id)
    accounts = account_query.order_by(Account.id).limit(20).all()

    if not accounts:
        return {
            "module": MODULE_TRADER,
            "status": "missing",
            "summary": "No AI trader account found for Arena automation.",
            "direction": "neutral",
            "confidence": 0.0,
            "risk_level": "high",
            "raw_payload": {"account_id": account_id},
        }

    rows: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for account in accounts:
        strategy = db.query(AccountStrategyConfig).filter(AccountStrategyConfig.account_id == account.id).first()
        prompt_binding = (
            db.query(AccountPromptBinding)
            .filter(AccountPromptBinding.account_id == account.id, AccountPromptBinding.is_deleted != True)  # noqa: E712
            .first()
        )
        program_binding = (
            db.query(AccountProgramBinding)
            .filter(
                AccountProgramBinding.account_id == account.id,
                AccountProgramBinding.exchange == exchange,
                AccountProgramBinding.is_deleted != True,  # noqa: E712
            )
            .order_by(desc(AccountProgramBinding.updated_at))
            .first()
        )
        latest_decision = (
            db.query(AIDecisionLog)
            .filter(AIDecisionLog.account_id == account.id)
            .order_by(desc(AIDecisionLog.decision_time))
            .first()
        )
        latest_program_log = (
            db.query(ProgramExecutionLog)
            .filter(ProgramExecutionLog.account_id == account.id)
            .order_by(desc(ProgramExecutionLog.created_at))
            .first()
        )

        row = {
            "account_id": account.id,
            "name": account.name,
            "active": account.is_active == "true",
            "auto_trading_enabled": account.auto_trading_enabled == "true",
            "has_prompt_binding": bool(prompt_binding),
            "strategy_enabled": bool(strategy and strategy.enabled == "true"),
            "scheduled_trigger_enabled": bool(strategy and strategy.scheduled_trigger_enabled),
            "trigger_interval": strategy.trigger_interval if strategy else None,
            "strategy_exchange": strategy.exchange if strategy else None,
            "program_binding_active": bool(program_binding and program_binding.is_active),
            "program_scheduled_enabled": bool(program_binding and program_binding.scheduled_trigger_enabled),
            "latest_decision_at": latest_decision.decision_time.isoformat() if latest_decision and latest_decision.decision_time else None,
            "latest_program_success": latest_program_log.success if latest_program_log else None,
        }
        if not row["auto_trading_enabled"]:
            warnings.append(f"{account.name}: auto trading disabled")
        if not row["has_prompt_binding"]:
            warnings.append(f"{account.name}: no prompt binding")
        if strategy and strategy.exchange != exchange:
            warnings.append(f"{account.name}: strategy exchange={strategy.exchange}, context exchange={exchange}")
        rows.append(row)

    active_count = sum(1 for row in rows if row["active"] and row["auto_trading_enabled"])
    prompt_ready_count = sum(1 for row in rows if row["has_prompt_binding"])
    risk_level = "high" if warnings else "low"
    if warnings and active_count > 0 and prompt_ready_count > 0:
        risk_level = "medium"

    summary = (
        f"Trader management: {len(rows)} AI traders inspected, {active_count} active with auto trading, "
        f"{prompt_ready_count} prompt-ready. "
        f"Warnings={warnings[:4] if warnings else ['none']}."
    )

    return {
        "module": MODULE_TRADER,
        "status": "ok" if not warnings else "warning",
        "summary": summary,
        "direction": "neutral",
        "confidence": 0.75 if not warnings else 0.5,
        "risk_level": risk_level,
        "raw_payload": {"accounts": rows, "warnings": warnings, "exchange": exchange},
    }


def _timeframe_seconds(timeframe: str) -> int:
    mapping = {
        "1m": 60,
        "3m": 180,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "2h": 7200,
        "4h": 14400,
        "6h": 21600,
        "8h": 28800,
        "12h": 43200,
        "1d": 86400,
        "3d": 259200,
        "1w": 604800,
        "1M": 2592000,
    }
    return mapping.get(timeframe, mapping[DEFAULT_TIMEFRAME])


def _age_seconds_from_epoch_ms(value: Any, now_ms: int) -> Optional[float]:
    number = _to_float(value)
    if number is None:
        return None
    return max(0.0, (now_ms - number) / 1000.0)


def _age_seconds_from_epoch_s(value: Any, now: datetime) -> Optional[float]:
    number = _to_float(value)
    if number is None:
        return None
    return max(0.0, now.timestamp() - number)


def _build_attribution_snapshot(db: Session, account_id: Optional[int], exchange: str) -> Dict[str, Any]:
    query = db.query(AIDecisionLog)
    if account_id is not None:
        query = query.filter(AIDecisionLog.account_id == account_id)
    if exchange:
        query = query.filter((AIDecisionLog.exchange == exchange) | (AIDecisionLog.exchange.is_(None)))
    decisions = query.order_by(desc(AIDecisionLog.decision_time)).limit(50).all()

    latest_ai_message = (
        db.query(AiAttributionMessage)
        .filter(AiAttributionMessage.role == "assistant")
        .order_by(desc(AiAttributionMessage.created_at))
        .first()
    )

    if not decisions:
        summary = "Attribution AI: no AI decision logs yet, so attribution cannot validate trade quality."
        if latest_ai_message:
            summary += f" Latest attribution note: {_short_text(latest_ai_message.content, 220)}"
        return {
            "module": MODULE_ATTRIBUTION,
            "status": "missing",
            "summary": summary,
            "direction": "neutral",
            "confidence": 0.15,
            "risk_level": "unknown",
            "raw_payload": {"decision_count": 0, "latest_message_id": latest_ai_message.id if latest_ai_message else None},
        }

    ops: Dict[str, int] = {}
    pnl_values: List[float] = []
    executed_count = 0
    for decision in decisions:
        ops[decision.operation] = ops.get(decision.operation, 0) + 1
        if decision.executed == "true":
            executed_count += 1
        pnl = _to_float(decision.realized_pnl)
        if pnl is not None:
            pnl_values.append(pnl)

    total_pnl = sum(pnl_values) if pnl_values else None
    win_rate = (sum(1 for value in pnl_values if value > 0) / len(pnl_values) * 100) if pnl_values else None
    if total_pnl is None:
        direction = "neutral"
    else:
        direction = "bullish" if total_pnl > 0 else "bearish" if total_pnl < 0 else "neutral"
    risk_level = "low"
    if pnl_values and win_rate is not None and win_rate < 35:
        risk_level = "high"
    elif pnl_values and win_rate is not None and win_rate < 50:
        risk_level = "medium"

    note = _short_text(latest_ai_message.content, 220) if latest_ai_message else ""
    summary = (
        f"Attribution AI: last {len(decisions)} decisions, executed={executed_count}, ops={ops}, "
        f"realized_pnl={_format_usd(total_pnl)}, win_rate={_format_number(win_rate, 1)}%. "
        f"Risk={risk_level}."
    )
    if note:
        summary += f" Latest attribution note: {note}"

    return {
        "module": MODULE_ATTRIBUTION,
        "status": "ok",
        "summary": summary,
        "direction": direction,
        "confidence": 0.65 if pnl_values else 0.35,
        "risk_level": risk_level,
        "raw_payload": {
            "decision_count": len(decisions),
            "executed_count": executed_count,
            "operation_counts": ops,
            "realized_pnl": total_pnl,
            "win_rate": win_rate,
            "latest_decision_id": decisions[0].id if decisions else None,
            "latest_message_id": latest_ai_message.id if latest_ai_message else None,
        },
    }


def _latest_snapshots_for_supervisor(
    db: Session,
    account_id: Optional[int],
    exchange: str,
    symbols: List[str],
    timeframe: str,
) -> List[ArenaAIContextSnapshot]:
    modules = [m for m in MODULE_ORDER if m != MODULE_SUPERVISOR]
    query = db.query(ArenaAIContextSnapshot).filter(
        ArenaAIContextSnapshot.exchange == exchange,
        ArenaAIContextSnapshot.module.in_(modules),
    )
    query = query.filter(
        (ArenaAIContextSnapshot.account_id == account_id)
        if account_id is not None
        else ArenaAIContextSnapshot.account_id.is_(None)
    )
    query = query.filter(
        (ArenaAIContextSnapshot.symbol.in_(symbols)) | (ArenaAIContextSnapshot.symbol.is_(None))
    )
    query = query.filter(
        (ArenaAIContextSnapshot.timeframe == timeframe) | (ArenaAIContextSnapshot.timeframe.is_(None))
    )
    rows = query.order_by(desc(ArenaAIContextSnapshot.generated_at)).all()

    deduped: Dict[tuple, ArenaAIContextSnapshot] = {}
    for row in rows:
        key = (row.module, row.symbol, row.timeframe)
        if key not in deduped:
            deduped[key] = row
    return list(deduped.values())


def _build_supervisor_snapshot(
    db: Session,
    account_id: Optional[int],
    exchange: str,
    symbols: List[str],
    timeframe: str,
) -> Dict[str, Any]:
    snapshots = _latest_snapshots_for_supervisor(db, account_id, exchange, symbols, timeframe)
    symbol_votes: Dict[str, List[str]] = {symbol: [] for symbol in symbols}
    risks: List[str] = []
    stale_or_missing: List[str] = []

    for row in snapshots:
        freshness = _freshness_status(row)
        if row.risk_level:
            risks.append(row.risk_level)
        if row.status not in {"ok", "warning", "partial"} or freshness == "expired":
            stale_or_missing.append(f"{row.module}:{row.symbol or 'global'}={row.status}/{freshness}")
        elif freshness == "stale_but_usable":
            stale_or_missing.append(f"{row.module}:{row.symbol or 'global'}=stale")
        if row.symbol in symbol_votes and row.direction in {"bullish", "bearish"}:
            symbol_votes[row.symbol].append(row.direction)

    conflicts: List[str] = []
    final_symbol_direction: Dict[str, str] = {}
    for symbol, votes in symbol_votes.items():
        bullish = votes.count("bullish")
        bearish = votes.count("bearish")
        if bullish and bearish:
            conflicts.append(f"{symbol}: bullish={bullish}, bearish={bearish}")
            final_symbol_direction[symbol] = "conflict"
        elif bullish:
            final_symbol_direction[symbol] = "bullish"
        elif bearish:
            final_symbol_direction[symbol] = "bearish"
        else:
            final_symbol_direction[symbol] = "neutral"

    risk_level = "low"
    if "high" in risks or conflicts:
        risk_level = "high"
    elif "medium" in risks or stale_or_missing:
        risk_level = "medium"

    confidence_values = [
        float(row.confidence)
        for row in snapshots
        if row.confidence is not None and row.status in {"ok", "warning", "partial"}
    ]
    confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.25
    if conflicts:
        confidence *= 0.75
    if stale_or_missing:
        confidence *= 0.85

    summary = (
        f"Supervisor AI ({exchange}/{timeframe}): advisory layer built from {len(snapshots)} module snapshots. "
        f"Symbol directions={final_symbol_direction}. "
        f"Conflicts={conflicts or ['none']}. Data gaps={stale_or_missing or ['none']}. "
        "Main AI must verify every advisory signal with direct market/K-line/news/trigger context before trading."
    )

    return {
        "module": MODULE_SUPERVISOR,
        "status": "warning" if conflicts or stale_or_missing else "ok",
        "summary": summary,
        "direction": "conflict" if conflicts else "neutral",
        "confidence": _clamp(confidence, 0.0, 0.9),
        "risk_level": risk_level,
        "raw_payload": {
            "symbols": symbols,
            "timeframe": timeframe,
            "module_count": len(snapshots),
            "symbol_directions": final_symbol_direction,
            "conflicts": conflicts,
            "data_gaps": stale_or_missing,
            "risk_votes": risks,
        },
    }


def recompute_arena_ai_context(
    db: Session,
    *,
    account_id: Optional[int] = None,
    exchange: str = "binance",
    symbols: Optional[Iterable[str]] = None,
    timeframe: str = DEFAULT_TIMEFRAME,
    commit: bool = True,
) -> Dict[str, Any]:
    exchange = _normalize_exchange(exchange)
    symbol_list = normalize_symbols(exchange, symbols)
    timeframe = timeframe or DEFAULT_TIMEFRAME
    created: List[ArenaAIContextSnapshot] = []

    for symbol in symbol_list:
        for builder in (
            lambda: _build_kline_snapshot(db, account_id, exchange, symbol, timeframe),
            lambda: _build_insight_snapshot(db, exchange, symbol, timeframe),
            lambda: _build_market_snapshot(db, exchange, symbol, timeframe),
            lambda: _build_signal_snapshot(db, exchange, symbol, timeframe),
        ):
            payload = builder()
            created.append(
                save_context_snapshot(
                    db,
                    module=payload["module"],
                    account_id=account_id,
                    exchange=exchange,
                    symbol=symbol,
                    timeframe=timeframe,
                    status=payload["status"],
                    summary=payload["summary"],
                    direction=payload.get("direction"),
                    confidence=payload.get("confidence"),
                    risk_level=payload.get("risk_level"),
                    raw_payload=payload.get("raw_payload"),
                )
            )

    from services.arena_strategy_diagnostics import build_strategy_diagnostics_snapshot

    strategy_diagnostics = build_strategy_diagnostics_snapshot(
        db,
        account_id=account_id,
        exchange=exchange,
        symbols=symbol_list,
        timeframe=timeframe,
    )

    for payload in (
        _build_kline_coverage_snapshot(db, account_id, exchange, symbol_list, timeframe),
        _build_wallet_snapshot(db, account_id, exchange),
        _build_trader_snapshot(db, account_id, exchange),
        _build_backtest_snapshot(db, account_id, exchange, symbol_list, timeframe),
        strategy_diagnostics,
        _build_attribution_snapshot(db, account_id, exchange),
    ):
        created.append(
            save_context_snapshot(
                db,
                module=payload["module"],
                account_id=account_id,
                exchange=exchange,
                symbol=None,
                timeframe=None,
                status=payload["status"],
                summary=payload["summary"],
                direction=payload.get("direction"),
                confidence=payload.get("confidence"),
                risk_level=payload.get("risk_level"),
                raw_payload=payload.get("raw_payload"),
            )
        )

    supervisor = _build_supervisor_snapshot(db, account_id, exchange, symbol_list, timeframe)
    created.append(
        save_context_snapshot(
            db,
            module=supervisor["module"],
            account_id=account_id,
            exchange=exchange,
            symbol=None,
            timeframe=timeframe,
            status=supervisor["status"],
            summary=supervisor["summary"],
            direction=supervisor.get("direction"),
            confidence=supervisor.get("confidence"),
            risk_level=supervisor.get("risk_level"),
            raw_payload=supervisor.get("raw_payload"),
        )
    )

    if commit:
        db.commit()
    else:
        db.flush()
    return {
        "exchange": exchange,
        "symbols": symbol_list,
        "timeframe": timeframe,
        "account_id": account_id,
        "snapshots": [_serialize_snapshot(row) for row in created],
    }


def enqueue_arena_ai_context_recompute(
    *,
    account_id: Optional[int] = None,
    exchange: str = "binance",
    symbols: Optional[Iterable[str]] = None,
    timeframe: str = DEFAULT_TIMEFRAME,
) -> str:
    exchange = _normalize_exchange(exchange)
    symbol_list = normalize_symbols(exchange, symbols)
    timeframe = timeframe or DEFAULT_TIMEFRAME
    key = (account_id, exchange, tuple(symbol_list), timeframe)

    with _RECOMPUTE_LOCK:
        if key in _RECOMPUTE_IN_PROGRESS:
            return "already_running"
        _RECOMPUTE_IN_PROGRESS.add(key)

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = os.environ.copy()
    env["ARENA_AI_CONTEXT_RECOMPUTE_PAYLOAD"] = _json_dumps(
        {
            "account_id": account_id,
            "exchange": exchange,
            "symbols": symbol_list,
            "timeframe": timeframe,
        }
    )
    env["PYTHONPATH"] = backend_dir + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    log_path = os.getenv("ARENA_AI_CONTEXT_RECOMPUTE_LOG", "/tmp/hyper-alpha-ai-context-recompute.log")
    command = ["nice", "-n", "10", sys.executable, "-c", _RECOMPUTE_SUBPROCESS_CODE]

    log_file = None
    try:
        log_file = open(log_path, "a", encoding="utf-8")
        process = subprocess.Popen(
            command,
            cwd=backend_dir,
            env=env,
            stdout=log_file,
            stderr=log_file,
            close_fds=True,
        )
    except Exception as exc:
        with _RECOMPUTE_LOCK:
            _RECOMPUTE_IN_PROGRESS.discard(key)
        logger.warning(
            "Failed to enqueue Arena AI context external recompute account_id=%s exchange=%s timeframe=%s symbols=%s: %s",
            account_id,
            exchange,
            timeframe,
            symbol_list,
            exc,
            exc_info=True,
        )
        return "deferred_to_scheduler"
    finally:
        if log_file is not None:
            log_file.close()

    watcher = threading.Thread(
        target=_watch_recompute_process,
        args=(key, process),
        daemon=True,
        name=f"arena-ai-context-recompute-watch-{process.pid}",
    )
    watcher.start()
    logger.info(
        "Arena AI context external recompute queued pid=%s account_id=%s exchange=%s timeframe=%s symbols=%s",
        process.pid,
        account_id,
        exchange,
        timeframe,
        symbol_list,
    )
    return "queued_external"


def _watch_recompute_process(key: tuple[Any, ...], process: subprocess.Popen) -> None:
    try:
        return_code = process.wait()
        if return_code == 0:
            logger.info("Arena AI context external recompute finished pid=%s", process.pid)
        else:
            logger.warning("Arena AI context external recompute failed pid=%s return_code=%s", process.pid, return_code)
    finally:
        with _RECOMPUTE_LOCK:
            _RECOMPUTE_IN_PROGRESS.discard(key)


def get_latest_context_snapshots(
    db: Session,
    *,
    account_id: Optional[int] = None,
    exchange: str = "binance",
    symbols: Optional[Iterable[str]] = None,
    timeframe: str = DEFAULT_TIMEFRAME,
    include_expired: bool = False,
) -> List[ArenaAIContextSnapshot]:
    exchange = _normalize_exchange(exchange)
    symbol_list = normalize_symbols(exchange, symbols)
    query = db.query(ArenaAIContextSnapshot).filter(ArenaAIContextSnapshot.exchange == exchange)
    query = query.filter(
        (ArenaAIContextSnapshot.account_id == account_id)
        if account_id is not None
        else ArenaAIContextSnapshot.account_id.is_(None)
    )
    query = query.filter(
        (ArenaAIContextSnapshot.symbol.in_(symbol_list)) | (ArenaAIContextSnapshot.symbol.is_(None))
    )
    query = query.filter(
        (ArenaAIContextSnapshot.timeframe == timeframe) | (ArenaAIContextSnapshot.timeframe.is_(None))
    )
    if not include_expired:
        now = _utcnow()
        query = query.filter(
            (ArenaAIContextSnapshot.expires_at.is_(None)) | (ArenaAIContextSnapshot.expires_at >= now)
        )

    rows = query.order_by(desc(ArenaAIContextSnapshot.generated_at)).all()
    deduped: Dict[tuple, ArenaAIContextSnapshot] = {}
    for row in rows:
        key = (row.module, row.symbol, row.timeframe)
        if key not in deduped:
            deduped[key] = row
    return list(deduped.values())


def _format_snapshots_for_prompt(rows: List[ArenaAIContextSnapshot], modules: Optional[Iterable[str]] = None) -> str:
    module_filter = set(modules) if modules else None
    filtered = [row for row in rows if module_filter is None or row.module in module_filter]
    if not filtered:
        return "N/A"

    order_index = {module: idx for idx, module in enumerate(MODULE_ORDER)}
    filtered.sort(
        key=lambda row: (
            order_index.get(row.module, 99),
            row.symbol or "",
            row.timeframe or "",
        )
    )

    lines = [
        "=== ARENA AI ADVISORY CONTEXT ===",
        "Policy: Sub-AI outputs are advisory only. The main AI must verify them against direct live market, K-line, news, wallet, and trigger data before any trade.",
        "Role map: each Dashboard AI has a separate responsibility and provides compressed, auditable data to the main decision layer.",
    ]
    used_modules = []
    for module in MODULE_ORDER:
        if any(row.module == module for row in filtered):
            role = _module_role(module)
            used_modules.append(f"{role.get('display_name', module)}={module}")
    if used_modules:
        lines.append("Active roles: " + "; ".join(used_modules))

    now = _utcnow()
    for row in filtered:
        scope = row.symbol or "GLOBAL"
        if row.timeframe:
            scope = f"{scope}/{row.timeframe}"
        confidence = "N/A" if row.confidence is None else f"{row.confidence:.2f}"
        role = _module_role(row.module)
        age = _snapshot_age_seconds(row, now)
        age_text = "N/A" if age is None else f"{int(age)}s"
        freshness = _freshness_status(row, now)
        lines.append(
            f"- [{role.get('display_name', row.module)} / {row.module} | {scope} | status={row.status} "
            f"| freshness={freshness} age={age_text} | direction={row.direction or 'neutral'} "
            f"| confidence={confidence} | risk={row.risk_level or 'unknown'}] {row.summary}"
        )
    return "\n".join(lines)


def get_context_variables_for_prompt(
    db: Session,
    *,
    account_id: Optional[int],
    exchange: str,
    symbols: Iterable[str],
    timeframe: str = DEFAULT_TIMEFRAME,
    allow_recompute: bool = False,
) -> Dict[str, str]:
    exchange = _normalize_exchange(exchange)
    symbol_list = normalize_symbols(exchange, symbols)

    rows = get_latest_context_snapshots(
        db,
        account_id=account_id,
        exchange=exchange,
        symbols=symbol_list,
        timeframe=timeframe,
    )
    supervisor = next((row for row in rows if row.module == MODULE_SUPERVISOR), None)
    is_stale = True
    if supervisor and supervisor.generated_at:
        is_stale = (_utcnow() - supervisor.generated_at).total_seconds() > PROMPT_CONTEXT_STALE_SECONDS

    if allow_recompute and (is_stale or not rows):
        try:
            enqueue_arena_ai_context_recompute(
                account_id=account_id,
                exchange=exchange,
                symbols=symbol_list,
                timeframe=timeframe,
            )
        except Exception as exc:
            logger.warning("Failed to enqueue Arena AI context recompute for prompt: %s", exc, exc_info=True)

    return {
        "arena_ai_context": _format_snapshots_for_prompt(rows),
        "kline_ai_context": _format_snapshots_for_prompt(rows, [MODULE_KLINE]),
        "kline_coverage_context": _format_snapshots_for_prompt(rows, [MODULE_KLINE_COVERAGE]),
        "insight_ai_context": _format_snapshots_for_prompt(rows, [MODULE_INSIGHT]),
        "market_ai_context": _format_snapshots_for_prompt(rows, [MODULE_MARKET]),
        "signal_ai_context": _format_snapshots_for_prompt(rows, [MODULE_SIGNAL]),
        "wallet_ai_context": _format_snapshots_for_prompt(rows, [MODULE_WALLET]),
        "backtest_ai_context": _format_snapshots_for_prompt(rows, [MODULE_BACKTEST]),
        "strategy_diagnostics_context": _format_snapshots_for_prompt(rows, [MODULE_STRATEGY_DIAGNOSTICS]),
        "attribution_ai_context": _format_snapshots_for_prompt(rows, [MODULE_ATTRIBUTION]),
        "trader_management_context": _format_snapshots_for_prompt(rows, [MODULE_TRADER]),
        "supervisor_ai_context": _format_snapshots_for_prompt(rows, [MODULE_SUPERVISOR]),
    }


def get_context_payload(
    db: Session,
    *,
    account_id: Optional[int] = None,
    exchange: str = "binance",
    symbols: Optional[Iterable[str]] = None,
    timeframe: str = DEFAULT_TIMEFRAME,
    recompute: bool = False,
) -> Dict[str, Any]:
    exchange = _normalize_exchange(exchange)
    symbol_list = normalize_symbols(exchange, symbols)
    recompute_status = "not_requested"
    if recompute:
        recompute_status = enqueue_arena_ai_context_recompute(
            account_id=account_id,
            exchange=exchange,
            symbols=symbol_list,
            timeframe=timeframe,
        )

    rows = get_latest_context_snapshots(
        db,
        account_id=account_id,
        exchange=exchange,
        symbols=symbol_list,
        timeframe=timeframe,
    )
    modules: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        modules.setdefault(row.module, []).append(_serialize_snapshot(row))

    return {
        "module_responsibilities": MODULE_RESPONSIBILITIES,
        "exchange": exchange,
        "symbols": symbol_list,
        "timeframe": timeframe,
        "account_id": account_id,
        "recompute_requested": recompute,
        "recompute_status": recompute_status,
        "generated_at": _utcnow().isoformat(),
        "modules": modules,
        "snapshots": [_serialize_snapshot(row) for row in rows],
        "prompt_context": _format_snapshots_for_prompt(rows),
    }


def recompute_default_arena_ai_context() -> None:
    """Scheduler entry point. Recomputes advisory context for active strategies."""
    from database.connection import SessionLocal

    with SessionLocal() as db:
        strategies = (
            db.query(AccountStrategyConfig)
            .filter(AccountStrategyConfig.enabled == "true")
            .order_by(AccountStrategyConfig.account_id)
            .limit(20)
            .all()
        )
        if not strategies:
            enqueue_arena_ai_context_recompute(
                account_id=None,
                exchange="binance",
                symbols=None,
                timeframe=DEFAULT_TIMEFRAME,
            )
            return

        for strategy in strategies:
            exchange = _normalize_exchange(strategy.exchange)
            try:
                enqueue_arena_ai_context_recompute(
                    account_id=strategy.account_id,
                    exchange=exchange,
                    symbols=None,
                    timeframe=DEFAULT_TIMEFRAME,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to enqueue Arena AI context recompute for account=%s exchange=%s: %s",
                    strategy.account_id,
                    exchange,
                    exc,
                    exc_info=True,
                )
