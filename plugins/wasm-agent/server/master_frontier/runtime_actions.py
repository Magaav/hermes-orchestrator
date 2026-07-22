"""Model-facing runtime read schemas with host-only authority enforcement."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import runtime_proof, runtime_snapshot, runtime_snapshot_collector

SNAPSHOT_GET = "runtime.snapshot.get"
PROOF_GET = "runtime.proof.get"
ALLOWED = frozenset({SNAPSHOT_GET, PROOF_GET})


class ActionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def action_schemas() -> list[dict[str, Any]]:
    scope = {
        "route_id": {"type": "string", "minLength": 1, "maxLength": 160},
        "entity_id": {"type": "string", "minLength": 1, "maxLength": 120},
    }
    return [
        {
            "name": SNAPSHOT_GET,
            "description": "Read one bounded redacted historical runtime snapshot for an already-authorized route entity. This does not prove current live state.",
            "input_schema": {
                "type": "object",
                "required": ["route_id", "entity_id"],
                "properties": scope,
                "additionalProperties": False,
            },
        },
        {
            "name": PROOF_GET,
            "description": "Resolve one opaque runtime proof reference under the same authorized route and entity scope.",
            "input_schema": {
                "type": "object",
                "required": ["route_id", "entity_id", "proof_id"],
                "properties": {**scope, "proof_id": {"type": "string", "pattern": r"^run-store-[0-9a-f]{24}$"}},
                "additionalProperties": False,
            },
        },
    ]


def provider_tools() -> list[dict[str, Any]]:
    return [
        {"type": "function", "function": {"name": item["name"], "description": item["description"], "parameters": item["input_schema"]}}
        for item in action_schemas()
    ]


def _entity(authority: dict[str, Any], args: dict[str, Any]) -> dict[str, str]:
    allowed_keys = {"route_id", "entity_id", "proof_id"}
    if not isinstance(args, dict) or set(args) - allowed_keys:
        raise ActionError("runtime_action_arguments_invalid")
    route_id = str(args.get("route_id") or "").strip()
    entity_id = str(args.get("entity_id") or "").strip()
    if not route_id or not entity_id:
        raise ActionError("runtime_action_scope_missing")
    if len(route_id) > 160 or len(entity_id) > 120:
        raise ActionError("runtime_action_scope_invalid")
    if "runtime.inspect" not in set(authority.get("capabilities") or []):
        raise ActionError("runtime_action_capability_denied")
    if route_id != str(authority.get("route_id") or ""):
        raise ActionError("runtime_action_route_denied")
    entities = authority.get("entities") if isinstance(authority.get("entities"), list) else []
    matches = [item for item in entities if isinstance(item, dict) and str(item.get("id") or "") == entity_id]
    if len(matches) != 1:
        raise ActionError("runtime_action_entity_denied")
    kind = str(matches[0].get("kind") or "").strip()
    if not kind:
        raise ActionError("runtime_action_entity_kind_missing")
    return {"route_id": route_id, "entity_id": entity_id, "entity_kind": kind}


def execute(
    action: str,
    args: dict[str, Any],
    *,
    authority: dict[str, Any],
    db_path: Path,
    now_ms: int,
) -> dict[str, Any]:
    if action not in ALLOWED:
        raise ActionError("runtime_action_unsupported")
    user_id = str(authority.get("user_id") or "").strip()
    if not user_id:
        raise ActionError("runtime_action_user_missing")
    scope = _entity(authority, args)
    try:
        max_age_ms = int(authority.get("max_age_ms") or 30_000)
    except (TypeError, ValueError) as exc:
        raise ActionError("runtime_action_freshness_invalid") from exc
    if max_age_ms < 1 or max_age_ms > 86_400_000:
        raise ActionError("runtime_action_freshness_invalid")
    try:
        if action == SNAPSHOT_GET:
            snapshot = runtime_snapshot_collector.collect(
                db_path,
                user_id=user_id,
                route_id=scope["route_id"],
                entity_id=scope["entity_id"],
                entity_kind=scope["entity_kind"],
                now_ms=now_ms,
                max_age_ms=max_age_ms,
            )
            return {"ok": True, "action": action, "snapshot": runtime_snapshot.model_projection(snapshot)}
        proof_id = str(args.get("proof_id") or "").strip()
        if not runtime_proof.PROOF_ID.fullmatch(proof_id):
            raise ActionError("runtime_action_proof_id_invalid")
        proof = runtime_proof.resolve(
            db_path,
            user_id=user_id,
            route_id=scope["route_id"],
            entity_id=scope["entity_id"],
            proof_id=proof_id,
            now_ms=now_ms,
            max_age_ms=max_age_ms,
        )
        return {"ok": True, "action": action, "proof": proof}
    except (runtime_snapshot_collector.CollectorError, runtime_proof.ProofError) as exc:
        raise ActionError(str(exc)) from exc
