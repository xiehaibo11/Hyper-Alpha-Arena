"""Resolve the symbol scope that a strategy should evaluate."""

from __future__ import annotations

import json
from typing import Iterable, List, Optional, Set

from sqlalchemy.orm import Session

from database.models import AccountStrategyConfig, SignalPool
from repositories.strategy_repo import parse_signal_pool_ids


def _parse_symbols(raw_symbols) -> List[str]:
    if not raw_symbols:
        return []
    symbols = raw_symbols
    if isinstance(symbols, str):
        try:
            symbols = json.loads(symbols)
        except json.JSONDecodeError:
            symbols = [item.strip() for item in raw_symbols.split(",")]
    if not isinstance(symbols, list):
        return []
    return [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]


def get_strategy_bound_symbols(
    db: Session,
    *,
    account_ids: Optional[Iterable[int]] = None,
    exchange: str,
) -> List[str]:
    """Return unique symbols from enabled signal pools bound to strategy configs."""
    query = db.query(AccountStrategyConfig).filter(
        AccountStrategyConfig.exchange == exchange,
        AccountStrategyConfig.enabled == "true",
    )
    if account_ids is not None:
        account_id_set = [int(account_id) for account_id in account_ids]
        if not account_id_set:
            return []
        query = query.filter(AccountStrategyConfig.account_id.in_(account_id_set))

    pool_ids: Set[int] = set()
    for strategy in query.all():
        pool_ids.update(parse_signal_pool_ids(strategy))

    if not pool_ids:
        return []

    symbols: Set[str] = set()
    pools = (
        db.query(SignalPool)
        .filter(
            SignalPool.id.in_(pool_ids),
            SignalPool.exchange == exchange,
            SignalPool.enabled == True,
        )
        .all()
    )
    for pool in pools:
        symbols.update(_parse_symbols(pool.symbols))

    return sorted(symbols)
