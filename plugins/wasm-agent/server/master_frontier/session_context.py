"""Bounded reconstruction of prior Master:frontier turns from the run ledger."""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Callable


def _object(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _pointer(session_id: str) -> str:
    encoded = base64.urlsafe_b64encode(session_id.encode("utf-8")).decode("ascii").rstrip("=")
    return f"sm1.{encoded}"


def _session_id(pointer: str) -> str:
    if not pointer.startswith("sm1."):
        return ""
    encoded = pointer[4:]
    try:
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""
    return decoded if decoded and _pointer(decoded) == pointer else ""


def load_memory_manifest(
    connect: Callable[[], Any], *, user_id: str, active_session_id: str, limit: int = 12,
) -> dict[str, Any]:
    """Return a tiny account-owned session index without transcript bodies."""
    if not user_id:
        return {}
    bounded_limit = max(1, min(int(limit), 24))
    connection = connect()
    if connection is None:
        return {}
    with connection:
        rows = connection.execute(
            """SELECT r.session_id,MAX(r.updated_at) AS updated_at,COUNT(*) AS turn_count,
                      COALESCE((SELECT e.summary FROM agent_run_event_tb e
                                 WHERE e.run_id=(SELECT rr.run_id FROM agent_run_tb rr
                                                   WHERE rr.user_id=r.user_id AND rr.session_id=r.session_id
                                                     AND rr.status='completed'
                                                   ORDER BY rr.terminal_at DESC,rr.updated_at DESC LIMIT 1)
                                   AND e.type='envelope.created' ORDER BY e.seq LIMIT 1),'') AS intent
                 FROM agent_run_tb r
                WHERE r.user_id=? AND r.status='completed' AND r.session_id!=''
                GROUP BY r.session_id ORDER BY updated_at DESC LIMIT ?""",
            (user_id, bounded_limit),
        ).fetchall()
        raw_row = connection.execute(
            """SELECT COALESCE(SUM(LENGTH(COALESCE(json_extract(final_json,'$.reply'),''))),0)
                         + COALESCE(SUM(LENGTH(COALESCE((SELECT e.summary FROM agent_run_event_tb e
                                                          WHERE e.run_id=agent_run_tb.run_id
                                                            AND e.type='envelope.created'
                                                          ORDER BY e.seq LIMIT 1),''))),0) AS chars
                 FROM agent_run_tb WHERE user_id=? AND status='completed'""",
            (user_id,),
        ).fetchone()
    entries = [{
        "p": _pointer(str(row["session_id"] or "")),
        "i": str(row["intent"] or "")[:160],
        "u": str(row["updated_at"] or "")[:32],
        "n": int(row["turn_count"] or 0),
    } for row in rows if str(row["session_id"] or "") != active_session_id]
    manifest = {"v": 1, "intent": "rel-continuity-v1", "sessions": entries}
    manifest_chars = len(json.dumps(manifest, separators=(",", ":"), ensure_ascii=False))
    raw_chars = int(raw_row["chars"] or 0) if raw_row else 0
    manifest["cost"] = {
        "raw_chars": raw_chars, "manifest_chars": manifest_chars,
        "saved_chars": max(0, raw_chars - manifest_chars),
    }
    return manifest


def read_memory(
    connect: Callable[[], Any], *, user_id: str, pointer: str, limit: int = 6,
) -> dict[str, Any]:
    """Read exact recent turns after opaque-pointer and account-scope validation."""
    session_id = _session_id(pointer)
    if not user_id or not session_id:
        return {"ok": False, "code": "session_memory_pointer_invalid", "turns": []}
    bounded_limit = max(1, min(int(limit), 12))
    with connect() as connection:
        rows = connection.execute(
            """SELECT r.run_id,r.turn_id,r.updated_at,
                      COALESCE(json_extract(r.final_json,'$.reply'),'') AS answer,
                      COALESCE((SELECT e.summary FROM agent_run_event_tb e
                                 WHERE e.run_id=r.run_id AND e.user_id=r.user_id
                                   AND e.session_id=r.session_id AND e.type='envelope.created'
                                 ORDER BY e.seq LIMIT 1),'') AS objective
                 FROM agent_run_tb r
                WHERE r.user_id=? AND r.session_id=? AND r.status='completed'
                ORDER BY r.terminal_at DESC,r.updated_at DESC LIMIT ?""",
            (user_id, session_id, bounded_limit),
        ).fetchall()
    if not rows:
        return {"ok": False, "code": "session_memory_not_found", "turns": []}
    turns = [{
        "run": str(row["run_id"] or ""), "turn": str(row["turn_id"] or ""),
        "objective": str(row["objective"] or "")[:4000],
        "answer": str(row["answer"] or "")[:8000], "at": str(row["updated_at"] or "")[:32],
    } for row in reversed(rows)]
    digest = hashlib.sha256(json.dumps(turns, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return {"ok": True, "code": "ok", "pointer": pointer, "turns": turns, "digest": digest}


def load_recent(
    connect: Callable[[], Any], *, session_id: str, turn_id: str, user_id: str,
    limit: int = 4, answer_chars: int = 2000,
) -> list[dict[str, Any]]:
    """Return compact recent turns without materializing full final trajectories."""
    if not session_id or not user_id:
        return []
    bounded_limit = max(1, min(int(limit), 8))
    with connect() as connection:
        rows = connection.execute(
            """SELECT r.run_id,r.turn_id,
                      COALESCE(json_extract(r.final_json,'$.reply'),json_extract(r.final_json,'$.answer'),'') AS answer,
                      COALESCE(json_extract(r.final_json,'$.route_id'),'') AS route_id,
                      COALESCE(json_extract(r.final_json,'$.trajectory.status'),'completed') AS trajectory_status,
                      COALESCE(json_extract(r.final_json,'$.changed_files'),json('[]')) AS changed_files_json,
                      COALESCE(json_extract(r.final_json,'$.diagnostics.verification_level'),'') AS verification_level,
                      COALESCE(json_extract(r.final_json,'$.decision'),json('{}')) AS decision_json,
                      COALESCE(json_extract(r.final_json,'$.trajectory.root_objective'),'') AS root_objective,
                      COALESCE((SELECT e.summary FROM agent_run_event_tb e
                                 WHERE e.run_id=r.run_id AND e.user_id=r.user_id AND e.session_id=r.session_id
                                   AND e.type='envelope.created' ORDER BY e.seq LIMIT 1),'') AS objective
                 FROM agent_run_tb r
                 WHERE r.user_id=? AND r.session_id=? AND r.status='completed'
                   AND (?='' OR r.turn_id!=?)
                 ORDER BY r.terminal_at DESC,r.updated_at DESC LIMIT ?""",
            (user_id, session_id, turn_id, turn_id, bounded_limit),
        ).fetchall()
        projected: list[dict[str, Any]] = []
        for row in reversed(rows):
            try:
                changed = json.loads(str(row["changed_files_json"] or "[]"))
            except (TypeError, ValueError, json.JSONDecodeError):
                changed = []
            try:
                decision = json.loads(str(row["decision_json"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                decision = {}
            projected.append({
                "run_id": str(row["run_id"] or ""),
                "turn_id": str(row["turn_id"] or ""),
                "route_id": str(row["route_id"] or ""),
                "objective": str(row["objective"] or "")[:1000],
                "root_objective": str(row["root_objective"] or row["objective"] or "")[:2000],
                "answer": str(row["answer"] or "")[:answer_chars],
                "status": str(row["trajectory_status"] or "completed"),
                "changed_files": [str(item) for item in (changed if isinstance(changed, list) else [])[:64]],
                "verification_level": str(row["verification_level"] or ""),
                "decision": decision if isinstance(decision, dict) else {},
            })
    return projected


def load_lineage_parent(
    connect: Callable[[], Any], *, previous_run_id: str, session_id: str, user_id: str,
) -> dict[str, Any]:
    """Project one exact completed or resumable parent from server-owned state."""
    if not previous_run_id or not session_id or not user_id:
        return {}
    with connect() as connection:
        row = connection.execute(
            """SELECT r.run_id,r.turn_id,r.status,r.final_json,
                      (SELECT e.summary FROM agent_run_event_tb e
                         WHERE e.run_id=r.run_id AND e.user_id=r.user_id AND e.session_id=r.session_id
                           AND e.type='envelope.created' ORDER BY e.seq LIMIT 1) AS objective,
                      (SELECT e.payload_json FROM agent_run_event_tb e
                         WHERE e.run_id=r.run_id AND e.user_id=r.user_id AND e.session_id=r.session_id
                           AND e.type='state.writeback' ORDER BY e.seq DESC LIMIT 1) AS state_payload
                 FROM agent_run_tb r
                WHERE r.run_id=? AND r.user_id=? AND r.session_id=?
                  AND r.status IN ('completed','interrupted','cancelled') LIMIT 1""",
            (previous_run_id, user_id, session_id),
        ).fetchone()
    if not row:
        return {}
    final = _object(row["final_json"])
    state_payload = _object(row["state_payload"])
    checkpoint = state_payload.get("checkpoint") if isinstance(state_payload.get("checkpoint"), dict) else {}
    state = checkpoint.get("state") if isinstance(checkpoint.get("state"), dict) else {}
    scope = checkpoint.get("scope") if isinstance(checkpoint.get("scope"), dict) else {}
    trajectory_value = final.get("trajectory") if isinstance(final.get("trajectory"), dict) else {}
    diagnostics = final.get("diagnostics") if isinstance(final.get("diagnostics"), dict) else {}
    verification = str(diagnostics.get("verification_level") or "")
    if not verification:
        successful = [
            str(step.get("tool") or "")
            for step in (state.get("steps") or [])
            if (
                isinstance(step, dict)
                and step.get("status") in {"completed", "duplicate"}
                and isinstance(step.get("result"), dict)
                and step["result"].get("ok") is True
            )
        ]
        if "prove" in successful:
            verification = "proof"
        elif "test" in successful:
            verification = "behavioral"
        elif "inspect" in successful:
            verification = "runtime"
        elif any(tool in {"read", "search"} for tool in successful):
            verification = "source"
    return {
        "run_id": str(row["run_id"] or ""),
        "turn_id": str(row["turn_id"] or ""),
        "route_id": str(final.get("route_id") or scope.get("route_id") or state.get("route_id") or ""),
        "objective": str(row["objective"] or "")[:1000],
        "root_objective": str(
            trajectory_value.get("root_objective") or state.get("root_objective") or row["objective"] or ""
        )[:2000],
        "status": str(row["status"] or ""),
        "verification_level": verification,
    }


def load_resume(
    connect: Callable[[], Any], *, previous_run_id: str, session_id: str, user_id: str,
    evidence_limit: int = 12,
) -> dict[str, Any]:
    """Load one server-owned V5 checkpoint lineage and its recent evidence."""
    if not previous_run_id or not session_id or not user_id:
        return {}
    with connect() as connection:
        row = connection.execute(
            """SELECT run_id,turn_id,status,protocol,error_json FROM agent_run_tb
                 WHERE run_id=? AND user_id=? AND session_id=? LIMIT 1""",
            (previous_run_id, user_id, session_id),
        ).fetchone()
        if not row or str(row["protocol"] or "") != "v5" or str(row["status"] or "") not in {"interrupted", "cancelled"}:
            return {}
        state_row = connection.execute(
            """SELECT payload_json FROM agent_run_event_tb
                 WHERE run_id=? AND user_id=? AND session_id=? AND type='state.writeback'
                 ORDER BY seq DESC LIMIT 1""",
            (previous_run_id, user_id, session_id),
        ).fetchone()
        state_payload = _object(state_row["payload_json"] if state_row else None)
        checkpoint = state_payload.get("checkpoint") if isinstance(state_payload.get("checkpoint"), dict) else None
        if checkpoint is None:
            error = _object(row["error_json"])
            checkpoint = error.get("resume_checkpoint") if isinstance(error.get("resume_checkpoint"), dict) else None
        if checkpoint is None:
            return {}
        limit = max(1, min(int(evidence_limit), 16))
        evidence_rows = connection.execute(
            """SELECT type,summary,payload_json FROM agent_run_event_tb
                 WHERE run_id=? AND user_id=? AND session_id=?
                   AND type IN ('evidence.received','command.failed')
                 ORDER BY seq DESC LIMIT ?""",
            (previous_run_id, user_id, session_id, limit),
        ).fetchall()
        evidence_steps: list[dict[str, Any]] = []
        for event in reversed(evidence_rows):
            payload = _object(event["payload_json"])
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            if payload.get("protocol") != "v5" or not result:
                continue
            evidence_steps.append({
                "kind": "tool",
                "action_id": str(payload.get("action_id") or ""),
                "tool": str(payload.get("tool") or ""),
                "status": "completed" if result.get("ok") else "failed",
                "summary": str(event["summary"] or result.get("summary") or result.get("code") or ""),
                "result": result,
            })
        return {
            "checkpoint": checkpoint,
            "previous_run_id": str(row["run_id"] or ""),
            "previous_turn_id": str(row["turn_id"] or ""),
            "previous_status": str(row["status"] or ""),
            "evidence_steps": evidence_steps,
        }
