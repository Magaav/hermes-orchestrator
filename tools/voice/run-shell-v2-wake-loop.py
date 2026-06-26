#!/usr/bin/env python3
"""Run the Android shell-v2 wake-word production loop without rebuilding."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "windows"))

from hot_shell_common import (  # noqa: E402
    classify_roundtrip,
    command_timeline,
    read_json,
    run_id as hot_run_id,
    unwrap_result,
    wait_for_result as wait_for_local_result,
    write_json,
)


DEFAULT_ORIGIN = "http://127.0.0.1:8877"
DEFAULT_STATE_DIR = ROOT / "plugins" / "wasm-agent" / "state"
DEFAULT_ENV_FILES = (
    ROOT / "plugins" / "wasm-agent" / "conf" / "wa.env",
    ROOT / "conf" / "wa.env",
)
REPORT_ROOT = ROOT / "reports" / "android" / "wake-shell-v2"
MIN_BUILD_ID = "android-universal-20260622T193436Z"
SHELL_V2_COMPONENT = "com.colmeio.wasmagent/.shell.NativeShellV2Activity"
SHELL_V2_CONTROL_URL = (
    "https://wa.colmeio.com/home?"
    "native=android&shell=android-webview-v2&android_shell=android-webview-v2"
    "&android_runtime=user-full&android_startup=instant-v2&wake=off"
    "&bridgeDiagnostics=off&healthProbes=off&nativeControl=on&nativeObs=on&wao=on"
)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def tail_text(value: str, limit: int = 120_000) -> str:
    if len(value) <= limit:
        return value
    return value[-limit:]


def extract_last_json(text: str) -> dict[str, Any]:
    starts = [index for index, char in enumerate(text) if char == "{"]
    for index in reversed(starts):
        try:
            parsed = json.loads(text[index:].strip())
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def read_env_file(path: str | Path) -> dict[str, str]:
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


def default_env_values(paths: tuple[Path, ...] = DEFAULT_ENV_FILES) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in paths:
        values.update(read_env_file(path))
    return values


def is_local_origin(origin: str) -> bool:
    parsed = urllib.parse.urlparse(origin)
    return parsed.hostname in {"127.0.0.1", "localhost"}


def run_streamed(label: str, cmd: list[str], log_path: Path, extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    with log_path.open("w", encoding="utf-8") as log:
        line = "$ " + " ".join(cmd) + "\n"
        print(line, end="")
        log.write(line)
        process_env = os.environ.copy()
        if extra_env:
            process_env.update({key: value for key, value in extra_env.items() if value})
        process = subprocess.Popen(
            cmd,
            cwd=ROOT,
            env=process_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for output in process.stdout:
            print(output, end="")
            log.write(output)
            parts.append(output)
        exit_code = process.wait()
    output = "".join(parts)
    return {
        "label": label,
        "command": cmd,
        "exitCode": exit_code,
        "ok": exit_code == 0,
        "startedAt": started_at,
        "durationMs": round((time.monotonic() - started) * 1000),
        "log": str(log_path.relative_to(ROOT)),
        "parsedJson": extract_last_json(output),
        "outputTail": tail_text(output),
    }


def request_json(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    *,
    key: str = "",
    timeout: int = 10,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if key:
        headers["X-Wasm-Agent-Native-Control-Key"] = key
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=headers,
    )
    try:
        response = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{method} {url} failed: HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"{method} {url} failed: {error}") from error
    with response:
        parsed = json.loads(response.read().decode("utf-8"))
    return parsed if isinstance(parsed, dict) else {}


def parse_iso_timestamp(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def origin_authority(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def client_received_at(client: dict[str, Any]) -> datetime | None:
    heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
    return parse_iso_timestamp(heartbeat.get("received_at") or client.get("received_at"))


def android_client_summary(client: dict[str, Any], fresh_after: datetime | None = None) -> dict[str, Any]:
    heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
    received_at = client_received_at(client)
    haystack = json.dumps(heartbeat, sort_keys=True).lower()
    build_id = android_client_build_id(client)
    return {
        "deviceId": str(client.get("device_id") or heartbeat.get("device_id") or ""),
        "buildId": build_id,
        "receivedAt": received_at.isoformat().replace("+00:00", "Z") if received_at else "",
        "diagnosticsReceivedAt": str(client.get("diagnostics_received_at") or ""),
        "runtime": heartbeat.get("runtime") or heartbeat.get("native_runtime") or "",
        "route": heartbeat.get("route") or "",
        "shellV2": "android-webview-v2" in haystack,
        "nativeControlOn": "nativecontrol=on" in haystack or "native_control" in haystack,
        "serviceClient": "android-service" in haystack,
        "buildOk": build_id_ok(build_id, MIN_BUILD_ID),
        "fresh": bool(received_at and (fresh_after is None or received_at.timestamp() + 5.0 >= fresh_after.timestamp())),
    }


def clients(origin: str, key: str = "") -> list[dict[str, Any]]:
    payload = request_json("GET", f"{origin.rstrip('/')}/native/control/clients", key=key, timeout=8)
    return payload.get("clients") if isinstance(payload.get("clients"), list) else []


def pick_device(items: list[dict[str, Any]], wanted: str, role: str) -> str:
    if wanted and wanted != "auto":
        return wanted
    scored: list[tuple[int, str]] = []
    for item in items:
        device_id = str(item.get("device_id") or "")
        heartbeat = item.get("heartbeat") if isinstance(item.get("heartbeat"), dict) else {}
        haystack = json.dumps(heartbeat, sort_keys=True).lower()
        if role == "windows" and (device_id.startswith("win-") or "native=electron" in haystack):
            scored.append((20 + (10 if "native=electron" in haystack else 0), device_id))
        if role == "android" and device_id.startswith("android-"):
            score = 10
            if "android-webview-v2" in haystack:
                score += 40
            if "android-webview" in haystack:
                score += 20
            if "nativecontrol=on" in haystack or "native_control" in haystack:
                score += 10
            if "android-service" in haystack:
                score -= 20
            scored.append((score, device_id))
    if not scored:
        return ""
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def android_client_build_id(client: dict[str, Any]) -> str:
    heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
    return str(client.get("build_id") or client.get("buildId") or heartbeat.get("build_id") or heartbeat.get("buildId") or "")


def is_android_webview_client(client: dict[str, Any]) -> bool:
    heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
    haystack = json.dumps(heartbeat, sort_keys=True).lower()
    return "android-webview" in haystack and "android-service" not in haystack


def pick_current_android_webview(
    items: list[dict[str, Any]],
    minimum_build_id: str,
    *,
    fresh_after: datetime | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    scored: list[tuple[int, str]] = []
    summaries: list[dict[str, Any]] = []
    for item in items:
        device_id = str(item.get("device_id") or "")
        if not device_id.startswith("android-") or not is_android_webview_client(item):
            continue
        summary = android_client_summary(item, fresh_after)
        summary["buildOk"] = build_id_ok(str(summary.get("buildId") or ""), minimum_build_id)
        summaries.append(summary)
        build_id = android_client_build_id(item)
        if not build_id_ok(build_id, minimum_build_id):
            continue
        heartbeat = item.get("heartbeat") if isinstance(item.get("heartbeat"), dict) else {}
        haystack = json.dumps(heartbeat, sort_keys=True).lower()
        received_at = client_received_at(item)
        if fresh_after and (not received_at or received_at.timestamp() + 5.0 < fresh_after.timestamp()):
            continue
        if "android-webview-v2" not in haystack:
            continue
        if "nativecontrol=on" not in haystack and "native_control" not in haystack:
            continue
        score = 20
        if "android-webview-v2" in haystack:
            score += 20
        if "nativecontrol=on" in haystack:
            score += 10
        scored.append((score, device_id))
    if not scored:
        return "", summaries
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1], summaries


def wait_current_android_webview(
    origin: str,
    minimum_build_id: str,
    *,
    key: str = "",
    control_url: str,
    fresh_after: datetime | None = None,
    timeout_sec: float = 20.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    latest: list[dict[str, Any]] = []
    latest_summaries: list[dict[str, Any]] = []
    queue_origin = origin_authority(origin)
    control_origin = origin_authority(control_url)
    origin_mismatch = bool(queue_origin and control_origin and queue_origin != control_origin)
    while time.monotonic() < deadline:
        latest = clients(origin, key)
        device_id, latest_summaries = pick_current_android_webview(latest, minimum_build_id, fresh_after=fresh_after)
        if device_id:
            return {
                "ok": True,
                "deviceId": device_id,
                "clientsSeen": len(latest),
                "queueOrigin": queue_origin,
                "controlUrlOrigin": control_origin,
                "controlOriginMismatch": origin_mismatch,
                "freshAfter": fresh_after.isoformat().replace("+00:00", "Z") if fresh_after else "",
            }
        time.sleep(1.0)
    return {
        "ok": False,
        "deviceId": "",
        "clientsSeen": len(latest),
        "queueOrigin": queue_origin,
        "controlUrlOrigin": control_origin,
        "controlOriginMismatch": origin_mismatch,
        "freshAfter": fresh_after.isoformat().replace("+00:00", "Z") if fresh_after else "",
        "androidClients": latest_summaries,
    }


def queue_control_command(
    origin: str,
    key: str,
    device_id: str,
    command: str,
    payload: dict[str, Any],
    rid: str,
    reason: str,
) -> tuple[str, dict[str, Any]]:
    body = {
        "device_id": device_id,
        "command": command,
        "command_id": f"{rid}-{command.replace('_', '-')[:32]}",
        "payload": payload,
        "reason": reason,
    }
    queued = request_json("POST", f"{origin.rstrip('/')}/native/control/command", body, key=key, timeout=10)
    command_id = str((queued.get("command") or {}).get("id") or body["command_id"])
    return command_id, queued


def read_remote_result(origin: str, key: str, device_id: str, command_id: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"device_id": device_id})
    try:
        payload = request_json("GET", f"{origin.rstrip('/')}/native/frontier/status?{query}", key=key, timeout=15)
    except RuntimeError:
        return {}
    latest = payload.get("native_control", {}).get("latest_result", {})
    if isinstance(latest, dict) and str(latest.get("command_id") or "").lower() == command_id.lower():
        return latest
    return {}


def wait_for_command_result(
    *,
    local: bool,
    state_dir: Path,
    origin: str,
    key: str,
    device_id: str,
    command_id: str,
    wait_sec: int,
    poll_sec: float = 0.5,
) -> dict[str, Any]:
    if local:
        return wait_for_local_result(state_dir, device_id, command_id, wait_sec=wait_sec, poll_sec=poll_sec)
    deadline = time.monotonic() + max(1, wait_sec)
    while time.monotonic() < deadline:
        found = read_remote_result(origin, key, device_id, command_id)
        if found:
            return found
        time.sleep(max(1.0, poll_sec))
    return {}


def classify_command_roundtrip(local: bool, state_dir: Path, device_id: str, command_id: str, record: dict[str, Any]) -> str:
    if local:
        return classify_roundtrip(state_dir, device_id, command_id, record)
    if not record:
        return "command_not_polled"
    result = unwrap_result(record)
    if not isinstance(result, dict) or not result:
        return "result_seen_wrong_shape"
    if result.get("ok") is False:
        return str(result.get("failureClassification") or result.get("failure_classification") or result.get("error") or "handler_threw")
    return "pass"


def command_timeline_for_result(
    local: bool,
    state_dir: Path,
    device_id: str,
    command_id: str,
    record: dict[str, Any],
    queued: dict[str, Any],
) -> dict[str, Any]:
    if local:
        return command_timeline(state_dir, device_id, command_id, record)
    command = queued.get("command") if isinstance(queued.get("command"), dict) else {}
    return {
        "command_id": command_id,
        "command_type": command.get("type") or command.get("command") or "",
        "command_status": command.get("status") or "",
        "queued_at": command.get("created_at") or "",
        "picked_up_at": command.get("delivered_at") or "",
        "completed_at": record.get("received_at") or "",
        "uploaded_at": record.get("received_at") or "",
        "result_seen_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z") if record else "",
        "result_json_shape": "present" if record else "missing",
    }


def phase_status(phase: dict[str, Any]) -> str:
    parsed = phase.get("parsedJson") if isinstance(phase.get("parsedJson"), dict) else {}
    if phase.get("ok") is True:
        return "pass"
    for key in ("failureClass", "failureClassification", "classification", "status"):
        if parsed.get(key):
            return str(parsed[key])
    output = str(phase.get("outputTail") or "")
    for needle in ("Failure classification:", "failureClassification="):
        if needle in output:
            value = output.rsplit(needle, 1)[-1].strip().split()[0].strip(".,")
            if value:
                return value
    return "failed"


def build_id_ok(value: str, minimum: str) -> bool:
    if not value:
        return False
    return value >= minimum


def release_build_id() -> str:
    feed = read_json(ROOT / "plugins" / "wasm-agent" / "public" / "native" / "releases" / "latest.json")
    artifacts = feed.get("artifacts") if isinstance(feed.get("artifacts"), dict) else {}
    android = artifacts.get("android") if isinstance(artifacts.get("android"), dict) else {}
    arm64 = android.get("arm64") if isinstance(android.get("arm64"), dict) else {}
    return str(arm64.get("buildId") or "")


def result_state(record: dict[str, Any]) -> dict[str, Any]:
    result = unwrap_result(record) if record else {}
    nested = result.get("result") if isinstance(result.get("result"), dict) else {}
    for candidate in (
        nested.get("state"),
        result.get("state"),
        result.get("wake_word_state"),
        result.get("wakeWordState"),
        nested,
        result,
    ):
        if isinstance(candidate, dict):
            return candidate
    return {}


def run_android_command(
    *,
    origin: str,
    key: str,
    local: bool,
    state_dir: Path,
    android_device_id: str,
    command_type: str,
    payload: dict[str, Any],
    reason: str,
    wait_sec: int,
) -> dict[str, Any]:
    started = time.monotonic()
    command_id, queued = queue_control_command(origin, key, android_device_id, command_type, payload, hot_run_id("shell-v2-wake"), reason)
    record = wait_for_command_result(
        local=local,
        state_dir=state_dir,
        origin=origin,
        key=key,
        device_id=android_device_id,
        command_id=command_id,
        wait_sec=wait_sec,
        poll_sec=0.5,
    )
    result = unwrap_result(record) if record else {}
    roundtrip = classify_command_roundtrip(local, state_dir, android_device_id, command_id, record)
    ok = bool(roundtrip == "pass" and result.get("ok") is not False)
    return {
        "label": command_type,
        "commandId": command_id,
        "queued": queued,
        "ok": ok,
        "exitCode": 0 if ok else 1,
        "durationMs": round((time.monotonic() - started) * 1000),
        "roundtrip": roundtrip,
        "timeline": command_timeline_for_result(local, state_dir, android_device_id, command_id, record, queued),
        "parsedJson": result,
        "state": result_state(record),
    }


def run_windows_hot_operation(
    *,
    origin: str,
    key: str,
    local: bool,
    state_dir: Path,
    windows_device_id: str,
    operation_name: str,
    operation_args: dict[str, Any],
    reason: str,
    wait_sec: int,
) -> dict[str, Any]:
    started = time.monotonic()
    payload = {"operationName": operation_name, "args": operation_args}
    command_id, queued = queue_control_command(origin, key, windows_device_id, "run_hot_operation", payload, hot_run_id("shell-v2-wake"), reason)
    record = wait_for_command_result(
        local=local,
        state_dir=state_dir,
        origin=origin,
        key=key,
        device_id=windows_device_id,
        command_id=command_id,
        wait_sec=wait_sec,
        poll_sec=0.5,
    )
    result = unwrap_result(record) if record else {}
    roundtrip = classify_command_roundtrip(local, state_dir, windows_device_id, command_id, record)
    raw = result.get("rawResult") if isinstance(result.get("rawResult"), dict) else result.get("result") if isinstance(result.get("result"), dict) else result
    ok = bool(roundtrip == "pass" and result.get("ok") is not False and raw.get("ok") is not False)
    return {
        "label": f"windows_hot_op:{operation_name}",
        "commandId": command_id,
        "queued": queued,
        "ok": ok,
        "exitCode": 0 if ok else 1,
        "durationMs": round((time.monotonic() - started) * 1000),
        "roundtrip": roundtrip,
        "timeline": command_timeline_for_result(local, state_dir, windows_device_id, command_id, record, queued),
        "parsedJson": result,
        "rawResult": raw,
    }


def finish(report: dict[str, Any], report_path: Path) -> int:
    latest_path = REPORT_ROOT / "latest-shell-v2-wake-loop.json"
    report["finishedAt"] = datetime.now(timezone.utc).isoformat()
    report["durationMs"] = round((time.monotonic() - report["_startedMonotonic"]) * 1000)
    report.pop("_startedMonotonic", None)
    write_json(report_path, report)
    write_json(latest_path, report)
    print(json.dumps({
        "status": report["status"],
        "failureClass": report.get("failureClass"),
        "report": str(report_path.relative_to(ROOT)),
        "latest": str(latest_path.relative_to(ROOT)),
        "summary": report.get("summary", ""),
    }, indent=2, sort_keys=True))
    return int(report.get("exitCode", 1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    env_defaults = default_env_values()
    parser.add_argument("--origin", default=os.getenv("WASM_AGENT_ORIGIN") or env_defaults.get("WASM_AGENT_ORIGIN") or DEFAULT_ORIGIN)
    parser.add_argument("--android-origin", default=os.getenv("WASM_AGENT_ANDROID_CONTROL_ORIGIN") or env_defaults.get("WASM_AGENT_ANDROID_CONTROL_ORIGIN") or "")
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    parser.add_argument("--control-key", default=os.getenv("WASM_AGENT_NATIVE_CONTROL_KEY") or env_defaults.get("WASM_AGENT_NATIVE_CONTROL_KEY") or "")
    parser.add_argument("--env-file", default=os.getenv("WASM_AGENT_ENV_FILE", ""))
    parser.add_argument("--wait-sec", type=int, default=75)
    parser.add_argument("--ux-wait-sec", type=int, default=180)
    parser.add_argument("--android-device-id", default="auto")
    parser.add_argument("--windows-device-id", default="auto")
    parser.add_argument("--min-build-id", default=MIN_BUILD_ID)
    parser.add_argument("--control-url", default=SHELL_V2_CONTROL_URL)
    parser.add_argument("--phrase", default="alexa open wake word")
    parser.add_argument("--wake-threshold", type=float, default=0.999)
    parser.add_argument("--wake-confirmation-frames", type=int, default=2)
    parser.add_argument("--wake-confirmation-window-ms", type=int, default=700)
    parser.add_argument("--wake-cooldown-ms", type=int, default=8000)
    parser.add_argument("--vad-rms-threshold", type=float, default=0.04)
    parser.add_argument("--vad-peak-threshold", type=int, default=5000)
    parser.add_argument("--observe-sec", type=float, default=28.0)
    parser.add_argument("--settle-sec", type=float, default=2.0)
    parser.add_argument("--volume", type=int, default=100)
    parser.add_argument("--rate", type=int, default=-2)
    parser.add_argument("--full-gate", action="store_true", help="Run slow production gate phases before wake tuning.")
    parser.add_argument("--skip-ux-proof", action="store_true", default=True)
    parser.add_argument("--run-ux-proof", dest="skip_ux_proof", action="store_false")
    parser.add_argument("--skip-publish-hot-op-feed", action="store_true", default=True)
    parser.add_argument("--publish-hot-op-feed", dest="skip_publish_hot_op_feed", action="store_false")
    parser.add_argument("--skip-control-relaunch", action="store_true")
    parser.add_argument("--accept-responsiveness-incomplete", action="store_true", default=True)
    parser.add_argument("--strict-responsiveness", dest="accept_responsiveness_incomplete", action="store_false")
    args = parser.parse_args()
    if args.env_file:
        explicit_env = read_env_file(args.env_file)
        args.origin = args.origin or explicit_env.get("WASM_AGENT_ORIGIN") or DEFAULT_ORIGIN
        args.control_key = args.control_key or explicit_env.get("WASM_AGENT_NATIVE_CONTROL_KEY") or ""
    if args.full_gate:
        args.skip_ux_proof = False
        args.skip_publish_hot_op_feed = False
        args.accept_responsiveness_incomplete = False

    windows_origin = args.origin.rstrip("/")
    android_origin = (args.android_origin or origin_authority(args.control_url) or windows_origin).rstrip("/")
    windows_local = is_local_origin(windows_origin)
    android_local = is_local_origin(android_origin)
    control_key = args.control_key or ""
    if not android_local and not control_key:
        stamp = utc_stamp()
        report_path = REPORT_ROOT / f"{stamp}-shell-v2-wake-loop.json"
        report = {
            "_startedMonotonic": time.monotonic(),
            "schema": "hermes.wasm_agent.android_shell_v2_wake_loop.v1",
            "status": "blocked",
            "exitCode": 2,
            "failureClass": "native_control_key_missing",
            "summary": "Cloud shell-v2 wake proof requires WASM_AGENT_NATIVE_CONTROL_KEY or --control-key.",
            "startedAt": datetime.now(timezone.utc).isoformat(),
            "origin": windows_origin,
            "windowsOrigin": windows_origin,
            "androidOrigin": android_origin,
            "target": {"shellV2": True, "component": SHELL_V2_COMPONENT, "controlUrl": args.control_url},
            "phases": [],
        }
        return finish(report, report_path)
    state_dir = Path(args.state_dir)
    stamp = utc_stamp()
    run_dir = REPORT_ROOT / "runs" / f"shell-v2-wake-{stamp}"
    report_path = REPORT_ROOT / f"{stamp}-shell-v2-wake-loop.json"
    report: dict[str, Any] = {
        "_startedMonotonic": time.monotonic(),
        "schema": "hermes.wasm_agent.android_shell_v2_wake_loop.v1",
        "status": "running",
        "exitCode": 1,
        "failureClass": "",
        "summary": "",
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "origin": windows_origin,
        "windowsOrigin": windows_origin,
        "androidOrigin": android_origin,
        "controlUrlOrigin": origin_authority(args.control_url),
        "minBuildId": args.min_build_id,
        "target": {
            "shellV2": True,
            "component": SHELL_V2_COMPONENT,
            "controlUrl": args.control_url,
            "phrase": args.phrase,
            "directAdbServiceStartAllowed": False,
        },
        "release": {"buildId": release_build_id()},
        "policy": {
            "wakePhrase": "alexa",
            "wakeThreshold": args.wake_threshold,
            "wakeConfirmationFrames": args.wake_confirmation_frames,
            "wakeConfirmationWindowMs": args.wake_confirmation_window_ms,
            "wakeCooldownMs": args.wake_cooldown_ms,
            "vadRmsThreshold": args.vad_rms_threshold,
            "vadPeakThreshold": args.vad_peak_threshold,
            "tuningSessionId": f"shell-v2-wake-{stamp.lower()}",
        },
        "phases": [],
    }

    if not build_id_ok(report["release"]["buildId"], args.min_build_id):
        report.update({
            "status": "blocked",
            "exitCode": 2,
            "failureClass": "android_release_build_too_old",
            "summary": f"Release feed buildId {report['release']['buildId'] or '<missing>'} is older than required {args.min_build_id}.",
        })
        return finish(report, report_path)

    preflight = run_streamed(
        "windows_hot_shell_preflight",
        ["python3", "tools/windows/prove-hot-shell.py", "--preflight-only", "--wait-sec", str(args.wait_sec)],
        run_dir / "01-windows-hot-shell-preflight.log",
    )
    report["phases"].append(preflight)
    if not preflight["ok"]:
        report.update({
            "status": "blocked",
            "exitCode": 2,
            "failureClass": phase_status(preflight),
            "summary": "Windows hot-shell preflight failed. Restart/reopen the installed Windows app, then rerun this loop.",
        })
        return finish(report, report_path)

    if not args.skip_publish_hot_op_feed:
        feed = run_streamed(
            "publish_native_release_feed_for_hot_ops",
            ["node", "plugins/wasm-agent/scripts/generate-native-release-feed.js"],
            run_dir / "02-publish-native-release-feed.log",
        )
        report["phases"].append(feed)
        if not feed["ok"]:
            report.update({
                "status": "blocked",
                "exitCode": 2,
                "failureClass": phase_status(feed),
                "summary": "Native release feed refresh failed before shell-v2 control relaunch.",
            })
            return finish(report, report_path)

    if not args.skip_ux_proof:
        ux = run_streamed(
            "android_shell_v2_ux_release_loop",
            [
                "python3",
                "tools/android/prove-android-native-ux-release-loop.py",
                "--skip-build",
                "--shell-v2",
                "--run-shell-v2-adb-proof",
                "--publish-feed",
                "--wait-sec",
                str(args.ux_wait_sec),
            ],
            run_dir / "03-android-shell-v2-ux-release-loop.log",
        )
        report["phases"].append(ux)
        parsed = ux.get("parsedJson") if isinstance(ux.get("parsedJson"), dict) else {}
        report["uxProof"] = parsed
        if not ux["ok"] and not args.accept_responsiveness_incomplete:
            report.update({
                "status": "blocked",
                "exitCode": 2,
                "failureClass": phase_status(ux),
                "summary": "Shell-v2 launch/responsiveness proof failed or was incomplete; wake loop was not started.",
            })
            return finish(report, report_path)
        if not ux["ok"]:
            report["responsivenessAccepted"] = {
                "accepted": True,
                "reason": "--accept-responsiveness-incomplete was set",
                "failureClass": phase_status(ux),
            }
    else:
        report["responsivenessAccepted"] = {
            "accepted": bool(args.accept_responsiveness_incomplete),
            "reason": "--skip-ux-proof was set",
        }
        if not args.accept_responsiveness_incomplete:
            report.update({
                "status": "needs-human-proof",
                "exitCode": 3,
                "failureClass": "responsiveness_proof_skipped_without_acceptance",
                "summary": "Shell-v2 responsiveness proof was skipped without explicit acceptance.",
            })
            return finish(report, report_path)

    windows_clients = clients(windows_origin, control_key if not windows_local else "")
    android_clients = clients(android_origin, control_key if not android_local else "")
    windows_device_id = pick_device(windows_clients, args.windows_device_id, "windows")
    android_device_id = pick_device(android_clients, args.android_device_id, "android")
    report["devices"] = {"windowsDeviceId": windows_device_id, "androidDeviceId": android_device_id}
    if not windows_device_id:
        report.update({
            "status": "blocked",
            "exitCode": 2,
            "failureClass": "windows_native_control_client_missing",
            "summary": "No Windows native-control client was visible for shell-v2 Android hot operations.",
        })
        return finish(report, report_path)
    if not android_device_id and args.skip_control_relaunch:
        report.update({
            "status": "blocked",
            "exitCode": 2,
            "failureClass": "android_native_control_client_missing",
            "summary": "No Android native-control client was visible after shell-v2 launch proof.",
        })
        return finish(report, report_path)

    if not args.skip_control_relaunch:
        # Shell v2 intentionally starts with nativeControl=off. This explicit
        # relaunch keeps startup clean while enabling the bridge command loop
        # for the wake proof stage, without an APK rebuild.
        control_relaunch_started_at = datetime.now(timezone.utc)
        control_launch = run_windows_hot_operation(
            origin=windows_origin,
            key=control_key if not windows_local else "",
            local=windows_local,
            state_dir=state_dir,
            windows_device_id=windows_device_id,
            operation_name="run_android_ui_input_proof",
            operation_args={
                "action": "launch",
                "packageName": "com.colmeio.wasmagent",
                "componentName": SHELL_V2_COMPONENT,
                "dataUri": args.control_url,
                "intentAction": "android.intent.action.VIEW",
                "categories": ["android.intent.category.DEFAULT", "android.intent.category.BROWSABLE"],
                "stopFirst": True,
            },
            reason="shell-v2 wake loop: relaunch shell v2 with nativeControl=on for bridge wake proof",
            wait_sec=args.wait_sec,
        )
        report["phases"].append(control_launch)
        if not control_launch["ok"]:
            report.update({
                "status": "fail",
                "exitCode": 1,
                "failureClass": control_launch.get("roundtrip") or "shell_v2_control_relaunch_failed",
                "summary": "Shell-v2 control relaunch with nativeControl=on failed.",
            })
            return finish(report, report_path)
        webview = wait_current_android_webview(
            android_origin,
            args.min_build_id,
            key=control_key if not android_local else "",
            control_url=args.control_url,
            fresh_after=control_relaunch_started_at,
            timeout_sec=24.0,
        )
        report["shellV2WebViewClient"] = webview
        if not webview.get("ok"):
            failure_class = "shell_v2_webview_native_control_client_missing"
            summary = "Shell-v2 relaunched with nativeControl=on, but no fresh current-build Android WebView native-control client registered to poll bridge commands."
            if webview.get("controlOriginMismatch"):
                failure_class = "shell_v2_control_origin_mismatch"
                summary = (
                    "Shell-v2 control relaunch used a different origin than the command queue; "
                    "the Android WebView will not poll commands from this harness origin."
                )
            report.update({
                "status": "blocked",
                "exitCode": 2,
                "failureClass": failure_class,
                "summary": summary,
            })
            return finish(report, report_path)
        android_device_id = str(webview.get("deviceId") or "")
        report["devices"] = {"windowsDeviceId": windows_device_id, "androidDeviceId": android_device_id}

    start = run_android_command(
        origin=android_origin,
        key=control_key if not android_local else "",
        local=android_local,
        state_dir=state_dir,
        android_device_id=android_device_id,
        command_type="start_voice_wake",
        payload={"restart": True, "settleMs": 1800},
        reason="shell-v2 wake loop: call WasmAgentNative.enableVoiceWake through the app bridge",
        wait_sec=args.wait_sec,
    )
    report["phases"].append(start)
    if not start["ok"]:
        report.update({
            "status": "fail",
            "exitCode": 1,
            "failureClass": start.get("roundtrip") or "start_voice_wake_failed",
            "summary": "Wake service did not start through shell-v2 bridge command start_voice_wake / enableVoiceWake.",
        })
        return finish(report, report_path)

    policy = run_android_command(
        origin=android_origin,
        key=control_key if not android_local else "",
        local=android_local,
        state_dir=state_dir,
        android_device_id=android_device_id,
        command_type="apply_wake_word_policy",
        payload=report["policy"],
        reason="shell-v2 wake loop: apply production wake policy through app bridge",
        wait_sec=args.wait_sec,
    )
    report["phases"].append(policy)
    if not policy["ok"]:
        report.update({
            "status": "fail",
            "exitCode": 1,
            "failureClass": policy.get("roundtrip") or "apply_wake_word_policy_failed",
            "summary": "Wake policy did not apply through shell-v2 bridge.",
        })
        return finish(report, report_path)

    refresh = run_android_command(
        origin=android_origin,
        key=control_key if not android_local else "",
        local=android_local,
        state_dir=state_dir,
        android_device_id=android_device_id,
        command_type="refresh_wake_word_state",
        payload={},
        reason="shell-v2 wake loop: refresh wake state after bridge start/policy",
        wait_sec=args.wait_sec,
    )
    report["phases"].append(refresh)
    state = refresh.get("state") if isinstance(refresh.get("state"), dict) else {}
    voice = state.get("voice_wake") if isinstance(state.get("voice_wake"), dict) else state
    report["wakeStateAfterStart"] = state
    state_build_id = str(voice.get("build_id") or state.get("build_id") or "")
    if not build_id_ok(state_build_id, args.min_build_id):
        report.update({
            "status": "blocked",
            "exitCode": 2,
            "failureClass": "installed_android_build_too_old",
            "summary": f"Installed wake state buildId {state_build_id or '<missing>'} is older than required {args.min_build_id}.",
        })
        return finish(report, report_path)
    if not bool(voice.get("foreground_service_active") or voice.get("foreground_service_started") or state.get("foreground_service_active")):
        report.update({
            "status": "fail",
            "exitCode": 1,
            "failureClass": "wake_service_not_active_after_shell_v2_bridge_start",
            "summary": "Wake service did not report active after shell-v2 bridge start and policy.",
        })
        return finish(report, report_path)

    room = run_streamed(
        "wake_room_loop_synth_speech",
        [
            "python3",
            "tools/voice/run-wake-room-loop.py",
            "--windows-origin",
            windows_origin,
            "--android-origin",
            android_origin,
            "--android-device-id",
            android_device_id,
            "--windows-device-id",
            windows_device_id or "auto",
            "--stimulus",
            "speech",
            "--phrase",
            args.phrase,
            "--observe-sec",
            str(args.observe_sec),
            "--settle-sec",
            str(args.settle_sec),
            "--state-source",
            "command",
            "--label",
            "shell-v2-alexa-command",
            "--volume",
            str(args.volume),
            "--rate",
            str(args.rate),
        ],
        run_dir / "03-wake-room-loop-synth-speech.log",
        extra_env={"WASM_AGENT_NATIVE_CONTROL_KEY": control_key if not android_local else ""},
    )
    report["phases"].append(room)
    parsed_room = room.get("parsedJson") if isinstance(room.get("parsedJson"), dict) else {}
    report["roomLoop"] = parsed_room
    classification = str(parsed_room.get("classification") or "")
    routed = (parsed_room.get("timeline") if isinstance(parsed_room.get("timeline"), dict) else {}).get("routed_command_count", 0)
    if room["ok"] and classification == "voice_command_routed" and int(routed or 0) > 0:
        report.update({
            "status": "pass",
            "exitCode": 0,
            "failureClass": "",
            "summary": "Shell-v2 wake loop passed: bridge health, installed shell-v2 launch, bridge-started wake, policy, and synthesized speech routing all produced evidence.",
        })
        return finish(report, report_path)

    report.update({
        "status": "fail",
        "exitCode": 1,
        "failureClass": classification or phase_status(room),
        "summary": "Synthesized wake phrase did not produce routed command evidence.",
    })
    return finish(report, report_path)


if __name__ == "__main__":
    raise SystemExit(main())
