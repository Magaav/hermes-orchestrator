from __future__ import annotations

import hashlib
import json
from typing import Any

from . import executive, operation_ledger, reliability, usage


SCHEMA = "master.frontier.v5.trajectory.v1"
SUMMARY_SCHEMA = "master.frontier.v5.trajectory.summary.v1"
MAX_STEPS = 32
MAX_ACTIONS = 64
MAX_CONTENT_CHARS = 24_000
MAX_OBSERVATION_CHARS = 32_000
COUNTER_KEYS = (
    "provider_attempts", "provider_calls", "tool_calls", "invalid_decisions",
    "no_progress", "duplicate_actions", "evidence_repairs", "proof_repairs", "implementation_repairs", "outcome_repairs", "length_continuations", "elapsed_ms",
)


def initial_counters() -> dict[str, int]:
    return {key: 0 for key in COUNTER_KEYS}


def new(run_id: str, turn_id: str, objective: str, route_id: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "turn_id": turn_id,
        "objective": objective,
        "root_objective": objective,
        "route_id": route_id,
        "status": "running",
        "steps": [],
        "completed_actions": {},
        "pending_action": None,
        "pending": None,
        "last_error": None,
        "completion_assessment": None,
        "provider_reliability": reliability.initial_state(),
        "operation_ledger": operation_ledger.new(route_id),
        "loop_counters": initial_counters(),
        "usages": [],
        "usage_totals": usage.empty(),
        "final_answer": None,
        "executive": executive.empty(),
        "decision_finalization": False,
        "queued_tool_calls": [],
    }


def normalize_counters(value: Any) -> dict[str, int]:
    result = initial_counters()
    if not isinstance(value, dict):
        return result
    for key in COUNTER_KEYS:
        try:
            result[key] = max(0, int(value.get(key) or 0))
        except (TypeError, ValueError):
            result[key] = 0
    return result


def restore(value: Any, *, run_id: str, turn_id: str, objective: str, route_id: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        return new(run_id, turn_id, objective, route_id)
    result = new(run_id, turn_id, objective, route_id)
    result.update({key: value.get(key) for key in (
        "root_objective", "steps", "completed_actions", "pending_action", "pending",
        "last_error", "completion_assessment", "final_answer", "executive", "decision_finalization", "queued_tool_calls",
    )})
    result["root_objective"] = str(result.get("root_objective") or value.get("objective") or objective)
    result["steps"] = [item for item in list(result["steps"] or []) if isinstance(item, dict)][-MAX_STEPS:]
    actions = dict(result["completed_actions"] or {})
    result["completed_actions"] = dict(list(actions.items())[-MAX_ACTIONS:])
    result["provider_reliability"] = reliability.normalize_state(value.get("provider_reliability"))
    result["executive"] = executive.normalize(value.get("executive"))
    result["decision_finalization"] = value.get("decision_finalization") is True
    result["queued_tool_calls"] = [item for item in (result.get("queued_tool_calls") or []) if isinstance(item, dict)][:16]
    result["operation_ledger"] = operation_ledger.normalize(value.get("operation_ledger"), route_id=route_id)
    result["loop_counters"] = normalize_counters(value.get("loop_counters"))
    result["usages"] = [item for item in list(value.get("usages") or []) if isinstance(item, dict)][-16:]
    totals = value.get("usage_totals")
    if isinstance(totals, dict):
        result["usage_totals"] = usage.normalize(totals)
    else:
        aggregate = usage.empty()
        for item in result["usages"]:
            aggregate = usage.record(aggregate, item)
        result["usage_totals"] = aggregate
    result["status"] = "running"
    return result


def action_id(name: str, arguments: dict[str, Any], route_id: str = "", revision: int | None = None) -> str:
    payload: dict[str, Any] = {"route": route_id, "tool": name, "arguments": arguments}
    # Reads and proof operations may be repeated after a mutation. Replaying the
    # same mutation is intentionally still treated as a duplicate.
    if revision is not None and name != "edit":
        payload["revision"] = max(0, int(revision))
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "act_" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 32:
        return value[:limit]
    head = (limit * 2) // 3
    tail = limit - head - 17
    return value[:head] + "\n...[clipped]...\n" + value[-max(0, tail):]


def _bounded(value: Any, *, depth: int = 0, content_limit: int = MAX_CONTENT_CHARS, key: str = "") -> Any:
    if depth > 5:
        return "[depth-clipped]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        limit = content_limit if key == "content" else 4_000 if key in {"diff", "stdout", "stderr", "text"} else 1_200
        if limit <= 0 and key == "content":
            return None
        return _clip(value, max(0, limit))
    if isinstance(value, list):
        return [_bounded(item, depth=depth + 1, content_limit=content_limit) for item in value[:32]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for child_key, item in list(value.items())[:48]:
            clean_key = str(child_key)[:120]
            projected = _bounded(item, depth=depth + 1, content_limit=content_limit, key=clean_key)
            if projected is not None:
                result[clean_key] = projected
        return result
    return _bounded(str(value), depth=depth, content_limit=content_limit, key=key)


def _encoded_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=True, separators=(",", ":"), default=str))


