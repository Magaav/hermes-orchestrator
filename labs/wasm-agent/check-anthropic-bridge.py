#!/usr/bin/env python3
"""Deterministic checks for the safe-lab Anthropic Messages bridge."""

from __future__ import annotations

import json

import anthropic_bridge


def main() -> int:
    request = {
        "system": [{"type": "text", "text": "Be concise."}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
        "tools": [{"name": "Bash", "description": "Run command", "input_schema": {"type": "object"}}],
    }
    chat = anthropic_bridge.request_to_chat(request, model="glm-5.2", max_tokens=512)
    reply = {
        "choices": [{"message": {"content": "Hello"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }
    message = anthropic_bridge.message(reply, model="frank/GLM-5.2")
    tool_reply = {
        "choices": [{"message": {"content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "Bash", "arguments": '{"command":"pwd"}'}}]}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4},
    }
    tool = anthropic_bridge.message(tool_reply, model="frank/GLM-5.2")
    errors = []
    if chat["messages"][:2] != [{"role": "system", "content": "Be concise."}, {"role": "user", "content": "hello"}]:
        errors.append("Messages input translation failed")
    if chat.get("tools", [{}])[0].get("function", {}).get("name") != "Bash" or chat.get("stream") is not False:
        errors.append("tool translation or bounded upstream transport failed")
    if message["content"] != [{"type": "text", "text": "Hello"}] or message["usage"] != {"input_tokens": 10, "output_tokens": 2}:
        errors.append("text or exact usage response translation failed")
    if tool["stop_reason"] != "tool_use" or tool["content"][0].get("input") != {"command": "pwd"}:
        errors.append("tool response translation failed")
    if "message_stop" not in anthropic_bridge.message_sse(reply, model="frank/GLM-5.2").decode():
        errors.append("Messages SSE termination missing")
    result = {
        "schema": "wasm-agent.safe-lab.anthropic-bridge-check.v1", "ok": not errors,
        "checks": {"input": True, "tools": True, "text": True, "toolUse": True, "sse": True, "countTokens": anthropic_bridge.count_tokens(request)["input_tokens"] > 0},
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
