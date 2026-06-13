#!/usr/bin/env python3
"""Queue and wait for a Windows-bridge real-device Hermes wake proof."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows"))
from hot_shell_common import artifact_paths, next_action, run_id  # noqa: E402


DEFAULT_ORIGIN = "http://127.0.0.1:8877"
DEFAULT_STATE_DIR = "/local/plugins/wasm-agent/state"
DEFAULT_ENV_FILES = (
    "/local/plugins/wasm-agent/conf/wa.env",
    "/local/conf/wa.env",
)
NEW_OPERATION = "run_android_hermes_wake_proof"
COMPAT_OPERATION = "debug_android_voice_tuning_runtime"
HOT_OPERATION = "run_hot_operation"
LIST_HOT_OPERATIONS = "list_hot_operations"
HOT_OP_PROTOCOL = 1
HOT_MODULE = "android/hermes-wake-proof.js"
HOT_MANIFEST = "android/hermes-wake-proof.manifest.json"
RUNNER_VERSION = "20260612"


def stable_classification(value: str) -> str:
    mapped = {
        "": "unknown_failure",
        "stable": "pass",
        "passed": "pass",
        "ok": "pass",
        "missing_bridge": "bridge_unreachable",
        "failed": "unknown_failure",
        "unstable": "unknown_failure",
        "service_alive": "audio_capture_not_started",
        "audio_capture_alive": "audio_capture_not_started",
        "onnx_model_ready": "onnx_model_not_ready",
        "inference_running": "inference_not_running",
        "wake_confidence_observed": "wake_confidence_missing",
        "wake_threshold_crossed": "wake_threshold_not_crossed",
        "wake_event_emitted": "wake_event_not_emitted",
        "command_capture_ui_started": "command_capture_ui_not_started",
        "no_authorized_devices": "android_device_missing",
        "missing_authorized_device": "android_device_missing",
    }
    return mapped.get(str(value or "").strip(), str(value or "unknown_failure").strip())


def result_classification(record: dict[str, Any]) -> str:
    payload = result_payload(record)
    value = (
        payload.get("failureClassification")
        or payload.get("failure_classification")
        or payload.get("error")
        or payload.get("status")
        or record.get("status")
    )
    if bridge_result_ok(record):
        return stable_classification(value or "pass")
    return stable_classification(value or "unknown_failure")


def adb_available() -> bool:
    try:
        return subprocess.run(["adb", "version"], text=True, capture_output=True, timeout=5, check=False).returncode == 0
    except Exception:
        return False


def android_app_present() -> bool | None:
    try:
        devices = subprocess.run(["adb", "devices"], text=True, capture_output=True, timeout=5, check=False)
        serial = ""
        for line in devices.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serial = parts[0]
                break
        if not serial:
            return None
        package = subprocess.run(["adb", "-s", serial, "shell", "pm", "path", "com.colmeio.wasmagent"], text=True, capture_output=True, timeout=8, check=False)
        return package.returncode == 0 and "package:" in package.stdout
    except Exception:
        return None


def iso_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    candidate = Path(path)
    if not candidate.exists():
        return values
    for line in candidate.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def default_env_values(paths: tuple[str, ...] = DEFAULT_ENV_FILES) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in paths:
        values.update(read_env_file(path))
    return values


def is_local_origin(origin: str) -> bool:
    return origin.startswith("http://127.0.0.1") or origin.startswith("http://localhost")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def request_json(method: str, url: str, *, key: str = "", body: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if key:
        headers["X-Wasm-Agent-Native-Control-Key"] = key
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.URLError as error:
        raise RuntimeError(f"{method} {url} failed: {error}") from error
    return json.loads(raw.decode("utf-8"))


def state_dir_from_env(env: dict[str, str]) -> Path:
    return Path(env.get("HERMES_WASM_AGENT_STATE_DIR") or DEFAULT_STATE_DIR)


def native_control_dir(state_dir: Path) -> Path:
    return state_dir / "native-control"


def latest_heartbeat_device(state_dir: Path, explicit: str = "") -> str:
    if explicit:
        return explicit
    heartbeats = []
    for path in (native_control_dir(state_dir) / "heartbeats").glob("*.json"):
        payload = read_json(path)
        device_id = str(payload.get("device_id") or path.stem)
        route = str(payload.get("route") or "")
        build_id = str(payload.get("build_id") or "")
        score = path.stat().st_mtime
        if "native=electron" in route or build_id.startswith("win-"):
            score += 10_000_000_000
        if device_id.startswith("win-"):
            score += 1_000_000_000
        heartbeats.append((score, device_id, path, payload))
    if not heartbeats:
        raise SystemExit("No local native-control heartbeat found. Start the installed Windows wasm-agent app.")
    heartbeats.sort(key=lambda item: item[0], reverse=True)
    return heartbeats[0][1]


def choose_remote_device(origin: str, key: str, explicit: str = "") -> str:
    if explicit:
        return explicit
    clients = request_json("GET", f"{origin}/native/control/clients", key=key)
    candidates = []
    for client in clients.get("clients", []):
        heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
        device_id = str(client.get("device_id") or heartbeat.get("device_id") or "")
        runtime = str(heartbeat.get("runtime") or heartbeat.get("native_runtime") or "").lower()
        route = str(heartbeat.get("route") or "")
        if not device_id:
            continue
        score = 0
        if "electron" in runtime or "native=electron" in route:
            score += 10
        if device_id.startswith("win-"):
            score += 3
        candidates.append((score, device_id))
    if not candidates:
        raise SystemExit("No native bridge clients are polling. Start the installed Windows wasm-agent app.")
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def heartbeat_payload(state_dir: Path, device_id: str) -> dict[str, Any]:
    heartbeat = read_json(native_control_dir(state_dir) / "heartbeats" / f"{device_id}.json")
    return heartbeat


def hot_ops_summary_from_heartbeat(heartbeat: dict[str, Any]) -> dict[str, Any]:
    hot = heartbeat.get("hotOperations") if isinstance(heartbeat.get("hotOperations"), dict) else {}
    protocol = int(hot.get("supportedHotOpsProtocol") or hot.get("protocol") or hot.get("supported_hot_ops_protocol") or 0)
    available = hot.get("availableHotOps") if isinstance(hot.get("availableHotOps"), list) else []
    return {
        "supported": hot.get("supported") is True or "run_hot_operation" in json.dumps(heartbeat, sort_keys=True),
        "has_list_hot_operations": "list_hot_operations" in json.dumps(heartbeat, sort_keys=True) or bool(available),
        "protocol": protocol,
        "mode": str(hot.get("hotOpsMode") or heartbeat.get("hotOpsMode") or ""),
        "root": str(hot.get("hotOpsRoot") or heartbeat.get("hotOpsRoot") or ""),
        "available": available,
        "raw": hot,
    }


def bridge_supports_hot_operation(state_dir: Path, device_id: str) -> bool:
    heartbeat = heartbeat_payload(state_dir, device_id)
    summary = hot_ops_summary_from_heartbeat(heartbeat)
    return bool(summary["supported"])


def classify_bridge_discovery(state_dir: Path, device_id: str) -> dict[str, Any]:
    summary = hot_ops_summary_from_heartbeat(heartbeat_payload(state_dir, device_id))
    if not summary["supported"]:
        return {"ok": False, "classification": "bridge_update_required", "summary": summary, "message": "local bridge lacks run_hot_operation"}
    if not summary["has_list_hot_operations"]:
        return {"ok": False, "classification": "bridge_update_required", "summary": summary, "message": "local bridge lacks list_hot_operations"}
    if summary["protocol"] < HOT_OP_PROTOCOL:
        return {"ok": False, "classification": "bridge_update_required", "summary": summary, "message": "hot-op protocol is missing or too old"}
    if summary["available"] and not any(item.get("name") == NEW_OPERATION for item in summary["available"] if isinstance(item, dict)):
        return {"ok": False, "classification": "hot_operation_missing", "summary": summary, "message": f"{NEW_OPERATION} is not visible to the installed bridge"}
    return {"ok": True, "classification": "", "summary": summary}


def print_hot_ops_discovery(discovery: dict[str, Any]) -> None:
    summary = discovery.get("summary") if isinstance(discovery.get("summary"), dict) else {}
    print(json.dumps({
        "hot_ops": {
            "ok": discovery.get("ok"),
            "classification": discovery.get("classification", ""),
            "mode": summary.get("mode", ""),
            "root": summary.get("root", ""),
            "protocol": summary.get("protocol", 0),
            "available": [item.get("name") for item in summary.get("available", []) if isinstance(item, dict)],
        }
    }, indent=2))


def stage_dev_hot_ops() -> str:
    override = os.getenv("WASM_AGENT_BRIDGE_OPS_DIR", "").strip()
    if override:
        return override
    repo_op = Path("native/windows/ops") / HOT_MODULE
    repo_manifest = Path("native/windows/ops") / HOT_MANIFEST
    if not repo_op.exists() or not repo_manifest.exists():
        return ""
    appdata = os.getenv("APPDATA")
    if not appdata:
        return ""
    target = Path(appdata) / "WASM-Agent" / "bridge-ops" / HOT_MODULE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(repo_op.read_text(encoding="utf-8"), encoding="utf-8")
    manifest_target = Path(appdata) / "WASM-Agent" / "bridge-ops" / HOT_MANIFEST
    manifest_target.parent.mkdir(parents=True, exist_ok=True)
    manifest_target.write_text(repo_manifest.read_text(encoding="utf-8"), encoding="utf-8")
    return str(target.parent.parent)


def command_payload(operation: str, wait_ms: int) -> dict[str, Any]:
    if operation == HOT_OPERATION:
        return {
            "operationName": NEW_OPERATION,
            "timeoutMs": wait_ms + 45000,
            "args": {
                "waitForSpeech": True,
                "timeoutMs": wait_ms,
            },
        }
    payload = {
        "packageName": "com.colmeio.wasmagent",
        "waitMs": wait_ms,
    }
    if operation == COMPAT_OPERATION:
        payload.update({
            "clearData": False,
            "clearWebViewData": False,
            "debugScreen": "hermes-wake-proof",
            "nativeScreen": "hermes-wake-proof",
            "componentName": "com.colmeio.wasmagent/.MainActivity",
        })
    return payload


def queue_local(state_dir: Path, device_id: str, operation: str, wait_ms: int, reason: str) -> tuple[str, Path]:
    command_id = f"cmd-hermes-wake-proof-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    record = {
        "ok": True,
        "schema": "hermes.wasm_agent.native_control_command.v1",
        "id": command_id,
        "device_id": device_id,
        "type": operation,
        "payload": command_payload(operation, wait_ms),
        "status": "pending",
        "created_at": iso_timestamp(),
        "created_by": "localhost-direct",
        "reason": reason,
    }
    path = native_control_dir(state_dir) / "commands" / device_id / f"{command_id}.json"
    write_json(path, record)
    return command_id, path


def queue_remote(origin: str, key: str, device_id: str, operation: str, wait_ms: int, reason: str) -> tuple[str, dict[str, Any]]:
    queued = request_json(
        "POST",
        f"{origin}/native/frontier/command",
        key=key,
        body={
            "command": operation,
            "device_id": device_id,
            "reason": reason,
            "payload": command_payload(operation, wait_ms),
        },
    )
    for item in queued.get("queued", []):
        command_id = str(item.get("id") or "")
        if command_id:
            return command_id, queued
    raise SystemExit(f"Command did not return a queued id: {json.dumps(queued, indent=2)}")


def local_result_path(state_dir: Path, device_id: str, command_id: str) -> Path:
    return native_control_dir(state_dir) / "results" / device_id / f"{command_id}.json"


def read_local_result(state_dir: Path, device_id: str, command_id: str) -> dict[str, Any]:
    exact = read_json(local_result_path(state_dir, device_id, command_id))
    if exact:
        return exact
    folded = read_json(local_result_path(state_dir, device_id, command_id.lower()))
    if folded:
        return folded
    result_dir = native_control_dir(state_dir) / "results" / device_id
    for path in result_dir.glob("*.json"):
        payload = read_json(path)
        if str(payload.get("command_id") or "").lower() == command_id.lower():
            return payload
    return {}


def read_remote_result(origin: str, key: str, device_id: str, command_id: str) -> dict[str, Any]:
    # The backend exposes result files in Frontier bundles, but local state is the
    # canonical fast path for this workspace. Keep remote waiting tolerant.
    try:
        clients = request_json("GET", f"{origin}/native/frontier/status?device_id={device_id}", key=key, timeout=15)
        latest = clients.get("native_control", {}).get("latest_result", {})
        if latest.get("command_id") == command_id:
            return latest
    except Exception:
        return {}
    return {}


def result_payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("result") if isinstance(record.get("result"), dict) else {}
    return payload


def unsupported_result(record: dict[str, Any]) -> bool:
    payload = result_payload(record)
    text = json.dumps(record, sort_keys=True).lower()
    return (
        payload.get("error") == "operation_not_implemented"
        or payload.get("error") == "operation_not_allowed"
        or str(payload.get("error") or "").startswith("unsupported_command:")
        or "operation_not_implemented" in text
        or "unsupported_command:" in text
        or "local_diagnostics_command_refused" in text
    )


def bridge_result_ok(record: dict[str, Any]) -> bool:
    payload = result_payload(record)
    if payload:
        classification = payload.get("classification") if isinstance(payload.get("classification"), dict) else {}
        if classification and classification.get("stable") is False:
            return False
        if payload.get("classification", {}).get("ok") is False:
            return False
        return payload.get("ok") is not False and not payload.get("error")
    return record.get("ok") is True


def wait_for_result(
    *,
    local: bool,
    state_dir: Path,
    origin: str,
    key: str,
    device_id: str,
    command_id: str,
    wait_sec: int,
    poll_sec: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(1, wait_sec)
    while time.monotonic() < deadline:
        if local:
            record = read_local_result(state_dir, device_id, command_id)
        else:
            record = read_remote_result(origin, key, device_id, command_id)
        if record:
            return record
        time.sleep(max(1.0, poll_sec))
    raise SystemExit(f"Timed out waiting for Windows bridge result for {command_id}.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default=os.getenv("WASM_AGENT_ORIGIN", DEFAULT_ORIGIN))
    parser.add_argument("--control-key", default=os.getenv("WASM_AGENT_NATIVE_CONTROL_KEY", ""))
    parser.add_argument("--env-file", default=os.getenv("WASM_AGENT_ENV_FILE", ""))
    parser.add_argument("--device-id", default=os.getenv("WASM_AGENT_NATIVE_DEVICE_ID", ""))
    parser.add_argument("--wait-ms", type=int, default=int(os.getenv("HERMES_WAKE_PROOF_WAIT_MS", "30000")))
    parser.add_argument("--wait-sec", type=int, default=int(os.getenv("HERMES_WAKE_PROOF_RESULT_WAIT_SEC", "150")))
    parser.add_argument("--poll-sec", type=float, default=float(os.getenv("HERMES_WAKE_PROOF_POLL_SEC", "5")))
    parser.add_argument("--operation", choices=("auto", HOT_OPERATION, NEW_OPERATION, COMPAT_OPERATION), default="auto")
    parser.add_argument("--allow-stale-command-fallback", action="store_true", help="Allow old command-specific bridge operations when run_hot_operation is missing.")
    parser.add_argument("--proof", action="store_true", help="Strict proof mode: minimal artifacts, fail fast.")
    parser.add_argument("--debug", action="store_true", help="Debug mode: collect richer diagnostics and continue past non-bridge preflight failures.")
    parser.add_argument("--dry-run", action="store_true", help="Validate shell/hot-op/ADB/app presence without launching screens or mutating device state.")
    parser.add_argument("--out", default=os.getenv("HERMES_WAKE_PROOF_OUT", "reports/sim/android/latest/hermes-wake-proof-result.json"))
    args = parser.parse_args()
    rid = run_id()
    artifacts = artifact_paths("sim/android", rid)
    mode = "dry-run" if args.dry_run else "debug" if args.debug else "proof" if args.proof else "default"
    failed_stage = ""
    failure_classification = "unknown_failure"

    env = read_env_file(args.env_file) if args.env_file else default_env_values()
    origin = (args.origin or env.get("WASM_AGENT_ORIGIN") or DEFAULT_ORIGIN).rstrip("/")
    local = is_local_origin(origin)
    state_dir = state_dir_from_env(env)
    key = args.control_key or env.get("WASM_AGENT_NATIVE_CONTROL_KEY", "")
    if not local and not key:
        raise SystemExit("Cloud proof requires WASM_AGENT_NATIVE_CONTROL_KEY, --control-key, or a key in wa.env. Use --origin http://127.0.0.1:8877 for local bridge state.")

    device_id = latest_heartbeat_device(state_dir, args.device_id) if local else choose_remote_device(origin, key, args.device_id)
    if local:
        stage_dev_hot_ops()
        discovery = classify_bridge_discovery(state_dir, device_id)
        print_hot_ops_discovery(discovery)
        if not discovery["ok"]:
            failed_stage = "hot_ops_discovery"
            failure_classification = stable_classification(discovery["classification"])
            if args.debug and failure_classification != "bridge_unreachable":
                pass
            else:
                last_record = {
                    "ok": False,
                    "result": {
                        "ok": False,
                        "status": failure_classification,
                        "error": failure_classification,
                        "message": discovery.get("message", ""),
                        "hotOps": discovery.get("summary", {}),
                        "failureClassification": failure_classification,
                        "nextAction": next_action(failure_classification),
                    },
                }
                output = {
                    "ok": False,
                    "schema": "hermes.wasm_agent.android_hermes_wake_proof_runner.v1",
                    "runId": rid,
                    "runnerVersion": RUNNER_VERSION,
                    "mode": mode,
                    "origin": origin,
                    "device_id": device_id,
                    "queued": [],
                    "result": last_record,
                    "failedStage": failed_stage,
                    "failureClassification": failure_classification,
                    "nextAction": next_action(failure_classification),
                    "artifacts": {"result": str(Path(args.out)), "logs": artifacts["logs"]},
                }
                out = Path(args.out)
                write_json(out, output)
                write_json(Path(artifacts["runResult"]), output)
                Path(artifacts["logs"]).write_text(json.dumps(discovery, indent=2) + "\n", encoding="utf-8")
                print(json.dumps({"ok": False, "out": str(out), "classification": failure_classification, "failedStage": failed_stage, "nextAction": output["nextAction"], "resultJson": str(out)}, indent=2))
                return 1
        if args.dry_run:
            summary = discovery.get("summary", {}) if isinstance(discovery.get("summary"), dict) else {}
            adb_ok = adb_available()
            app_present = android_app_present()
            app_status = "unknown" if app_present is None else "present" if app_present else "missing"
            if not discovery["ok"]:
                failure_classification = stable_classification(discovery["classification"])
                failed_stage = "hot_ops_discovery"
            elif not adb_ok:
                failure_classification = "adb_missing"
                failed_stage = "adb"
            elif app_present is False:
                failure_classification = "android_app_missing"
                failed_stage = "android_app"
            else:
                failure_classification = "pass"
                failed_stage = ""
            output = {
                "ok": failure_classification == "pass",
                "schema": "hermes.wasm_agent.android_hermes_wake_proof_runner.v1",
                "runId": rid,
                "runnerVersion": RUNNER_VERSION,
                "mode": mode,
                "origin": origin,
                "device_id": device_id,
                "queued": [],
                "dryRun": {
                    "hotOpsDiscovery": discovery,
                    "manifestVisible": any(item.get("name") == NEW_OPERATION for item in summary.get("available", []) if isinstance(item, dict)),
                    "adbAvailable": adb_ok,
                    "androidApp": app_status,
                },
                "failedStage": failed_stage,
                "failureClassification": None if failure_classification == "pass" else failure_classification,
                "nextAction": next_action(failure_classification),
                "artifacts": {"result": str(Path(args.out)), "logs": artifacts["logs"]},
            }
            out = Path(args.out)
            write_json(out, output)
            write_json(Path(artifacts["runResult"]), output)
            Path(artifacts["logs"]).write_text(json.dumps(output["dryRun"], indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"ok": output["ok"], "classification": failure_classification, "failedStage": failed_stage, "nextAction": output["nextAction"], "resultJson": str(out)}, indent=2))
            return 0 if output["ok"] else 1
    if args.operation == "auto":
        operations = [HOT_OPERATION, COMPAT_OPERATION] if args.allow_stale_command_fallback else [HOT_OPERATION]
    else:
        operations = [args.operation]
    last_record: dict[str, Any] = {}
    queued_details: list[dict[str, Any]] = []
    reason = "Real-device Hermes wake proof: launch Android proof mode, speak Hermes, classify eight acceptance stages."

    for operation in operations:
        if local:
            command_id, path = queue_local(state_dir, device_id, operation, args.wait_ms, reason)
            if operation == HOT_OPERATION and args.debug:
                command = read_json(path)
                payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
                payload.setdefault("args", {})
                payload["args"]["debug"] = True
                payload["runId"] = rid
                command["payload"] = payload
                write_json(path, command)
            queued_details.append({"operation": operation, "command_id": command_id, "path": str(path)})
        else:
            command_id, queued = queue_remote(origin, key, device_id, operation, args.wait_ms, reason)
            queued_details.append({"operation": operation, "command_id": command_id, "queued": queued})
        print(json.dumps({"queued": queued_details[-1], "prompt": "Speak Hermes near the connected Android device now."}, indent=2))
        record = wait_for_result(
            local=local,
            state_dir=state_dir,
            origin=origin,
            key=key,
            device_id=device_id,
            command_id=command_id,
            wait_sec=args.wait_sec,
            poll_sec=args.poll_sec,
        )
        last_record = record
        if operation != HOT_OPERATION or not unsupported_result(record):
            break
        if not args.allow_stale_command_fallback:
            last_record = {
                "ok": False,
                "result": {
                    "ok": False,
                    "status": "bridge_update_required",
                    "error": "bridge_update_required",
                    "message": "Installed Windows bridge does not support run_hot_operation.",
                    "failureClassification": "bridge_update_required",
                    "nextAction": next_action("bridge_update_required"),
                },
            }
            break
        print(json.dumps({"fallback": COMPAT_OPERATION, "reason": "installed bridge does not support run_hot_operation yet"}, indent=2))

    ok = bridge_result_ok(last_record)
    failure_classification = result_classification(last_record)
    failed_stage = "" if ok else "hermes_wake_proof"
    output = {
        "ok": ok,
        "schema": "hermes.wasm_agent.android_hermes_wake_proof_runner.v1",
        "runId": rid,
        "runnerVersion": RUNNER_VERSION,
        "origin": origin,
        "mode": mode,
        "transport": "local-state" if local else "remote-frontier",
        "device_id": device_id,
        "queued": queued_details,
        "result": last_record,
        "failedStage": failed_stage,
        "failureClassification": None if ok else failure_classification,
        "nextAction": next_action(failure_classification),
        "artifacts": {"result": str(Path(args.out)), "logs": artifacts["logs"]},
    }
    out = Path(args.out)
    write_json(out, output)
    write_json(Path(artifacts["runResult"]), output)
    Path(artifacts["logs"]).write_text(json.dumps({"queued": queued_details, "result": last_record}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": output["ok"], "out": str(out), "classification": failure_classification, "failedStage": failed_stage, "nextAction": output["nextAction"], "resultJson": str(out)}, indent=2))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
