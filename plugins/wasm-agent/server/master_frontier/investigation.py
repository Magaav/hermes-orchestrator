from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


SCHEMA = "INVESTIGATION/1"
ANSWERABILITY = {
    "unresolved", "supported", "ambiguous", "not_found_with_coverage",
    "capability_blocked", "scope_unresolved",
}
MAX_STATE_BYTES = 16_384


class InvestigationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def new_state(investigation_id: str, objective: str, *, question: str = "") -> dict[str, Any]:
    return {
        "schema": SCHEMA, "investigation_id": str(investigation_id), "revision": 0,
        "original_objective": str(objective), "normalized_question": str(question or objective).strip(),
        "hypotheses": [], "facts": [], "unknowns": [], "contradictions": [],
        "search_coverage": {}, "capability_health": {}, "latest_progress_delta": [],
        "next_proposed_probe": None, "expected_information_gain": "", "answerability": "unresolved",
    }


def _ids(items: list[Any], key: str) -> set[str]:
    return {str(item.get(key) or "") for item in items if isinstance(item, dict) and item.get(key)}


def validate(state: dict[str, Any], *, visible_handles: set[str] | None = None, max_bytes: int = MAX_STATE_BYTES) -> dict[str, Any]:
    if not isinstance(state, dict) or state.get("schema") != SCHEMA:
        raise InvestigationError("investigation_schema_invalid", "Investigation state must use INVESTIGATION/1.")
    if not str(state.get("investigation_id") or "") or not str(state.get("original_objective") or ""):
        raise InvestigationError("investigation_identity_missing", "Investigation identity and objective are required.")
    if not isinstance(state.get("revision"), int) or state["revision"] < 0:
        raise InvestigationError("investigation_revision_invalid", "Revision must be a non-negative integer.")
    if state.get("answerability") not in ANSWERABILITY:
        raise InvestigationError("answerability_invalid", "Unknown answerability status.")
    for key in ("hypotheses", "facts", "unknowns", "contradictions", "latest_progress_delta"):
        if not isinstance(state.get(key), list):
            raise InvestigationError("investigation_field_invalid", f"{key} must be a list.")
    if not isinstance(state.get("search_coverage"), dict) or not isinstance(state.get("capability_health"), dict):
        raise InvestigationError("investigation_field_invalid", "Coverage and capability health must be objects.")
    visible = visible_handles
    for fact in state["facts"]:
        if not isinstance(fact, dict) or not str(fact.get("text") or "") or not fact.get("evidence_handles"):
            raise InvestigationError("fact_evidence_missing", "Every fact requires text and evidence handles.")
        handles = {str(item) for item in fact["evidence_handles"]}
        if visible is not None and not handles.issubset(visible):
            raise InvestigationError("fact_evidence_unobserved", "Facts may cite only model-visible evidence.")
    if len(canonical(state)) > max_bytes:
        raise InvestigationError("investigation_state_overflow", "Investigation state exceeds its byte bound.")
    return state


def _merge_by_id(existing: list[Any], additions: list[Any], key: str) -> list[Any]:
    result = deepcopy(existing)
    seen = _ids(result, key)
    for item in additions:
        if not isinstance(item, dict) or not str(item.get(key) or ""):
            raise InvestigationError("patch_item_identity_missing", f"Patch item requires {key}.")
        if str(item[key]) not in seen:
            result.append(deepcopy(item)); seen.add(str(item[key]))
    return result


def semantic_progress(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    changes: list[str] = []
    for key, label, item_key in (("hypotheses", "hypothesis", "id"), ("facts", "fact", "id"), ("contradictions", "contradiction", "id")):
        if _ids(after[key], item_key) != _ids(before[key], item_key): changes.append(label)
    if canonical(after["search_coverage"]) != canonical(before["search_coverage"]): changes.append("coverage")
    if canonical(after["capability_health"]) != canonical(before["capability_health"]): changes.append("capability")
    if after["answerability"] != before["answerability"]: changes.append("answerability")
    return changes


def apply_patch(
    state: dict[str, Any], patch: dict[str, Any], *, visible_handles: set[str],
    tool_coverage: dict[str, Any] | None = None, tool_capability_health: dict[str, Any] | None = None,
    max_bytes: int = MAX_STATE_BYTES,
) -> dict[str, Any]:
    validate(state, visible_handles=visible_handles, max_bytes=max_bytes)
    if int(patch.get("base_revision", -1)) != state["revision"]:
        raise InvestigationError("obsolete_state_revision", "Patch does not target the current revision.")
    candidate = deepcopy(state)
    for field, key in (("add_hypotheses", "id"), ("add_facts", "id"), ("add_unknowns", "id"), ("add_contradictions", "id")):
        target = field.removeprefix("add_")
        if field in patch:
            candidate[target] = _merge_by_id(candidate[target], patch[field], key)
    removals = patch.get("eliminate_hypotheses") or []
    for removal in removals:
        if not isinstance(removal, dict) or not removal.get("id") or not (removal.get("evidence_handles") or removal.get("logical_justification")):
            raise InvestigationError("hypothesis_elimination_unjustified", "Elimination requires counterevidence or typed logic.")
        cited = {str(item) for item in removal.get("evidence_handles") or []}
        if not cited.issubset(visible_handles):
            raise InvestigationError("hypothesis_evidence_unobserved", "Elimination cites unobserved evidence.")
        candidate["hypotheses"] = [item for item in candidate["hypotheses"] if item.get("id") != removal["id"]]
    resolutions = {str(item.get("id")): item for item in patch.get("resolve_contradictions") or [] if isinstance(item, dict)}
    for cid, resolution in resolutions.items():
        cited = {str(item) for item in resolution.get("evidence_handles") or []}
        if not cited or not cited.issubset(visible_handles):
            raise InvestigationError("contradiction_resolution_uncited", "Contradiction resolution requires visible evidence.")
        candidate["contradictions"] = [item for item in candidate["contradictions"] if str(item.get("id")) != cid]
    if "search_coverage" in patch and tool_coverage is None:
        raise InvestigationError("coverage_model_invented", "Coverage values must originate from tools.")
    if tool_coverage is not None: candidate["search_coverage"] = deepcopy(tool_coverage)
    if tool_capability_health is not None: candidate["capability_health"] = deepcopy(tool_capability_health)
    for field in ("next_proposed_probe", "expected_information_gain", "answerability"):
        if field in patch: candidate[field] = deepcopy(patch[field])
    candidate["revision"] += 1
    candidate["latest_progress_delta"] = semantic_progress(state, candidate)
    return validate(candidate, visible_handles=visible_handles, max_bytes=max_bytes)


def compact(state: dict[str, Any], *, max_bytes: int = MAX_STATE_BYTES) -> dict[str, Any]:
    candidate = deepcopy(state)
    if len(canonical(candidate)) <= max_bytes: return candidate
    for collection in ("facts", "hypotheses", "unknowns", "contradictions"):
        for item in candidate[collection]:
            if isinstance(item, dict) and "detail" in item:
                item["detail_ref"] = "sha256:" + hashlib.sha256(canonical(item["detail"])).hexdigest()
                item.pop("detail", None)
    if len(canonical(candidate)) > max_bytes:
        raise InvestigationError("investigation_state_overflow", "Reference compaction could not satisfy the state bound.")
    return candidate
