#!/usr/bin/env python3
"""Submit one bounded production V6 Windows fixture and record exact evidence."""
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


ROOT = Path(__file__).resolve().parents[3]
CLOUD = Path("/home/ubuntu/.local/share/wasm-agent-cloud")
STATE = CLOUD / "state"
ORIGIN = "https://wa.colmeio.com"
FIXTURES = {
    "windows-list": {
        "objective": "List the visible top-level Windows application windows and report their application names.",
        "kind": "client_state",
        "expected_cap": "client.windows.desktop.windows.list",
        "expected_proof": "windows.desktop.top_level_windows",
    },
    "windows-describe": {
        "objective": "Describe the bounded Windows desktop automation capability, including its current authority and elevation limits.",
        "kind": "client_state",
        "expected_cap": "client.windows.desktop.describe",
        "expected_proof": "windows.desktop.capability_manifest",
    },
    "notepad-canary": {
        "objective": "Run the bounded Notepad UI Automation canary with marker MFV7-PILOT-SAFE and report the verified result.",
        "kind": "client_action",
        "expected_cap": "client.windows.notepad.uia_canary",
        "expected_proof": "windows.desktop.notepad_uia_canary",
    },
}


def env_value(path: Path, name: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip().strip('"').strip("'")
    raise RuntimeError(f"{name} missing")


def auth_cookie() -> tuple[str, str]:
    email = env_value(ROOT / "plugins/wasm-agent/conf/wa.env", "ADMIN_EMAIL").split(",", 1)[0]
    db = STATE / "db/sqlite/wa_db.sqlite3"
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as connection:
        row = connection.execute(
            "SELECT id FROM user_tb WHERE lower(email)=lower(?) ORDER BY last_login_at DESC LIMIT 1", (email,),
        ).fetchone()
    if not row:
        raise RuntimeError("admin user missing")
    issued = int(time.time())
    message = f"{int(row[0])}.{issued}"
    secret = (STATE / "db/sqlite/wa_auth_secret").read_text(encoding="utf-8").strip().encode()
    return str(row[0]), f"{message}.{hmac.new(secret, message.encode(), hashlib.sha256).hexdigest()}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", choices=sorted(FIXTURES))
    parser.add_argument("--session", required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    fixture = FIXTURES[args.fixture]
    user_id, cookie = auth_cookie()
    nonce = uuid.uuid4().hex[:16]
    body = {
        "protocol": "v6", "session_id": args.session, "turn_id": f"turn-{nonce}",
        "instructions": (
            "Use only bounded declared Windows capabilities. Do not use unrestricted shell or Browser JavaScript. "
            "Do not edit files, change settings, navigate the browser, access private content, or elevate. "
            "Require the capability-owned proof and answer honestly if unavailable."
        ),
        "max_output_tokens": 700,
        "envelope": {
            "schema": "hermes.wasm_agent.master_frontier.v6", "trace_id": nonce,
            "objective": fixture["objective"], "objective_kind": fixture["kind"],
            "surface": "avatar-chat", "route_id": "wasm-agent.avatar-chat.ui",
            "compact_state": {"fixture": args.fixture, "label": args.label},
            "capabilities": ["client.ui.inspect", "client.ui.control"],
            "budget": {"provider_call_ms_max": 90000, "task_lease_ms_max": 300000, "api_calls_max": 6},
        },
    }
    request = urllib.request.Request(
        f"{ORIGIN}/agent/provider/envelope", data=json.dumps(body).encode(),
        headers={"Cookie": f"wa_uid={cookie}", "Origin": ORIGIN, "Content-Type": "application/json", "User-Agent": "mf-v7-pilot/1"},
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=300) as response:
        result = json.loads(response.read(4 * 1024 * 1024))
    provider = result.get("provider") if isinstance(result.get("provider"), dict) else {}
    diagnostics = provider.get("diagnostics") if isinstance(provider.get("diagnostics"), dict) else {}
    tools = provider.get("local_tools") if isinstance(provider.get("local_tools"), list) else []
    matched = [item for item in tools if item.get("capability") == fixture["expected_cap"]]
    proof = {
        str(value) for item in (provider.get("evidence") or []) if isinstance(item, dict)
        for value in (item.get("proof") or [])
    }
    report = {
        "schema": "mf-v7.pilot.live-fixture.v1", "fixture": args.fixture, "label": args.label,
        "session_id": args.session, "run_id": result.get("run_id") or provider.get("run_id"),
        "user_id_hash": hashlib.sha256(user_id.encode()).hexdigest()[:16],
        "reply": result.get("reply"), "duration_ms": round((time.monotonic() - started) * 1000),
        "expected_capability": fixture["expected_cap"], "expected_proof": fixture["expected_proof"],
        "capability_used": len(matched) == 1, "capability_ok": bool(matched and matched[0].get("ok") is True),
        "proof_verified": fixture["expected_proof"] in proof,
        "provider_calls": diagnostics.get("provider_calls"),
        "procedure_memory": diagnostics.get("procedure_memory") if isinstance(diagnostics.get("procedure_memory"), dict) else {},
        "token_usage": diagnostics.get("token_usage_total"),
        "performance": diagnostics.get("performance"),
        "changed_files": provider.get("changed_files") or [],
    }
    report["ok"] = bool(
        report["run_id"] and report["reply"] and report["capability_used"]
        and report["capability_ok"] and report["proof_verified"] and not report["changed_files"]
    )
    output = Path(__file__).with_name("live-results") / f"{args.fixture}-{args.label}.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({**report, "output": str(output)}, separators=(",", ":")))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
