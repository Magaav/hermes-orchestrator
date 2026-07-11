from __future__ import annotations

import json
from typing import Any


def request_fields(body: dict[str, Any]) -> dict[str, Any]:
    raw = body.get("tools")
    if not isinstance(raw, list) or not raw:
        return {}
    tools = []
    for item in raw[:16]:
        if not isinstance(item, dict): continue
        function = item.get("function") if isinstance(item.get("function"), dict) else item
        name = str(function.get("name") or "").strip()
        if not name: continue
        parameters = function.get("parameters") if isinstance(function.get("parameters"), dict) else function.get("input_schema")
        tools.append({"type": "function", "function": {"name": name[:80], "description": str(function.get("description") or "")[:500], "parameters": parameters if isinstance(parameters, dict) else {"type": "object"}}})
    if not tools: return {}
    choice = body.get("tool_choice") or body.get("toolChoice") or "auto"
    return {"tools": tools, "tool_choice": choice}


def response_calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    raw = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else payload.get("tool_calls")
    calls = []
    for index, item in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(item, dict): continue
        function = item.get("function") if isinstance(item.get("function"), dict) else item
        name = str(function.get("name") or item.get("name") or "").strip()
        arguments = function.get("arguments", item.get("arguments", {}))
        if isinstance(arguments, str):
            try: arguments = json.loads(arguments)
            except json.JSONDecodeError: arguments = {}
        if name: calls.append({"id": str(item.get("id") or f"call_{index + 1}"), "name": name, "arguments": arguments if isinstance(arguments, dict) else {}})
    return calls

