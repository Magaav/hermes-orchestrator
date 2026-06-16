#!/usr/bin/env python3
"""Shared helpers for local Windows hot-shell proof scripts."""

from __future__ import annotations

import json
import shutil
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_ORIGIN = "http://127.0.0.1:8877"
EXPECTED_HOT_OPS_PROTOCOL = 1
EXPECTED_SHELL_PROTOCOL = 2
CLASSIFICATIONS = {
    "bridge_unreachable": "Start the local wasm-agent backend and installed Windows app.",
    "command_not_polled": "Restart or reopen the installed Windows app; the command was queued but never picked up by native-control polling.",
    "command_polled_not_started": "Inspect the installed app native-control audit; the backend delivered the command but no handler start was observed.",
    "handler_missing": "Install or hot-sync a shell that supports the requested native-control handler.",
    "handler_threw": "Inspect the command result error/logsTail and fix the throwing native-control handler.",
    "handler_timeout": "The native-control watchdog bounded a stuck handler; inspect logsTail, then continue with the next command.",
    "handler_never_resolved": "Restart the installed app to clear the stuck handler, then fix the smallest handler path that never completes.",
    "result_upload_failed": "Inspect installed app network/backend access; the handler completed but result upload failed.",
    "result_uploaded_but_script_parser_missed": "Fix the local proof script result lookup or result schema handling.",
    "result_seen_wrong_shape": "Fix the native-control result envelope so it contains a structured result object.",
    "bridge_update_required": "Rebuild and reinstall the Windows shell so it advertises protocol v2 and hot ops protocol v1.",
    "hot_ops_protocol_missing": "Rebuild and reinstall the Windows shell with hot-operation protocol support.",
    "hot_operation_missing": "Use a registered op or publish/register the missing manifest.",
    "hot_operation_failed": "Inspect the hot operation result and logsTail for the operation-specific failure.",
    "shell_self_test_failed": "Fix the first failed shell self-test check before running Hermes proof.",
    "native_capability_missing": "Install a native shell build that advertises the requested capability kernel method.",
    "runtime_bundle_missing": "Publish or stage the downloaded runtime bundle in the native release feed.",
    "runtime_sha_mismatch": "Regenerate the native release feed and verify the downloaded runtime bundle checksums.",
    "runtime_download_failed": "Check the backend release artifact URL and shell network access.",
    "runtime_manifest_invalid": "Fix the downloaded runtime manifest schema before syncing the shell.",
    "runtime_missing_capability": "The runtime bundle requires a native capability this shell does not advertise.",
    "runtime_bundle_stale": "Open or ping the native shell so it activates the latest downloaded runtime bundle.",
    "downloaded_operation_not_supported": "Keep product logic in the downloaded runtime or add a stable native primitive in the next native build.",
    "last_known_good_missing": "Sync a known-good downloaded runtime before attempting rollback.",
    "runtime_rollback_failed": "Inspect the shell runtime cache and retry after the last-known-good root is readable.",
    "adb_missing": "Install Android platform-tools and ensure adb is visible to the Windows app.",
    "adb_timeout": "ADB device discovery timed out while starting or contacting the daemon; retry after daemon recovery or restart the Windows app.",
    "adb_server_start_failed": "ADB server failed to start. Close other ADB processes, reconnect USB, and retry.",
    "no_device": "Phone not visible to Windows ADB. Check cable, USB mode, driver, and debugging.",
    "unauthorized": "Unlock the phone and accept the USB debugging authorization prompt.",
    "offline": "Reconnect USB, toggle USB debugging, then retry.",
    "multiple_devices": "Disconnect extra Android devices or emulators, then retry with exactly one authorized phone.",
    "one_authorized_device": "Proceed to Hermes proof.",
    "android_device_missing": "Connect exactly one authorized Android device and accept the adb prompt.",
    "android_app_missing": "Install com.colmeio.wasmagent on the authorized Android device.",
    "unknown_failure": "Inspect result artifacts and bridge logs.",
    "pass": "Proceed to the next proof stage.",
}


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_id(prefix: str = "hotop") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cleanup_native_control_state(
    state_dir: Path,
    device_id: str,
    *,
    keep_recent: int = 40,
    reason: str = "proof_recovery",
) -> dict[str, Any]:
    """Archive old finished command/result pairs so stale queue state cannot starve proof commands."""
    root = state_dir / "native-control"
    command_dir = root / "commands" / device_id
    result_dir = root / "results" / device_id
    report: dict[str, Any] = {
        "ok": True,
        "deviceId": device_id,
        "reason": reason,
        "archiveRoot": "",
        "commandsBefore": 0,
        "resultsBefore": 0,
        "commandsArchived": 0,
        "resultsArchived": 0,
        "pendingCommands": 0,
        "deliveredCommands": 0,
        "finishedCommands": 0,
        "keptRecent": keep_recent,
        "staleStateFound": False,
        "notes": [],
    }
    if not command_dir.exists() and not result_dir.exists():
        return report
    command_paths = sorted(command_dir.glob("*.json"), key=lambda item: item.stat().st_mtime) if command_dir.exists() else []
    result_paths = sorted(result_dir.glob("*.json"), key=lambda item: item.stat().st_mtime) if result_dir.exists() else []
    report["commandsBefore"] = len(command_paths)
    report["resultsBefore"] = len(result_paths)
    parsed: list[tuple[Path, dict[str, Any]]] = []
    for path in command_paths:
        command = read_json(path)
        status = str(command.get("status") or "")
        if status == "pending":
            report["pendingCommands"] += 1
        elif status == "delivered":
            report["deliveredCommands"] += 1
        elif status == "finished":
            report["finishedCommands"] += 1
        parsed.append((path, command))
    finished = [(path, command) for path, command in parsed if command.get("status") == "finished" or command.get("finished_at")]
    to_archive = finished[:-max(0, keep_recent)] if keep_recent else finished
    if not to_archive:
        return report
    archive_root = root / "archive" / f"{iso_now().replace(':', '').replace('-', '').replace('Z', 'Z')}-{reason}-{uuid.uuid4().hex[:8]}" / device_id
    archive_commands = archive_root / "commands"
    archive_results = archive_root / "results"
    archive_commands.mkdir(parents=True, exist_ok=True)
    archive_results.mkdir(parents=True, exist_ok=True)
    archived_ids: set[str] = set()
    for path, command in to_archive:
        command_id = path.stem
        if command.get("id"):
            command_id = str(command.get("id"))
        archived_ids.add(command_id.lower())
        shutil.move(str(path), str(archive_commands / path.name))
        report["commandsArchived"] += 1
    for path in result_paths:
        result = read_json(path)
        command_id = str(result.get("command_id") or path.stem).lower()
        if command_id in archived_ids:
            shutil.move(str(path), str(archive_results / path.name))
            report["resultsArchived"] += 1
    report["archiveRoot"] = str(archive_root)
    report["staleStateFound"] = bool(report["commandsArchived"] or report["resultsArchived"])
    if report["pendingCommands"] or report["deliveredCommands"]:
        report["notes"].append("live pending/delivered commands were left untouched")
    if report["staleStateFound"]:
        report["notes"].append("archived old finished command/result files before proof")
    return report


