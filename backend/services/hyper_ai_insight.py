"""Dashboard Insight one-shot analysis for Hyper AI."""

from __future__ import annotations

import json
import logging
import math
import random
import time
from typing import Any, Callable, Dict, Generator, List, Optional

import requests
from sqlalchemy import desc
from sqlalchemy.orm import Session

from api.market_flow_routes import TIMEFRAME_MS
from database.models import CryptoKline
from services.ai_decision_service import (
    build_chat_completion_endpoints,
    build_llm_headers,
    build_llm_payload,
    strip_thinking_tags,
)
from services.ai_stream_service import (
    format_sse_event,
    generate_task_id,
    get_buffer_manager,
    run_ai_task_in_background,
)

logger = logging.getLogger(__name__)

API_MAX_RETRIES = 5
API_BASE_DELAY = 1.0
API_MAX_DELAY = 16.0
RETRYABLE_STATUS_CODES = {502, 503, 504, 429}


def _should_retry_api(status_code: Optional[int], error: Optional[str]) -> bool:
    if status_code and status_code in RETRYABLE_STATUS_CODES:
        return True
    if error and any(text in error.lower() for text in ["timeout", "connection", "reset"]):
        return True
    return False


def _get_retry_delay(attempt: int) -> float:
    delay = min(API_BASE_DELAY * (2 ** attempt), API_MAX_DELAY)
    return delay + random.uniform(0, delay * 0.1)


def _insight_sequence_missing(value: Any) -> bool:
    return not isinstance(value, list) or len(value) == 0


def _load_insight_chart_context(
    db: Session,
    exchange: str,
    symbol: str,
    timeframe: str,
    analysis_window: str,
) -> List[Dict[str, Any]]:
    interval_ms = TIMEFRAME_MS.get(timeframe, TIMEFRAME_MS["15m"])
    window_ms = TIMEFRAME_MS.get(analysis_window, TIMEFRAME_MS["4h"])
    desired = max(20, min(120, math.ceil(window_ms / interval_ms) + 10))

    rows = (
        db.query(CryptoKline)
        .filter(
            CryptoKline.exchange == exchange,
            CryptoKline.symbol == symbol,
            CryptoKline.market == "CRYPTO",
            CryptoKline.period == timeframe,
            CryptoKline.environment == "mainnet",
        )
        .order_by(desc(CryptoKline.timestamp))
        .limit(desired)
        .all()
    )

    return [
        {
            "time": int(row.timestamp),
            "open": float(row.open_price) if row.open_price is not None else None,
            "high": float(row.high_price) if row.high_price is not None else None,
            "low": float(row.low_price) if row.low_price is not None else None,
            "close": float(row.close_price) if row.close_price is not None else None,
            "volume": float(row.volume) if row.volume is not None else None,
        }
        for row in reversed(rows)
    ]


