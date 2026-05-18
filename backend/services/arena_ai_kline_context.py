"""K-Line Charts AI snapshot builder for Arena context."""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from database.models import KlineAIAnalysisLog, MarketAssetMetrics

logger = logging.getLogger(__name__)

MODULE_KLINE = "kline_ai"
KLINE_CHART_TECHNICAL_INDICATORS = [
    "MA5",
    "MA10",
    "MA20",
    "EMA20",
    "EMA50",
    "EMA100",
    "VWAP",
    "OBV",
    "RSI14",
    "RSI7",
    "STOCH",
    "MACD",
    "BOLL",
    "ATR14",
]
KLINE_CHART_FLOW_INDICATORS = ["CVD", "TAKER", "OI", "OI_DELTA", "FUNDING", "DEPTH", "IMBALANCE"]
KLINE_CHART_FLOW_QUERY_INDICATORS = [*KLINE_CHART_FLOW_INDICATORS, "PRICE_CHANGE"]


def _utcnow() -> datetime:
    return datetime.utcnow()


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


def _last_number(value: Any) -> Optional[float]:
    if isinstance(value, list):
        for item in reversed(value):
            number = _to_float(item)
            if number is not None:
                return number
        return None
    return _to_float(value)


def _short_text(value: Any, limit: int = 320) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


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
        return f"{sign}${abs_value / 1_000:.2f}K"
    return f"{sign}${abs_value:.2f}"


def _direction_from_score(score: float, dead_zone: float = 0.35) -> str:
    if score > dead_zone:
        return "bullish"
    if score < -dead_zone:
        return "bearish"
    return "neutral"


def _age_seconds_from_epoch_ms(value: Any, now_ms: int) -> Optional[float]:
    number = _to_float(value)
    if number is None:
        return None
    return max(0.0, (now_ms - number) / 1000.0)


def _get_latest_kline_ai_log(
    db: Session,
    account_id: Optional[int],
    symbol: str,
    timeframe: str,
) -> Optional[KlineAIAnalysisLog]:
    query = db.query(KlineAIAnalysisLog).filter(
        KlineAIAnalysisLog.symbol == symbol,
        KlineAIAnalysisLog.period == timeframe,
    )
    if account_id is not None:
        query = query.filter(KlineAIAnalysisLog.account_id == account_id)
    return query.order_by(desc(KlineAIAnalysisLog.created_at)).first()


def _latest_market_metrics(db: Session, exchange: str, symbol: str) -> Optional[MarketAssetMetrics]:
    return (
        db.query(MarketAssetMetrics)
        .filter(
            MarketAssetMetrics.exchange == exchange,
            MarketAssetMetrics.symbol == symbol,
        )
        .order_by(desc(MarketAssetMetrics.timestamp))
        .first()
    )


def _build_kline_page_market_data(
    db: Session,
    exchange: str,
    symbol: str,
    close: float,
) -> Dict[str, Any]:
    ticker: Dict[str, Any] = {}
    ticker_error: Optional[str] = None
    try:
        from services.market_data import get_ticker_data

        market_param = exchange if exchange in {"binance", "okx"} else "CRYPTO"
        ticker = get_ticker_data(symbol, market_param)
    except Exception as exc:
        ticker_error = _short_text(exc, 180)

    metrics = _latest_market_metrics(db, exchange, symbol)
    metrics_ts = metrics.timestamp if metrics else None
    now_ms = int(_utcnow().timestamp() * 1000)

    price = _to_float(ticker.get("price")) or _to_float(metrics.mark_price if metrics else None) or close
    oracle_price = _to_float(ticker.get("oracle_price")) or _to_float(metrics.oracle_price if metrics else None) or price
    open_interest = _to_float(ticker.get("open_interest")) or _to_float(metrics.open_interest if metrics else None)
    funding_rate = _to_float(ticker.get("funding_rate")) or _to_float(metrics.funding_rate if metrics else None)
    volume24h = _to_float(ticker.get("volume24h")) or _to_float(metrics.day_notional_volume if metrics else None)

    return {
        "symbol": symbol,
        "exchange": exchange,
        "price": price,
        "oracle_price": oracle_price,
        "change24h": _to_float(ticker.get("change24h")),
        "volume24h": volume24h,
        "percentage24h": _to_float(ticker.get("percentage24h")),
        "open_interest": open_interest,
        "funding_rate": funding_rate,
        "mark_price": _to_float(metrics.mark_price if metrics else None),
        "mid_price": _to_float(metrics.mid_price if metrics else None),
        "premium": _to_float(metrics.premium if metrics else None),
        "asset_metric_timestamp": metrics_ts,
        "asset_metric_age_seconds": _age_seconds_from_epoch_ms(metrics_ts, now_ms),
        "source": "live_ticker" if ticker else "asset_metrics_or_latest_close",
        "ticker_error": ticker_error,
    }