def request_json(method: str, url: str, *, body: dict[str, Any] | None = None, timeout: int = 10) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def safe_request(method: str, url: str, *, body: dict[str, Any] | None = None, timeout: int = 10) -> tuple[dict[str, Any], str]:
    try:
        return request_json(method, url, body=body, timeout=timeout), ""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {}, str(exc)


def choose_windows_client(clients: list[dict[str, Any]]) -> dict[str, Any]:
    scored: list[tuple[int, dict[str, Any]]] = []
    for client in clients:
        heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
        device_id = str(client.get("device_id") or heartbeat.get("device_id") or "")
        haystack = json.dumps(heartbeat, sort_keys=True).lower()
        score = 0
        if device_id.startswith("win-"):
            score += 20
        if "electron" in haystack or "native=electron" in haystack:
            score += 10
        if heartbeat.get("hotOperations") or heartbeat.get("hotOpsProtocolVersion"):
            score += 5
        if device_id:
            scored.append((score, client))
    if not scored:
        return {}
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def result_path(state_dir: Path, device_id: str, command_id: str) -> Path:
    return state_dir / "native-control" / "results" / device_id / f"{command_id}.json"


def command_path(state_dir: Path, device_id: str, command_id: str) -> Path:
    return state_dir / "native-control" / "commands" / device_id / f"{command_id}.json"


