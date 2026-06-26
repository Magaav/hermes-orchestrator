#!/usr/bin/env python3
"""Prove a small Android native input budget through the Windows bridge."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "windows"))

from hot_shell_common import (  # noqa: E402
    artifact_paths,
    choose_windows_client,
    classify_roundtrip,
    cleanup_native_control_state,
    command_timeline,
    next_action,
    queue_command,
    request_json,
    run_id,
    unwrap_result,
    wait_for_result,
    write_json,
)


DEFAULT_ORIGIN = "http://127.0.0.1:8877"
DEFAULT_PACKAGE = "com.colmeio.wasmagent"


def choose_android_client(clients: list[dict[str, Any]]) -> str:
    candidates: list[tuple[int, str]] = []
    for index, client in enumerate(clients):
        heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
        device_id = str(client.get("device_id") or heartbeat.get("device_id") or "")
        if not device_id.startswith("android-"):
            continue
        score = 1000 - index
        if "universal" in device_id:
            score += 100
        if heartbeat.get("route") or heartbeat.get("capabilities"):
            score += 20
        candidates.append((score, device_id))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][1]


def number_after(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def percentile(label: str, text: str) -> int | None:
    return number_after(rf"{re.escape(label)}\s*percentile:\s*(\d+)ms", text)


def parse_launch_timing(text: str) -> dict[str, Any]:
    return {
        "launch_total_time_ms": number_after(r"TotalTime:\s*(\d+)", text),
        "launch_wait_time_ms": number_after(r"WaitTime:\s*(\d+)", text),
        "launch_this_time_ms": number_after(r"ThisTime:\s*(\d+)", text),
    }


def parse_gfxinfo(text: str) -> dict[str, Any]:
    return {
        "total_frames": number_after(r"Total frames rendered:\s*(\d+)", text),
        "janky_frames": number_after(r"Janky frames:\s*(\d+)", text),
        "high_input_latency": number_after(r"Number High input latency:\s*(\d+)", text),
        "slow_ui_thread": number_after(r"Number Slow UI thread:\s*(\d+)", text),
        "slow_draw_commands": number_after(r"Number Slow issue draw commands:\s*(\d+)", text),
        "frame_deadline_missed": number_after(r"Number Frame deadline missed:\s*(\d+)", text),
        "p50_ms": percentile("50th", text),
        "p90_ms": percentile("90th", text),
        "p95_ms": percentile("95th", text),
        "p99_ms": percentile("99th", text),
    }


def nested_result(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("rawResult", "result"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload


def budget_pass(metrics: dict[str, Any], args: argparse.Namespace) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if not args.no_launch_first and args.launch_method == "activity":
        launch_checks = [
            ("launch_total_time_ms", args.max_launch_total_ms),
            ("launch_wait_time_ms", args.max_launch_wait_ms),
        ]
        for key, maximum in launch_checks:
            value = metrics.get(key)
            if value is None:
                failures.append(f"{key}=missing")
            elif value > maximum:
                failures.append(f"{key}={value} > {maximum}")
    if args.launch_only:
        return not failures, failures
    total_frames = metrics.get("total_frames")
    if total_frames is None:
        failures.append("total_frames=missing")
    elif total_frames <= 0:
        failures.append("total_frames=0")
    checks = [
        ("high_input_latency", args.max_high_input_latency),
        ("slow_ui_thread", args.max_slow_ui_thread),
        ("slow_draw_commands", args.max_slow_draw_commands),
        ("frame_deadline_missed", args.max_frame_deadline_missed),
        ("p95_ms", args.max_p95_ms),
        ("janky_frames", args.max_janky_frames),
    ]
    for key, maximum in checks:
        value = metrics.get(key)
        if value is None:
            failures.append(f"{key}=missing")
        elif value > maximum:
            failures.append(f"{key}={value} > {maximum}")
    return not failures, failures


def run_hot_op(
    *,
    origin: str,
    state_dir: Path,
    windows_device_id: str,
    rid: str,
    action: str,
    args: dict[str, Any],
    wait_sec: int,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    payload = {
        "operationName": "run_android_ui_input_proof",
        "args": {"action": action, **args},
    }
    command_id, _queued = queue_command(
        origin,
        windows_device_id,
        "run_hot_operation",
        payload,
        f"{rid}-{action}",
        f"android input budget {action}",
    )
    record = wait_for_result(state_dir, windows_device_id, command_id, wait_sec=wait_sec, poll_sec=0.75)
    result = unwrap_result(record) if record else {}
    return command_id, record, result


def collect_android_ux_report(
    *,
    origin: str,
    state_dir: Path,
    rid: str,
    wait_sec: int,
    result: dict[str, Any],
    logs: list[str],
    reason: str,
) -> None:
    try:
        clients = request_json("GET", f"{origin.rstrip()}/native/control/clients", timeout=8)
        android_device_id = choose_android_client(clients.get("clients") if isinstance(clients.get("clients"), list) else [])
        if not android_device_id:
            result["androidNativeUxReport"] = {
                "ok": False,
                "error": "android_native_control_missing",
            }
            return
        last_error: Exception | None = None
        for command_type, payload in (
            ("get_android_native_ux_report", {"reason": reason, "force": True, "idleTimeoutMs": 1200}),
            ("get_runtime_snapshot", {"reason": reason, "force": True, "idleTimeoutMs": 1200}),
        ):
            try:
                command_id, _queued = queue_command(
                    origin,
                    android_device_id,
                    command_type,
                    payload,
                    f"{rid}-{command_type}",
                    "collect Android native UX report after input budget proof",
                )
            except Exception as exc:
                last_error = exc
                logs.append(json.dumps({"action": command_type, "queue_error": exc.__class__.__name__, "message": str(exc)}, sort_keys=True))
                continue
            record = wait_for_result(state_dir, android_device_id, command_id, wait_sec=wait_sec, poll_sec=0.75)
            hot_result = unwrap_result(record) if record else {}
            classification = classify_roundtrip(state_dir, android_device_id, command_id, record)
            command_summary = {
                "action": command_type,
                "commandId": command_id,
                "classification": classification,
                "timeline": command_timeline(state_dir, android_device_id, command_id, record),
                "result": hot_result,
            }
            result["commands"].append(command_summary)
            logs.append(json.dumps({"action": command_type, "classification": classification}, sort_keys=True))
            if command_type == "get_android_native_ux_report":
                report = hot_result.get("report") if isinstance(hot_result.get("report"), dict) else hot_result
            else:
                snapshot = hot_result.get("snapshot") if isinstance(hot_result.get("snapshot"), dict) else hot_result
                report = {
                    "schema": "hermes.wasm_agent.android_native_ux_report_from_runtime_snapshot.v1",
                    "source": "get_runtime_snapshot",
                    "canvas_navigation": snapshot.get("canvas_navigation", {}),
                    "responsiveness": snapshot.get("responsiveness", {}),
                    "ui_scheduler": snapshot.get("ui_scheduler", {}),
                    "recent_user_input_ms": snapshot.get("recent_user_input_ms"),
                    "input_pending": snapshot.get("input_pending"),
                }
            result["androidNativeUxReport"] = report
            return
        if last_error is not None:
            raise last_error
    except Exception as exc:
        result["androidNativeUxReport"] = {
            "ok": False,
            "error": exc.__class__.__name__,
            "message": str(exc),
        }


def android_ux_ready_state(hot_result: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    report = hot_result.get("report") if isinstance(hot_result.get("report"), dict) else {}
    responsiveness = report.get("responsiveness") if isinstance(report.get("responsiveness"), dict) else {}
    capabilities = hot_result.get("capabilities") if isinstance(hot_result.get("capabilities"), dict) else {}
    reasons: list[str] = []
    if hot_result.get("ok") is not True:
        reasons.append("report_not_ok")
    if not report:
        reasons.append("report_missing")
    runtime_mode = str(capabilities.get("runtime_mode") or "").strip()
    if runtime_mode and runtime_mode not in {"user-full", "full"}:
        reasons.append(f"runtime_mode={runtime_mode}")
    if responsiveness.get("overloaded") is True:
        reasons.append("overloaded")
    if responsiveness.get("input_pending") is True or report.get("input_pending") is True:
        reasons.append("input_pending")
    if responsiveness.get("recent_user_input") is True:
        reasons.append("recent_user_input")
    if not (report.get("full_ui_ready_marker_ms") or report.get("first_interactive_marker_ms")):
        reasons.append("ui_ready_marker_missing")
    summary = {
        "runtimeMode": runtime_mode,
        "source": report.get("source") or "",
        "verdict": report.get("app_responsiveness_verdict") or "",
        "overloaded": responsiveness.get("overloaded"),
        "recentUserInput": responsiveness.get("recent_user_input"),
        "inputPending": responsiveness.get("input_pending") or report.get("input_pending"),
        "fullUiReadyMs": report.get("full_ui_ready_marker_ms"),
        "firstInteractiveMs": report.get("first_interactive_marker_ms"),
        "frameGapP95Ms": report.get("frame_gap_p95_ms"),
        "frameGapMaxMs": report.get("frame_gap_max_ms"),
    }
    return not reasons, reasons, summary


def wait_for_android_ux_ready(
    *,
    origin: str,
    state_dir: Path,
    rid: str,
    wait_sec: int,
    ready_wait_sec: float,
    result: dict[str, Any],
    logs: list[str],
) -> tuple[bool, str]:
    if ready_wait_sec <= 0:
        return True, ""
    deadline = time.monotonic() + ready_wait_sec
    last_reason = "not_checked"
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        clients = request_json("GET", f"{origin.rstrip()}/native/control/clients", timeout=8)
        android_device_id = choose_android_client(clients.get("clients") if isinstance(clients.get("clients"), list) else [])
        if not android_device_id:
            last_reason = "android_native_control_missing"
            time.sleep(1.0)
            continue
        command_id, _queued = queue_command(
            origin,
            android_device_id,
            "get_android_native_ux_report",
            {"reason": "pre_prepare_ready", "force": True, "idleTimeoutMs": 1200},
            f"{rid}-pre-prepare-ready-{attempt}",
            "wait for Android native full-runtime readiness before canvas input proof",
        )
        remaining = max(1, int(deadline - time.monotonic()))
        record = wait_for_result(state_dir, android_device_id, command_id, wait_sec=min(wait_sec, remaining), poll_sec=0.75)
        hot_result = unwrap_result(record) if record else {}
        classification = classify_roundtrip(state_dir, android_device_id, command_id, record)
        ready, reasons, summary = android_ux_ready_state(hot_result)
        result["commands"].append({
            "action": "pre_prepare_ready",
            "commandId": command_id,
            "classification": classification,
            "timeline": command_timeline(state_dir, android_device_id, command_id, record),
            "readiness": {
                "ready": ready,
                "reasons": reasons,
                "summary": summary,
            },
            "result": hot_result,
        })
        logs.append(json.dumps({
            "action": "pre_prepare_ready",
            "attempt": attempt,
            "classification": classification,
            "ready": ready,
            "reasons": reasons,
            "summary": summary,
        }, sort_keys=True))
        if classification == "pass" and ready:
            result["androidNativePrePrepareReady"] = {
                "ok": True,
                "attempts": attempt,
                "summary": summary,
            }
            return True, ""
        last_reason = ",".join(reasons or [classification or "not_ready"])
        time.sleep(1.5)
    result["androidNativePrePrepareReady"] = {
        "ok": False,
        "reason": last_reason,
    }
    return False, last_reason


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--state-dir", default="plugins/wasm-agent/state")
    parser.add_argument("--package-name", default=DEFAULT_PACKAGE)
    parser.add_argument("--wait-sec", type=int, default=90)
    parser.add_argument("--gesture-duration-ms", type=int, default=420)
    parser.add_argument("--no-launch-first", action="store_true", help="Skip the default app foreground launch before resetting gfxinfo.")
    parser.add_argument("--stop-first", dest="stop_first", action="store_true", default=True, help="Force-stop the app during the default foreground launch.")
    parser.add_argument("--no-stop-first", dest="stop_first", action="store_false", help="Launch without force-stopping first.")
    parser.add_argument("--launch-method", choices=["activity", "monkey"], default="activity")
    parser.add_argument("--launch-component", default="", help="Explicit Android component to launch, e.g. com.colmeio.wasmagent/.shell.NativeShellV2Activity.")
    parser.add_argument("--launch-settle-sec", type=float, default=4.0)
    parser.add_argument("--launch-ready-wait-sec", type=float, default=45.0)
    parser.add_argument("--launch-only", action="store_true", help="Measure only the Activity launch timing; do not dispatch synthetic input or gfxinfo probes.")
    parser.add_argument("--prepare-space", dest="prepare_space", action="store_true", default=True, help="Switch to a non-home space panel before resetting gfxinfo.")
    parser.add_argument("--no-prepare-space", dest="prepare_space", action="store_false", help="Measure the current surface without preparing the space canvas.")
    parser.add_argument("--prepare-space-mode", choices=["adb", "native-control"], default="adb")
    parser.add_argument("--prepare-tap-x", type=int, default=36)
    parser.add_argument("--prepare-tap-y", type=int, default=108)
    parser.add_argument("--prepare-settle-sec", type=float, default=0.45)
    parser.add_argument("--target-panel", default="acceptance-shared", help="Panel/space id to prepare before canvas input proof.")
    parser.add_argument("--start-x", type=int, default=700)
    parser.add_argument("--start-y", type=int, default=1500)
    parser.add_argument("--end-x", type=int, default=700)
    parser.add_argument("--end-y", type=int, default=620)
    parser.add_argument("--max-high-input-latency", type=int, default=0)
    parser.add_argument("--max-slow-ui-thread", type=int, default=0)
    parser.add_argument("--max-slow-draw-commands", type=int, default=1)
    parser.add_argument("--max-frame-deadline-missed", type=int, default=1)
    parser.add_argument("--max-p95-ms", type=int, default=32)
    parser.add_argument("--max-janky-frames", type=int, default=3)
    parser.add_argument("--max-launch-total-ms", type=int, default=2500)
    parser.add_argument("--max-launch-wait-ms", type=int, default=3000)
    args = parser.parse_args()
    if args.launch_only and args.no_launch_first:
        parser.error("--launch-only requires the launch phase; remove --no-launch-first")

    rid = run_id("android-input-budget")
    artifacts = artifact_paths("android-input-budget", rid)
    state_dir = Path(args.state_dir)
    logs: list[str] = []
    started = time.monotonic()

    result: dict[str, Any] = {
        "status": "fail",
        "promiseId": "android-native-input-budget",
        "claim": "Android native canvas/navigation input stays inside the configured frame/input budget.",
        "runId": rid,
        "origin": args.origin,
        "packageName": args.package_name,
        "durationMs": None,
        "evidence": [artifacts["result"], artifacts["runResult"], artifacts["logs"]],
        "summary": "",
        "failureClass": None,
        "nextSuggestedSteps": [],
        "commands": [],
        "metrics": {},
        "budget": {
            "max_high_input_latency": args.max_high_input_latency,
            "max_slow_ui_thread": args.max_slow_ui_thread,
            "max_slow_draw_commands": args.max_slow_draw_commands,
            "max_frame_deadline_missed": args.max_frame_deadline_missed,
            "max_p95_ms": args.max_p95_ms,
            "max_janky_frames": args.max_janky_frames,
            "max_launch_total_ms": args.max_launch_total_ms,
            "max_launch_wait_ms": args.max_launch_wait_ms,
            "launch_only": bool(args.launch_only),
        },
    }

    try:
        clients = request_json("GET", f"{args.origin.rstrip()}/native/control/clients", timeout=8)
    except Exception as exc:
        result.update({
            "status": "blocked",
            "failureClass": "bridge_unreachable",
            "summary": f"Native-control backend was unreachable: {exc}",
            "nextSuggestedSteps": [next_action("bridge_unreachable")],
        })
        return finish(result, artifacts, logs, started, exit_code=2)

    client_list = clients.get("clients") if isinstance(clients.get("clients"), list) else []
    windows = choose_windows_client(client_list)
    windows_device_id = str(windows.get("device_id") or windows.get("heartbeat", {}).get("device_id") or "")
    if not windows_device_id:
        result.update({
            "status": "blocked",
            "failureClass": "bridge_unreachable",
            "summary": "No Windows native-control client was available.",
            "nextSuggestedSteps": [next_action("bridge_unreachable")],
        })
        return finish(result, artifacts, logs, started, exit_code=2)

    cleanup = cleanup_native_control_state(state_dir, windows_device_id, keep_recent=60, reason="android_input_budget")
    logs.append(json.dumps({"cleanup": cleanup}, sort_keys=True))

    sequence = []
    if not args.no_launch_first:
        launch_args = {
            "packageName": args.package_name,
            "stopFirst": bool(args.stop_first),
            "method": args.launch_method,
        }
        if args.launch_component.strip():
            launch_args["componentName"] = args.launch_component.strip()
        sequence.append(("launch", launch_args))
    if args.prepare_space and not args.launch_only:
        if args.prepare_space_mode == "native-control":
            sequence.append(("prepare_space", {}))
        else:
            sequence.append(("prepare_space_tap", {
                "x": args.prepare_tap_x,
                "y": args.prepare_tap_y,
            }))
    if not args.launch_only:
        sequence.extend([
            ("gfx_reset", {"packageName": args.package_name}),
            ("swipe", {
                "x1": args.start_x,
                "y1": args.start_y,
                "x2": args.end_x,
                "y2": args.end_y,
                "durationMs": args.gesture_duration_ms,
            }),
            ("gfxinfo", {"packageName": args.package_name}),
        ])

    for action, action_args in sequence:
        if action == "prepare_space":
            clients = request_json("GET", f"{args.origin.rstrip()}/native/control/clients", timeout=8)
            android_device_id = choose_android_client(clients.get("clients") if isinstance(clients.get("clients"), list) else [])
            if not android_device_id:
                result.update({
                    "status": "blocked",
                    "failureClass": "android_native_control_missing",
                    "summary": "No Android native-control client was available to prepare the canvas surface.",
                    "nextSuggestedSteps": ["Relaunch the Android app and wait for the native-control heartbeat before running the canvas budget proof."],
                })
                return finish(result, artifacts, logs, started, exit_code=2)
            command_id, _queued = queue_command(
                args.origin,
                android_device_id,
                "probe_space_switch_latency",
                {"targetPanel": args.target_panel, "return": False, "holdMs": 0, "settleMs": 120, "profileLimit": 8},
                f"{rid}-prepare-space",
                "prepare Android canvas input budget surface",
            )
            record = wait_for_result(state_dir, android_device_id, command_id, wait_sec=args.wait_sec, poll_sec=0.75)
            hot_result = unwrap_result(record) if record else {}
            classification = classify_roundtrip(state_dir, android_device_id, command_id, record)
            result["commands"].append({
                "action": action,
                "commandId": command_id,
                "classification": classification,
                "timeline": command_timeline(state_dir, android_device_id, command_id, record),
                "result": hot_result,
            })
            logs.append(json.dumps({"action": action, "classification": classification}, sort_keys=True))
            if classification != "pass" or hot_result.get("ok") is not True:
                result.update({
                    "status": "fail",
                    "failureClass": classification,
                    "summary": f"Android input budget proof failed during {action}: {classification}",
                    "nextSuggestedSteps": [next_action(classification)],
                })
                return finish(result, artifacts, logs, started, exit_code=1)
            time.sleep(max(0.0, min(5.0, args.launch_settle_sec / 2)))
            continue
        if action == "prepare_space_tap":
            command_id, record, hot_result = run_hot_op(
                origin=args.origin,
                state_dir=state_dir,
                windows_device_id=windows_device_id,
                rid=rid,
                action="tap",
                args=action_args,
                wait_sec=args.wait_sec,
            )
            classification = classify_roundtrip(state_dir, windows_device_id, command_id, record)
            timeline = command_timeline(state_dir, windows_device_id, command_id, record)
            result["commands"].append({
                "action": action,
                "commandId": command_id,
                "classification": classification,
                "timeline": timeline,
                "result": hot_result,
            })
            logs.append(json.dumps({"action": action, "classification": classification, "timeline": timeline}, sort_keys=True))
            if classification != "pass" or hot_result.get("ok") is not True:
                result.update({
                    "status": "fail",
                    "failureClass": classification,
                    "summary": f"Android input budget proof failed during {action}: {classification}",
                    "nextSuggestedSteps": [next_action(classification)],
                })
                return finish(result, artifacts, logs, started, exit_code=1)
            time.sleep(max(0.0, min(3.0, args.prepare_settle_sec)))
            continue

        command_id, record, hot_result = run_hot_op(
            origin=args.origin,
            state_dir=state_dir,
            windows_device_id=windows_device_id,
            rid=rid,
            action=action,
            args=action_args,
            wait_sec=args.wait_sec,
        )
        classification = classify_roundtrip(state_dir, windows_device_id, command_id, record)
        timeline = command_timeline(state_dir, windows_device_id, command_id, record)
        command_summary = {
            "action": action,
            "commandId": command_id,
            "classification": classification,
            "timeline": timeline,
            "result": hot_result,
        }
        result["commands"].append(command_summary)
        logs.append(json.dumps({"action": action, "classification": classification, "timeline": timeline}, sort_keys=True))
        if classification != "pass" or hot_result.get("ok") is not True:
            result.update({
                "status": "fail",
                "failureClass": classification,
                "summary": f"Android input budget proof failed during {action}: {classification}",
                "nextSuggestedSteps": [next_action(classification)],
            })
            return finish(result, artifacts, logs, started, exit_code=1)
        if action == "launch" and args.launch_settle_sec > 0:
            time.sleep(args.launch_settle_sec)
            if args.prepare_space and args.prepare_space_mode == "native-control":
                ready, reason = wait_for_android_ux_ready(
                    origin=args.origin,
                    state_dir=state_dir,
                    rid=rid,
                    wait_sec=args.wait_sec,
                    ready_wait_sec=args.launch_ready_wait_sec,
                    result=result,
                    logs=logs,
                )
                if not ready:
                    result.update({
                        "status": "blocked",
                        "failureClass": "android_native_ui_not_ready",
                        "summary": f"Android native UI did not reach the pre-prepare readiness gate: {reason}",
                        "nextSuggestedSteps": ["Inspect androidNativePrePrepareReady and the last pre_prepare_ready command before rerunning the input budget proof."],
                    })
                    return finish(result, artifacts, logs, started, exit_code=2)

    launch_metrics: dict[str, Any] = {}
    for command in result["commands"]:
        if command.get("action") != "launch":
            continue
        launch_payload = nested_result(command.get("result") or {})
        launch_info = launch_payload.get("launch") if isinstance(launch_payload.get("launch"), dict) else {}
        launch_metrics = parse_launch_timing(str(launch_info.get("stdout") or ""))
        launch_metrics["launch_hot_op_elapsed_ms"] = launch_info.get("elapsedMs")
        launch_metrics["launch_component"] = launch_payload.get("componentName") or ""
        launch_metrics["launch_method"] = launch_payload.get("method") or ""
        break

    if args.launch_only:
        metrics = {}
    else:
        gfx_payload = nested_result(result["commands"][-1].get("result") or {})
        gfx_text = str(gfx_payload.get("gfxinfo") or "")
        metrics = parse_gfxinfo(gfx_text)
    metrics.update(launch_metrics)
    ok, failures = budget_pass(metrics, args)
    result["metrics"] = metrics
    if args.launch_only:
        if ok:
            result.update({
                "status": "pass",
                "failureClass": None,
                "summary": "Android native launch budget passed without synthetic ADB input.",
                "nextSuggestedSteps": [],
            })
            return finish(result, artifacts, logs, started, exit_code=0)
        result.update({
            "status": "fail",
            "failureClass": "android_launch_budget_exceeded",
            "summary": "Android native launch budget exceeded: " + "; ".join(failures),
            "nextSuggestedSteps": [
                "Inspect the launch command timing before dispatching any ADB swipe or gfxinfo proof.",
            ],
        })
        return finish(result, artifacts, logs, started, exit_code=1)
    if metrics.get("total_frames") == 0:
        summary_id, summary_record, summary_result = run_hot_op(
            origin=args.origin,
            state_dir=state_dir,
            windows_device_id=windows_device_id,
            rid=rid,
            action="foreground_summary",
            args={"packageName": args.package_name},
            wait_sec=args.wait_sec,
        )
        summary_classification = classify_roundtrip(state_dir, windows_device_id, summary_id, summary_record)
        summary_command = {
            "action": "foreground_summary",
            "commandId": summary_id,
            "classification": summary_classification,
            "timeline": command_timeline(state_dir, windows_device_id, summary_id, summary_record),
            "result": summary_result,
        }
        result["commands"].append(summary_command)
        result["foregroundSummary"] = nested_result(summary_result)
        logs.append(json.dumps({
            "action": "foreground_summary",
            "classification": summary_classification,
            "timeline": summary_command["timeline"],
        }, sort_keys=True))
        result.update({
            "status": "inconclusive",
            "failureClass": "android_input_no_rendered_frames",
            "summary": "Android input proof dispatched the gesture, but gfxinfo reported zero rendered frames after reset.",
            "nextSuggestedSteps": [
                "Launch or foreground the app, verify the current screen is scrollable, then rerun the budget proof with coordinates that force WebView drawing.",
            ],
        })
        return finish(result, artifacts, logs, started, exit_code=3)
    if ok:
        result.update({
            "status": "pass",
            "failureClass": None,
            "summary": "Android native input budget passed after a real ADB swipe.",
            "nextSuggestedSteps": [],
        })
        return finish(result, artifacts, logs, started, exit_code=0)
    collect_android_ux_report(
        origin=args.origin,
        state_dir=state_dir,
        rid=rid,
        wait_sec=args.wait_sec,
        result=result,
        logs=logs,
        reason="input_budget_exceeded",
    )
    result.update({
        "status": "fail",
        "failureClass": "android_input_budget_exceeded",
        "summary": "Android native input budget exceeded: " + "; ".join(failures),
        "nextSuggestedSteps": [
            "Use the gfxinfo failure fields to choose the next simplification: draw-command/frame-deadline failures point to paint/layout work, while high input latency points to event/main-thread pressure.",
        ],
    })
    return finish(result, artifacts, logs, started, exit_code=1)


def finish(result: dict[str, Any], artifacts: dict[str, str], logs: list[str], started: float, *, exit_code: int) -> int:
    result["durationMs"] = round((time.monotonic() - started) * 1000)
    write_json(Path(artifacts["result"]), result)
    write_json(Path(artifacts["runResult"]), result)
    Path(artifacts["logs"]).write_text("\n".join(logs) + ("\n" if logs else ""), encoding="utf-8")
    Path(artifacts["runLogs"]).write_text("\n".join(logs) + ("\n" if logs else ""), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
