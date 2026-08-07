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


def responses_request_fields(body: dict[str, Any]) -> dict[str, Any]:
    chat_fields = request_fields(body)
    tools = []
    for item in chat_fields.get("tools") or []:
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        tools.append({
            "type": "function",
            "name": function.get("name"),
            "description": function.get("description") or "",
            "parameters": function.get("parameters") or {"type": "object"},
        })
    if not tools:
        return {}
    return {
        "tools": tools,
        "tool_choice": chat_fields.get("tool_choice") or "auto",
        "parallel_tool_calls": False,
    }


def responses_calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
    output = payload.get("output") if isinstance(payload.get("output"), list) else []
    calls = []
    for index, item in enumerate(output):
        if not isinstance(item, dict) or item.get("type") != "function_call":
            continue
        name = str(item.get("name") or "").strip()
        arguments = item.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        if name:
            calls.append({
                "id": str(item.get("call_id") or item.get("id") or f"call_{index + 1}"),
                "name": name,
                "arguments": arguments if isinstance(arguments, dict) else {},
            })
    return calls[:16]


class ResponsesCallAccumulator:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._aliases: dict[str, str] = {}

    @staticmethod
    def _key(event: dict[str, Any], item: dict[str, Any]) -> str:
        return str(
            item.get("call_id") or item.get("id")
            or event.get("call_id") or event.get("item_id")
            or f"index_{event.get('output_index', 0)}"
        )

    def ingest(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        if item.get("type") == "function_call":
            key = self._key(event, item)
            current = self._items.get(key, {})
            self._items[key] = {**current, **item}
            for alias in (item.get("id"), item.get("call_id")):
                if alias:
                    self._aliases[str(alias)] = key
        if event_type in {"response.function_call_arguments.delta", "response.function_call_arguments.done"}:
            raw_key = self._key(event, item)
            key = self._aliases.get(raw_key, raw_key)
            current = self._items.get(key, {})
            delta = str(event.get("delta") or "")
            arguments = event.get("arguments")
            if isinstance(arguments, str):
                current["arguments"] = arguments
            elif delta:
                current["arguments"] = str(current.get("arguments") or "") + delta
            current["type"] = "function_call"
            current["call_id"] = current.get("call_id") or event.get("call_id") or key
            current["name"] = current.get("name") or event.get("name") or ""
            self._items[key] = current

    def calls(self, completed: dict[str, Any]) -> list[dict[str, Any]]:
        terminal = responses_calls(completed)
        if terminal:
            return terminal
        return responses_calls({"output": list(self._items.values())})
