from __future__ import annotations

from typing import Any


READ_ONLY_TOOLS = ("search", "read", "inspect")


def tool_descriptors() -> list[dict[str, Any]]:
    return [
        {"name": "search", "description": "Find relevant files, source text, and symbols in the routed workspace.", "input_schema": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}, "path": {"type": "string"}, "limit": {"type": "integer"}}}},
        {"name": "read", "description": "Read exact bounded content from a routed workspace file.", "input_schema": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}}},
        {"name": "inspect", "description": "Inspect a live run, service, device, application, or runtime entity. Source objects require search/read.", "input_schema": {"type": "object", "required": ["target"], "properties": {"target": {"type": "string", "enum": ["run", "service", "device", "application", "runtime_entity"]}, "id": {"type": "string"}, "fields": {"type": "array", "items": {"type": "string"}}}}},
    ]


def provider_tools() -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": item["name"], "description": item["description"], "parameters": item["input_schema"]}} for item in tool_descriptors()]


def allowed(name: str) -> bool:
    return name in READ_ONLY_TOOLS
