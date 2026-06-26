#!/usr/bin/env python3
"""Read passive Android native UX evidence without ADB or device commands."""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "plugins/wasm-agent/state"
DIAGNOSTICS_DIR = STATE_DIR / "native-diagnostics"
RELEASE_FEED = ROOT / "plugins/wasm-agent/public/native/releases/latest.json"
REPORT_DIR = ROOT / "reports/android/responsiveness"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_json(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def release_metadata() -> dict[str, Any]:
    feed = read_json(RELEASE_FEED)
    artifacts = feed.get("artifacts") if isinstance(feed.get("artifacts"), dict) else {}
    android = artifacts.get("android") if isinstance(artifacts.get("android"), dict) else {}
    arm64 = android.get("arm64") if isinstance(android.get("arm64"), dict) else {}
    return {
        "buildId": arm64.get("buildId") or "",
        "sha256": arm64.get("sha256") or "",
        "sizeBytes": arm64.get("sizeBytes") or arm64.get("size") or 0,
        "url": arm64.get("url") or "",
    }


def payload_of(diagnostic: dict[str, Any]) -> dict[str, Any]:
    payload = diagnostic.get("payload")
    return payload if isinstance(payload, dict) else diagnostic


def url_query(url: str) -> dict[str, str]:
    try:
        parsed = urllib.parse.urlparse(url)
        pairs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    except Exception:
        return {}
    return {key: values[-1] if values else "" for key, values in pairs.items()}


def summarize_diagnostic(path: Path) -> dict[str, Any]:
    raw = read_json(path)
    payload = payload_of(raw)
    webview = payload.get("webview") if isinstance(payload.get("webview"), dict) else {}
    build = payload.get("build") if isinstance(payload.get("build"), dict) else {}
    voice = payload.get("voice_wake") if isinstance(payload.get("voice_wake"), dict) else {}
    url = str(payload.get("current_webview_url") or webview.get("current_url") or "")
    query = url_query(url)
    responsiveness = payload.get("responsiveness") if isinstance(payload.get("responsiveness"), dict) else {}
    ux_report = payload.get("android_native_ux_report") if isinstance(payload.get("android_native_ux_report"), dict) else {}
    return {
        "path": str(path.relative_to(ROOT)),
        "mtime": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "receivedAt": raw.get("received_at") or payload.get("received_at") or "",
        "deviceId": payload.get("device_id") or raw.get("device_id") or "",
        "buildId": payload.get("build_id") or build.get("build_id") or query.get("buildId") or "",
        "currentWebViewUrl": url,
        "native": query.get("native") or "",
        "shell": query.get("shell") or query.get("android_shell") or "",
        "androidRuntime": query.get("android_runtime") or "",
        "androidStartup": query.get("android_startup") or "",
        "wakeFlag": query.get("wake") or "",
        "bridgeDiagnostics": query.get("bridgeDiagnostics") or "",
        "healthProbes": query.get("healthProbes") or "",
        "perfSafeMode": query.get("perfSafeMode") or "",
        "hasUxReport": bool(ux_report),
        "appResponsivenessVerdict": payload.get("app_responsiveness_verdict") or ux_report.get("app_responsiveness_verdict") or "",
        "firstContentPaintMs": ux_report.get("first_content_paint_marker_ms"),
        "firstInteractiveMs": ux_report.get("first_interactive_marker_ms"),
        "fullUiReadyMs": ux_report.get("full_ui_ready_marker_ms"),
        "frameGapP95Ms": ux_report.get("frame_gap_p95_ms"),
        "frameGapMaxMs": ux_report.get("frame_gap_max_ms"),
        "longTasksCount": ux_report.get("long_tasks_count"),
        "responsiveness": {
            "present": bool(responsiveness),
            "degraded": responsiveness.get("degraded"),
            "overloaded": responsiveness.get("overloaded"),
            "degradationReasons": responsiveness.get("degradation_reasons") or [],
            "maxFrameGapMs": responsiveness.get("max_frame_gap_ms"),
            "maxLongTaskMs": responsiveness.get("max_long_task_ms"),
        },
        "wake": {
            "present": bool(voice),
            "enabled": voice.get("enabled"),
            "foregroundServiceRunning": voice.get("foreground_service_running"),
            "audioRecordActive": voice.get("audio_record_active"),
            "inferenceRunning": voice.get("inference_running"),
            "inferenceCount": voice.get("inference_count"),
            "threshold": voice.get("effective_wake_threshold") or voice.get("threshold"),
        },
    }


def android_diagnostics() -> list[dict[str, Any]]:
    paths = sorted(DIAGNOSTICS_DIR.glob("android-*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return [summarize_diagnostic(path) for path in paths]


def latest_ui_input_launch() -> dict[str, Any]:
    root = STATE_DIR / "native-control/results"
    paths = sorted(root.glob("win-*/android-input-budget-*-launch-run-hot-operation.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not paths:
        return {}
    raw = read_json(paths[0])
    result = raw.get("result") if isinstance(raw.get("result"), dict) else raw
    nested = result.get("rawResult") if isinstance(result.get("rawResult"), dict) else result.get("result") if isinstance(result.get("result"), dict) else result
    launch = nested.get("launch") if isinstance(nested.get("launch"), dict) else {}
    return {
        "path": str(paths[0].relative_to(ROOT)),
        "mtime": datetime.fromtimestamp(paths[0].stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "ok": nested.get("ok"),
        "action": nested.get("action") or "",
        "componentName": nested.get("componentName") or "",
        "failureClassification": nested.get("failureClassification") or "",
        "elapsedMs": launch.get("elapsedMs"),
        "stdout": str(launch.get("stdout") or "").replace("\r", ""),
    }


def native_control_clients(origin: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(origin.rstrip("/") + "/native/control/clients", timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__, "message": str(exc)}
    clients = data.get("clients") if isinstance(data.get("clients"), list) else []
    return {
        "ok": True,
        "count": len(clients),
        "androidDeviceIds": [
            str(client.get("device_id") or (client.get("heartbeat") or {}).get("device_id") or "")
            for client in clients
            if str(client.get("device_id") or (client.get("heartbeat") or {}).get("device_id") or "").startswith("android-")
        ][:12],
        "windowsDeviceIds": [
            str(client.get("device_id") or (client.get("heartbeat") or {}).get("device_id") or "")
            for client in clients
            if str(client.get("device_id") or (client.get("heartbeat") or {}).get("device_id") or "").startswith("win-")
        ][:6],
    }


def classify(report: dict[str, Any]) -> tuple[str, str, str, list[str]]:
    release = report["release"]
    latest = report.get("latestDiagnostic") or {}
    matching = report.get("latestMatchingDiagnostic") or {}
    findings = report["findings"]
    next_steps: list[str] = []
    if not latest:
        return "blocked", "android_passive_diagnostics_missing", "No passive Android diagnostics were found.", [
            "Open the Android app manually and wait for its normal diagnostics heartbeat, without using ADB."
        ]
    if release.get("buildId") and not matching:
        return "stale", "android_passive_diagnostics_stale", "Passive diagnostics do not show the promoted Android build.", [
            "Do not run ADB to force proof; first confirm manually whether the installed app is open and emitting diagnostics."
        ]
    subject = matching or latest
    if subject.get("shell") != "android-webview-v2" and findings.get("latestLaunchComponent", "").endswith("/.shell.NativeShellV2Activity"):
        next_steps.append("The last recorded v2 launch is not represented by passive diagnostics because shell v2 disables native-control; use manual visual proof or an explicit launch-only proof only if safe.")
    if not subject.get("hasUxReport"):
        next_steps.append("Add or wait for passive UX report emission before claiming Android runtime responsiveness.")
        return "inconclusive", "android_passive_ux_metrics_missing", "Latest passive diagnostics lack Android native UX timing/responsiveness metrics.", next_steps
    if subject.get("appResponsivenessVerdict") not in {"green", "pass"}:
        return "fail", "android_passive_ux_not_green", "Passive Android UX report exists but is not green.", [
            "Inspect frame gap, long task, touch, minimap, wake, and diagnostics counters before rebuilding."
        ]
    return "pass", "", "Passive Android UX state is green for the promoted build.", []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="http://127.0.0.1:8877")
    parser.add_argument("--skip-clients", action="store_true", help="Do not read /native/control/clients.")
    args = parser.parse_args()

    release = release_metadata()
    diagnostics = android_diagnostics()
    latest = diagnostics[0] if diagnostics else {}
    matching = next((item for item in diagnostics if item.get("buildId") == release.get("buildId")), {})
    launch = latest_ui_input_launch()
    report: dict[str, Any] = {
        "schema": "hermes.wasm_agent.android_passive_ux_state.v1",
        "checkedAt": utc_now(),
        "claim": "Passive Android native UX evidence is readable without ADB or device commands.",
        "release": release,
        "latestDiagnostic": latest,
        "latestMatchingDiagnostic": matching,
        "recentDiagnostics": diagnostics[:8],
        "latestUiInputLaunch": launch,
        "nativeControlClients": {} if args.skip_clients else native_control_clients(args.origin),
        "findings": {
            "usedAdb": False,
            "queuedNativeControlCommand": False,
            "latestLaunchComponent": launch.get("componentName") or "",
            "latestLaunchWasShellV2": str(launch.get("componentName") or "").endswith("/.shell.NativeShellV2Activity"),
            "latestDiagnosticIsReleaseBuild": bool(latest and latest.get("buildId") == release.get("buildId")),
            "matchingDiagnosticHasUxReport": bool(matching and matching.get("hasUxReport")),
            "wakeRunningInMatchingDiagnostic": bool((matching.get("wake") or {}).get("foregroundServiceRunning")) if matching else None,
        },
    }
    status, failure, summary, next_steps = classify(report)
    report.update({
        "status": status,
        "failureClass": failure,
        "summary": summary,
        "nextSuggestedSteps": next_steps,
        "evidence": [],
    })
    out = REPORT_DIR / f"{stamp()}-android-passive-ux-state.json"
    latest_out = REPORT_DIR / "latest-android-passive-ux-state.json"
    report["evidence"] = [str(out.relative_to(ROOT)), str(latest_out.relative_to(ROOT))]
    write_json(out, report)
    write_json(latest_out, report)
    print(json.dumps({
        "status": report["status"],
        "failureClass": report["failureClass"],
        "summary": report["summary"],
        "evidence": report["evidence"],
    }, indent=2, sort_keys=True))
    return 0 if status == "pass" else 3 if status in {"inconclusive", "needs-human-proof", "stale"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
