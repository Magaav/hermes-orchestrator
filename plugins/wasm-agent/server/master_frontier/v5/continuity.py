"""Bounded, scope-bound restart checkpoints for Master:frontier V5."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from . import executive, operation_ledger, trajectory, usage


SCHEMA = "master.frontier.v5.checkpoint.v1"
PROTOCOL = "v5"
MAX_CHECKPOINT_CHARS = 22_000
MAX_STEPS = 12
MAX_ACTIONS = 24


class ContinuityError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:24]


def contract_digest(route: dict[str, Any]) -> str:
    owned = {
        key: route.get(key)
        for key in (
            "route_id", "owner", "workspace_root", "allowed_read_roots", "allowed_write_roots",
            "caps", "checks", "budget", "source_index", "task_contract",
        )
    }
    return hashlib.sha256(json.dumps(owned, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def binding(*, user_id: str, session_id: str, route_id: str, route_digest: str = "", source_run_id: str = "", source_turn_id: str = "") -> dict[str, str]:
    return {
        "principal": _hash(user_id),
        "session": _hash(session_id),
        "route_id": str(route_id or "")[:160],
        "route_digest": str(route_digest or "")[:64],
        "source_run_id": str(source_run_id or "")[:160],
        "source_turn_id": str(source_turn_id or "")[:160],
    }


def _bounded(value: Any, *, depth: int = 0, string_limit: int = 800) -> Any:
    if depth > 5:
        return "[depth-clipped]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= string_limit else value[:string_limit] + "...[clipped]"
    if isinstance(value, list):
        return [_bounded(item, depth=depth + 1, string_limit=string_limit) for item in value[:24]]
    if isinstance(value, dict):
        return {
            str(key)[:120]: _bounded(item, depth=depth + 1, string_limit=string_limit)
            for key, item in list(value.items())[:48]
        }
    return _bounded(str(value), depth=depth, string_limit=string_limit)


def _step(value: dict[str, Any]) -> dict[str, Any]:
    result = value.get("result") if isinstance(value.get("result"), dict) else None
    projected = {
        key: _bounded(item, string_limit=1200 if key == "content" else 600)
        for key, item in value.items()
        if key in {"sequence", "kind", "action_id", "tool", "status", "summary"}
    }
    if result is not None:
        projected["result"] = _observation(result)
    return projected


def _observation(value: dict[str, Any]) -> dict[str, Any]:
    """Persist receipt metadata, never raw source, command output, or diffs."""
    projected = {
        key: _bounded(item, string_limit=320)
        for key, item in value.items()
        if key in {
            "ok", "code", "summary", "runtime", "focus", "path", "start_line", "end_line",
            "line_count", "sha256", "truncated", "limitations", "primitive", "local_action", "changed_files",
            "checks", "schema", "check_id", "returncode", "duration_ms",
        }
    }
    nested = value.get("result") if isinstance(value.get("result"), dict) else None
    if nested is not None:
        projected["result"] = {
            key: _bounded(item, string_limit=240)
            for key, item in nested.items()
            if key in {
                "ok", "code", "summary", "schema", "route_id", "changed_files", "checks",
                "check_id", "returncode", "duration_ms", "applied", "dry_run", "operations",
            }
        }
    return projected


def _receipt(value: dict[str, Any]) -> dict[str, Any]:
    projected = {
        key: _bounded(item, string_limit=320)
        for key, item in value.items()
        if key in {
            "tool", "ok", "code", "summary", "runtime", "focus", "path", "start_line",
            "end_line", "sha256", "truncated", "limitations", "primitive", "local_action",
            "changed_files", "checks",
        }
    }
    observation = value.get("observation") if isinstance(value.get("observation"), dict) else value
    projected["observation"] = _observation(observation)
    return projected


def _state_projection(state: dict[str, Any]) -> dict[str, Any]:
    actions = state.get("completed_actions") if isinstance(state.get("completed_actions"), dict) else {}
    ledger = operation_ledger.normalize(state.get("operation_ledger"), route_id=str(state.get("route_id") or ""))
    mutation_actions = {
        str(item.get("action") or "")
        for item in ledger.get("mutations") or []
        if isinstance(item, dict) and item.get("action")
    }
    return {
        "schema": trajectory.SCHEMA,
        "root_objective": str(state.get("root_objective") or state.get("objective") or "")[:2000],
        "steps": [
            ({key: value for key, value in _step(item).items() if key != "result"}
             if str(item.get("action_id") or "") in mutation_actions else _step(item))
            for item in list(state.get("steps") or [])[-MAX_STEPS:]
            if isinstance(item, dict)
        ],
        "completed_actions": {
            str(key)[:80]: (
                {"tool": "edit", "observation": {"ok": True, "code": "mutation_recorded"}}
                if str(key) in mutation_actions else _receipt(value)
            )
            for key, value in list(actions.items())[-MAX_ACTIONS:]
            if isinstance(value, dict)
        },
        "pending_action": _bounded(state.get("pending_action"), string_limit=320),
        "pending": _bounded(state.get("pending"), string_limit=120),
        "last_error": _bounded(state.get("last_error"), string_limit=600),
        "completion_assessment": _bounded(state.get("completion_assessment"), string_limit=600),
        "executive": _bounded(executive.normalize(state.get("executive")), string_limit=600),
        "decision_finalization": state.get("decision_finalization") is True,
        "provider_reliability": _bounded(state.get("provider_reliability"), string_limit=120),
        "operation_ledger": operation_ledger.checkpoint(ledger),
        "loop_counters": trajectory.normalize_counters(state.get("loop_counters")),
        "usages": [_bounded(item, string_limit=160) for item in list(state.get("usages") or [])[-16:] if isinstance(item, dict)],
        "usage_totals": usage.normalize(state.get("usage_totals")),
    }


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def create(state: dict[str, Any], *, scope: dict[str, str]) -> dict[str, Any]:
    payload = {
        "schema": SCHEMA,
        "protocol": PROTOCOL,
        "scope": {key: str(scope.get(key) or "") for key in ("principal", "session", "route_id", "route_digest", "source_run_id", "source_turn_id")},
        "state": _state_projection(state),
    }
    while len(_canonical(payload)) > MAX_CHECKPOINT_CHARS and payload["state"]["steps"]:
        payload["state"]["steps"].pop(0)
    while len(_canonical(payload)) > MAX_CHECKPOINT_CHARS and payload["state"]["completed_actions"]:
        first = next(iter(payload["state"]["completed_actions"]))
        payload["state"]["completed_actions"].pop(first)
    encoded = _canonical(payload)
    if len(encoded) > MAX_CHECKPOINT_CHARS:
        raise ContinuityError("resume_checkpoint_too_large", "The bounded V5 checkpoint exceeds its persistence budget.")
    payload["sha256"] = hashlib.sha256(encoded.encode()).hexdigest()
    return payload


def _validated(value: Any, *, expected_scope: dict[str, str], previous_run_id: str = "") -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA or value.get("protocol") != PROTOCOL:
        raise ContinuityError("resume_checkpoint_invalid", "The V5 resume checkpoint schema is invalid.")
    digest = str(value.get("sha256") or "")
    unsigned = {key: item for key, item in value.items() if key != "sha256"}
    if not digest or hashlib.sha256(_canonical(unsigned).encode()).hexdigest() != digest:
        raise ContinuityError("resume_checkpoint_digest_mismatch", "The V5 resume checkpoint digest does not match its content.")
    actual = value.get("scope") if isinstance(value.get("scope"), dict) else {}
    for key in ("principal", "session", "route_id", "route_digest"):
        if str(actual.get(key) or "") != str(expected_scope.get(key) or ""):
            raise ContinuityError("resume_checkpoint_scope_mismatch", f"The V5 resume checkpoint {key} scope does not match this run.")
    source = str(previous_run_id or "")
    if source and str(actual.get("source_run_id") or "") != source:
        raise ContinuityError("resume_checkpoint_source_mismatch", "The V5 resume checkpoint belongs to a different source run.")
    state = value.get("state")
    if not isinstance(state, dict) or state.get("schema") != trajectory.SCHEMA:
        raise ContinuityError("resume_checkpoint_state_invalid", "The V5 resume checkpoint has no valid trajectory state.")
    return state


def restore(value: Any, *, expected_scope: dict[str, str], previous_run_id: str, run_id: str, turn_id: str, objective: str, route_id: str, allow_legacy: bool = False) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("schema") == trajectory.SCHEMA and allow_legacy:
        source = value
    else:
        source = _validated(value, expected_scope=expected_scope, previous_run_id=previous_run_id)
    restored = trajectory.restore(source, run_id=run_id, turn_id=turn_id, objective=objective, route_id=route_id)
    for mutation in restored["operation_ledger"].get("mutations") or []:
        action_id = str(mutation.get("action") or "") if isinstance(mutation, dict) else ""
        if action_id:
            restored["completed_actions"].setdefault(
                action_id,
                {"tool": "edit", "observation": {"ok": True, "code": "mutation_recorded"}},
            )
    restored["resumed_from"] = str(previous_run_id or (value.get("scope") or {}).get("source_run_id") or "") if isinstance(value, dict) else ""
    return restored


def replace_stale_route_checkpoint(
    value: Any, *, expected_scope: dict[str, str], previous_run_id: str,
    run_id: str, turn_id: str, objective: str, route_id: str,
) -> dict[str, Any]:
    """Preserve signed lineage while discarding state from an old route contract."""
    if not isinstance(value, dict) or value.get("schema") != SCHEMA or value.get("protocol") != PROTOCOL:
        raise ContinuityError("resume_checkpoint_invalid", "The V5 resume checkpoint schema is invalid.")
    digest = str(value.get("sha256") or "")
    unsigned = {key: item for key, item in value.items() if key != "sha256"}
    if not digest or hashlib.sha256(_canonical(unsigned).encode()).hexdigest() != digest:
        raise ContinuityError("resume_checkpoint_digest_mismatch", "The V5 resume checkpoint digest does not match its content.")
    actual = value.get("scope") if isinstance(value.get("scope"), dict) else {}
    for key in ("principal", "session", "route_id"):
        if str(actual.get(key) or "") != str(expected_scope.get(key) or ""):
            raise ContinuityError("resume_checkpoint_scope_mismatch", f"The V5 resume checkpoint {key} scope does not match this run.")
    if str(actual.get("route_digest") or "") == str(expected_scope.get("route_digest") or ""):
        raise ContinuityError("resume_checkpoint_not_stale", "The V5 resume checkpoint already matches the current route contract.")
    if previous_run_id and str(actual.get("source_run_id") or "") != str(previous_run_id):
        raise ContinuityError("resume_checkpoint_source_mismatch", "The V5 resume checkpoint belongs to a different source run.")
    source = value.get("state") if isinstance(value.get("state"), dict) else {}
    if source.get("schema") != trajectory.SCHEMA:
        raise ContinuityError("resume_checkpoint_state_invalid", "The V5 resume checkpoint has no valid trajectory state.")
    root_objective = str(source.get("root_objective") or "").strip()
    if not root_objective:
        raise ContinuityError("resume_checkpoint_objective_missing", "The stale V5 checkpoint has no signed root objective.")
    replaced = trajectory.new(run_id, turn_id, root_objective, route_id)
    replaced["objective"] = str(objective or root_objective)
    replaced["root_objective"] = root_objective
    replaced["resumed_from"] = str(previous_run_id or actual.get("source_run_id") or "")
    trajectory.append(replaced, {
        "kind": "system", "tool": "continuity", "status": "rejected",
        "summary": "Discarded a checkpoint from an older route contract and started clean under the current contract.",
        "result": {"ok": False, "code": "stale_checkpoint_replaced"},
    })
    return replaced


def continuation_context(envelope: dict[str, Any]) -> dict[str, Any]:
    compact = envelope.get("compact_state") if isinstance(envelope.get("compact_state"), dict) else {}
    value = compact.get("continuation_context")
    return value if isinstance(value, dict) else {}


def request_checkpoint(body: dict[str, Any], envelope: dict[str, Any]) -> Any:
    if isinstance(body.get("resume_checkpoint"), dict):
        return body["resume_checkpoint"]
    context = continuation_context(envelope)
    return context.get("resume_checkpoint") if isinstance(context.get("resume_checkpoint"), dict) else None


def model_projection(state: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = context or {}
    pending = state.get("pending_action") if isinstance(state.get("pending_action"), dict) else {}
    result = {
        "resumed": bool(state.get("resumed_from")),
        "root_objective": str(state.get("root_objective") or "")[:1200],
        "previous_run_id": str(state.get("resumed_from") or context.get("previous_run_id") or "")[:160],
        "previous_status": str(context.get("previous_status") or "")[:40],
        "completed_action_count": len(state.get("completed_actions") or {}),
        "operations": operation_ledger.project(state.get("operation_ledger") or {}),
    }
    if pending:
        result["pending_action"] = {key: pending.get(key) for key in ("action_id", "tool", "status") if pending.get(key)}
    return result
