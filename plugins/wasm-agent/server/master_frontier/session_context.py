"""Bounded reconstruction of prior Master:frontier turns from the run ledger."""
from __future__ import annotations

import json
from typing import Any, Callable


def _object(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


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
                "answer": str(row["answer"] or "")[:answer_chars],
                "status": str(row["trajectory_status"] or "completed"),
                "changed_files": [str(item) for item in (changed if isinstance(changed, list) else [])[:64]],
                "verification_level": str(row["verification_level"] or ""),
                "decision": decision if isinstance(decision, dict) else {},
            })
    return projected


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
