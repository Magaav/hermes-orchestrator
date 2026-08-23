#!/usr/bin/env python3
"""Measure whether a Windows speech fixture reaches the default capture endpoint."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hot_shell_common import choose_windows_client, queue_command, request_json, run_id, unwrap_result, wait_for_result  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="https://wa.colmeio.com")
    parser.add_argument("--state-dir", default="/local/plugins/wasm-agent/state")
    parser.add_argument("--voice", default="Microsoft David Desktop")
    parser.add_argument("--phrase", default="Audio signal probe confirms the virtual cable path.")
    parser.add_argument("--wait-sec", type=int, default=45)
    args = parser.parse_args()
    origin = args.origin.rstrip("/")
    rid = run_id("audio-signal")
    clients = request_json("GET", f"{origin}/native/control/clients", timeout=8)
    client = choose_windows_client(clients.get("clients", []))
    if not client:
        raise RuntimeError("No Windows native client heartbeat found.")
    heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
    device_id = str(client.get("device_id") or heartbeat.get("device_id") or "")
    command_id, _ = queue_command(origin, device_id, "run_hot_operation", {
        "operationName": "probe_windows_audio_signal", "forceSync": True,
        "args": {"voice": args.voice, "phrase": args.phrase, "captureMs": 8000},
    }, rid, "Windows VB-CABLE live signal proof")
    record = wait_for_result(Path(args.state_dir), device_id, command_id, wait_sec=args.wait_sec, origin=origin)
    result = unwrap_result(record)
    raw = result.get("rawResult") if isinstance(result.get("rawResult"), dict) else result
    proof = {
        "status": "pass" if raw.get("ok") is True and raw.get("signalPresent") is True else "fail",
        "promiseId": "windows-audio-loopback-signal",
        "claim": "Synthesized speech produces measurable samples on the default Windows capture endpoint.",
        "runId": rid, "deviceId": device_id, "commandId": command_id, "result": raw,
        "failureClass": None if raw.get("signalPresent") is True else raw.get("failureClassification", "unknown_failure"),
        "summary": "VB-CABLE carried measurable speech." if raw.get("signalPresent") is True else "Default capture remained silent during speech synthesis.",
    }
    latest = Path("reports/windows/latest/audio-signal-proof.json")
    run_path = Path("reports/windows/runs") / rid / "audio-signal-proof.json"
    for path in (latest, run_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    return 0 if proof["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
