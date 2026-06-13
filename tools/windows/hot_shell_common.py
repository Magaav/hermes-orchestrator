#!/usr/bin/env python3
"""Shared helpers for local Windows hot-shell proof scripts."""

from __future__ import annotations

import json
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
    "bridge_update_required": "Rebuild and reinstall the Windows shell so it advertises protocol v2 and hot ops protocol v1.",
    "hot_ops_protocol_missing": "Rebuild and reinstall the Windows shell with hot-operation protocol support.",
    "hot_operation_missing": "Set WASM_AGENT_BRIDGE_OPS_DIR or stage the missing hot operation into the active root.",
    "hot_operation_failed": "Inspect the hot operation result and logsTail for the operation-specific failure.",
    "shell_self_test_failed": "Fix the first failed shell self-test check before running Hermes proof.",
    "adb_missing": "Install Android platform-tools and ensure adb is visible to the Windows app.",
    "android_device_missing": "Connect one authorized Android device and accept the adb prompt.",
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
