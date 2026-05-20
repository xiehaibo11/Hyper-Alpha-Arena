"""Runtime contracts for Hyper AI tools.

This module bridges the static OpenAI-compatible tool definitions and the
runtime executor. It keeps validation and tool metadata close to the tool
catalog without changing individual tool implementations.
"""

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from services.ai_exchange_query_tools import EXCHANGE_QUERY_TOOLS
from services.binance_full_api_tools import BINANCE_FULL_API_TOOLS
from services.hyper_ai_subagents import SUBAGENT_TOOLS
from services.hyper_ai_tool_definitions import EXTERNAL_TOOLS, SKILL_TOOLS
from services.hyper_ai_tool_defs_factor import FACTOR_TOOLS
from services.hyper_ai_tool_defs_read import READ_ONLY_TOOLS
from services.hyper_ai_tool_defs_write import WRITE_TOOLS


RISK_READONLY = "readonly"
RISK_LOW_WRITE = "low_write"
RISK_HIGH = "high_risk"


READONLY_TOOL_NAMES: Set[str] = {
    "get_system_overview",
    "get_robot_architecture",
    "get_wallet_status",
    "get_api_reference",
    "get_klines",
    "get_market_regime",
    "get_market_flow",
    "get_system_logs",
    "get_contact_config",
    "get_trading_environment",
    "get_watchlist",
    "plan_trading_goal",
    "diagnose_trader_issues",
    "inspect_project_health",
    "read_project_file",
    "analyze_tracked_address",
    "get_tracked_wallets",
    "get_strategy_radar_universe",
    "search_strategy_radar",
    "list_traders",
    "list_signal_pools",
    "list_strategies",
    "query_factors",
    "evaluate_factor",
    "get_factor_functions",
    "get_exchange_public_data",
    "list_exchange_instruments",
    "get_exchange_account_data",
    "query_binance_api",
    "get_binance_klines",
    "web_search",
    "fetch_url",
    "load_skill",
    "load_skill_reference",
    "call_prompt_ai",
    "call_program_ai",
    "call_signal_ai",
    "call_attribution_ai",
    "coordinate_all_ai",
}

LOW_WRITE_TOOL_NAMES: Set[str] = {
    "save_signal_pool",
    "save_prompt",
    "save_program",
    "create_ai_trader",
    "update_signal_pool",
    "save_factor",
    "edit_factor",
    "compute_factor",
    "update_watchlist",
    "save_memory",
    "run_dream_review",
    "run_safe_project_repair",
    "write_project_file",
    "run_project_command",
    "restart_backend_service",
}

HIGH_RISK_TOOL_NAMES: Set[str] = {
    "bind_prompt_to_trader",
    "bind_program_to_trader",
    "update_trader_strategy",
    "update_ai_trader",
    "update_program_binding",
    "update_prompt_binding",
    "delete_trader",
    "delete_prompt_template",
    "delete_signal_definition",
    "delete_signal_pool",
    "delete_trading_program",
    "delete_prompt_binding",
    "delete_program_binding",
}

# Safe to execute concurrently in a later executor because they are read-only and
# should not mutate application state. Sub-agents are intentionally excluded
# because they run nested agent loops.
CONCURRENCY_SAFE_TOOL_NAMES: Set[str] = READONLY_TOOL_NAMES - {
    "coordinate_all_ai",
    "call_prompt_ai",
    "call_program_ai",
    "call_signal_ai",
    "call_attribution_ai",
}


@dataclass(frozen=True)
class HyperAIToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]
    required: Tuple[str, ...]
    group: str
    risk_level: str
    concurrency_safe: bool


@dataclass
class ToolValidationResult:
    tool_name: str
    ok: bool
    arguments: Dict[str, Any]
    errors: List[str]
    warnings: List[str]


def _definition_groups() -> List[Tuple[str, List[Dict[str, Any]]]]:
    return [
        ("read", READ_ONLY_TOOLS),
        ("exchange", EXCHANGE_QUERY_TOOLS),
        ("binance", BINANCE_FULL_API_TOOLS),
        ("write", WRITE_TOOLS),
        ("factor", FACTOR_TOOLS),
        ("external", EXTERNAL_TOOLS),
        ("skill", SKILL_TOOLS),
        ("subagent", SUBAGENT_TOOLS),
    ]


def _risk_level(tool_name: str) -> str:
    if tool_name in HIGH_RISK_TOOL_NAMES:
        return RISK_HIGH
    if tool_name in LOW_WRITE_TOOL_NAMES:
        return RISK_LOW_WRITE
    return RISK_READONLY


def _iter_tool_specs() -> Iterable[HyperAIToolSpec]:
    for group, tool_defs in _definition_groups():
        for item in tool_defs:
            function = item.get("function") if isinstance(item, dict) else None
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            if not name:
                continue
            parameters = function.get("parameters") or {"type": "object", "properties": {}, "required": []}
            required = tuple(parameters.get("required") or [])
            yield HyperAIToolSpec(
                name=name,
                description=function.get("description") or "",
                parameters=parameters,
                required=required,
                group=group,
                risk_level=_risk_level(name),
                concurrency_safe=name in CONCURRENCY_SAFE_TOOL_NAMES,
            )