def local_command_record(state_dir: Path, device_id: str, command_id: str) -> dict[str, Any]:
    exact = read_json(command_path(state_dir, device_id, command_id))
    if exact:
        return exact
    command_dir = state_dir / "native-control" / "commands" / device_id
    for path in sorted(command_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        payload = read_json(path)
        if str(payload.get("id") or "").lower() == command_id.lower():
            return payload
    return {}


def latest_local_result(state_dir: Path, device_id: str, command_id: str) -> dict[str, Any]:
    exact = read_json(result_path(state_dir, device_id, command_id))
    if exact:
        return exact
    result_dir = state_dir / "native-control" / "results" / device_id
    for path in sorted(result_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        payload = read_json(path)
        if str(payload.get("command_id") or "").lower() == command_id.lower():
            return payload
    return {}


def queue_command(origin: str, device_id: str, command: str, payload: dict[str, Any], rid: str, reason: str) -> tuple[str, dict[str, Any]]:
    body = {
        "device_id": device_id,
        "command": command,
        "command_id": f"{rid}-{command.replace('_', '-')[:32]}",
        "payload": payload,
        "reason": reason,
    }
    queued = request_json("POST", f"{origin.rstrip('/')}/native/control/command", body=body, timeout=10)
    command_id = str((queued.get("command") or {}).get("id") or body["command_id"])
    return command_id, queued


def wait_for_result(state_dir: Path, device_id: str, command_id: str, *, wait_sec: int = 45, poll_sec: float = 1.5) -> dict[str, Any]:
    deadline = time.monotonic() + wait_sec
    while time.monotonic() < deadline:
        found = latest_local_result(state_dir, device_id, command_id)
        if found:
            return found
        time.sleep(max(0.25, poll_sec))
    return {}


def command_timeline(state_dir: Path, device_id: str, command_id: str, record: dict[str, Any] | None = None) -> dict[str, Any]:
    command = local_command_record(state_dir, device_id, command_id)
    result_record = record if isinstance(record, dict) else latest_local_result(state_dir, device_id, command_id)
    result = unwrap_result(result_record) if isinstance(result_record, dict) else {}
    completed_at = (
        command.get("finished_at")
        or result.get("completed_at")
        or result.get("finishedAt")
        or result.get("finished_at")
        or result_record.get("received_at") if isinstance(result_record, dict) else ""
    )
    uploaded_at = (
        result.get("uploaded_at")
        or result.get("uploadedAt")
        or (result_record.get("received_at") if isinstance(result_record, dict) else "")
    )
    return {
        "command_id": command_id,
        "command_type": command.get("type") or result.get("operation") or "",
        "handler": command.get("type") or result.get("operation") or "",
        "queued_at": command.get("created_at") or "",
        "picked_up_at": command.get("delivered_at") or "",
        "started_at": result.get("startedAt") or result.get("started_at") or command.get("started_at") or command.get("delivered_at") or "",
        "completed_at": completed_at or "",
        "uploaded_at": uploaded_at or "",
        "result_seen_at": iso_now() if result_record else "",
        "command_status": command.get("status") or "",
        "result_json_shape": "object" if isinstance(result, dict) and bool(result) else "missing",
    }


def classify_roundtrip(state_dir: Path, device_id: str, command_id: str, record: dict[str, Any] | None = None) -> str:
    command = local_command_record(state_dir, device_id, command_id)
    result_record = record if isinstance(record, dict) else latest_local_result(state_dir, device_id, command_id)
    result = unwrap_result(result_record) if isinstance(result_record, dict) else {}
    if result_record:
        if not isinstance(result, dict) or not result:
            return "result_seen_wrong_shape"
        error = str(result.get("error") or "")
        if error.startswith("unsupported_command:") or error in {"operation_not_implemented", "operation_not_allowed"}:
            return "handler_missing"
        if result.get("failureClassification") == "handler_timeout" or error == "handler_timeout":
            return "handler_timeout"
        if result.get("ok") is False and error:
            return "handler_threw"
        return classify_result(result)
    if not command:
        return "command_not_polled"
    if not command.get("delivered_at"):
        return "command_not_polled"
    deadline_at = str(command.get("deadline_at") or "")
    if deadline_at:
        try:
            deadline = datetime.fromisoformat(deadline_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) >= deadline:
                return "handler_timeout"
        except ValueError:
            pass
    timeout_sec = command.get("timeout_sec")
    if timeout_sec:
        try:
            delivered = datetime.fromisoformat(str(command.get("delivered_at")).replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - delivered).total_seconds() >= float(timeout_sec):
                return "handler_timeout"
        except (TypeError, ValueError):
            pass
    if command.get("finished_at"):
        return "result_uploaded_but_script_parser_missed"
    return "handler_never_resolved"


def unwrap_result(record: dict[str, Any]) -> dict[str, Any]:
    return record.get("result") if isinstance(record.get("result"), dict) else record


def classify_result(result: dict[str, Any]) -> str:
    if not result:
        return "unknown_failure"
    value = result.get("failureClassification") or result.get("failure_classification") or result.get("error") or result.get("status")
    if result.get("ok") is True and not value:
        return "pass"
    if value in {"stable", "passed", "ok"}:
        return "pass"
    return str(value or "unknown_failure")


def next_action(classification: str) -> str:
    return CLASSIFICATIONS.get(classification, CLASSIFICATIONS["unknown_failure"])


def artifact_paths(area: str, rid: str) -> dict[str, str]:
    latest = Path("reports") / area / "latest"
    run_root = Path("reports") / area / "runs" / rid
    latest.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)
    return {
        "latest": str(latest),
        "runRoot": str(run_root),
        "result": str(latest / "result.json"),
        "logs": str(latest / "logs.txt"),
        "runResult": str(run_root / "result.json"),
        "runLogs": str(run_root / "logs.txt"),
    }