def enrich_insight_context(db: Session, context: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(context or {})
    exchange = str(enriched.get("exchange") or "binance").lower()
    symbol = str(enriched.get("symbol") or "BTC").upper()
    timeframe = str(enriched.get("chart_interval") or enriched.get("timeframe") or "15m")
    analysis_window = str(enriched.get("analysis_window") or "4h")

    if _insight_sequence_missing(enriched.get("chart")):
        try:
            chart = _load_insight_chart_context(db, exchange, symbol, timeframe, analysis_window)
            if chart:
                enriched["chart"] = chart
        except Exception as exc:
            logger.warning("[HyperAI Insight] Failed to enrich chart context: %s", exc)

    needs_snapshot = (
        not isinstance(enriched.get("summary"), dict)
        or _insight_sequence_missing(enriched.get("news"))
        or _insight_sequence_missing(enriched.get("large_order_zones"))
    )
    if needs_snapshot:
        try:
            from api.market_intelligence_routes import _load_snapshot

            snapshot = _load_snapshot(
                db=db,
                symbol=symbol,
                exchange=exchange,
                timeframe=timeframe,
                window="4h",
            )
            if not isinstance(enriched.get("summary"), dict) and snapshot.get("summary"):
                enriched["summary"] = snapshot["summary"]
            if _insight_sequence_missing(enriched.get("news")) and snapshot.get("news_items"):
                enriched["news"] = snapshot["news_items"][:80]
            if _insight_sequence_missing(enriched.get("large_order_zones")) and snapshot.get("zone_items"):
                enriched["large_order_zones"] = snapshot["zone_items"][-120:]
        except Exception as exc:
            logger.warning("[HyperAI Insight] Failed to enrich intelligence snapshot: %s", exc)

    if isinstance(enriched.get("summary"), dict):
        enriched["fund_flow_summary"] = enriched["summary"]

    enriched["data_quality"] = {
        "chart_points": len(enriched.get("chart") or []),
        "news_items": len(enriched.get("news") or []),
        "large_order_zone_points": len(enriched.get("large_order_zones") or []),
        "has_fund_flow_summary": isinstance(enriched.get("summary"), dict),
    }
    return enriched


def _build_insight_messages(
    lang: str,
    context: Dict[str, Any],
    selected_event: Optional[Dict[str, Any]],
) -> List[Dict[str, str]]:
    use_zh = (lang or "").startswith("zh")
    language_instruction = (
        "以中文回复。\n"
        "所有自然语言字段必须使用简体中文，包括 market_emotion、headline、summary、key_drivers.text、risks、explanation_markdown、next_cycle_period、confidence_basis、similar_pattern。\n"
        "即使输入数据或字段名是英文，输出内容也必须是中文，不能夹杂英文句子。\n"
    ) if use_zh else (
        "Respond in English.\n"
        "All natural-language fields must be written in English.\n"
    )

    system_prompt = (
        "You are Hyper AI inside Hyper Alpha Arena.\n"
        f"{language_instruction}"
        "You analyze market intelligence for a retail crypto trader.\n"
        "Use only the provided context.\n"
        "Do not use external tools.\n"
        "Return exactly one JSON object and nothing else.\n"
        "Do not use markdown fences.\n"
        "Think in four layers before producing the JSON: technical structure, fund-flow behavior, news/event sentiment, and the conflicts between them.\n"
        "The final directional call must be grounded in those layers instead of giving a free-floating opinion.\n"
        "Use this exact schema:\n"
        "{\n"
        '  "sentiment": "bullish|bearish|mixed",\n'
        '  "probability": 0-100 integer,\n'
        '  "market_emotion": "short phrase",\n'
        '  "headline": "one sentence conclusion",\n'
        '  "summary": "2-3 sentence plain-language explanation",\n'
        '  "sentiment_breakdown": {\n'
        '    "technical": 0-100 integer,\n'
        '    "flow": 0-100 integer,\n'
        '    "news": 0-100 integer\n'
        '  },\n'
        '  "next_cycle_period": "the next period matching the current chart interval",\n'
        '  "next_cycle_target_price": number|null,\n'
        '  "next_cycle_range_low": number|null,\n'
        '  "next_cycle_range_high": number|null,\n'
        '  "technical_levels": [\n'
        '    {"price": number, "type": "support|resistance", "label": "short phrase"}\n'
        '  ],\n'
        '  "key_drivers": [\n'
        '    {"text": "driver 1", "impact": "high|medium|low", "tone": "bullish|bearish|mixed"}\n'
        '  ],\n'
        '  "risks": ["risk 1", "risk 2"],\n'
        '  "confidence_basis": "one sentence explaining why the confidence level is justified",\n'
        '  "similar_pattern": "short description of the nearest comparable market setup from recent behavior",\n'
        '  "explanation_markdown": "short markdown explanation with evidence bullets"\n'
        "}\n"
        "The probability must reflect directional confidence for the next cycle and should be justified by the breakdown scores, not guessed in isolation.\n"
        "The next-cycle target and range must be your forecast for the next period, even if uncertain.\n"
        "Use sentiment_breakdown to score each dimension independently: technical is based on kline structure, momentum, and nearby support/resistance; flow is based on large-order direction, OI change, and funding behavior; news is based on recent event tone, clustering, and relevance.\n"
        "Use technical_levels to identify the most relevant nearby support and resistance levels from the provided chart context.\n"
        "Use key_drivers to rank the most important catalysts. Impact must distinguish primary versus secondary drivers.\n"
        "Use confidence_basis to state what specifically makes the confidence believable.\n"
        "Use similar_pattern to describe the closest recent setup or regime match visible in the provided data. If there is no credible analogue, say that clearly.\n"
        'If evidence is mixed, set sentiment to "mixed" and explain the conflict clearly.\n'
        "The context includes kline behavior, all relevant symbol news events, and selected exchange fund-flow behavior.\n"
        "Fund-flow evidence may appear as context.summary or context.fund_flow_summary; use net_inflow, buy_ratio, OI change, and funding even when large_order_zones is empty or neutral.\n"
        "Use context.data_quality to distinguish genuinely missing data from available-but-neutral evidence."
    )

    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps({"selected_event": selected_event, "context": context}, ensure_ascii=False),
        },
    ]


