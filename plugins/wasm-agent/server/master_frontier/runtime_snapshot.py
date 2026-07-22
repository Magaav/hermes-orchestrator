"""Bounded read-only runtime snapshot contract; collection is owned elsewhere."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

SCHEMA = "wasm-agent.runtime-snapshot.v1"
STATUSES = frozenset({"available", "degraded", "unavailable", "unknown"})
FRESHNESS_STATES = frozenset({"fresh", "stale", "unknown"})
MAX_BYTES = 8192
MAX_CAPABILITIES = 16
MAX_COUNTERS = 16
MAX_UNKNOWNS = 8
MAX_PROOF_REFS = 8
PROOF_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
PROOF_LOOKUP = re.compile(r"^runtime\.proof\.get:[A-Za-z0-9._-]{1,96}$")


class SnapshotError(ValueError):
    """A collector result violated the runtime snapshot boundary."""


def contract() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "max_bytes": MAX_BYTES,
        "required": ["entity", "status", "freshness", "capabilities", "counters", "proof_refs", "unknowns", "redaction"],
        "status_values": sorted(STATUSES),
        "freshness_values": sorted(FRESHNESS_STATES),
        "limits": {"capabilities": MAX_CAPABILITIES, "counters": MAX_COUNTERS, "proof_refs": MAX_PROOF_REFS, "unknowns": MAX_UNKNOWNS},
        "authority": "read_only_snapshot",
        "forbidden": ["secrets", "raw_logs", "binary", "base64", "control_actions", "host_paths"],
    }


def _text(value: Any, field: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > limit:
        raise SnapshotError(f"{field}_invalid")
    return text


def _timestamp(value: Any, field: str) -> str:
    text = _text(value, field, 40)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotError(f"{field}_invalid") from exc
    if parsed.tzinfo is None:
        raise SnapshotError(f"{field}_timezone_required")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _named_map(value: Any, field: str, limit: int, *, counters: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict) or len(value) > limit:
        raise SnapshotError(f"{field}_invalid")
    result: dict[str, Any] = {}
    for raw_name, raw_value in sorted(value.items()):
        name = _text(raw_name, f"{field}_name", 64)
        if counters:
            if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0 or raw_value > 1_000_000_000:
                raise SnapshotError(f"{field}_value_invalid")
            result[name] = raw_value
        elif isinstance(raw_value, bool):
            result[name] = raw_value
        else:
            result[name] = _text(raw_value, f"{field}_value", 80)
    return result


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SnapshotError("snapshot_invalid")
    entity = raw.get("entity") if isinstance(raw.get("entity"), dict) else {}
    freshness = raw.get("freshness") if isinstance(raw.get("freshness"), dict) else {}
    status = _text(raw.get("status"), "status", 24).lower()
    freshness_state = _text(freshness.get("state"), "freshness_state", 24).lower()
    if status not in STATUSES:
        raise SnapshotError("status_unsupported")
    if freshness_state not in FRESHNESS_STATES:
        raise SnapshotError("freshness_state_unsupported")
    age_ms = freshness.get("age_ms")
    max_age_ms = freshness.get("max_age_ms")
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 or item > 86_400_000 for item in (age_ms, max_age_ms)):
        raise SnapshotError("freshness_window_invalid")
    proof_refs = raw.get("proof_refs")
    if not isinstance(proof_refs, list) or len(proof_refs) > MAX_PROOF_REFS:
        raise SnapshotError("proof_refs_invalid")
    normalized_refs = []
    for item in proof_refs:
        if not isinstance(item, dict):
            raise SnapshotError("proof_ref_invalid")
        proof_id = _text(item.get("id"), "proof_ref_id", 96)
        digest = _text(item.get("digest"), "proof_ref_digest", 128)
        lookup = _text(item.get("lookup"), "proof_ref_lookup", 160)
        if not PROOF_DIGEST.fullmatch(digest):
            raise SnapshotError("proof_ref_digest_invalid")
        if not PROOF_LOOKUP.fullmatch(lookup) or lookup.rsplit(":", 1)[-1] != proof_id:
            raise SnapshotError("proof_ref_lookup_invalid")
        normalized_refs.append({
            "id": proof_id,
            "kind": _text(item.get("kind"), "proof_ref_kind", 48),
            "digest": digest,
            "lookup": lookup,
        })
    unknowns = raw.get("unknowns")
    if not isinstance(unknowns, list) or len(unknowns) > MAX_UNKNOWNS:
        raise SnapshotError("unknowns_invalid")
    normalized_unknowns = []
    for item in unknowns:
        if not isinstance(item, dict):
            raise SnapshotError("unknown_invalid")
        normalized_unknowns.append({
            "code": _text(item.get("code"), "unknown_code", 64),
            "field": _text(item.get("field"), "unknown_field", 64),
        })
    redaction = raw.get("redaction") if isinstance(raw.get("redaction"), dict) else {}
    if redaction.get("applied") is not True:
        raise SnapshotError("redaction_required")
    result = {
        "schema": SCHEMA,
        "entity": {
            "route_id": _text(entity.get("route_id"), "route_id", 160),
            "id": _text(entity.get("id"), "entity_id", 120),
            "kind": _text(entity.get("kind"), "entity_kind", 64),
        },
        "status": status,
        "freshness": {
            "state": freshness_state,
            "observed_at": _timestamp(freshness.get("observed_at"), "observed_at"),
            "age_ms": age_ms,
            "max_age_ms": max_age_ms,
            "trusted": freshness.get("trusted") is True and freshness_state == "fresh" and age_ms <= max_age_ms,
        },
        "capabilities": _named_map(raw.get("capabilities"), "capabilities", MAX_CAPABILITIES),
        "counters": _named_map(raw.get("counters"), "counters", MAX_COUNTERS, counters=True),
        "proof_refs": normalized_refs,
        "unknowns": normalized_unknowns,
        "redaction": {"applied": True, "class": _text(redaction.get("class"), "redaction_class", 64)},
    }
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > MAX_BYTES:
        raise SnapshotError("snapshot_too_large")
    result["snapshot_digest"] = hashlib.sha256(encoded).hexdigest()
    return result


def model_projection(snapshot: dict[str, Any]) -> dict[str, Any]:
    value = normalize(snapshot)
    return {
        "v": 1,
        "e": value["entity"],
        "s": value["status"],
        "f": value["freshness"],
        "c": value["capabilities"],
        "n": value["counters"],
        "p": [{"id": item["id"], "kind": item["kind"]} for item in value["proof_refs"]],
        "u": value["unknowns"],
        "d": value["snapshot_digest"],
    }
