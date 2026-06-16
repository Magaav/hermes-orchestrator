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
    classify_roundtrip,
    classify_result,
    command_timeline,
    cleanup_native_control_state,
    next_action,
    queue_command,
    request_json,
    run_id,
    unwrap_result,
    wait_for_result,
    write_json,
)

ROUNDTRIP_FAILURES = {
    "command_not_polled",
    "command_polled_not_started",
    "handler_missing",
    "handler_threw",
    "handler_timeout",
    "handler_never_resolved",
    "result_upload_failed",
    "result_uploaded_but_script_parser_missed",
    "result_seen_wrong_shape",
}

COMMANDS: dict[str, tuple[str, dict[str, Any]]] = {
    "get_bridge_status": ("get_bridge_status", {}),
    "get_native_kernel_status": ("get_native_kernel_status", {}),
    "sync_downloaded_runtime": ("sync_downloaded_runtime", {"forceSync": True}),
    "list_hot_operations": ("list_hot_operations", {"forceSync": True}),
    "run_shell_self_test": ("run_shell_self_test", {}),
    "canary_echo": ("run_hot_operation", {"operationName": "canary_echo", "dryRun": True, "args": {"dryRun": True}}),
    "hot_op_lightweight_snapshot": ("run_hot_operation", {"operationName": "hot_op_lightweight_snapshot", "args": {}}),
    "check_android_connection": ("check_android_connection", {}),
    "run_hermes_wake_goal_loop": ("run_hot_operation", {"operationName": "run_hermes_wake_goal_loop", "args": {}}),
}

PREFLIGHT_COMMANDS = ("get_bridge_status", "run_shell_self_test")


def result_failure(result: dict[str, Any]) -> str:
    value = result.get("failureClassification") or result.get("failure_classification")
    return str(value or "")


def command_debug(
    *,
    label: str,
    native_command: str,
    command_id: str,
    client: dict[str, Any],
    record: dict[str, Any],
    result: dict[str, Any],
    timeline: dict[str, Any],
    roundtrip_classification: str,
    top_level_failure: str,
    bridge_alive_source: str,
) -> dict[str, Any]:
    heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
    return {
        "label": label,
        "nativeCommand": native_command,
        "commandId": command_id,
        "queued_at": timeline.get("queued_at") or "",
        "picked_up_at": timeline.get("picked_up_at") or "",
        "delivered_at": timeline.get("picked_up_at") or "",
        "completed_at": timeline.get("completed_at") or "",
        "uploaded_at": timeline.get("uploaded_at") or "",
        "result_seen_at": timeline.get("result_seen_at") or "",
        "clientId": client.get("client_id") or heartbeat.get("clientId") or heartbeat.get("client_id") or client.get("device_id") or heartbeat.get("device_id") or "",
        "buildId": client.get("build_id") or heartbeat.get("buildId") or heartbeat.get("build_id") or "",
        "result.ok": result.get("ok") if isinstance(result, dict) else None,
        "result.failureClassification": result_failure(result) if isinstance(result, dict) else "",
        "roundtripFailureClassification": roundtrip_classification,
        "topLevelFailureClassification": top_level_failure,
        "bridge_alive_source": bridge_alive_source,
    }


def require_command_pass(
    *,
    label: str,
    result: dict[str, Any],
    roundtrip_classification: str,
    timeline: dict[str, Any],
    client: dict[str, Any],
) -> str:
    heartbeat = client.get("heartbeat") if isinstance(client.get("heartbeat"), dict) else {}
    build_id = str(client.get("build_id") or heartbeat.get("buildId") or heartbeat.get("build_id") or "")
    client_id = str(client.get("client_id") or heartbeat.get("clientId") or heartbeat.get("client_id") or client.get("device_id") or heartbeat.get("device_id") or "")
    if roundtrip_classification != "pass":
        return roundtrip_classification
    if classify_result(result) != "pass":
        return classify_result(result)
    if result.get("ok") is not True:
        return f"{label}_not_ok"
    if not build_id or not client_id:
        return "bridge_unreachable"
    if label == "run_shell_self_test":
        for field in ("completed_at", "uploaded_at", "result_seen_at"):
            if not timeline.get(field):
                return "result_uploaded_but_script_parser_missed"
    return "pass"


