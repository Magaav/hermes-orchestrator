"""Audited host ports shared by V5 and V6 semantic tool adapters."""
from __future__ import annotations

from typing import Any, Callable

from . import client_ui_actions, session_context
from .v5 import tools as v5_tools


InvokeKernel = Callable[[str, dict[str, Any]], dict[str, Any]]


class InternalHandler:
    headers: dict[str, str] = {}
    client_address = ("127.0.0.1", 0)


def execute_v5(
    name: str, arguments: dict[str, Any], route: dict[str, Any], *, server: Any,
    user: dict[str, Any] | None, runtime: dict[str, Any], principal: str,
    action_id: str, invoke_kernel: InvokeKernel,
) -> dict[str, Any]:
    def invoke(tool: str, payload: dict[str, Any]) -> dict[str, Any]:
        if tool == "session.memory.read":
            result = session_context.read_memory(
                runtime["auth_connect"], user_id=principal,
                pointer=str(payload.get("pointer") or ""), limit=int(payload.get("limit") or 6),
            )
            return {**result, "summary": "Read one account-scoped session." if result.get("ok") else "Account-scoped session read rejected."}
        if tool == "client.ui.control":
            return client_ui_actions.execute(
                payload, route,
                list_clients=lambda: runtime["native_control_clients_payload"](server),
                queue_command=lambda command: runtime["create_native_control_command"](server, command, InternalHandler(), user),
                read_command=lambda device_id, command_id: runtime["read_json_file"](
                    runtime["native_control_command_path"](server, device_id, command_id), {},
                ),
            )
        return invoke_kernel(tool, {**payload, "action_id": action_id})

    return v5_tools.execute(name, arguments, route, invoke=invoke)
