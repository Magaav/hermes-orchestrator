from __future__ import annotations

import hashlib
import json
from typing import Any


SCHEMA = "master.frontier.v5.trajectory.v1"


def new(run_id: str, turn_id: str, objective: str, route_id: str) -> dict[str, Any]:
    return {"schema": SCHEMA, "run_id": run_id, "turn_id": turn_id, "objective": objective, "route_id": route_id, "status": "running", "steps": [], "completed_actions": {}, "pending": None, "last_error": None, "final_answer": None}


def restore(value: Any, *, run_id: str, turn_id: str, objective: str, route_id: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        return new(run_id, turn_id, objective, route_id)
    result = new(run_id, turn_id, objective, route_id)
    result.update({key: value.get(key) for key in ("steps", "completed_actions", "pending", "last_error", "final_answer")})
    result["steps"] = list(result["steps"] or [])[-24:]
    result["completed_actions"] = dict(result["completed_actions"] or {})
    return result


def action_id(name: str, arguments: dict[str, Any]) -> str:
    raw = json.dumps({"tool": name, "arguments": arguments}, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "act_" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def append(state: dict[str, Any], step: dict[str, Any]) -> None:
    state["steps"].append({"sequence": len(state["steps"]) + 1, **step})


def checkpoint(state: dict[str, Any], code: str, message: str) -> dict[str, Any]:
    state["status"] = "resumable"
    state["pending"] = "frontier_completion"
    state["last_error"] = {"code": code, "message": message}
    return state

