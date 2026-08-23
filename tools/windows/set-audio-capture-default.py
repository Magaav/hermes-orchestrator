#!/usr/bin/env python3
"""Set one exact ready Windows capture endpoint through the installed native bridge."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hot_shell_common import choose_windows_client, queue_command, request_json, run_id, unwrap_result, wait_for_result  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="https://wa.colmeio.com")
    parser.add_argument("--state-dir", default="/local/plugins/wasm-agent/state")
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--expected-name", required=True)
    parser.add_argument("--flow", choices=("capture", "render"), default="capture")
    parser.add_argument("--wait-sec", type=int, default=45)
    parser.add_argument("--apply", action="store_true", help="Apply the change; otherwise run in dry-run mode.")
    args = parser.parse_args()
    rid = run_id("audio-default")
    origin = args.origin.rstrip("/")
    clients = request_json("GET", f"{origin}/native/control/clients", timeout=8)
    client = choose_windows_client(clients.get("clients", []) if isinstance(clients.get("clients"), list) else [])
    if not client:
        raise RuntimeError("No Windows native client heartbeat found.")
    heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
    device_id = str(client.get("device_id") or heartbeat.get("device_id") or "")
    command_id, _ = queue_command(
        origin, device_id, "run_hot_operation",
        {"operationName": f"set_windows_audio_{args.flow}_default", "forceSync": True, "args": {"instanceId": args.instance_id, "expectedName": args.expected_name, "dryRun": not args.apply}},
        rid, "Set exact Windows audio capture default" if args.apply else "Dry-run exact Windows audio capture default",
    )
    record = wait_for_result(Path(args.state_dir), device_id, command_id, wait_sec=args.wait_sec, origin=origin)
    envelope = unwrap_result(record)
    result = envelope.get("rawResult") if isinstance(envelope.get("rawResult"), dict) else envelope
    passed = result.get("ok") is True and result.get("failureClassification") == "pass" and result.get("changed") is args.apply
    proof = {
        "status": "pass" if passed else "fail", "runId": rid, "deviceId": device_id, "commandId": command_id,
        "applied": args.apply, "result": result,
        "envelope": {"hotOpSource": envelope.get("hotOpSource"), "hotOpSha": envelope.get("hotOpSha"), "bundleId": envelope.get("bundleId")},
    }
    latest = Path("reports/windows/latest/audio-default-action.json")
    run_path = Path("reports/windows/runs") / rid / "audio-default-action.json"
    write_json(latest, proof)
    write_json(run_path, proof)
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
