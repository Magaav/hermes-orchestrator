"""Owner-aware reconciliation for agent runs left nonterminal by a restart."""
from __future__ import annotations

import json
import os
import socket
from collections.abc import Callable, Mapping
from typing import Any


OVERRIDE_ENV = "HERMES_WASM_AGENT_MARK_INTERRUPTED_ON_STARTUP"
DEPLOYMENT_ENV = "HERMES_WASM_AGENT_DEPLOYMENT_MODE"
REMOTE_STALE_MS = 5 * 60 * 1000
RECONCILE_BATCH_SIZE = 128


def _process_start(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            raw = handle.read()
        fields = raw[raw.rfind(")") + 2:].split()
        return fields[19] if len(fields) > 19 else ""
    except OSError:
        return ""


_WORKER = {"host": socket.gethostname(), "pid": os.getpid(), "start": _process_start(os.getpid())}


def worker_identity() -> dict[str, Any]:
    return dict(_WORKER)


def startup_enabled(server_port: object, environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    override = str(source.get(OVERRIDE_ENV) or "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    if str(source.get(DEPLOYMENT_ENV) or "local").strip().lower() == "cloud":
        return True
    try:
        return int(server_port or 0) == 8877
    except (TypeError, ValueError):
        return False


def _object(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _owner_alive(owner: dict[str, Any]) -> bool | None:
    if not owner or str(owner.get("host") or "") != _WORKER["host"]:
        return None
    try:
        pid = int(owner.get("pid") or 0)
    except (TypeError, ValueError):
        return False
    current_start = _process_start(pid) if pid > 0 else ""
    expected_start = str(owner.get("start") or "")
    return bool(current_start and expected_start and current_start == expected_start)


def orphaned(row: Any, *, now_ms: int) -> bool:
    summary = _object(row["request_summary_json"])
    owner = summary.get("worker") if isinstance(summary.get("worker"), dict) else {}
    if not owner:
        return True
    alive = _owner_alive(owner)
    if alive is not None:
        return not alive
    try:
        age_ms = max(0, now_ms - int(row["updated_at"] or 0))
    except (TypeError, ValueError):
        age_ms = 0
    return age_ms >= REMOTE_STALE_MS


def reconcile(
    connection: Any, *, now_ms: int, force: bool,
    encode_json: Callable[[Any], str], append_event: Callable[..., Any],
) -> int:
    changed = 0
    after_run_id = ""
    while True:
        rows = connection.execute(
            """SELECT * FROM agent_run_tb
                 WHERE status NOT IN ('completed', 'failed', 'interrupted', 'cancelled')
                   AND run_id > ?
                 ORDER BY run_id
                 LIMIT ?""",
            (after_run_id, RECONCILE_BATCH_SIZE),
        ).fetchall()
        if not rows:
            return changed
        after_run_id = str(rows[-1]["run_id"])
        for row in rows:
            if not force and not orphaned(row, now_ms=now_ms):
                continue
            summary = _object(row["request_summary_json"])
            objective_event = connection.execute(
                "SELECT payload_json FROM agent_run_event_tb WHERE run_id=? AND type='envelope.created' ORDER BY seq DESC LIMIT 1",
                (str(row["run_id"]),),
            ).fetchone()
            objective_payload = _object(objective_event["payload_json"] if objective_event else None)
            envelope = objective_payload.get("envelope") if isinstance(objective_payload.get("envelope"), dict) else {}
            checkpoint = {
                "schema": "hermes.wasm_agent.restart_checkpoint.v1",
                "original_objective": str(envelope.get("objective") or "")[:1200],
                "resume_key": str(summary.get("resume_key") or f"{row['session_id']}:{row['turn_id']}")[:240],
                "previous_run_id": str(row["run_id"]), "previous_turn_id": str(row["turn_id"]),
                "instruction": "Inspect persisted run events and proof before repeating any side effect.",
            }
            error = {
                "code": "agent_run_interrupted",
                "message": "Agent run was interrupted by a server restart and remains resumable.",
                "resume_checkpoint": checkpoint,
            }
            connection.execute(
                """UPDATE agent_run_tb SET status='interrupted',updated_at=?,terminal_at=?,error_json=?
                     WHERE run_id=? AND status NOT IN ('completed','failed','interrupted','cancelled')""",
                (now_ms, now_ms, encode_json(error), str(row["run_id"])),
            )
            updated = connection.execute("SELECT * FROM agent_run_tb WHERE run_id=?", (str(row["run_id"]),)).fetchone()
            if updated and str(updated["status"]) == "interrupted":
                append_event(connection, updated, "run.error", summary=error["message"], payload={"error": error}, created_at=now_ms)
                changed += 1
