#!/usr/bin/env python3
"""Prove the one-call, proof-owned production CDP lifecycle reporting path."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/context/latest/master-frontier-v6-cdp-lifecycle-golden.json"
PROMISE_ID = "master-frontier-v6-cdp-lifecycle-golden"
OBJECTIVE = "Read-only: report the current persistent browser lifecycle state. Do not navigate, open, close, or modify anything."
VALID_REPLY = re.compile(r"\b(?:closed|open_no_page|open_page)\b")
REQUIRED_CLIENT_CAPABILITIES = {"control.agent.session.new", "control.agent.prompt.submit"}


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def env_value(path: Path, name: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    raise RuntimeError(f"{name.lower()}_missing")


def select_renderer(state: Path, *, freshness_sec: int = 45) -> str:
    now = time.time()
    candidates = sorted((state / "live-clients").glob("electron-renderer-*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates:
        payload = read_json(path)
        if now - path.stat().st_mtime <= freshness_sec and REQUIRED_CLIENT_CAPABILITIES <= set(payload.get("capabilities") or []):
            return str(payload.get("device_id") or payload.get("client_id") or path.stem)
    raise RuntimeError("fresh_agent_renderer_missing")


def request_json(url: str, key: str, body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json",
        "X-Wasm-Agent-Native-Control-Key": key,
        "User-Agent": "wasm-agent-cdp-lifecycle-golden-proof/1",
    })
    try:
        response = urllib.request.urlopen(request, timeout=15)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        payload = json.loads(response.read(512 * 1024))
    if int(response.status) != 200 or payload.get("ok") is not True:
        raise RuntimeError("native_control_command_rejected")
    return payload


def queue(origin: str, key: str, device_id: str, command: str, payload: dict[str, Any], prefix: str) -> str:
    command_id = f"{prefix}-{uuid.uuid4().hex[:12]}"
    result = request_json(f"{origin.rstrip('/')}/native/control/command", key, {
        "device_id": device_id, "command": command, "command_id": command_id,
        "payload": payload, "reason": "automated read-only CDP lifecycle golden-path proof",
    })
    return str((result.get("command") or {}).get("id") or command_id)


def wait_command(state: Path, device_id: str, command_id: str, timeout_sec: int = 25) -> dict[str, Any]:
    directory = state / "native-control/results" / device_id
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        for path in directory.glob("*.json"):
            payload = read_json(path)
            if str(payload.get("command_id") or "") == command_id:
                return payload
        time.sleep(0.5)
    raise RuntimeError(f"{command_id.split('-', 1)[0]}_receipt_timeout")


def wait_run(db_path: Path, created_after_ms: int, timeout_sec: int = 120) -> tuple[str, dict[str, Any]]:
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


def evaluate(final: dict[str, Any]) -> tuple[dict[str, bool], dict[str, Any]]:
    reply = str(final.get("reply") or "").strip()
    diagnostics = final.get("diagnostics") if isinstance(final.get("diagnostics"), dict) else {}
    tools = final.get("local_tools") if isinstance(final.get("local_tools"), list) else []
    calls = int(diagnostics.get("provider_calls") or 0)
    gaps = diagnostics.get("completion_gaps") if isinstance(diagnostics.get("completion_gaps"), list) else ["missing"]
    status_tools = [item for item in tools if isinstance(item, dict) and item.get("capability") == "client.windows.browser.cdp.status"]
    checks = {
        "typedLifecycleAnswer": bool(VALID_REPLY.search(reply)),
        "exactlyOneProviderCall": calls == 1,
        "zeroCompletionGaps": gaps == [],
        "exactlyOneReadOnlyStatusOperation": len(tools) == 1 and len(status_tools) == 1 and status_tools[0].get("ok") is True,
        "noStallDiagnostic": not bool(diagnostics.get("stall_diagnostic")),
    }
    usage = final.get("token_usage") if isinstance(final.get("token_usage"), dict) else {}
    measurements = {
        "providerCalls": calls, "completionGaps": gaps,
        "totalTokens": int(usage.get("total_tokens") or 0),
        "inputTokens": int(usage.get("input_tokens") or 0),
        "outputTokens": int(usage.get("output_tokens") or 0),
        "reply": reply[:240],
        "capabilities": [str(item.get("capability") or "") for item in tools if isinstance(item, dict)],
    }
    return checks, measurements


def self_test() -> int:
    good = {
        "reply": "The persistent CDP realm is open_page.",
        "diagnostics": {"provider_calls": 1, "completion_gaps": []},
        "local_tools": [{"capability": "client.windows.browser.cdp.status", "ok": True}],
        "token_usage": {"total_tokens": 11249},
    }
    checks, _ = evaluate(good)
    regressions = []
    for name, mutate in (
        ("calls", lambda value: value["diagnostics"].update(provider_calls=2)),
        ("gaps", lambda value: value["diagnostics"].update(completion_gaps=["completion:goal_action"])),
        ("answer", lambda value: value.update(reply="Status observed.")),
        ("mutation", lambda value: value["local_tools"].append({"capability": "client.windows.browser.cdp.navigate", "ok": True})),
    ):
        candidate = json.loads(json.dumps(good))
        mutate(candidate)
        candidate_checks, _ = evaluate(candidate)
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
    state = args.cloud_root / "state"
    report: dict[str, Any] = {
        "schema": "MF6_CDP_LIFECYCLE_GOLDEN/1", "status": "fail", "promiseId": PROMISE_ID,
        "claim": "Production CDP lifecycle reporting is truthful and completes in one provider call.",
        "objectiveSha256": hashlib.sha256(OBJECTIVE.encode()).hexdigest(),
    }
    try:
        key = env_value(ROOT / "plugins/wasm-agent/conf/wa.env", "WASM_AGENT_NATIVE_CONTROL_KEY")
        device_id = select_renderer(state)
        session_id = queue(args.origin, key, device_id, "agent_session_new", {}, "cdp-life-session")
        session_receipt = wait_command(state, device_id, session_id)
        if session_receipt.get("ok") is not True or ((session_receipt.get("result") or {}).get("input_empty") is not True):
            raise RuntimeError("clean_session_unproven")
        created_after_ms = int(time.time() * 1000) - 1000
        prompt_id = queue(args.origin, key, device_id, "agent_prompt_submit", {"message": OBJECTIVE}, "cdp-life-prompt")
        prompt_receipt = wait_command(state, device_id, prompt_id)
        if prompt_receipt.get("ok") is not True:
            raise RuntimeError("prompt_submission_unproven")
        run_id, final = wait_run(state / "db/sqlite/wa_db.sqlite3", created_after_ms)
        checks, measurements = evaluate(final)
        ok = all(checks.values())
        report.update({
            "status": "pass" if ok else "fail", "runId": run_id, "deviceId": device_id,
            "checks": checks, "measurements": measurements,
            "evidence": [str(REPORT.relative_to(ROOT))],
            "summary": "One-call CDP lifecycle golden path passed." if ok else "CDP lifecycle golden path regressed.",
            "failureClass": None if ok else "cdp_lifecycle_golden_regression",
            "nextSuggestedSteps": [] if ok else ["Inspect the persisted run before changing prompts or token ceilings."],
        })
    except (OSError, sqlite3.Error, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        report.update({"failureClass": str(exc)[:160], "summary": "CDP lifecycle golden proof could not complete."})
    report["durationMs"] = round((time.monotonic() - started) * 1000)
    report["checkedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return 0 if report.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
