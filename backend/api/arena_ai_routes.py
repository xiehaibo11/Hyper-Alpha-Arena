"""Arena AI context and strategy diagnostics routes."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.connection import SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter()


class StrategyPromptFixRequest(BaseModel):
    account_id: int
    exchange: str = "binance"
    limit: int = 50


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/ai-context")
def get_arena_ai_context(
    account_id: Optional[int] = Query(None, description="AI trader account ID"),
    exchange: str = Query("binance", description="Exchange: binance or hyperliquid"),
    symbols: Optional[str] = Query(None, description="Comma-separated symbols, e.g. BTC,ETH,SOL"),
    timeframe: str = Query("15m", description="Context timeframe"),
    recompute: bool = Query(False, description="Recompute advisory snapshots before returning"),
    db: Session = Depends(get_db),
):
    """Return the Arena sub-AI advisory context bus."""
    try:
        from services.arena_ai_context_service import get_context_payload

        symbol_list = [item.strip().upper() for item in symbols.split(",") if item.strip()] if symbols else None
        return get_context_payload(
            db,
            account_id=account_id,
            exchange=exchange,
            symbols=symbol_list,
            timeframe=timeframe,
            recompute=recompute,
        )
    except Exception as exc:
        logger.error("Failed to get Arena AI context: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get Arena AI context: {exc}")


@router.post("/ai-context/recompute")
def recompute_arena_ai_context_endpoint(
    account_id: Optional[int] = Query(None, description="AI trader account ID"),
    exchange: str = Query("binance", description="Exchange: binance or hyperliquid"),
    symbols: Optional[str] = Query(None, description="Comma-separated symbols, e.g. BTC,ETH,SOL"),
    timeframe: str = Query("15m", description="Context timeframe"),
):
    """Manually recompute Arena sub-AI advisory snapshots."""
    try:
        from services.arena_ai_context_service import enqueue_arena_ai_context_recompute

        symbol_list = [item.strip().upper() for item in symbols.split(",") if item.strip()] if symbols else None
        recompute_status = enqueue_arena_ai_context_recompute(
            account_id=account_id,
            exchange=exchange,
            symbols=symbol_list,
            timeframe=timeframe,
        )
        return {
            "status": recompute_status,
            "recompute_requested": True,
            "exchange": exchange,
            "symbols": symbol_list,
            "timeframe": timeframe,
            "account_id": account_id,
        }
    except Exception as exc:
        logger.error("Failed to recompute Arena AI context: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to recompute Arena AI context: {exc}")


@router.get("/strategy-diagnostics")
def get_strategy_diagnostics(
    account_id: Optional[int] = Query(None, description="AI trader account ID"),
    exchange: str = Query("binance", description="Exchange: binance or hyperliquid"),
    limit: int = Query(50, ge=5, le=200, description="Recent decision count to summarize"),
    db: Session = Depends(get_db),
):
    """Return Arena Strategy Diagnosis AI output and prompt optimization draft."""
    try:
        from services.arena_strategy_diagnostics import build_strategy_diagnostics

        return build_strategy_diagnostics(
            db,
            account_id=account_id,
            exchange=exchange,
            limit=limit,
            include_prompt=True,
        )
    except Exception as exc:
        logger.error("Failed to build strategy diagnostics: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to build strategy diagnostics: {exc}")


@router.post("/strategy-diagnostics/apply-prompt-fix")
def apply_strategy_prompt_fix_endpoint(
    payload: StrategyPromptFixRequest,
    db: Session = Depends(get_db),
):
    """Create and bind a repaired prompt template generated from Strategy Diagnosis AI."""
    try:
        from services.arena_strategy_diagnostics import apply_strategy_prompt_fix

        return apply_strategy_prompt_fix(
            db,
            account_id=payload.account_id,
            exchange=payload.exchange,
            limit=payload.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Failed to apply strategy prompt fix: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to apply strategy prompt fix: {exc}")
