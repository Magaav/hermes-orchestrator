"""Source-owned capability promotion and compact projection."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "hermes.wasm_agent.capability_registry.v1"
VALID_CLASSES = frozenset({"exact", "predictive", "anti_predictive", "proof", "hypothesis"})
VALID_STATES = frozenset({"discovered", "candidate", "calibrated", "promoted", "demoted", "rejected"})
VALID_CLAIM_STATUSES = frozenset({
    "verified", "implemented-unverified", "proposal", "future", "stale", "unknown",
})
MAX_CAPABILITIES = 128


class CapabilityFoundryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def default_registry_path() -> Path:
    return Path(__file__).with_name("capability_registry.json")


def _text(value: Any, field: str, *, limit: int = 240) -> str:
    text = str(value or "").strip()
    if not text or len(text) > limit:
        raise CapabilityFoundryError("capability_registry_invalid", f"Capability {field} is invalid.")
    return text


def _strings(value: Any, field: str, *, maximum: int = 32) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise CapabilityFoundryError("capability_registry_invalid", f"Capability {field} must be a bounded list.")
    return [str(item)[:240] for item in value if str(item or "").strip()]


def load(path: str | Path | None = None) -> dict[str, Any]:
    source = Path(path) if path is not None else default_registry_path()
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityFoundryError("capability_registry_unavailable", str(exc)) from exc
    if value.get("schema") != SCHEMA or not isinstance(value.get("capabilities"), list):
        raise CapabilityFoundryError("capability_registry_invalid", "Capability registry schema is invalid.")
    if len(value["capabilities"]) > MAX_CAPABILITIES:
        raise CapabilityFoundryError("capability_registry_invalid", "Capability registry exceeds its bound.")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for raw in value["capabilities"]:
        if not isinstance(raw, dict):
            raise CapabilityFoundryError("capability_registry_invalid", "Capability records must be objects.")
        capability_id = _text(raw.get("id"), "id", limit=160)
        if capability_id in seen:
            raise CapabilityFoundryError("capability_registry_duplicate", f"Duplicate capability: {capability_id}")
        seen.add(capability_id)
        capability_class = str(raw.get("class") or "")
        state = str(raw.get("state") or "")
        claim_status = str(raw.get("claim_status") or "")
        if capability_class not in VALID_CLASSES or state not in VALID_STATES or claim_status not in VALID_CLAIM_STATUSES:
            raise CapabilityFoundryError("capability_registry_invalid", f"Capability enums are invalid: {capability_id}")
        evidence = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
        record = {
            "id": capability_id,
            "class": capability_class,
            "state": state,
            "claim_status": claim_status,
            "owner": _text(raw.get("owner"), "owner"),
            "version": _text(raw.get("version"), "version", limit=80),
            "entry": _text(raw.get("entry"), "entry"),
            "artifact_sha256": str(raw.get("artifact_sha256") or "")[:64],
            "input": _text(raw.get("input"), "input"),
            "output": _text(raw.get("output"), "output"),
            "limits": _strings(raw.get("limits"), "limits"),
            "side_effects": _strings(raw.get("side_effects"), "side_effects"),
            "routes": _strings(raw.get("routes"), "routes"),
            "required_caps": _strings(raw.get("required_caps"), "required_caps"),
            "evidence": {
                "status": str(evidence.get("status") or "missing"),
                "classes": _strings(evidence.get("classes") or [], "evidence.classes"),
                "verifier": str(evidence.get("verifier") or "")[:300],
            },
            "blockers": _strings(raw.get("blockers"), "blockers"),
            "invalidated_by": _strings(raw.get("invalidated_by"), "invalidated_by"),
        }
        digest_source = {key: item for key, item in record.items() if key != "digest"}
        record["digest"] = hashlib.sha256(
            json.dumps(digest_source, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(),
        ).hexdigest()
        normalized.append(record)
    return {
        "schema": SCHEMA,
        "version": int(value.get("version") or 1),
        "capabilities": normalized,
    }


def evaluate(record: dict[str, Any], *, route_id: str = "", available_caps: list[str] | None = None) -> dict[str, Any]:
    caps = {str(item) for item in (available_caps or [])}
    failures: list[str] = []
    if record["state"] != "promoted":
        failures.append(f"state:{record['state']}")
    if record["claim_status"] != "verified":
        failures.append(f"claim:{record['claim_status']}")
    if record["evidence"]["status"] != "pass":
        failures.append("evidence")
    if record["blockers"]:
        failures.append("blockers")
    if route_id and route_id not in record["routes"]:
        failures.append("route")
    missing_caps = sorted(set(record["required_caps"]) - caps)
    if missing_caps:
        failures.append("caps")
    return {
        "id": record["id"],
        "eligible": not failures,
        "failures": failures,
        "missing_caps": missing_caps,
        "digest": record["digest"],
    }


def undeclared_routes(registry: dict[str, Any], declared_routes: list[str] | set[str]) -> list[str]:
    declared = {str(item) for item in declared_routes}
    return sorted({
        route_id
        for record in registry.get("capabilities") or []
        for route_id in record.get("routes") or []
        if route_id not in declared
    })


def project(
    registry: dict[str, Any],
    *,
    route_id: str,
    available_caps: list[str] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    projected: list[dict[str, str]] = []
    blocked = 0
    for record in registry["capabilities"]:
        decision = evaluate(record, route_id=route_id, available_caps=available_caps)
        if not decision["eligible"]:
            blocked += 1
            continue
        projected.append({
            "id": record["id"][:96],
            "class": record["class"],
            "entry": record["entry"][:80],
            "in": record["input"][:32],
            "out": record["output"][:32],
            "digest": record["digest"][:12],
        })
        if len(projected) >= max(1, min(int(limit), 16)):
            break
    return {
        "schema": "hermes.wasm_agent.capability_projection.v1",
        "route_id": str(route_id or "")[:160],
        "count": len(projected),
        "blocked": blocked,
        "capabilities": projected,
    }
