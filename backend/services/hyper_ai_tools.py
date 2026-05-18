"""
Hyper AI Tools - Tools for Hyper AI main agent

Provides tools for:
- System overview and diagnostics
- Wallet status queries
- API reference documentation
- Market data (klines, regime, flow)
- Create/save operations (signal pool, prompt, program, AI trader)
- Sub-agent calls (Prompt AI, Program AI, Signal AI, Attribution AI)
"""

import json
import logging
from typing import Dict, List, Any, Optional

from sqlalchemy.orm import Session

from services.hyper_ai_binding_tools import (
    execute_bind_program_to_trader,
    execute_bind_prompt_to_trader,
    execute_save_memory,
    execute_update_ai_trader,
    execute_update_program_binding,
    execute_update_prompt_binding,
    execute_update_signal_pool,
    execute_update_trader_strategy,
)
from services.hyper_ai_creation_tools import (
    execute_create_ai_trader,
    execute_save_program,
    execute_save_prompt,
    execute_save_signal_pool,
)
from services.hyper_ai_factor_tools import (
    execute_compute_factor,
    execute_edit_factor,
    execute_evaluate_factor,
    execute_get_factor_functions,
    execute_query_factors,
    execute_save_factor,
)
from services.hyper_ai_diagnostic_tools import (
    execute_diagnose_trader_issues,
    execute_update_watchlist,
)
from services.hyper_ai_dream_service import execute_run_dream_review
from services.hyper_ai_goal_planner import execute_plan_trading_goal
from services.hyper_ai_project_repair_tools import (
    execute_inspect_project_health,
    execute_run_safe_project_repair,
)
from services.hyper_ai_operator_tools import (
    execute_read_project_file,
    execute_restart_backend_service,
    execute_run_project_command,
    execute_write_project_file,
)
from services.hyper_ai_status_tools import (
    execute_get_api_reference,
    execute_get_contact_config,
    execute_get_klines,
    execute_get_market_flow,
    execute_get_market_regime,
    execute_get_robot_architecture,
    execute_get_system_logs,
    execute_get_system_overview,
    execute_get_trading_environment,
    execute_get_wallet_status,
    execute_get_watchlist,
)
from services.hyper_ai_listing_tools import (
    execute_analyze_tracked_address,
    execute_list_signal_pools,
    execute_list_strategies,
    execute_list_traders,
)
from services.hyper_ai_strategy_radar_tools import (
    execute_get_strategy_radar_universe,
    execute_get_tracked_wallets,
    execute_search_strategy_radar,
)
from services.hyper_ai_subagents import execute_subagent_tool
from services.hyper_ai_tool_definitions import HYPER_AI_TOOLS
from services.hyper_ai_web_tools import execute_fetch_url, execute_web_search

logger = logging.getLogger(__name__)


# Tool definitions live in services.hyper_ai_tool_definitions.

# =============================================================================
# Tool Execution Functions
# =============================================================================

