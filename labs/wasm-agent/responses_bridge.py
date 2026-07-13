#!/usr/bin/env python3
"""Bounded OpenAI Responses API to Chat Completions compatibility bridge."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        value = item.get("text") or item.get("content")
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts)


def request_to_chat(payload: dict[str, Any], *, model: str, max_tokens: int) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    instructions = str(payload.get("instructions") or "").strip()
    if instructions:
        messages.append({"role": "system", "content": instructions})
    source = payload.get("input")
    items = source if isinstance(source, list) else [{"role": "user", "content": source}] if isinstance(source, str) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "")
        if item_type == "function_call":
            arguments = item.get("arguments")
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments if isinstance(arguments, dict) else {}, separators=(",", ":"))
            messages.append({
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": str(item.get("call_id") or item.get("id") or "call"), "type": "function",
                    "function": {"name": str(item.get("name") or ""), "arguments": arguments},
                }],
            })
            continue
        if item_type == "function_call_output":
            output = item.get("output")
            messages.append({
                "role": "tool", "tool_call_id": str(item.get("call_id") or "call"),
                "content": output if isinstance(output, str) else json.dumps(output, separators=(",", ":")),
            })
            continue
        role = str(item.get("role") or "user")
        if role not in {"system", "developer", "user", "assistant"}:
            role = "user"
        text = _text(item.get("content"))
        if text:
            messages.append({"role": "system" if role == "developer" else role, "content": text})
    if not messages:
        messages = [{"role": "user", "content": "Complete the requested task."}]
    tools = []
    for item in payload.get("tools") if isinstance(payload.get("tools"), list) else []:
        if not isinstance(item, dict) or item.get("type") != "function" or not item.get("name"):
            continue
        tools.append({
            "type": "function",
            "function": {
                "name": str(item["name"]), "description": str(item.get("description") or ""),
                "parameters": item.get("parameters") if isinstance(item.get("parameters"), dict) else {"type": "object"},
            },
        })
    result: dict[str, Any] = {
        "model": model, "messages": messages, "max_tokens": max_tokens, "stream": False,
    }
    if tools:
        result.update({"tools": tools, "tool_choice": "auto"})
    return result


def _usage(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    input_tokens = int(source.get("prompt_tokens") or 0)
    output_tokens = int(source.get("completion_tokens") or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": int(source.get("total_tokens") or input_tokens + output_tokens),
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0},
    }


def response_events(payload: dict[str, Any], *, model: str) -> list[dict[str, Any]]:
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    seed = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    response_id = "resp_" + hashlib.sha256(seed).hexdigest()[:24]
    output: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
    for index, raw in enumerate(tool_calls):
        if not isinstance(raw, dict):
            continue
        function = raw.get("function") if isinstance(raw.get("function"), dict) else raw
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments if isinstance(arguments, dict) else {}, separators=(",", ":"))
        item = {
            "id": "fc_" + hashlib.sha256(f"{response_id}:{index}".encode()).hexdigest()[:24],
            "type": "function_call", "status": "completed",
            "call_id": str(raw.get("id") or f"call_{index + 1}"),
            "name": str(function.get("name") or ""), "arguments": arguments,
        }
        output.append(item)
        events.extend([
            {"type": "response.output_item.added", "response_id": response_id, "output_index": index, "item": item},
            {"type": "response.function_call_arguments.done", "response_id": response_id, "output_index": index, "item_id": item["id"], "name": item["name"], "arguments": arguments},
            {"type": "response.output_item.done", "response_id": response_id, "output_index": index, "item": item},
        ])
    text = str(message.get("content") or "")
    if text:
        item_id = "msg_" + hashlib.sha256((response_id + text).encode()).hexdigest()[:24]
        item = {
            "id": item_id, "type": "message", "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }
        output.append(item)
        events.extend([
            {"type": "response.output_item.added", "response_id": response_id, "output_index": len(output) - 1, "item": {**item, "status": "in_progress", "content": []}},
            {"type": "response.content_part.added", "response_id": response_id, "item_id": item_id, "output_index": len(output) - 1, "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": []}},
            {"type": "response.output_text.delta", "response_id": response_id, "item_id": item_id, "output_index": len(output) - 1, "content_index": 0, "delta": text},
            {"type": "response.output_text.done", "response_id": response_id, "item_id": item_id, "output_index": len(output) - 1, "content_index": 0, "text": text},
            {"type": "response.content_part.done", "response_id": response_id, "item_id": item_id, "output_index": len(output) - 1, "content_index": 0, "part": item["content"][0]},
            {"type": "response.output_item.done", "response_id": response_id, "output_index": len(output) - 1, "item": item},
        ])
    response = {
        "id": response_id, "object": "response", "created_at": int(time.time()), "status": "completed",
        "model": model, "output": output, "usage": _usage(payload), "error": None,
    }
    events.append({"type": "response.completed", "response": response})
    return events


def response_sse(payload: dict[str, Any], *, model: str) -> bytes:
    lines = [f"data: {json.dumps(event, separators=(',', ':'))}\n\n" for event in response_events(payload, model=model)]
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()
