"""Add on-demand skills and web tools to AI Trader decisions."""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

DECISION_SKILLS = ("skill-install",)
MAX_TOOL_ROUNDS = 2
_PATCHED = False


def build_decision_skill_guardrails() -> str:
    skills = ", ".join(DECISION_SKILLS)
    return (
        "\n\nOn-demand decision tools:\n"
        f"- Skills installed for this decision AI: {skills}.\n"
        "- When the market setup is unclear or risk logic needs review, call "
        "`load_skill` with `skill_name=\"skill-install\"` instead of relying on memory.\n"
        "- When current external research, news, or strategy references are needed, call "
        "`web_search`, then `fetch_url` for the most relevant result.\n"
        "- Do not call tools for every tick. Use them only when they materially improve the decision.\n"
    )


def _decision_tool_definitions() -> List[Dict[str, Any]]:
    from services.hyper_ai_tool_definitions import EXTERNAL_TOOLS, SKILL_TOOLS

    allowed = {"load_skill", "web_search", "fetch_url"}
    tools = []
    for tool in SKILL_TOOLS + EXTERNAL_TOOLS:
        fn = tool.get("function", {})
        if fn.get("name") in allowed:
            tools.append(tool)
    return tools


def _is_decision_payload(payload: Dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or payload.get("tools"):
        return False
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return False
    for message in messages:
        if message.get("role") != "system":
            continue
        content = str(message.get("content") or "")
        if "AI Trader execution layer" in content:
            return True
    return False


def _parse_tool_args(raw_args: Any) -> Dict[str, Any]:
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str) and raw_args.strip():
        try:
            parsed = json.loads(raw_args)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _execute_decision_tool(db, name: str, args: Dict[str, Any]) -> str:
    if name == "load_skill":
        from services.hyper_ai_skill_engine import load_skill

        skill_name = args.get("skill_name")
        if skill_name not in DECISION_SKILLS:
            return json.dumps({"error": f"Skill '{skill_name}' is not installed for AI decisions."})
        return json.dumps(load_skill(skill_name), ensure_ascii=False)

    if name == "web_search":
        from services.hyper_ai_web_tools import execute_web_search

        return execute_web_search(db, args.get("query", ""), int(args.get("max_results", 5) or 5))

    if name == "fetch_url":
        from services.hyper_ai_web_tools import execute_fetch_url

        return execute_fetch_url(args.get("url", ""), int(args.get("max_length", 8000) or 8000))

    return json.dumps({"error": f"Unsupported decision tool: {name}"})


def _tool_calls_from_response(response) -> List[Dict[str, Any]]:
    if response.status_code != 200:
        return []
    try:
        result = response.json()
    except Exception:
        return []
    choices = result.get("choices") or []
    if not choices:
        return []
    message = (choices[0] or {}).get("message") or {}
    calls = message.get("tool_calls") or []
    return calls if isinstance(calls, list) else []


def _append_tool_messages(messages: List[Dict[str, Any]], response, db) -> None:
    result = response.json()
    message = result["choices"][0]["message"]
    tool_calls = message.get("tool_calls") or []
    messages.append({
        "role": "assistant",
        "content": message.get("content") or "",
        "tool_calls": tool_calls,
    })

    for call in tool_calls:
        fn = call.get("function") or {}
        name = fn.get("name") or ""
        args = _parse_tool_args(fn.get("arguments"))
        try:
            tool_result = _execute_decision_tool(db, name, args)
        except Exception as exc:
            logger.error("AI decision tool %s failed: %s", name, exc, exc_info=True)
            tool_result = json.dumps({"error": str(exc)})
        messages.append({
            "role": "tool",
            "tool_call_id": call.get("id"),
            "name": name,
            "content": str(tool_result)[:15000],
        })


def _decision_post_with_tools(original_post, *args, **kwargs):
    payload = kwargs.get("json")
    if not _is_decision_payload(payload) or kwargs.get("stream"):
        return original_post(*args, **kwargs)

    from database.connection import SessionLocal

    working_payload = copy.deepcopy(payload)
    working_payload["tools"] = _decision_tool_definitions()
    working_payload["tool_choice"] = "auto"
    working_kwargs = dict(kwargs)
    working_kwargs["json"] = working_payload

    with SessionLocal() as db:
        for _ in range(MAX_TOOL_ROUNDS):
            response = original_post(*args, **working_kwargs)
            if not _tool_calls_from_response(response):
                return response
            _append_tool_messages(working_payload["messages"], response, db)

        final_payload = copy.deepcopy(working_payload)
        final_payload.pop("tools", None)
        final_payload.pop("tool_choice", None)
        working_kwargs["json"] = final_payload
        return original_post(*args, **working_kwargs)


def install_ai_decision_skill_guardrails_patch() -> bool:
    global _PATCHED
    if _PATCHED:
        return True

    from services import ai_decision_service

    original_guardrails = ai_decision_service._build_ai_trader_system_guardrails
    if not getattr(original_guardrails, "_decision_skill_patched", False):
        def patched_guardrails(context: Dict[str, Any]) -> str:
            return f"{original_guardrails(context)}{build_decision_skill_guardrails()}"

        setattr(patched_guardrails, "_decision_skill_patched", True)
        ai_decision_service._build_ai_trader_system_guardrails = patched_guardrails

    original_post = ai_decision_service.requests.post
    if not getattr(original_post, "_decision_tools_patched", False):
        def patched_post(*args, **kwargs):
            return _decision_post_with_tools(original_post, *args, **kwargs)

        setattr(patched_post, "_decision_tools_patched", True)
        ai_decision_service.requests.post = patched_post

    _PATCHED = True
    logger.info("Installed on-demand AI decision skills/tools: %s", ", ".join(DECISION_SKILLS))
    return True