def _build_kline_page_flow_context(db: Session, exchange: str, symbol: str, timeframe: str) -> Dict[str, Any]:
    try:
        from services.market_flow_indicators import get_flow_indicators_for_prompt

        flow = get_flow_indicators_for_prompt(
            db,
            symbol,
            timeframe,
            KLINE_CHART_FLOW_QUERY_INDICATORS,
            exchange=exchange,
        )
    except Exception as exc:
        logger.warning("Failed to calculate K-Line Charts flow context for %s/%s: %s", symbol, timeframe, exc)
        flow = {}

    cvd = flow.get("CVD") or {}
    taker = flow.get("TAKER") or {}
    oi = flow.get("OI") or {}
    oi_delta = flow.get("OI_DELTA") or {}
    funding = flow.get("FUNDING") or {}
    depth = flow.get("DEPTH") or {}
    imbalance = flow.get("IMBALANCE") or {}
    price_change = flow.get("PRICE_CHANGE") or {}

    return {
        "indicator_set": KLINE_CHART_FLOW_INDICATORS,
        "query_indicator_set": KLINE_CHART_FLOW_QUERY_INDICATORS,
        "values": {
            "cvd_current": _to_float(cvd.get("current")),
            "cvd_cumulative": _to_float(cvd.get("cumulative")),
            "taker_buy": _to_float(taker.get("buy")),
            "taker_sell": _to_float(taker.get("sell")),
            "taker_ratio": _to_float(taker.get("ratio")),
            "oi_current": _to_float(oi.get("current")),
            "oi_absolute_current": _to_float(oi.get("absolute_current")),
            "oi_absolute_current_usd": _to_float(oi.get("absolute_current_usd")),
            "oi_status": oi.get("status"),
            "oi_delta_current": _to_float(oi_delta.get("current")),
            "oi_delta_status": oi_delta.get("status"),
            "funding_pct": _to_float(funding.get("current_pct")),
            "depth_ratio": _to_float(depth.get("ratio")),
            "order_imbalance": _to_float(imbalance.get("current")),
            "price_change_pct": _to_float(price_change.get("current")),
        },
        "raw": flow,
    }


def _build_indicator_latest_values(indicators: Dict[str, Any], close: float) -> Dict[str, Any]:
    macd_data = indicators.get("MACD") if isinstance(indicators.get("MACD"), dict) else {}
    boll_data = indicators.get("BOLL") if isinstance(indicators.get("BOLL"), dict) else {}
    stoch_data = indicators.get("STOCH") if isinstance(indicators.get("STOCH"), dict) else {}

    boll_upper = _last_number(boll_data.get("upper")) if isinstance(boll_data, dict) else None
    boll_middle = _last_number(boll_data.get("middle")) if isinstance(boll_data, dict) else None
    boll_lower = _last_number(boll_data.get("lower")) if isinstance(boll_data, dict) else None
    boll_position = None
    if boll_upper is not None and boll_lower is not None and boll_upper != boll_lower:
        boll_position = _clamp((close - boll_lower) / (boll_upper - boll_lower), 0.0, 1.0)

    return {
        "ma5": _last_number(indicators.get("MA5")),
        "ma10": _last_number(indicators.get("MA10")),
        "ma20": _last_number(indicators.get("MA20")),
        "ema20": _last_number(indicators.get("EMA20")),
        "ema50": _last_number(indicators.get("EMA50")),
        "ema100": _last_number(indicators.get("EMA100")),
        "vwap": _last_number(indicators.get("VWAP")),
        "obv": _last_number(indicators.get("OBV")),
        "rsi14": _last_number(indicators.get("RSI14")),
        "rsi7": _last_number(indicators.get("RSI7")),
        "stoch_k": _last_number(stoch_data.get("k")) if isinstance(stoch_data, dict) else None,
        "stoch_d": _last_number(stoch_data.get("d")) if isinstance(stoch_data, dict) else None,
        "macd": _last_number(macd_data.get("macd")) if isinstance(macd_data, dict) else None,
        "macd_signal": _last_number(macd_data.get("signal")) if isinstance(macd_data, dict) else None,
        "macd_hist": _last_number(macd_data.get("histogram")) if isinstance(macd_data, dict) else None,
        "boll_upper": boll_upper,
        "boll_middle": boll_middle,
        "boll_lower": boll_lower,
        "boll_position": boll_position,
        "atr14": _last_number(indicators.get("ATR14")),
    }


