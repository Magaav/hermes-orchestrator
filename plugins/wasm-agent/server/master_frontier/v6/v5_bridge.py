"""V6 semantic executors backed by the trusted V5 tool substrate."""
from __future__ import annotations

from typing import Any, Callable

from . import adapters, kernel


Invoke = Callable[[str, dict[str, Any]], dict[str, Any]]
InvokeMcp = Callable[[str, str, dict[str, Any]], dict[str, Any]]


def _client_wait(args: dict[str, Any], default: float = 18, maximum: float = 20) -> float:
    try:
        requested = float(args.get("wait_sec", default))
    except (TypeError, ValueError):
        requested = default
    return min(maximum, max(default, requested))


V5_TOOLS = {
    "repository.map": ("inspect", lambda args: {"target": "application", "id": str(args.get("id") or "repository")}),
    "repository.search": ("search", lambda args: args),
    "repository.read": ("read", lambda args: args),
    "repository.patch": ("edit", lambda args: args),
    "repository.test": ("test", lambda args: args),
    "repository.diff": ("diff", lambda args: args),
    "repository.prove": ("prove", lambda args: args),
    "client.inspect": ("client", lambda args: {**args, "operation": "inspect"}),
    "client.space.catalog": ("client", lambda args: {"operation": "space_catalog", "client_id": args.get("client"), "wait_sec": _client_wait(args)}),
    "client.runtime.diagnose": ("client", lambda args: {"operation": "runtime_diagnose", "client_id": args.get("client"), "lease_ms": args.get("lease_ms", 30000), "wait_sec": _client_wait(args)}),
    "client.runtime.refresh": ("client", lambda args: {"operation": "runtime_refresh", "client_id": args.get("client"), "wait_sec": _client_wait(args)}),
    "client.widget.open": ("client", lambda args: {"operation": "open_widget", "client_id": args.get("client"), "widget_id": args.get("widget"), "wait_sec": _client_wait(args)}),
    "client.space.open": ("client", lambda args: {"operation": "space_open", "client_id": args.get("client"), "space": args.get("space"), "wait_sec": _client_wait(args)}),
    "client.windows.shell.execute.unrestricted": ("client", lambda args: {"operation": "windows_shell_execute_unrestricted", "client_id": args.get("client"), "command": args.get("command"), "shell": args.get("shell", "powershell"), "cwd": args.get("cwd", ""), "environment": args.get("environment", {}), "timeout_ms": args.get("timeout_ms", 60000), "wait_sec": _client_wait(args, 20, 20)}),
    "client.companion.overlay.show": ("client", lambda args: {"operation": "show_companion_overlay", "client_id": args.get("client"), "wait_sec": _client_wait(args)}),
    "client.windows.notepad.uia_canary": ("client", lambda args: {"operation": "run_notepad_uia_canary", "client_id": args.get("client"), "canary": args.get("canary"), "timeout_ms": args.get("timeout_ms", 30000), "wait_sec": _client_wait(args, 30, 30)}),
    "client.windows.desktop.describe": ("client", lambda args: {"operation": "windows_desktop_describe", "client_id": args.get("client"), "wait_sec": _client_wait(args)}),
    "client.windows.desktop.windows.list": ("client", lambda args: {"operation": "windows_desktop_windows_list", "client_id": args.get("client"), "wait_sec": _client_wait(args, 30, 30)}),
    "client.windows.desktop.screenshot": ("client", lambda args: {"operation": "windows_desktop_screenshot", "client_id": args.get("client"), "wait_sec": _client_wait(args, 30, 30)}),
    "client.windows.browser.private_cdp.open": ("client", lambda args: {"operation": "windows_browser_private_cdp_open", "client_id": args.get("client"), "wait_sec": _client_wait(args, 30, 30)}),
    "client.windows.browser.cdp.default.open": ("client", lambda args: {"operation": "windows_browser_cdp_persistent_open", "client_id": args.get("client"), "wait_sec": _client_wait(args, 30, 30)}),
    "client.windows.browser.cdp.status": ("client", lambda args: {"operation": "windows_browser_cdp_status", "client_id": args.get("client"), "wait_sec": _client_wait(args, 30, 30)}),
    "client.windows.browser.cdp.persistent.open": ("client", lambda args: {"operation": "windows_browser_cdp_persistent_open", "client_id": args.get("client"), "wait_sec": _client_wait(args, 30, 30)}),
    "client.windows.browser.cdp.incognito.open": ("client", lambda args: {"operation": "windows_browser_cdp_incognito_open", "client_id": args.get("client"), "wait_sec": _client_wait(args, 30, 30)}),
    "client.windows.browser.cdp.navigate": ("client", lambda args: {"operation": "windows_browser_cdp_navigate", "client_id": args.get("client"), "url": args.get("url"), "wait_sec": _client_wait(args, 30, 30)}),
    "client.windows.browser.cdp.inspect": ("client", lambda args: {"operation": "windows_browser_cdp_inspect", "client_id": args.get("client"), "target_url": args.get("target_url", ""), "max_elements": args.get("max_elements", 120), "query_text": args.get("query_text", ""), "query_selector": args.get("query_selector", ""), "wait_sec": _client_wait(args, 30, 30)}),
    "client.windows.browser.cdp.runtime.inspect": ("client", lambda args: {"operation": "windows_browser_cdp_runtime_inspect", "client_id": args.get("client"), "target_url": args.get("target_url", ""), "locator": args.get("locator", ""), "max_ancestors": args.get("max_ancestors", 8), "max_properties": args.get("max_properties", 80), "wait_sec": _client_wait(args, 30, 30)}),
    "client.windows.browser.cdp.act": ("client", lambda args: {"operation": "windows_browser_cdp_act", "client_id": args.get("client"), "target_url": args.get("target_url", ""), "locator": args.get("locator"), "action": args.get("action"), "value": args.get("value", ""), "key": args.get("key", ""), "expect": args.get("expect"), "wait_sec": _client_wait(args, 30, 30)}),
    "client.windows.browser.cdp.transaction": ("client", lambda args: {"operation": "windows_browser_cdp_act", "client_id": args.get("client"), "target_url": args.get("target_url", ""), "steps": args.get("steps", []), "expect": args.get("expect"), "wait_sec": _client_wait(args, 30, 30)}),
    "client.windows.browser.cdp.procedure": ("client", lambda args: {"operation": "windows_browser_cdp_procedure", "client_id": args.get("client"), "target_url": args.get("target_url", ""), "page_target_id": args.get("page_target_id", ""), "steps": args.get("steps", []), "assertions": args.get("assertions", []), "wait_sec": _client_wait(args, 30, 30)}),
    "client.windows.desktop.inspect": ("client", lambda args: {"operation": "windows_desktop_inspect", "client_id": args.get("client"), "target": args.get("target", {}), "max_elements": args.get("max_elements", 80), "max_depth": args.get("max_depth", 12), "include_values": args.get("include_values", False), "timeout_ms": args.get("timeout_ms", 15000), "wait_sec": _client_wait(args, 30, 30)}),
    "client.windows.desktop.act": ("client", lambda args: {"operation": "windows_desktop_act", "client_id": args.get("client"), "snapshot_id": args.get("snapshot_id"), "ref": args.get("ref"), "action": args.get("action"), "value": args.get("value", ""), "expect": args.get("expect"), "timeout_ms": args.get("timeout_ms", 15000), "wait_sec": _client_wait(args, 30, 30)}),
    "client.windows.desktop.prove": ("client", lambda args: {"operation": "windows_desktop_prove", "client_id": args.get("client"), "snapshot_id": args.get("snapshot_id"), "ref": args.get("ref"), "expect": args.get("expect"), "timeout_ms": args.get("timeout_ms", 15000), "wait_sec": _client_wait(args, 30, 30)}),
}


