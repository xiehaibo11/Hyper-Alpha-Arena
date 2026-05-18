"""数据.md K-line coverage snapshot builder for Arena context."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

MODULE_KLINE_COVERAGE = "kline_coverage_ai"


def _utcnow() -> datetime:
    return datetime.utcnow()


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _short_text(value: Any, limit: int = 320) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def build_kline_coverage_snapshot(
    db: Session,
    account_id: Optional[int],
    exchange: str,
    symbols: List[str],
    timeframe: str,
) -> Dict[str, Any]:
    if exchange != "binance":
        return {
            "module": MODULE_KLINE_COVERAGE,
            "status": "ok",
            "summary": f"数据.md K-Line Coverage AI: {exchange} is outside the Binance coverage worker scope.",
            "direction": "neutral",
            "confidence": 0.5,
            "risk_level": "low",
            "raw_payload": {
                "account_id": account_id,
                "exchange": exchange,
                "symbols": symbols,
                "timeframe": timeframe,
            },
        }

    from services.binance_kline_coverage_service import (
        CHECK_INTERVAL_SECONDS,
        FLOW_INDICATORS,
        PERIODS,
        TECHNICAL_INDICATORS,
        load_latest_binance_kline_coverage,
    )

    payload = load_latest_binance_kline_coverage(db)
    if not payload:
        return {
            "module": MODULE_KLINE_COVERAGE,
            "status": "missing",
            "summary": (
                "数据.md K-Line Coverage AI: no Binance coverage check has completed yet. "
                "The 3-minute worker must refresh K-line/indicator coverage before the main AI trusts it."
            ),
            "direction": "neutral",
            "confidence": 0.0,
            "risk_level": "high",
            "raw_payload": {
                "account_id": account_id,
                "exchange": exchange,
                "symbols": symbols,
                "timeframe": timeframe,
                "periods": PERIODS,
                "technical_indicators": TECHNICAL_INDICATORS,
                "flow_indicators": FLOW_INDICATORS,
            },
        }

    summary_counts = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    total = int(summary_counts.get("total_periods") or 0)
    ok_count = int(summary_counts.get("ok") or 0)
    partial_count = int(summary_counts.get("partial") or 0)
    missing_count = int(summary_counts.get("missing") or 0)
    generated_at = payload.get("generated_at")
    coverage_age_seconds: Optional[float] = None
    if generated_at:
        try:
            generated_dt = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
            if generated_dt.tzinfo is not None:
                generated_dt = generated_dt.astimezone(timezone.utc).replace(tzinfo=None)
            coverage_age_seconds = max(0.0, (_utcnow() - generated_dt).total_seconds())
        except ValueError:
            coverage_age_seconds = None

    covered_symbols = {str(item).upper() for item in payload.get("symbols") or []}
    requested_symbols = {str(item).upper() for item in symbols}
    uncovered_symbols = sorted(requested_symbols - covered_symbols)
    worker_stale = (
        coverage_age_seconds is not None
        and coverage_age_seconds > max(CHECK_INTERVAL_SECONDS * 2, CHECK_INTERVAL_SECONDS + 60)
    )
    issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
    if uncovered_symbols:
        issues = [*issues, f"uncovered_symbols={','.join(uncovered_symbols)}"]
    if worker_stale:
        issues = [*issues, f"coverage_worker_stale={int(coverage_age_seconds or 0)}s"]

    if missing_count > 0 or uncovered_symbols:
        status = "missing"
    elif partial_count > 0 or worker_stale:
        status = "partial"
    else:
        status = "ok"

    if missing_count > 0 or uncovered_symbols:
        risk_level = "high"
    elif partial_count > 0 or worker_stale or issues:
        risk_level = "medium"
    else:
        risk_level = "low"

    confidence = (ok_count / total) if total else 0.0
    if worker_stale:
        confidence *= 0.7
    if uncovered_symbols:
        confidence *= 0.8

    issue_preview = "; ".join(_short_text(item, 160) for item in issues[:3]) or "none"
    age_text = "N/A" if coverage_age_seconds is None else f"{int(coverage_age_seconds)}s"
    summary = (
        f"数据.md K-Line Coverage AI ({exchange}): checked {len(covered_symbols)} symbols x "
        f"{len(payload.get('periods') or PERIODS)} periods every {CHECK_INTERVAL_SECONDS}s. "
        f"ok={ok_count}, partial={partial_count}, missing={missing_count}, "
        f"requests={payload.get('requests_used', 0)}/{payload.get('request_budget', 0)}, "
        f"refreshed={payload.get('refreshed_periods', 0)}, latest_check_age={age_text}. "
        f"Issues={issue_preview}."
    )

    raw_payload = dict(payload)
    raw_payload["account_id"] = account_id
    raw_payload["coverage_age_seconds"] = coverage_age_seconds
    raw_payload["uncovered_symbols"] = uncovered_symbols

    return {
        "module": MODULE_KLINE_COVERAGE,
        "status": status,
        "summary": summary,
        "direction": "neutral",
        "confidence": _clamp(confidence, 0.0, 0.95),
        "risk_level": risk_level,
        "raw_payload": raw_payload,
    }
