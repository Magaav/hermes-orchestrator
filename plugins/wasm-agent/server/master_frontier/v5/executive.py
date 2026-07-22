"""Bounded model-owned executive state; the host stores but does not author it."""

from __future__ import annotations

from typing import Any

from . import decision_record

FIELDS = ("goal", "situation", "plan", "hypotheses", "open", "next", "done")
LIMITS = {"goal": 1200, "situation": 2400, "plan": 2400, "hypotheses": 2000, "open": 1600, "next": 1200, "done": 1600}
OUTCOME_STATES = frozenset({"open", "done", "dropped", "blocked"})
MAX_OUTCOMES = 12


def empty() -> dict[str, Any]:
    return {**{field: "" for field in FIELDS}, "outcomes": [], "decision": decision_record.normalize({})}


def normalize(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    result: dict[str, Any] = {
        field: str(source.get(field) or "").replace("\x00", " ").strip()[:LIMITS[field]]
        for field in FIELDS
    }
    outcomes = []
    for index, item in enumerate(source.get("outcomes") if isinstance(source.get("outcomes"), list) else []):
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "open").strip().lower()
        outcomes.append({
            "id": str(item.get("id") or f"outcome-{index + 1}").replace("\x00", " ").strip()[:80],
            "state": state if state in OUTCOME_STATES else "open",
            "objective": str(item.get("objective") or "").replace("\x00", " ").strip()[:600],
            "requires": str(item.get("requires") or "").replace("\x00", " ").strip()[:80],
            "evidence": str(item.get("evidence") or "").replace("\x00", " ").strip()[:600],
            "reason": str(item.get("reason") or "").replace("\x00", " ").strip()[:600],
        })
    result["outcomes"] = outcomes[:MAX_OUTCOMES]
    result["decision"] = decision_record.normalize(source.get("decision"))
    return result


def reconcile(value: Any, *, available_tools: set[str]) -> dict[str, Any]:
    result = normalize(value)
    for item in result["outcomes"]:
        required = str(item.get("requires") or "")
        if item["state"] == "open" and required and required not in available_tools:
            item["state"] = "blocked"
            item["reason"] = item["reason"] or f"Required tool is unavailable: {required}."
    return result


def open_outcomes(value: Any) -> list[dict[str, Any]]:
    return [item for item in normalize(value)["outcomes"] if item["state"] == "open"]


def project(value: Any) -> dict[str, Any]:
    normalized = normalize(value)
    projected = {key: item for key, item in normalized.items() if key != "decision" and item}
    decision = decision_record.project(normalized.get("decision"))
    if decision:
        projected["decision"] = decision
    return projected
