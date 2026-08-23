#!/usr/bin/env python3
"""Prove one admin-authorized V6 Browser-widget action in the installed Electron app."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "plugins/wasm-agent/server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import live_clients  # noqa: E402
from master_frontier import event_anchor_store  # noqa: E402


REPORT = ROOT / "reports/context/latest/master-frontier-v6-client-ui.json"
OBJECTIVE = "Open the Browser widget on the live Electron client and report only after the client acknowledges it."


def env_value(path: Path, name: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    raise RuntimeError(f"{name} is not configured")


def request_json(
    url: str, *, cookie: str, origin: str, body: dict[str, Any] | None = None,
    timeout: float = 240,
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers={
        "Cookie": f"wa_uid={cookie}", "Origin": origin,
        "Content-Type": "application/json", "User-Agent": "wasm-agent-v6-client-ui-proof/1",
    })
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        payload = json.loads(response.read(2 * 1024 * 1024))
        return int(response.status), payload


def live_electron_clients(state: Path) -> list[dict[str, Any]]:
    payload = live_clients.list_clients(state, native_root=state / "native-control")
    return [
        item for item in (payload.get("clients") or [])
        if isinstance(item, dict)
        and item.get("live") is True
        and item.get("runtime_type") == "electron"
        and "control.widget.open" in set(item.get("capabilities") or [])
    ]


def command_artifact(state: Path, command_id: str) -> tuple[Path | None, dict[str, Any]]:
    matches = list((state / "native-control/commands").glob(f"*/{command_id}.json"))
    if len(matches) != 1:
        return None, {}
    try:
        payload = json.loads(matches[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return matches[0], {}
    return matches[0], payload if isinstance(payload, dict) else {}


def main() -> int:
    started_monotonic = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="https://wa.colmeio.com")
    parser.add_argument("--cloud-root", type=Path, default=Path("/home/ubuntu/.local/share/wasm-agent-cloud"))
    args = parser.parse_args()
    state = args.cloud_root / "state"
    clients_before = live_electron_clients(state)
    report: dict[str, Any] = {
        "schema": "MF6_CLIENT_UI_PRODUCTION/1", "ok": False, "origin": args.origin,
        "objectiveSha256": hashlib.sha256(OBJECTIVE.encode()).hexdigest(),
        "liveElectronBefore": len(clients_before), "userRole": "admin",
    }
    if not clients_before:
        report["error"] = {"code": "live_electron_client_missing"}
        report["durationMs"] = round((time.monotonic() - started_monotonic) * 1000)
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, separators=(",", ":")))
        return 1

    admin_email = env_value(ROOT / "plugins/wasm-agent/conf/wa.env", "ADMIN_EMAIL").split(",", 1)[0].strip()
    db_path = state / "db/sqlite/wa_db.sqlite3"
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT id FROM user_tb WHERE lower(email)=lower(?) ORDER BY last_login_at DESC LIMIT 1",
            (admin_email,),
        ).fetchone()
    if not row:
        raise RuntimeError("configured admin user was not found")
    issued = int(time.time())
    message = f"{int(row[0])}.{issued}"
    secret = (state / "db/sqlite/wa_auth_secret").read_text(encoding="utf-8").strip().encode()
    cookie = f"{message}.{hmac.new(secret, message.encode(), hashlib.sha256).hexdigest()}"
    nonce = uuid.uuid4().hex[:16]
    body = {
        "protocol": "v6", "session_id": f"v6-client-ui-{nonce}", "turn_id": f"turn-{nonce}",
        "instructions": "Use only the declared client inspect/open-widget operations. Open widget id browser; do not navigate, reload, edit files, or claim success without the acknowledged receipt.",
        "max_output_tokens": 800,
        "envelope": {
            "schema": "hermes.wasm_agent.master_frontier.v6", "trace_id": nonce,
            "objective": OBJECTIVE, "objective_kind": "model_decision", "surface": "avatar-chat",
            "route_id": "wasm-agent.avatar-chat.ui",
            "compact_state": {"surface": "production-installed-client-proof", "route_id": "wasm-agent.avatar-chat.ui"},
            "capabilities": ["client.ui.inspect", "client.ui.control"],
            "allowed_actions": [{"id": "answer"}, {"id": "client.inspect"}, {"id": "client.widget.open"}],
            "budget": {"provider_call_ms_max": 90000, "task_lease_ms_max": 300000},
        },
    }
    auth_status, auth = request_json(f"{args.origin}/auth/session", cookie=cookie, origin=args.origin)
    report["authenticatedAdmin"] = bool(
        auth_status == 200 and auth.get("authenticated") is True
        and (auth.get("user") or {}).get("role") == "admin"
    )
    status, result = request_json(
        f"{args.origin}/agent/provider/envelope", cookie=cookie, origin=args.origin, body=body,
    )
    provider = result.get("provider") if isinstance(result.get("provider"), dict) else {}
    diagnostics = provider.get("diagnostics") if isinstance(provider.get("diagnostics"), dict) else {}
    tools = provider.get("local_tools") if isinstance(provider.get("local_tools"), list) else []
    widget_tools = [
        item for item in tools
        if isinstance(item, dict) and item.get("capability") == "client.widget.open"
    ]
    operations = {str(item.get("operation") or "") for item in widget_tools}
    command_ids = [
        str(proof)
        for item in (provider.get("evidence") or []) if isinstance(item, dict)
        and str(item.get("subject") or "").removeprefix("operation:") in operations
        for proof in (item.get("proof") or [])
        if str(proof).startswith("cmd-")
    ]
    command_path, command = command_artifact(state, command_ids[0]) if len(command_ids) == 1 else (None, {})
    command_result = command.get("result") if isinstance(command.get("result"), dict) else {}
    acknowledged = bool(
        len(widget_tools) == 1 and widget_tools[0].get("ok") is True
        and widget_tools[0].get("status") == "acknowledged"
    )
    command_verified = bool(
        command_path and command.get("status") == "finished" and command.get("type") == "open_widget"
        and (command.get("payload") or {}).get("widget_id") == "browser"
        and command_result.get("ok") is True
    )
    integrity = provider.get("integrity_proof") if isinstance(provider.get("integrity_proof"), dict) else {}
    anchor = integrity.get("anchor") if isinstance(integrity.get("anchor"), dict) else {}
    run_id = str(result.get("run_id") or provider.get("run_id") or "")
    chain = event_anchor_store.EventAnchorStore(event_anchor_store.default_path(state)).verify_chain(
        user_id=str(row[0]), run_id=run_id,
    ) if run_id else {}
    target_id = str(command.get("device_id") or "")
    target = next((item for item in live_electron_clients(state) if item.get("client_id") == target_id), {})
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        commentary_rows = connection.execute(
            "SELECT payload_json FROM agent_run_event_tb "
            "WHERE run_id=? AND type='llm.reason.summary' ORDER BY seq",
            (run_id,),
        ).fetchall() if run_id else []
    commentary_updates = []
    for (raw_payload,) in commentary_rows:
        try:
            payload = json.loads(raw_payload or "{}")
        except json.JSONDecodeError:
            payload = {}
        update = payload.get("commentary") if isinstance(payload.get("commentary"), dict) else {}
        commentary_updates.append(update)
    commentary_verified = bool(commentary_updates) and all(
        update.get("schema") == "master.frontier.v6.commentary.v1"
        and update.get("authored_by") == "model"
        and update.get("visibility") == "public"
        and bool(str(update.get("message") or "").strip())
        for update in commentary_updates
    )
    report.update({
        "httpStatus": status, "runId": run_id, "protocol": provider.get("protocol") or "",
        "upstreamError": result.get("error") if isinstance(result.get("error"), dict) else {},
        "replySha256": hashlib.sha256(str(result.get("reply") or "").encode()).hexdigest(),
        "nonemptyReply": bool(str(result.get("reply") or "").strip()),
        "providerCalls": int(diagnostics.get("provider_calls") or 0),
        "exactUsageMeasured": (diagnostics.get("token_usage_total") or {}).get("exact") is True,
        "tokenUsage": diagnostics.get("token_usage_total") if isinstance(diagnostics.get("token_usage_total"), dict) else None,
        "performance": diagnostics.get("performance") if isinstance(diagnostics.get("performance"), dict) else None,
        "durationMs": round((time.monotonic() - started_monotonic) * 1000),
        "completionGatePassed": diagnostics.get("completion_gaps") == [],
        "clientWidgetAcknowledged": acknowledged,
        "clientCommandArtifactVerified": command_verified,
        "modelAuthoredCommentaryVerified": commentary_verified,
        "modelCommentaryCount": len(commentary_updates),
        "modelCommentarySha256": [
            hashlib.sha256(str(update.get("message") or "").encode()).hexdigest()
            for update in commentary_updates
        ],
        "commandIdSha256": hashlib.sha256(command_ids[0].encode()).hexdigest() if len(command_ids) == 1 else "",
        "installedClient": {
            "runtimeType": target.get("runtime_type") or "", "buildId": target.get("build_id") or "",
            "appVersion": target.get("app_version") or "", "route": target.get("route") or "",
            "live": target.get("live") is True,
        },
        "changedFiles": provider.get("changed_files") if isinstance(provider.get("changed_files"), list) else [],
        "integrityProof": {
            "status": integrity.get("status") or "", "terminal": anchor.get("terminal") is True,
            "checkpoint": int(anchor.get("checkpoint") or 0),
        },
        "anchorChain": {
            "ok": chain.get("ok") is True, "final": chain.get("final") is True,
            "checkpoints": int(chain.get("checkpoints") or 0),
        },
    })
    report["ok"] = bool(
        report["authenticatedAdmin"] and status == 200 and run_id
        and report["protocol"] == "v6" and report["nonemptyReply"]
        and report["exactUsageMeasured"] and report["completionGatePassed"]
        and acknowledged and command_verified and commentary_verified and report["changedFiles"] == []
        and report["installedClient"]["runtimeType"] == "electron"
        and str(report["installedClient"]["route"]).startswith("https://wa.colmeio.com/")
        and report["installedClient"]["live"]
        and report["integrityProof"]["status"] == "verified"
        and report["integrityProof"]["terminal"]
        and report["anchorChain"]["ok"] and report["anchorChain"]["final"]
    )
    report["checkedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, separators=(",", ":")))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
