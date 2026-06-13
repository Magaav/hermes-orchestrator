#!/usr/bin/env python3
"""Read-only full-stack doctor for WASM Agent Native proof/debug loops."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows"))

from hot_shell_common import (  # noqa: E402
    DEFAULT_ORIGIN,
    artifact_paths,
    choose_windows_client,
    classify_result,
    next_action,
    queue_command,
    read_json,
    request_json,
    run_id,
    unwrap_result,
    wait_for_result,
    write_json,
)


PACKAGE_NAME = "com.colmeio.wasmagent"


def run_cmd(args: list[str], timeout: int = 8) -> dict[str, Any]:
    try:
        proc = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
        return {"ok": proc.returncode == 0, "exitCode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    except FileNotFoundError:
        return {"ok": False, "error": "not_found", "stdout": "", "stderr": ""}
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "error": "timeout", "stdout": exc.stdout or "", "stderr": exc.stderr or ""}


def adb_serial(devices_output: str) -> str:
    for line in devices_output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            return parts[0]
    return ""


def model_sha_from_reports() -> str:
    candidates = [
        Path("reports/sim/android/latest/hermes-wake-proof-result.json"),
        Path("reports/sim/android/latest/summary.json"),
        Path("reports/doctor/latest/wasm-agent-doctor-result.json"),
    ]
    for path in candidates:
        payload = read_json(path)
        text = json.dumps(payload)
        known = read_json(Path("reports/known-good.json")).get("modelSha")
        if known and known in text:
            return str(known)
    return ""


def latest_voice_wake_source() -> str:
    candidates = [
        Path("reports/sim/android/latest/hermes-wake-proof-result.json"),
        Path("reports/windows/latest/hot-shell-proof-result.json"),
        Path("reports/sim/android/latest/summary.md"),
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default=os.getenv("WASM_AGENT_ORIGIN", DEFAULT_ORIGIN))
    parser.add_argument("--state-dir", default=os.getenv("HERMES_WASM_AGENT_STATE_DIR", "/local/plugins/wasm-agent/state"))
    parser.add_argument("--wait-sec", type=int, default=35)
    parser.add_argument("--fix", action="store_true", help="Allow future mutating repairs. Current checks remain conservative.")
    args = parser.parse_args()

    rid = run_id()
    artifacts = artifact_paths("doctor", rid)
    origin = args.origin.rstrip("/")
    state_dir = Path(args.state_dir)
    logs: list[str] = []
    known_good = read_json(Path("reports/known-good.json"))
    checks: dict[str, Any] = {}
    failure = "pass"

    try:
        clients = request_json("GET", f"{origin}/native/control/clients", timeout=8)
        client = choose_windows_client(clients.get("clients", []) if isinstance(clients.get("clients"), list) else [])
        checks["windowsBridgeAlive"] = bool(client)
        if not client:
            failure = "bridge_unreachable"
            raise RuntimeError("No Windows native client heartbeat found.")
        device_id = str(client.get("device_id") or client.get("heartbeat", {}).get("device_id") or "")
        heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
        checks["shellBuildId"] = heartbeat.get("build_id") or heartbeat.get("buildId") or ""
        checks["shellSha"] = heartbeat.get("build_sha") or heartbeat.get("buildSha") or ""

        for command, payload in [
            ("get_bridge_status", {}),
            ("list_hot_operations", {}),
            ("run_hot_operation", {"operationName": "canary_echo", "dryRun": True, "args": {"dryRun": True}}),
        ]:
            command_id, _queued = queue_command(origin, device_id, command, payload, rid, "WASM Agent doctor read-only check")
            record = wait_for_result(state_dir, device_id, command_id, wait_sec=args.wait_sec)
            result = unwrap_result(record)
            checks[command] = result
            logs.extend(str(item) for item in result.get("logsTail", []) if isinstance(result.get("logsTail"), list))
            if not result:
                failure = "bridge_unreachable"
                raise RuntimeError(f"No result for {command}.")

        status = checks["get_bridge_status"]
        hot_ops = checks["list_hot_operations"]
        canary = checks["run_hot_operation"]
        checks["hotOpsProtocolVersion"] = hot_ops.get("hotOpsProtocolVersion") or hot_ops.get("supportedHotOpsProtocol") or status.get("hotOpsProtocolVersion")
        checks["activeHotOpsRoot"] = hot_ops.get("hotOpsMode") or status.get("hotOperations", {}).get("hotOpsMode") or ""
        checks["canaryHotOpWorks"] = canary.get("ok") is True
        if int(checks["hotOpsProtocolVersion"] or 0) < int(known_good.get("expectedHotOpsProtocol") or 1):
            failure = "hot_ops_protocol_missing"
        elif not checks["canaryHotOpWorks"]:
            failure = classify_result(canary)
    except Exception as exc:
        if failure == "pass":
            failure = "bridge_unreachable"
        logs.append(str(exc))

    adb_version = run_cmd(["adb", "version"], timeout=5)
    adb_devices = run_cmd(["adb", "devices", "-l"], timeout=5) if adb_version["ok"] else {"ok": False, "stdout": ""}
    serial = adb_serial(adb_devices.get("stdout", ""))
    checks["adbAvailable"] = adb_version["ok"]
    checks["authorizedAndroidDeviceConnected"] = bool(serial)
    checks["androidDeviceSerial"] = serial
    if failure == "pass" and not checks["adbAvailable"]:
        failure = "adb_missing"
    elif failure == "pass" and not serial:
        failure = "android_device_missing"

    package = run_cmd(["adb", "-s", serial, "shell", "dumpsys", "package", PACKAGE_NAME], timeout=10) if serial else {"ok": False, "stdout": ""}
    checks["androidAppInstalled"] = PACKAGE_NAME in package.get("stdout", "")
    checks["androidAppBuildId"] = ""
    checks["recordAudioPermission"] = ""
    if serial and checks["androidAppInstalled"]:
        build_info = run_cmd(["adb", "-s", serial, "shell", "run-as", PACKAGE_NAME, "cat", "files/native-diagnostics/build-info.json"], timeout=8)
        try:
            build_payload = json.loads(build_info.get("stdout") or "{}")
            checks["androidAppBuildId"] = str(build_payload.get("buildId") or build_payload.get("build_id") or "")
        except Exception:
            checks["androidAppBuildId"] = ""
        appops = run_cmd(["adb", "-s", serial, "shell", "appops", "get", PACKAGE_NAME, "RECORD_AUDIO"], timeout=8)
        checks["recordAudioPermission"] = (appops.get("stdout") or appops.get("stderr") or "").strip()
    elif failure == "pass" and serial:
        failure = "android_app_missing"

    checks["latestHermesModelSha"] = model_sha_from_reports()
    checks["latestVoiceWakeDiagnosticsSource"] = latest_voice_wake_source()
    feed, feed_error = ({}, "")
    try:
        feed = request_json("GET", f"{origin}/native/releases/latest.json", timeout=8)
    except Exception as exc:
        feed_error = str(exc)
    checks["releaseFeedReachable"] = bool(feed)
    checks["releaseFeedError"] = feed_error
    try:
        diag = request_json("GET", f"{origin}/native/diagnostics/latest", timeout=8)
    except Exception as exc:
        diag = {"ok": False, "error": str(exc)}
    checks["backendNativeDiagnosticsReachable"] = bool(diag.get("ok"))
    checks["knownGood"] = known_good
    checks["drift"] = {
        "androidBuildId": bool(checks.get("androidAppBuildId") and known_good.get("androidBuildId") and checks.get("androidAppBuildId") != known_good.get("androidBuildId")),
        "modelSha": bool(checks.get("latestHermesModelSha") and known_good.get("modelSha") and checks.get("latestHermesModelSha") != known_good.get("modelSha")),
        "hotOpsProtocol": bool(checks.get("hotOpsProtocolVersion") and known_good.get("expectedHotOpsProtocol") and int(checks.get("hotOpsProtocolVersion") or 0) != int(known_good.get("expectedHotOpsProtocol") or 0)),
    }

    output = {
        "ok": failure == "pass",
        "runId": rid,
        "schema": "hermes.wasm_agent.doctor.v1",
        "mode": "fix" if args.fix else "read-only",
        "origin": origin,
        "artifacts": {"result": artifacts["result"], "logs": artifacts["logs"]},
        "failureClassification": None if failure == "pass" else failure,
        "nextAction": next_action(failure),
        "checks": checks,
    }
    write_json(Path(artifacts["result"]), output)
    write_json(Path(artifacts["latest"]) / "wasm-agent-doctor-result.json", output)
    write_json(Path(artifacts["runResult"]), output)
    Path(artifacts["logs"]).write_text("\n".join(logs) + "\n", encoding="utf-8")
    Path(artifacts["runLogs"]).write_text("\n".join(logs) + "\n", encoding="utf-8")

    print(f"WASM Agent doctor: {'PASS' if output['ok'] else 'FAIL'}")
    print(f"Windows bridge alive: {'yes' if checks.get('windowsBridgeAlive') else 'no'}")
    print(f"Shell build id: {checks.get('shellBuildId') or 'unknown'}")
    print(f"Hot ops protocol: {checks.get('hotOpsProtocolVersion') or 'unknown'}")
    print(f"Active hot ops root: {checks.get('activeHotOpsRoot') or 'unknown'}")
    print(f"Canary hot op: {'pass' if checks.get('canaryHotOpWorks') else 'fail'}")
    print(f"ADB: {'available' if checks.get('adbAvailable') else 'unavailable'}")
    print(f"Android device: {'authorized' if checks.get('authorizedAndroidDeviceConnected') else 'missing'}")
    print(f"Failure classification: {failure}")
    print(f"Next action: {output['nextAction']}")
    print(f"Result JSON: {artifacts['latest']}/wasm-agent-doctor-result.json")
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
