from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from . import completion, evidence, investigation


def _line_number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _negative_coverage(packet: dict[str, Any]) -> bool:
    coverage = packet.get("coverage") or []
    if not coverage or packet.get("limitations"): return False
    lane_health = packet.get("capability_health") or {}
    required = {"exact_text", "symbol", "content_file", "structural"}
    return bool(packet.get("searched_roots")) and all(lane_health.get(lane) == "searched" for lane in required) and all(bool(item.get("complete")) for item in coverage if isinstance(item, dict))


def evaluate(
    state: dict[str, Any], packet: dict[str, Any], completion_packet: dict[str, Any], *,
    visible_handles: set[str], semantic_verify: Callable[[dict[str, Any], list[dict[str, Any]]], str] | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    try: investigation.validate(state, visible_handles=visible_handles)
    except investigation.InvestigationError as exc: errors.append({"code": exc.code, "message": str(exc)})
    try: evidence.validate(packet)
    except evidence.EvidenceError as exc: errors.append({"code": exc.code, "message": str(exc)})
    try: completion.validate(completion_packet)
    except completion.CompletionError as exc: errors.append({"code": exc.code, "message": str(exc)})
    evidence_by_handle = {str(item.get("handle")): item for item in packet.get("matches") or [] if isinstance(item, dict)}
    route_ok = packet.get("route_id") and packet.get("route_id") == completion_packet.get("route_id") == state.get("route_id", packet.get("route_id"))
    if not route_ok: errors.append({"code": "route_scope_incompatible", "message": "State, evidence, and completion routes must agree."})
    root = Path(str(packet.get("workspace_scope") or "")).resolve()
    for claim in completion_packet.get("claims") or []:
        handles = {str(item) for item in claim.get("evidence_handles") or []}
        if not handles: continue
        if not handles.issubset(evidence_by_handle): errors.append({"code": "claim_evidence_missing", "message": str(claim.get("id") or "")})
        if not handles.issubset(visible_handles): errors.append({"code": "claim_evidence_unavailable_to_model", "message": str(claim.get("id") or "")})
        if claim.get("proof_level") not in completion.ALLOWED_SLICE_LEVELS:
            errors.append({"code": "proof_level_out_of_scope", "message": str(claim.get("proof_level") or "")})
        locations = claim.get("locations") or []
        for location in locations:
            path = (root / str(location.get("file") or "")).resolve() if isinstance(location, dict) else root
            line = _line_number(location.get("line")) if isinstance(location, dict) else 0
            cited_locations = {(str(evidence_by_handle[handle].get("file") or ""), _line_number(evidence_by_handle[handle].get("line"))) for handle in handles if handle in evidence_by_handle}
            valid_path = root == path or root in path.parents
            try: line_count = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError: line_count = 0
            if not valid_path or not path.is_file() or line < 1 or line > line_count or (str(location.get("file") or ""), line) not in cited_locations:
                errors.append({"code": "source_location_invalid", "message": str(location)})
        requires_semantic = claim.get("status") == "inferred" or bool(claim.get("consequential") or claim.get("contradictory") or claim.get("weak_coverage"))
        if requires_semantic:
            if semantic_verify is None:
                errors.append({"code": "semantic_verifier_unavailable", "message": str(claim.get("id") or "")})
            else:
                cited = [evidence_by_handle[handle] for handle in sorted(handles) if handle in evidence_by_handle]
                verdict = semantic_verify(claim, cited)
                if verdict != "supported": errors.append({"code": "semantic_claim_" + str(verdict), "message": str(claim.get("id") or "")})
    terminal = completion_packet.get("terminal_answerability")
    if terminal != state.get("answerability"): errors.append({"code": "terminal_status_inconsistent", "message": "State and completion terminal status differ."})
    if terminal == "not_found_with_coverage":
        if packet.get("matches") or not _negative_coverage(packet): errors.append({"code": "negative_coverage_incomplete", "message": "Negative conclusion lacks complete tool-reported coverage."})
    if state.get("contradictions") and not completion_packet.get("unresolved_contradictions"):
        errors.append({"code": "contradiction_undisclosed", "message": "Unresolved contradictions must be disclosed."})
    return {"schema": "GATE-V4/1", "ok": not errors, "decision": "accepted" if not errors else "rejected", "errors": errors, "semantic_verifier_required": any(claim.get("status") == "inferred" or claim.get("consequential") or claim.get("contradictory") or claim.get("weak_coverage") for claim in completion_packet.get("claims") or [])}
