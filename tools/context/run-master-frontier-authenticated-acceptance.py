#!/usr/bin/env python3
"""Run one bounded authenticated Master:frontier production acceptance."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sqlite3
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CLOUD = Path("/home/ubuntu/.local/share/wasm-agent-cloud")


def env_value(path: Path, name: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip().strip('"').strip("'")
    raise RuntimeError(f"{name} is not configured")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--objective-file", type=Path, required=True)
    parser.add_argument("--route-id", default="wasm-agent.space.ui")
    parser.add_argument("--origin", default="https://wa.colmeio.com")
    parser.add_argument("--cloud-root", type=Path, default=DEFAULT_CLOUD)
    parser.add_argument("--allow-write", action="store_true", help="Required for implementation acceptance")
    parser.add_argument("--report", type=Path, default=ROOT / "reports/context/latest/master-frontier-authenticated-acceptance.json")
    args = parser.parse_args()
    if not args.allow_write:
        parser.error("implementation acceptance requires explicit --allow-write")

    objective = args.objective_file.read_text(encoding="utf-8").strip()
    if not objective:
        parser.error("objective file is empty")
    state = args.cloud_root / "state"
    email = env_value(ROOT / "plugins/wasm-agent/conf/wa.env", "ADMIN_EMAIL")
    with sqlite3.connect(state / "db/sqlite/wa_db.sqlite3") as conn:
        row = conn.execute(
            "SELECT id FROM user_tb WHERE lower(email)=lower(?) ORDER BY last_login_at DESC LIMIT 1",
            (email,),
        ).fetchone()
    if not row:
        raise RuntimeError("configured admin user was not found")
    issued = int(time.time())
    message = f"{int(row[0])}.{issued}"
    secret = (state / "db/sqlite/wa_auth_secret").read_text(encoding="utf-8").strip().encode()
    cookie = f"{message}.{hmac.new(secret, message.encode(), hashlib.sha256).hexdigest()}"
    nonce = uuid.uuid4().hex[:12]
    session_id = f"agent_accept_{nonce}"
    body = {
        "protocol": "v5", "session_id": session_id, "turn_id": f"turn_{nonce}",
        "route_id": args.route_id,
        "instructions": "Implement the request in the routed repository. Use repository tools, run the declared focused test, inspect the diff, and report only verified results.",
        "max_output_tokens": 1800, "text_verbosity": "low",
        "envelope": {
            "schema": "hermes.wasm_agent.master_frontier.v5", "trace_id": nonce,
            "objective": objective, "objective_kind": "implementation", "surface": "avatar-chat",
            "route_id": args.route_id,
            "compact_state": {"surface": "avatar-chat", "route_id": args.route_id, "target": "Master:frontier"},
            "capabilities": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_actions": [{"id": "answer"}, {"id": "dispatch.hermes", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"]}],
            "constraints": ["Use only the declared route contract.", "Do not claim completion without an applied mutation and focused test proof."],
            "proof_requests": ["route_id", "changed_files", "checks", "token_ledger"],
            "budget": {"enforcement": "hard", "head_tokens_max": 3000, "input_tokens_max": 12000, "provider_tokens_max": 50000, "api_calls_max": 8, "provider_call_ms_max": 90000, "task_lease_ms_max": 900000},
            "stream": True,
        },
    }
    request = urllib.request.Request(
        args.origin.rstrip("/") + "/agent/provider/envelope/stream",
        data=json.dumps(body).encode(), method="POST",
        headers={"Cookie": f"wa_uid={cookie}", "Origin": args.origin, "Content-Type": "application/json", "User-Agent": "master-frontier-production-acceptance/1"},
    )
    report = {"schema": "MF_AUTH_ACCEPTANCE/1", "session_id": session_id, "route_id": args.route_id, "objective_sha256": hashlib.sha256(objective.encode()).hexdigest(), "terminal": False, "events": []}
    print(json.dumps({"phase": "submitted", "session_id": session_id}), flush=True)
    with urllib.request.urlopen(request, timeout=1000) as response:
        for raw in response:
            if not raw.strip():
                continue
            item = json.loads(raw)
            if item.get("type") not in {"run", "action", "final", "error"}:
                continue
            agent = item.get("agent") if isinstance(item.get("agent"), dict) else {}
            compact = {"type": item.get("type"), "run_id": agent.get("run_id") or item.get("run_id") or ""}
            if item.get("type") in {"final", "error"}:
                compact["status"] = agent.get("status") or item.get("status") or ""
                compact["reply"] = agent.get("reply") or item.get("reply") or ""
                compact["error"] = agent.get("error") or item.get("error") or None
                report["terminal"] = True
            report["events"].append(compact)
            print(json.dumps(compact, default=str), flush=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return 0 if report["terminal"] and report["events"][-1]["type"] == "final" else 1


if __name__ == "__main__":
    raise SystemExit(main())
