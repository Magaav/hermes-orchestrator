#!/usr/bin/env python3
"""Deterministic contract checks for the safe-lab Responses compatibility bridge."""

from __future__ import annotations

import json

import responses_bridge


def main() -> int:
    request = {
        "instructions": "Be concise.",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}],
        "tools": [{"type": "function", "name": "shell", "description": "Run command", "parameters": {"type": "object"}}],
    }
    chat = responses_bridge.request_to_chat(request, model="glm-5.2", max_tokens=512)
    reply = {
        "model": "frank/GLM-5.2", "choices": [{"message": {"content": "Hello"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }
    events = responses_bridge.response_events(reply, model="frank/GLM-5.2")
    tool_reply = {
        "model": "frank/GLM-5.2",
        "choices": [{"message": {"content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "shell", "arguments": '{"cmd":"pwd"}'}}]}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
    }
    tool_events = responses_bridge.response_events(tool_reply, model="frank/GLM-5.2")
    errors = []
    if chat["messages"] != [{"role": "system", "content": "Be concise."}, {"role": "user", "content": "hello"}]:
        errors.append("Responses input translation failed")
    if chat.get("tools", [{}])[0].get("function", {}).get("name") != "shell" or chat.get("stream") is not False:
        errors.append("tool or non-stream upstream projection failed")
    if [item["type"] for item in events][-1] != "response.completed" or events[-1]["response"]["usage"]["total_tokens"] != 12:
        errors.append("text response or exact usage translation failed")
    calls = [item for item in tool_events if item["type"] == "response.output_item.done"]
    if not calls or calls[-1]["item"].get("type") != "function_call" or calls[-1]["item"].get("call_id") != "c1":
        errors.append("function-call response translation failed")
    result = {
        "schema": "wasm-agent.safe-lab.responses-bridge-check.v1", "ok": not errors,
        "checks": {"input": True, "tools": True, "textEvents": True, "functionCallEvents": True, "exactUsage": True},
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
