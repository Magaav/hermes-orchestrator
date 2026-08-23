"""Route-scoped control of an authenticated user's live application client."""
from __future__ import annotations

import json
import math
import time
from typing import Any, Callable
from urllib.parse import urlparse

import live_clients as client_transport

OPERATIONS = frozenset({"inspect", "browser_inspect", "open_widget", "space_open", "browser_navigate", "browser_input_receipt", "browser_pointer_dispatch", "browser_javascript_execute_unrestricted", "windows_shell_execute_unrestricted", "command_status"})
CAPABILITIES = {
    "browser_inspect": "observe.browser.inspect",
    "open_widget": "control.widget.open",
    "space_open": "control.space.open",
    "browser_navigate": "control.browser.navigate",
    "browser_input_receipt": "control.browser.input_receipt",
    "browser_pointer_dispatch": "control.browser.pointer.dispatch",
    "browser_javascript_execute_unrestricted": "control.browser.javascript.execute.unrestricted",
    "windows_shell_execute_unrestricted": "windows.shell.execute.unrestricted",
}
ARGUMENT_KEYS = {
    "inspect": frozenset({"operation", "client_id"}),
    "browser_inspect": frozenset({"operation", "client_id", "wait_sec"}),
    "open_widget": frozenset({"operation", "client_id", "widget_id", "wait_sec"}),
    "space_open": frozenset({"operation", "client_id", "space", "wait_sec"}),
    "browser_navigate": frozenset({"operation", "client_id", "url", "wait_sec"}),
    "browser_input_receipt": frozenset({"operation", "client_id", "enabled", "wait_sec"}),
    "browser_pointer_dispatch": frozenset({"operation", "client_id", "x", "y", "wait_sec"}),
    "browser_javascript_execute_unrestricted": frozenset({"operation", "client_id", "javascript", "wait_sec"}),
    "windows_shell_execute_unrestricted": frozenset({"operation", "client_id", "command", "shell", "cwd", "environment", "timeout_ms", "wait_sec"}),
    "command_status": frozenset({"operation", "client_id", "command_id"}),
}


def _contract(route: dict[str, Any]) -> dict[str, Any]:
    value = route.get("client_ui")
    return value if isinstance(value, dict) else {}


def _select(payload: dict[str, Any], client_id: str, capability: str) -> dict[str, Any] | None:
    values = payload.get("clients") if isinstance(payload.get("clients"), list) else []
    candidates = [item for item in values[:160] if isinstance(item, dict) and item.get("live") is True]
    if client_id:
        candidates = [item for item in candidates if str(item.get("client_id") or item.get("device_id") or "") == client_id]
    if capability:
        candidates = [item for item in candidates if capability in set(item.get("capabilities") or [])]
    return candidates[0] if candidates else None


def _compact(client: dict[str, Any]) -> dict[str, Any]:
    return {key: client.get(key) for key in ("client_id", "runtime_type", "route", "visibility", "space_id", "space_name", "capabilities", "last_seen_at", "age_sec", "live")}


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
        "proof": [str(item)[:240] for item in (payload.get("proof") or [])[:32]],
    }