def _receipt(result: dict[str, Any]) -> dict[str, Any]:
    ok = result.get("ok") is True
    return {
        "ok": ok, "state": "acknowledged" if ok and result.get("acknowledged") is True else "completed" if ok else "failed",
        "observed": result, "proof": [str(item) for item in (result.get("proof") or [])] + ([str(result["command_id"])] if result.get("command_id") else []),
        "error": {} if ok else {"code": str(result.get("code") or "v5_tool_failed"), "summary": str(result.get("summary") or "")[:500]},
    }


def register_repository(target: kernel.Kernel, invoke: Invoke, *, route: dict[str, Any] | None = None) -> None:
    for capability in adapters.repository():
        if capability["authority"] not in target.authorities:
            continue
        executor_name = capability["executor"]
        if executor_name == "repository.map" and isinstance(route, dict):
            summary = {
                key: route.get(key)
                for key in (
                    "route_id", "owner", "workspace_root", "allowed_read_roots",
                    "allowed_write_roots", "caps", "lookup_handles", "checks",
                    "implementation_invariants",
                )
                if route.get(key) not in (None, "", [], {})
            }
            source_index = route.get("source_index") if isinstance(route.get("source_index"), dict) else {}
            source_roots = [str(item) for item in (source_index.get("include_roots") or [])[:12] if str(item).strip()]
            if source_roots:
                summary["source_roots"] = source_roots
            target.register(capability, lambda _cap, _operation, observed=summary: {
                "ok": True, "observed": observed, "proof": [f"route:{observed.get('route_id', '')}"],
            })
            continue
        tool, project = V5_TOOLS[executor_name]
        target.register(capability, lambda _cap, operation, tool=tool, project=project: _receipt(invoke(tool, project(operation["args"]))))


def register_clients(target: kernel.Kernel, clients: list[dict[str, Any]], invoke: Invoke, *, topology: dict[str, Any] | None = None, topology_summary: str = "") -> None:
    if topology:
        capability = adapters.client_environment(topology, topology_summary)
        if capability["authority"] in target.authorities:
            target.register(capability, lambda _cap, _operation, observed=topology: {
                "ok": True, "observed": observed, "proof": ["client.environment.topology"],
            })
    registered = set(target.catalog.all())
    for client in clients:
        client_id = str(client.get("client_id") or client.get("device_id") or "").strip()
        for capability in adapters.live_client(client):
            if capability["authority"] not in target.authorities or capability["id"] in registered:
                continue
            executor_name = capability["executor"]
            tool, project = V5_TOOLS[executor_name]
            def execute(_cap: dict[str, Any], operation: dict[str, Any], *, tool: str = tool, project: Callable[[dict[str, Any]], dict[str, Any]] = project, client_id: str = client_id) -> dict[str, Any]:
                arguments = project(operation["args"])
                if client_id:
                    arguments["client_id"] = client_id
                return _receipt(invoke(tool, arguments))
            target.register(capability, execute)
            registered.add(capability["id"])


def register_client(target: kernel.Kernel, client: dict[str, Any], invoke: Invoke) -> None:
    register_clients(target, [client], invoke)


def register_mcp(target: kernel.Kernel, server: str, tools: list[dict[str, Any]], invoke: InvokeMcp) -> None:
    for capability in adapters.mcp(server, tools):
        if capability["authority"] not in target.authorities:
            continue
        _prefix, declared_server, tool = capability["executor"].split(":", 2)
        target.register(capability, lambda _cap, operation, server=declared_server, tool=tool: _receipt(invoke(server, tool, operation["args"])))
