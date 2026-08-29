"""Persist native-control results with bounded receipt telemetry."""

from __future__ import annotations

import json
from typing import Any, Callable


BUDGET_SCHEMA = "hermes.wasm_agent.native_control_receipt_budget.v1"
DEFAULT_BUDGET_BYTES = 64 * 1024
DETAIL_BUDGET_BYTES = 256 * 1024
COMMAND_BUDGET_BYTES = {
    "get_bridge_status": 8 * 1024,
    "get_native_kernel_status": 4 * 1024,
    "list_hot_operations": 12 * 1024,
    "sync_downloaded_runtime": 4 * 1024,
    "refresh_downloaded_runtime": 4 * 1024,
    "sync_downloaded_hot_ops": 8 * 1024,
    "refresh_downloaded_hot_ops": 8 * 1024,
}


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def receipt_budget(command_type: Any, command_payload: Any, result: Any) -> dict[str, Any]:
    """Return exact compact-JSON bytes and a non-destructive budget verdict."""
    op = str(command_type or "unknown")[:80]
    payload = command_payload if isinstance(command_payload, dict) else {}
    detail_requested = any(bool(payload.get(key)) for key in ("includeDetails", "include_details", "includeLogs", "include_logs"))
    if detail_requested:
        profile = "detail"
        budget_bytes = DETAIL_BUDGET_BYTES
    elif op in COMMAND_BUDGET_BYTES:
        profile = "compact"
        budget_bytes = COMMAND_BUDGET_BYTES[op]
    else:
        profile = "default"
        budget_bytes = DEFAULT_BUDGET_BYTES
    result_bytes = _json_bytes(result)
    within_budget = result_bytes <= budget_bytes
    return {
        "schema": BUDGET_SCHEMA,
        "profile": profile,
        "resultBytes": result_bytes,
        "budgetBytes": budget_bytes,
        "withinBudget": within_budget,
        "overByBytes": max(0, result_bytes - budget_bytes),
        "alert": None if within_budget else "native_control_receipt_budget_exceeded",
    }


def save_result(
    server: Any,
    body: dict[str, Any],
    handler: Any,
    *,
    browser_error: type[Exception],
    device_id_from_value: Callable[[Any], str],
    safe_state_id: Callable[[str, str], str],
    iso_timestamp: Callable[[], str],
    clipped_verbatim: Callable[[str, int], str],
    redact_diagnostics: Callable[[Any], Any],
    control_dir: Callable[[Any], Any],
    write_json_file: Callable[[Any, Any], None],
    resolve_command_path: Callable[[Any, str, str], Any],
    read_json_file: Callable[[Any, Any], Any],
    apply_command_result_surface: Callable[..., Any],
    append_audit: Callable[[Any, dict[str, Any]], None],
) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise browser_error("invalid_native_control_result", "Native control result payload must be an object.")
    device_id = device_id_from_value(body.get("device_id") or handler.headers.get("X-Wasm-Agent-Native-Device-Id"))
    command_id = safe_state_id(str(body.get("command_id") or "unknown"), "unknown")
    now = iso_timestamp()
    command_path = resolve_command_path(server, device_id, command_id)
    command = read_json_file(command_path, {})
    command_type = clipped_verbatim(str(body.get("command_type") or (command.get("type") if isinstance(command, dict) else "") or "unknown"), 80)
    redacted_result = redact_diagnostics(body.get("result") if isinstance(body.get("result"), dict) else body)
    budget = receipt_budget(command_type, command.get("payload") if isinstance(command, dict) else {}, redacted_result)
    record = {
        "ok": True,
        "schema": "hermes.wasm_agent.native_control_result.v1",
        "device_id": device_id,
        "command_id": command_id,
        "received_at": now,
        "remote_addr": clipped_verbatim(str(handler.client_address[0] if handler.client_address else ""), 120),
        "receiptBudget": budget,
        "result": redacted_result,
    }
    write_json_file(control_dir(server) / "results" / device_id / f"{command_id}.json", record)
    observability_hub = getattr(server, "observability_hub", None)
    if isinstance(command, dict) and command:
        command["status"] = "finished"
        command["finished_at"] = now
        command["result"] = redacted_result
        command["receiptBudget"] = budget
        write_json_file(command_path, command)
        apply_command_result_surface(server.state_dir, device_id, command.get("type"), redacted_result, received_at=now)
        if observability_hub is not None:
            observability_hub.record_command(command, status="finished", result=redacted_result)
    elif observability_hub is not None:
        observability_hub.record_command(
            {"id": command_id, "device_id": device_id, "type": command_type, "payload": {}},
            status="finished",
            result=redacted_result,
        )
    if observability_hub is not None:
        observability_hub.record_event(device_id, "native.control", "command_result", {
            "command_id": command_id, "op": command_type, "status": "finished", "receiptBudget": budget, "result": redacted_result,
        })
        if not budget["withinBudget"]:
            observability_hub.record_event(device_id, "native.control", "receipt_budget_exceeded", {
                "command_id": command_id, "op": command_type, **budget,
            })
    append_audit(server, {
        "action": "command_result",
        "device_id": device_id,
        "command_id": command_id,
        "command_type": command_type,
        "result_ok": bool(redacted_result.get("ok")) if isinstance(redacted_result, dict) else None,
        "receipt_budget": budget,
        "result": redacted_result,
        "remote_addr": record["remote_addr"],
    })
    if not budget["withinBudget"]:
        append_audit(server, {
            "action": "receipt_budget_exceeded", "device_id": device_id, "command_id": command_id,
            "command_type": command_type, "receipt_budget": budget,
        })
    return {
        "ok": True, "stored": True, "deviceId": device_id, "commandId": command_id,
        "receivedAt": now, "receiptBudget": budget,
    }