def _browser_answer(result: dict[str, Any]) -> str:
    browser = result.get("browser") if isinstance(result.get("browser"), dict) else {}
    visibility = "visible" if browser.get("visible") is True else "not currently visible"
    title = str(browser.get("title") or "").strip()[:200]
    url = str(browser.get("url") or "").strip()[:500]
    page = title or url
    answer = f"Yes—I can inspect the Browser widget. It is {visibility}." + (f" It has {page} loaded." if page else "")
    receipt_state = str(browser.get("input_receipt_state") or "unsupported")
    receipt = browser.get("input_receipt") if isinstance(browser.get("input_receipt"), dict) else {}
    input_source = str(receipt.get("input_source") or "")
    proof = {str(item) for item in (result.get("proof") or [])[:32]}
    age_ms = receipt.get("age_ms")
    viewport = receipt.get("viewport") if isinstance(receipt.get("viewport"), dict) else {}
    values = (receipt.get("x"), receipt.get("y"), viewport.get("width"), viewport.get("height"))
    coordinates_valid = all(
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        for value in values
    )
    if coordinates_valid:
        x, y, width, height = (round(value) for value in values)
        coordinates_valid = 0 <= x < width and 0 <= y < height and width > 0 and height > 0
    valid_receipt = (
        receipt_state == "enabled"
        and "native.web_surface.input_receipt" in proof
        and receipt.get("schema") == "hermes.wasm_agent.native_web_surface_input_receipt.v1"
        and isinstance(receipt.get("id"), str) and 0 < len(receipt["id"]) <= 80
        and receipt.get("surface_id") == "browser"
        and receipt.get("action") == "pointer.primary_gesture"
        and receipt.get("outcome") == "observed_pre_dispatch"
        and receipt.get("button") == "left"
        and input_source in {"unattributed_native_input", "electron_synthetic"}
        and receipt.get("redacted") is True
        and receipt.get("current_document") is True
        and isinstance(age_ms, (int, float)) and not isinstance(age_ms, bool)
        and math.isfinite(age_ms) and 0 <= age_ms < 120000
        and coordinates_valid
    )
    if not valid_receipt:
        if receipt_state == "disabled":
            return f"{answer} Input receipts are disabled; enable Agent in the Browser widget before the next gesture."
        if receipt_state == "enabled":
            return f"{answer} Input receipts are enabled, but no fresh primary pointer gesture was observed in the last 120 seconds."
        return f"{answer} The installed shell lacks Browser input-receipt support."
    if input_source == "electron_synthetic":
        return (
            f"{answer} A synthetic Electron pointer dispatch traversed the native Browser input-receipt boundary "
            f"before page dispatch at ({x}, {y}) within a viewport measuring {width}×{height} pixels "
            f"on the current loaded document, {round(age_ms)} ms ago. This proves the bounded dispatch/receipt "
            "plumbing, not a physical user click, DOM target, or successful page handling."
        )
    return (
        f"{answer} The native Browser boundary observed a recent unattributed primary pointer gesture before page dispatch "
        f"at ({x}, {y}) within a viewport measuring {width}×{height} pixels "
        f"on the current loaded document, {round(age_ms)} ms ago. This receipt does not identify its physical source, "
        "a DOM target, or successful page handling."
    )


