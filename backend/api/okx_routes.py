"""OKX public market-data API routes."""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.exchanges.okx_adapter import OKXAdapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/okx", tags=["okx"])


class OKXSymbolSelectionRequest(BaseModel):
    symbols: List[str] = Field(default_factory=list, description="Symbols to monitor")

    class Config:
        json_schema_extra = {"example": {"symbols": ["BTC", "ETH", "SOL"]}}


@router.get("/symbols/available")
def list_available_symbols():
    from services.okx_symbol_service import MAX_WATCHLIST_SYMBOLS, get_available_symbols_info

    info = get_available_symbols_info()
    return {
        "symbols": info.get("symbols", []),
        "count": info.get("count", 0),
        "max_symbols": MAX_WATCHLIST_SYMBOLS,
    }


@router.post("/symbols/refresh")
def refresh_symbols():
    from services.okx_symbol_service import MAX_WATCHLIST_SYMBOLS, refresh_okx_symbols

    symbols = refresh_okx_symbols()
    return {"symbols": symbols, "count": len(symbols), "max_symbols": MAX_WATCHLIST_SYMBOLS}


@router.get("/symbols/watchlist")
def get_symbol_watchlist():
    from services.okx_symbol_service import MAX_WATCHLIST_SYMBOLS, get_selected_symbols

    return {"symbols": get_selected_symbols(), "max_symbols": MAX_WATCHLIST_SYMBOLS}


@router.put("/symbols/watchlist")
def update_symbol_watchlist(payload: OKXSymbolSelectionRequest):
    from services.okx_symbol_service import MAX_WATCHLIST_SYMBOLS, update_selected_symbols

    try:
        symbols = update_selected_symbols(payload.symbols)
        return {"symbols": symbols, "max_symbols": MAX_WATCHLIST_SYMBOLS}
    except Exception as exc:
        logger.error("[OKX] Failed to update watchlist: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update OKX watchlist")


@router.get("/market/ticker/{symbol}")
def get_ticker(symbol: str):
    try:
        adapter = OKXAdapter()
        ticker = adapter.fetch_ticker(symbol)
        mark = adapter.fetch_mark_price(symbol)
        index = adapter.fetch_index_ticker(symbol)
        return {"symbol": symbol.upper(), "ticker": ticker, "mark_price": mark, "index_ticker": index}
    except Exception as exc:
        logger.error("[OKX] Failed to get ticker for %s: %s", symbol, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/market/snapshot/{symbol}")
def get_market_snapshot(symbol: str, depth: int = 10, trades: int = 50):
    try:
        adapter = OKXAdapter()
        ticker = adapter.fetch_ticker(symbol)
        mark = adapter.fetch_mark_price(symbol)
        index = adapter.fetch_index_ticker(symbol)
        funding = adapter.fetch_funding_rate(symbol)
        oi = adapter.fetch_open_interest(symbol)
        orderbook = adapter.fetch_orderbook(symbol, depth=depth)
        recent_trades = adapter.fetch_recent_trades(symbol, limit=trades)
        sentiment = adapter.fetch_sentiment(symbol)
        taker = adapter.fetch_taker_volume_history(symbol, "5m", limit=12)
        return {
            "symbol": symbol.upper(),
            "exchange": "okx",
            "ticker": ticker,
            "mark_price": mark,
            "index_ticker": index,
            "funding": funding.__dict__,
            "open_interest": oi.__dict__,
            "orderbook": orderbook.__dict__,
            "recent_trades": [item.__dict__ for item in recent_trades],
            "sentiment": sentiment.__dict__ if sentiment else None,
            "taker_volume": taker,
        }
    except Exception as exc:
        logger.error("[OKX] Failed to get snapshot for %s: %s", symbol, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/market/klines/{symbol}")
def get_klines(symbol: str, period: str = "1m", limit: int = 100):
    try:
        adapter = OKXAdapter()
        klines = adapter.fetch_klines(symbol, period, limit=limit)
        return {
            "symbol": symbol.upper(),
            "exchange": "okx",
            "period": period,
            "count": len(klines),
            "data": [item.__dict__ for item in klines],
        }
    except Exception as exc:
        logger.error("[OKX] Failed to get klines for %s/%s: %s", symbol, period, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/market/history/{symbol}")
def get_history(symbol: str, period: str = "5m", limit: int = 100):
    try:
        adapter = OKXAdapter()
        return {
            "symbol": symbol.upper(),
            "exchange": "okx",
            "funding": [item.__dict__ for item in adapter.fetch_funding_history(symbol, limit=limit)],
            "open_interest": [item.__dict__ for item in adapter.fetch_open_interest_history(symbol, period, limit=limit)],
            "sentiment": [item.__dict__ for item in adapter.fetch_sentiment_history(symbol, period, limit=limit)],
            "taker_volume": adapter.fetch_taker_volume_history(symbol, period, limit=limit),
        }
    except Exception as exc:
        logger.error("[OKX] Failed to get history for %s/%s: %s", symbol, period, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/market/tickers")
def get_tickers(inst_type: str = "SWAP", uly: Optional[str] = None):
    try:
        return {"exchange": "okx", "data": OKXAdapter().fetch_tickers(inst_type=inst_type, uly=uly)}
    except Exception as exc:
        logger.error("[OKX] Failed to get tickers: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/public/instruments")
def get_instruments(inst_type: str = "SWAP", uly: Optional[str] = None, inst_family: Optional[str] = None):
    try:
        return {
            "exchange": "okx",
            "data": OKXAdapter().fetch_instruments(inst_type=inst_type, uly=uly, inst_family=inst_family),
        }
    except Exception as exc:
        logger.error("[OKX] Failed to get instruments: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
