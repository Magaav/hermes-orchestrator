from __future__ import annotations

import json
from typing import Any


SCHEMA = "COMPLETION/1"
PROOF_LEVELS = {"source_presence", "inferred_purpose", "runtime_existence", "deployed_behavior", "build_proof", "installed_app_proof", "production_proof"}
ALLOWED_SLICE_LEVELS = {"source_presence", "inferred_purpose"}


class CompletionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message); self.code = code


def validate(packet: dict[str, Any], *, max_bytes: int = 24_000) -> dict[str, Any]:
    if not isinstance(packet, dict) or packet.get("schema") != SCHEMA:
        raise CompletionError("completion_schema_invalid", "Completion must use COMPLETION/1.")
    if not isinstance(packet.get("claims"), list) or not str(packet.get("answer") or ""):
        raise CompletionError("completion_fields_missing", "Claims and answer are required.")
    for key in ("unresolved_contradictions", "ambiguity", "coverage_limitations", "disclaimers"):
        if not isinstance(packet.get(key), list): raise CompletionError("completion_field_invalid", f"{key} must be a list.")
    if packet.get("terminal_answerability") not in {"supported", "ambiguous", "not_found_with_coverage", "capability_blocked", "scope_unresolved"}:
        raise CompletionError("completion_terminal_invalid", "Completion requires a terminal answerability status.")
    confidence = packet.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise CompletionError("completion_confidence_invalid", "Confidence must be between zero and one.")
    ids: set[str] = set()
    for claim in packet["claims"]:
        if not isinstance(claim, dict) or not str(claim.get("id") or "") or not str(claim.get("text") or ""):
            raise CompletionError("claim_invalid", "Claims require id and atomic text.")
        if claim["id"] in ids: raise CompletionError("claim_duplicate", "Claim ids must be unique.")
        ids.add(claim["id"])
        if claim.get("status") not in {"direct", "inferred"}: raise CompletionError("claim_status_invalid", "Claim status must be direct or inferred.")
        if claim.get("proof_level") not in PROOF_LEVELS: raise CompletionError("claim_proof_level_invalid", "Claim proof level is invalid.")
        if not isinstance(claim.get("evidence_handles"), list) or not claim["evidence_handles"]:
            raise CompletionError("claim_citation_missing", "Every factual claim requires evidence handles.")
        if not isinstance(claim.get("locations"), list): raise CompletionError("claim_location_invalid", "Claim locations must be a list.")
    if len(json.dumps(packet, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()) > max_bytes:
        raise CompletionError("completion_byte_limit", "Completion exceeds its byte bound.")
    return packet


def source_disclaimers() -> list[str]:
    return ["This read-only slice proves source-level claims only; it does not prove runtime existence, deployed behavior, a build, an installed app, or production behavior."]