def _page_proof(payload: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    browser = payload.get("browser") if isinstance(payload.get("browser"), dict) else {}
    execution = browser.get("javascript_execution") if isinstance(browser.get("javascript_execution"), dict) else {}
    try:
        value = json.loads(str(execution.get("result_json") or ""))
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    observation = value.get("observation") if isinstance(value.get("observation"), dict) else {}
    observed_value = observation.get("result")
    projected_observation = {
        "observed": observation.get("observed") is True,
        "target": " ".join(str(observation.get("target") or "").split())[:240],
        "predicate": " ".join(str(observation.get("predicate") or "").split())[:240],
        "result": " ".join(json.dumps(observed_value, ensure_ascii=False, sort_keys=True).split())[:240],
    }
    if (
        observation.get("observed") is True
        and all(projected_observation.values())
        and observed_value is not None
        and not isinstance(observed_value, (dict, list))
    ):
        return "observation", projected_observation
    postcondition = value.get("postcondition") if isinstance(value.get("postcondition"), dict) else {}
    projected = {
        key: " ".join(str(postcondition.get(key) or "").split())[:240]
        for key in ("action", "target", "predicate", "before", "after")
    }
    if postcondition.get("observed") is not True or not all(projected.values()) or projected["before"] == projected["after"]:
        return None
    return "postcondition", projected


def execute(
    arguments: dict[str, Any], route: dict[str, Any], *,
    list_clients: Callable[[], dict[str, Any]], queue_command: Callable[[dict[str, Any]], dict[str, Any]],
    read_command: Callable[[str, str], dict[str, Any]], monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    operation = str(arguments.get("operation") or "inspect").strip().lower()
    if operation not in OPERATIONS:
        return {"ok": False, "code": "client_ui_operation_unsupported", "summary": "Unsupported client UI operation."}
    unexpected = sorted(set(arguments) - ARGUMENT_KEYS[operation])
    if unexpected:
        return {"ok": False, "code": "client_ui_arguments_invalid", "summary": f"Unexpected fields for {operation}: {', '.join(unexpected)}."}
    contract = _contract(route)
    if not contract:
        return {"ok": False, "code": "client_ui_contract_missing", "summary": "The route does not declare a client UI contract."}
    declared = {str(item or "").strip().lower() for item in (contract.get("operations") or [])}
    if operation not in declared:
        return {"ok": False, "code": "client_ui_operation_denied", "summary": "The route does not declare this client UI operation."}
    route_caps = {str(item or "").strip().lower() for item in (route.get("caps") or [])}
    if operation not in {"inspect", "browser_inspect", "command_status"} and "client.ui.control" not in route_caps:
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
    if operation == "browser_inspect":
        payload = {}
        command_type = "observability_browser_surface"
    elif operation == "open_widget":
        widget_id = str(arguments.get("widget_id") or "").strip()
        if not widget_id or widget_id not in {str(item or "").strip() for item in (contract.get("widget_ids") or [])}:
            return {"ok": False, "code": "client_widget_denied", "summary": "The requested widget is not declared by this route."}
        payload = {"widget_id": widget_id}
        command_type = operation
    elif operation == "space_open":
        space = str(arguments.get("space") or "").strip()
        if not space or len(space) > 160:
            return {"ok": False, "code": "client_space_reference_invalid", "summary": "Space open requires a name or ID of at most 160 characters."}
        payload = {"space": space}
        command_type = operation
    elif operation == "browser_navigate":
        url = str(arguments.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            return {"ok": False, "code": "client_browser_url_invalid", "summary": "Native browser navigation requires an HTTPS URL."}
        payload = {"url": url[:2000]}
        command_type = operation
    elif operation == "browser_input_receipt":
        try:
            payload = client_transport.normalize_control_payload(operation, {"enabled": arguments.get("enabled")})
        except ValueError as exc:
            return {"ok": False, "code": "client_browser_input_receipt_invalid", "summary": str(exc)}
        command_type = operation
    elif operation == "browser_pointer_dispatch":
        try:
            payload = client_transport.normalize_control_payload(operation, {"x": arguments.get("x"), "y": arguments.get("y")})
        except ValueError as exc:
            return {"ok": False, "code": "client_browser_pointer_invalid", "summary": str(exc)}
        command_type = operation
    elif operation == "browser_javascript_execute_unrestricted":
        try:
            payload = client_transport.normalize_control_payload(operation, {"javascript": arguments.get("javascript")})
        except ValueError as exc:
            return {"ok": False, "code": "client_browser_javascript_invalid", "summary": str(exc)}
        command_type = operation
    elif operation == "windows_shell_execute_unrestricted":
        try:
            payload = client_transport.normalize_control_payload(operation, {
                "command": arguments.get("command"), "shell": arguments.get("shell", "powershell"),
                "cwd": arguments.get("cwd", ""), "environment": arguments.get("environment", {}),
                "timeout_ms": arguments.get("timeout_ms", 60000),
            })
        except ValueError as exc:
            return {"ok": False, "code": "windows_shell_execution_invalid", "summary": str(exc)}
        command_type = operation
    queued = queue_command({"device_id": device_id, "type": command_type, "payload": payload, "reason": "master-frontier-client-ui"})
    command_id = str(queued.get("command_id") or queued.get("commandId") or "")
    if not command_id:
        return {"ok": False, "code": "client_command_queue_failed", "summary": "The client UI command queue returned no command id."}
    max_wait_sec = 30.0 if operation == "browser_javascript_execute_unrestricted" else 20.0
    default_wait_sec = 30.0 if operation == "browser_javascript_execute_unrestricted" else 18.0
    try:
        wait_sec = min(max_wait_sec, max(0.0, float(arguments.get("wait_sec", default_wait_sec))))
    except (TypeError, ValueError):
        wait_sec = default_wait_sec
    deadline = monotonic() + wait_sec
    record = read_command(device_id, command_id)
    while str(record.get("status") or "") != "finished" and monotonic() < deadline:
        sleep(0.1)
        record = read_command(device_id, command_id)
    resolved = _result(record, client, command_id)
    if operation != "browser_inspect" and resolved.get("ok") is True:
        resolved["proof"] = list(dict.fromkeys(["client.ack", *(resolved.get("proof") or [])]))
    if operation == "browser_inspect" and resolved.get("ok") is True:
        resolved["answer"] = _browser_answer(resolved.get("result") or {})[:600]
    if operation == "space_open" and resolved.get("ok") is True:
        observed = resolved.get("result") if isinstance(resolved.get("result"), dict) else {}
        space_name = str(observed.get("space_name") or arguments.get("space") or "the requested").strip()[:160]
        resolved["proof"] = list(dict.fromkeys(["client.ack", *(resolved.get("proof") or [])]))
        if observed.get("opened") is True and (observed.get("space_id") or observed.get("space_name")):
            resolved["proof"] = list(dict.fromkeys([*resolved.get("proof", []), "client.space.active"]))
        resolved["answer"] = f"Opened the {space_name} space."
    if operation == "browser_javascript_execute_unrestricted" and resolved.get("ok") is True:
        page_proof = _page_proof(resolved.get("result") or {})
        if page_proof is None:
            resolved.update({
                "ok": False, "code": "client_page_postcondition_unverified",
                "summary": "The Browser JavaScript ran, but it returned neither a valid read-only observation nor an observed before/after postcondition.",
            })
        else:
            proof_kind, proof_value = page_proof
            proof_name = f"client.page.{proof_kind}.observed"
            resolved["proof"] = list(dict.fromkeys([
                "client.ack", *(resolved.get("proof") or []), proof_name,
            ]))
            resolved[proof_kind] = proof_value
    return resolved
