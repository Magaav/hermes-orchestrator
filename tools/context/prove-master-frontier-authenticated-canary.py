#!/usr/bin/env python3
"""Run one revocable, read-only authenticated Master:frontier canary."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import secrets
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "plugins/wasm-agent/server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from master_frontier import event_anchor_store  # noqa: E402

REPORTS = {
    "v5": ROOT / "reports/context/latest/master-frontier-authenticated-canary.json",
    "v6": ROOT / "reports/context/latest/master-frontier-v6-authenticated-canary.json",
}
OBJECTIVES = {
    "v5": "Read plugins/wasm-agent/MASTER_FRONTIER_V5.md and state its protocol name in one sentence. Do not modify files.",
    "v6": "Read MASTER_FRONTIER_V6.md and state its protocol name in one sentence. Do not modify files.",
}
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
    parser.add_argument("--protocol", choices=sorted(OBJECTIVES), default="v5")
    args = parser.parse_args()
    objective = OBJECTIVES[args.protocol]
    report_path = REPORTS[args.protocol]
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
    route["caps"] = ["repo.read"]
    body = {
        "protocol": args.protocol, "session_id": session_id, "turn_id": turn_id,
        "instructions": "Use only read/search evidence. Never edit or run a mutating command.",
        "max_output_tokens": 800,
        "envelope": {
            "schema": f"hermes.wasm_agent.master_frontier.{args.protocol}", "trace_id": nonce,
            "objective": objective, "objective_kind": "source-investigation", "surface": "avatar-chat",
            "route_id": route["route_id"], "route_contract": route,
            "compact_state": {"surface": "authenticated-production-canary", "route_id": route["route_id"]},
            "capabilities": route["caps"],
            "completion_capabilities": ["repo.read"],
            "allowed_actions": [{"id": "answer"}, {"id": "search"}, {"id": "read"}],
            "budget": {"head_tokens_max": 800, "provider_tokens_max": 6000, "api_calls_max": 4, "provider_call_ms_max": 90000, "task_lease_ms_max": 300000},
        },
    }
    report: dict[str, Any] = {
        "schema": "MF_AUTH_CLOUD/2", "ok": False, "origin": args.origin,
        "requestedProtocol": args.protocol, "scenario": "repository-read",
        "objectiveSha256": hashlib.sha256(objective.encode()).hexdigest(),
        "userRole": "user", "revoked": False,
    }
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
        integrity = provider.get("integrity_proof") if isinstance(provider.get("integrity_proof"), dict) else {}
        anchor_result = integrity.get("anchor") if isinstance(integrity.get("anchor"), dict) else {}
        diagnostics = provider.get("diagnostics") if isinstance(provider.get("diagnostics"), dict) else {}
        tools = provider.get("local_tools") if isinstance(provider.get("local_tools"), list) else []
        observed_protocol = (
            str(provider.get("protocol") or "")
            if args.protocol == "v6"
            else str((provider.get("envelope") or {}).get("schema") or "")
        )
        report.update({
            "httpStatus": status,
            "runId": result.get("run_id") or provider.get("run_id") or "",
            "protocol": observed_protocol,
            "replySha256": hashlib.sha256(str(result.get("reply") or "").encode()).hexdigest(),
            "nonemptyReply": bool(str(result.get("reply") or "").strip()),
            "upstreamError": result.get("error") if isinstance(result.get("error"), dict) else {},
        })
        if args.protocol == "v6":
            report["v6"] = {
                "schema": provider.get("schema") or "",
                "completionGatePassed": diagnostics.get("completion_gaps") == [],
                "exactUsageMeasured": (diagnostics.get("token_usage_total") or {}).get("exact") is True,
                "providerCalls": int(diagnostics.get("provider_calls") or 0),
                "repoReadSucceeded": any(
                    item.get("capability") == "repo.read" and item.get("ok") is True
                    for item in tools if isinstance(item, dict)
                ),
                "changedFiles": provider.get("changed_files") if isinstance(provider.get("changed_files"), list) else [],
            }
        report["integrityProof"] = {
            "status": integrity.get("status") or "",
            "anchorStatus": anchor_result.get("status") or "",
            "terminal": anchor_result.get("terminal") is True,
            "checkpoint": int(anchor_result.get("checkpoint") or 0),
        }
        anchor_store = event_anchor_store.EventAnchorStore(event_anchor_store.default_path(state))
        chain = (
            anchor_store.verify_chain(user_id=str(user_id), run_id=str(report["runId"]))
            if report["runId"]
            else {}
        )
        report["anchorChain"] = {
            "ok": chain.get("ok") is True,
            "final": chain.get("final") is True,
            "checkpoints": int(chain.get("checkpoints") or 0),
            "runRef": chain.get("run_ref") or "",
        }
        report["ok"] = bool(
            report["authenticated"]
            and status == 200
            and report["runId"]
            and report["nonemptyReply"]
            and (
                args.protocol == "v5"
                or (
                    report["protocol"] == "v6"
                    and report["v6"]["schema"] == "hermes.wasm_agent.master_frontier.final.v6"
                    and report["v6"]["completionGatePassed"]
                    and report["v6"]["exactUsageMeasured"]
                    and report["v6"]["repoReadSucceeded"]
                    and report["v6"]["changedFiles"] == []
                )
            )
            and report["integrityProof"]["status"] == "verified"
            and report["integrityProof"]["terminal"]
            and report["anchorChain"]["ok"]
            and report["anchorChain"]["final"]
        )
    finally:
        conn.execute("DELETE FROM synthetic_canary_grant_tb WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM user_tb WHERE id = ? AND provider = 'synthetic-canary'", (user_id,))
        conn.commit()
        conn.close()
        revoke_status, revoked = request_json(f"{args.origin}/auth/session", cookie=cookie, origin=args.origin)
        report["revoked"] = revoke_status == 200 and revoked.get("authenticated") is False
        report["ok"] = bool(report["ok"] and report["revoked"])
        report["checkedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, separators=(",", ":")))
    return 0 if report["ok"] else 1


if __name__ == "__main__": raise SystemExit(main())
