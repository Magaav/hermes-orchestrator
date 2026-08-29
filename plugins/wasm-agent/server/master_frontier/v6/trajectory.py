"""Canonical append-only V6 model-visible trajectory contract.

The trajectory is the single replay description for model context, decisions,
tool transitions, checkpoints, and terminal answers.  Large/raw values remain
in their owning evidence stores; trajectory payloads are bounded projections.
"""
from __future__ import annotations

from typing import Any, Callable

from . import contracts


SCHEMA = "master.frontier.v6.trajectory.v1"
EVENT_SCHEMA = "master.frontier.v6.trajectory.event.v1"
MAX_EVENTS = 512
MAX_PAYLOAD_BYTES = 256_000
KINDS = frozenset({
    "run.started", "run.resumed", "context.projected", "model.completed",
    "decision.completed", "tool.completed", "checkpoint.saved",
    "run.completed", "run.interrupted",
})


class TrajectoryError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _bounded(value: Any) -> Any:
    encoded = contracts.canonical(value)
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise TrajectoryError("v6_trajectory_payload_too_large")
    return contracts.decode(encoded, max_bytes=MAX_PAYLOAD_BYTES)


def create(*, run_id: str, route_id: str, parent: dict[str, Any] | None = None) -> dict[str, Any]:
    lineage = None
    if isinstance(parent, dict):
        lineage = {
            "run_id": str(parent.get("run_id") or "")[:160],
            "head": str(parent.get("head") or "")[:80],
            "count": int(parent.get("count") or 0),
        }
    return {
        "schema": SCHEMA, "run_id": str(run_id)[:160], "route_id": str(route_id)[:160],
        "parent": lineage, "events": [], "head": "", "count": 0,
    }


def append(
    value: dict[str, Any], *, kind: str, source: str, payload: dict[str, Any],
    sink: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if kind not in KINDS:
        raise TrajectoryError("v6_trajectory_kind_invalid")
    events = value.get("events") if isinstance(value.get("events"), list) else []
    if len(events) >= MAX_EVENTS:
        raise TrajectoryError("v6_trajectory_event_limit")
    body = {
        "schema": EVENT_SCHEMA, "seq": len(events) + 1, "kind": kind,
        "source": str(source)[:160], "prev": str(value.get("head") or ""),
        "payload": _bounded(payload),
    }
    event = {**body, "id": contracts.digest(body, prefix="ev")}
    events.append(event)
    value["events"] = events
    value["head"] = event["id"]
    value["count"] = len(events)
    if sink:
        sink(event)
    return event


def verify(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema") != SCHEMA:
        raise TrajectoryError("v6_trajectory_schema_invalid")
    events = value.get("events")
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise TrajectoryError("v6_trajectory_events_invalid")
    previous = ""
    for index, event in enumerate(events, start=1):
        if not isinstance(event, dict) or event.get("schema") != EVENT_SCHEMA:
            raise TrajectoryError("v6_trajectory_event_invalid")
        body = {key: event.get(key) for key in ("schema", "seq", "kind", "source", "prev", "payload")}
        if event.get("seq") != index or event.get("prev") != previous:
            raise TrajectoryError("v6_trajectory_chain_invalid")
        expected = contracts.digest(body, prefix="ev")
        if event.get("id") != expected:
            raise TrajectoryError("v6_trajectory_digest_mismatch")
        if event.get("kind") not in KINDS:
            raise TrajectoryError("v6_trajectory_kind_invalid")
        _bounded(event.get("payload"))
        previous = expected
    if value.get("count") != len(events) or str(value.get("head") or "") != previous:
        raise TrajectoryError("v6_trajectory_head_mismatch")
    return {"ok": True, "count": len(events), "head": previous}


def checkpoint(value: dict[str, Any]) -> dict[str, Any]:
    verified = verify(value)
    return {
        "schema": SCHEMA, "run_id": str(value.get("run_id") or ""),
        "route_id": str(value.get("route_id") or ""), "parent": value.get("parent"),
        "events": list(value.get("events") or []), **verified,
    }


def context_payload(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]], *,
    decision: int, profile: str,
) -> dict[str, Any]:
    blocks = []
    for index, message in enumerate(messages):
        content = str(message.get("content") or "")
        blocks.append({
            "i": index, "role": str(message.get("role") or ""),
            "source": str(message.get("source") or ("system" if index == 0 else "projection")),
            "chars": len(content), "sha256": contracts.digest(content),
        })
    tool_projection = [{
        "name": str((item.get("function") or {}).get("name") or ""),
        "sha256": contracts.digest(item),
    } for item in tools if isinstance(item, dict)]
    return {
        "decision": int(decision), "profile": str(profile), "blocks": blocks,
        "tools": tool_projection, "message_chars": sum(item["chars"] for item in blocks),
        "projection_sha256": contracts.digest({"messages": messages, "tools": tools}),
        "messages": _bounded(messages), "tool_contracts": _bounded(tools),
    }


def replay(value: dict[str, Any]) -> dict[str, Any]:
    verify(value)
    contexts = [event["payload"] for event in value["events"] if event["kind"] == "context.projected"]
    decisions = [event["payload"] for event in value["events"] if event["kind"] == "decision.completed"]
    tools = [event["payload"] for event in value["events"] if event["kind"] == "tool.completed"]
    return {
        "schema": "master.frontier.v6.trajectory.replay.v1", "head": value["head"],
        "count": value["count"], "contexts": contexts, "decisions": decisions,
        "tools": tools, "terminal": next((event["payload"] for event in reversed(value["events"]) if event["kind"] in {"run.completed", "run.interrupted"}), None),
    }
