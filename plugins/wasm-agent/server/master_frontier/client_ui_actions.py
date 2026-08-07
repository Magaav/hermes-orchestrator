"""Route-scoped control of an authenticated user's live application client."""
from __future__ import annotations

import time
from typing import Any, Callable
from urllib.parse import urlparse

OPERATIONS = frozenset({"inspect", "open_widget", "browser_navigate", "command_status"})
CAPABILITIES = {"open_widget": "control.widget.open", "browser_navigate": "control.browser.navigate"}


def _contract(route: dict[str, Any]) -> dict[str, Any]:
    value = route.get("client_ui")
    return value if isinstance(value, dict) else {}


def _select(payload: dict[str, Any], client_id: str, capability: str) -> dict[str, Any] | None:
    values = payload.get("clients") if isinstance(payload.get("clients"), list) else []
    candidates = [item for item in values[:160] if isinstance(item, dict) and item.get("live") is True and item.get("runtime_type") == "electron"]
    if client_id:
        candidates = [item for item in candidates if str(item.get("client_id") or item.get("device_id") or "") == client_id]
    if capability:
        candidates = [item for item in candidates if capability in set(item.get("capabilities") or [])]
    return candidates[0] if candidates else None


def _compact(client: dict[str, Any]) -> dict[str, Any]:
    return {key: client.get(key) for key in ("client_id", "runtime_type", "route", "visibility", "capabilities", "last_seen_at", "age_sec", "live")}


def _result(record: dict[str, Any], client: dict[str, Any], command_id: str) -> dict[str, Any]:
    status = str(record.get("status") or "pending")
    payload = record.get("result") if isinstance(record.get("result"), dict) else {}
    acknowledged = status == "finished"
    ok = acknowledged and payload.get("ok") is True
    return {
        "ok": ok,
        "code": "client_command_acknowledged" if ok else ("client_command_failed" if acknowledged else "client_command_pending"),
        "summary": "The live Electron client acknowledged the UI command." if ok else ("The live Electron client rejected the UI command." if acknowledged else "The UI command is queued but has not been acknowledged yet."),
        "client": _compact(client), "command_id": command_id, "status": status,
        "acknowledged": acknowledged, "result": payload,
    }


def execute(
    arguments: dict[str, Any], route: dict[str, Any], *,
    list_clients: Callable[[], dict[str, Any]], queue_command: Callable[[dict[str, Any]], dict[str, Any]],
    read_command: Callable[[str, str], dict[str, Any]], monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    operation = str(arguments.get("operation") or "inspect").strip().lower()
    if operation not in OPERATIONS:
        return {"ok": False, "code": "client_ui_operation_unsupported", "summary": "Unsupported client UI operation."}
    contract = _contract(route)
    if not contract:
        return {"ok": False, "code": "client_ui_contract_missing", "summary": "The route does not declare a client UI contract."}
    route_caps = {str(item or "").strip().lower() for item in (route.get("caps") or [])}
    if operation != "inspect" and "client.ui.control" not in route_caps:
        return {"ok": False, "code": "client_ui_control_denied", "summary": "The route grants client inspection but not client UI control."}
    required = CAPABILITIES.get(operation, "")
    client = _select(list_clients(), str(arguments.get("client_id") or "").strip(), required)
    if client is None:
        return {"ok": False, "code": "live_electron_client_missing", "summary": "No live Electron client advertises the required UI capability.", "required_capability": required}
    device_id = str(client.get("device_id") or client.get("client_id") or "")
    if operation == "inspect":
        return {"ok": True, "summary": "Found one live route-scoped Electron client.", "client": _compact(client)}
    if operation == "command_status":
        command_id = str(arguments.get("command_id") or "").strip()
        if not command_id:
            return {"ok": False, "code": "client_command_id_missing", "summary": "Command status requires command_id."}
        return _result(read_command(device_id, command_id), client, command_id)
    if operation == "open_widget":
        widget_id = str(arguments.get("widget_id") or "").strip()
        if not widget_id or widget_id not in {str(item or "").strip() for item in (contract.get("widget_ids") or [])}:
            return {"ok": False, "code": "client_widget_denied", "summary": "The requested widget is not declared by this route."}
        payload = {"widget_id": widget_id}
    else:
        url = str(arguments.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            return {"ok": False, "code": "client_browser_url_invalid", "summary": "Native browser navigation requires an HTTPS URL."}
        payload = {"url": url[:2000]}
    queued = queue_command({"device_id": device_id, "type": operation, "payload": payload, "reason": "master-frontier-client-ui"})
    command_id = str(queued.get("command_id") or queued.get("commandId") or "")
    if not command_id:
        return {"ok": False, "code": "client_command_queue_failed", "summary": "The client UI command queue returned no command id."}
    try:
        wait_sec = min(20.0, max(0.0, float(arguments.get("wait_sec", 18))))
    except (TypeError, ValueError):
        wait_sec = 18.0
    deadline = monotonic() + wait_sec
    record = read_command(device_id, command_id)
    while str(record.get("status") or "") != "finished" and monotonic() < deadline:
        sleep(0.1)
        record = read_command(device_id, command_id)
    return _result(record, client, command_id)
