"""Create/save tools used by Hyper AI."""

import json
import logging
import os
import re
from typing import Any, Dict, List

from sqlalchemy.orm import Session
from sqlalchemy import text

from services.signal_pool_maintenance import (
    MARKET_SIGNAL_SOURCE,
    json_int_ids,
    matching_pools,
    pool_reference_count,
    refresh_signal_runtime_cache,
    select_pool_to_update,
    soft_delete_duplicate_pools,
    soft_delete_orphan_signals,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_SIGNALS_PER_AI_POOL = 50


def _max_signals_per_ai_pool() -> int:
    raw_value = os.getenv("HYPER_AI_SIGNAL_POOL_MAX_SIGNALS", str(DEFAULT_MAX_SIGNALS_PER_AI_POOL))
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        return DEFAULT_MAX_SIGNALS_PER_AI_POOL


def _build_trigger_condition(sig: Dict[str, Any], index: int) -> Dict[str, Any]:
    metric_name = sig.get("metric") or sig.get("indicator")
    if metric_name == "taker_volume":
        condition = {
            "metric": metric_name,
            "direction": sig.get("direction"),
            "ratio_threshold": sig.get("ratio_threshold"),
            "volume_threshold": sig.get("volume_threshold"),
            "time_window": sig.get("time_window"),
        }
        missing = [
            field for field in ("direction", "ratio_threshold", "volume_threshold", "time_window")
            if condition.get(field) is None or condition.get(field) == ""
        ]
        if missing or sig.get("operator"):
            raise ValueError(
                f"Signal {index} (taker_volume) format error. "
                "taker_volume requires direction, ratio_threshold, volume_threshold, time_window "
                "and must not use operator/threshold."
            )
        return condition

    condition = {
        "metric": metric_name,
        "operator": sig.get("operator"),
        "threshold": sig.get("threshold"),
        "time_window": sig.get("time_window"),
    }
    missing = [
        field for field in ("metric", "operator", "threshold", "time_window")
        if condition.get(field) is None or condition.get(field) == ""
    ]
    if missing:
        raise ValueError(f"Signal {index} missing required fields: {', '.join(missing)}")
    return condition


def _create_signal_definitions(
    db: Session,
    pool_name: str,
    signals: List[Dict[str, Any]],
    exchange: str,
    description: str | None,
) -> tuple[List[int], List[Dict[str, Any]]]:
    created_signal_ids: List[int] = []
    created_signals: List[Dict[str, Any]] = []
    for index, sig in enumerate(signals, start=1):
        condition = _build_trigger_condition(sig, index)
        signal_name = sig.get("name") or f"{pool_name}_{index}"
        result = db.execute(text("""
            INSERT INTO signal_definitions (signal_name, description, trigger_condition, enabled, exchange)
            VALUES (:name, :description, :condition, :enabled, :exchange)
            RETURNING id, signal_name
        """), {
            "name": signal_name,
            "description": sig.get("description") or description or f"Part of {pool_name}",
            "condition": json.dumps(condition),
            "enabled": True,
            "exchange": exchange,
        })
        row = result.fetchone()
        created_signal_ids.append(row[0])
        created_signals.append({
            "id": row[0],
            "signal_name": row[1],
            "trigger_condition": condition,
            "exchange": exchange,
        })

    return created_signal_ids, created_signals


def _save_signal_pool(
    db: Session,
    pool_name: str,
    symbol: str,
    signals: List[Dict[str, Any]],
    logic: str,
    exchange: str,
    description: str | None,
) -> Dict[str, Any]:
    if not signals:
        raise ValueError("No signals provided")

    max_signals = _max_signals_per_ai_pool()
    if len(signals) > max_signals:
        raise ValueError(f"Maximum {max_signals} signals per AI-created pool")

    created_signal_ids, created_signals = _create_signal_definitions(
        db, pool_name, signals, exchange, description
    )
    matching_signal_pools = matching_pools(db, pool_name, symbol, exchange)
    pool = select_pool_to_update(db, matching_signal_pools)
    old_signal_ids: List[int] = []
    duplicate_signal_ids: List[int] = []
    duplicate_pools_deleted: List[int] = []

    if pool:
        old_signal_ids = json_int_ids(pool.signal_ids)
        for duplicate_pool in matching_signal_pools:
            if duplicate_pool.id != pool.id and pool_reference_count(db, duplicate_pool.id) == 0:
                duplicate_signal_ids.extend(json_int_ids(duplicate_pool.signal_ids))
        duplicate_pools_deleted = soft_delete_duplicate_pools(db, matching_signal_pools, pool.id)
        pool.signal_ids = json.dumps(created_signal_ids)
        pool.symbols = json.dumps([symbol.upper()])
        pool.logic = logic
        pool.enabled = True
        pool.exchange = exchange
        pool.source_type = MARKET_SIGNAL_SOURCE
        pool.source_config = json.dumps({})
        action = "updated"
    else:
        pool_result = db.execute(text("""
            INSERT INTO signal_pools (pool_name, signal_ids, symbols, enabled, logic, exchange, source_type, source_config)
            VALUES (:name, :signal_ids, :symbols, :enabled, :logic, :exchange, :source_type, :source_config)
            RETURNING id, pool_name
        """), {
            "name": pool_name,
            "signal_ids": json.dumps(created_signal_ids),
            "symbols": json.dumps([symbol.upper()]),
            "enabled": True,
            "logic": logic,
            "exchange": exchange,
            "source_type": MARKET_SIGNAL_SOURCE,
            "source_config": json.dumps({}),
        })
        pool_row = pool_result.fetchone()
        pool = type("PoolResult", (), {"id": pool_row[0], "pool_name": pool_row[1]})()
        action = "created"

    db.flush()
    deleted_signal_ids = soft_delete_orphan_signals(db, old_signal_ids + duplicate_signal_ids)
    db.commit()
    refresh_signal_runtime_cache()
    return {
        "pool": {"id": pool.id, "pool_name": pool.pool_name},
        "signals": created_signals,
        "action": action,
        "old_signals_deleted": len(deleted_signal_ids),
        "duplicate_pools_deleted": len(duplicate_pools_deleted),
    }


def execute_save_signal_pool(
    db: Session,
    pool_name: str,
    symbol: str,
    signals: List[Dict[str, Any]],
    logic: str = "AND",
    exchange: str = "hyperliquid",
    description: str = None
) -> str:
    """Create a signal pool from Hyper AI without the public route's small UI cap."""
    try:
        result = _save_signal_pool(db, pool_name, symbol, signals, logic, exchange, description)
        return json.dumps({
            "success": True,
            "pool_id": result["pool"]["id"],
            "pool_name": result["pool"]["pool_name"],
            "symbol": symbol.upper(),
            "action": result["action"],
            "signals_created": len(result["signals"]),
            "old_signals_deleted": result["old_signals_deleted"],
            "duplicate_pools_deleted": result["duplicate_pools_deleted"],
            "signals": result["signals"],
            "logic": logic,
            "exchange": exchange,
            "view_url": f"/#signal-management?view={result['pool']['id']}",
            "note": "Signal pool saved. Same-name updates replace old signals instead of leaving stale ones."
        })

    except Exception as e:
        db.rollback()
        logger.error(f"[save_signal_pool] Error: {e}")
        return json.dumps({"error": str(e)})


def execute_save_prompt(
    db: Session,
    name: str,
    template_text: str,
    prompt_id: int = None,
    description: str = None
) -> str:
    """Create or update a trading prompt template."""
    from database.models import PromptTemplate
    import re

    try:
        # Extract variables from template
        variables = re.findall(r'\{([a-zA-Z_][a-zA-Z0-9_]*)\}', template_text)
        variables = list(set(variables))

        if prompt_id:
            # Update existing prompt
            prompt = db.query(PromptTemplate).filter(
                PromptTemplate.id == prompt_id,
                PromptTemplate.is_deleted == "false"
            ).first()
            if not prompt:
                return json.dumps({"error": f"Prompt {prompt_id} not found"})

            prompt.name = name
            prompt.template_text = template_text
            if description:
                prompt.description = description
            prompt.updated_by = "hyper_ai"
            db.commit()
            action = "updated"
        else:
            # Create new prompt
            # Generate unique key
            import uuid
            key = f"hyper_ai_{uuid.uuid4().hex[:8]}"

            # Get default system template
            default_system = db.query(PromptTemplate).filter(
                PromptTemplate.is_system == "true"
            ).first()
            system_text = default_system.system_template_text if default_system else ""

            prompt = PromptTemplate(
                key=key,
                name=name,
                description=description or "",
                template_text=template_text,
                system_template_text=system_text,
                is_system="false",
                is_deleted="false",
                created_by="hyper_ai"
            )
            db.add(prompt)
            db.commit()
            db.refresh(prompt)
            action = "created"

        return json.dumps({
            "success": True,
            "prompt_id": prompt.id,
            "name": name,
            "action": action,
            "variables_detected": variables[:20],
            "template_text": template_text,
            "view_url": f"/#prompt-management?view={prompt.id}",
            "note": "Prompt saved. Changes apply to bound AI Traders on next trigger."
        }, indent=2)

    except Exception as e:
        db.rollback()
        logger.error(f"[save_prompt] Error: {e}")
        return json.dumps({"error": str(e)})


def execute_save_program(
    db: Session,
    name: str,
    code: str,
    program_id: int = None,
    description: str = None
) -> str:
    """Create or update a trading program by calling existing API handlers."""
    from routes.program_routes import (
        create_program, update_program, ProgramCreate, ProgramUpdate
    )
    from fastapi import HTTPException

    try:
        if program_id:
            # Update existing program
            data = ProgramUpdate(name=name, code=code, description=description)
            result = update_program(program_id, data, db)
            action = "updated"
        else:
            # Create new program
            data = ProgramCreate(name=name, code=code, description=description)
            result = create_program(data, db)
            action = "created"

        return json.dumps({
            "success": True,
            "program_id": result.id,
            "name": result.name,
            "action": action,
            "code": code,
            "view_url": f"/#program-trader?view={result.id}",
            "validation": {"syntax_valid": True, "security_check": "passed"},
            "note": "Program saved. Use test_run_code to verify logic before binding."
        }, indent=2)

    except HTTPException as e:
        db.rollback()
        logger.error(f"[save_program] HTTPException: {e.detail}")
        return json.dumps({"success": False, "error": e.detail})
    except Exception as e:
        db.rollback()
        logger.error(f"[save_program] Error: {e}")
        return json.dumps({"error": str(e)})


def execute_create_ai_trader(
    db: Session,
    name: str,
    model: str,
    base_url: str,
    api_key: str
) -> str:
    """Create a new AI Trader with LLM config only. Strategy and wallet binding done separately."""
    from database.models import Account

    try:
        # Step 1: Test LLM connection first
        from api.account_routes import test_llm_connection

        test_result = test_llm_connection({
            "model": model,
            "base_url": base_url,
            "api_key": api_key
        })

        if not test_result.get("success"):
            return json.dumps({
                "success": False,
                "error": "LLM connection test failed",
                "details": test_result.get("message", "Unknown error"),
                "note": "Please check your LLM credentials and try again."
            })

        # Step 2: Create Account with LLM config only
        account = Account(
            user_id=1,
            name=name,
            account_type="AI",
            is_active="true",
            auto_trading_enabled="false",  # Disabled until strategy/wallet configured
            model=model,
            base_url=base_url,
            api_key=api_key
        )
        db.add(account)
        db.commit()

        return json.dumps({
            "success": True,
            "trader_id": account.id,
            "trader_name": name,
            "llm_config": {
                "model": model,
                "base_url": base_url,
                "connection_tested": True
            },
            "view_url": f"/#trader-management?view={account.id}",
            "next_steps": [
                "1. Bind a wallet to this trader",
                "2. Create/select a trading strategy",
                "3. Enable auto-trading when ready"
            ],
            "note": "AI Trader created with LLM config. Complete wallet and strategy setup to start trading."
        }, indent=2)

    except Exception as e:
        db.rollback()
        logger.error(f"[create_ai_trader] Error: {e}")
        return json.dumps({"error": str(e)})


# =============================================================================
# Query Tools: list resources
# =============================================================================
