"""Claim-bound V6 finalization over route evidence and operation receipts."""
from __future__ import annotations

from typing import Any

from . import contracts


SCHEMA = "master.frontier.v6.final_claims.v1"
SCOPES = frozenset({"conceptual", "route", "source", "runtime", "action", "verification", "external"})
FLOOR_SCOPES = {
    "conceptual": SCOPES,
    "route": frozenset({"route", "source", "runtime", "action", "verification", "external"}),
    "source": frozenset({"source", "verification"}),
    "runtime": frozenset({"runtime", "action", "verification"}),
    "proof": frozenset({"action", "verification"}),
}
RUNTIME_AUTHORITIES = frozenset({
    "runtime.inspect", "browser.inspect", "browser.control",
    "client.ui.inspect", "client.ui.control",
})


class ClaimError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def parse(text: str) -> dict[str, Any]:
    """Parse one strict, bounded provider-authored finalization contract."""
    try:
        value = contracts.decode(str(text or ""), max_bytes=32_768)
    except contracts.ContractError as exc:
        raise ClaimError("final_claim_json_invalid") from exc
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ClaimError("final_claim_schema_invalid")
    answer = " ".join(str(value.get("answer") or "").replace("\x00", "").split())[:12_000]
    raw_claims = value.get("claims")
    if not answer:
        raise ClaimError("final_claim_answer_missing")
    if not isinstance(raw_claims, list) or not raw_claims or len(raw_claims) > 16:
        raise ClaimError("final_claims_missing")
    claims = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_claims, 1):
        if not isinstance(raw, dict):
            raise ClaimError("final_claim_invalid")
        claim_id = str(raw.get("id") or f"c{index}").strip()[:80]
        scope = str(raw.get("scope") or "").strip().lower()
        statement = " ".join(str(raw.get("statement") or "").replace("\x00", "").split())[:600]
        if not claim_id or claim_id in seen or scope not in SCOPES or not statement:
            raise ClaimError("final_claim_invalid")
        seen.add(claim_id)
        claims.append({
            "id": claim_id,
            "scope": scope,
            "statement": statement,
            "operations": list(dict.fromkeys(
                str(item).strip()[:160] for item in (raw.get("operations") or [])[:8]
                if str(item).strip()
            )),
            "evidence": list(dict.fromkeys(
                str(item).strip()[:160] for item in (raw.get("evidence") or [])[:8]
                if str(item).strip()
            )),
            "proof": list(dict.fromkeys(
                str(item).strip()[:240] for item in (raw.get("proof") or [])[:16]
                if str(item).strip()
            )),
        })
    return {"schema": SCHEMA, "answer": answer, "claims": claims}


def _compatible(scope: str, capability: dict[str, Any]) -> bool:
    kind = str(capability.get("kind") or "")
    mode = str(capability.get("mode") or "")
    authority = str(capability.get("authority") or "")
    if scope == "source":
        return authority == "repo.read" and mode == "read"
    if scope == "runtime":
        return kind in {"observe", "verify"} and authority in RUNTIME_AUTHORITIES
    if scope == "action":
        return kind == "act" and mode == "write"
    if scope == "verification":
        return kind in {"observe", "act", "verify"}
    if scope == "external":
        return kind == "observe" and authority.startswith("mcp.")
    return False


def gaps(
    final: dict[str, Any], kernel: Any, *, viewed_operations: set[str], evidence_floor: str,
) -> list[str]:
    """Return exact unsupported-claim gaps without interpreting prompt strings."""
    journal = {
        str((item.get("operation") or {}).get("id") or ""): item
        for item in kernel.journal()
        if str((item.get("operation") or {}).get("id") or "")
    }
    evidence = {
        str(item.get("id") or ""): item
        for item in kernel.evidence.list(limit=256)
        if str(item.get("id") or "")
    }
    floor = str(evidence_floor or "route").strip().lower()
    allowed_scopes = FLOOR_SCOPES.get(floor, FLOOR_SCOPES["route"])
    result: list[str] = []
    claims = final.get("claims") if isinstance(final.get("claims"), list) else []
    if not any(isinstance(item, dict) and str(item.get("scope") or "") in allowed_scopes for item in claims):
        result.append(f"claim:floor:{floor}")
    for claim in claims:
        claim_id = str(claim.get("id") or "claim")
        scope = str(claim.get("scope") or "")
        if scope not in allowed_scopes:
            result.append(f"claim:{claim_id}:scope:{scope}")
            continue
        if scope == "conceptual":
            if floor != "conceptual":
                result.append(f"claim:{claim_id}:conceptual_not_allowed")
            continue
        if scope == "route":
            cited = [evidence.get(str(item)) for item in (claim.get("evidence") or [])]
            if not any(isinstance(item, dict) and item.get("kind") == "route.contract" for item in cited):
                result.append(f"claim:{claim_id}:route_evidence")
            continue
        operation_ids = [str(item) for item in (claim.get("operations") or [])]
        entries = [journal.get(item) for item in operation_ids]
        if not operation_ids or any(not isinstance(item, dict) for item in entries):
            result.append(f"claim:{claim_id}:operation")
            continue
        valid_entries = []
        for entry in entries:
            receipt = entry.get("receipt") if isinstance(entry.get("receipt"), dict) else {}
            capability = kernel.catalog.get(str(entry.get("capability") or "")) or {}
            if (
                receipt.get("ok") is True
                and receipt.get("state") in {"acknowledged", "completed"}
                and _compatible(scope, capability)
            ):
                valid_entries.append((entry, receipt, capability))
        if not valid_entries:
            result.append(f"claim:{claim_id}:support")
            continue
        if scope in {"source", "runtime", "external"} and not any(
            str((entry.get("operation") or {}).get("id") or "") in viewed_operations
            for entry, _receipt, _capability in valid_entries
        ):
            result.append(f"claim:{claim_id}:unviewed")
        actual_proof = {
            str(item)
            for _entry, receipt, _capability in valid_entries
            for item in (receipt.get("proof") or [])
        }
        declared_proof = {
            str(item)
            for _entry, _receipt, capability in valid_entries
            for item in [*(capability.get("proof") or []), *(capability.get("completion_proof") or [])]
        }
        requested_proof = {str(item) for item in (claim.get("proof") or [])}
        if requested_proof and not requested_proof.issubset(actual_proof & declared_proof):
            result.extend(f"claim:{claim_id}:proof:{item}" for item in sorted(requested_proof - (actual_proof & declared_proof)))
        elif scope in {"runtime", "verification"} and not (actual_proof & declared_proof):
            result.append(f"claim:{claim_id}:{scope}_proof")
    return list(dict.fromkeys(result))
