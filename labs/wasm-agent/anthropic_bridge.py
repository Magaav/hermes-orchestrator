#!/usr/bin/env python3
"""Bounded Anthropic Messages API to Chat Completions compatibility bridge."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    return "\n".join(
        str(item.get("text") or "") for item in value
        if isinstance(item, dict) and item.get("type") == "text" and item.get("text")
    )


def request_to_chat(payload: dict[str, Any], *, model: str, max_tokens: int) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    system = _text(payload.get("system"))
    if system:
        messages.append({"role": "system", "content": system})
    for raw in payload.get("messages") if isinstance(payload.get("messages"), list) else []:
        if not isinstance(raw, dict):
            continue
        role = "assistant" if raw.get("role") == "assistant" else "user"
        content = raw.get("content")
        text = _text(content)
        if text:
            messages.append({"role": role, "content": text})
        if not isinstance(content, list):
            continue
        calls = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                calls.append({
                    "id": str(block.get("id") or "call"), "type": "function",
                    "function": {
                        "name": str(block.get("name") or ""),
                        "arguments": json.dumps(block.get("input") if isinstance(block.get("input"), dict) else {}, separators=(",", ":")),
                    },
                })
            elif block.get("type") == "tool_result":
                result_text = _text(block.get("content")) or str(block.get("content") or "")
                messages.append({"role": "tool", "tool_call_id": str(block.get("tool_use_id") or "call"), "content": result_text})
        if calls:
            messages.append({"role": "assistant", "content": None, "tool_calls": calls})
    if not messages:
        messages = [{"role": "user", "content": "Complete the requested task."}]
    tools = []
    for item in payload.get("tools") if isinstance(payload.get("tools"), list) else []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        tools.append({
            "type": "function", "function": {
                "name": str(item["name"]), "description": str(item.get("description") or ""),
                "parameters": item.get("input_schema") if isinstance(item.get("input_schema"), dict) else {"type": "object"},
            },
        })
    result: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens, "stream": False}
    if tools:
        result.update({"tools": tools, "tool_choice": "auto"})
    return result


def count_tokens(payload: dict[str, Any]) -> dict[str, int]:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return {"input_tokens": max(1, (len(canonical.encode()) + 3) // 4)}


def message(payload: dict[str, Any], *, model: str) -> dict[str, Any]:
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    source = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    content: list[dict[str, Any]] = []
    text = str(source.get("content") or "")
    if text:
        content.append({"type": "text", "text": text})
    for raw in source.get("tool_calls") if isinstance(source.get("tool_calls"), list) else []:
        if not isinstance(raw, dict):
            continue
        function = raw.get("function") if isinstance(raw.get("function"), dict) else raw
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        content.append({
            "type": "tool_use", "id": str(raw.get("id") or "call"),
            "name": str(function.get("name") or ""), "input": arguments if isinstance(arguments, dict) else {},
        })
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return {
        "id": "msg_" + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24],
        "type": "message", "role": "assistant", "model": model, "content": content,
        "stop_reason": "tool_use" if any(item["type"] == "tool_use" for item in content) else "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": int(usage.get("prompt_tokens") or 0), "output_tokens": int(usage.get("completion_tokens") or 0)},
    }


def message_sse(payload: dict[str, Any], *, model: str) -> bytes:
    result = message(payload, model=model)
    events: list[tuple[str, dict[str, Any]]] = [
        ("message_start", {"type": "message_start", "message": {**result, "content": [], "stop_reason": None, "usage": {"input_tokens": result["usage"]["input_tokens"], "output_tokens": 0}}}),
    ]
    for index, item in enumerate(result["content"]):
        if item["type"] == "text":
            events.extend([
                ("content_block_start", {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}}),
                ("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": item["text"]}}),
                ("content_block_stop", {"type": "content_block_stop", "index": index}),
            ])
        else:
            arguments = json.dumps(item["input"], separators=(",", ":"))
            events.extend([
                ("content_block_start", {"type": "content_block_start", "index": index, "content_block": {"type": "tool_use", "id": item["id"], "name": item["name"], "input": {}}}),
                ("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {"type": "input_json_delta", "partial_json": arguments}}),
                ("content_block_stop", {"type": "content_block_stop", "index": index}),
            ])
    events.extend([
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": result["stop_reason"], "stop_sequence": None}, "usage": {"output_tokens": result["usage"]["output_tokens"]}}),
        ("message_stop", {"type": "message_stop"}),
    ])
    return "".join(f"event: {name}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n" for name, event in events).encode()