def _build_registry() -> Dict[str, HyperAIToolSpec]:
    registry: Dict[str, HyperAIToolSpec] = {}
    for spec in _iter_tool_specs():
        registry[spec.name] = spec
    return registry


TOOL_RUNTIME_REGISTRY: Dict[str, HyperAIToolSpec] = _build_registry()


def get_tool_runtime_spec(tool_name: str) -> Optional[HyperAIToolSpec]:
    return TOOL_RUNTIME_REGISTRY.get(tool_name)


def _type_names(schema: Dict[str, Any]) -> List[str]:
    raw_type = schema.get("type")
    if isinstance(raw_type, list):
        return [str(item) for item in raw_type]
    if isinstance(raw_type, str):
        return [raw_type]
    return []


def _coerce_scalar(value: Any, expected_type: str) -> Any:
    if expected_type == "integer" and isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"-?\d+", text):
            return int(text)
    if expected_type == "number" and isinstance(value, str):
        text = value.strip()
        try:
            return float(text)
        except ValueError:
            return value
    if expected_type == "boolean" and isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return value


def _matches_type(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    return True


def _validate_value(value: Any, schema: Dict[str, Any], path: str, errors: List[str]) -> Any:
    expected_types = _type_names(schema)
    normalized = value
    if expected_types:
        normalized = _coerce_scalar(value, expected_types[0])
        if not any(_matches_type(normalized, expected_type) for expected_type in expected_types):
            errors.append(f"{path} must be {', '.join(expected_types)}")
            return value

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and normalized not in enum_values:
        errors.append(f"{path} must be one of {enum_values}")

    if isinstance(normalized, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            return [
                _validate_value(item, item_schema, f"{path}[{index}]", errors)
                for index, item in enumerate(normalized)
            ]
        return normalized

    if isinstance(normalized, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            return _validate_object(normalized, schema, path, errors)

    return normalized


def _validate_object(
    arguments: Dict[str, Any],
    schema: Dict[str, Any],
    path: str,
    errors: List[str],
) -> Dict[str, Any]:
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    normalized = dict(arguments)

    for key in required:
        value = normalized.get(key)
        if value is None or value == "":
            errors.append(f"{path}.{key} is required")

    for key, prop_schema in properties.items():
        if key not in normalized:
            if isinstance(prop_schema, dict) and "default" in prop_schema:
                normalized[key] = prop_schema["default"]
            continue
        if isinstance(prop_schema, dict):
            normalized[key] = _validate_value(normalized[key], prop_schema, f"{path}.{key}", errors)

    return normalized


def validate_tool_arguments(tool_name: str, arguments: Any) -> ToolValidationResult:
    spec = get_tool_runtime_spec(tool_name)
    if not spec:
        return ToolValidationResult(
            tool_name=tool_name,
            ok=False,
            arguments=arguments if isinstance(arguments, dict) else {},
            errors=[f"Unknown tool: {tool_name}"],
            warnings=[],
        )

    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return ToolValidationResult(
            tool_name=tool_name,
            ok=False,
            arguments={},
            errors=[f"{tool_name} arguments must be an object"],
            warnings=[],
        )

    errors: List[str] = []
    normalized = _validate_object(arguments, spec.parameters, tool_name, errors)
    unknown = sorted(set(normalized) - set((spec.parameters.get("properties") or {}).keys()))
    warnings = [f"Ignoring undocumented argument: {key}" for key in unknown]

    return ToolValidationResult(
        tool_name=tool_name,
        ok=not errors,
        arguments=normalized,
        errors=errors,
        warnings=warnings,
    )


def format_tool_validation_errors(validation: ToolValidationResult) -> str:
    if validation.ok:
        return ""
    details = "; ".join(validation.errors)
    return f"Tool call rejected by runtime schema validation: {details}"


def _max_parallel_readonly_workers() -> int:
    try:
        return max(1, int(os.getenv("HYPER_AI_MAX_PARALLEL_READONLY_TOOLS", "6")))
    except ValueError:
        return 6


def get_tool_runtime_snapshot() -> Dict[str, Any]:
    names = list(TOOL_RUNTIME_REGISTRY)
    classified = READONLY_TOOL_NAMES | LOW_WRITE_TOOL_NAMES | HIGH_RISK_TOOL_NAMES
    max_parallel_workers = _max_parallel_readonly_workers()
    return {
        "total": len(names),
        "schema_validated": len(names),
        "concurrency_safe": len([name for name in names if name in CONCURRENCY_SAFE_TOOL_NAMES]),
        "parallel_execution": {
            "enabled": max_parallel_workers > 1,
            "max_readonly_workers": max_parallel_workers,
        },
        "risk_counts": {
            RISK_READONLY: len([name for name in names if name in READONLY_TOOL_NAMES]),
            RISK_LOW_WRITE: len([name for name in names if name in LOW_WRITE_TOOL_NAMES]),
            RISK_HIGH: len([name for name in names if name in HIGH_RISK_TOOL_NAMES]),
        },
        "missing_risk_metadata": sorted(set(names) - classified),
        "stale_risk_metadata": sorted(classified - set(names)),
    }