def execute_hyper_ai_tool(
    db: Session, tool_name: str, arguments: Dict[str, Any],
    user_id: int = 1, api_config: Optional[Dict[str, Any]] = None
) -> str:
    """Execute a Hyper AI tool by name."""
    try:
        if tool_name == "get_system_overview":
            return execute_get_system_overview(db)

        elif tool_name == "get_robot_architecture":
            return execute_get_robot_architecture(
                db,
                include_recent_activity=arguments.get("include_recent_activity", True),
            )

        elif tool_name == "get_wallet_status":
            return execute_get_wallet_status(
                db,
                exchange=arguments.get("exchange", "all"),
                environment=arguments.get("environment", "all")
            )

        elif tool_name == "get_api_reference":
            return execute_get_api_reference(
                doc_type=arguments.get("doc_type", "prompt"),
                api_type=arguments.get("api_type", "all"),
                lang=arguments.get("lang", "en")
            )

        elif tool_name == "get_klines":
            return execute_get_klines(
                db,
                symbol=arguments.get("symbol", "BTC"),
                period=arguments.get("period", "1h"),
                limit=arguments.get("limit", 50),
                exchange=arguments.get("exchange", "hyperliquid")
            )

        elif tool_name == "get_market_regime":
            return execute_get_market_regime(
                db,
                symbol=arguments.get("symbol", "BTC"),
                period=arguments.get("period", "1h"),
                exchange=arguments.get("exchange", "hyperliquid")
            )

        elif tool_name == "get_market_flow":
            return execute_get_market_flow(
                db,
                symbol=arguments.get("symbol", "BTC"),
                period=arguments.get("period", "1h"),
                exchange=arguments.get("exchange", "hyperliquid")
            )

        elif tool_name == "get_system_logs":
            return execute_get_system_logs(
                db,
                level=arguments.get("level", "error"),
                limit=arguments.get("limit", 20),
                trader_id=arguments.get("trader_id")
            )

        elif tool_name == "get_contact_config":
            return execute_get_contact_config()

        elif tool_name == "get_trading_environment":
            return execute_get_trading_environment(db)

        elif tool_name == "get_watchlist":
            return execute_get_watchlist(db)

        elif tool_name == "plan_trading_goal":
            return execute_plan_trading_goal(
                db,
                starting_capital=arguments.get("starting_capital"),
                target_capital=arguments.get("target_capital"),
                time_horizon_days=arguments.get("time_horizon_days"),
                time_horizon_text=arguments.get("time_horizon_text"),
                exchange=arguments.get("exchange", "unknown"),
                environment=arguments.get("environment", "unknown"),
                max_loss=arguments.get("max_loss"),
                risk_mode=arguments.get("risk_mode", "unknown"),
                preferred_symbols=arguments.get("preferred_symbols"),
                strategy_type=arguments.get("strategy_type", "unknown"),
                existing_trader_id=arguments.get("existing_trader_id"),
                notes=arguments.get("notes"),
            )

        elif tool_name == "update_watchlist":
            return execute_update_watchlist(
                db,
                exchange=arguments.get("exchange"),
                symbols=arguments.get("symbols", [])
            )

        elif tool_name == "diagnose_trader_issues":
            return execute_diagnose_trader_issues(db, trader_id=arguments.get("trader_id"))

        elif tool_name == "inspect_project_health":
            return execute_inspect_project_health(
                db,
                scope=arguments.get("scope", "all"),
                include_logs=arguments.get("include_logs", True),
                log_limit=arguments.get("log_limit", 30),
            )

        elif tool_name == "read_project_file":
            return execute_read_project_file(
                path=arguments.get("path", ""),
                start_line=arguments.get("start_line", 1),
                end_line=arguments.get("end_line"),
                max_chars=arguments.get("max_chars", 20000),
            )

        elif tool_name == "analyze_tracked_address":
            return execute_analyze_tracked_address(
                db,
                address=arguments.get("address", ""),
            )

        elif tool_name == "get_tracked_wallets":
            return execute_get_tracked_wallets(db)

        elif tool_name == "get_strategy_radar_universe":
            return execute_get_strategy_radar_universe(db)

        elif tool_name == "search_strategy_radar":
            return execute_search_strategy_radar(
                db,
                symbol=arguments.get("symbol", ""),
                period=arguments.get("period", "1h"),
                regime=arguments.get("regime"),
                exchange=arguments.get("exchange"),
                strategy_type=arguments.get("strategy_type"),
                sort_by=arguments.get("sort_by"),
                risk_level=arguments.get("risk_level"),
                timeframe=arguments.get("timeframe"),
                limit=arguments.get("limit", 5),
            )

        elif tool_name == "save_signal_pool":
            return execute_save_signal_pool(
                db,
                pool_name=arguments.get("pool_name"),
                symbol=arguments.get("symbol", "BTC"),
                signals=arguments.get("signals", []),
                logic=arguments.get("logic", "AND"),
                exchange=arguments.get("exchange", "hyperliquid"),
                description=arguments.get("description")
            )

        elif tool_name == "save_prompt":
            return execute_save_prompt(
                db,
                name=arguments.get("name"),
                template_text=arguments.get("template_text"),
                prompt_id=arguments.get("prompt_id"),
                description=arguments.get("description")
            )

        elif tool_name == "save_program":
            return execute_save_program(
                db,
                name=arguments.get("name"),
                code=arguments.get("code"),
                program_id=arguments.get("program_id"),
                description=arguments.get("description")
            )

        elif tool_name == "create_ai_trader":
            return execute_create_ai_trader(
                db,
                name=arguments.get("name"),
                model=arguments.get("model"),
                base_url=arguments.get("base_url"),
                api_key=arguments.get("api_key")
            )

        # --- Query tools: list resources ---
        elif tool_name == "list_traders":
            return execute_list_traders(db, trader_id=arguments.get("trader_id"))

        elif tool_name == "list_signal_pools":
            return execute_list_signal_pools(db, pool_id=arguments.get("pool_id"))

        elif tool_name == "list_strategies":
            return execute_list_strategies(
                db,
                strategy_id=arguments.get("strategy_id"),
                strategy_type=arguments.get("strategy_type")
            )

        # --- Binding tools: assemble components ---
        elif tool_name == "bind_prompt_to_trader":
            return execute_bind_prompt_to_trader(
                db,
                trader_id=arguments.get("trader_id"),
                prompt_id=arguments.get("prompt_id")
            )

        elif tool_name == "bind_program_to_trader":
            return execute_bind_program_to_trader(
                db,
                trader_id=arguments.get("trader_id"),
                program_id=arguments.get("program_id"),
                exchange=arguments.get("exchange", "hyperliquid"),
                signal_pool_ids=arguments.get("signal_pool_ids"),
                trigger_interval=arguments.get("trigger_interval", 180),
                is_active=arguments.get("is_active", True)
            )

        elif tool_name == "update_trader_strategy":
            return execute_update_trader_strategy(
                db,
                trader_id=arguments.get("trader_id"),
                signal_pool_ids=arguments.get("signal_pool_ids"),
                scheduled_trigger_enabled=arguments.get("scheduled_trigger_enabled"),
                trigger_interval=arguments.get("trigger_interval"),
                exchange=arguments.get("exchange")
            )

        # --- Update tools ---
        elif tool_name == "update_ai_trader":
            return execute_update_ai_trader(
                db, trader_id=arguments.get("trader_id"),
                name=arguments.get("name"), model=arguments.get("model"),
                base_url=arguments.get("base_url"), api_key=arguments.get("api_key")
            )

        elif tool_name == "update_program_binding":
            return execute_update_program_binding(
                db, binding_id=arguments.get("binding_id"),
                signal_pool_ids=arguments.get("signal_pool_ids"),
                trigger_interval=arguments.get("trigger_interval"),
                scheduled_trigger_enabled=arguments.get("scheduled_trigger_enabled"),
                is_active=arguments.get("is_active"),
                params_override=arguments.get("params_override")
            )

        elif tool_name == "update_signal_pool":
            return execute_update_signal_pool(
                db, pool_id=arguments.get("pool_id"),
                pool_name=arguments.get("pool_name"),
                enabled=arguments.get("enabled"),
                logic=arguments.get("logic"),
                signal_ids=arguments.get("signal_ids")
            )

        elif tool_name == "update_prompt_binding":
            return execute_update_prompt_binding(
                db, trader_id=arguments.get("trader_id"),
                prompt_id=arguments.get("prompt_id")
            )

        # --- Skill tools: load workflow guidance (no side effects) ---
        elif tool_name == "load_skill":
            from services.hyper_ai_skill_engine import load_skill
            return json.dumps(load_skill(skill_name=arguments.get("skill_name", "")))

        elif tool_name == "load_skill_reference":
            from services.hyper_ai_skill_engine import load_skill_reference
            return json.dumps(load_skill_reference(
                skill_name=arguments.get("skill_name", ""),
                reference_file=arguments.get("reference_file", "")
            ))

        elif tool_name == "save_memory":
            return execute_save_memory(
                db,
                category=arguments.get("category", "context"),
                content=arguments.get("content", ""),
                importance=arguments.get("importance", 0.5),
                api_config=api_config
            )

        elif tool_name == "run_dream_review":
            return execute_run_dream_review(
                db,
                conversation_id=arguments.get("conversation_id"),
                conversation_ids=arguments.get("conversation_ids"),
                hours=arguments.get("hours", 24),
                max_messages=arguments.get("max_messages", 80),
                save_memories=arguments.get("save_memories", True),
                wait_for_memory_write=arguments.get("wait_for_memory_write", False),
                api_config=api_config,
            )

        elif tool_name == "run_safe_project_repair":
            return execute_run_safe_project_repair(
                db,
                action=arguments.get("action", "auto"),
                dry_run=arguments.get("dry_run", False),
                reason=arguments.get("reason"),
            )

        elif tool_name == "write_project_file":
            return execute_write_project_file(
                path=arguments.get("path", ""),
                content=arguments.get("content", ""),
                expected_sha256=arguments.get("expected_sha256"),
                create=arguments.get("create", False),
                reason=arguments.get("reason"),
            )

        elif tool_name == "run_project_command":
            return execute_run_project_command(
                command=arguments.get("command", ""),
                working_dir=arguments.get("working_dir", "."),
                timeout_seconds=arguments.get("timeout_seconds", 60),
                reason=arguments.get("reason"),
            )

        elif tool_name == "restart_backend_service":
            return execute_restart_backend_service(
                reason=arguments.get("reason"),
                delay_seconds=arguments.get("delay_seconds", 2),
            )

        # --- Factor tools ---
        elif tool_name == "query_factors":
            return execute_query_factors(
                db, exchange=arguments.get("exchange", "hyperliquid"),
                symbol=arguments.get("symbol"),
                factor_name=arguments.get("factor_name"),
                forward_period=arguments.get("forward_period", "4h"),
                days=arguments.get("days", 30)
            )

        elif tool_name == "evaluate_factor":
            return execute_evaluate_factor(
                db, expression=arguments.get("expression", ""),
                symbol=arguments.get("symbol", "BTC"),
                exchange=arguments.get("exchange", "hyperliquid")
            )

        elif tool_name == "save_factor":
            return execute_save_factor(
                db, name=arguments.get("name", ""),
                expression=arguments.get("expression", ""),
                description=arguments.get("description", "")
            )

        elif tool_name == "edit_factor":
            return execute_edit_factor(
                db, factor_id=arguments.get("factor_id"),
                name=arguments.get("name"),
                expression=arguments.get("expression"),
                description=arguments.get("description")
            )

        elif tool_name == "compute_factor":
            return execute_compute_factor(
                db, factor_name=arguments.get("factor_name", ""),
                exchange=arguments.get("exchange", "hyperliquid")
            )

        elif tool_name == "get_factor_functions":
            return execute_get_factor_functions(
                category=arguments.get("category")
            )

        # --- External tools ---
        elif tool_name == "web_search":
            return execute_web_search(
                db, query=arguments.get("query", ""),
                max_results=arguments.get("max_results", 5)
            )

        elif tool_name == "fetch_url":
            return execute_fetch_url(
                url=arguments.get("url", ""),
                max_length=arguments.get("max_length", 8000)
            )

        # --- Delete tools ---
        elif tool_name == "delete_trader":
            from services.entity_deletion_service import delete_trader
            return json.dumps(delete_trader(db, trader_id=arguments.get("trader_id")), indent=2)

        elif tool_name == "delete_prompt_template":
            from services.entity_deletion_service import delete_prompt_template
            return json.dumps(delete_prompt_template(db, prompt_id=arguments.get("prompt_id")), indent=2)

        elif tool_name == "delete_signal_definition":
            from services.entity_deletion_service import delete_signal_definition
            return json.dumps(delete_signal_definition(db, signal_id=arguments.get("signal_id")), indent=2)

        elif tool_name == "delete_signal_pool":
            from services.entity_deletion_service import delete_signal_pool
            return json.dumps(delete_signal_pool(db, pool_id=arguments.get("pool_id")), indent=2)

        elif tool_name == "delete_trading_program":
            from services.entity_deletion_service import delete_trading_program
            return json.dumps(delete_trading_program(db, program_id=arguments.get("program_id")), indent=2)

        elif tool_name == "delete_prompt_binding":
            from services.entity_deletion_service import delete_prompt_binding
            return json.dumps(delete_prompt_binding(db, binding_id=arguments.get("binding_id")), indent=2)

        elif tool_name == "delete_program_binding":
            from services.entity_deletion_service import delete_program_binding
            return json.dumps(delete_program_binding(db, binding_id=arguments.get("binding_id")), indent=2)

        # Sub-agent tools are handled directly in hyper_ai_service.py main loop
        # via _execute_tool_with_progress() which uses yield from for progress events.
        # This branch should not be reached but kept as safety fallback.
        elif tool_name in ("call_prompt_ai", "call_program_ai", "call_signal_ai", "call_attribution_ai"):
            logger.warning(f"[execute_hyper_ai_tool] Sub-agent {tool_name} reached fallback path")
            return execute_subagent_tool(db, tool_name, arguments, user_id=user_id)

        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    except Exception as e:
        logger.error(f"[execute_hyper_ai_tool] Error executing {tool_name}: {e}")
        return json.dumps({"error": str(e), "_error_class": type(e).__name__})
