"""Generic capability compilers for repository, live-client, and MCP adapters."""
from __future__ import annotations

import re
from typing import Any

from . import browser_procedure_plugin, contracts, windows_control_plugin


def _segment(value: Any, fallback: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return clean[:80] or fallback


def repository() -> list[dict[str, Any]]:
    edit_operation = {
        "type": "object", "required": ["op", "path"],
        "properties": {
            "op": {"type": "string", "enum": ["create", "replace", "append", "move", "delete"]},
            "path": {"type": "string"}, "destination": {"type": "string"},
            "content": {"type": "string", "minLength": 1}, "find": {"type": "string"},
            "replace": {"type": "string"},
            "expected_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "expected_absent": {"type": "boolean"},
        }, "additionalProperties": False,
    }
    schemas = {
        "repo.map": {"type": "object", "properties": {"id": {"type": "string"}}, "additionalProperties": False},
        "repo.search": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string", "minLength": 1}, "path": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 30}}, "additionalProperties": False},
        "repo.read": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string", "minLength": 1}, "start_line": {"type": "integer", "minimum": 1}, "end_line": {"type": "integer", "minimum": 1}}, "additionalProperties": False},
        "repo.patch": {"type": "object", "required": ["operations"], "properties": {"operations": {"type": "array", "minItems": 1, "maxItems": 24, "items": edit_operation}, "dry_run": {"type": "boolean"}}, "additionalProperties": False},
        "repo.test": {"type": "object", "required": ["check_id"], "properties": {"check_id": {"type": "string", "minLength": 1}}, "additionalProperties": False},
        "repo.diff": {"type": "object", "properties": {"paths": {"type": "array", "maxItems": 64, "items": {"type": "string"}}}, "additionalProperties": False},
        "repo.prove": {"type": "object", "properties": {}, "additionalProperties": False},
    }
    definitions = [
        ("repo.map", "observe", "repo.read", "repository.map", "Discover instructions, ownership, languages, checks, and dirty state.", "read", []),
        ("repo.search", "observe", "repo.read", "repository.search", "Search source and symbols in the routed repository.", "read", []),
        ("repo.read", "observe", "repo.read", "repository.read", "Read exact revision-bound repository content.", "read", []),
        ("repo.patch", "act", "repo.edit", "repository.patch", "Apply a preconditioned route-scoped transaction.", "write", ["repo:worktree"]),
        ("repo.test", "verify", "test.run", "repository.test", "Run a route-registered focused check.", "write", ["repo:worktree"]),
        ("repo.diff", "verify", "proof.report", "repository.diff", "Inspect revision-bound changed-file and diff proof.", "read", ["repo:worktree"]),
        ("repo.prove", "verify", "proof.report", "repository.prove", "Collect route, mutation, check, diff, and evidence proof.", "read", ["repo:worktree"]),
    ]
    return [contracts.capability({
        "id": identifier, "kind": kind, "authority": authority, "executor": executor,
        "summary": summary, "mode": mode, "conflicts": conflicts,
        "input": schemas[identifier], "result": {"type": "object"},
        "proof": ["structured.receipt"],
        "requires_after": ["repo.test", "repo.diff", "repo.prove"] if identifier == "repo.patch" else [],
    }) for identifier, kind, authority, executor, summary, mode, conflicts in definitions]


def live_client(client: dict[str, Any]) -> list[dict[str, Any]]:
    runtime = _segment(client.get("runtime_type"), "client")
    client_id = str(client.get("client_id") or client.get("device_id") or "").strip()[:120]
    capabilities = set(client.get("capabilities") or [])
    widget_ids = list(dict.fromkeys(
        str(item).strip()[:80] for item in (client.get("widget_ids") or [])
        if str(item).strip()
    ))[:32]
    available_widget_ids = list(dict.fromkeys(
        str(item).strip()[:80] for item in (client.get("available_widget_ids") or [])
        if str(item).strip()
    ))[:32]
    space = str(client.get("space_name") or client.get("space_id") or "unknown")[:160]
    binding = ";".join(filter(None, (
        f"client:{client_id}" if client_id else "",
        f"declared_widgets:{','.join(widget_ids) or 'none'}",
        f"active_widgets:{','.join(available_widget_ids) or 'none'}",
        f"space:{space}",
    )))
    result = [contracts.capability({
        "id": "client.inspect", "kind": "observe", "authority": "client.ui.inspect",
        "executor": "client.inspect", "summary": f"Inspect the bound live {runtime} client and semantic UI state.",
        "mode": "read", "proof": ["client.status"], "detail": binding,
        "input": {"type": "object", "properties": {}, "additionalProperties": False},
    })]
    if "observe.spaces.catalog" in capabilities:
        result.append(contracts.capability({
            "id": "client.space.catalog", "kind": "observe", "authority": "client.ui.inspect",
            "executor": "client.space.catalog", "summary": "List bounded authenticated spaces and the route-declared widgets available in each space.",
            "mode": "read", "proof": ["client.space.catalog"], "detail": binding,
            "input": {"type": "object", "properties": {"wait_sec": {"type": "number", "minimum": 0, "maximum": 20, "default": 18}}, "additionalProperties": False},
        }))
    if "observe.runtime.diagnose" in capabilities:
        result.append(contracts.capability({
            "id": "client.runtime.diagnose", "kind": "observe", "authority": "client.ui.inspect",
            "executor": "client.runtime.diagnose", "summary": "Collect a bounded, redacted runtime snapshot with readiness, errors, rejections, performance, module, focus, viewport, and recent interaction evidence.",
            "mode": "read", "proof": ["client.runtime.diagnostic_snapshot"], "detail": binding,
            "input": {"type": "object", "properties": {"lease_ms": {"type": "integer", "minimum": 5000, "maximum": 120000, "default": 30000}, "wait_sec": {"type": "number", "minimum": 0, "maximum": 20, "default": 18}}, "additionalProperties": False},
        }))
    if "control.runtime.refresh" in capabilities:
        result.append(contracts.capability({
            "id": "client.runtime.refresh", "kind": "act", "authority": "client.ui.control",
            "executor": "client.runtime.refresh", "summary": "Schedule a bounded renderer runtime refresh so the connected client loads the current cloud module release without clearing local storage.",
            "mode": "write", "conflicts": [f"client:{client_id or 'bound'}"],
            "proof": ["client.runtime.refresh.scheduled"], "detail": binding,
            "input": {"type": "object", "properties": {"wait_sec": {"type": "number", "minimum": 0, "maximum": 20, "default": 18}}, "additionalProperties": False},
        }))
    if "control.widget.open" in capabilities:
        widget_field: dict[str, Any] = {"type": "string", "minLength": 1, "maxLength": 80}
        if widget_ids:
            widget_field.update({"enum": widget_ids, "default": widget_ids[0]})
        result.append(contracts.capability({
            "id": "client.widget.open", "kind": "act", "authority": "client.ui.control",
            "executor": "client.widget.open", "summary": f"Open a route-declared widget only when it is present in the active surface; current space {space} has {','.join(available_widget_ids) or 'no widgets'}.",
            "mode": "write", "conflicts": [f"client:{client_id or 'bound'}"], "proof": ["client.ack", "client.widget.visible"], "completion_proof": ["client.widget.visible"], "terminal_result": True, "detail": binding,
            "input": {"type": "object", "required": ["widget"], "properties": {"widget": widget_field, "wait_sec": {"type": "number", "minimum": 0, "maximum": 20, "default": 18}}, "additionalProperties": False},
        }))
    if "control.space.open" in capabilities:
        result.append(contracts.capability({
            "id": "client.space.open", "kind": "act", "authority": "client.ui.control",
            "executor": "client.space.open", "summary": "Open an authenticated app space by its exact name or ID on the live client.",
            "mode": "write", "conflicts": [f"client:{client_id or 'bound'}"], "proof": ["client.ack", "client.space.active"], "terminal_result": True, "detail": binding,
            "input": {"type": "object", "required": ["space"], "properties": {"space": {"type": "string", "minLength": 1, "maxLength": 160}, "wait_sec": {"type": "number", "minimum": 0, "maximum": 20, "default": 18}}, "additionalProperties": False},
        }))
    result.extend(windows_control_plugin.capabilities(capabilities, client_id=client_id, binding=binding))
    result.extend(browser_procedure_plugin.capabilities(capabilities, client_id=client_id, binding=binding))
    return result


def client_environment(topology: dict[str, Any], summary: str) -> dict[str, Any]:
    return contracts.capability({
        "id": "client.environment.inspect", "kind": "observe", "authority": "client.ui.inspect",
        "executor": "client.environment.inspect", "summary": summary,
        "mode": "read", "proof": ["client.environment.topology"],
        "detail": f"environment:{topology.get('environment', 'unknown')};binding:{topology.get('binding', 'unknown')}",
        "input": {"type": "object", "properties": {}, "additionalProperties": False},
    })


def mcp(server: str, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    server_id = _segment(server, "server")
    result = []
    used: set[str] = set()
    for raw in tools[:512]:
        if not isinstance(raw, dict):
            continue
        function = raw.get("function") if isinstance(raw.get("function"), dict) else raw
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        annotations = function.get("annotations") if isinstance(function.get("annotations"), dict) else {}
        read_only = annotations.get("readOnlyHint") is True or annotations.get("read_only") is True
        kind = "observe" if read_only else "act"
        tool_id = _segment(name, "tool")
        if tool_id in used:
            tool_id = f"{tool_id}-{contracts.digest(name).split(':', 1)[1][:8]}"
        used.add(tool_id)
        result.append(contracts.capability({
            "id": f"mcp.{server_id}.{tool_id}", "kind": kind,
            "authority": f"mcp.{server_id}.{tool_id}", "executor": f"mcp:{server}:{name}",
            "summary": str(function.get("description") or f"MCP tool {name}")[:500],
            "mode": "read" if read_only else "write",
            "conflicts": [] if read_only else [f"mcp:{server_id}"],
            "input": function.get("inputSchema") if isinstance(function.get("inputSchema"), dict) else function.get("parameters") if isinstance(function.get("parameters"), dict) else {"type": "object"},
            "result": function.get("outputSchema") if isinstance(function.get("outputSchema"), dict) else {"type": "object"},
            "proof": ["mcp.receipt"], "detail": f"mcp:{server}:{name}",
        }))
    return result
