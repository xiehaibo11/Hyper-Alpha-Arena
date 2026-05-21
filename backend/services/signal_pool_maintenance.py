"""Maintenance helpers for market signal pools."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MARKET_SIGNAL_SOURCE = "market_signals"


def json_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def json_int_ids(value: Any) -> List[int]:
    ids: List[int] = []
    for item in json_list(value):
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def normalize_trigger_condition(value: Any) -> str:
    if isinstance(value, (dict, list)):
        parsed = value
    else:
        try:
            parsed = json.loads(value or "{}")
        except (TypeError, ValueError):
            return str(value or "").strip()
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def pool_reference_count(db: Session, pool_id: int) -> int:
    from database.models import AccountProgramBinding, AccountStrategyConfig, TraderTriggerConfig

    count = 0
    for config in db.query(AccountStrategyConfig).all():
        if config.signal_pool_id == pool_id or pool_id in json_int_ids(config.signal_pool_ids):
            count += 1
    bindings = db.query(AccountProgramBinding).filter(AccountProgramBinding.is_deleted != True).all()
    for binding in bindings:
        if pool_id in json_int_ids(binding.signal_pool_ids):
            count += 1
    for trigger in db.query(TraderTriggerConfig).all():
        if trigger.signal_pool_id == pool_id or pool_id in json_int_ids(trigger.signal_pool_ids):
            count += 1
    return count


def matching_pools(db: Session, pool_name: str, symbol: str, exchange: str) -> List[Any]:
    from database.models import SignalPool

    target_symbol = symbol.upper()
    pools = (
        db.query(SignalPool)
        .filter(
            SignalPool.pool_name == pool_name,
            SignalPool.exchange == exchange,
            SignalPool.source_type == MARKET_SIGNAL_SOURCE,
            SignalPool.is_deleted != True,
        )
        .order_by(SignalPool.id.desc())
        .all()
    )
    return [
        pool for pool in pools
        if target_symbol in [str(item).upper() for item in json_list(pool.symbols)]
    ]


def select_pool_to_update(db: Session, pools: List[Any]) -> Any:
    if not pools:
        return None
    return sorted(
        pools,
        key=lambda pool: (pool_reference_count(db, pool.id) > 0, pool.id),
        reverse=True,
    )[0]


def active_signal_references(db: Session, signal_ids: set[int]) -> set[int]:
    if not signal_ids:
        return set()
    from database.models import SignalPool

    referenced: set[int] = set()
    pools = db.query(SignalPool).filter(SignalPool.is_deleted != True).all()
    for pool in pools:
        for signal_id in json_int_ids(pool.signal_ids):
            if signal_id in signal_ids:
                referenced.add(signal_id)
    return referenced


def soft_delete_orphan_signals(db: Session, signal_ids: List[int]) -> List[int]:
    candidates = set(signal_ids)
    referenced = active_signal_references(db, candidates)
    orphan_ids = sorted(candidates - referenced)
    if orphan_ids:
        db.execute(text("""
            UPDATE signal_definitions
            SET is_deleted = true, deleted_at = CURRENT_TIMESTAMP
            WHERE id = ANY(:ids) AND (is_deleted IS NULL OR is_deleted = false)
        """), {"ids": orphan_ids})
    return orphan_ids


def soft_delete_duplicate_pools(db: Session, pools: List[Any], keep_pool_id: int) -> List[int]:
    deleted_pool_ids: List[int] = []
    for pool in pools:
        if pool.id == keep_pool_id or pool_reference_count(db, pool.id) > 0:
            continue
        pool.is_deleted = True
        pool.deleted_at = datetime.now(timezone.utc)
        deleted_pool_ids.append(pool.id)
    return deleted_pool_ids


def refresh_signal_runtime_cache() -> None:
    try:
        from services.signal_detection_service import signal_detection_service

        signal_detection_service._cache_time = 0
        signal_detection_service._refresh_cache_if_needed()
    except Exception as exc:
        logger.warning("Failed to refresh signal runtime cache: %s", exc)


def cleanup_duplicate_signal_definitions(db: Session) -> Dict[str, int]:
    from database.models import SignalDefinition, SignalPool

    signals = (
        db.query(SignalDefinition)
        .filter(
            SignalDefinition.enabled == True,
            SignalDefinition.is_deleted != True,
        )
        .order_by(SignalDefinition.id.asc())
        .all()
    )

    grouped: Dict[tuple[str, str], List[Any]] = {}
    for signal in signals:
        key = (
            signal.exchange or "hyperliquid",
            normalize_trigger_condition(signal.trigger_condition),
        )
        grouped.setdefault(key, []).append(signal)

    canonical_by_old_id: Dict[int, int] = {}
    duplicate_groups = 0
    for group in grouped.values():
        if len(group) < 2:
            continue
        duplicate_groups += 1
        canonical_id = max(signal.id for signal in group)
        for signal in group:
            if signal.id != canonical_id:
                canonical_by_old_id[signal.id] = canonical_id

    pools_updated = 0
    pools = db.query(SignalPool).filter(SignalPool.is_deleted != True).all()
    for pool in pools:
        original_ids = json_int_ids(pool.signal_ids)
        if not original_ids:
            continue
        next_ids: List[int] = []
        for signal_id in original_ids:
            canonical_id = canonical_by_old_id.get(signal_id, signal_id)
            if canonical_id not in next_ids:
                next_ids.append(canonical_id)
        if next_ids != original_ids:
            pool.signal_ids = json.dumps(next_ids)
            pools_updated += 1

    db.flush()
    deleted_ids = soft_delete_orphan_signals(db, list(canonical_by_old_id.keys()))
    db.commit()
    refresh_signal_runtime_cache()
    return {
        "duplicate_groups": duplicate_groups,
        "pools_updated": pools_updated,
        "signals_deleted": len(deleted_ids),
    }
