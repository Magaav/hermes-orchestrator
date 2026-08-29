#!/usr/bin/env python3
"""Run and audit production V6 space ownership discovery before opening a widget."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/context/latest/master-frontier-v6-space-widget-discovery.json"
OBJECTIVE = "find a space which owns the browser widget, open that space, then open the browser widget"


def env_value(path: Path, name: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    raise RuntimeError(f"{name} is not configured")


def request_json(url: str, *, cookie: str, origin: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers={
        "Cookie": f"wa_uid={cookie}", "Origin": origin, "Content-Type": "application/json",
        "User-Agent": "wasm-agent-v6-space-widget-discovery-proof/1",
    })
    try:
        response = urllib.request.urlopen(request, timeout=600)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return int(response.status), json.loads(response.read(4 * 1024 * 1024))


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def command_record(state: Path, command_id: str) -> dict[str, Any]:
    matches = list((state / "native-control/commands").glob(f"*/{command_id}.json"))
    return read_json(matches[0]) if len(matches) == 1 else {}


def command_id_for(operation: str, evidence: list[dict[str, Any]]) -> str:
    item = next((entry for entry in evidence if entry.get("subject") == f"operation:{operation}"), {})
    return next((str(value) for value in (item.get("proof") or []) if str(value).startswith("cmd-")), "")


def main() -> int:
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="https://wa.colmeio.com")
    parser.add_argument("--cloud-root", type=Path, default=Path("/home/ubuntu/.local/share/wasm-agent-cloud"))
    args = parser.parse_args()
    state = args.cloud_root / "state"
    report: dict[str, Any] = {
        "schema": "MF6_SPACE_WIDGET_DISCOVERY_PRODUCTION/1", "ok": False, "origin": args.origin,
        "objectiveSha256": hashlib.sha256(OBJECTIVE.encode()).hexdigest(),
    }
    try:
        admin_email = env_value(ROOT / "plugins/wasm-agent/conf/wa.env", "ADMIN_EMAIL").split(",", 1)[0].strip()
        db_path = state / "db/sqlite/wa_db.sqlite3"
        with sqlite3.connect(db_path) as connection:
            row = connection.execute(
                "SELECT id FROM user_tb WHERE lower(email)=lower(?) ORDER BY last_login_at DESC LIMIT 1", (admin_email,),
            ).fetchone()
        if not row:
            raise RuntimeError("configured_admin_missing")
        issued = int(time.time())
        message = f"{int(row[0])}.{issued}"
        secret = (state / "db/sqlite/wa_auth_secret").read_text(encoding="utf-8").strip().encode()
        cookie = f"{message}.{hmac.new(secret, message.encode(), hashlib.sha256).hexdigest()}"
        nonce = uuid.uuid4().hex[:16]
        auth_status, auth = request_json(f"{args.origin}/auth/session", cookie=cookie, origin=args.origin)
        authenticated = bool(auth_status == 200 and auth.get("authenticated") is True and (auth.get("user") or {}).get("role") == "admin")
        body = {
            "protocol": "v6", "session_id": f"v6-space-widget-{nonce}", "turn_id": f"turn-{nonce}",
            "instructions": (
                "If Browser is absent from the active surface, execute client.space.catalog exactly once as a read-only setup "
                "operation without goals or goal bindings. Use the exact returned owner space ID. Then declare exactly two "
                "action goals, open that space, and after it succeeds open Browser. Do not guess a space, retry the catalog, "
                "change files, navigate Browser, or claim success without both action proofs."
            ),
            "max_output_tokens": 1000,
            "envelope": {
                "schema": "hermes.wasm_agent.master_frontier.v6", "trace_id": nonce,
                "objective": OBJECTIVE, "objective_kind": "client_action", "surface": "avatar-chat",
                "route_id": "wasm-agent.avatar-chat.ui",
                "compact_state": {"surface": "production-space-widget-discovery", "route_id": "wasm-agent.avatar-chat.ui"},
                "capabilities": ["client.ui.inspect", "client.ui.control"],
                "allowed_actions": [
                    {"id": "answer"}, {"id": "client.space.catalog"},
                    {"id": "client.space.open"}, {"id": "client.widget.open"},
                ],
                "budget": {"provider_call_ms_max": 90000, "task_lease_ms_max": 600000},
            },
        }
        http_status, response = request_json(
            f"{args.origin}/agent/provider/envelope", cookie=cookie, origin=args.origin, body=body,
        )
        final = response.get("provider") if isinstance(response.get("provider"), dict) else {}
        tools = final.get("local_tools") if isinstance(final.get("local_tools"), list) else []
        evidence = final.get("evidence") if isinstance(final.get("evidence"), list) else []
        diagnostics = final.get("diagnostics") if isinstance(final.get("diagnostics"), dict) else {}
        state_value = final.get("state") if isinstance(final.get("state"), dict) else {}
        by_capability = {str(item.get("capability") or ""): item for item in tools if isinstance(item, dict)}
        commands: dict[str, dict[str, Any]] = {}
        command_ids: dict[str, str] = {}
        for capability, tool in by_capability.items():
            operation = str(tool.get("operation") or "")
            command_id = command_id_for(operation, evidence)
            command_ids[capability] = command_id
            commands[capability] = command_record(state, command_id) if command_id else {}
        catalog_result = (commands.get("client.space.catalog") or {}).get("result") or {}
        spaces = catalog_result.get("spaces") if isinstance(catalog_result.get("spaces"), list) else []
        owner = next((item for item in spaces if isinstance(item, dict) and "browser" in set(item.get("widget_ids") or [])), {})
        home = next((item for item in spaces if isinstance(item, dict) and item.get("id") == "home"), {})
        space_command = commands.get("client.space.open") or {}
        widget_command = commands.get("client.widget.open") or {}
        space_result = space_command.get("result") if isinstance(space_command.get("result"), dict) else {}
        widget_result = widget_command.get("result") if isinstance(widget_command.get("result"), dict) else {}
        goals = state_value.get("goals") if isinstance(state_value.get("goals"), list) else []
        goal_caps = {str(goal.get("cap") or "") for goal in goals if isinstance(goal, dict)}
        capability_order = [str(item.get("capability") or "") for item in tools if isinstance(item, dict)]
        action_proofs = {
            capability: set(next((item.get("proof") or [] for item in evidence if item.get("subject") == f"operation:{tool.get('operation')}"), []))
            for capability, tool in by_capability.items()
        }
        checks = {
            "authenticatedAdmin": authenticated,
            "httpSuccess": http_status == 200,
            "completedV6": final.get("protocol") == "v6" and state_value.get("status") == "complete",
            "exactCapabilityOrder": capability_order == ["client.space.catalog", "client.space.open", "client.widget.open"],
            "allToolsSucceeded": len(tools) == 3 and all(item.get("ok") is True for item in tools),
            "catalogExecutedOnce": [item.get("capability") for item in tools].count("client.space.catalog") == 1,
            "catalogProof": "client.space.catalog" in action_proofs.get("client.space.catalog", set()),
            "homeHasNoBrowser": bool(home) and "browser" not in set(home.get("widget_ids") or []),
            "ownerDiscovered": bool(owner.get("id")),
            "exactOwnerOpened": (space_command.get("payload") or {}).get("space") in {owner.get("id"), owner.get("name")},
            "spaceActiveProof": "client.space.active" in action_proofs.get("client.space.open", set()) and space_result.get("opened") is True,
            "spaceSurfaceAdvanced": (space_result.get("surface") or {}).get("space_id") == owner.get("id") and "browser" in set((space_result.get("surface") or {}).get("widget_ids") or []),
            "browserVisibleProof": "client.widget.visible" in action_proofs.get("client.widget.open", set()) and widget_result.get("visible") is True,
            "twoActionGoalsSatisfied": goal_caps == {"client.space.open", "client.widget.open"} and len(goals) == 2 and all(goal.get("status") == "satisfied" for goal in goals),
            "zeroCompletionGaps": diagnostics.get("completion_gaps") == [],
            "noStallDiagnostic": not bool(diagnostics.get("stall_diagnostic")),
            "fourProviderCalls": int(diagnostics.get("provider_calls") or 0) == 4,
            "nonemptyReply": bool(str(response.get("reply") or final.get("reply") or "").strip()),
            "threeDistinctCommands": len({value for value in command_ids.values() if value}) == 3,
        }
        report.update({
            "runId": str(response.get("run_id") or final.get("run_id") or ""),
            "httpStatus": http_status, "providerCalls": int(diagnostics.get("provider_calls") or 0),
            "completionGaps": diagnostics.get("completion_gaps") or [], "checks": checks,
            "owner": {key: owner.get(key) for key in ("id", "name", "kind")},
            "capabilityOrder": capability_order,
            "commandIds": command_ids, "goalCapabilities": sorted(goal_caps),
            "replySha256": hashlib.sha256(str(response.get("reply") or final.get("reply") or "").encode()).hexdigest(),
        })
        report["ok"] = all(checks.values())
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
        report["error"] = {"code": str(exc)[:240]}
    report["durationMs"] = round((time.monotonic() - started) * 1000)
    report["checkedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
