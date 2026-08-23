#!/usr/bin/env python3
"""Prove whether the installed Windows bridge exposes a ready default loopback input."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hot_shell_common import (  # noqa: E402
    choose_windows_client,
    queue_command,
    request_json,
    run_id,
    unwrap_result,
    wait_for_result,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="https://wa.colmeio.com")
    parser.add_argument("--state-dir", default="/local/plugins/wasm-agent/state")
    parser.add_argument("--wait-sec", type=int, default=45)
    args = parser.parse_args()
    origin = args.origin.rstrip("/")
    rid = run_id("audio-loopback")
    latest_path = Path("reports/windows/latest/audio-loopback-proof.json")
    run_path = Path("reports/windows/runs") / rid / "audio-loopback-proof.json"
    proof = {
        "status": "fail",
        "promiseId": "windows-audio-loopback-route",
        "claim": "Windows exposes a ready default loopback recording input for deterministic browser_speech testing.",
        "runId": rid,
        "origin": origin,
        "evidence": [str(latest_path), str(run_path)],
        "summary": "Windows audio loopback proof did not run.",
        "failureClass": "bridge_unreachable",
        "nextSuggestedSteps": ["Start the installed Windows app and rerun the production proof."],
    }
    try:
        clients = request_json("GET", f"{origin}/native/control/clients", timeout=8)
        client = choose_windows_client(clients.get("clients", []) if isinstance(clients.get("clients"), list) else [])
        if not client:
            raise RuntimeError("No Windows native client heartbeat found.")
        heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
        device_id = str(client.get("device_id") or heartbeat.get("device_id") or "")
        build_id = str(client.get("build_id") or heartbeat.get("buildId") or heartbeat.get("build_id") or "")
        command_id, _queued = queue_command(
            origin,
            device_id,
            "run_hot_operation",
            {"operationName": "inspect_windows_audio_loopback", "forceSync": True, "args": {}},
            rid,
            "Windows audio loopback route proof",
        )
        record = wait_for_result(Path(args.state_dir), device_id, command_id, wait_sec=args.wait_sec, origin=origin)
        result = unwrap_result(record)
        raw_result = result.get("rawResult") if isinstance(result.get("rawResult"), dict) else result
        failure_class = str(raw_result.get("failureClassification") or result.get("failureClassification") or result.get("error") or "unknown_failure")
        passed = raw_result.get("ok") is True and raw_result.get("defaultMatchesLoopback") is True and failure_class == "pass"
        proof.update({
            "status": "pass" if passed else "fail",
            "deviceId": device_id,
            "buildId": build_id,
            "commandId": command_id,
            "summary": "Ready default Windows loopback input found." if passed else str(raw_result.get("nextAction") or "No ready default Windows loopback input was proven."),
            "failureClass": None if passed else failure_class,
            "nextSuggestedSteps": [] if passed else [str(raw_result.get("nextAction") or "Inspect the audio endpoint inventory result.")],
            "result": raw_result,
            "envelope": {
                "ok": result.get("ok"),
                "hotOpSource": result.get("hotOpSource"),
                "hotOpSha": result.get("hotOpSha"),
                "bundleId": result.get("bundleId"),
            },
        })
    except Exception as error:  # noqa: BLE001 - proof must persist a bounded failure artifact
        proof["summary"] = str(error)
    write_json(latest_path, proof)
    write_json(run_path, proof)
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    return 0 if proof["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
