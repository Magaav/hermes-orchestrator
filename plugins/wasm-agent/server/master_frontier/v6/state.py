"""Deterministic V6 working-state reducer."""
from __future__ import annotations

from typing import Any

from . import contracts


STATUSES = frozenset({"exploring", "acting", "checking", "blocked", "complete", "interrupted"})


def _id(value: dict[str, Any]) -> str:
    return "st:" + contracts.digest(value).split(":", 1)[1][:32]


def initial(goal: str) -> dict[str, Any]:
    body = {"v": contracts.VERSION, "rev": 0, "goal": str(goal)[:4000], "known": [], "open": [], "plan": [], "status": "exploring", "decision": {}}
    return {"id": _id(body), **body}


def apply(current: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    if str(delta.get("from") or "") != str(current.get("id") or ""):
        raise contracts.ContractError("state_delta_source_mismatch")
    known = list(dict.fromkeys(str(item) for item in (current.get("known") or []) if str(item)))
    opened = list(dict.fromkeys(str(item) for item in (current.get("open") or []) if str(item)))
    for item in delta.get("add_known") or []:
        if str(item) and str(item) not in known:
            known.append(str(item))
    dropped_known = {str(item) for item in (delta.get("drop_known") or [])}
    known = [item for item in known if item not in dropped_known][-256:]
    for item in delta.get("add_open") or []:
        if str(item) and str(item) not in opened:
            opened.append(str(item))
    dropped_open = {str(item) for item in (delta.get("drop_open") or [])}
    opened = [item for item in opened if item not in dropped_open][-128:]
    status = str(delta.get("status") or current.get("status") or "exploring")
    if status not in STATUSES:
        raise contracts.ContractError("state_status_invalid")
    plan = delta.get("plan") if isinstance(delta.get("plan"), list) else current.get("plan") or []
    decision = delta.get("decision") if isinstance(delta.get("decision"), dict) else current.get("decision") or {}
    body = {
        "v": contracts.VERSION, "rev": int(current.get("rev") or 0) + 1,
        "goal": str(delta.get("goal") or current.get("goal") or "")[:4000],
        "known": known, "open": opened, "plan": plan[:128], "status": status,
        "decision": decision,
    }
    return {"id": _id(body), **body}


def delta(current: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {"v": contracts.VERSION, "from": current.get("id"), **changes}
