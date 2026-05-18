"""Market data query routes for AI program authoring."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database.connection import get_db
from routes.program_schemas import MarketDataQueryRequest, MarketDataQueryResponse

router = APIRouter()

@router.post("/query-market-data", response_model=MarketDataQueryResponse)
async def query_market_data(
    request: MarketDataQueryRequest,
    db: Session = Depends(get_db)
):
    """
    Query current market data for a symbol.

    Use this API to check current indicator values before setting thresholds
    in your strategy code. Returns real-time data for all available indicators.
    """
    import time
    from datetime import datetime
    from services.technical_indicators import calculate_indicator
    from services.market_flow_indicators import get_flow_indicators_for_prompt
    from services.market_regime_service import get_market_regime
    from services.hyperliquid_market_data import get_last_price_from_hyperliquid
    from database.models import CryptoKline
    from sqlalchemy import desc

    symbol = request.symbol.upper()
    period = request.period
    current_time_ms = int(time.time() * 1000)

    # Get current price
    price = None
    try:
        price = get_last_price_from_hyperliquid(symbol, "mainnet")
        if price:
            price = float(price)
    except Exception:
        pass

    # Default indicators and flow metrics
    all_indicators = ["RSI14", "RSI7", "MA5", "MA10", "MA20", "EMA20", "EMA50",
                      "EMA100", "MACD", "BOLL", "ATR14", "VWAP", "STOCH", "OBV"]
    all_flow_metrics = ["CVD", "OI", "OI_DELTA", "TAKER", "FUNDING", "DEPTH", "IMBALANCE"]

    indicators_to_query = request.indicators or all_indicators
    flow_metrics_to_query = request.flow_metrics or all_flow_metrics

    # Query indicators
    indicators_result = {}
    for ind in indicators_to_query:
        try:
            result = calculate_indicator(db, symbol, ind, period, current_time_ms)
            # Note: empty dict {} or 0.0 values are valid results
            indicators_result[ind] = result if result is not None else None
        except Exception as e:
            indicators_result[ind] = {"error": str(e)}

    # Query flow metrics - return full structure (not simplified single value)
    flow_result = {}
    try:
        full_flow_data = get_flow_indicators_for_prompt(
            db, symbol, period, flow_metrics_to_query, current_time_ms
        )
        for metric in flow_metrics_to_query:
            flow_result[metric] = full_flow_data.get(metric) if full_flow_data else None
    except Exception as e:
        for metric in flow_metrics_to_query:
            flow_result[metric] = {"error": str(e)}

    # Query regime - return full structure including indicators
    regime_result = None
    try:
        regime = get_market_regime(db, symbol, period, timestamp_ms=current_time_ms)
        if regime:
            regime_result = {
                "regime": regime.get("regime", "noise"),
                "confidence": regime.get("confidence", 0.0),
                "direction": regime.get("direction", "neutral"),
                "reason": regime.get("reason", ""),
                "indicators": regime.get("indicators", {})
            }
    except Exception:
        pass

    # Get sample klines (last 5)
    klines_sample = None
    try:
        rows = (
            db.query(CryptoKline)
            .filter(CryptoKline.symbol == symbol, CryptoKline.period == period)
            .order_by(desc(CryptoKline.timestamp))
            .limit(5)
            .all()
        )
        if rows:
            klines_sample = [
                {
                    "timestamp": row.timestamp,
                    "open": float(row.open_price) if row.open_price else 0,
                    "high": float(row.high_price) if row.high_price else 0,
                    "low": float(row.low_price) if row.low_price else 0,
                    "close": float(row.close_price) if row.close_price else 0,
                    "volume": float(row.volume) if row.volume else 0,
                }
                for row in reversed(rows)
            ]
    except Exception:
        pass

    return MarketDataQueryResponse(
        symbol=symbol,
        period=period,
        price=price,
        indicators=indicators_result,
        flow_metrics=flow_result,
        regime=regime_result,
        klines_sample=klines_sample,
        timestamp=datetime.utcnow().isoformat() + "Z"
    )


@router.get("/available-symbols")
async def get_available_symbols(db: Session = Depends(get_db)):
    """
    Get list of symbols with available market data.
    """
    from database.models import CryptoKline
    from sqlalchemy import distinct

    try:
        symbols = db.query(distinct(CryptoKline.symbol)).all()
        return {"symbols": sorted([s[0] for s in symbols])}
    except Exception as e:
        return {"symbols": ["BTC", "ETH", "SOL"], "error": str(e)}


# ============================================================================