def available_hot_operation_names(result: dict[str, Any]) -> list[str]:
    ops = result.get("availableHotOps") if isinstance(result.get("availableHotOps"), list) else []
    names = sorted(
        {
            str(item.get("name") or item.get("operationId") or "").strip()
            for item in ops
            if isinstance(item, dict) and str(item.get("name") or item.get("operationId") or "").strip()
        }
    )
    return names


def hot_operation_name(native_command: str, payload: dict[str, Any]) -> str:
    if native_command != "run_hot_operation":
        return ""
    return str(payload.get("operationName") or payload.get("operation") or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default=os.getenv("WASM_AGENT_ORIGIN", DEFAULT_ORIGIN))
    parser.add_argument("--state-dir", default=os.getenv("HERMES_WASM_AGENT_STATE_DIR", "/local/plugins/wasm-agent/state"))
    parser.add_argument("--wait-sec", type=int, default=45)
    parser.add_argument("--only", action="append", default=[], help="Run only the named native-control command. Can be repeated.")
    parser.add_argument("--preflight", action="store_true", help="Require bridge status and shell self-test in this same invocation before selected commands.")
    parser.add_argument("--preflight-only", action="store_true", help="Run only the atomic bridge preflight.")
    parser.add_argument("--skip-state-cleanup", action="store_true", help="Do not archive old finished native-control command/result files before queueing.")
    args = parser.parse_args()

    rid = run_id()
    artifacts = artifact_paths("windows", rid)
    logs: list[str] = []
    origin = args.origin.rstrip("/")
    state_dir = Path(args.state_dir)
    failure = "unknown_failure"
    results: dict[str, Any] = {}
    debug: list[dict[str, Any]] = []
    bridge_alive = False
    bridge_alive_source = "not_checked"
    requested_hot_operation = ""
    available_hot_operations: list[str] = []
    cleanup: dict[str, Any] = {}

    try:
        clients = request_json("GET", f"{origin}/native/control/clients", timeout=8)
        client = choose_windows_client(clients.get("clients", []) if isinstance(clients.get("clients"), list) else [])
        if not client:
            failure = "bridge_unreachable"
            raise RuntimeError("No Windows native client heartbeat found.")
        device_id = str(client.get("device_id") or client.get("heartbeat", {}).get("device_id") or "")
        if not args.skip_state_cleanup:
            cleanup = cleanup_native_control_state(state_dir, device_id)
            if cleanup.get("staleStateFound"):
                logs.append("native-control cleanup " + json.dumps(cleanup, sort_keys=True))
        selected = [
            "get_bridge_status",
            "get_native_kernel_status",
            "sync_downloaded_runtime",
            "list_hot_operations",
            "run_shell_self_test",
            "canary_echo",
        ]
        only = {str(item).strip() for item in args.only if str(item).strip()}
        if only:
            unsupported = sorted(item for item in only if item not in COMMANDS)
            if unsupported:
                failure = "unknown_failure"
                raise RuntimeError(f"No supported --only command selected: {unsupported}")
            selected = [item for item in COMMANDS if item in only]
        if selected != ["get_bridge_status"]:
            args.preflight = True
        if args.preflight_only:
            selected = []
            args.preflight = True

        def run_one(label: str, *, preflight_phase: bool = False) -> dict[str, Any]:
            nonlocal failure, bridge_alive, bridge_alive_source, requested_hot_operation, available_hot_operations
            native_command, payload = COMMANDS[label]
            command_id, queued = queue_command(origin, device_id, native_command, payload, rid, "Windows hot shell proof")
            logs.append(f"queued {label} {command_id}")
            record = wait_for_result(state_dir, device_id, command_id, wait_sec=args.wait_sec)
            timeline = command_timeline(state_dir, device_id, command_id, record)
            result = unwrap_result(record)
            roundtrip_classification = classify_roundtrip(state_dir, device_id, command_id, record)
            classification = classify_result(result)
            result_ok = result.get("ok") is True if isinstance(result, dict) else False
            if label == "get_bridge_status":
                bridge_alive = roundtrip_classification == "pass" and classification == "pass" and result_ok
                bridge_alive_source = f"{label}:{command_id}"
            if classification == "pass" and result_ok:
                top_failure = "pass"
            else:
                top_failure = classification
            item = {
                "queued": queued,
                "record": record,
                "result": result,
                "timeline": timeline,
                "roundtripFailureClassification": roundtrip_classification,
                "failureClassification": classification,
                "preflight": preflight_phase,
            }
            results[label] = item
            debug_item = command_debug(
                label=label,
                native_command=native_command,
                command_id=command_id,
                client=client,
                record=record,
                result=result,
                timeline=timeline,
                roundtrip_classification=roundtrip_classification,
                top_level_failure=top_failure,
                bridge_alive_source=bridge_alive_source,
            )
            debug.append(debug_item)
            logs.append("debug " + json.dumps(debug_item, sort_keys=True))
            logs.extend(str(item) for item in result.get("logsTail", []) if isinstance(result.get("logsTail"), list))
            if not record:
                failure = classify_roundtrip(state_dir, device_id, command_id, record)
                raise RuntimeError(f"No result for {label}: {failure}.")
            if roundtrip_classification in ROUNDTRIP_FAILURES:
                failure = roundtrip_classification
                return item
            if label == "get_bridge_status":
                protocol = int(result.get("hotOpsProtocolVersion") or result.get("hotOperations", {}).get("supportedHotOpsProtocol") or 0)
                capabilities = result.get("capabilities") if isinstance(result.get("capabilities"), list) else []
                if "run_hot_operation" not in capabilities:
                    failure = "bridge_update_required"
                    return item
                if protocol < EXPECTED_HOT_OPS_PROTOCOL:
                    failure = "hot_ops_protocol_missing"
                    return item
            elif label == "get_native_kernel_status":
                kernel = result.get("nativeKernel") if isinstance(result.get("nativeKernel"), dict) else {}
                if not kernel and isinstance(result.get("kernel"), dict):
                    kernel = result.get("kernel") or {}
                if not kernel:
                    kernel = result
                kernel_capabilities = kernel.get("capabilities") if isinstance(kernel.get("capabilities"), list) else []
                if not kernel_capabilities and isinstance(kernel.get("supportedCapabilities"), list):
                    kernel_capabilities = kernel.get("supportedCapabilities") or []
                if result.get("ok") is not True and not kernel_capabilities:
                    failure = "bridge_update_required"
                    return item
                if "native.capabilities.downloadedRuntime.v1" not in kernel_capabilities:
                    failure = "native_capability_missing"
                    return item
            elif label == "sync_downloaded_runtime":
                if result.get("ok") is not True:
                    failure = classify_result(result)
                    if failure == "unknown_failure":
                        failure = "runtime_download_failed"
                    return item
            elif label == "list_hot_operations":
                available_hot_operations = available_hot_operation_names(result)
                if "canary_echo" not in available_hot_operations:
                    requested_hot_operation = "canary_echo"
                    failure = "hot_operation_missing"
                    return item
            elif label == "run_shell_self_test" and result.get("ok") is not True:
                failure = result.get("failureClassification") or "shell_self_test_failed"
                adb_status = ""
                if isinstance(result.get("adbDiscovery"), dict):
                    adb_status = str(result["adbDiscovery"].get("status") or "")
                if failure == "handler_timeout":
                    failure = "handler_timeout"
                elif adb_status in {"adb_missing", "adb_timeout", "adb_server_start_failed", "no_device", "unauthorized", "offline", "multiple_devices"}:
                    failure = adb_status
                elif failure not in {"adb_missing", "adb_timeout", "adb_server_start_failed", "no_device", "unauthorized", "offline", "multiple_devices", "android_device_missing"}:
                    failure = "shell_self_test_failed"
                return item
            elif native_command == "run_hot_operation" and result.get("ok") is not True:
                failure = classification if classification.startswith("hot_operation_") else "hot_operation_failed"
                return item
            elif native_command == "check_android_connection" and result.get("ok") is not True:
                failure = classification
                return item
            failure = "pass"
            return item

        def ensure_hot_operation_registered(label: str) -> bool:
            nonlocal failure, requested_hot_operation, available_hot_operations
            native_command, payload = COMMANDS[label]
            requested = hot_operation_name(native_command, payload)
            if not requested:
                return True
            requested_hot_operation = requested
            hot_ops_item = results.get("list_hot_operations") if isinstance(results.get("list_hot_operations"), dict) else {}
            hot_ops_result = hot_ops_item.get("result") if isinstance(hot_ops_item.get("result"), dict) else {}
            if not hot_ops_result or hot_ops_result.get("ok") is not True:
                hot_ops_item = run_one("list_hot_operations")
                if failure != "pass":
                    return False
                hot_ops_result = hot_ops_item.get("result") if isinstance(hot_ops_item.get("result"), dict) else {}
            available_hot_operations = available_hot_operation_names(hot_ops_result)
            if requested not in available_hot_operations:
                failure = "hot_operation_missing"
                logs.append(
                    "hot operation missing "
                    + json.dumps(
                        {"requestedOp": requested, "availableOps": available_hot_operations},
                        sort_keys=True,
                    )
                )
                return False
            return True

        if args.preflight:
            for label in PREFLIGHT_COMMANDS:
                item = run_one(label, preflight_phase=True)
                if failure != "pass":
                    break
                preflight_failure = require_command_pass(
                    label=label,
                    result=item.get("result", {}),
                    roundtrip_classification=str(item.get("roundtripFailureClassification") or ""),
                    timeline=item.get("timeline", {}),
                    client=client,
                )
                if preflight_failure != "pass":
                    failure = preflight_failure
                    break
        elif failure == "unknown_failure":
            failure = "pass"
        if failure == "pass":
            for label in selected:
                if args.preflight and label in PREFLIGHT_COMMANDS:
                    continue
                native_command, payload = COMMANDS[label]
                if hot_operation_name(native_command, payload) and not ensure_hot_operation_registered(label):
                    break
                run_one(label)
                if failure != "pass":
                    break
        if failure == "pass":
            failure = "pass"
    except Exception as exc:
        if failure == "unknown_failure":
            failure = "bridge_unreachable"
        logs.append(str(exc))

    bridge_status = unwrap_result(results.get("get_bridge_status", {}).get("record", {}))
    kernel_status = unwrap_result(results.get("get_native_kernel_status", {}).get("record", {}))
    runtime_sync = unwrap_result(results.get("sync_downloaded_runtime", {}).get("record", {}))
    hot_ops = unwrap_result(results.get("list_hot_operations", {}).get("record", {}))
    self_test = unwrap_result(results.get("run_shell_self_test", {}).get("record", {}))
    canary = unwrap_result(results.get("canary_echo", {}).get("record", {}))
    active_root = hot_ops.get("hotOpsMode") or bridge_status.get("hotOperations", {}).get("hotOpsMode") or ""
    downloaded_sync = hot_ops.get("downloadedHotOpsSync") if isinstance(hot_ops.get("downloadedHotOpsSync"), dict) else {}
    downloaded_runtime = runtime_sync.get("downloadedRuntime") if isinstance(runtime_sync.get("downloadedRuntime"), dict) else {}
    if not downloaded_runtime:
        downloaded_runtime = bridge_status.get("downloadedRuntime") if isinstance(bridge_status.get("downloadedRuntime"), dict) else {}
    native_kernel = kernel_status.get("nativeKernel") if isinstance(kernel_status.get("nativeKernel"), dict) else {}
    if not native_kernel and isinstance(kernel_status.get("kernel"), dict):
        native_kernel = kernel_status.get("kernel") or {}
    if not native_kernel:
        native_kernel = kernel_status
    if not available_hot_operations:
        available_hot_operations = available_hot_operation_names(hot_ops)
    protocol = hot_ops.get("hotOpsProtocolVersion") or hot_ops.get("supportedHotOpsProtocol") or bridge_status.get("hotOpsProtocolVersion") or 0
    checks = self_test.get("checks") if isinstance(self_test.get("checks"), dict) else {}
    adb_discovery = self_test.get("adbDiscovery") if isinstance(self_test.get("adbDiscovery"), dict) else {}
    adb_status = str(adb_discovery.get("status") or "")
    output = {
        "ok": failure == "pass",
        "runId": rid,
        "schema": "hermes.wasm_agent.windows_hot_shell_proof.v1",
        "origin": origin,
        "artifacts": {"result": artifacts["result"], "logs": artifacts["logs"]},
        "failureClassification": None if failure == "pass" else failure,
        "nextAction": next_action(failure),
        "requestedHotOperation": requested_hot_operation,
        "availableHotOperations": available_hot_operations,
        "bridgeAlive": bridge_alive,
        "bridgeAliveSource": bridge_alive_source,
        "hotOpsProtocolVersion": protocol,
        "nativeKernel": native_kernel,
        "downloadedRuntime": downloaded_runtime,
        "activeDownloadedRuntimeId": downloaded_runtime.get("activeRuntimeId") or downloaded_runtime.get("activeBundleId") or "",
        "activeDownloadedRuntimeSha": downloaded_runtime.get("activeRuntimeSha") or downloaded_runtime.get("activeBundleSha") or "",
        "activeHotOpsRoot": active_root,
        "downloadedHotOpsSync": downloaded_sync,
        "canaryOp": "pass" if canary.get("ok") else "fail",
        "adb": "available" if checks.get("adb_discoverable") else "unavailable",
        "androidDiscoveryStatus": adb_status or ("one_authorized_device" if checks.get("authorized_android_device_present") else "unknown"),
        "androidDevice": "authorized" if checks.get("authorized_android_device_present") else (adb_status or "missing"),
        "results": results,
        "nativeControlCleanup": cleanup,
        "roundTrip": {
            command: item.get("timeline", {})
            for command, item in results.items()
            if isinstance(item, dict)
        },
        "debug": debug,
    }
    if output["ok"] and not output["bridgeAlive"]:
        output["ok"] = False
        failure = "bridge_unreachable"
        output["failureClassification"] = failure
        output["nextAction"] = next_action(failure)
    write_json(Path(artifacts["result"]), output)
    write_json(Path(artifacts["latest"]) / "hot-shell-proof-result.json", output)
    write_json(Path(artifacts["runResult"]), output)
    Path(artifacts["logs"]).write_text("\n".join(logs) + "\n", encoding="utf-8")
    Path(artifacts["runLogs"]).write_text("\n".join(logs) + "\n", encoding="utf-8")

    print(f"Windows hot shell: {'PASS' if output['ok'] else 'FAIL'}")
    print(f"Bridge alive: {'yes' if output['bridgeAlive'] else 'no'}")
    print(f"Bridge alive source: {output['bridgeAliveSource']}")
    print(f"Hot ops protocol: {protocol}")
    native_kernel_capabilities = native_kernel.get("capabilities") if isinstance(native_kernel.get("capabilities"), list) else []
    if not native_kernel_capabilities and isinstance(native_kernel.get("supportedCapabilities"), list):
        native_kernel_capabilities = native_kernel.get("supportedCapabilities") or []
    print(f"Native kernel: contract={native_kernel.get('contractVersion') or native_kernel.get('kernelContractVersion') or 'unknown'} capabilities={len(native_kernel_capabilities)}")
    print(f"Downloaded runtime: ok={downloaded_runtime.get('ok')} activeId={output['activeDownloadedRuntimeId'] or 'unknown'} activeSha={output['activeDownloadedRuntimeSha'] or 'unknown'}")
    print(f"Active hot ops root: {active_root or 'unknown'}")
    print(f"Downloaded hot ops sync: ok={downloaded_sync.get('ok')} changed={downloaded_sync.get('changed')} feedBundleId={downloaded_sync.get('feedBundleId') or 'unknown'} cachedBundleId={downloaded_sync.get('cachedBundleId') or 'unknown'} moduleSha={downloaded_sync.get('moduleSha') or 'unknown'}")
    print(f"Canary op: {output['canaryOp']}")
    print(f"ADB: {output['adb']}")
    print(f"Android device: {output['androidDevice']}")
    if cleanup:
        print(
            "Native-control cleanup: "
            f"archived commands={cleanup.get('commandsArchived', 0)} results={cleanup.get('resultsArchived', 0)} "
            f"pending={cleanup.get('pendingCommands', 0)} delivered={cleanup.get('deliveredCommands', 0)} "
            f"archive={cleanup.get('archiveRoot') or 'none'}"
        )
    print(f"Failure classification: {failure}")
    if failure == "hot_operation_missing":
        print(f"Requested op: {requested_hot_operation or 'unknown'}")
        print(f"Available ops: {', '.join(available_hot_operations) if available_hot_operations else 'none'}")
    print(f"Next action: {output['nextAction']}")
    for item in debug:
        print(
            "Debug command: "
            f"label={item['label']} id={item['commandId']} clientId={item['clientId'] or 'unknown'} buildId={item['buildId'] or 'unknown'} "
            f"queued_at={item['queued_at'] or 'missing'} picked_up_at={item['picked_up_at'] or 'missing'} "
            f"completed_at={item['completed_at'] or 'missing'} uploaded_at={item['uploaded_at'] or 'missing'} "
            f"result_seen_at={item['result_seen_at'] or 'missing'} result.ok={item['result.ok']} "
            f"result.failureClassification={item['result.failureClassification'] or 'none'} "
            f"top-level={item['topLevelFailureClassification']} bridge_alive_source={item['bridge_alive_source']}"
        )
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
