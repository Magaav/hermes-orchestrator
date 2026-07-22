#!/usr/bin/env python3
"""Run one revocable, read-only authenticated MF5 production canary."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/context/latest/master-frontier-authenticated-canary.json"
OBJECTIVE = "Read plugins/wasm-agent/MASTER_FRONTIER_V5.md and state its protocol name in one sentence. Do not modify files."


def request_json(url: str, *, cookie: str, origin: str, body: dict[str, Any] | None = None, timeout: float = 240) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers={
        "Cookie": f"wa_uid={cookie}", "Origin": origin, "Content-Type": "application/json",
        "User-Agent": "wasm-agent-authenticated-canary/1",
    })
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        payload = json.loads(response.read(2 * 1024 * 1024))
        return int(response.status), payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="https://wa.colmeio.com")
    parser.add_argument("--cloud-root", type=Path, default=Path("/home/ubuntu/.local/share/wasm-agent-cloud"))
    args = parser.parse_args()
    state = args.cloud_root / "state"
    db_path = state / "db/sqlite/wa_db.sqlite3"
    secret_path = state / "db/sqlite/wa_auth_secret"
    nonce = secrets.token_hex(8)
    user_id = 820000000000000000 + secrets.randbelow(9000000000000000)
    session_id = f"canary-{nonce}"
    turn_id = f"turn-{nonce}"
    issued = int(time.time())
    message = f"{user_id}.{issued}"
    signing_secret = secret_path.read_text(encoding="utf-8").strip().encode("utf-8")
    cookie = f"{message}.{hmac.new(signing_secret, message.encode(), hashlib.sha256).hexdigest()}"
    route = next(item for item in json.loads((ROOT / "plugins/wasm-agent/server/agent_route_contracts.json").read_text())["routes"] if item["route_id"] == "wasm-agent.avatar-chat.ui")
    route = dict(route)
    route["workspace_root"] = str(ROOT / "plugins/wasm-agent")
    route["cwd"] = route["workspace_root"]
    route["allowed_read_roots"] = [route["workspace_root"]]
    route["allowed_write_roots"] = []
    body = {
        "protocol": "v5", "session_id": session_id, "turn_id": turn_id,
        "instructions": "Use only read/search evidence. Never edit or run a mutating command.",
        "max_output_tokens": 800,
        "envelope": {
            "schema": "hermes.wasm_agent.master_frontier.v5", "trace_id": nonce,
            "objective": OBJECTIVE, "objective_kind": "source-investigation", "surface": "avatar-chat",
            "route_id": route["route_id"], "route_contract": route,
            "compact_state": {"surface": "authenticated-production-canary", "route_id": route["route_id"]},
            "capabilities": ["repo.read", "proof.report"],
            "allowed_actions": [{"id": "answer"}, {"id": "search"}, {"id": "read"}],
            "budget": {"head_tokens_max": 800, "provider_tokens_max": 6000, "api_calls_max": 4, "provider_call_ms_max": 90000, "task_lease_ms_max": 300000},
        },
    }
    report: dict[str, Any] = {"schema": "MF_AUTH_CLOUD/1", "ok": False, "origin": args.origin, "objectiveSha256": hashlib.sha256(OBJECTIVE.encode()).hexdigest(), "userRole": "user", "revoked": False}
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS synthetic_canary_grant_tb (user_id INTEGER PRIMARY KEY, objective_sha256 TEXT NOT NULL, session_id TEXT NOT NULL, expires_at INTEGER NOT NULL, created_at INTEGER NOT NULL)")
        conn.execute("INSERT INTO user_tb (id,provider,provider_sub,email,email_verified,name,picture_url,created_at,updated_at,last_login_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (user_id,"synthetic-canary",nonce,f"canary-{nonce}@invalid",1,"Production Canary","",issued,issued,issued))
        conn.execute("INSERT INTO synthetic_canary_grant_tb VALUES (?,?,?,?,?)", (user_id, report["objectiveSha256"], session_id, issued + 300, issued))
        conn.commit()
        auth_status, auth = request_json(f"{args.origin}/auth/session", cookie=cookie, origin=args.origin)
        report["authenticated"] = auth_status == 200 and auth.get("authenticated") is True and (auth.get("user") or {}).get("role") == "user"
        status, result = request_json(f"{args.origin}/agent/canary/envelope", cookie=cookie, origin=args.origin, body=body)
        provider = result.get("provider") if isinstance(result.get("provider"), dict) else {}
        report.update({"httpStatus": status, "runId": result.get("run_id") or provider.get("run_id") or "", "protocol": (provider.get("envelope") or {}).get("schema") or "", "replySha256": hashlib.sha256(str(result.get("reply") or "").encode()).hexdigest(), "nonemptyReply": bool(str(result.get("reply") or "").strip())})
        report["ok"] = bool(report["authenticated"] and status == 200 and report["runId"] and report["nonemptyReply"])
    finally:
        conn.execute("DELETE FROM synthetic_canary_grant_tb WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM user_tb WHERE id = ? AND provider = 'synthetic-canary'", (user_id,))
        conn.commit()
        conn.close()
        revoke_status, revoked = request_json(f"{args.origin}/auth/session", cookie=cookie, origin=args.origin)
        report["revoked"] = revoke_status == 200 and revoked.get("authenticated") is False
        report["ok"] = bool(report["ok"] and report["revoked"])
        report["checkedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, separators=(",", ":")))
    return 0 if report["ok"] else 1


if __name__ == "__main__": raise SystemExit(main())
