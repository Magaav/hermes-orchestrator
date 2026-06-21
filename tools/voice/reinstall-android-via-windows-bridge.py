#!/usr/bin/env python3
"""Build/publish and reinstall the Android APK through the Windows ADB bridge."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
TOOLS_WINDOWS = REPO_ROOT / "tools" / "windows"
sys.path.insert(0, str(TOOLS_WINDOWS))

from hot_shell_common import (  # noqa: E402
    DEFAULT_ORIGIN,
    choose_windows_client,
    classify_result,
    classify_roundtrip,
    command_timeline,
    next_action,
    queue_command,
    request_json,
    run_id,
    unwrap_result,
    wait_for_result,
)


STATE_DIR = REPO_ROOT / "plugins" / "wasm-agent" / "state"
PUBLIC_ANDROID_DIR = REPO_ROOT / "plugins" / "wasm-agent" / "public" / "native" / "releases" / "android"
PUBLIC_FEED = REPO_ROOT / "plugins" / "wasm-agent" / "public" / "native" / "releases" / "latest.json"
RELEASE_APK = REPO_ROOT / "native" / "android" / "release" / "WASM-Agent-arm64.apk"
RELEASE_META = REPO_ROOT / "native" / "android" / "release" / "WASM-Agent-arm64.native-defaults.json"
PUBLIC_APK = PUBLIC_ANDROID_DIR / "WASM-Agent-arm64.apk"


def run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=REPO_ROOT, env=env, check=True)


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def apk_metadata() -> dict[str, Any]:
    feed = read_json(PUBLIC_FEED)
    android = (feed.get("artifacts") or {}).get("android") if isinstance(feed.get("artifacts"), dict) else {}
    arm64 = android.get("arm64") if isinstance(android, dict) else {}
    sidecar = read_json(RELEASE_META)
    return {
        "buildId": arm64.get("buildId") or sidecar.get("buildId") or "",
        "sha256": arm64.get("sha256") or sidecar.get("artifactSha256") or "",
        "sizeBytes": arm64.get("sizeBytes") or arm64.get("size") or sidecar.get("artifactSize") or 0,
        "url": "/native/releases/android/WASM-Agent-arm64.apk",
    }


def current_android_device_id(build_id: str) -> str:
    if not build_id:
        return ""
    normalized = build_id.lower()
    diag_root = STATE_DIR / "native-diagnostics"
    candidates = sorted(diag_root.glob(f"*{normalized}*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for path in candidates:
        stem = path.stem
        if normalized in stem:
            return stem
    return ""


def wait_for_android_build(build_id: str, wait_sec: int) -> dict[str, Any]:
    if not build_id:
        return {"ok": False, "error": "build_id_missing"}
    import time

    deadline = time.monotonic() + wait_sec
    while time.monotonic() < deadline:
        device_id = current_android_device_id(build_id)
        if device_id:
            diag = read_json(STATE_DIR / "native-diagnostics" / f"{device_id}.json")
            payload = diag.get("payload") or diag if isinstance(diag, dict) else {}
            voice = payload.get("voice_wake") if isinstance(payload, dict) else {}
            build_payload = payload.get("build") if isinstance(payload.get("build"), dict) else {}
            top_build_id = payload.get("build_id") or build_payload.get("build_id") or ""
            voice_build_id = (voice or {}).get("android_build_id") or (voice or {}).get("build_id") or ""
            return {
                "ok": True,
                "deviceId": device_id,
                "diagnostics": {
                    "received_at": diag.get("received_at") if isinstance(diag, dict) else "",
                    "android_build_id": top_build_id or voice_build_id or build_id,
                    "voice_wake_android_build_id": voice_build_id,
                    "voice_wake_build_stale": bool(voice_build_id and top_build_id and voice_build_id != top_build_id),
                    "state": (voice or {}).get("state"),
                    "threshold": (voice or {}).get("threshold") or (voice or {}).get("wake_threshold"),
                    "wake_detection_count": (voice or {}).get("wake_detection_count"),
                    "wake_service_ready": (voice or {}).get("wake_service_ready"),
                    "foreground_service_active": (voice or {}).get("foreground_service_active"),
                },
            }
        time.sleep(2)
    return {"ok": False, "error": "android_diagnostics_build_not_seen", "buildId": build_id}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default=os.getenv("WASM_AGENT_ORIGIN", DEFAULT_ORIGIN))
    parser.add_argument("--state-dir", default=str(STATE_DIR))
    parser.add_argument("--wait-sec", type=int, default=240)
    parser.add_argument("--proof-wait-ms", type=int, default=8000)
    parser.add_argument("--build", action="store_true", help="Run horc build android before publishing/installing.")
    parser.add_argument("--publish-feed", action="store_true", help="Regenerate /native/releases/latest.json before install.")
    parser.add_argument("--skip-preflight", action="store_true", help="Queue install without first proving the Windows bridge polling loop.")
    parser.add_argument("--skip-install", action="store_true", help="Only build/publish and print selected APK metadata.")
    args = parser.parse_args()

    if args.build:
        run(["horc", "build", "android"])
    if args.publish_feed:
        run(["node", "plugins/wasm-agent/scripts/generate-native-release-feed.js"])

    if not PUBLIC_APK.exists():
        raise SystemExit(f"Published APK missing: {PUBLIC_APK}. Run with --build --publish-feed.")
    meta = apk_metadata()
    if not meta["sha256"] or not meta["sizeBytes"]:
        raise SystemExit("Published APK metadata missing sha256/sizeBytes. Run with --publish-feed.")
    print("selected apk " + json.dumps(meta, sort_keys=True), flush=True)
    if args.skip_install:
        return 0

    origin = args.origin.rstrip("/")
    state_dir = Path(args.state_dir)
    clients = request_json("GET", f"{origin}/native/control/clients", timeout=8)
    client = choose_windows_client(clients.get("clients", []) if isinstance(clients.get("clients"), list) else [])
    if not client:
        raise SystemExit("No Windows native client heartbeat found.")
    heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
    device_id = str(client.get("device_id") or heartbeat.get("device_id") or "")
    if not device_id:
        raise SystemExit("Windows native client id missing.")

    if not args.skip_preflight:
        preflight_id, _queued = queue_command(
            origin,
            device_id,
            "get_bridge_status",
            {},
            run_id("android-reinstall-preflight"),
            "Android reinstall preflight",
        )
        preflight_record = wait_for_result(state_dir, device_id, preflight_id, wait_sec=45)
        preflight_result = unwrap_result(preflight_record)
        preflight_roundtrip = classify_roundtrip(state_dir, device_id, preflight_id, preflight_record)
        preflight_classification = classify_result(preflight_result)
        preflight = {
            "commandId": preflight_id,
            "roundtrip": preflight_roundtrip,
            "classification": preflight_classification,
            "ok": bool(preflight_record) and preflight_roundtrip == "pass" and preflight_classification == "pass" and preflight_result.get("ok") is True,
        }
        print("preflight " + json.dumps(preflight, sort_keys=True), flush=True)
        if not preflight["ok"]:
            print(json.dumps({
                "ok": False,
                "stage": "preflight",
                "preflight": preflight,
                "nextAction": next_action(preflight_roundtrip if preflight_roundtrip != "pass" else preflight_classification),
            }, indent=2, sort_keys=True))
            return 1

    payload = {
        "apkUrl": meta["url"],
        "apkSha256": meta["sha256"],
        "apkSizeBytes": meta["sizeBytes"],
        "buildId": meta["buildId"],
        "proofWaitMs": args.proof_wait_ms,
        "packageName": "com.colmeio.wasmagent",
    }
    rid = run_id("android-reinstall")
    command_id, queued = queue_command(origin, device_id, "prove_android_voice_tuning", payload, rid, "Android APK reinstall via Windows ADB bridge")
    print("queued " + json.dumps({"deviceId": device_id, "commandId": command_id, "queued": queued}, sort_keys=True), flush=True)
    record = wait_for_result(state_dir, device_id, command_id, wait_sec=args.wait_sec)
    result = unwrap_result(record)
    timeline = command_timeline(state_dir, device_id, command_id, record)
    roundtrip = classify_roundtrip(state_dir, device_id, command_id, record)
    classification = classify_result(result)
    android = wait_for_android_build(str(meta["buildId"]), 60)
    summary = {
        "ok": bool(record) and roundtrip == "pass" and classification == "pass" and result.get("ok") is True,
        "commandId": command_id,
        "roundtrip": roundtrip,
        "classification": classification,
        "timeline": timeline,
        "installStatus": result.get("status") or "",
        "adbPath": result.get("adbPath") or "",
        "apk": result.get("apk") or payload,
        "androidBuildSeen": android,
        "nextAction": next_action(roundtrip if roundtrip != "pass" else classification),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
