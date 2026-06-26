#!/usr/bin/env python3
"""Run the deterministic Android native UX build/install/proof loop.

This script exists to prevent repeated manual rebuild/reinstall/proof loops.
It composes the existing release, Windows bridge, Android reinstall, and input
budget harnesses into one command and one aggregate report.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "windows"))

from hot_shell_common import (  # noqa: E402
    choose_windows_client,
    classify_roundtrip,
    command_timeline,
    queue_command,
    request_json,
    run_id as hot_run_id,
    unwrap_result,
    wait_for_result,
)

DEFAULT_ORIGIN = "http://127.0.0.1:8877"
REPORT_ROOT = ROOT / "reports" / "android" / "responsiveness"
SHELL_V2_COMPONENT = "com.colmeio.wasmagent/.shell.NativeShellV2Activity"
UI_INPUT_PROOF_SOURCE = ROOT / "native" / "windows" / "ops" / "android" / "android-ui-input-proof.js"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def tail_text(value: str, limit: int = 120_000) -> str:
    if len(value) <= limit:
        return value
    return value[-limit:]


def extract_last_json(text: str) -> dict[str, Any]:
    starts = [index for index, char in enumerate(text) if char == "{"]
    for index in reversed(starts):
        candidate = text[index:].strip()
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def run_streamed(
    label: str,
    cmd: list[str],
    *,
    env: dict[str, str] | None = None,
    log_path: Path,
) -> dict[str, Any]:
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_parts: list[str] = []
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(cmd) + "\n")
        process = subprocess.Popen(
            cmd,
            cwd=ROOT,
            env=merged_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        try:
            for line in process.stdout:
                print(line, end="")
                log.write(line)
                stdout_parts.append(line)
            exit_code = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try:
                exit_code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                exit_code = process.wait()
            message = "\ninterrupted_by_user\n"
            print(message, end="")
            log.write(message)
            stdout_parts.append(message)
            duration_ms = round((time.monotonic() - started) * 1000)
            output = "".join(stdout_parts)
            return {
                "label": label,
                "command": cmd,
                "exitCode": 130 if exit_code == 0 else exit_code,
                "ok": False,
                "interrupted": True,
                "startedAt": started_at,
                "durationMs": duration_ms,
                "log": str(log_path.relative_to(ROOT)),
                "parsedJson": extract_last_json(output),
                "outputTail": tail_text(output),
            }
    duration_ms = round((time.monotonic() - started) * 1000)
    output = "".join(stdout_parts)
    return {
        "label": label,
        "command": cmd,
        "exitCode": exit_code,
        "ok": exit_code == 0,
        "startedAt": started_at,
        "durationMs": duration_ms,
        "log": str(log_path.relative_to(ROOT)),
        "parsedJson": extract_last_json(output),
        "outputTail": tail_text(output),
    }


def read_json(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def release_metadata() -> dict[str, Any]:
    feed = read_json(ROOT / "plugins" / "wasm-agent" / "public" / "native" / "releases" / "latest.json")
    artifacts = feed.get("artifacts") if isinstance(feed.get("artifacts"), dict) else {}
    android = artifacts.get("android") if isinstance(artifacts.get("android"), dict) else {}
    arm64 = android.get("arm64") if isinstance(android.get("arm64"), dict) else {}
    apk = ROOT / "native" / "android" / "release" / "WASM-Agent-arm64.apk"
    return {
        "apk": str(apk.relative_to(ROOT)),
        "apkExists": apk.exists(),
        "buildId": arm64.get("buildId") or "",
        "sha256": arm64.get("sha256") or "",
        "sizeBytes": arm64.get("sizeBytes") or arm64.get("size") or 0,
        "url": arm64.get("url") or "/native/releases/android/WASM-Agent-arm64.apk",
    }


def sha256_file(path: Path) -> str:
    import hashlib

    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hot_op_metadata() -> dict[str, Any]:
    feed = read_json(ROOT / "plugins" / "wasm-agent" / "public" / "native" / "releases" / "latest.json")
    artifacts = feed.get("artifacts") if isinstance(feed.get("artifacts"), dict) else {}
    hot_ops = artifacts.get("hotOps") if isinstance(artifacts.get("hotOps"), dict) else {}
    android = hot_ops.get("android") if isinstance(hot_ops.get("android"), dict) else {}
    ui_input = android.get("uiInputProof") if isinstance(android.get("uiInputProof"), dict) else {}
    files = ui_input.get("files") if isinstance(ui_input.get("files"), list) else []
    feed_module_sha = ""
    for item in files:
        if not isinstance(item, dict):
            continue
        if item.get("filename") == "android-ui-input-proof.js":
            feed_module_sha = str(item.get("sha256") or "")
            break
    source_sha = sha256_file(UI_INPUT_PROOF_SOURCE)
    return {
        "uiInputProofSourceSha256": source_sha,
        "uiInputProofFeedSha256": feed_module_sha,
        "uiInputProofFeedMatchesSource": bool(source_sha and feed_module_sha and source_sha == feed_module_sha),
        "uiInputProofBundleId": ui_input.get("bundleId") or ui_input.get("id") or "",
        "uiInputProofBundleSha": ui_input.get("bundleSha") or "",
    }


def backend_ready(origin: str, timeout: float = 2.5) -> tuple[bool, str]:
    url = origin.rstrip("/") + "/native/control/clients"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read()
        parsed = json.loads(body.decode("utf-8"))
    except Exception as exc:
        return False, f"{exc.__class__.__name__}: {exc}"
    if isinstance(parsed, dict) and isinstance(parsed.get("clients"), list):
        return True, f"clients={len(parsed['clients'])}"
    return False, "native-control clients response missing clients list"


def wait_backend_ready(origin: str, timeout_sec: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    attempts = 0
    last = ""
    while time.monotonic() < deadline:
        attempts += 1
        ok, detail = backend_ready(origin)
        last = detail
        if ok:
            return {
                "label": "wait_local_wasm_agent_backend",
                "command": ["GET", origin.rstrip("/") + "/native/control/clients"],
                "exitCode": 0,
                "ok": True,
                "durationMs": None,
                "attempts": attempts,
                "detail": detail,
                "parsedJson": {},
                "outputTail": detail,
            }
        time.sleep(0.75)
    return {
        "label": "wait_local_wasm_agent_backend",
        "command": ["GET", origin.rstrip("/") + "/native/control/clients"],
        "exitCode": 1,
        "ok": False,
        "durationMs": None,
        "attempts": attempts,
        "detail": last,
        "parsedJson": {},
        "outputTail": last,
    }


def phase_status(phase: dict[str, Any]) -> str:
    if phase.get("ok") is True:
        return "pass"
    parsed = phase.get("parsedJson") if isinstance(phase.get("parsedJson"), dict) else {}
    for key in ("failureClass", "failureClassification", "classification", "handlerClassification", "roundtrip", "status"):
        if parsed.get(key):
            return str(parsed.get(key))
    return "failed"


def install_phase_usable(phase: dict[str, Any], release: dict[str, Any]) -> bool:
    parsed = phase.get("parsedJson") if isinstance(phase.get("parsedJson"), dict) else {}
    apk = parsed.get("apk") if isinstance(parsed.get("apk"), dict) else {}
    if phase.get("label") == "install_android_apk_via_windows_ui_input_hot_op":
        return bool(
            parsed.get("installAccepted") is True
            and apk.get("ok") is True
            and str(apk.get("buildId") or "") == str(release.get("buildId") or "")
            and str(apk.get("sha256") or "").lower() == str(release.get("sha256") or "").lower()
        )
    seen = parsed.get("androidBuildSeen") if isinstance(parsed.get("androidBuildSeen"), dict) else {}
    diagnostics = seen.get("diagnostics") if isinstance(seen.get("diagnostics"), dict) else {}
    expected_build = str(release.get("buildId") or "")
    expected_sha = str(release.get("sha256") or "").lower()
    build_values = {
        str(apk.get("buildId") or ""),
        str(diagnostics.get("android_build_id") or ""),
    }
    sha_values = {
        str(apk.get("sha256") or "").lower(),
        str(apk.get("expectedSha256") or "").lower(),
    }
    return bool(
        apk.get("ok") is True
        and seen.get("ok") is True
        and expected_build
        and expected_build in build_values
        and expected_sha
        and expected_sha in sha_values
    )


def reused_install_phase(path: Path, release: dict[str, Any]) -> dict[str, Any]:
    report = read_json(path)
    phases = report.get("phases") if isinstance(report.get("phases"), list) else []
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        if phase.get("label") not in {"install_android_apk_via_windows_bridge", "install_android_apk_via_windows_ui_input_hot_op"}:
            continue
        reused = dict(phase)
        reused["label"] = "reuse_install_report"
        reused["reusedFrom"] = str(path)
        reused["ok"] = install_phase_usable(reused, release)
        reused["acceptedForUxLoop"] = reused["ok"]
        return reused
    return {
        "label": "reuse_install_report",
        "reusedFrom": str(path),
        "ok": False,
        "acceptedForUxLoop": False,
        "parsedJson": {},
        "outputTail": "No install_android_apk_via_windows_bridge phase was found in the reused report.",
    }


def nested_payload(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("rawResult", "result"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload


def android_hot_op_install_phase(origin: str, state_dir: Path, wait_sec: int, release: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    command = ["native-control", "run_hot_operation", "run_android_ui_input_proof", "install_apk"]
    try:
        clients = request_json("GET", f"{origin.rstrip()}/native/control/clients", timeout=8)
        client = choose_windows_client(clients.get("clients", []) if isinstance(clients.get("clients"), list) else [])
        if not client:
            raise RuntimeError("No Windows native client heartbeat found.")
        heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
        device_id = str(client.get("device_id") or heartbeat.get("device_id") or "")
        if not device_id:
            raise RuntimeError("Windows native client id missing.")
        rid = hot_run_id("android-shell-v2-install")
        payload = {
            "operationName": "run_android_ui_input_proof",
            "args": {"action": "install_apk"},
        }
        command_id, queued = queue_command(
            origin.rstrip(),
            device_id,
            "run_hot_operation",
            payload,
            rid,
            "Android APK install without post-install relaunch",
        )
        record = wait_for_result(state_dir, device_id, command_id, wait_sec=wait_sec, poll_sec=0.75)
        result = unwrap_result(record) if record else {}
        raw = nested_payload(result)
        apk = raw.get("apk") if isinstance(raw.get("apk"), dict) else {}
        roundtrip = classify_roundtrip(state_dir, device_id, command_id, record)
        expected_build = str(release.get("buildId") or "")
        expected_sha = str(release.get("sha256") or "").lower()
        ok = bool(
            roundtrip == "pass"
            and raw.get("ok") is True
            and apk.get("ok") is True
            and expected_build
            and str(apk.get("buildId") or "") == expected_build
            and expected_sha
            and str(apk.get("sha256") or "").lower() == expected_sha
        )
        return {
            "label": "install_android_apk_via_windows_ui_input_hot_op",
            "command": command,
            "exitCode": 0 if ok else 1,
            "ok": ok,
            "acceptedForUxLoop": ok,
            "durationMs": round((time.monotonic() - started) * 1000),
            "commandId": command_id,
            "queued": queued,
            "roundtrip": roundtrip,
            "timeline": command_timeline(state_dir, device_id, command_id, record),
            "parsedJson": {
                "ok": ok,
                "installAccepted": ok,
                "apk": apk,
                "rawResult": raw,
                "hotOperation": {
                    "hotOpSha": result.get("hotOpSha"),
                    "bundleId": result.get("bundleId"),
                    "hotOpSource": result.get("hotOpSource"),
                },
            },
            "outputTail": json.dumps({"ok": ok, "roundtrip": roundtrip, "apk": apk}, sort_keys=True),
        }
    except Exception as exc:  # noqa: BLE001 - compact phase failure for aggregate report.
        return {
            "label": "install_android_apk_via_windows_ui_input_hot_op",
            "command": command,
            "exitCode": 1,
            "ok": False,
            "acceptedForUxLoop": False,
            "durationMs": round((time.monotonic() - started) * 1000),
            "parsedJson": {
                "ok": False,
                "failureClass": "shell_v2_install_hot_op_failed",
                "error": exc.__class__.__name__,
                "message": str(exc),
            },
            "outputTail": f"{exc.__class__.__name__}: {exc}",
        }


def finish(report: dict[str, Any], report_path: Path) -> int:
    latest_path = REPORT_ROOT / "latest-android-native-ux-release-loop.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report["finishedAt"] = datetime.now(timezone.utc).isoformat()
    report["durationMs"] = round((time.monotonic() - report["_startedMonotonic"]) * 1000)
    report.pop("_startedMonotonic", None)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--wait-sec", type=int, default=180)
    parser.add_argument("--proof-wait-ms", type=int, default=8000)
    parser.add_argument("--skip-start-backend", action="store_true", help="Assume the local wasm-agent backend is already running.")
    parser.add_argument("--skip-build", action="store_true", help="Use the existing promoted APK/feed instead of rebuilding.")
    parser.add_argument("--publish-feed", action="store_true", help="Refresh the release feed when --skip-build is used. This can invalidate reused install proof if APK metadata changes.")
    parser.add_argument("--skip-publish-feed", action="store_true", help="Compatibility no-op: --skip-build now reuses the existing feed unless --publish-feed is set.")
    parser.add_argument("--skip-hot-shell", action="store_true", help="Skip the Windows hot-shell preflight.")
    parser.add_argument("--skip-install", action="store_true", help="Skip APK install and only run the runtime proof against the installed app.")
    parser.add_argument("--reuse-install-report", default="", help="Reuse a previous aggregate report's matching install phase instead of reinstalling.")
    parser.add_argument("--skip-input-budget", action="store_true", help="Stop after package install; report remains runtime-incomplete.")
    parser.add_argument("--input-budget-extra", action="append", default=[], help="Extra argument passed to prove-android-input-budget.py. Can be repeated.")
    parser.add_argument("--launch-component", default="", help="Explicit Android component passed to the input-budget launch phase.")
    parser.add_argument("--shell-v2", action="store_true", help="Launch the clean shell v2 Activity explicitly and skip legacy canvas preparation unless overridden.")
    parser.add_argument("--run-shell-v2-adb-proof", action="store_true", help="After shell-v2 install, explicitly run the ADB launch-only proof. Default shell-v2 mode stops after install to avoid a second ADB relaunch/input pass.")
    parser.add_argument("--prepare-space", dest="prepare_space", action="store_true", default=None, help="Prepare the canvas surface before measuring input.")
    parser.add_argument("--no-prepare-space", dest="prepare_space", action="store_false", help="Measure the launched surface without the legacy canvas preparation step.")
    args = parser.parse_args()
    launch_component = args.launch_component.strip() or (SHELL_V2_COMPONENT if args.shell_v2 else "")
    prepare_space = args.prepare_space
    if prepare_space is None:
        prepare_space = not args.shell_v2

    stamp = utc_stamp()
    run_id = f"android-native-ux-release-loop-{stamp}"
    run_dir = REPORT_ROOT / "runs" / run_id
    report_path = REPORT_ROOT / f"{stamp}-android-native-ux-release-loop.json"
    report: dict[str, Any] = {
        "_startedMonotonic": time.monotonic(),
        "schema": "hermes.wasm_agent.android_native_ux_release_loop.v1",
        "status": "running",
        "exitCode": 1,
        "failureClass": "",
        "summary": "",
        "runId": run_id,
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "origin": args.origin,
        "reportPath": str(report_path.relative_to(ROOT)),
        "repeatGuard": {
            "purpose": "Replace manual repeated rebuild/reinstall/proof loops with one deterministic command.",
            "manualLoopToAvoid": [
                "plugins/wasm-agent/scripts/start_wasm_agent.sh",
                "horc build android-fast",
                "horc build android-apk",
                "reinstall Android APK through Windows bridge",
                "prove Android input budget",
            ],
            "useSkipBuildWhen": "The promoted APK/feed already contains the source change being tested.",
        },
        "release": release_metadata(),
        "hotOps": hot_op_metadata(),
        "target": {
            "shellV2": bool(args.shell_v2),
            "launchComponent": launch_component,
            "prepareSpace": bool(prepare_space),
        },
        "skipBuildPolicy": {
            "skipBuild": bool(args.skip_build),
            "publishFeedRequested": bool(args.publish_feed),
            "skipPublishFeedRequested": bool(args.skip_publish_feed),
            "effectiveFeedAction": "pending",
        },
        "phases": [],
    }

    def add_phase(label: str, cmd: list[str], *, env: dict[str, str] | None = None) -> dict[str, Any]:
        phase = run_streamed(label, cmd, env=env, log_path=run_dir / f"{len(report['phases']) + 1:02d}-{label}.log")
        report["phases"].append(phase)
        report["release"] = release_metadata()
        return phase

    if not args.skip_start_backend:
        phase = add_phase(
            "start_local_wasm_agent_backend",
            ["bash", "plugins/wasm-agent/scripts/start_wasm_agent.sh"],
            env={"HERMES_WASM_AGENT_HOST": "127.0.0.1"},
        )
        if not phase["ok"]:
            report.update({
                "status": "blocked",
                "exitCode": 2,
                "failureClass": phase_status(phase),
                "summary": "Local wasm-agent backend startup failed before Android release-loop proof.",
            })
            return finish(report, report_path)
        backend_phase = wait_backend_ready(args.origin)
        report["phases"].append(backend_phase)
        if not backend_phase["ok"]:
            report.update({
                "status": "blocked",
                "exitCode": 2,
                "failureClass": "local_backend_unreachable_after_start",
                "summary": "Local wasm-agent backend start command returned but native-control clients never became reachable.",
            })
            return finish(report, report_path)

    if not args.skip_build:
        report["skipBuildPolicy"]["effectiveFeedAction"] = "build_android_apk"
        phase = add_phase(
            "build_android_apk",
            ["horc", "build", "android-apk"],
            env={"HORC_ANDROID_BUILD_MODE": "auto"},
        )
        if not phase["ok"]:
            report.update({
                "status": "fail",
                "exitCode": 1,
                "failureClass": phase_status(phase),
                "summary": "Android release APK build failed; no install/runtime claim was made.",
            })
            return finish(report, report_path)
    elif args.publish_feed and not args.skip_publish_feed:
        report["skipBuildPolicy"]["effectiveFeedAction"] = "publish_native_release_feed"
        phase = add_phase("publish_native_release_feed", ["node", "plugins/wasm-agent/scripts/generate-native-release-feed.js"])
        if not phase["ok"]:
            report.update({
                "status": "fail",
                "exitCode": 1,
                "failureClass": phase_status(phase),
                "summary": "Native release feed refresh failed before install/runtime proof.",
            })
            return finish(report, report_path)
    else:
        reason = "--skip-publish-feed overrode --publish-feed" if args.publish_feed else "--skip-build reused the existing native release feed"
        report["skipBuildPolicy"]["effectiveFeedAction"] = "reuse_existing_native_release_feed"
        report["phases"].append({
            "label": "reuse_existing_native_release_feed",
            "command": [],
            "exitCode": 0,
            "ok": True,
            "durationMs": 0,
            "detail": reason,
            "parsedJson": {},
            "outputTail": reason,
        })

    release = release_metadata()
    report["release"] = release
    report["hotOps"] = hot_op_metadata()
    if not release["apkExists"] or not release["sha256"] or not release["sizeBytes"]:
        report.update({
            "status": "blocked",
            "exitCode": 2,
            "failureClass": "android_release_artifact_missing",
            "summary": "Promoted Android APK/feed metadata is missing; run without --skip-build.",
        })
        return finish(report, report_path)
    if args.shell_v2 and not report["hotOps"].get("uiInputProofFeedMatchesSource"):
        report.update({
            "status": "blocked",
            "exitCode": 2,
            "failureClass": "android_ui_input_hot_op_feed_stale",
            "summary": "Shell v2 proof requires the release feed to publish the current Android input-proof hot-op with component launch support.",
        })
        return finish(report, report_path)

    if not args.skip_hot_shell:
        phase = add_phase("windows_hot_shell", ["python3", "tools/windows/prove-hot-shell.py", "--wait-sec", str(args.wait_sec)])
        if not phase["ok"]:
            report.update({
                "status": "blocked",
                "exitCode": 2,
                "failureClass": phase_status(phase),
                "summary": "Windows hot-shell preflight failed; Android bridge install/proof was not attempted.",
            })
            return finish(report, report_path)

    if args.reuse_install_report:
        phase = reused_install_phase(Path(args.reuse_install_report), release)
        report["phases"].append(phase)
        report["installProof"] = {
            "source": "reused_report",
            "acceptedForUxLoop": install_phase_usable(phase, release),
            "report": args.reuse_install_report,
            "parsed": phase.get("parsedJson", {}),
        }
        if not report["installProof"]["acceptedForUxLoop"]:
            report.update({
                "status": "blocked",
                "exitCode": 2,
                "failureClass": "reused_install_report_not_matching_release",
                "summary": "The reused install report did not prove the current promoted Android build and SHA.",
            })
            return finish(report, report_path)
    elif not args.skip_install:
        phase = android_hot_op_install_phase(args.origin, ROOT / "plugins/wasm-agent/state", args.wait_sec, release)
        report["phases"].append(phase)
        report["installProof"] = {
            "source": "fresh_ui_input_hot_op_install",
            "acceptedForUxLoop": bool(phase.get("acceptedForUxLoop")),
            "parsed": phase.get("parsedJson", {}),
        }
        if not phase.get("acceptedForUxLoop"):
            report.update({
                "status": "fail",
                "exitCode": 1,
                "failureClass": phase_status(phase),
                "summary": "Android APK install through the Windows UI input hot-op failed.",
            })
            return finish(report, report_path)

    if args.skip_input_budget:
        report.update({
            "status": "incomplete",
            "exitCode": 3,
            "failureClass": "runtime_input_budget_not_run",
            "summary": "Build/install lane completed, but Android input-budget runtime proof was skipped.",
        })
        return finish(report, report_path)
    if args.shell_v2 and not args.run_shell_v2_adb_proof:
        report.update({
            "status": "needs-human-proof",
            "exitCode": 3,
            "failureClass": "shell_v2_adb_relaunch_proof_skipped",
            "summary": "Shell v2 build/install proof completed; second ADB relaunch/input proof was skipped to avoid freezing or changing the visible app state.",
            "nextSuggestedSteps": [
                "Inspect the already-open Android app manually or run with --run-shell-v2-adb-proof only when an explicit ADB relaunch is acceptable.",
            ],
        })
        return finish(report, report_path)

    input_cmd = [
        "python3",
        "tools/android/prove-android-input-budget.py",
        "--origin",
        args.origin,
        "--wait-sec",
        str(args.wait_sec),
    ]
    if launch_component:
        input_cmd.extend(["--launch-component", launch_component])
    if not prepare_space:
        input_cmd.append("--no-prepare-space")
    if args.shell_v2:
        input_cmd.extend(["--launch-only", "--no-stop-first", "--max-launch-total-ms", "1500", "--max-launch-wait-ms", "1800"])
    input_cmd.extend(args.input_budget_extra)
    phase = add_phase("android_input_budget", input_cmd)
    parsed = phase.get("parsedJson") if isinstance(phase.get("parsedJson"), dict) else {}
    report["inputBudget"] = {
        "status": parsed.get("status", ""),
        "failureClass": parsed.get("failureClass"),
        "summary": parsed.get("summary", ""),
        "metrics": parsed.get("metrics", {}),
        "evidence": parsed.get("evidence", []),
    }
    if phase["ok"] and parsed.get("status") == "pass":
        report.update({
            "status": "pass",
            "exitCode": 0,
            "failureClass": "",
            "summary": "Android native UX release loop passed: build/feed, bridge install, and input budget all passed.",
        })
        return finish(report, report_path)

    report.update({
        "status": "fail",
        "exitCode": 1,
        "failureClass": str(parsed.get("failureClass") or phase_status(phase)),
        "summary": str(parsed.get("summary") or "Android input-budget proof failed after build/install loop."),
    })
    return finish(report, report_path)


if __name__ == "__main__":
    raise SystemExit(main())
