#!/usr/bin/env python3
"""Play one bounded Windows audio stimulus through the installed native bridge."""

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
    parser.add_argument("--kind", choices=("speech", "voice_inventory", "system_sound", "beep", "silence"), default="speech")
    parser.add_argument("--phrase", default="")
    parser.add_argument("--voice", default="")
    parser.add_argument("--rate", type=int, default=-1)
    parser.add_argument("--label", default="stimulus")
    parser.add_argument("--wait-sec", type=int, default=45)
    args = parser.parse_args()
    origin = args.origin.rstrip("/")
    rid = run_id("audio-stimulus")
    clients = request_json("GET", f"{origin}/native/control/clients", timeout=8)
    client = choose_windows_client(clients.get("clients", []) if isinstance(clients.get("clients"), list) else [])
    if not client:
        raise RuntimeError("No Windows native client heartbeat found.")
    heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
    device_id = str(client.get("device_id") or heartbeat.get("device_id") or "")
    payload = {"kind": args.kind, "label": args.label, "phrase": args.phrase, "voice": args.voice, "rate": args.rate}
    command_id, _ = queue_command(origin, device_id, "play_audio_stimulus", payload, rid, f"Play bounded {args.kind} audio stimulus")
    record = wait_for_result(Path(args.state_dir), device_id, command_id, wait_sec=args.wait_sec, origin=origin)
    envelope = unwrap_result(record)
    result = envelope.get("rawResult") if isinstance(envelope.get("rawResult"), dict) else envelope
    proof = {"status": "pass" if result.get("ok") is True else "fail", "runId": rid, "deviceId": device_id, "commandId": command_id, "result": result}
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    return 0 if proof["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
