"""Generic capability compilers for repository, live-client, and MCP adapters."""
from __future__ import annotations

import re
from typing import Any

from . import contracts


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
    binding = ";".join(filter(None, (
        f"client:{client_id}" if client_id else "",
        f"widgets:{','.join(widget_ids)}" if widget_ids else "",
    )))
    result = [contracts.capability({
        "id": "client.inspect", "kind": "observe", "authority": "client.ui.inspect",
        "executor": "client.inspect", "summary": f"Inspect the bound live {runtime} client and semantic UI state.",
        "mode": "read", "proof": ["client.status"], "detail": binding,
        "input": {"type": "object", "properties": {}, "additionalProperties": False},
    })]
    if "observe.browser.inspect" in capabilities:
        result.append(contracts.capability({
            "id": "client.browser.inspect", "kind": "observe", "authority": "client.ui.inspect",
            "executor": "client.browser.inspect", "summary": "Inspect native Browser state and its latest fresh redacted input receipt when present.",
            "mode": "read", "proof": ["native.web_surface.status"], "terminal_result": True, "detail": binding,
            "input": {"type": "object", "properties": {"wait_sec": {"type": "number", "minimum": 0, "maximum": 20}}, "additionalProperties": False},
        }))
    if "control.widget.open" in capabilities:
        widget_field: dict[str, Any] = {"type": "string", "minLength": 1, "maxLength": 80}
        if widget_ids:
            widget_field.update({"enum": widget_ids, "default": widget_ids[0]})
        result.append(contracts.capability({
            "id": "client.widget.open", "kind": "act", "authority": "client.ui.control",
            "executor": "client.widget.open", "summary": "Open a declared widget on the live client.",
            "mode": "write", "conflicts": [f"client:{client_id or 'bound'}"], "proof": ["client.ack"], "detail": binding,
            "input": {"type": "object", "required": ["widget"], "properties": {"widget": widget_field, "wait_sec": {"type": "number", "minimum": 0, "maximum": 20}}, "additionalProperties": False},
        }))
    if "control.space.open" in capabilities:
        result.append(contracts.capability({
            "id": "client.space.open", "kind": "act", "authority": "client.ui.control",
            "executor": "client.space.open", "summary": "Open an authenticated app space by its exact name or ID on the live client.",
            "mode": "write", "conflicts": [f"client:{client_id or 'bound'}"], "proof": ["client.ack", "client.space.active"], "terminal_result": True, "detail": binding,
            "input": {"type": "object", "required": ["space"], "properties": {"space": {"type": "string", "minLength": 1, "maxLength": 160}, "wait_sec": {"type": "number", "minimum": 0, "maximum": 20}}, "additionalProperties": False},
        }))
    if "control.browser.navigate" in capabilities:
        result.append(contracts.capability({
            "id": "client.browser.navigate", "kind": "act", "authority": "client.ui.control",
            "executor": "client.browser.navigate", "summary": "Navigate the native Browser widget to an HTTPS URL.",
            "mode": "write", "conflicts": [f"client:{client_id or 'bound'}"], "proof": ["client.ack", "browser.url"], "detail": binding,
            "input": {"type": "object", "required": ["url"], "properties": {"url": {"type": "string", "minLength": 1, "maxLength": 2000, "pattern": "^https://"}, "wait_sec": {"type": "number", "minimum": 0, "maximum": 20}}, "additionalProperties": False},
        }))
    if "control.browser.input_receipt" in capabilities:
        result.append(contracts.capability({
            "id": "client.browser.input_receipt", "kind": "act", "authority": "client.ui.control",
            "executor": "client.browser.input_receipt", "summary": "Enable or disable bounded native Browser input receipts.",
            "mode": "write", "conflicts": [f"client:{client_id or 'bound'}"], "proof": ["client.ack"], "detail": binding,
            "input": {"type": "object", "required": ["enabled"], "properties": {"enabled": {"type": "boolean"}, "wait_sec": {"type": "number", "minimum": 0, "maximum": 20}}, "additionalProperties": False},
        }))
    if "control.browser.pointer.dispatch" in capabilities:
        coordinate = {"type": "integer", "minimum": 0, "maximum": 65_535}
        result.append(contracts.capability({
            "id": "client.browser.pointer.dispatch", "kind": "act", "authority": "client.ui.control",
            "executor": "client.browser.pointer.dispatch", "summary": "Dispatch one bounded synthetic primary pointer gesture by viewport coordinates; this cannot prove a physical user click or DOM activation.",
            "mode": "write", "conflicts": [f"client:{client_id or 'bound'}"], "proof": ["client.ack"], "detail": binding,
            "input": {"type": "object", "required": ["x", "y"], "properties": {"x": coordinate, "y": coordinate, "wait_sec": {"type": "number", "minimum": 0, "maximum": 20}}, "additionalProperties": False},
        }))
    if "control.browser.javascript.execute.unrestricted" in capabilities:
        result.append(contracts.capability({
            "id": "client.browser.javascript.observe.unrestricted", "kind": "observe", "authority": "client.ui.control",
            "executor": "client.browser.javascript.observe.unrestricted", "summary": "Inspect a loaded Browser page using arbitrary JavaScript without claiming a page mutation. Success requires result_json {observation:{observed:true,target,predicate,result}} with a scalar result.",
            "mode": "write", "conflicts": [f"client:{client_id or 'bound'}"], "proof": ["client.ack", "native.web_surface.javascript.execute.unrestricted"], "detail": binding,
            "completion_proof": ["client.page.observation.observed"],
            "input": {"type": "object", "required": ["javascript"], "properties": {"javascript": {"type": "string", "minLength": 1, "maxLength": 1_048_576}, "wait_sec": {"type": "number", "minimum": 0, "maximum": 30, "default": 30}}, "additionalProperties": False},
        }))
        result.append(contracts.capability({
            "id": "client.browser.javascript.execute.unrestricted", "kind": "act", "authority": "client.ui.control",
            "executor": "client.browser.javascript.execute.unrestricted", "summary": "Interact with a loaded Browser page using arbitrary JavaScript, including sending a message. For asynchronous UI updates, return a Promise and wait until the result is observable. Mutation success requires result_json {postcondition:{observed:true,action,target,predicate,before,after}} with differing before and after; use the separate observe capability for read-only inspection.",
            "mode": "write", "conflicts": [f"client:{client_id or 'bound'}"], "proof": ["client.ack", "native.web_surface.javascript.execute.unrestricted"], "detail": binding,
            "completion_proof": ["client.page.postcondition.observed"],
            "input": {"type": "object", "required": ["javascript"], "properties": {"javascript": {"type": "string", "minLength": 1, "maxLength": 1_048_576}, "wait_sec": {"type": "number", "minimum": 0, "maximum": 30, "default": 30}}, "additionalProperties": False},
        }))
    if "windows.shell.execute.unrestricted" in capabilities:
        result.append(contracts.capability({
            "id": "client.windows.shell.execute.unrestricted", "kind": "act", "authority": "client.ui.control",
            "executor": "client.windows.shell.execute.unrestricted", "summary": "Execute an arbitrary PowerShell or cmd command as the installed Windows user.",
            "mode": "write", "conflicts": [f"client:{client_id or 'bound'}"], "proof": ["client.ack", "windows.shell.exit"], "detail": binding,
            "input": {"type": "object", "required": ["command"], "properties": {"command": {"type": "string", "minLength": 1, "maxLength": 1_048_576}, "shell": {"type": "string", "enum": ["powershell", "cmd"], "default": "powershell"}, "cwd": {"type": "string", "maxLength": 32_768}, "environment": {"type": "object", "maxProperties": 128}, "timeout_ms": {"type": "integer", "minimum": 1000, "maximum": 240000, "default": 60000}, "wait_sec": {"type": "number", "minimum": 0, "maximum": 20}}, "additionalProperties": False},
        }))
    return result


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
