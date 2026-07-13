#!/usr/bin/env python3
"""Bounded Google GenerateContent API to Chat Completions compatibility bridge."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import unquote


_PATH = re.compile(r"^/v1beta/models/([^/:]+):(generateContent|streamGenerateContent|countTokens)$")


def parse_path(path: str) -> tuple[str, str] | None:
    match = _PATH.fullmatch(path)
    return (unquote(match.group(1)), match.group(2)) if match else None


def _parts_text(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    return "\n".join(
        str(part.get("text") or "")
        for part in parts
        if isinstance(part, dict) and part.get("text")
    )


def request_to_chat(payload: dict[str, Any], *, model: str, max_tokens: int) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    system = payload.get("systemInstruction") if isinstance(payload.get("systemInstruction"), dict) else {}
    system_text = _parts_text(system.get("parts"))
    if system_text:
        messages.append({"role": "system", "content": system_text})

    for content in payload.get("contents") if isinstance(payload.get("contents"), list) else []:
        if not isinstance(content, dict):
            continue
        role = "assistant" if content.get("role") == "model" else "user"
        parts = content.get("parts") if isinstance(content.get("parts"), list) else []
        text = _parts_text(parts)
        calls: list[dict[str, Any]] = []
        responses: list[dict[str, Any]] = []
        for index, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            call = part.get("functionCall") if isinstance(part.get("functionCall"), dict) else None
            if call:
                calls.append({
                    "id": str(call.get("id") or f"call_{index}"),
                    "type": "function",
                    "function": {
                        "name": str(call.get("name") or ""),
                        "arguments": json.dumps(call.get("args") if isinstance(call.get("args"), dict) else {}, separators=(",", ":")),
                    },
                })
            response = part.get("functionResponse") if isinstance(part.get("functionResponse"), dict) else None
            if response:
                value = response.get("response")
                responses.append({
                    "role": "tool",
                    "tool_call_id": str(response.get("id") or response.get("name") or f"call_{index}"),
                    "content": value if isinstance(value, str) else json.dumps(value if value is not None else {}, separators=(",", ":")),
                })
        if role == "assistant" and (text or calls):
            message: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                message["tool_calls"] = calls
            messages.append(message)
        elif text:
            messages.append({"role": "user", "content": text})
        messages.extend(responses)

    if not messages:
        messages = [{"role": "user", "content": "Complete the requested task."}]

    tools: list[dict[str, Any]] = []
    for group in payload.get("tools") if isinstance(payload.get("tools"), list) else []:
        declarations = group.get("functionDeclarations") if isinstance(group, dict) and isinstance(group.get("functionDeclarations"), list) else []
        for declaration in declarations:
            if not isinstance(declaration, dict) or not declaration.get("name"):
                continue
            parameters = declaration.get("parametersJsonSchema") or declaration.get("parameters")
            tools.append({
                "type": "function",
                "function": {
                    "name": str(declaration["name"]),
                    "description": str(declaration.get("description") or ""),
                    "parameters": parameters if isinstance(parameters, dict) else {"type": "object"},
                },
            })

    result: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if tools:
        result.update({"tools": tools, "tool_choice": "auto"})
    return result


def count_tokens(payload: dict[str, Any]) -> dict[str, int]:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return {"totalTokens": max(1, (len(canonical.encode()) + 3) // 4)}


def generate_content(payload: dict[str, Any], *, model: str) -> dict[str, Any]:
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    source = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    parts: list[dict[str, Any]] = []
    text = str(source.get("content") or "")
    if text:
        parts.append({"text": text})
    for index, raw in enumerate(source.get("tool_calls") if isinstance(source.get("tool_calls"), list) else []):
        if not isinstance(raw, dict):
            continue
        function = raw.get("function") if isinstance(raw.get("function"), dict) else raw
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        parts.append({
            "functionCall": {
                "id": str(raw.get("id") or f"call_{index}"),
                "name": str(function.get("name") or ""),
                "args": arguments if isinstance(arguments, dict) else {},
            }
        })
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "candidates": [{
            "content": {"role": "model", "parts": parts},
            "finishReason": "STOP",
            "index": 0,
        }],
        "usageMetadata": {
            "promptTokenCount": int(usage.get("prompt_tokens") or 0),
            "candidatesTokenCount": int(usage.get("completion_tokens") or 0),
            "totalTokenCount": int(usage.get("total_tokens") or (int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0))),
        },
        "modelVersion": model,
        "responseId": "resp_" + digest[:24],
    }


def generate_content_sse(payload: dict[str, Any], *, model: str) -> bytes:
    event = generate_content(payload, model=model)
    return f"data: {json.dumps(event, separators=(',', ':'))}\n\n".encode()
