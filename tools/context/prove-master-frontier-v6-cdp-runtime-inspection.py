#!/usr/bin/env python3
"""Prove production getter-safe CDP runtime inspection from an empty client session."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/context/latest/master-frontier-v6-cdp-runtime-inspection.json"
PROMISE_ID = "master-frontier-v6-cdp-runtime-inspection"
OBJECTIVE = (
    "Read-only: use the browser runtime inspector to inspect exact visible text hi in the current persistent browser tab. "
    "Report whether it is found and what runtime evidence identifies it. Do not navigate, click, type, or modify anything."
)
MUTATING_CAPABILITIES = {
    "client.windows.browser.cdp.act", "client.windows.browser.cdp.navigate",
    "client.windows.browser.cdp.transaction", "client.windows.browser.cdp.procedure",
}


def golden_module() -> Any:
    path = ROOT / "tools/context/prove-master-frontier-v6-cdp-lifecycle-golden.py"
    spec = importlib.util.spec_from_file_location("cdp_lifecycle_golden", path)
    if not spec or not spec.loader:
        raise RuntimeError("cdp_lifecycle_golden_import_failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait_run(db_path: Path, created_after_ms: int, timeout_sec: int = 180) -> tuple[str, dict[str, Any]]:
    digest = hashlib.sha256(OBJECTIVE.encode()).hexdigest()
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        with sqlite3.connect(db_path, timeout=10) as connection:
            row = connection.execute(
                "SELECT run_id,status,final_json FROM agent_run_tb "
                "WHERE json_extract(request_summary_json,'$.message_sha256')=? "
                "AND json_extract(request_summary_json,'$.created_at')>=? "
                "ORDER BY json_extract(request_summary_json,'$.created_at') DESC LIMIT 1",
                (digest, created_after_ms),
            ).fetchone()
        if row and str(row[1]) != "running":
            return str(row[0]), json.loads(str(row[2] or "{}"))
        time.sleep(1)
    raise RuntimeError("agent_run_timeout")


def request_class(db_path: Path, run_id: str) -> str:
    with sqlite3.connect(db_path, timeout=10) as connection:
        row = connection.execute(
            "SELECT payload_json FROM agent_run_event_tb WHERE run_id=? AND type='route.resolved' ORDER BY seq DESC LIMIT 1",
            (run_id,),
        ).fetchone()
    payload = json.loads(str(row[0] or "{}")) if row else {}
    route = payload.get("route_contract") if isinstance(payload.get("route_contract"), dict) else {}
    contract = route.get("task_contract") if isinstance(route.get("task_contract"), dict) else {}
    return str(contract.get("request_class") or "")


def evaluate(final: dict[str, Any], resolved_class: str) -> tuple[dict[str, bool], dict[str, Any]]:
    reply = " ".join(str(final.get("reply") or "").split())
    diagnostics = final.get("diagnostics") if isinstance(final.get("diagnostics"), dict) else {}
    tools = [item for item in (final.get("local_tools") or []) if isinstance(item, dict)]
    runtime = [item for item in tools if item.get("capability") == "client.windows.browser.cdp.runtime.inspect"]
    capabilities = {str(item.get("capability") or "") for item in tools}
    checks = {
        "runtimeInspectionClass": resolved_class == "runtime_inspection",
        "oneSuccessfulRuntimeInspection": len(runtime) == 1 and runtime[0].get("ok") is True,
        "noMutation": not bool(capabilities & MUTATING_CAPABILITIES),
        "zeroCompletionGaps": diagnostics.get("completion_gaps") == [],
        "boundedProviderCalls": 0 <= int(diagnostics.get("provider_calls") or 0) <= 3,
        "typedFinding": bool(re.search(r"\b(?:was|is) (?:not )?found\b", reply, re.I)),
        "runtimeIdentity": bool(re.search(r"\btarget(?:Id| ID)\b", reply)) and bool(re.search(r"\br-[0-9a-f]{16}\b", reply, re.I)),
        "getterSafeAnswer": bool(re.search(r"\bzero getter invocations\b", reply, re.I)),
        "readOnlyAnswer": "read-only" in reply.lower(),
    }
    return checks, {
        "requestClass": resolved_class,
        "providerCalls": int(diagnostics.get("provider_calls") or 0),
        "completionGaps": diagnostics.get("completion_gaps"),
        "capabilities": sorted(capabilities),
        "reply": reply[:600],
    }


def self_test() -> int:
    good = {
        "reply": "The exact visible text hi was not found. Inspection was read-only with zero getter invocations; revision r-56e95ebd8762d643 and targetId ABCDEF0123456789 identify the runtime evidence.",
        "diagnostics": {"provider_calls": 2, "completion_gaps": []},
        "local_tools": [{"capability": "client.windows.browser.cdp.runtime.inspect", "ok": True}],
    }
    checks, _ = evaluate(good, "runtime_inspection")
    regressions = []
    for mutate in (
        lambda value: value["diagnostics"].update(completion_gaps=["completion:goal_action"]),
        lambda value: value["local_tools"].append({"capability": "client.windows.browser.cdp.act", "ok": True}),
        lambda value: value.update(reply="Inspection acknowledged."),
    ):
        candidate = json.loads(json.dumps(good))
        mutate(candidate)
        candidate_checks, _ = evaluate(candidate, "runtime_inspection")
        regressions.append(not all(candidate_checks.values()))
    ok = all(checks.values()) and all(regressions)
    print(json.dumps({"status": "pass" if ok else "fail", "promiseId": PROMISE_ID, "selfTest": True}, separators=(",", ":")))
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="http://127.0.0.1:8878")
    parser.add_argument("--cloud-root", type=Path, default=Path("/home/ubuntu/.local/share/wasm-agent-cloud"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    started = time.monotonic()
    report: dict[str, Any] = {
        "schema": "MF6_CDP_RUNTIME_INSPECTION/1", "status": "fail", "promiseId": PROMISE_ID,
        "claim": "Production Avatar Chat completes getter-safe CDP runtime inspection from an empty client session.",
        "objectiveSha256": hashlib.sha256(OBJECTIVE.encode()).hexdigest(),
    }
    try:
        golden = golden_module()
        state = args.cloud_root / "state"
        database = state / "db/sqlite/wa_db.sqlite3"
        key = golden.env_value(ROOT / "plugins/wasm-agent/conf/wa.env", "WASM_AGENT_NATIVE_CONTROL_KEY")
        device_id = golden.select_renderer(state)
        session_id = golden.queue(args.origin, key, device_id, "agent_session_new", {}, "runtime-inspect-session")
        session_receipt = golden.wait_command(state, device_id, session_id, timeout_sec=30)
        empty = session_receipt.get("ok") is True and ((session_receipt.get("result") or {}).get("input_empty") is True)
        if not empty:
            raise RuntimeError("clean_session_unproven")
        created_after_ms = int(time.time() * 1000) - 1000
        prompt_id = golden.queue(args.origin, key, device_id, "agent_prompt_submit", {"message": OBJECTIVE}, "runtime-inspect-prompt")
        if golden.wait_command(state, device_id, prompt_id, timeout_sec=30).get("ok") is not True:
            raise RuntimeError("prompt_submission_unproven")
        run_id, final = wait_run(database, created_after_ms)
        resolved_class = request_class(database, run_id)
        checks, measurements = evaluate(final, resolved_class)
        ok = all(checks.values())
        report.update({
            "status": "pass" if ok else "fail", "runId": run_id, "deviceId": device_id,
            "checks": {"emptySession": empty, **checks}, "measurements": measurements,
            "evidence": [str(REPORT.relative_to(ROOT))],
            "summary": "Getter-safe CDP runtime inspection passed from an empty production client session." if ok else "CDP runtime inspection golden path regressed.",
            "failureClass": None if ok else "cdp_runtime_inspection_regression",
            "nextSuggestedSteps": [] if ok else ["Inspect the persisted route contract, transition evidence, receipt proof, and completion gaps before changing prompts."],
        })
    except (OSError, sqlite3.Error, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        report.update({"failureClass": str(exc)[:160], "summary": "CDP runtime inspection proof could not complete."})
    report["durationMs"] = round((time.monotonic() - started) * 1000)
    report["checkedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return 0 if report.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
