"""
Shared factor resolver for builtin registry factors and custom expression factors.

This module centralizes factor lookup and computation so Prompt, Program,
Signal Detection, and backtest paths stay aligned.
"""

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from database.models import CustomFactor
from services.factor_registry import FACTOR_BY_NAME
from services.factor_expression_engine import factor_expression_engine
from services.technical_indicators import calculate_indicators


def resolve_factor_definition(db: Session, factor_name: str) -> Optional[Dict[str, Any]]:
    """Resolve a factor by name from builtin registry first, then custom_factors."""
    builtin = FACTOR_BY_NAME.get(factor_name)
    if builtin:
        return {
            **builtin,
            "id": None,
            "source": "builtin_registry",
            "expression": builtin.get("expression"),
        }

    custom = db.query(CustomFactor).filter(
        CustomFactor.name == factor_name,
        CustomFactor.is_active == True,
    ).first()
    if not custom:
        return None

    return {
        "name": custom.name,
        "id": custom.id,
        "category": custom.category,
        "description": custom.description or "",
        "expression": custom.expression,
        "source": custom.source or "custom",
        "compute_type": "expression",
    }


def compute_factor_series(
    db: Session,
    factor_name: str,
    symbol: str,
    period: str,
    exchange: str,
    klines: List[Dict[str, Any]],
) -> Tuple[Optional[pd.Series], Optional[Dict[str, Any]], Optional[str]]:
    """
    Compute a full factor series for builtin registry factors or custom factors.

    Returns:
        (series, factor_meta, error)
    """
    factor = resolve_factor_definition(db, factor_name)
    if not factor:
        return None, None, f"Factor '{factor_name}' not found"

    if factor.get("source") == "builtin_registry":
        if factor.get("compute_type") == "microstructure":
            values = _compute_microstructure_series(
                db, factor, symbol, period, exchange, klines,
            )
            if values is None:
                return None, factor, f"Factor '{factor_name}' could not be computed"
            return pd.Series(values), factor, None

        indicators: Dict[str, Any] = {}
        if factor.get("compute_type") == "technical":
            indicator_key = factor.get("indicator_key")
            if indicator_key:
                indicators = calculate_indicators(klines, [indicator_key])

        from services.factor_effectiveness_service import factor_effectiveness_service
        values = factor_effectiveness_service._extract_full_series(
            factor,
            indicators,
            klines,
            len(klines),
            db=db,
            symbol=symbol,
            exchange=exchange,
        )
        if values is None:
            return None, factor, f"Factor '{factor_name}' could not be computed"
        return pd.Series(values), factor, None

    series, err = factor_expression_engine.execute(factor["expression"], klines)
    if series is None or len(series) == 0:
        return None, factor, err or f"Factor '{factor_name}' could not be computed"
    return series, factor, None


def compute_factor_value(
    db: Session,
    factor_name: str,
    symbol: str,
    period: str,
    exchange: str,
    klines: List[Dict[str, Any]],
) -> Tuple[Optional[float], Optional[Dict[str, Any]], Optional[str]]:
    """Compute the latest factor value and return (value, factor_meta, error)."""
    series, factor, err = compute_factor_series(
        db=db,
        factor_name=factor_name,
        symbol=symbol,
        period=period,
        exchange=exchange,
        klines=klines,
    )
    if series is None:
        return None, factor, err

    last_val = series.iloc[-1]
    if pd.isna(last_val):
        return None, factor, None
    return round(float(last_val), 6), factor, None


def extract_factor_expression(factor: Dict[str, Any]) -> str:
    """Return a human-readable factor expression/label for mixed factor sources."""
    if factor.get("expression"):
        return str(factor["expression"])

    if factor.get("source") == "builtin_registry":
        return str(factor.get("display_name") or factor.get("name") or "")

    return str(factor.get("name") or "")


def _timestamp_ms(kline: Dict[str, Any]) -> int:
    ts = int(kline.get("timestamp") or 0)
    return ts if ts >= 1_000_000_000_000 else ts * 1000


def _period_ms(period: str) -> Optional[int]:
    from services.market_flow_indicators import TIMEFRAME_MS
    return TIMEFRAME_MS.get(period)


