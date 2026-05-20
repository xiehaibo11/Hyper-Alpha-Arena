"""Hyper AI tool dispatch overrides for split tool implementations."""

from __future__ import annotations

from typing import Any, Dict, Optional

from services.ai_exchange_query_tools import EXCHANGE_QUERY_TOOL_NAMES, execute_exchange_query_tool
from services.binance_full_api_tools import BINANCE_FULL_API_TOOL_NAMES, execute_binance_full_api_tool
from sqlalchemy.orm import Session

from services.hyper_ai_tools import execute_hyper_ai_tool as execute_legacy_hyper_ai_tool
from services.hyper_ai_wallet_status import execute_get_wallet_status


def execute_hyper_ai_tool(
    db: Session,
    tool_name: str,
    arguments: Dict[str, Any],
    user_id: int = 1,
    api_config: Optional[Dict[str, Any]] = None,
) -> str:
    if tool_name == "get_wallet_status":
        args = arguments or {}
        return execute_get_wallet_status(
            db,
            exchange=args.get("exchange", "all"),
            environment=args.get("environment", "all"),
        )

    if tool_name in EXCHANGE_QUERY_TOOL_NAMES:
        return execute_exchange_query_tool(db, tool_name, arguments or {})

    if tool_name in BINANCE_FULL_API_TOOL_NAMES:
        return execute_binance_full_api_tool(db, tool_name, arguments or {})

    return execute_legacy_hyper_ai_tool(
        db,
        tool_name,
        arguments,
        user_id=user_id,
        api_config=api_config,
    )
