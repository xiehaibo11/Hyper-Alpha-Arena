"""Reference data routes for Program Trader."""

import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Account, SignalPool
from routes.program_schemas import AccountInfo, SignalPoolInfo

router = APIRouter()

@router.get("/dev-guide")
def get_program_dev_guide(lang: str = "en") -> dict:
    """
    Get Program Trader development guide documentation.
    Supports English (default) and Chinese.
    """
    import os

    if lang == "zh":
        filename = "PROGRAM_DEV_GUIDE_ZH.md"
    else:
        filename = "PROGRAM_DEV_GUIDE.md"

    doc_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "config",
        filename
    )

    try:
        with open(doc_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Documentation file not found: {filename}")


@router.get("/signal-pools/", response_model=List[SignalPoolInfo])
def list_signal_pools(db: Session = Depends(get_db)):
    """List available signal pools."""
    pools = db.query(SignalPool).filter(
        SignalPool.enabled == True,
        SignalPool.is_deleted != True,
    ).all()
    result = []
    for pool in pools:
        symbols = pool.symbols
        if isinstance(symbols, str):
            try:
                symbols = json.loads(symbols)
            except:
                symbols = []
        result.append(SignalPoolInfo(
            id=pool.id,
            pool_name=pool.pool_name,
            symbols=symbols or [],
            enabled=pool.enabled,
            exchange=pool.exchange or "hyperliquid",
            source_type=pool.source_type or "market_signals",
        ))
    return result


@router.get("/accounts/", response_model=List[AccountInfo])
def list_accounts(db: Session = Depends(get_db)):
    """List available AI Traders for binding."""
    accounts = db.query(Account).filter(
        Account.is_active == "true",
        Account.account_type == "AI",
        Account.is_deleted != True
    ).all()
    return [AccountInfo(id=a.id, name=a.name, model=a.model) for a in accounts]
