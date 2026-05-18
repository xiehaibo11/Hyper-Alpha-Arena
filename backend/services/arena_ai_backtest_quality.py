"""Backtest data-quality self-checks for Arena context."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import (
    AIDecisionLog,
    CryptoKline,
    MarketAssetMetrics,
    MarketOrderbookSnapshots,
    MarketTradesAggregated,
    ProgramExecutionLog,
    SignalPool,
    SignalTriggerLog,
)

DEFAULT_TIMEFRAME = "15m"


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


def _pool_symbols_match(pool: SignalPool, symbol: str) -> bool:
    symbols = _parse_json_text(pool.symbols, [])
    if not symbols:
        return True
    return symbol.upper() in {str(item).upper() for item in symbols}


def build_backtest_data_quality(
    db: Session,
    account_id: Optional[int],
    exchange: str,
    symbols: List[str],
    timeframe: str,
) -> Dict[str, Any]:
    now = _utcnow()
    now_ms = int(now.timestamp() * 1000)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    day_ago_ms = now_ms - 24 * 3600 * 1000
    timeframe_sec = _timeframe_seconds(timeframe)
    max_kline_age = max(timeframe_sec * 3, 900)
    max_flow_age = 300

    symbol_quality: Dict[str, Dict[str, Any]] = {}
    kline_ready_count = 0
    flow_ready_count = 0
    total_signal_pools = 0
    total_live_triggers_24h = 0
    warnings: List[str] = []

    for symbol in symbols:
        kline_count, oldest_kline_ts, latest_kline_ts = (
            db.query(
                func.count(CryptoKline.id),
                func.min(CryptoKline.timestamp),
                func.max(CryptoKline.timestamp),
            )
            .filter(
                CryptoKline.exchange == exchange,
                CryptoKline.symbol == symbol,
                CryptoKline.period == timeframe,
                CryptoKline.environment == "mainnet",
            )
            .one()
        )
        kline_count = int(kline_count or 0)
        kline_age_seconds = _age_seconds_from_epoch_s(latest_kline_ts, now)
        kline_ready = kline_count >= 120 and (
            kline_age_seconds is not None and kline_age_seconds <= max_kline_age
        )
        if kline_ready:
            kline_ready_count += 1
        elif kline_count == 0:
            warnings.append(f"{symbol}:no_kline_history")
        else:
            warnings.append(f"{symbol}:kline_sparse_or_stale")

        def flow_stats(model):
            count, latest_ts = (
                db.query(func.count(model.id), func.max(model.timestamp))
                .filter(
                    model.exchange == exchange,
                    model.symbol == symbol,
                    model.timestamp >= day_ago_ms,
                )
                .one()
            )
            return int(count or 0), latest_ts, _age_seconds_from_epoch_ms(latest_ts, now_ms)

        trades_count, latest_trade_ts, trade_age = flow_stats(MarketTradesAggregated)
        orderbook_count, latest_orderbook_ts, orderbook_age = flow_stats(MarketOrderbookSnapshots)
        asset_count, latest_asset_ts, asset_age = flow_stats(MarketAssetMetrics)
        flow_ready = all(
            [
                trades_count >= 20,
                orderbook_count >= 20,
                asset_count >= 10,
                trade_age is not None and trade_age <= max_flow_age,
                orderbook_age is not None and orderbook_age <= max_flow_age,
                asset_age is not None and asset_age <= max_flow_age,
            ]
        )
        if flow_ready:
            flow_ready_count += 1
        else:
            warnings.append(f"{symbol}:flow_sparse_or_stale")

        pools = (
            db.query(SignalPool)
            .filter(
                SignalPool.exchange == exchange,
                SignalPool.enabled == True,  # noqa: E712
                SignalPool.is_deleted != True,  # noqa: E712
                SignalPool.source_type == "market_signals",
            )
            .all()
        )
        matching_pools = [pool for pool in pools if _pool_symbols_match(pool, symbol)]
        pool_ids = [pool.id for pool in matching_pools]
        live_trigger_count = 0
        latest_live_trigger = None
        if pool_ids:
            live_trigger_count, latest_live_trigger = (
                db.query(func.count(SignalTriggerLog.id), func.max(SignalTriggerLog.triggered_at))
                .filter(
                    SignalTriggerLog.pool_id.in_(pool_ids),
                    SignalTriggerLog.symbol == symbol,
                    SignalTriggerLog.triggered_at >= day_ago,
                )
                .one()
            )
            live_trigger_count = int(live_trigger_count or 0)
        if not matching_pools:
            warnings.append(f"{symbol}:no_signal_pool")
        total_signal_pools += len(matching_pools)
        total_live_triggers_24h += int(live_trigger_count or 0)

        symbol_quality[symbol] = {
            "kline": {
                "ready": kline_ready,
                "count": kline_count,
                "oldest_timestamp": oldest_kline_ts,
                "latest_timestamp": latest_kline_ts,
                "latest_age_seconds": kline_age_seconds,
                "required_candles": 120,
                "max_acceptable_age_seconds": max_kline_age,
            },
            "market_flow": {
                "ready": flow_ready,
                "trades_count_24h": trades_count,
                "orderbook_count_24h": orderbook_count,
                "asset_metric_count_24h": asset_count,
                "latest_trade_timestamp": latest_trade_ts,
                "latest_orderbook_timestamp": latest_orderbook_ts,
                "latest_asset_metric_timestamp": latest_asset_ts,
                "latest_trade_age_seconds": trade_age,
                "latest_orderbook_age_seconds": orderbook_age,
                "latest_asset_metric_age_seconds": asset_age,
                "max_acceptable_age_seconds": max_flow_age,
            },
            "signals": {
                "enabled_pool_count": len(matching_pools),
                "pool_ids": pool_ids,
                "live_trigger_count_24h": live_trigger_count,
                "latest_live_trigger_at": latest_live_trigger.isoformat() if latest_live_trigger else None,
            },
        }

    decision_query = db.query(AIDecisionLog).filter(AIDecisionLog.created_at >= week_ago)
    program_query = db.query(ProgramExecutionLog).filter(ProgramExecutionLog.created_at >= week_ago)
    if account_id is not None:
        decision_query = decision_query.filter(AIDecisionLog.account_id == account_id)
        program_query = program_query.filter(ProgramExecutionLog.account_id == account_id)
    if exchange:
        decision_query = decision_query.filter((AIDecisionLog.exchange == exchange) | (AIDecisionLog.exchange.is_(None)))
        program_query = program_query.filter((ProgramExecutionLog.exchange == exchange) | (ProgramExecutionLog.exchange.is_(None)))

    decision_count_7d = int(decision_query.count() or 0)
    executed_decision_count_7d = int(decision_query.filter(AIDecisionLog.executed == "true").count() or 0)
    decision_with_pnl_count_7d = int(
        decision_query
        .filter(AIDecisionLog.realized_pnl.isnot(None))
        .filter(AIDecisionLog.realized_pnl != 0)
        .count()
        or 0
    )
    program_count_7d = int(program_query.count() or 0)
    program_with_pnl_count_7d = int(
        program_query
        .filter(ProgramExecutionLog.realized_pnl.isnot(None))
        .filter(ProgramExecutionLog.realized_pnl != 0)
        .count()
        or 0
    )
    closed_outcome_count_7d = decision_with_pnl_count_7d + program_with_pnl_count_7d

    if closed_outcome_count_7d == 0 and (executed_decision_count_7d or program_count_7d):
        warnings.append("no_closed_trade_outcomes")

    kline_coverage_status = "ok" if kline_ready_count == len(symbols) else "partial" if kline_ready_count else "missing"
    flow_freshness_status = "ok" if flow_ready_count == len(symbols) else "partial" if flow_ready_count else "missing"
    outcome_status = "ok" if closed_outcome_count_7d >= 10 else "partial" if closed_outcome_count_7d else "missing"
    backtest_readiness = (
        "ready_for_backtest"
        if kline_ready_count == len(symbols) and flow_ready_count == len(symbols) and total_signal_pools > 0
        else "not_ready"
    )

    return {
        "account_id": account_id,
        "exchange": exchange,
        "symbols": symbols,
        "timeframe": timeframe,
        "backtest_readiness": backtest_readiness,
        "kline_ready_count": kline_ready_count,
        "flow_ready_count": flow_ready_count,
        "symbol_count": len(symbols),
        "signal_pool_count": total_signal_pools,
        "live_trigger_count_24h": total_live_triggers_24h,
        "decision_count_7d": decision_count_7d,
        "executed_decision_count_7d": executed_decision_count_7d,
        "program_execution_count_7d": program_count_7d,
        "closed_outcome_count_7d": closed_outcome_count_7d,
        "accuracy_self_check": {
            "kline_coverage": kline_coverage_status,
            "market_flow_freshness": flow_freshness_status,
            "signal_sample": "ok" if total_live_triggers_24h > 0 else "missing",
            "closed_trade_outcomes": outcome_status,
            "performance_accuracy": "insufficient_closed_trades" if closed_outcome_count_7d < 10 else "usable",
        },
        "warnings": sorted(set(warnings)),
        "by_symbol": symbol_quality,
    }
