#!/usr/bin/env python3
"""Emit one compact, read-only health view for an avatar-chat session/run."""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE = Path("/home/ubuntu/.local/share/wasm-agent-cloud/state")
DEFAULT_REPORT = ROOT / "reports/context/latest/avatar-chat-run-watch.json"
TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def json_value(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(str(value or ""))
    except (TypeError, json.JSONDecodeError):
        return fallback


def connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def find_run(connection: sqlite3.Connection, session_id: str, run_id: str) -> sqlite3.Row | None:
    if run_id:
        return connection.execute("SELECT * FROM agent_run_tb WHERE run_id=?", (run_id,)).fetchone()
    return connection.execute(
        "SELECT * FROM agent_run_tb WHERE session_id=? ORDER BY created_at DESC LIMIT 1",
        (session_id,),
    ).fetchone()


def backend_view(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    run_id = str(row["run_id"])
    counts = {
        str(item["type"]): int(item["count"])
        for item in connection.execute(
            "SELECT type,COUNT(*) count FROM agent_run_event_tb WHERE run_id=? GROUP BY type", (run_id,)
        )
    }
    latest = connection.execute(
        "SELECT seq,type,summary,created_at,payload_json FROM agent_run_event_tb WHERE run_id=? ORDER BY seq DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    writeback = connection.execute(
        "SELECT payload_json FROM agent_run_event_tb WHERE run_id=? AND type='state.writeback' ORDER BY seq DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    checkpoint = json_value(writeback["payload_json"], {}).get("checkpoint", {}) if writeback else {}
    state = checkpoint.get("state") if isinstance(checkpoint.get("state"), dict) else {}
    counters = state.get("loop_counters") if isinstance(state.get("loop_counters"), dict) else {}
    usage = connection.execute(
        "SELECT COUNT(*) calls,COALESCE(SUM(total_tokens),0) tokens FROM agent_token_ledger_tb WHERE run_id=?",
        (run_id,),
    ).fetchone()
    mutations = state.get("operation_ledger", {}).get("mutations", []) if isinstance(state.get("operation_ledger"), dict) else []
    now_ms = int(time.time() * 1000)
    status = str(row["status"] or "unknown")
    updated_at = int(row["updated_at"] or 0)
    return {
        "run": run_id,
        "status": status,
        "terminal": status in TERMINAL,
        "age_s": max(0, round((now_ms - int(row["created_at"] or now_ms)) / 1000)),
        "stale_s": max(0, round((now_ms - updated_at) / 1000)),
        "event_seq": int(latest["seq"] or 0) if latest else 0,
        "last_event": str(latest["type"] or "") if latest else "",
        "last_summary": str(latest["summary"] or "")[:160] if latest else "",
        "attempts": int(counters.get("provider_attempts") or counts.get("llm.inference.started", 0)),
        "calls": int(usage["calls"] or 0),
        "tokens": int(usage["tokens"] or 0),
        "evidence": counts.get("evidence.received", 0),
        "duplicates": int(counters.get("duplicate_actions") or 0),
        "no_progress": int(counters.get("no_progress") or 0),
        "mutations": len(mutations) if isinstance(mutations, list) else 0,
        "cancel_requested": counts.get("cancel.requested", 0) > 0,
        "errors": counts.get("run.error", 0),
    }


def client_view(state_root: Path, session_id: str, run_id: str) -> dict[str, Any]:
    candidates = sorted(state_root.glob("users/*/client-snapshots/latest.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates:
        payload = json_value(path.read_text(encoding="utf-8"), {})
        sessions = payload.get("sessions") if isinstance(payload.get("sessions"), list) else []
        session = next((item for item in sessions if isinstance(item, dict) and str(item.get("id")) == session_id), None)
        if not session:
            continue
        messages = session.get("messages") if isinstance(session.get("messages"), list) else []
        matched = [item for item in messages if isinstance(item, dict) and str(item.get("run_id") or "") == run_id]
        latest = matched[-1] if matched else (messages[-1] if messages else {})
        content = str(latest.get("content") or "")
        return {
            "seen": True,
            "snapshot_at": str(payload.get("server_received_at") or payload.get("created_at") or ""),
            "reason": str(payload.get("reason") or ""),
            "visibility": str((payload.get("page") or {}).get("visibility") or ""),
            "message_status": str(latest.get("agent_run_status") or ""),
            "pending": bool(latest.get("pending")),
            "interrupted": bool(
                str(latest.get("run_id") or "") == run_id
                and "I was interrupted before I could finish this turn." in content
            ),
            "message_run": str(latest.get("run_id") or ""),
        }
    return {"seen": False}


def cdp_view(endpoint: str, session_id: str, run_id: str) -> dict[str, Any]:
    helper = Path(__file__).with_name("cdp-wasm-agent-observe.js")
    try:
        result = subprocess.run(
            ["node", str(helper), endpoint, session_id, run_id], cwd=ROOT, text=True,
            capture_output=True, timeout=7, check=False,
        )
        payload = json_value(result.stdout, {"available": False, "error": "cdp_invalid_json"})
        if result.returncode not in {0, 2}:
            payload["error"] = (result.stderr or "cdp_helper_failed")[:240]
        return payload
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "error": str(exc)}


def classify(backend: dict[str, Any], client: dict[str, Any], cdp: dict[str, Any]) -> tuple[str, list[str]]:
    signals: list[str] = []
    page = cdp.get("page") if isinstance(cdp.get("page"), dict) else {}
    ui_interrupted = bool(client.get("interrupted") or page.get("interrupted_visible"))
    if ui_interrupted and not backend["terminal"]:
        signals.append("ui_terminal_backend_running")
    if backend["attempts"] > 12 and backend["mutations"] == 0 and not backend["terminal"]:
        signals.append("runaway_no_mutation")
    if backend["tokens"] > 20_000 and not backend["terminal"]:
        signals.append("token_target_exceeded")
    if backend["duplicates"] >= 2 and not backend["terminal"]:
        signals.append("novelty_loop")
    if backend["cancel_requested"] and not backend["terminal"]:
        signals.append("cancel_unacknowledged")
    if signals:
        return "unhealthy", signals
    if backend["terminal"]:
        return "terminal", []
    return "healthy", []


def observe(args: argparse.Namespace) -> dict[str, Any]:
    db_path = args.db or args.state_root / "db/sqlite/wa_db.sqlite3"
    with connect_read_only(db_path) as connection:
        row = find_run(connection, args.session_id, args.run_id)
        if row is None:
            return {"ok": False, "classification": "run_not_found", "session": args.session_id, "run": args.run_id}
        backend = backend_view(connection, row)
    client = client_view(args.state_root, args.session_id or str(row["session_id"]), backend["run"])
    cdp = cdp_view(args.cdp_endpoint, args.session_id or str(row["session_id"]), backend["run"]) if args.cdp else {"available": False, "skipped": True}
    classification, signals = classify(backend, client, cdp)
    return {
        "schema": "hermes.wasm_agent.avatar_chat.watch.v1",
        "ok": classification in {"healthy", "terminal"},
        "classification": classification,
        "signals": signals,
        "session": args.session_id or str(row["session_id"]),
        "backend": backend,
        "client": client,
        "cdp": cdp,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_id")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--cdp", action="store_true")
    parser.add_argument("--cdp-endpoint", default="http://127.0.0.1:9222")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = observe(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, separators=(",", ":")))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
