"""Parse AI-generated signal configuration blocks."""

from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def extract_signal_configs(content: str) -> List[Dict]:
    configs = []

    signal_pattern = r"```signal-config\s*([\s\S]*?)```"
    for match in re.findall(signal_pattern, content):
        try:
            config = json.loads(match.strip())
            config["_type"] = "signal"
            configs.append(config)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse signal config: %s", exc)

    pool_pattern = r"```signal-pool-config\s*([\s\S]*?)```"
    for match in re.findall(pool_pattern, content):
        try:
            config = json.loads(match.strip())
            config["_type"] = "pool"
            configs.append(config)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse signal pool config: %s", exc)

    if configs:
        return configs

    logger.info("No exact code block match, attempting fallback parsing")
    json_pattern = r"```json\s*([\s\S]*?)```"
    for match in re.findall(json_pattern, content):
        config = _try_parse_signal_json(match.strip())
        if config:
            configs.append(config)

    if configs:
        return configs

    json_start_pattern = r'\{\s*"name"\s*:'
    for match in re.finditer(json_start_pattern, content):
        json_obj = _extract_balanced_json(content, match.start())
        if json_obj:
            config = _try_parse_signal_json(json_obj)
            if config:
                configs.append(config)
                break

    return configs


def _extract_balanced_json(content: str, start_idx: int) -> Optional[str]:
    if start_idx >= len(content) or content[start_idx] != "{":
        return None

    depth = 0
    in_string = False
    escape_next = False

    for index in range(start_idx, len(content)):
        char = content[index]
        if escape_next:
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[start_idx:index + 1]

    return None


def _try_parse_signal_json(json_str: str) -> Optional[Dict]:
    try:
        config = json.loads(json_str)
        if not isinstance(config, dict) or "name" not in config:
            return None

        if "signals" in config and isinstance(config.get("signals"), list):
            config["_type"] = "pool"
        elif "logic" in config:
            config["_type"] = "pool"
        elif "trigger_condition" in config:
            config["_type"] = "signal"
        else:
            config["_type"] = "signal"

        logger.info("Fallback parsing succeeded: type=%s, name=%s", config["_type"], config.get("name"))
        return config
    except json.JSONDecodeError as exc:
        logger.warning("Fallback JSON parse failed: %s", exc)
        return None
