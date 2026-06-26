#!/usr/bin/env python3
"""Prove Android rebuilds run the UX performance regression gate."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "reports/android/rebuild-guard/latest"
REPORT_PATH = REPORT_DIR / "android-ux-rebuild-gate.json"
GRADLE = ROOT / "native/android/.gradle-dist/gradle-8.9/bin/gradle"
BUILD_FILE = ROOT / "native/android/app/build.gradle"
TEST_FILE = ROOT / "plugins/wasm-agent/tests/android_lite_performance_budget.test.js"
INPUT_BUDGET_FILE = ROOT / "tools/android/prove-android-input-budget.py"
RELEASE_LOOP_FILE = ROOT / "tools/android/prove-android-native-ux-release-loop.py"
MANIFEST_FILE = ROOT / "native/android/app/src/main/AndroidManifest.xml"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_report(report: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    started = time.monotonic()
    build_gradle = read_text(BUILD_FILE)
    test_source = read_text(TEST_FILE)
    input_budget_source = read_text(INPUT_BUDGET_FILE)
    release_loop_source = read_text(RELEASE_LOOP_FILE)
    manifest_source = read_text(MANIFEST_FILE)
    static_checks = {
        "gradle_task_declared": "verifyAndroidUxPerformanceRegression" in build_gradle,
        "prebuild_depends_on_guard": 'dependsOn("verifyAndroidUxPerformanceRegression")' in build_gradle,
        "node_guard_command_declared": "plugins/wasm-agent/tests/android_lite_performance_budget.test.js" in build_gradle,
        "shell_v2_line_budgets": "MAX_SHELL_V2_ACTIVITY_LINES" in test_source
        and "MAX_SHELL_V2_BRIDGE_LINES" in test_source,
        "shell_v2_forbidden_startup_pattern": "SHELL_V2_FORBIDDEN_STARTUP_PATTERN" in test_source,
        "shell_v2_launcher_guard": "manifestActivityBlock" in test_source
        and "Android shell v2 must own the installed launcher" in test_source
        and 'android:name=".shell.NativeShellV2Activity"' in manifest_source
        and manifest_source.count("android.intent.action.MAIN") == 1
        and manifest_source.count("android.intent.category.LAUNCHER") == 1,
        "input_budget_launch_timing": "def parse_launch_timing" in input_budget_source
        and "--max-launch-total-ms" in input_budget_source
        and "--launch-only" in input_budget_source
        and "launch_total_time_ms" in input_budget_source,
        "release_loop_skip_build_reuses_feed": "elif args.publish_feed and not args.skip_publish_feed:" in release_loop_source
        and "elif not args.skip_publish_feed:" not in release_loop_source
        and '"reuse_existing_native_release_feed"' in release_loop_source,
        "release_loop_strict_install_acceptance": "phase = android_hot_op_install_phase(" in release_loop_source
        and '"acceptedForUxLoop": bool(phase.get("acceptedForUxLoop"))' in release_loop_source
        and 'phase["ok"] or install_phase_usable' not in release_loop_source,
        "release_loop_shell_v2_path": 'SHELL_V2_COMPONENT = "com.colmeio.wasmagent/.shell.NativeShellV2Activity"' in release_loop_source
        and 'parser.add_argument("--shell-v2"' in release_loop_source
        and 'parser.add_argument("--run-shell-v2-adb-proof"' in release_loop_source
        and '"shell_v2_adb_relaunch_proof_skipped"' in release_loop_source
        and '"--launch-only", "--no-stop-first"' in release_loop_source
        and '"install_android_apk_via_windows_ui_input_hot_op"' in release_loop_source
        and '"fresh_ui_input_hot_op_install"' in release_loop_source
        and '"tools/voice/reinstall-android-via-windows-bridge.py"' not in release_loop_source
        and "interrupted_by_user" in release_loop_source
        and '"interrupted": True' in release_loop_source
        and '"android_ui_input_hot_op_feed_stale"' in release_loop_source,
    }

    cmd = [str(GRADLE), "--no-daemon", ":app:preBuild"]
    result = subprocess.run(
        cmd,
        cwd=ROOT / "native/android",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
        check=False,
    )
    output = result.stdout or ""
    guard_executed = "> Task :app:verifyAndroidUxPerformanceRegression" in output
    guard_passed = "android lite performance budget ok" in output
    ok = result.returncode == 0 and all(static_checks.values()) and guard_executed and guard_passed
    report = {
        "status": "pass" if ok else "fail",
        "promiseId": "android-ux-rebuild-gate",
        "claim": "Android Gradle rebuilds run the UX performance regression guard before build work proceeds.",
        "checkedAt": utc_now(),
        "durationMs": round((time.monotonic() - started) * 1000),
        "command": cmd,
        "exitCode": result.returncode,
        "staticChecks": static_checks,
        "guardExecuted": guard_executed,
        "guardPassed": guard_passed,
        "evidence": [str(REPORT_PATH.relative_to(ROOT))],
        "summary": "Android UX rebuild gate passed" if ok else "Android UX rebuild gate failed",
        "failureClass": None if ok else "android_ux_rebuild_gate_failed",
        "stdoutTail": output[-6000:],
    }
    write_report(report)
    print(json.dumps({
        "status": report["status"],
        "promiseId": report["promiseId"],
        "summary": report["summary"],
        "failureClass": report["failureClass"],
        "evidence": report["evidence"],
    }, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.TimeoutExpired as exc:
        report = {
            "status": "fail",
            "promiseId": "android-ux-rebuild-gate",
            "claim": "Android Gradle rebuilds run the UX performance regression guard before build work proceeds.",
            "checkedAt": utc_now(),
            "durationMs": None,
            "command": exc.cmd,
            "exitCode": None,
            "staticChecks": {},
            "guardExecuted": False,
            "guardPassed": False,
            "evidence": [str(REPORT_PATH.relative_to(ROOT))],
            "summary": "Android UX rebuild gate timed out",
            "failureClass": "android_ux_rebuild_gate_timeout",
            "stdoutTail": (exc.stdout or "")[-6000:] if isinstance(exc.stdout, str) else "",
        }
        write_report(report)
        print(json.dumps({
            "status": report["status"],
            "promiseId": report["promiseId"],
            "summary": report["summary"],
            "failureClass": report["failureClass"],
            "evidence": report["evidence"],
        }, indent=2))
        raise SystemExit(1)
    except Exception as exc:  # noqa: BLE001 - compact failure report for harness use.
        report = {
            "status": "fail",
            "promiseId": "android-ux-rebuild-gate",
            "claim": "Android Gradle rebuilds run the UX performance regression guard before build work proceeds.",
            "checkedAt": utc_now(),
            "durationMs": None,
            "command": [],
            "exitCode": None,
            "staticChecks": {},
            "guardExecuted": False,
            "guardPassed": False,
            "evidence": [str(REPORT_PATH.relative_to(ROOT))],
            "summary": f"Android UX rebuild gate check crashed: {exc.__class__.__name__}",
            "failureClass": "android_ux_rebuild_gate_checker_error",
            "stdoutTail": str(exc),
        }
        write_report(report)
        print(json.dumps({
            "status": report["status"],
            "promiseId": report["promiseId"],
            "summary": report["summary"],
            "failureClass": report["failureClass"],
            "evidence": report["evidence"],
        }, indent=2))
        raise SystemExit(1)
