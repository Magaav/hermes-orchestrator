"""V6 semantic executors backed by the trusted V5 tool substrate."""
from __future__ import annotations

from typing import Any, Callable

from . import adapters, kernel


Invoke = Callable[[str, dict[str, Any]], dict[str, Any]]
InvokeMcp = Callable[[str, str, dict[str, Any]], dict[str, Any]]


V5_TOOLS = {
    "repository.map": ("inspect", lambda args: {"target": "application", "id": str(args.get("id") or "repository")}),
    "repository.search": ("search", lambda args: args),
    "repository.read": ("read", lambda args: args),
    "repository.patch": ("edit", lambda args: args),
    "repository.test": ("test", lambda args: args),
    "repository.diff": ("diff", lambda args: args),
    "repository.prove": ("prove", lambda args: args),
    "client.inspect": ("client", lambda args: {**args, "operation": "inspect"}),
    "client.widget.open": ("client", lambda args: {"operation": "open_widget", "client_id": args.get("client"), "widget_id": args.get("widget"), "wait_sec": args.get("wait_sec", 18)}),
    "client.browser.navigate": ("client", lambda args: {"operation": "browser_navigate", "client_id": args.get("client"), "url": args.get("url"), "wait_sec": args.get("wait_sec", 18)}),
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
                for key in ("route_id", "owner", "workspace_root", "allowed_read_roots", "allowed_write_roots", "caps", "lookup_handles", "checks")
                if route.get(key) not in (None, "", [], {})
            }
            target.register(capability, lambda _cap, _operation, observed=summary: {
                "ok": True, "observed": observed, "proof": [f"route:{observed.get('route_id', '')}"],
            })
            continue
        tool, project = V5_TOOLS[executor_name]
        target.register(capability, lambda _cap, operation, tool=tool, project=project: _receipt(invoke(tool, project(operation["args"]))))


def register_client(target: kernel.Kernel, client: dict[str, Any], invoke: Invoke) -> None:
    client_id = str(client.get("client_id") or client.get("device_id") or "").strip()
    for capability in adapters.live_client(client):
        if capability["authority"] not in target.authorities:
            continue
        executor_name = capability["executor"]
        tool, project = V5_TOOLS[executor_name]
        def execute(_cap: dict[str, Any], operation: dict[str, Any], *, tool: str = tool, project: Callable[[dict[str, Any]], dict[str, Any]] = project) -> dict[str, Any]:
            arguments = project(operation["args"])
            if client_id:
                arguments["client_id"] = client_id
            return _receipt(invoke(tool, arguments))
        target.register(capability, execute)


def register_mcp(target: kernel.Kernel, server: str, tools: list[dict[str, Any]], invoke: InvokeMcp) -> None:
    for capability in adapters.mcp(server, tools):
        if capability["authority"] not in target.authorities:
            continue
        _prefix, declared_server, tool = capability["executor"].split(":", 2)
        target.register(capability, lambda _cap, operation, server=declared_server, tool=tool: _receipt(invoke(server, tool, operation["args"])))
