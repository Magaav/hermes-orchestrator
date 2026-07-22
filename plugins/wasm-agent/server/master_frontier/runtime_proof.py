"""Scoped resolver for opaque runtime snapshot proof references."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import runtime_snapshot_collector as collector

SCHEMA = "wasm-agent.runtime-proof.v1"
PROOF_ID = re.compile(r"^run-store-[0-9a-f]{24}$")
MAX_BYTES = 4096
RUN_STATUSES = frozenset({"pending", "queued", "starting", "running", "completed", "failed", "interrupted", "cancelled"})


class ProofError(RuntimeError):
    """An opaque runtime proof could not be resolved within its scope."""


def _iso(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve(
    db_path: Path,
    *,
    user_id: str,
    route_id: str,
    entity_id: str,
    proof_id: str,
    now_ms: int,
    max_age_ms: int = 30_000,
) -> dict[str, Any]:
    if not PROOF_ID.fullmatch(proof_id):
        raise ProofError("runtime_proof_id_invalid")
    if not entity_id.strip() or now_ms < 0 or max_age_ms < 1 or max_age_ms > 86_400_000:
        raise ProofError("runtime_proof_scope_invalid")
    try:
        rows = collector.scoped_rows(db_path, user_id=user_id, route_id=route_id)
    except collector.CollectorError as exc:
        raise ProofError(str(exc)) from exc
    matched = None
    matched_ref: dict[str, str] = {}
    for row in rows:
        reference = collector.proof_reference(route_id, entity_id, row)
        if reference["id"] == proof_id:
            matched = row
            matched_ref = reference
            break
    if matched is None:
        raise ProofError("runtime_proof_not_found")
    updated_at = int(matched["updated_at"] or 0)
    age_ms = max(0, now_ms - updated_at)
    freshness_state = "fresh" if age_ms <= max_age_ms else "stale"
    run_status = str(matched["status"] or "unknown").strip().lower()
    result = {
        "schema": SCHEMA,
        "proof": matched_ref,
        "entity": {"route_id": route_id, "id": entity_id},
        "evidence": {
            "run_status": run_status if run_status in RUN_STATUSES else "unknown",
            "created_at": _iso(int(matched["created_at"] or 0)),
            "updated_at": _iso(updated_at),
            "terminal_at": _iso(int(matched["terminal_at"] or 0)) if int(matched["terminal_at"] or 0) else "",
        },
        "freshness": {
            "state": freshness_state,
            "age_ms": age_ms,
            "max_age_ms": max_age_ms,
            "trusted": freshness_state == "fresh",
        },
        "redaction": {"applied": True, "class": "scoped-run-proof-v1"},
    }
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > MAX_BYTES:
        raise ProofError("runtime_proof_too_large")
    result["receipt_digest"] = hashlib.sha256(encoded).hexdigest()
    return result
