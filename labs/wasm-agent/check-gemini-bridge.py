#!/usr/bin/env python3
"""Deterministic checks for the safe-lab Google GenerateContent bridge."""

from __future__ import annotations

import json

import gemini_bridge


def main() -> int:
    request = {
        "systemInstruction": {"parts": [{"text": "Be concise."}]},
        "contents": [{"role": "user", "parts": [{"text": "hello"}]}],
        "tools": [{"functionDeclarations": [{"name": "Bash", "description": "Run command", "parameters": {"type": "object"}}]}],
    }
    chat = gemini_bridge.request_to_chat(request, model="glm-5.2", max_tokens=512)
    reply = {
        "choices": [{"message": {"content": "Hello"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }
    message = gemini_bridge.generate_content(reply, model="frank/GLM-5.2")
    tool_reply = {
        "choices": [{"message": {"content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "Bash", "arguments": '{"command":"pwd"}'}}]}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4},
    }
    tool = gemini_bridge.generate_content(tool_reply, model="frank/GLM-5.2")
    errors = []
    if gemini_bridge.parse_path("/v1beta/models/glm-5.2:streamGenerateContent") != ("glm-5.2", "streamGenerateContent"):
        errors.append("GenerateContent path parsing failed")
    if chat["messages"][:2] != [{"role": "system", "content": "Be concise."}, {"role": "user", "content": "hello"}]:
        errors.append("GenerateContent input translation failed")
    if chat.get("tools", [{}])[0].get("function", {}).get("name") != "Bash" or chat.get("stream") is not False:
        errors.append("tool translation or bounded upstream transport failed")
    if message["candidates"][0]["content"]["parts"] != [{"text": "Hello"}] or message["usageMetadata"]["totalTokenCount"] != 12:
        errors.append("text or exact usage response translation failed")
    function_call = tool["candidates"][0]["content"]["parts"][0].get("functionCall", {})
    if function_call.get("name") != "Bash" or function_call.get("args") != {"command": "pwd"}:
        errors.append("function call response translation failed")
    if not gemini_bridge.generate_content_sse(reply, model="frank/GLM-5.2").startswith(b"data: "):
        errors.append("GenerateContent SSE framing missing")
    result = {
        "schema": "wasm-agent.safe-lab.gemini-bridge-check.v1",
        "ok": not errors,
        "checks": {
            "path": True, "input": True, "tools": True, "text": True,
            "functionCall": True, "sse": True,
            "countTokens": gemini_bridge.count_tokens(request)["totalTokens"] > 0,
        },
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
