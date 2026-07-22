"""Compact model-authored operational decisions; never host-inferred."""

from __future__ import annotations

from typing import Any

STATES = frozenset({"selected", "blocked", "rejected", "overscoped"})
MAX_TARGETS = 12


def normalize(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    state = str(source.get("state") or "").strip().lower()
    targets = [str(item).strip()[:240] for item in (source.get("targets") or []) if str(item).strip()]
    return {
        "state": state if state in STATES else "",
        "candidate": str(source.get("candidate") or "").strip()[:1200],
        "targets": targets[:MAX_TARGETS],
        "acceptance": str(source.get("acceptance") or "").strip()[:1600],
        "blocker": str(source.get("blocker") or "").strip()[:1200],
        "next_action": str(source.get("next_action") or "").strip()[:600],
        "confidence": _confidence(source.get("confidence")),
    }


def _confidence(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(min(1.0, max(0.0, number)), 3)


def validate(value: Any) -> tuple[dict[str, Any], list[str]]:
    record = normalize(value)
    missing: list[str] = []
    if not record["state"]:
        missing.append("state")
    if record["state"] in {"selected", "overscoped"}:
        for field in ("candidate", "targets", "acceptance", "next_action"):
            if not record[field]:
                missing.append(field)
    elif record["state"] in {"blocked", "rejected"}:
        for field in ("candidate", "blocker"):
            if not record[field]:
                missing.append(field)
    return record, missing


def ready(value: Any) -> bool:
    _record, missing = validate(value)
    return not missing


def project(value: Any) -> dict[str, Any]:
    record = normalize(value)
    return {key: item for key, item in record.items() if item not in (None, "", [])}
