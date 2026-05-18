"""Binance K-line coverage worker for Arena sub-AI context.

The WebSocket collector keeps closed candles flowing. This worker runs a
bounded three-minute coverage check across the selected Binance symbols and
official intervals, then stores a compact status snapshot for Arena sub-AI.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import CryptoKline, SystemConfig
from services.exchanges.binance_adapter import BinanceAdapter
from services.exchanges.data_persistence import ExchangeDataPersistence
from services.market_flow_indicators import get_flow_indicators_for_prompt
from services.technical_indicators import calculate_indicators, get_required_kline_count

logger = logging.getLogger(__name__)

STATUS_CONFIG_KEY = "binance_kline_coverage_status"
CHECK_INTERVAL_SECONDS = 180
PERIODS = [
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "8h", "12h",
    "1d", "3d", "1w", "1M",
]
TECHNICAL_INDICATORS = [
    "MA5", "MA10", "EMA100", "VWAP", "OBV", "RSI14", "RSI7",
    "BOLL", "ATR14", "MA20", "EMA20", "EMA50", "STOCH", "MACD",
]
FLOW_INDICATORS = ["CVD", "FUNDING", "TAKER", "DEPTH", "OI_DELTA", "IMBALANCE"]
DEFAULT_MIN_KLINES = 100
DEFAULT_TARGET_KLINES = 180


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 10000) -> int:
    try:
        return max(minimum, min(maximum, int(os.getenv(name, str(default)))))
    except ValueError:
        return default


def _period_seconds(period: str) -> int:
    mapping = {
        "1m": 60,
        "3m": 180,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "2h": 7200,
        "4h": 14400,
        "8h": 28800,
        "12h": 43200,
        "1d": 86400,
        "3d": 259200,
        "1w": 604800,
        "1M": 2592000,
    }
    return mapping.get(period, 900)


def _decimal_to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _query_kline_stats(db: Session, symbol: str, period: str) -> Dict[str, Any]:
    count, latest_ts = (
        db.query(func.count(CryptoKline.id), func.max(CryptoKline.timestamp))
        .filter(
            CryptoKline.exchange == "binance",
            CryptoKline.symbol == symbol,
            CryptoKline.period == period,
            CryptoKline.environment == "mainnet",
        )
        .one()
    )
    now_ts = int(_utcnow().timestamp())
    latest_age_seconds = max(0, now_ts - int(latest_ts)) if latest_ts else None
    return {
        "count": int(count or 0),
        "latest_timestamp": int(latest_ts) if latest_ts else None,
        "latest_age_seconds": latest_age_seconds,
    }


def _query_local_klines(db: Session, symbol: str, period: str, limit: int) -> List[Dict[str, Any]]:
    rows = (
        db.query(CryptoKline)
        .filter(
            CryptoKline.exchange == "binance",
            CryptoKline.symbol == symbol,
            CryptoKline.period == period,
            CryptoKline.environment == "mainnet",
        )
        .order_by(desc(CryptoKline.timestamp))
        .limit(limit)
        .all()
    )
    result: List[Dict[str, Any]] = []
    for row in reversed(rows):
        close = _decimal_to_float(row.close_price)
        open_price = _decimal_to_float(row.open_price)
        high = _decimal_to_float(row.high_price)
        low = _decimal_to_float(row.low_price)
        if close is None or open_price is None or high is None or low is None:
            continue
        result.append(
            {
                "timestamp": int(row.timestamp),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": _decimal_to_float(row.volume) or 0.0,
            }
        )
    return result


def _has_indicator_values(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, list):
        return any(item is not None for item in value)
    if isinstance(value, dict):
        return any(_has_indicator_values(item) for item in value.values())
    return True


def _flow_status(flow_payload: Dict[str, Any]) -> Dict[str, Any]:
    statuses: Dict[str, str] = {}
    for indicator in FLOW_INDICATORS:
        item = flow_payload.get(indicator)
        if not item:
            statuses[indicator] = "missing"
        elif isinstance(item, dict) and item.get("status") == "partial":
            statuses[indicator] = "partial"
        else:
            statuses[indicator] = "ok"
    if any(status == "missing" for status in statuses.values()):
        status = "missing"
    elif any(status == "partial" for status in statuses.values()):
        status = "partial"
    else:
        status = "ok"
    return {"status": status, "indicators": statuses}


def _save_status(db: Session, payload: Dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
    row = db.query(SystemConfig).filter(SystemConfig.key == STATUS_CONFIG_KEY).first()
    if row:
        row.value = text
        if not row.description:
            row.description = "Latest Binance K-line coverage check for Arena sub-AI"
    else:
        row = SystemConfig(
            key=STATUS_CONFIG_KEY,
            value=text,
            description="Latest Binance K-line coverage check for Arena sub-AI",
        )
        db.add(row)
    db.commit()


def load_latest_binance_kline_coverage(db: Session) -> Dict[str, Any]:
    row = db.query(SystemConfig).filter(SystemConfig.key == STATUS_CONFIG_KEY).first()
    if not row or not row.value:
        return {}
    try:
        parsed = json.loads(row.value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def run_binance_kline_coverage_check(symbols: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Check and refresh Binance K-line coverage for Arena sub-AI."""
    from services.binance_symbol_service import get_selected_symbols

    max_symbols = _env_int("BINANCE_KLINE_COVERAGE_MAX_SYMBOLS", 20, minimum=1, maximum=200)
    request_budget = _env_int("BINANCE_KLINE_COVERAGE_MAX_REQUESTS", 240, minimum=1, maximum=300)
    min_klines = _env_int("BINANCE_KLINE_COVERAGE_MIN_KLINES", DEFAULT_MIN_KLINES, minimum=20, maximum=500)
    target_klines = _env_int("BINANCE_KLINE_COVERAGE_TARGET_KLINES", DEFAULT_TARGET_KLINES, minimum=50, maximum=500)
    selected_symbols = [str(item).upper() for item in (symbols or get_selected_symbols() or ["BTC"])][:max_symbols]
    required_klines = max(min_klines, get_required_kline_count(TECHNICAL_INDICATORS))
    adapter = BinanceAdapter(environment="mainnet")
    started_at = _utcnow()
    issues: List[str] = []
    request_count = 0
    refreshed_count = 0
    by_symbol: Dict[str, Any] = {}

    with SessionLocal() as db:
        persistence = ExchangeDataPersistence(db)
        for symbol in selected_symbols:
            period_status: Dict[str, Any] = {}
            for period in PERIODS:
                stats = _query_kline_stats(db, symbol, period)
                period_sec = _period_seconds(period)
                max_age = max(CHECK_INTERVAL_SECONDS + period_sec, period_sec * 2)
                stale = stats["latest_age_seconds"] is None or stats["latest_age_seconds"] > max_age
                sparse = stats["count"] < required_klines
                history_limited = period == "1M" and 50 <= stats["count"] < required_klines
                should_fetch = (stale or sparse) and not history_limited and request_count < request_budget

                if should_fetch:
                    limit = target_klines if sparse else 5
                    try:
                        klines = adapter.fetch_klines(symbol, period, limit=limit)
                        request_count += 1
                        if klines:
                            persistence.save_klines(klines, environment="mainnet")
                            if period == "1m":
                                persistence.save_taker_volumes_from_klines(klines)
                            refreshed_count += 1
                    except Exception as exc:
                        issues.append(f"{symbol}/{period}:fetch_failed:{str(exc)[:120]}")
                        logger.warning("[KLineCoverage] fetch failed for %s/%s: %s", symbol, period, exc)
                    stats = _query_kline_stats(db, symbol, period)
                    stale = stats["latest_age_seconds"] is None or stats["latest_age_seconds"] > max_age
                    sparse = stats["count"] < required_klines
                    history_limited = period == "1M" and 50 <= stats["count"] < required_klines

                klines = _query_local_klines(db, symbol, period, target_klines)
                indicator_payload = calculate_indicators(klines, TECHNICAL_INDICATORS)
                missing_indicators = [
                    indicator
                    for indicator in TECHNICAL_INDICATORS
                    if not _has_indicator_values(indicator_payload.get(indicator))
                ]
                flow_payload = get_flow_indicators_for_prompt(
                    db,
                    symbol,
                    period,
                    FLOW_INDICATORS,
                    exchange="binance",
                )
                flow = _flow_status(flow_payload)

                status = "ok"
                if stale or stats["count"] == 0 or flow["status"] == "missing":
                    status = "missing"
                elif missing_indicators or flow["status"] == "partial" or history_limited:
                    status = "partial"
                if status != "ok":
                    issues.append(
                        f"{symbol}/{period}:{status}:klines={stats['count']}:"
                        f"missing_indicators={','.join(missing_indicators) or '-'}:"
                        f"flow={flow['status']}"
                    )

                period_status[period] = {
                    "status": status,
                    "kline_count": stats["count"],
                    "latest_timestamp": stats["latest_timestamp"],
                    "latest_age_seconds": stats["latest_age_seconds"],
                    "max_acceptable_age_seconds": max_age,
                    "missing_indicators": missing_indicators,
                    "flow_status": flow["status"],
                    "flow_indicators": flow["indicators"],
                    "history_limited": history_limited,
                }
            by_symbol[symbol] = period_status

        total_periods = len(selected_symbols) * len(PERIODS)
        ok_count = sum(
            1
            for symbol_status in by_symbol.values()
            for item in symbol_status.values()
            if item.get("status") == "ok"
        )
        partial_count = sum(
            1
            for symbol_status in by_symbol.values()
            for item in symbol_status.values()
            if item.get("status") == "partial"
        )
        missing_count = total_periods - ok_count - partial_count
        payload = {
            "generated_at": started_at.isoformat(),
            "exchange": "binance",
            "symbols": selected_symbols,
            "periods": PERIODS,
            "technical_indicators": TECHNICAL_INDICATORS,
            "flow_indicators": FLOW_INDICATORS,
            "required_klines": required_klines,
            "target_klines": target_klines,
            "request_budget": request_budget,
            "requests_used": request_count,
            "refreshed_periods": refreshed_count,
            "summary": {
                "total_periods": total_periods,
                "ok": ok_count,
                "partial": partial_count,
                "missing": missing_count,
            },
            "issues": issues[:80],
            "by_symbol": by_symbol,
        }
        _save_status(db, payload)
        return payload
