"""Live signal-system monitoring routes."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database.connection import get_db
from services.signal_runtime_snapshot import build_signal_runtime_snapshot_payload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/signals", tags=["Signal System"])


@router.get("/live-state")
def get_signal_live_state(
    exchange: str = Query("binance"),
    symbols: Optional[str] = Query(None),
    pool_id: Optional[int] = Query(None),
    include_values: bool = Query(True),
    db: Session = Depends(get_db),
):
    """Return live signal-pool state for Signal System cards and diagnostics."""
    try:
        return build_signal_runtime_snapshot_payload(
            db,
            symbols=symbols,
            exchange=exchange,
            pool_id=pool_id,
            include_values=include_values,
        )
    except Exception as exc:
        logger.error("[SignalLiveState] failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
