#!/usr/bin/env python3
"""Prove active-space identity, grounding, and provider status in production."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATE = Path("/home/ubuntu/.local/share/wasm-agent-cloud/state")
DB = STATE / "db/sqlite/wa_db.sqlite3"
ORIGIN = "https://wa.colmeio.com"
SESSION_ID = "agent_mt1xwmzj_o77v93"
SPACE = {"id": "space_mqzddgni_2vzsq", "name": "Realure", "display_name": "Realure"}
OBJECTIVE = "What space am I viewing, and what evidence proves its name?"
REPORT = ROOT / "reports/context/latest/master-frontier-active-space-proof.json"


def env_value(name: str) -> str:
    path = ROOT / "plugins/wasm-agent/conf/wa.env"
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    raise RuntimeError(f"{name} is not configured")


def admin_cookie() -> str:
    email = env_value("ADMIN_EMAIL").split(",", 1)[0].strip()
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as connection:
        row = connection.execute(
            "SELECT id FROM user_tb WHERE lower(email)=lower(?) ORDER BY last_login_at DESC LIMIT 1",
            (email,),
        ).fetchone()
    if not row:
        raise RuntimeError("configured admin user was not found")
    issued = int(time.time())
    message = f"{int(row[0])}.{issued}"
    secret = (STATE / "db/sqlite/wa_auth_secret").read_text(encoding="utf-8").strip().encode()
    return f"{message}.{hmac.new(secret, message.encode(), hashlib.sha256).hexdigest()}"


def post(body: dict) -> dict:
    request = urllib.request.Request(
        f"{ORIGIN}/agent/provider/envelope",
        data=json.dumps(body).encode(),
        headers={
            "Cookie": f"wa_uid={admin_cookie()}",
            "Origin": ORIGIN,
            "Content-Type": "application/json",
            "User-Agent": "wasm-agent-active-space-proof/1",
        },
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read(4 * 1024 * 1024))


def main() -> int:
    turn_id = f"active-space-proof-{uuid.uuid4().hex[:16]}"
    transcript = [
        {"role": "user", "content": "Hello, can you see what space I am looking at?"},
        {"role": "assistant", "content": "I need to inspect the active client state before naming it."},
        {"role": "user", "content": OBJECTIVE},
    ]
    body = {
        "protocol": "v6",
        "session_id": SESSION_ID,
        "turn_id": turn_id,
        "space_id": SPACE["id"],
        "space_name": SPACE["name"],
        "active_space": SPACE,
        "transcript": transcript,
        "instructions": "Inspect the live client. Name the active space only from returned evidence and state the evidence field used. Do not infer a name from the product or origin.",
        "max_output_tokens": 900,
        "envelope": {
            "schema": "hermes.wasm_agent.master_frontier.v6",
            "trace_id": turn_id,
            "objective": OBJECTIVE,
            "objective_kind": "conversation",
            "surface": "avatar-chat",
            "route_id": "wasm-agent.avatar-chat.ui",
            "compact_state": {"surface": "avatar-chat", "route_id": "wasm-agent.avatar-chat.ui", "workspace": {"active_space": SPACE}, "transcript": transcript},
            "capabilities": ["client.ui.inspect"],
            "completion_capabilities": ["client.inspect"],
            "allowed_actions": [{"id": "answer"}, {"id": "client.inspect"}],
            "budget": {"provider_call_ms_max": 90000, "task_lease_ms_max": 300000},
        },
    }
    result = post(body)
    provider = result.get("provider") if isinstance(result.get("provider"), dict) else result
    run_id = str(result.get("run_id") or provider.get("run_id") or "")
    with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM agent_run_tb WHERE run_id=?", (run_id,)).fetchone()
    request_summary = json.loads(row["request_summary_json"] or "{}") if row else {}
    final = json.loads(row["final_json"] or "{}") if row else {}
    diagnostics = final.get("diagnostics") if isinstance(final.get("diagnostics"), dict) else {}
    usage = diagnostics.get("token_usage_total") if isinstance(diagnostics.get("token_usage_total"), dict) else {}
    tools = final.get("local_tools") if isinstance(final.get("local_tools"), list) else []
    inspect_ok = any(item.get("capability") == "client.inspect" and item.get("ok") is True for item in tools if isinstance(item, dict))
    reply = str(final.get("reply") or result.get("reply") or "")
    checks = {
        "completed": bool(row and row["status"] == "completed"),
        "replyNamesRealure": "realure" in reply.lower(),
        "inspectEvidenceOk": inspect_ok,
        "requestSpaceId": request_summary.get("space_id") == SPACE["id"],
        "requestSpaceName": str(request_summary.get("space_name") or "").lower() == "realure",
        "contextWindowReported": int(usage.get("context_window_tokens") or 0) > 0,
        "sevenDayReported": isinstance((usage.get("rate_limits") or {}).get("seven_day"), dict),
        "completionGatePassed": diagnostics.get("completion_gaps") == [],
    }
    report = {
        "schema": "hermes.wasm_agent.master_frontier_active_space_proof.v1",
        "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ok": all(checks.values()),
        "origin": ORIGIN,
        "sessionId": SESSION_ID,
        "runId": run_id,
        "turnId": turn_id,
        "activeSpace": SPACE,
        "reply": reply,
        "checks": checks,
        "telemetry": {
            "activeContextTokens": usage.get("active_context_tokens"),
            "contextWindowTokens": usage.get("context_window_tokens"),
            "sevenDay": (usage.get("rate_limits") or {}).get("seven_day"),
        },
        "redacted": True,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, separators=(",", ":")))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
