#!/usr/bin/env python3
"""Prove the local Windows hot-operation shell is ready for fast debug loops."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from hot_shell_common import (
    DEFAULT_ORIGIN,
    EXPECTED_HOT_OPS_PROTOCOL,
    artifact_paths,
    choose_windows_client,
    classify_result,
    next_action,
    queue_command,
    request_json,
    run_id,
    unwrap_result,
    wait_for_result,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default=os.getenv("WASM_AGENT_ORIGIN", DEFAULT_ORIGIN))
    parser.add_argument("--state-dir", default=os.getenv("HERMES_WASM_AGENT_STATE_DIR", "/local/plugins/wasm-agent/state"))
    parser.add_argument("--wait-sec", type=int, default=45)
    args = parser.parse_args()

    rid = run_id()
    artifacts = artifact_paths("windows", rid)
    logs: list[str] = []
    origin = args.origin.rstrip("/")
    state_dir = Path(args.state_dir)
    failure = "unknown_failure"
    results: dict[str, Any] = {}

    try:
        clients = request_json("GET", f"{origin}/native/control/clients", timeout=8)
        client = choose_windows_client(clients.get("clients", []) if isinstance(clients.get("clients"), list) else [])
        if not client:
            failure = "bridge_unreachable"
            raise RuntimeError("No Windows native client heartbeat found.")
        device_id = str(client.get("device_id") or client.get("heartbeat", {}).get("device_id") or "")
        commands = [
            ("get_bridge_status", {}),
            ("list_hot_operations", {}),
            ("run_shell_self_test", {}),
            ("run_hot_operation", {"operationName": "canary_echo", "dryRun": True, "args": {"dryRun": True}}),
        ]
        for command, payload in commands:
            command_id, queued = queue_command(origin, device_id, command, payload, rid, "Windows hot shell proof")
            logs.append(f"queued {command} {command_id}")
            record = wait_for_result(state_dir, device_id, command_id, wait_sec=args.wait_sec)
            result = unwrap_result(record)
            results[command] = {"queued": queued, "record": record, "result": result}
            logs.extend(str(item) for item in result.get("logsTail", []) if isinstance(result.get("logsTail"), list))
            if not record:
                failure = "bridge_unreachable"
                raise RuntimeError(f"No result for {command}.")
            classification = classify_result(result)
            if command == "get_bridge_status":
                protocol = int(result.get("hotOpsProtocolVersion") or result.get("hotOperations", {}).get("supportedHotOpsProtocol") or 0)
                capabilities = result.get("capabilities") if isinstance(result.get("capabilities"), list) else []
                if "run_hot_operation" not in capabilities:
                    failure = "bridge_update_required"
                    break
                if protocol < EXPECTED_HOT_OPS_PROTOCOL:
                    failure = "hot_ops_protocol_missing"
                    break
            elif command == "list_hot_operations":
                ops = result.get("availableHotOps") if isinstance(result.get("availableHotOps"), list) else []
                if not any(item.get("name") == "canary_echo" for item in ops if isinstance(item, dict)):
                    failure = "hot_operation_missing"
                    break
            elif command == "run_shell_self_test" and result.get("ok") is not True:
                failure = result.get("failureClassification") or "shell_self_test_failed"
                if failure not in {"adb_missing", "android_device_missing"}:
                    failure = "shell_self_test_failed"
                break
            elif command == "run_hot_operation" and result.get("ok") is not True:
                failure = classification if classification.startswith("hot_operation_") else "hot_operation_failed"
                break
        else:
            failure = "pass"
    except Exception as exc:
        if failure == "unknown_failure":
            failure = "bridge_unreachable"
        logs.append(str(exc))

    bridge_status = unwrap_result(results.get("get_bridge_status", {}).get("record", {}))
    hot_ops = unwrap_result(results.get("list_hot_operations", {}).get("record", {}))
    self_test = unwrap_result(results.get("run_shell_self_test", {}).get("record", {}))
    canary = unwrap_result(results.get("run_hot_operation", {}).get("record", {}))
    active_root = hot_ops.get("hotOpsMode") or bridge_status.get("hotOperations", {}).get("hotOpsMode") or ""
    protocol = hot_ops.get("hotOpsProtocolVersion") or hot_ops.get("supportedHotOpsProtocol") or bridge_status.get("hotOpsProtocolVersion") or 0
    checks = self_test.get("checks") if isinstance(self_test.get("checks"), dict) else {}
    output = {
        "ok": failure == "pass",
        "runId": rid,
        "schema": "hermes.wasm_agent.windows_hot_shell_proof.v1",
        "origin": origin,
        "artifacts": {"result": artifacts["result"], "logs": artifacts["logs"]},
        "failureClassification": None if failure == "pass" else failure,
        "nextAction": next_action(failure),
        "bridgeAlive": bool(bridge_status.get("ok")),
        "hotOpsProtocolVersion": protocol,
        "activeHotOpsRoot": active_root,
        "canaryOp": "pass" if canary.get("ok") else "fail",
        "adb": "available" if checks.get("adb_discoverable") else "unavailable",
        "androidDevice": "authorized" if checks.get("authorized_android_device_present") else "missing",
        "results": results,
    }
    write_json(Path(artifacts["result"]), output)
    write_json(Path(artifacts["latest"]) / "hot-shell-proof-result.json", output)
    write_json(Path(artifacts["runResult"]), output)
    Path(artifacts["logs"]).write_text("\n".join(logs) + "\n", encoding="utf-8")
    Path(artifacts["runLogs"]).write_text("\n".join(logs) + "\n", encoding="utf-8")

    print(f"Windows hot shell: {'PASS' if output['ok'] else 'FAIL'}")
    print(f"Bridge alive: {'yes' if output['bridgeAlive'] else 'no'}")
    print(f"Hot ops protocol: {protocol}")
    print(f"Active hot ops root: {active_root or 'unknown'}")
    print(f"Canary op: {output['canaryOp']}")
    print(f"ADB: {output['adb']}")
    print(f"Android device: {output['androidDevice']}")
    print(f"Failure classification: {failure}")
    print(f"Next action: {output['nextAction']}")
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