def stream_insight_response(
    db: Session,
    context: Dict[str, Any],
    *,
    get_llm_config: Callable[[Session], Dict[str, Any]],
    selected_event: Optional[Dict[str, Any]] = None,
    lang: str = "en",
) -> Generator[str, None, None]:
    llm_config = get_llm_config(db)
    if not llm_config.get("configured"):
        yield format_sse_event("error", {"message": "LLM not configured"})
        return

    base_url = llm_config["base_url"]
    model = llm_config["model"]
    api_key = llm_config["api_key"]
    api_format = llm_config.get("api_format", "openai")
    endpoints = build_chat_completion_endpoints(base_url, model)
    if not endpoints:
        yield format_sse_event("error", {"message": "Invalid API endpoint"})
        return

    headers = build_llm_headers(api_format, api_key, base_url)
    body = build_llm_payload(
        model=model,
        messages=_build_insight_messages(lang or "en", context, selected_event),
        api_format=api_format,
        stream=True,
        temperature=0.2,
    )

    response = None
    last_error = None
    last_status_code = None
    last_response_text = None

    for attempt in range(API_MAX_RETRIES):
        for endpoint in endpoints:
            try:
                response = requests.post(endpoint, headers=headers, json=body, stream=True, timeout=180)
                last_status_code = response.status_code
                last_response_text = response.text[:2000] if response.text else None
                if response.status_code == 200:
                    break
                last_error = f"HTTP {response.status_code}"
            except requests.exceptions.Timeout as exc:
                last_error = f"Timeout: {str(exc)}"
            except requests.exceptions.RequestException as exc:
                last_error = str(exc)

        if response and response.status_code == 200:
            break
        if not _should_retry_api(last_status_code, last_error):
            break
        if attempt < API_MAX_RETRIES - 1:
            yield format_sse_event("retry", {"attempt": attempt + 2, "max_retries": API_MAX_RETRIES})
            time.sleep(_get_retry_delay(attempt))

    if not response or response.status_code != 200:
        error_parts = []
        if last_error:
            error_parts.append(f"error={last_error}")
        if last_status_code:
            error_parts.append(f"status={last_status_code}")
        if last_response_text:
            error_parts.append(f"response={last_response_text[:500]}")
        yield format_sse_event("error", {"message": "; ".join(error_parts) if error_parts else "No response from API"})
        return

    content_parts: List[str] = []
    reasoning_parts: List[str] = []

    try:
        for line in response.iter_lines():
            if not line:
                continue

            line_str = line.decode("utf-8")
            if not line_str.startswith("data: "):
                continue

            data_str = line_str[6:]
            if data_str == "[DONE]":
                break

            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            if api_format == "anthropic":
                event_type = data.get("type")
                if event_type == "content_block_delta":
                    delta = data.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            content_parts.append(text)
                            yield format_sse_event("content", {"text": text})
                elif event_type == "content_block_start":
                    content_block = data.get("content_block", {})
                    if content_block.get("type") == "thinking":
                        thinking = content_block.get("thinking", "")
                        if thinking:
                            reasoning_parts.append(thinking)
                            yield format_sse_event("reasoning", {"content": thinking})
            else:
                choices = data.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                text = delta.get("content", "")
                if text:
                    content_parts.append(text)
                    yield format_sse_event("content", {"text": text})

                reasoning = delta.get("reasoning_content", "")
                if reasoning:
                    reasoning_parts.append(reasoning)
                    yield format_sse_event("reasoning", {"content": reasoning})

        full_content = "".join(content_parts)
        full_reasoning = "".join(reasoning_parts) if reasoning_parts else None
        full_content, tag_thinking = strip_thinking_tags(full_content)
        if tag_thinking:
            full_reasoning = (full_reasoning + "\n\n" + tag_thinking).strip() if full_reasoning else tag_thinking

        yield format_sse_event("done", {"content": full_content.strip(), "reasoning": full_reasoning})
    except Exception as exc:
        yield format_sse_event("error", {"message": str(exc)})


def start_insight_task(
    db: Session,
    context: Dict[str, Any],
    *,
    get_llm_config: Callable[[Session], Dict[str, Any]],
    selected_event: Optional[Dict[str, Any]] = None,
    lang: Optional[str] = None,
) -> str:
    task_id = generate_task_id("insight")
    manager = get_buffer_manager()
    manager.create_task(task_id, None)

    effective_lang = lang or "en"
    enriched_context = enrich_insight_context(db, context)

    def generator_func():
        from database.connection import SessionLocal

        task_db = SessionLocal()
        try:
            yield from stream_insight_response(
                task_db,
                context=enriched_context,
                get_llm_config=get_llm_config,
                selected_event=selected_event,
                lang=effective_lang,
            )
        finally:
            task_db.close()

    run_ai_task_in_background(task_id, generator_func)
    return task_id