def build_kline_snapshot(
    db: Session,
    account_id: Optional[int],
    exchange: str,
    symbol: str,
    timeframe: str,
) -> Dict[str, Any]:
    from services.kline_autofill import ensure_indicator_klines
    from services.technical_indicators import calculate_indicators, get_required_kline_count

    required_count = get_required_kline_count(KLINE_CHART_TECHNICAL_INDICATORS)
    kline_data, source_exchange, auto_fetched = ensure_indicator_klines(
        db=db,
        symbol=symbol,
        period=timeframe,
        indicators=KLINE_CHART_TECHNICAL_INDICATORS,
        exchange=exchange,
        environment="mainnet",
        min_count=required_count,
        limit=180,
    )

    if not kline_data:
        return {
            "module": MODULE_KLINE,
            "status": "missing",
            "summary": f"{symbol}/{timeframe}: no local K-line history available for {exchange}.",
            "direction": "neutral",
            "confidence": 0.0,
            "risk_level": "unknown",
            "raw_payload": {"records": 0, "source_exchange": source_exchange, "auto_fetched": auto_fetched},
        }

    if len(kline_data) < 5:
        return {
            "module": MODULE_KLINE,
            "status": "partial",
            "summary": f"{symbol}/{timeframe}: K-line data exists but is too sparse ({len(kline_data)} candles).",
            "direction": "neutral",
            "confidence": 0.1,
            "risk_level": "unknown",
            "raw_payload": {
                "records": len(kline_data),
                "source_exchange": source_exchange,
                "auto_fetched": auto_fetched,
            },
        }

    try:
        indicators = calculate_indicators(kline_data, KLINE_CHART_TECHNICAL_INDICATORS)
    except Exception as exc:
        logger.warning("Failed to calculate K-line indicators for %s/%s: %s", symbol, timeframe, exc)
        indicators = {}

    latest = kline_data[-1]
    previous = kline_data[-2] if len(kline_data) >= 2 else latest
    close = latest["close"]
    prev_close = previous["close"]
    price_change_pct = ((close - prev_close) / prev_close * 100) if prev_close else 0.0

    indicator_values = _build_indicator_latest_values(indicators, close)
    market_data = _build_kline_page_market_data(db, exchange, symbol, close)
    flow_context = _build_kline_page_flow_context(db, exchange, symbol, timeframe)
    flow_values = flow_context.get("values") or {}

    ma5 = indicator_values.get("ma5")
    ma10 = indicator_values.get("ma10")
    ma20 = indicator_values.get("ma20")
    ema20 = indicator_values.get("ema20")
    ema50 = indicator_values.get("ema50")
    ema100 = indicator_values.get("ema100")
    rsi14 = indicator_values.get("rsi14")
    rsi7 = indicator_values.get("rsi7")
    stoch_k = indicator_values.get("stoch_k")
    atr14 = indicator_values.get("atr14")
    vwap = indicator_values.get("vwap")
    obv = indicator_values.get("obv")
    macd_hist = indicator_values.get("macd_hist")
    boll_position = indicator_values.get("boll_position")
    taker_ratio = _to_float(flow_values.get("taker_ratio"))
    cvd_current = _to_float(flow_values.get("cvd_current"))
    oi_delta_current = _to_float(flow_values.get("oi_delta_current"))
    depth_ratio = _to_float(flow_values.get("depth_ratio"))
    imbalance_current = _to_float(flow_values.get("order_imbalance"))
    funding_pct = _to_float(flow_values.get("funding_pct"))

    score = 0.0
    if ema20 is not None:
        score += 0.8 if close > ema20 else -0.8
    if ema20 is not None and ema50 is not None:
        score += 0.7 if ema20 > ema50 else -0.7
    if ma20 is not None:
        score += 0.4 if close > ma20 else -0.4
    if vwap is not None:
        score += 0.35 if close > vwap else -0.35
    if rsi14 is not None:
        if rsi14 >= 60:
            score += 0.45
        elif rsi14 <= 40:
            score -= 0.45
    if macd_hist is not None:
        score += 0.5 if macd_hist > 0 else -0.5
    if rsi7 is not None:
        if rsi7 >= 60:
            score += 0.2
        elif rsi7 <= 40:
            score -= 0.2
    if stoch_k is not None:
        if stoch_k >= 80:
            score += 0.15
        elif stoch_k <= 20:
            score -= 0.15
    if boll_position is not None:
        if boll_position >= 0.8:
            score += 0.15
        elif boll_position <= 0.2:
            score -= 0.15
    if cvd_current is not None:
        score += 0.25 if cvd_current > 0 else -0.25
    if taker_ratio is not None:
        if taker_ratio > 1.1:
            score += 0.25
        elif taker_ratio < 0.9:
            score -= 0.25
    if depth_ratio is not None:
        if depth_ratio > 1.05:
            score += 0.12
        elif depth_ratio < 0.95:
            score -= 0.12
    if imbalance_current is not None:
        if imbalance_current > 0.08:
            score += 0.18
        elif imbalance_current < -0.08:
            score -= 0.18
    if abs(price_change_pct) >= 0.05:
        score += 0.25 if price_change_pct > 0 else -0.25

    direction = _direction_from_score(score)
    confidence = _clamp(0.34 + abs(score) * 0.105, 0.0, 0.92)
    atr_pct = (atr14 / close * 100) if atr14 and close else 0.0
    risk_level = "low"
    if (
        (rsi14 is not None and (rsi14 >= 72 or rsi14 <= 28))
        or abs(price_change_pct) >= 2.5
        or atr_pct >= 3.0
        or abs(funding_pct or 0.0) >= 0.08
        or abs(oi_delta_current or 0.0) >= 5.0
        or abs(imbalance_current or 0.0) >= 0.35
    ):
        risk_level = "high"
    elif (
        (rsi14 is not None and (rsi14 >= 65 or rsi14 <= 35))
        or abs(price_change_pct) >= 1.0
        or atr_pct >= 1.5
        or abs(funding_pct or 0.0) >= 0.03
        or abs(oi_delta_current or 0.0) >= 1.5
        or abs(imbalance_current or 0.0) >= 0.18
    ):
        risk_level = "medium"

    latest_ai = _get_latest_kline_ai_log(db, account_id, symbol, timeframe)
    latest_ai_excerpt = _short_text(latest_ai.analysis_result, 220) if latest_ai else ""
    summary = (
        f"K-Line Charts AI {symbol}/{timeframe}: {direction}, close={close:.4f}, "
        f"page_price={_format_number(_to_float(market_data.get('price')), 4)}, "
        f"24h={_format_number(_to_float(market_data.get('percentage24h')), 2)}%, "
        f"OI={_format_usd(_to_float(market_data.get('open_interest')))}, "
        f"funding={_format_number((_to_float(market_data.get('funding_rate')) or 0.0) * 100, 4)}%, "
        f"bar_change={price_change_pct:+.2f}%, MA5/10/20="
        f"{_format_number(ma5, 4)}/{_format_number(ma10, 4)}/{_format_number(ma20, 4)}, "
        f"EMA20/50/100={_format_number(ema20, 4)}/{_format_number(ema50, 4)}/{_format_number(ema100, 4)}, "
        f"RSI14/7={_format_number(rsi14, 1)}/{_format_number(rsi7, 1)}, "
        f"STOCH_K={_format_number(stoch_k, 1)}, MACD_hist={_format_number(macd_hist, 4)}, "
        f"BOLL_pos={_format_number(boll_position, 2)}, ATR%={atr_pct:.2f}, "
        f"CVD={_format_usd(cvd_current)}, taker_ratio={_format_number(taker_ratio, 2)}, "
        f"OI_delta={_format_number(oi_delta_current, 3)}%, depth={_format_number(depth_ratio, 2)}, "
        f"imbalance={_format_number(imbalance_current, 3)}. "
        f"Advisory confidence={confidence:.2f}, risk={risk_level}."
    )
    if latest_ai_excerpt:
        summary += f" Latest chart AI note: {latest_ai_excerpt}"

    return {
        "module": MODULE_KLINE,
        "status": "ok" if len(kline_data) >= 30 else "partial",
        "summary": summary,
        "direction": direction,
        "confidence": confidence,
        "risk_level": risk_level,
        "raw_payload": {
            "records": len(kline_data),
            "source_page": "K-Line Charts",
            "auto_worker": True,
            "requested_exchange": exchange,
            "source_exchange": source_exchange,
            "auto_fetched": auto_fetched,
            "technical_indicator_set": KLINE_CHART_TECHNICAL_INDICATORS,
            "flow_indicator_set": KLINE_CHART_FLOW_INDICATORS,
            "latest_timestamp": latest.get("timestamp"),
            "close": close,
            "price_change_pct": price_change_pct,
            "market_data": market_data,
            "indicator_values": indicator_values,
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "ema20": ema20,
            "ema50": ema50,
            "ema100": ema100,
            "rsi14": rsi14,
            "rsi7": rsi7,
            "stoch_k": stoch_k,
            "macd_hist": macd_hist,
            "boll_position": boll_position,
            "atr14": atr14,
            "atr_pct": atr_pct,
            "vwap": vwap,
            "obv": obv,
            "flow_values": flow_values,
            "flow_context": flow_context,
            "latest_ai_log_id": latest_ai.id if latest_ai else None,
        },
    }
