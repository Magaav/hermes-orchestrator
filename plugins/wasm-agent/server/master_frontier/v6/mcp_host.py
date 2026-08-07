"""Route-authorized bindings between V6 capabilities and an injected MCP host."""
from __future__ import annotations

from typing import Any, Callable

from . import adapters, contracts, kernel


Call = Callable[[str, str, dict[str, Any]], dict[str, Any]]


def _server_contracts(route: dict[str, Any]) -> list[dict[str, Any]]:
    config = route.get("mcp") if isinstance(route.get("mcp"), dict) else {}
    return [item for item in (config.get("servers") or [])[:64] if isinstance(item, dict) and str(item.get("id") or "").strip()]


def compile(route: dict[str, Any], manifests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    declared = {str(item["id"]): item for item in _server_contracts(route)}
    if not declared:
        return []
    available = {str(item.get("id") or ""): item for item in manifests[:64] if isinstance(item, dict)}
    missing = sorted(set(declared) - set(available))
    if missing:
        raise contracts.ContractError("mcp_declared_server_missing")
    bindings: list[dict[str, Any]] = []
    capability_ids: set[str] = set()
    for server, policy in declared.items():
        manifest = available[server]
        tools = manifest.get("tools") if isinstance(manifest.get("tools"), list) else []
        allowed = {str(item) for item in (policy.get("tools") or [])}
        if not allowed:
            raise contracts.ContractError("mcp_tool_allowlist_missing")
        mode = str(policy.get("mode") or "read-only")
        if mode not in {"read-only", "read-write"}:
            raise contracts.ContractError("mcp_mode_invalid")
        if mode == "read-only" and "*" in allowed:
            raise contracts.ContractError("mcp_read_only_wildcard_denied")
        selected = []
        for raw in tools:
            function = raw.get("function") if isinstance(raw, dict) and isinstance(raw.get("function"), dict) else raw
            if not isinstance(function, dict):
                continue
            name = str(function.get("name") or "")
            if "*" not in allowed and name not in allowed:
                continue
            selected.append(raw)
        for capability in adapters.mcp(server, selected):
            if capability["id"] in capability_ids:
                raise contracts.ContractError("mcp_capability_collision")
            capability_ids.add(capability["id"])
            _prefix, declared_server, tool = capability["executor"].split(":", 2)
            bindings.append({"capability": capability, "server": declared_server, "tool": tool})
    return bindings


def register(target: kernel.Kernel, bindings: list[dict[str, Any]], call: Call) -> None:
    for binding in bindings:
        capability = binding["capability"]
        server = str(binding["server"])
        tool = str(binding["tool"])

        def execute(_capability, operation, server=server, tool=tool):
            result = call(server, tool, operation["args"])
            if not isinstance(result, dict):
                return {"ok": False, "error": {"code": "mcp_result_invalid"}}
            ok = result.get("ok") is not False and not result.get("isError")
            observed = result.get("structuredContent") if isinstance(result.get("structuredContent"), dict) else result
            return {
                "ok": ok, "state": "completed" if ok else "failed", "observed": observed,
                "proof": [str(item) for item in (result.get("proof") or [])] or [f"mcp:{server}:{tool}"],
                "error": {} if ok else {"code": str(result.get("code") or "mcp_tool_failed")},
            }

        target.register(capability, execute)
