"""Cooperative per-run cancellation for agent workers."""
from __future__ import annotations

import threading
from http import HTTPStatus
from typing import Any


_LOCK = threading.Lock()
_REQUESTED: set[str] = set()
_EVENTS: dict[str, threading.Event] = {}


def request(run_id: str) -> bool:
    clean = str(run_id or "").strip()
    if not clean:
        return False
    with _LOCK:
        fresh = clean not in _REQUESTED
        _REQUESTED.add(clean)
        _EVENTS.setdefault(clean, threading.Event()).set()
    return fresh


def requested(run_id: str) -> bool:
    with _LOCK:
        return str(run_id or "") in _REQUESTED


def event(run_id: str) -> threading.Event:
    clean = str(run_id or "").strip()
    with _LOCK:
        value = _EVENTS.setdefault(clean, threading.Event())
        if clean in _REQUESTED:
            value.set()
        return value


def clear(run_id: str) -> None:
    with _LOCK:
        clean = str(run_id or "")
        _REQUESTED.discard(clean)
        _EVENTS.pop(clean, None)


def request_http(server: Any, run_id: str, user: dict[str, Any] | None, runtime: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    with runtime["auth_connect"]() as conn:
        row = runtime["get_agent_run_for_user"](conn, run_id, user)
    status = str(row["status"] or "")
    if status in runtime["AGENT_RUN_TERMINAL_STATUSES"]:
        return HTTPStatus.CONFLICT, {"ok": False, "error": {"code": "agent_run_terminal", "message": f"Agent run is already {status}."}}
    fresh = request(run_id)
    if fresh:
        runtime["append_agent_run_event"](server, run_id, "cancel.requested", summary="User requested cooperative cancellation.", payload={"status": "requested"})
    return HTTPStatus.ACCEPTED, {"ok": True, "run_id": run_id, "cancel_requested": True, "fresh": fresh}
