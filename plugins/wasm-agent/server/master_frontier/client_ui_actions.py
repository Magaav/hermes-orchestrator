"""Route-scoped control of an authenticated user's live application client."""
from __future__ import annotations

import time
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

import live_clients as client_transport

OPERATIONS = frozenset({"inspect", "space_catalog", "runtime_diagnose", "runtime_refresh", "open_widget", "space_open", "windows_shell_execute_unrestricted", "show_companion_overlay", "run_notepad_uia_canary", "windows_browser_cdp_status", "windows_browser_cdp_persistent_open", "windows_browser_cdp_incognito_open", "windows_browser_private_cdp_open", "windows_browser_cdp_navigate", "windows_browser_cdp_inspect", "windows_browser_cdp_runtime_inspect", "windows_browser_cdp_act", "windows_browser_cdp_procedure", "windows_desktop_windows_list", "windows_desktop_screenshot", "windows_desktop_describe", "windows_desktop_inspect", "windows_desktop_act", "windows_desktop_prove", "command_status"})
CAPABILITIES = {
    "space_catalog": "observe.spaces.catalog",
    "runtime_diagnose": "observe.runtime.diagnose",
    "runtime_refresh": "control.runtime.refresh",
    "open_widget": "control.widget.open",
    "space_open": "control.space.open",
    "windows_shell_execute_unrestricted": "windows.shell.execute.unrestricted",
    "show_companion_overlay": "companion.overlay.show",
    "run_notepad_uia_canary": "windows.desktop.notepad_uia_canary",
    "windows_browser_cdp_status": "run_hot_operation",
    "windows_browser_private_cdp_open": "run_hot_operation",
    "windows_browser_cdp_persistent_open": "run_hot_operation",
    "windows_browser_cdp_incognito_open": "run_hot_operation",
    "windows_browser_cdp_navigate": "run_hot_operation",
    "windows_browser_cdp_inspect": "run_hot_operation",
    "windows_browser_cdp_runtime_inspect": "run_hot_operation",
    "windows_browser_cdp_act": "run_hot_operation",
    "windows_browser_cdp_procedure": "run_hot_operation",
    "windows_desktop_windows_list": "run_hot_operation",
    "windows_desktop_screenshot": "run_hot_operation",
    "windows_desktop_describe": "windows.desktop.describe",
    "windows_desktop_inspect": "windows.desktop.inspect",
    "windows_desktop_act": "windows.desktop.act",
    "windows_desktop_prove": "windows.desktop.prove",
}
WIDGET_OPERATION_TARGETS: dict[str, str] = {}
ARGUMENT_KEYS = {
    "inspect": frozenset({"operation", "client_id"}),
    "space_catalog": frozenset({"operation", "client_id", "wait_sec"}),
    "runtime_diagnose": frozenset({"operation", "client_id", "lease_ms", "wait_sec"}),
    "runtime_refresh": frozenset({"operation", "client_id", "wait_sec"}),
    "open_widget": frozenset({"operation", "client_id", "widget_id", "wait_sec"}),
    "space_open": frozenset({"operation", "client_id", "space", "wait_sec"}),
    "windows_shell_execute_unrestricted": frozenset({"operation", "client_id", "command", "shell", "cwd", "environment", "timeout_ms", "wait_sec"}),
    "show_companion_overlay": frozenset({"operation", "client_id", "wait_sec"}),
    "run_notepad_uia_canary": frozenset({"operation", "client_id", "canary", "timeout_ms", "wait_sec"}),
    "windows_browser_cdp_status": frozenset({"operation", "client_id", "wait_sec"}),
    "windows_browser_private_cdp_open": frozenset({"operation", "client_id", "wait_sec"}),
    "windows_browser_cdp_persistent_open": frozenset({"operation", "client_id", "wait_sec"}),
    "windows_browser_cdp_incognito_open": frozenset({"operation", "client_id", "wait_sec"}),
    "windows_browser_cdp_navigate": frozenset({"operation", "client_id", "url", "wait_sec"}),
    "windows_browser_cdp_inspect": frozenset({"operation", "client_id", "target_url", "max_elements", "query_text", "query_selector", "wait_sec"}),
    "windows_browser_cdp_runtime_inspect": frozenset({"operation", "client_id", "target_url", "locator", "max_ancestors", "max_properties", "wait_sec"}),
    "windows_browser_cdp_act": frozenset({"operation", "client_id", "target_url", "locator", "action", "value", "key", "steps", "expect", "wait_sec"}),
    "windows_browser_cdp_procedure": frozenset({"operation", "client_id", "target_url", "page_target_id", "steps", "assertions", "wait_sec"}),
    "windows_desktop_windows_list": frozenset({"operation", "client_id", "wait_sec"}),
    "windows_desktop_screenshot": frozenset({"operation", "client_id", "wait_sec"}),
    "windows_desktop_describe": frozenset({"operation", "client_id", "wait_sec"}),
    "windows_desktop_inspect": frozenset({"operation", "client_id", "target", "max_elements", "max_depth", "include_values", "timeout_ms", "wait_sec"}),
    "windows_desktop_act": frozenset({"operation", "client_id", "snapshot_id", "ref", "action", "value", "expect", "timeout_ms", "wait_sec"}),
    "windows_desktop_prove": frozenset({"operation", "client_id", "snapshot_id", "ref", "expect", "timeout_ms", "wait_sec"}),
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


def _widget_ids(value: Any) -> list[str]:
    items = value if isinstance(value, list) else []
    return list(dict.fromkeys(str(item or "").strip()[:80] for item in items if str(item or "").strip()))[:32]


def surface_manifest(client: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """Intersect route authority with the live client's explicit active-surface manifest."""
    declared = _widget_ids(contract.get("widget_ids"))
    reported = _widget_ids(client.get("widget_ids")) if client.get("widget_manifest") == client_transport.ACTIVE_SURFACE_MANIFEST else []
    available = [item for item in declared if item in set(reported)]
    route_capabilities = {
        CAPABILITIES[operation] for operation in (contract.get("operations") or [])
        if operation in CAPABILITIES
    }
    client_capabilities = {str(item) for item in (client.get("capabilities") or [])}
    return {
        "runtime_type": str(client.get("runtime_type") or ""),
        "client_id": str(client.get("client_id") or client.get("device_id") or ""),
        "capabilities": sorted(route_capabilities & client_capabilities),
        "widget_ids": declared,
        "available_widget_ids": available,
        "widget_manifest": str(client.get("widget_manifest") or ""),
        "space_id": str(client.get("space_id") or "")[:120],
        "space_name": str(client.get("space_name") or "")[:160],
    }


def space_catalog(payload: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any] | None:
    """Validate and intersect an on-demand client catalog with route widget authority."""
    raw_spaces = payload.get("spaces")
    if payload.get("manifest") != client_transport.SPACE_CATALOG_MANIFEST or not isinstance(raw_spaces, list):
        return None
    declared = _widget_ids(contract.get("widget_ids"))
    spaces: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_spaces[:32]:
        if not isinstance(raw, dict):
            continue
        space_id = str(raw.get("id") or "").strip()[:120]
        if not space_id or space_id in seen:
            continue
        seen.add(space_id)
        reported = set(_widget_ids(raw.get("widget_ids")))
        spaces.append({
            "id": space_id,
            "name": str(raw.get("name") or space_id).strip()[:160],
            "kind": str(raw.get("kind") or "user").strip()[:24],
            "active": raw.get("active") is True,
            "widget_ids": [widget_id for widget_id in declared if widget_id in reported],
        })
    return {
        "manifest": client_transport.SPACE_CATALOG_MANIFEST,
        "spaces": spaces,
        "truncated": payload.get("truncated") is True or len(raw_spaces) > 32,
    }


def _compact(client: dict[str, Any]) -> dict[str, Any]:
    return {key: client.get(key) for key in ("client_id", "runtime_type", "route", "visibility", "space_id", "space_name", "widget_manifest", "widget_ids", "capabilities", "last_seen_at", "age_sec", "live")}


def _canonical_http_url(value: Any) -> str:
    """Match browser-canonical HTTP(S) URLs without weakening target identity."""
    try:
        parsed = urlsplit(str(value or "").strip())
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return ""
        host = parsed.hostname.lower()
        port = parsed.port
        if port and not ((parsed.scheme.lower() == "http" and port == 80) or (parsed.scheme.lower() == "https" and port == 443)):
            host = f"{host}:{port}"
        return urlunsplit((parsed.scheme.lower(), host, parsed.path or "/", parsed.query, parsed.fragment))
    except (TypeError, ValueError):
        return ""


def _cdp_action_match_projection(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    projected = dict(item)
    if str(projected.get("actionLocator") or ""):
        projected.pop("locator", None)
        projected.pop("ancestry", None)
        projected.pop("hit", None)
    return projected


def _result(record: dict[str, Any], client: dict[str, Any], command_id: str) -> dict[str, Any]:
    status = str(record.get("status") or "pending")
    payload = record.get("result") if isinstance(record.get("result"), dict) else {}
    acknowledged = status == "finished"
    ok = acknowledged and payload.get("ok") is True
    envelope = payload.get("rawResult") if isinstance(payload.get("rawResult"), dict) else payload
    inner_message = str(envelope.get("message") or "")
    cause = str(inner_message if inner_message.startswith(("windows_", "browser_")) else envelope.get("cause") or envelope.get("failureClassification") or inner_message or envelope.get("error") or "")[:160]
    lifecycle_causes = {"windows_cdp_persistent_unavailable", "windows_cdp_page_missing"}
    recovery = {
        "recoverable": cause in lifecycle_causes or cause == "commit_unknown",
        "next": (
            "client.windows.browser.cdp.default.open" if cause in lifecycle_causes
            else "client.windows.browser.cdp.inspect" if cause == "commit_unknown"
            else ""
        ),
    }
    return {
        "ok": ok,
        "code": "client_command_acknowledged" if ok else ((cause or "client_command_failed") if acknowledged else "client_command_pending"),
        "summary": "The live Electron client acknowledged the UI command." if ok else ((f"The native operation failed with {cause}; next probe: {recovery['next'] or 'bounded receipt detail'}." if cause else "The live Electron client rejected the UI command.") if acknowledged else "The UI command is queued but has not been acknowledged yet."),
        "client": _compact(client), "command_id": command_id, "status": status,
        "acknowledged": acknowledged, "result": payload,
        "proof": [str(item)[:240] for item in (payload.get("proof") or [])[:32]],
        **({"cause": cause, "recovery": recovery} if cause else {}),
    }


def _windows_desktop_projection(result: dict[str, Any]) -> dict[str, Any]:
    """Bound a UIA snapshot into an LLM-readable window and control inventory."""
    window = result.get("window") if isinstance(result.get("window"), dict) else {}
    controls = []
    elements = result.get("elements") if isinstance(result.get("elements"), list) else []
    for item in elements[:40]:
        if not isinstance(item, dict):
            continue
        projected = {
            key: item.get(key)
            for key in ("ref", "name", "control_type", "automation_id", "enabled", "offscreen", "patterns", "selected", "focused", "editable", "value", "toggle_state", "expanded")
            if item.get(key) not in (None, "")
        }
        if projected:
            controls.append(projected)
    return {
        "schema": "master.frontier.windows_desktop_projection.v1",
        "snapshot_id": str(result.get("snapshot_id") or ""),
        "window": {
            key: window.get(key)
            for key in ("name", "title", "process_name", "process_id", "class_name", "hwnd")
            if window.get(key) not in (None, "")
        },
        "controls": controls,
        "control_count_returned": len(controls),
        "snapshot_truncated": result.get("truncated") is True or len(elements) > len(controls),
        "enumeration": {
            "element_count": int(result.get("element_count") or len(elements)),
            "conversion_errors": int(result.get("enumeration_errors") or 0),
            "tree_view": str(result.get("tree_view") or "control")[:40],
        },
    }


def _windows_desktop_target_matches(target: dict[str, Any], result: dict[str, Any]) -> bool:
    if not target:
        return True
    window = result.get("window") if isinstance(result.get("window"), dict) else {}
    title = str(window.get("name") or window.get("title") or "")
    if target.get("title_contains") and str(target["title_contains"]).casefold() not in title.casefold():
        return False
    if target.get("process_id") is not None:
        try:
            if int(target["process_id"]) != int(window.get("process_id")):
                return False
        except (TypeError, ValueError):
            return False
    if target.get("hwnd") is not None:
        try:
            expected = int(str(target["hwnd"]), 0)
            observed = int(str(result.get("hwnd") or "0"), 0)
        except ValueError:
            return False
        if expected != observed:
            return False
    return True


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
    if operation not in {"inspect", "space_catalog", "windows_desktop_windows_list", "windows_desktop_screenshot", "windows_desktop_describe", "windows_desktop_inspect", "windows_desktop_prove", "command_status"} and "client.ui.control" not in route_caps:
        return {"ok": False, "code": "client_ui_control_denied", "summary": "The route grants client inspection but not client UI control."}
    target_widget = WIDGET_OPERATION_TARGETS.get(operation, "")
    if operation == "open_widget":
        target_widget = str(arguments.get("widget_id") or "").strip()
        if not target_widget or target_widget not in {str(item or "").strip() for item in (contract.get("widget_ids") or [])}:
            return {"ok": False, "code": "client_widget_denied", "summary": "The requested widget is not declared by this route."}
    required = CAPABILITIES.get(operation, "")
    client = _select(list_clients(), str(arguments.get("client_id") or "").strip(), required)
    if client is None:
        return {"ok": False, "code": "live_electron_client_missing", "summary": "No live Electron client advertises the required UI capability.", "required_capability": required}
    if target_widget:
        if client.get("widget_manifest") != client_transport.ACTIVE_SURFACE_MANIFEST:
            return {
                "ok": False, "code": "client_widget_manifest_missing",
                "summary": "The live client has not reported an active-surface widget manifest, so the UI action is unavailable.",
                "widget_id": target_widget, "client": _compact(client),
            }
        available_widget_ids = _widget_ids(client.get("widget_ids"))
        if target_widget not in set(available_widget_ids):
            space = str(client.get("space_name") or client.get("space_id") or "the active space")[:160]
            return {
                "ok": False, "code": "client_widget_unavailable_on_active_surface",
                "summary": f"The {target_widget} widget is not available in {space}.",
                "widget_id": target_widget, "available_widget_ids": available_widget_ids,
                "client": _compact(client),
            }
    device_id = str(client.get("device_id") or client.get("client_id") or "")
    if operation == "inspect":
        return {"ok": True, "summary": "Found one live route-scoped Electron client.", "client": _compact(client)}
    if operation == "command_status":
        command_id = str(arguments.get("command_id") or "").strip()
        if not command_id:
            return {"ok": False, "code": "client_command_id_missing", "summary": "Command status requires command_id."}
        return _result(read_command(device_id, command_id), client, command_id)
    if operation == "space_catalog":
        payload = {}
        command_type = operation
    elif operation == "runtime_refresh":
        payload = {}
        command_type = operation
    elif operation == "runtime_diagnose":
        try:
            payload = client_transport.normalize_control_payload(operation, {"lease_ms": arguments.get("lease_ms", 30000)})
        except ValueError as exc:
            return {"ok": False, "code": "client_runtime_diagnose_invalid", "summary": str(exc)}
        command_type = operation
    elif operation == "open_widget":
        payload = {"widget_id": target_widget}
        command_type = operation
    elif operation == "space_open":
        space = str(arguments.get("space") or "").strip()
        if not space or len(space) > 160:
            return {"ok": False, "code": "client_space_reference_invalid", "summary": "Space open requires a name or ID of at most 160 characters."}
        payload = {"space": space}
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
    elif operation in {"show_companion_overlay", "run_notepad_uia_canary"}:
        candidate = {} if operation == "show_companion_overlay" else {
            "canary": arguments.get("canary"), "timeout_ms": arguments.get("timeout_ms", 30000),
        }
        try:
            payload = client_transport.normalize_control_payload(operation, candidate)
        except ValueError as exc:
            return {"ok": False, "code": f"{operation}_invalid", "summary": str(exc)}
        command_type = operation
    elif operation == "windows_desktop_windows_list":
        payload = {"operationName": "inspect_windows_open_apps", "args": {}}
        command_type = "run_hot_operation"
    elif operation == "windows_desktop_screenshot":
        payload = {"operationName": "capture_windows_desktop_screenshot", "args": {}}
        command_type = "run_hot_operation"
    elif operation == "windows_browser_cdp_status":
        payload = {"operationName": "status_windows_cdp_persistent", "args": {}}
        command_type = "run_hot_operation"
    elif operation in {"windows_browser_private_cdp_open", "windows_browser_cdp_incognito_open", "windows_browser_cdp_persistent_open"}:
        operation_name = "open_windows_cdp_persistent" if operation == "windows_browser_cdp_persistent_open" else "open_windows_cdp_incognito"
        payload = {"operationName": operation_name, "args": {}}
        command_type = "run_hot_operation"
    elif operation == "windows_browser_cdp_navigate":
        url = str(arguments.get("url") or "").strip()
        if len(url) > 2048 or not url.startswith(("http://", "https://")):
            return {"ok": False, "code": "windows_browser_cdp_url_invalid", "summary": "CDP navigation requires an HTTP(S) URL of at most 2048 characters."}
        payload = {"operationName": "navigate_windows_cdp_persistent", "args": {"url": url}}
        command_type = "run_hot_operation"
    elif operation == "windows_browser_cdp_inspect":
        payload = {"operationName": "inspect_windows_cdp_persistent", "args": {
            "target_url": str(arguments.get("target_url") or "")[:2048],
            "max_elements": max(1, min(int(arguments.get("max_elements") or 120), 200)),
            "query_text": str(arguments.get("query_text") or "")[:300],
            "query_selector": str(arguments.get("query_selector") or "")[:300],
        }}
        command_type = "run_hot_operation"
    elif operation == "windows_browser_cdp_runtime_inspect":
        payload = {"operationName": "inspect_windows_cdp_runtime", "args": {
            key: arguments.get(key) for key in ("target_url", "locator", "max_ancestors", "max_properties")
            if arguments.get(key) not in (None, "")
        }}
        command_type = "run_hot_operation"
    elif operation == "windows_browser_cdp_act":
        payload = {"operationName": "act_windows_cdp_persistent", "args": {
            key: arguments.get(key) for key in ("target_url", "locator", "action", "value", "key", "steps", "expect")
            if arguments.get(key) not in (None, "")
        }}
        command_type = "run_hot_operation"
    elif operation == "windows_browser_cdp_procedure":
        payload = {"operationName": "execute_windows_cdp_procedure", "args": {
            "target_url": str(arguments.get("target_url") or "")[:2048],
            "page_target_id": str(arguments.get("page_target_id") or "")[:160],
            "steps": arguments.get("steps", []), "assertions": arguments.get("assertions", []),
        }}
        command_type = "run_hot_operation"
    elif operation in {"windows_desktop_describe", "windows_desktop_inspect", "windows_desktop_act", "windows_desktop_prove"}:
        keys = {
            "windows_desktop_describe": (),
            "windows_desktop_inspect": ("target", "max_elements", "max_depth", "include_values", "timeout_ms"),
            "windows_desktop_act": ("snapshot_id", "ref", "action", "value", "expect", "timeout_ms"),
            "windows_desktop_prove": ("snapshot_id", "ref", "expect", "timeout_ms"),
        }[operation]
        candidate = {key: arguments[key] for key in keys if key in arguments}
        try:
            payload = client_transport.normalize_control_payload(operation, candidate)
        except ValueError as exc:
            return {"ok": False, "code": f"{operation}_invalid", "summary": str(exc)}
        command_type = operation
    queued = queue_command({"device_id": device_id, "type": command_type, "payload": payload, "reason": "master-frontier-client-ui"})
    command_id = str(queued.get("command_id") or queued.get("commandId") or "")
    if not command_id:
        return {"ok": False, "code": "client_command_queue_failed", "summary": "The client UI command queue returned no command id."}
    slow_operations = {"windows_browser_cdp_status", "windows_browser_private_cdp_open", "windows_browser_cdp_persistent_open", "windows_browser_cdp_incognito_open", "windows_browser_cdp_navigate", "windows_browser_cdp_inspect", "windows_browser_cdp_runtime_inspect", "windows_browser_cdp_act", "windows_browser_cdp_procedure", "windows_desktop_windows_list", "windows_desktop_screenshot", "windows_desktop_inspect", "windows_desktop_act", "windows_desktop_prove"}
    max_wait_sec = 30.0 if operation in slow_operations else 20.0
    default_wait_sec = 30.0 if operation in slow_operations else 18.0
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
    if operation == "windows_desktop_inspect" and resolved.get("ok") is True:
        observed = resolved.get("result") if isinstance(resolved.get("result"), dict) else {}
        target = arguments.get("target") if isinstance(arguments.get("target"), dict) else {}
        if not _windows_desktop_target_matches(target, observed):
            resolved.update({
                "ok": False, "code": "windows_desktop_target_mismatch",
                "summary": "The Windows inspection receipt did not identify the exact requested window.",
            })
    if operation != "space_catalog" and resolved.get("ok") is True:
        resolved["proof"] = list(dict.fromkeys(["client.ack", *(resolved.get("proof") or [])]))
    if operation == "space_catalog" and resolved.get("ok") is True:
        catalog = space_catalog(resolved.get("result") or {}, contract)
        proof = set(resolved.get("proof") or [])
        if catalog is None or "client.space.catalog" not in proof:
            resolved.update({
                "ok": False, "code": "client_space_catalog_unverified",
                "summary": "The live client did not return a valid bounded space catalog with ownership proof.",
            })
        else:
            resolved["result"] = catalog
            resolved["catalog"] = catalog
            resolved["proof"] = ["client.space.catalog"]
            resolved["answer"] = f"Discovered {len(catalog['spaces'])} authenticated client spaces and their route-declared widgets."
    if operation == "open_widget" and resolved.get("ok") is True:
        observed = resolved.get("result") if isinstance(resolved.get("result"), dict) else {}
        proof = set(resolved.get("proof") or [])
        verified = (
            observed.get("widget_id") == target_widget
            and observed.get("opened") is True
            and observed.get("visible") is True
            and "client.widget.visible" in proof
        )
        if not verified:
            resolved.update({
                "ok": False, "code": "client_widget_postcondition_unverified",
                "summary": "The client acknowledged the widget command but did not prove the widget visible on the active surface.",
            })
        else:
            resolved["answer"] = f"Opened the {target_widget} widget and verified it is visible in the active space."
    if operation == "windows_desktop_inspect" and resolved.get("ok") is True:
        projection = _windows_desktop_projection(resolved.get("result") or {})
        resolved["model_projection"] = projection
        window = projection.get("window") or {}
        label = str(window.get("name") or window.get("title") or "the foreground window")
        resolved["answer"] = f"Inspected {label} and found {projection['control_count_returned']} bounded controls."
    if operation == "windows_desktop_windows_list" and resolved.get("ok") is True:
        envelope = resolved.get("result") if isinstance(resolved.get("result"), dict) else {}
        inventory = envelope.get("rawResult") if isinstance(envelope.get("rawResult"), dict) else envelope
        valid = (
            inventory.get("schema") == "hermes.wasm_agent.windows_open_apps.v1"
            and inventory.get("operation") == "inspect_windows_open_apps"
            and isinstance(inventory.get("windows"), list)
            and inventory.get("ok") is True
        )
        if not valid:
            resolved.update({
                "ok": False, "code": "windows_desktop_windows_inventory_invalid",
                "summary": "The Windows hot operation did not return a valid bounded top-level window inventory.",
            })
        else:
            windows = [item for item in inventory["windows"][:64] if isinstance(item, dict)]
            projection = {
                "schema": inventory["schema"], "windowCount": len(windows),
                "windows": windows, "truncated": inventory.get("truncated") is True,
            }
            resolved["result"] = projection
            resolved["model_projection"] = projection
            resolved["proof"] = list(dict.fromkeys(["client.ack", "windows.desktop.top_level_windows"]))
            labels = [
                f"{str(item.get('title') or item.get('processName') or 'Untitled')[:100]} ({str(item.get('processName') or 'unknown')[:40]})"
                for item in windows[:12]
            ]
            suffix = "; …" if len(windows) > len(labels) else ""
            resolved["answer"] = f"{len(windows)} visible top-level Windows windows: " + "; ".join(labels) + suffix
    if operation == "windows_desktop_screenshot" and resolved.get("ok") is True:
        envelope = resolved.get("result") if isinstance(resolved.get("result"), dict) else {}
        receipt = envelope.get("rawResult") if isinstance(envelope.get("rawResult"), dict) else envelope
        artifact = receipt.get("artifact") if isinstance(receipt.get("artifact"), dict) else {}
        valid = receipt.get("schema") == "hermes.wasm_agent.windows_desktop_screenshot.v1" and receipt.get("operation") == "capture_windows_desktop_screenshot" and receipt.get("ok") is True and isinstance(artifact.get("width"), int) and isinstance(artifact.get("height"), int) and len(str(artifact.get("sha256") or "")) == 64
        if not valid:
            resolved.update({"ok": False, "code": "windows_desktop_screenshot_invalid", "summary": "The Windows hot operation did not return a valid screenshot artifact receipt."})
        else:
            projection = {"schema": receipt["schema"], "artifact": {key: artifact.get(key) for key in ("path", "sha256", "width", "height", "left", "top", "capturedAt", "scope", "containsSensitivePixels")}}
            resolved["result"] = projection
            resolved["model_projection"] = projection
            resolved["proof"] = ["client.ack", "windows.desktop.screenshot"]
            resolved["answer"] = f"Captured the {artifact.get('width')}×{artifact.get('height')} Windows virtual desktop to a local artifact (SHA-256 {str(artifact.get('sha256'))[:12]}…)."
    if operation == "windows_browser_cdp_status" and resolved.get("ok") is True:
        envelope = resolved.get("result") if isinstance(resolved.get("result"), dict) else {}
        status = envelope.get("rawResult") if isinstance(envelope.get("rawResult"), dict) else envelope
        valid = status.get("schema") == "hermes.wasm_agent.windows_cdp_status.v1" and status.get("operation") == "status_windows_cdp_persistent" and status.get("ok") is True and status.get("state") in {"closed", "open_no_page", "open_page"} and "windows.browser.cdp.lifecycle.observed" in set(status.get("proof") or [])
        if not valid:
            resolved.update({"ok": False, "code": "windows_cdp_status_invalid", "summary": "CDP lifecycle status did not return a valid bounded state."})
        else:
            projection = {key: status.get(key) for key in ("schema", "realm", "state", "process", "debugEndpoint", "port", "pageCount", "pages", "recoverable", "cause", "next") if status.get(key) is not None}
            resolved["result"] = projection
            resolved["model_projection"] = projection
            resolved["proof"] = ["client.ack", "windows.browser.cdp.lifecycle.observed"]
            resolved["answer"] = f"The persistent CDP realm is {status['state']}."
    if operation in {"windows_browser_private_cdp_open", "windows_browser_cdp_persistent_open", "windows_browser_cdp_incognito_open"} and resolved.get("ok") is True:
        envelope = resolved.get("result") if isinstance(resolved.get("result"), dict) else {}
        session = envelope.get("rawResult") if isinstance(envelope.get("rawResult"), dict) else envelope
        valid = (
            session.get("schema") == "hermes.wasm_agent.windows_cdp_session.v1"
            and session.get("operation") in {"open_windows_cdp_persistent", "open_windows_cdp_incognito"}
            and session.get("ok") is True
            and isinstance(session.get("port"), int)
            and str(session.get("endpoint") or "") == f"http://127.0.0.1:{session.get('port')}"
            and str(session.get("webSocketDebuggerUrl") or "").startswith(f"ws://127.0.0.1:{session.get('port')}/")
        )
        if not valid:
            resolved.update({
                "ok": False, "code": "windows_private_cdp_postcondition_unverified",
                "summary": "Chrome did not return a verified localhost CDP realm endpoint.",
            })
        else:
            projection = {
                key: session.get(key) for key in (
                    "schema", "sessionId", "processId", "port", "endpoint", "browser",
                    "protocolVersion", "webSocketDebuggerUrl", "realm", "defaultRealm", "profile", "storage", "isolation", "cleanup",
                )
            }
            resolved["result"] = projection
            resolved["model_projection"] = projection
            proof = f"windows.browser.cdp.{'persistent' if projection['realm'] == 'browser_cdp_persistent' else 'incognito'}.ready"
            resolved["proof"] = ["client.ack", proof]
            resolved["answer"] = (
                f"Opened {projection['realm']} at {projection['endpoint']} "
                f"(process {projection['processId']}, session {projection['sessionId']}). "
                + ("Its dedicated profile retains authenticated state." if projection["storage"] == "durable" else "Its temporary profile is removed automatically after Chrome exits.")
            )
    if operation == "windows_browser_cdp_navigate" and resolved.get("ok") is True:
        envelope = resolved.get("result") if isinstance(resolved.get("result"), dict) else {}
        navigation = envelope.get("rawResult") if isinstance(envelope.get("rawResult"), dict) else envelope
        requested_url = str(navigation.get("requestedUrl") or "")
        observed_url = str(navigation.get("observedUrl") or "")
        valid = (
            navigation.get("schema") == "hermes.wasm_agent.windows_cdp_navigation.v1"
            and navigation.get("operation") == "navigate_windows_cdp_persistent"
            and navigation.get("ok") is True
            and _canonical_http_url(requested_url) == _canonical_http_url(arguments.get("url"))
            and observed_url.startswith(("http://", "https://"))
            and bool(str(navigation.get("targetId") or ""))
            and "windows.browser.cdp.navigation.observed" in set(navigation.get("proof") or [])
        )
        if not valid:
            resolved.update({
                "ok": False, "code": "windows_cdp_navigation_postcondition_unverified",
                "summary": "CDP did not independently report the requested navigation target.",
            })
        else:
            projection = {key: navigation.get(key) for key in (
                "schema", "realm", "requestedUrl", "observedUrl", "targetId", "processId", "port",
            )}
            resolved["result"] = projection
            resolved["model_projection"] = projection
            resolved["proof"] = ["client.ack", "windows.browser.cdp.navigation.observed"]
            resolved["answer"] = f"Navigated the persistent CDP browser to {observed_url} and observed the resulting target."
    if operation == "windows_browser_cdp_inspect" and resolved.get("ok") is True:
        envelope = resolved.get("result") if isinstance(resolved.get("result"), dict) else {}
        inspection = envelope.get("rawResult") if isinstance(envelope.get("rawResult"), dict) else envelope
        controls = inspection.get("controls") if isinstance(inspection.get("controls"), list) else []
        editable_targets = inspection.get("editableTargets") if isinstance(inspection.get("editableTargets"), list) else []
        matches = inspection.get("matches") if isinstance(inspection.get("matches"), list) else []
        selector_matches = inspection.get("selectorMatches") if isinstance(inspection.get("selectorMatches"), list) else []
        valid = (
            inspection.get("schema") == "hermes.wasm_agent.windows_cdp_inspection.v1"
            and inspection.get("operation") == "inspect_windows_cdp_persistent"
            and inspection.get("ok") is True
            and bool(str(inspection.get("targetId") or ""))
            and "windows.browser.cdp.dom.snapshot" in set(inspection.get("proof") or [])
        )
        if not valid:
            resolved.update({"ok": False, "code": "windows_cdp_inspection_invalid", "summary": "CDP did not return a valid bounded semantic DOM snapshot."})
        else:
            projection = {
                "schema": inspection["schema"], "targetId": inspection.get("targetId"),
                "url": inspection.get("url"), "title": inspection.get("title"),
                "controls": [item for item in controls[:200] if isinstance(item, dict)],
                "editableTargets": [item for item in editable_targets[:16] if isinstance(item, dict)],
                "matches": [projected for item in matches[:12] if (projected := _cdp_action_match_projection(item)) is not None],
                "selectorMatches": [item for item in selector_matches[:12] if isinstance(item, dict)],
                "text": str(inspection.get("text") or "")[:12000],
            }
            resolved["result"] = projection
            resolved["model_projection"] = projection
            resolved["proof"] = ["client.ack", "windows.browser.cdp.dom.snapshot"]
            resolved["answer"] = f"Inspected {projection.get('title') or projection.get('url') or 'the CDP page'} and found {len(projection['controls'])} bounded controls."
    if operation == "windows_browser_cdp_runtime_inspect" and resolved.get("ok") is True:
        envelope = resolved.get("result") if isinstance(resolved.get("result"), dict) else {}
        snapshot = envelope.get("rawResult") if isinstance(envelope.get("rawResult"), dict) else envelope
        valid = (
            snapshot.get("schema") == "hermes.wasm_agent.windows_cdp_runtime_inspection.v1"
            and snapshot.get("operation") == "inspect_windows_cdp_runtime"
            and snapshot.get("ok") is True and snapshot.get("read_only") is True
            and snapshot.get("getter_invocations") == 0
            and "windows.browser.cdp.runtime.snapshot" in set(snapshot.get("proof") or [])
        )
        if not valid:
            resolved.update({"ok": False, "code": "windows_cdp_runtime_inspection_invalid", "summary": "CDP runtime inspection did not return a valid getter-safe bounded snapshot."})
        else:
            detail = {key: snapshot.get(key) for key in ("schema", "targetId", "revision", "handle", "read_only", "document", "selection", "ancestors", "prototypes", "globals", "budgets", "getter_invocations")}
            model_projection = {
                key: detail.get(key) for key in (
                    "schema", "targetId", "revision", "handle", "read_only",
                    "document", "selection", "budgets", "getter_invocations",
                )
            }
            model_projection["ancestors"] = [
                {key: item.get(key) for key in ("depth", "tag", "path", "attributes")}
                for item in (snapshot.get("ancestors") or [])[:8] if isinstance(item, dict)
            ]
            model_projection["prototypes"] = [
                {
                    "name": item.get("name"),
                    "properties": [str(prop.get("name") or "") for prop in (item.get("properties") or [])[:24] if isinstance(prop, dict)],
                }
                for item in (snapshot.get("prototypes") or [])[:6] if isinstance(item, dict)
            ]
            model_projection["globals"] = [
                str(item.get("name") or "") for item in (snapshot.get("globals") or [])[:40] if isinstance(item, dict)
            ]
            resolved["result"] = detail
            resolved["model_projection"] = model_projection
            resolved["proof"] = ["client.ack", "windows.browser.cdp.runtime.snapshot"]
            selection = snapshot.get("selection") if isinstance(snapshot.get("selection"), dict) else {}
            finding = "was found" if selection.get("found") is True else "was not found"
            locator = str(selection.get("locator") or "the requested locator")[:240]
            resolved["answer"] = (
                f"The requested runtime locator {locator} {finding}. "
                f"targetId {snapshot.get('targetId')}; revision {snapshot.get('revision')}. "
                "The inspection was read-only with zero getter invocations."
            )
    if operation == "windows_browser_cdp_procedure" and resolved.get("ok") is not True:
        envelope = resolved.get("result") if isinstance(resolved.get("result"), dict) else {}
        procedure = envelope.get("rawResult") if isinstance(envelope.get("rawResult"), dict) else envelope
        projection = {
            "schema": procedure.get("schema"), "action": procedure.get("action") or {},
            "observation": procedure.get("observation") or {},
            "completion_proof": procedure.get("completion_proof") or {},
            "failureClassification": procedure.get("failureClassification") or resolved.get("cause") or resolved.get("code"),
            "recovery": resolved.get("recovery") or {},
        }
        resolved["result"] = projection
        resolved["model_projection"] = projection
    if operation == "windows_browser_cdp_procedure" and resolved.get("ok") is True:
        envelope = resolved.get("result") if isinstance(resolved.get("result"), dict) else {}
        procedure = envelope.get("rawResult") if isinstance(envelope.get("rawResult"), dict) else envelope
        action = procedure.get("action") if isinstance(procedure.get("action"), dict) else {}
        observation = procedure.get("observation") if isinstance(procedure.get("observation"), dict) else {}
        completion = procedure.get("completion_proof") if isinstance(procedure.get("completion_proof"), dict) else {}
        assertions = completion.get("assertions") if isinstance(completion.get("assertions"), list) else []
        valid = (
            procedure.get("schema") == "hermes.wasm_agent.windows_cdp_procedure.v1"
            and procedure.get("operation") == "execute_windows_cdp_procedure"
            and procedure.get("ok") is True and action.get("dispatched") is True
            and completion.get("ok") is True and bool(assertions)
            and all(isinstance(item, dict) and item.get("passed") is True for item in assertions)
            and "windows.browser.cdp.procedure.completed" in set(procedure.get("proof") or [])
        )
        projection = {"schema": procedure.get("schema"), "action": action, "observation": observation, "completion_proof": completion}
        resolved["result"] = projection
        resolved["model_projection"] = projection
        if not valid:
            resolved.update({"ok": False, "code": "windows_cdp_procedure_unverified", "summary": "The browser procedure did not independently satisfy every scoped completion assertion."})
        else:
            resolved["proof"] = ["client.ack", "windows.browser.cdp.procedure.completed"]
            resolved["answer"] = f"Completed the browser procedure and verified {len(assertions)} scoped postconditions."
    if operation == "windows_browser_cdp_act" and resolved.get("ok") is True:
        envelope = resolved.get("result") if isinstance(resolved.get("result"), dict) else {}
        action = envelope.get("rawResult") if isinstance(envelope.get("rawResult"), dict) else envelope
        projection = {key: action.get(key) for key in (
            "schema", "targetId", "action", "stepCount", "changed", "observed",
            "postcondition", "postconditionVerified", "failureClassification",
            "failedStepIndex", "failedAction", "failedLocator", "recovery",
        ) if action.get(key) is not None}
        valid = (
            action.get("schema") == "hermes.wasm_agent.windows_cdp_action.v1"
            and action.get("operation") == "act_windows_cdp_persistent"
            and action.get("ok") is True
            and action.get("postconditionVerified") is True
            and "windows.browser.cdp.action.observed" in set(action.get("proof") or [])
        )
        if not valid:
            resolved.update({
                "ok": False, "code": "windows_cdp_action_unverified",
                "summary": "CDP did not independently verify a new requested browser postcondition.",
                "result": projection, "model_projection": projection,
            })
        else:
            resolved["result"] = projection
            resolved["model_projection"] = projection
            resolved["proof"] = ["client.ack", "windows.browser.cdp.action.observed"]
            resolved["answer"] = f"Completed the CDP {action.get('action')} action and verified its postcondition."
    if operation == "space_open" and resolved.get("ok") is True:
        observed = resolved.get("result") if isinstance(resolved.get("result"), dict) else {}
        space_name = str(observed.get("space_name") or arguments.get("space") or "the requested").strip()[:160]
        resolved["proof"] = list(dict.fromkeys(["client.ack", *(resolved.get("proof") or [])]))
        if observed.get("opened") is True and (observed.get("space_id") or observed.get("space_name")):
            resolved["proof"] = list(dict.fromkeys([*resolved.get("proof", []), "client.space.active"]))
        resolved["answer"] = f"Opened the {space_name} space."
    if operation == "run_notepad_uia_canary" and resolved.get("ok") is True:
        observed = resolved.get("result") if isinstance(resolved.get("result"), dict) else {}
        expected = str(arguments.get("canary") or "")
        if observed.get("independently_verified") is not True or observed.get("observed") != expected:
            resolved.update({
                "ok": False, "code": "notepad_uia_postcondition_unverified",
                "summary": "The Notepad action completed without an independent matching UI Automation postimage.",
            })
        else:
            resolved["proof"] = list(dict.fromkeys(["client.ack", *(resolved.get("proof") or []), "client.windows.uia.postimage"]))
    if operation in {"windows_desktop_act", "windows_desktop_prove"} and resolved.get("ok") is True:
        observed = resolved.get("result") if isinstance(resolved.get("result"), dict) else {}
        if arguments.get("expect") is not None and observed.get("independently_verified") is not True:
            resolved.update({
                "ok": False, "code": "windows_desktop_postcondition_unverified",
                "summary": "The Windows desktop operation returned without independently observing its declared postcondition.",
            })
        elif observed.get("independently_verified") is True:
            resolved["proof"] = list(dict.fromkeys(["client.ack", *(resolved.get("proof") or []), "client.windows.uia.postcondition"]))
    return resolved