def _fit(value: dict[str, Any], limit: int) -> dict[str, Any]:
    """Apply one global serialized bound after per-field projection."""
    for _ in range(128):
        if _encoded_chars(value) <= limit:
            return value
        strings: list[tuple[int, dict[str, Any], str]] = []
        lists: list[list[Any]] = []

        def visit(item: Any) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    if isinstance(child, str) and len(child) > 64:
                        strings.append((len(child), item, key))
                    else:
                        visit(child)
            elif isinstance(item, list):
                if len(item) > 1:
                    lists.append(item)
                for child in item:
                    visit(child)

        visit(value)
        if strings:
            size, parent, key = max(strings, key=lambda row: row[0])
            parent[key] = _clip(parent[key], max(48, size // 2))
            continue
        if lists:
            max(lists, key=len).pop()
            continue
        break
    return value


def compact_observation(
    value: Any, *, content_limit: int = MAX_CONTENT_CHARS,
    max_chars: int = MAX_OBSERVATION_CHARS,
) -> dict[str, Any]:
    """Bound one model-visible observation while retaining proof metadata."""
    if not isinstance(value, dict):
        return {"ok": False, "code": "tool_result_invalid", "summary": "Tool returned no structured observation."}
    projected = _bounded(value, content_limit=max(0, min(int(content_limit), MAX_CONTENT_CHARS)))
    if not isinstance(projected, dict):
        return {}
    return _fit(projected, max(2_000, min(int(max_chars), MAX_OBSERVATION_CHARS)))


_RECEIPT_FIELDS = frozenset({
    "ok", "code", "summary", "schema", "primitive", "local_action", "tool", "route_id",
    "path", "old_path", "start_line", "end_line", "line_count", "sha256", "receipt_sha256",
    "bytes", "file_bytes", "redacted", "truncated", "limitations", "status", "check_id",
    "returncode", "duration_ms", "timed_out", "termination", "applied", "dry_run", "operations",
    "changed_files", "postimage_sha256", "checks", "matches", "focus", "coverage", "stat",
    "truncation", "result", "owner_file", "key_symbols", "suggested_ranges",
    "related_tests", "scan_truncated", "name", "line", "files_considered", "bytes_read",
    "complete", "lanes", "universe", "reported", "staged", "worktree", "modified", "added",
    "deleted", "renamed", "copied", "untracked", "conflicted", "type_changed", "unknown",
})
_RECEIPT_MAPS = frozenset({"postimage_sha256", "lanes", "truncation"})


def _receipt_value(value: Any, *, key: str = "") -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _clip(value, 600)
    if isinstance(value, list):
        return [_receipt_value(item) for item in value[:64]]
    if isinstance(value, dict):
        if key in _RECEIPT_MAPS:
            return {str(child)[:300]: _receipt_value(item) for child, item in list(value.items())[:128]}
        return {
            str(child)[:120]: _receipt_value(item, key=str(child))
            for child, item in list(value.items())[:96]
            if str(child) in _RECEIPT_FIELDS
        }
    return _clip(str(value), 300)


def receipt(value: Any) -> dict[str, Any]:
    """Return a content-free final/proof receipt to avoid duplicating evidence."""
    projected = _receipt_value(value)
    return projected if isinstance(projected, dict) else {}


def summary(state: dict[str, Any]) -> dict[str, Any]:
    """Return the content-free trajectory stored in finals and sent to clients."""
    steps = []
    for step in state.get("steps", [])[-MAX_STEPS:]:
        if not isinstance(step, dict):
            continue
        projected = {
            key: step.get(key)
            for key in ("sequence", "kind", "action_id", "tool", "status", "summary")
            if step.get(key) not in (None, "")
        }
        if isinstance(step.get("result"), dict):
            projected["result"] = receipt(step["result"])
        steps.append(projected)
    return {
        "schema": SUMMARY_SCHEMA,
        "run_id": str(state.get("run_id") or "")[:160],
        "turn_id": str(state.get("turn_id") or "")[:160],
        "route_id": str(state.get("route_id") or "")[:160],
        "root_objective": _clip(str(state.get("root_objective") or ""), 1200),
        "status": str(state.get("status") or "")[:40],
        "steps": steps,
        "completed_action_count": len(state.get("completed_actions") or {}),
        "provider_reliability": reliability.normalize_state(state.get("provider_reliability")),
        "loop_counters": normalize_counters(state.get("loop_counters")),
        "operations": operation_ledger.project(state.get("operation_ledger") or {}),
        "last_error": _bounded(state.get("last_error"), content_limit=0),
    }


def append(state: dict[str, Any], step: dict[str, Any]) -> None:
    prior = [int(item.get("sequence") or 0) for item in state.get("steps", []) if isinstance(item, dict)]
    state.setdefault("steps", []).append({"sequence": max(prior, default=0) + 1, **step})
    state["steps"] = state["steps"][-MAX_STEPS:]


def checkpoint(state: dict[str, Any], code: str, message: str) -> dict[str, Any]:
    state["status"] = "resumable"
    state["last_error"] = {"code": code, "message": message}
    return state


def prior_tool_results(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one bounded result per completed action for proof after resume."""
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for step in state.get("steps", []):
        if not isinstance(step, dict) or step.get("kind") != "tool" or not isinstance(step.get("result"), dict):
            continue
        action = str(step.get("action_id") or "")
        if action:
            seen.add(action)
        results.append(dict(step["result"]))
    for action, receipt in (state.get("completed_actions") or {}).items():
        if action in seen or not isinstance(receipt, dict):
            continue
        result = receipt.get("observation") if isinstance(receipt.get("observation"), dict) else receipt
        results.append(dict(result))
    return results[-MAX_ACTIONS:]
