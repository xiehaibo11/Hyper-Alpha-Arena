"""Tool dispatcher for AI signal generation."""

from __future__ import annotations

import json
import logging
from typing import Dict

from sqlalchemy.orm import Session

from services.ai_signal_indicator_tools import _tool_get_indicators_batch, _tool_get_kline_context
from services.ai_signal_prediction_tools import _tool_predict_signal_combination

logger = logging.getLogger(__name__)


def _execute_tool(db: Session, tool_name: str, arguments: Dict) -> str:
    """Execute a tool and return JSON result."""
    try:
        exchange = arguments.get("exchange", "hyperliquid")

        if tool_name == "get_kline_context":
            result = _tool_get_kline_context(
                db=db,
                symbol=arguments.get("symbol", "BTC"),
                timestamps=arguments.get("timestamps", []),
                time_window=arguments.get("time_window", "5m"),
                exchange=exchange,
            )
        elif tool_name == "get_indicators_batch":
            result = _tool_get_indicators_batch(
                db=db,
                symbol=arguments.get("symbol", "BTC"),
                indicators=arguments.get("indicators", []),
                time_window=arguments.get("time_window", "5m"),
                exchange=exchange,
            )
        elif tool_name == "predict_signal_combination":
            result = _tool_predict_signal_combination(
                db=db,
                symbol=arguments.get("symbol", "BTC"),
                signals=arguments.get("signals", []),
                logic=arguments.get("logic", "AND"),
                exchange=exchange,
            )
        else:
            result = {"error": f"Unknown tool: {tool_name}"}

        return json.dumps(result)
    except Exception as exc:
        logger.error(f"Tool execution error: {tool_name} - {exc}")
        return json.dumps({"error": str(exc)})
