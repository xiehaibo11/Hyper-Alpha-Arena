"""Runtime-only market snapshot appended to AI decision prompts."""

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def append_runtime_market_snapshot(
    prompt: str,
    db: Optional[Session],
    *,
    symbols: Iterable[str],
    exchange: str,
    environment: str = "mainnet",
) -> str:
    """Append live exchange evidence without modifying stored prompt templates."""
    snapshot = build_runtime_market_snapshot(
        db,
        symbols=symbols,
        exchange=exchange,
        environment=environment,
    )
    if not snapshot:
        return prompt
    return f"{prompt.rstrip()}\n\n{snapshot}"


def build_runtime_market_snapshot(
    db: Optional[Session],
    *,
    symbols: Iterable[str],
    exchange: str,
    environment: str = "mainnet",
) -> str:
    """Build a compact Binance futures data block for AI decisions."""
    if str(exchange or "").lower() != "binance":
        return ""

    normalized = _normalize_symbols(symbols)
    if not normalized:
        return ""

    lines = [
        "=== RUNTIME BINANCE DATA SNAPSHOT ===",
        "Source: Binance USDS-M Futures REST plus local exchange=binance flow tables.",
        "This block is appended at runtime only; it is not saved into the Prompt Template.",
    ]

    for symbol in normalized:
        try:
            lines.extend(_symbol_snapshot(db, symbol, environment))
        except Exception as exc:
            logger.warning("[runtime_market_snapshot] %s failed: %s", symbol, exc, exc_info=True)
            lines.extend(["", f"## {symbol}USDT", f"- snapshot_error: {exc}"])

    signal_snapshot = _signal_snapshot(db, normalized, exchange)
    if signal_snapshot:
        lines.append("")
        lines.extend(signal_snapshot.splitlines())

    return "\n".join(lines).strip()


def _normalize_symbols(symbols: Iterable[str]) -> list[str]:
    result: list[str] = []
    for raw_symbol in symbols or []:
        symbol = str(raw_symbol or "").strip().upper()
        if symbol and symbol not in result:
            result.append(symbol)
        if len(result) >= 5:
            break
    return result


def _symbol_snapshot(db: Optional[Session], symbol: str, environment: str) -> list[str]:
    from services.exchanges.binance_adapter import BinanceAdapter
    from services.market_data import get_kline_data, get_ticker_data

    adapter = BinanceAdapter(environment=environment)
    ticker = _safe_dict(lambda: get_ticker_data(symbol, "binance", environment))
    premium = _safe_dict(lambda: adapter.fetch_premium_index(symbol))
    orderbook = _safe_obj(lambda: adapter.fetch_orderbook(symbol, depth=10))
    open_interest = _safe_obj(lambda: adapter.fetch_open_interest(symbol))
    flow_15m = _flow_snapshot(db, symbol, "15m")
    flow_1h = _flow_snapshot(db, symbol, "1h")

    price = ticker.get("price") or premium.get("mark_price")
    mark = premium.get("mark_price")
    index = premium.get("index_price")
    bid = getattr(orderbook, "best_bid", None)
    ask = getattr(orderbook, "best_ask", None)
    spread = getattr(orderbook, "spread", None)
    spread_bps = getattr(orderbook, "spread_bps", None)
    oi = getattr(open_interest, "open_interest", None)
    funding = premium.get("funding_rate") or ticker.get("funding_rate")

    lines = [
        "",
        f"## {symbol}USDT Binance live",
        (
            f"- price={_fmt(price)} mark={_fmt(mark)} index={_fmt(index)} "
            f"bid={_fmt(bid)} ask={_fmt(ask)} spread={_fmt(spread)} "
            f"spread_bps={_fmt(spread_bps, 4)}"
        ),
        f"- open_interest_contracts={_fmt(oi)} funding_rate={_fmt(funding, 8)}",
        f"- 15m_flow: {flow_15m}",
        f"- 1h_flow: {flow_1h}",
    ]

    for period in ("15m", "1h", "4h"):
        lines.append(f"- {period}_kline: {_kline_summary(symbol, period, environment)}")

    return lines


def _flow_snapshot(db: Optional[Session], symbol: str, period: str) -> str:
    if db is None:
        return "unavailable_no_db_session"
    from services.market_flow_indicators import get_flow_indicators_for_prompt

    flow = get_flow_indicators_for_prompt(
        db,
        symbol,
        period,
        ["CVD", "TAKER", "OI_DELTA", "OI", "FUNDING", "DEPTH", "IMBALANCE"],
        exchange="binance",
    )
    cvd = flow.get("CVD") or {}
    taker = flow.get("TAKER") or {}
    oi_delta = flow.get("OI_DELTA") or {}
    oi = flow.get("OI") or {}
    funding = flow.get("FUNDING") or {}
    depth = flow.get("DEPTH") or {}
    imbalance = flow.get("IMBALANCE") or {}

    return (
        f"cvd={_fmt(cvd.get('current'))} "
        f"taker_buy={_fmt(taker.get('buy'))} taker_sell={_fmt(taker.get('sell'))} "
        f"taker_ratio={_fmt(taker.get('ratio'), 4)} "
        f"oi_delta_pct={_fmt(oi_delta.get('current'), 4)} "
        f"oi_abs={_fmt(oi.get('absolute_current'))} "
        f"funding={_fmt(funding.get('current'), 4)} "
        f"depth_ratio={_fmt(depth.get('ratio'), 4)} "
        f"spread={_fmt(depth.get('spread'))} "
        f"imbalance={_fmt(imbalance.get('current'), 4)}"
    )


def _kline_summary(symbol: str, period: str, environment: str) -> str:
    from services.market_data import get_kline_data

    klines = get_kline_data(
        symbol,
        market="binance",
        period=period,
        count=3,
        environment=environment,
        persist=False,
    ) or []
    if not klines:
        return "unavailable"

    last = klines[-1]
    prev = klines[-2] if len(klines) > 1 else None
    close = _to_float(last.get("close"))
    prev_close = _to_float(prev.get("close")) if prev else None
    pct = None
    if close is not None and prev_close not in (None, 0):
        pct = (close - prev_close) / prev_close * 100
    return (
        f"time={last.get('datetime') or last.get('timestamp')} "
        f"open={_fmt(last.get('open'))} high={_fmt(last.get('high'))} "
        f"low={_fmt(last.get('low'))} close={_fmt(last.get('close'))} "
        f"volume={_fmt(last.get('volume'))} change_pct={_fmt(pct, 4)}"
    )


def _signal_snapshot(db: Optional[Session], symbols: list[str], exchange: str) -> str:
    try:
        from services.signal_runtime_snapshot import build_signal_runtime_snapshot_text

        return build_signal_runtime_snapshot_text(db, symbols=symbols, exchange=exchange)
    except Exception as exc:
        logger.warning("[runtime_market_snapshot] signal snapshot failed: %s", exc, exc_info=True)
        return ""


def _safe_dict(func) -> dict[str, Any]:
    try:
        value = func()
        return value if isinstance(value, dict) else {}
    except Exception as exc:
        logger.debug("[runtime_market_snapshot] section failed: %s", exc)
        return {}


def _safe_obj(func):
    try:
        return func()
    except Exception as exc:
        logger.debug("[runtime_market_snapshot] section failed: %s", exc)
        return None


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: Any, precision: int = 6) -> str:
    number = _to_float(value)
    if number is None:
        return "N/A"
    return f"{number:.{precision}f}"
