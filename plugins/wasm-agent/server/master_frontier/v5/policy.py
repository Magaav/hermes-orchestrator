from __future__ import annotations

from typing import Any

from .. import authority
from . import task_policy, tool_stage


TOOLS = authority.V5_TOOLS


def tool_descriptors() -> list[dict[str, Any]]:
    return [
        {"name": "search", "description": "Find relevant files, source text, and symbols in the routed workspace.", "input_schema": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}, "path": {"type": "string"}, "limit": {"type": "integer"}}}},
        {"name": "read", "description": "Read exact bounded content from a routed workspace file.", "input_schema": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}}},
        {"name": "inspect", "description": "Inspect a live runtime entity. Returns a bounded snapshot; pass its opaque proof_id to resolve scoped proof.", "input_schema": {"type": "object", "required": ["target", "id"], "properties": {"target": {"type": "string", "enum": ["run", "service", "device", "application", "runtime_entity"]}, "id": {"type": "string", "minLength": 1, "maxLength": 120}, "proof_id": {"type": "string", "pattern": "^run-store-[0-9a-f]{24}$"}, "fields": {"type": "array", "items": {"type": "string"}}}, "additionalProperties": False}},
        {"name": "edit", "description": "Create, edit, move, or delete files through one bounded route-scoped transaction. Bind edits to observed content with expected_sha256 or expected_absent.", "input_schema": {"type": "object", "required": ["operations"], "properties": {"operations": {"type": "array", "maxItems": 24, "items": {"type": "object", "required": ["op", "path"], "properties": {"op": {"type": "string", "enum": ["create", "replace", "append", "move", "delete"]}, "path": {"type": "string"}, "destination": {"type": "string"}, "content": {"type": "string"}, "find": {"type": "string"}, "replace": {"type": "string"}, "insert": {"type": "string"}, "after": {"type": "string"}, "expected_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}, "expected_absent": {"type": "boolean"}}, "additionalProperties": False}}, "dry_run": {"type": "boolean"}}, "additionalProperties": False}},
        {"name": "test", "description": "Run one focused check registered by the resolved route contract.", "input_schema": {"type": "object", "required": ["check_id"], "properties": {"check_id": {"type": "string"}}, "additionalProperties": False}},
        {"name": "diff", "description": "Inspect the current route-scoped git diff summary and changed files.", "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"name": "prove", "description": "Collect route, timeline, checks, and exact usage proof for this run and session.", "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    ]


def executive_descriptor() -> dict[str, Any]:
    fields = {name: {"type": "string", "maxLength": limit} for name, limit in {
        "goal": 1200, "situation": 2400, "plan": 2400, "hypotheses": 2000,
        "open": 1600, "next": 1200, "done": 1600,
    }.items()}
    fields["outcomes"] = {
        "type": "array", "maxItems": 12, "items": {
            "type": "object", "required": ["id", "state", "objective"],
            "properties": {
                "id": {"type": "string", "maxLength": 80},
                "state": {"type": "string", "enum": ["open", "done", "dropped", "blocked"]},
                "objective": {"type": "string", "maxLength": 600},
                "requires": {"type": "string", "enum": ["search", "read", "inspect", "edit", "test", "diff", "prove"]},
                "evidence": {"type": "string", "maxLength": 600},
                "reason": {"type": "string", "maxLength": 600},
            }, "additionalProperties": False,
        },
    }
    fields["decision"] = {
        "type": "object", "required": ["state", "candidate"],
        "properties": {
            "state": {"type": "string", "enum": ["selected", "blocked", "rejected", "overscoped"]},
            "candidate": {"type": "string", "maxLength": 1200},
            "targets": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 240}},
            "acceptance": {"type": "string", "maxLength": 1600},
            "blocker": {"type": "string", "maxLength": 1200},
            "next_action": {"type": "string", "maxLength": 600},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        }, "additionalProperties": False,
    }
    return {
        "name": "checkpoint",
        "description": "Replace your durable executive capsule, optional outcomes, and operational decision. A decision records candidate, target paths, acceptance criterion, blocker, next action, and confidence without hidden reasoning.",
        "input_schema": {"type": "object", "properties": fields, "additionalProperties": False},
    }


def descriptors_for(route: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    descriptors = [item for item in tool_descriptors() if authority.tool_allowed(item["name"], route)]
    if isinstance(route, dict) and task_policy.llm_autonomous(route) and task_policy.requires_mutation(route):
        edit = next((item for item in descriptors if item["name"] == "edit"), None)
        if edit is not None:
            edit["input_schema"]["properties"].pop("dry_run", None)
    if isinstance(route, dict) and str((route.get("task_contract") or {}).get("decision_mode") or "") == "llm_autonomous":
        descriptors.insert(0, executive_descriptor())
    return descriptors


def active_descriptors(route: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    descriptors = descriptors_for(route)
    names = tool_stage.active_names(route, state, [item["name"] for item in descriptors])
    return [item for item in descriptors if item["name"] in names]


def provider_tools(route: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": item["name"], "description": item["description"], "parameters": item["input_schema"]}} for item in descriptors_for(route)]


def active_provider_tools(route: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": item["name"], "description": item["description"], "parameters": item["input_schema"]}} for item in active_descriptors(route, state)]


def allowed(name: str, route: dict[str, Any] | None = None) -> bool:
    # The loop uses the route-less form only to recognize the fixed vocabulary.
    # Execution must always use the route-aware form below.
    if name == "checkpoint":
        return route is None or bool(isinstance(route, dict) and str((route.get("task_contract") or {}).get("decision_mode") or "") == "llm_autonomous")
    return authority.known_tool(name) if route is None else authority.tool_allowed(name, route)
