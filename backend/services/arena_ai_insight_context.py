"""Dashboard Insight context builder for Arena AI."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from database.models import CryptoKline

logger = logging.getLogger(__name__)

DEFAULT_TIMEFRAME = "15m"
MODULE_INSIGHT = "insight_ai"


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


def _datetime_to_epoch_ms(value: Any) -> Optional[int]:
    if value is None:
        return None
    number = _to_float(value)
    if number is not None:
        return int(number * 1000) if number < 10_000_000_000 else int(number)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    except ValueError:
        return None


def _sentiment_score(value: Any) -> int:
    text = str(value or "").strip().lower()
    if text in {"bullish", "positive", "buy", "long"}:
        return 1
    if text in {"bearish", "negative", "sell", "short"}:
        return -1
    if any(term in text for term in ["bull", "positive", "利好", "看涨", "做多"]):
        return 1
    if any(term in text for term in ["bear", "negative", "利空", "看跌", "做空"]):
        return -1
    return 0


def _load_insight_chart_context(
    db: Session,
    exchange: str,
    symbol: str,
    timeframe: str,
    start_time_ms: Optional[int],
) -> List[Dict[str, Any]]:
    base_query = db.query(CryptoKline).filter(
        CryptoKline.exchange == exchange,
        CryptoKline.symbol == symbol,
        CryptoKline.period == timeframe,
        CryptoKline.environment == "mainnet",
    )
    rows: List[CryptoKline] = []
    if start_time_ms:
        rows = (
            base_query
            .filter(CryptoKline.timestamp >= int(start_time_ms / 1000))
            .order_by(CryptoKline.timestamp.asc())
            .limit(520)
            .all()
        )
    if not rows:
        rows = list(
            reversed(
                base_query
                .order_by(desc(CryptoKline.timestamp))
                .limit(200)
                .all()
            )
        )

    chart: List[Dict[str, Any]] = []
    for row in rows:
        close = _to_float(row.close_price)
        if close is None:
            continue
        chart.append(
            {
                "time": row.timestamp,
                "open": _to_float(row.open_price),
                "high": _to_float(row.high_price),
                "low": _to_float(row.low_price),
                "close": close,
                "volume": _to_float(row.volume),
            }
        )
    return chart


def _build_insight_event_context(
    news_items: List[Dict[str, Any]],
    zone_items: List[Dict[str, Any]],
    exchange: str,
    symbol: str,
    timeframe: str,
) -> Dict[str, Any]:
    events: List[Dict[str, Any]] = []
    for item in news_items[:20]:
        event_time = _datetime_to_epoch_ms(item.get("published_at"))
        sentiment = str(item.get("sentiment") or "mixed").lower()
        tone = sentiment if sentiment in {"bullish", "bearish"} else "mixed"
        events.append(
            {
                "id": f"news-{item.get('id')}",
                "kind": "news",
                "time": event_time,
                "title": _short_text(item.get("title"), 160),
                "summary": _short_text(item.get("ai_summary") or item.get("summary"), 220),
                "tone": tone,
                "evidence": [
                    str(item.get("source_domain") or "unknown"),
                    ",".join(str(symbol_item) for symbol_item in (item.get("symbols") or [])[:4]),
                    sentiment,
                ],
            }
        )

    strongest_zones = sorted(
        zone_items,
        key=lambda zone: abs(_to_float(zone.get("large_order_net")) or 0.0),
        reverse=True,
    )
    top_flow_zones: List[Dict[str, Any]] = []
    for zone in strongest_zones[:8]:
        net = _to_float(zone.get("large_order_net")) or 0.0
        compact_zone = {
            "time": zone.get("time"),
            "large_buy_notional": _to_float(zone.get("large_buy_notional")) or 0.0,
            "large_sell_notional": _to_float(zone.get("large_sell_notional")) or 0.0,
            "large_order_net": net,
            "large_buy_count": int(zone.get("large_buy_count") or 0),
            "large_sell_count": int(zone.get("large_sell_count") or 0),
        }
        top_flow_zones.append(compact_zone)
        if abs(net) < 100_000:
            continue
        tone = "bullish" if net > 0 else "bearish"
        events.append(
            {
                "id": f"flow-{zone.get('time')}-{'up' if net >= 0 else 'down'}",
                "kind": "flow",
                "time": _datetime_to_epoch_ms(zone.get("time")),
                "title": "Large buy flow expanded" if net >= 0 else "Large sell flow expanded",
                "summary": (
                    f"{exchange} {symbol} {timeframe} large net {_format_usd(net)}, "
                    f"buy/sell count {compact_zone['large_buy_count']}/{compact_zone['large_sell_count']}."
                ),
                "tone": tone,
                "evidence": [
                    f"large_net={_format_usd(net)}",
                    f"buy_sell_count={compact_zone['large_buy_count']}/{compact_zone['large_sell_count']}",
                ],
            }
        )

    events.sort(key=lambda event: int(event.get("time") or 0), reverse=True)
    return {
        "selected_event": events[0] if events else None,
        "events": events[:8],
        "top_flow_zones": top_flow_zones[:5],
    }


def build_insight_snapshot(db: Session, exchange: str, symbol: str, timeframe: str) -> Dict[str, Any]:
    try:
        from api.market_flow_routes import TIMEFRAME_MS
        from api.market_intelligence_routes import _load_snapshot

        insight_timeframe = timeframe if timeframe in TIMEFRAME_MS else DEFAULT_TIMEFRAME
        snapshot = _load_snapshot(
            db=db,
            symbol=symbol,
            exchange=exchange,
            timeframe=insight_timeframe,
            window="4h",
        )
    except Exception as exc:
        logger.warning("Failed to load Dashboard Insight context for %s/%s: %s", symbol, exchange, exc)
        return {
            "module": MODULE_INSIGHT,
            "status": "error",
            "summary": f"Dashboard Insight AI {symbol}/{timeframe}: market-intelligence snapshot failed: {_short_text(exc, 180)}",
            "direction": "neutral",
            "confidence": 0.0,
            "risk_level": "unknown",
            "raw_payload": {"error": str(exc), "source_page": "Dashboard Insight"},
        }

    summary_data = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    news_items = list(snapshot.get("news_items") or [])
    zone_items = list(snapshot.get("zone_items") or [])
    insight_timeframe = str(snapshot.get("timeframe") or timeframe or DEFAULT_TIMEFRAME)

    chart_start_ms = _datetime_to_epoch_ms(snapshot.get("chart_lookback_start"))
    chart_context = _load_insight_chart_context(db, exchange, symbol, insight_timeframe, chart_start_ms)
    latest_close = chart_context[-1]["close"] if chart_context else None
    first_close = chart_context[0]["close"] if chart_context else None
    chart_change_pct = (
        ((latest_close - first_close) / first_close * 100)
        if latest_close is not None and first_close not in (None, 0)
        else None
    )

    total_buy = _to_float(summary_data.get("total_buy_notional")) or 0.0
    total_sell = _to_float(summary_data.get("total_sell_notional")) or 0.0
    total_flow = total_buy + total_sell
    net_inflow = _to_float(summary_data.get("net_inflow")) or 0.0
    buy_ratio = _to_float(summary_data.get("buy_ratio"))
    large_order_net = _to_float(summary_data.get("large_order_net")) or 0.0
    large_buy = _to_float(summary_data.get("total_large_buy_notional")) or 0.0
    large_sell = _to_float(summary_data.get("total_large_sell_notional")) or 0.0
    large_total = large_buy + large_sell
    oi_change_pct = _to_float(summary_data.get("open_interest_change_pct"))
    funding_rate_pct = _to_float(summary_data.get("funding_rate_pct"))

    score = 0.0
    if total_flow > 0:
        if buy_ratio is not None:
            score += _clamp((buy_ratio - 0.5) * 6.0, -1.0, 1.0)
        score += _clamp((net_inflow / total_flow) * 4.0, -0.8, 0.8)
    if large_total > 0:
        score += _clamp((large_order_net / large_total) * 0.9, -0.9, 0.9)
    if chart_change_pct is not None and abs(chart_change_pct) >= 0.05:
        score += _clamp(chart_change_pct / 2.5, -0.55, 0.55)
    if oi_change_pct is not None and abs(oi_change_pct) >= 0.2:
        if score >= 0:
            score += 0.22 if oi_change_pct > 0 else -0.08
        else:
            score -= 0.22 if oi_change_pct > 0 else -0.08
    if funding_rate_pct is not None and abs(funding_rate_pct) >= 0.02:
        score += 0.12 if funding_rate_pct > 0 else -0.12

    news_counts = {"bullish": 0, "bearish": 0, "neutral": 0, "unknown": 0}
    news_score = 0.0
    compact_news: List[Dict[str, Any]] = []
    for item in news_items:
        sentiment_value = _sentiment_score(item.get("sentiment"))
        if sentiment_value > 0:
            news_counts["bullish"] += 1
        elif sentiment_value < 0:
            news_counts["bearish"] += 1
        elif item.get("sentiment"):
            news_counts["neutral"] += 1
        else:
            news_counts["unknown"] += 1

        relevance = _to_float(item.get("relevance_score"))
        if relevance is None:
            relevance_weight = 0.7
        else:
            relevance_weight = relevance / 100 if relevance > 1 else relevance
            relevance_weight = _clamp(relevance_weight, 0.25, 1.0)
        news_score += sentiment_value * relevance_weight

        if len(compact_news) < 5:
            compact_news.append(
                {
                    "id": item.get("id"),
                    "source_domain": item.get("source_domain"),
                    "title": _short_text(item.get("title"), 180),
                    "summary": _short_text(item.get("ai_summary") or item.get("summary"), 240),
                    "published_at": item.get("published_at"),
                    "symbols": item.get("symbols"),
                    "sentiment": item.get("sentiment"),
                    "relevance_score": item.get("relevance_score"),
                }
            )
    score += _clamp(news_score * 0.28, -1.2, 1.2)

    event_context = _build_insight_event_context(news_items, zone_items, exchange, symbol, insight_timeframe)
    strongest_zone = (event_context.get("top_flow_zones") or [{}])[0]
    strongest_zone_net = _to_float(strongest_zone.get("large_order_net")) or 0.0
    if abs(strongest_zone_net) >= 100_000:
        score += 0.32 if strongest_zone_net > 0 else -0.32

    direction = _direction_from_score(score, neutral_band=0.45)
    insight_sentiment = direction if direction in {"bullish", "bearish"} else "mixed"
    flow_has_data = total_flow > 0 or bool(summary_data.get("latest_trade_timestamp"))
    has_chart = len(chart_context) >= 3
    has_events = bool(news_items or zone_items)
    if flow_has_data and has_chart and has_events:
        status = "ok"
    elif flow_has_data or has_chart or has_events:
        status = "partial"
    else:
        status = "missing"

    evidence_points = (
        (2 if flow_has_data else 0)
        + (1 if has_chart else 0)
        + min(len(news_items), 5) * 0.4
        + min(len(event_context.get("top_flow_zones") or []), 5) * 0.5
    )
    confidence = 0.0 if status == "missing" else _clamp(0.22 + abs(score) * 0.08 + min(evidence_points, 6) * 0.06, 0.1, 0.88)

    max_zone_abs = max(
        [abs(_to_float(zone.get("large_order_net")) or 0.0) for zone in zone_items] or [0.0]
    )
    risk_level = "unknown" if status == "missing" else "low"
    if risk_level != "unknown":
        if (
            abs(large_order_net) >= 2_000_000
            or max_zone_abs >= 1_000_000
            or abs(oi_change_pct or 0.0) >= 4.0
            or abs(funding_rate_pct or 0.0) >= 0.08
        ):
            risk_level = "high"
        elif (
            abs(large_order_net) >= 500_000
            or max_zone_abs >= 300_000
            or abs(oi_change_pct or 0.0) >= 1.5
            or abs(funding_rate_pct or 0.0) >= 0.03
        ):
            risk_level = "medium"

    latest_news_title = compact_news[0]["title"] if compact_news else "none"
    summary = (
        f"Dashboard Insight AI {symbol}/{insight_timeframe} 4h: {insight_sentiment}, "
        f"net_flow={_format_usd(net_inflow)}, large_order_net={_format_usd(large_order_net)}, "
        f"buy_ratio={_format_number((buy_ratio * 100) if buy_ratio is not None else None, 1)}%, "
        f"OI_change={_format_number(oi_change_pct, 3)}%, funding={_format_number(funding_rate_pct, 4)}%, "
        f"chart_change={_format_number(chart_change_pct, 2)}%, "
        f"news bull/bear/neutral={news_counts['bullish']}/{news_counts['bearish']}/{news_counts['neutral']}, "
        f"whale_zones={len(zone_items)}, strongest_zone={_format_usd(strongest_zone_net)}, "
        f"latest_news={_short_text(latest_news_title, 90)}. "
        f"Advisory confidence={confidence:.2f}, risk={risk_level}."
    )

    return {
        "module": MODULE_INSIGHT,
        "status": status,
        "summary": summary,
        "direction": direction,
        "confidence": confidence,
        "risk_level": risk_level,
        "raw_payload": {
            "source_page": "Dashboard Insight",
            "source_endpoint": "/api/market-intelligence/stream",
            "auto_worker": True,
            "exchange": exchange,
            "symbol": symbol,
            "timeframe": insight_timeframe,
            "analysis_window": "4h",
            "generated_at": snapshot.get("generated_at"),
            "flow_updated_at": snapshot.get("flow_updated_at"),
            "latest_news_at": snapshot.get("latest_news_at"),
            "flow_summary": summary_data,
            "news_counts": news_counts,
            "top_news": compact_news,
            "top_flow_zones": event_context.get("top_flow_zones") or [],
            "selected_event": event_context.get("selected_event"),
            "recent_events": event_context.get("events") or [],
            "chart_context": {
                "records": len(chart_context),
                "start_time": chart_context[0]["time"] if chart_context else None,
                "end_time": chart_context[-1]["time"] if chart_context else None,
                "latest_close": latest_close,
                "change_pct": chart_change_pct,
                "tail": chart_context[-20:],
            },
            "score": score,
        },
    }