def _compute_microstructure_series(
    db: Session,
    factor: Dict[str, Any],
    symbol: str,
    period: str,
    exchange: str,
    klines: List[Dict[str, Any]],
) -> Optional[List[Optional[float]]]:
    if not klines:
        return None
    interval_ms = _period_ms(period)
    if not interval_ms:
        return None

    name = factor.get("name")
    ts_list = [_timestamp_ms(k) for k in klines]
    tmin = min(ts_list)
    tmax = max(ts_list) + interval_ms

    if name in {"CVD_RATIO", "TAKER_BUY_RATIO"}:
        rows = db.execute(text("""
            SELECT timestamp, taker_buy_notional, taker_sell_notional
            FROM market_trades_aggregated
            WHERE symbol = :symbol AND exchange = :exchange
              AND timestamp >= :tmin AND timestamp < :tmax
            ORDER BY timestamp ASC
        """), {
            "symbol": symbol.upper(),
            "exchange": exchange.lower(),
            "tmin": tmin,
            "tmax": tmax,
        }).fetchall()
        if not rows:
            return None
        return _align_taker_factor(rows, ts_list, interval_ms, name)

    if name == "FUNDING_RATE":
        rows = db.execute(text("""
            SELECT timestamp, funding_rate
            FROM market_asset_metrics
            WHERE symbol = :symbol AND exchange = :exchange
              AND funding_rate IS NOT NULL
              AND timestamp >= :tmin AND timestamp < :tmax
            ORDER BY timestamp ASC
        """), {
            "symbol": symbol.upper(),
            "exchange": exchange.lower(),
            "tmin": tmin,
            "tmax": tmax,
        }).fetchall()
        if not rows:
            return None
        return _align_average(rows, ts_list, interval_ms, multiplier=1_000_000)

    if name == "OI_CHANGE_PCT":
        rows = db.execute(text("""
            SELECT timestamp, open_interest
            FROM market_asset_metrics
            WHERE symbol = :symbol AND exchange = :exchange
              AND open_interest IS NOT NULL
              AND timestamp >= :tmin AND timestamp < :tmax
            ORDER BY timestamp ASC
        """), {
            "symbol": symbol.upper(),
            "exchange": exchange.lower(),
            "tmin": tmin,
            "tmax": tmax,
        }).fetchall()
        if not rows:
            return None
        return _align_delta_pct(rows, ts_list, interval_ms)

    if name == "DEPTH_RATIO":
        rows = db.execute(text("""
            SELECT timestamp, bid_depth_5, ask_depth_5
            FROM market_orderbook_snapshots
            WHERE symbol = :symbol AND exchange = :exchange
              AND timestamp >= :tmin AND timestamp < :tmax
            ORDER BY timestamp ASC
        """), {
            "symbol": symbol.upper(),
            "exchange": exchange.lower(),
            "tmin": tmin,
            "tmax": tmax,
        }).fetchall()
        if not rows:
            return None
        return _align_depth(rows, ts_list, interval_ms)

    return None


def _align_taker_factor(rows, ts_list, interval_ms, name):
    result = []
    row_idx = 0
    for ts in ts_list:
        while row_idx < len(rows) and rows[row_idx][0] < ts:
            row_idx += 1
        buy = 0.0
        sell = 0.0
        j = row_idx
        while j < len(rows) and rows[j][0] < ts + interval_ms:
            buy += float(rows[j][1] or 0)
            sell += float(rows[j][2] or 0)
            j += 1
        total = buy + sell
        if total <= 0:
            result.append(None)
        elif name == "CVD_RATIO":
            result.append((buy - sell) / total)
        else:
            result.append(buy / total)
    return result


def _align_average(rows, ts_list, interval_ms, multiplier=1.0):
    result = []
    row_idx = 0
    for ts in ts_list:
        while row_idx < len(rows) and rows[row_idx][0] < ts:
            row_idx += 1
        vals = []
        j = row_idx
        while j < len(rows) and rows[j][0] < ts + interval_ms:
            if rows[j][1] is not None:
                vals.append(float(rows[j][1]) * multiplier)
            j += 1
        result.append(sum(vals) / len(vals) if vals else None)
    return result


def _align_delta_pct(rows, ts_list, interval_ms):
    result = []
    row_idx = 0
    for ts in ts_list:
        while row_idx < len(rows) and rows[row_idx][0] < ts:
            row_idx += 1
        start_val = None
        end_val = None
        j = row_idx
        while j < len(rows) and rows[j][0] < ts + interval_ms:
            if rows[j][1] is not None:
                value = float(rows[j][1])
                if start_val is None:
                    start_val = value
                end_val = value
            j += 1
        if start_val and end_val and start_val != 0:
            result.append((end_val - start_val) / start_val * 100)
        else:
            result.append(None)
    return result


def _align_depth(rows, ts_list, interval_ms):
    result = []
    row_idx = 0
    for ts in ts_list:
        while row_idx < len(rows) and rows[row_idx][0] < ts:
            row_idx += 1
        ratios = []
        j = row_idx
        while j < len(rows) and rows[j][0] < ts + interval_ms:
            bid = float(rows[j][1] or 0)
            ask = float(rows[j][2] or 0)
            if ask > 0:
                ratios.append(bid / ask)
            j += 1
        result.append(sum(ratios) / len(ratios) if ratios else None)
    return result
