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
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "plugins/wasm-agent/server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from master_frontier import event_anchor_store  # noqa: E402
from master_frontier.v6 import trajectory  # noqa: E402

REPORTS = {
    "v5": ROOT / "reports/context/latest/master-frontier-authenticated-canary.json",
    "v6": ROOT / "reports/context/latest/master-frontier-v6-authenticated-canary.json",
}
OBJECTIVES = {
    "v5": "Read plugins/wasm-agent/MASTER_FRONTIER_V5.md and state its protocol name in one sentence. Do not modify files.",
    "v6": "Read MASTER_FRONTIER_V6.md and state its protocol name in one sentence. Do not modify files.",
}


def canonical_trajectory(conn: sqlite3.Connection, run_id: str) -> tuple[dict[str, Any], str]:
    """Rebuild from the lossless V6 checkpoint plus its small terminal tail."""
    row = conn.execute(
        "SELECT snapshot_zlib FROM master_frontier_v6_snapshot_tb WHERE run_id = ?",
        (str(run_id),),
    ).fetchone()
    stream: dict[str, Any] = {}
    source = "event-ledger"
    if row:
        snapshot = json.loads(zlib.decompress(bytes(row[0])).decode("utf-8"))
        candidate = snapshot.get("trajectory") if isinstance(snapshot, dict) else None
        if isinstance(candidate, dict):
            trajectory.verify(candidate)
            stream = candidate
            source = "checkpoint+event-tail"

    events = list(stream.get("events") or [])
    checkpoint_count = len(events)
    rows = conn.execute(
        "SELECT payload_json FROM agent_run_event_tb WHERE run_id = ? ORDER BY seq",
        (str(run_id),),
    ).fetchall()
    ledger_events = []
    for event_row in rows:
        try:
            payload = json.loads(str(event_row[0] or "{}"))
        except json.JSONDecodeError:
            continue
        event = payload.get("trajectory_event") if isinstance(payload, dict) else None
        if isinstance(event, dict):
            ledger_events.append(event)
    events.extend(
        event for event in ledger_events
        if int(event.get("seq") or 0) > checkpoint_count
    )
    if not stream:
        stream = {
            "schema": trajectory.SCHEMA, "run_id": str(run_id), "route_id": "",
            "parent": None,
        }
    stream = {**stream, "events": events, "count": len(events)}
    stream["head"] = str(events[-1].get("id") or "") if events else ""
    return stream, source


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
    parser.add_argument("--objective", help="Override the default read-only canary objective.")
    parser.add_argument("--objective-kind", default="source-investigation")
    parser.add_argument("--evidence-floor", choices=("conceptual", "route", "source", "proof", "runtime"))
    parser.add_argument("--report", type=Path, help="Write this run to a separate report path.")
    args = parser.parse_args()
    objective = str(args.objective or OBJECTIVES[args.protocol])
    report_path = args.report or REPORTS[args.protocol]
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
    route["allowed_read_roots"] = [
        str((ROOT / "plugins/wasm-agent" / str(item)).resolve())
        for item in route.get("allowed_read_roots", ["."])
    ]
    route["allowed_write_roots"] = []
    client_state_canary = args.objective_kind in {"client_state", "windows_desktop_inspect"}
    envelope_objective_kind = "diagnosis" if args.objective_kind == "self_reflection" else args.objective_kind
    route["caps"] = ["client.ui.inspect"] if client_state_canary else ["repo.read"]
    body = {
        "protocol": args.protocol, "session_id": session_id, "turn_id": turn_id,
        "instructions": "Use only read/search evidence. Never edit or run a mutating command.",
        "max_output_tokens": 800,
        "envelope": {
            "schema": f"hermes.wasm_agent.master_frontier.{args.protocol}", "trace_id": nonce,
            "objective": objective, "objective_kind": envelope_objective_kind, "surface": "avatar-chat",
            "route_id": route["route_id"], "route_contract": route,
            "compact_state": {"surface": "authenticated-production-canary", "route_id": route["route_id"]},
            "capabilities": route["caps"],
            "allowed_actions": [{"id": "answer"}, {"id": "inspect"}] if client_state_canary else [{"id": "answer"}, {"id": "search"}, {"id": "read"}],
            "budget": {"head_tokens_max": 800, "provider_tokens_max": 6000, "api_calls_max": 4, "provider_call_ms_max": 90000, "task_lease_ms_max": 300000},
        },
    }
    if args.objective_kind == "source-investigation":
        body["envelope"]["completion_capabilities"] = ["repo.read"]
    elif client_state_canary:
        body["envelope"]["completion_capabilities"] = [
            "client.windows.desktop.inspect"
            if args.objective_kind == "windows_desktop_inspect"
            else "client.environment.inspect"
        ]
    if args.evidence_floor:
        body["envelope"]["evidence_floor"] = args.evidence_floor
    report: dict[str, Any] = {
        "schema": "MF_AUTH_CLOUD/2", "ok": False, "origin": args.origin,
        "requestedProtocol": args.protocol,
        "scenario": "repository-read" if not args.objective else f"custom-{args.objective_kind}",
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
            repo_read_succeeded = any(
                item.get("capability") == "repo.read" and item.get("ok") is True
                for item in tools if isinstance(item, dict)
            )
            repo_search_succeeded = any(
                item.get("capability") == "repo.search" and item.get("ok") is True
                for item in tools if isinstance(item, dict)
            )
            successful_capabilities = sorted({
                str(item.get("capability") or "")
                for item in tools if isinstance(item, dict) and item.get("ok") is True
            })
            client_environment_succeeded = "client.environment.inspect" in successful_capabilities
            windows_desktop_inspect_succeeded = "client.windows.desktop.inspect" in successful_capabilities
            stream, trajectory_source = canonical_trajectory(conn, str(report["runId"]))
            trajectory_events = stream.get("events") if isinstance(stream.get("events"), list) else []
            trajectory_result: dict[str, Any] = {"ok": False, "eventCount": len(trajectory_events)}
            if trajectory_events:
                try:
                    verified_trajectory = trajectory.verify(stream)
                    replayed_trajectory = trajectory.replay(stream)
                    contexts = replayed_trajectory.get("contexts") or []
                    trajectory_result.update({
                        "ok": (
                            verified_trajectory["head"] == (diagnostics.get("trajectory") or {}).get("head")
                            and replayed_trajectory.get("terminal") is not None
                            and bool(contexts)
                            and all(bool(item.get("messages")) and "tool_contracts" in item for item in contexts)
                        ),
                        "head": verified_trajectory["head"],
                        "finalHeadMatches": verified_trajectory["head"] == (diagnostics.get("trajectory") or {}).get("head"),
                        "contextCount": len(contexts),
                        "decisionCount": len(replayed_trajectory.get("decisions") or []),
                        "toolCount": len(replayed_trajectory.get("tools") or []),
                        "terminalReplayed": replayed_trajectory.get("terminal") is not None,
                        "providerContextsReconstructable": all(bool(item.get("messages")) and "tool_contracts" in item for item in contexts),
                        "source": trajectory_source,
                    })
                except trajectory.TrajectoryError as exc:
                    trajectory_result["error"] = exc.code
                    previous = ""
                    for position, event in enumerate(trajectory_events, start=1):
                        if event.get("seq") != position or event.get("prev") != previous:
                            trajectory_result["firstMismatch"] = {
                                "position": position,
                                "declaredSeq": event.get("seq"),
                                "eventId": str(event.get("id") or "")[:80],
                                "declaredPrev": str(event.get("prev") or "")[:80],
                                "expectedPrev": previous[:80],
                            }
                            break
                        previous = str(event.get("id") or "")
            report["v6"] = {
                "schema": provider.get("schema") or "",
                "completionGatePassed": diagnostics.get("completion_gaps") == [],
                "exactUsageMeasured": (diagnostics.get("token_usage_total") or {}).get("exact") is True,
                "providerCalls": int(diagnostics.get("provider_calls") or 0),
                "repoReadSucceeded": repo_read_succeeded,
                "repoSearchSucceeded": repo_search_succeeded,
                "repoEvidenceSucceeded": repo_read_succeeded or repo_search_succeeded,
                "clientEnvironmentSucceeded": client_environment_succeeded,
                "windowsDesktopInspectSucceeded": windows_desktop_inspect_succeeded,
                "successfulCapabilities": successful_capabilities,
                "changedFiles": provider.get("changed_files") if isinstance(provider.get("changed_files"), list) else [],
                "trajectory": trajectory_result,
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
                    and (
                        report["v6"]["windowsDesktopInspectSucceeded"]
                        if args.objective_kind == "windows_desktop_inspect"
                        else report["v6"]["clientEnvironmentSucceeded"]
                        if args.objective_kind == "client_state"
                        else True
                        if args.objective_kind in {"conversation", "general_conversation", "self_reflection"}
                        else report["v6"]["repoReadSucceeded"]
                        if args.objective_kind == "source-investigation"
                        else report["v6"]["repoEvidenceSucceeded"]
                    )
                    and report["v6"]["changedFiles"] == []
                    and report["v6"]["trajectory"]["ok"]
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
