"""Pure Loop 4/5 candidate outcome and ranking policy.

Candidate regressions are typed per digest.  A failed candidate is evidence to
retain and disqualify, not a reason to discard the other candidate outcomes.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


EXPECTED_SLOTS = frozenset(f"harness-{index:02d}" for index in range(1, 10))

DEFAULT_COMPLEXITY = {
    "minimal_class_allowlist": 1,
    "deny_first_class_policy": 2,
    "explicit_completion_mode": 3,
    "proof_policy_gate": 3,
    "capability_requirement_gate": 4,
    "evidence_requirement_gate": 4,
    "route_owned_execution_profile": 5,
    "structured_policy_decision": 5,
    "single_context_profile_constructor": 6,
}


def _copied_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            copied.append({
                "slot": f"invalid-{index + 1}",
                "loop4Passed": None,
                "errors": ["candidate outcome must be an object"],
            })
            continue
        raw_errors = row.get("errors") or []
        errors = list(raw_errors) if isinstance(raw_errors, list) else [str(raw_errors)]
        copied.append({**row, "errors": errors})
    return copied


def summarize_matrix(
    rows: Iterable[dict[str, Any]], *, global_errors: Iterable[str] = ()
) -> dict[str, Any]:
    """Validate a nine-outcome matrix without promoting candidate failures.

    ``ok`` means the matrix itself is complete and internally valid.  Promotion
    eligibility is reported separately and requires at least one passing exact
    digest.  Every failed row remains in ``rows`` with its typed errors.
    """

    outcomes = _copied_rows(rows)
    errors = [str(error) for error in global_errors if str(error).strip()]
    slots = [str(row.get("slot") or "") for row in outcomes]
    digests = [str(row.get("candidateDigest") or "") for row in outcomes]

    if len(outcomes) != 9:
        errors.append("nine typed candidate outcomes required")
    if set(slots) != EXPECTED_SLOTS or len(slots) != len(set(slots)):
        errors.append("candidate slots must be the nine unique harness slots")
    if (
        any(not re.fullmatch(r"[a-f0-9]{64}", digest) for digest in digests)
        or len(digests) != len(set(digests))
    ):
        errors.append("candidate digests must be canonical and unique")

    for row in outcomes:
        slot = str(row.get("slot") or "candidate")
        passed = row.get("loop4Passed")
        row_errors = row.get("errors") or []
        if not isinstance(passed, bool):
            errors.append(f"{slot}: loop4Passed must be boolean")
        elif passed and row_errors:
            errors.append(f"{slot}: passing candidate contains regression errors")
        elif not passed and not row_errors:
            errors.append(f"{slot}: failed candidate lacks a typed regression reason")

    matrix_valid = not errors
    passing_count = sum(row.get("loop4Passed") is True for row in outcomes)
    failed_count = len(outcomes) - passing_count
    promotion_eligible = matrix_valid and passing_count > 0
    if not matrix_valid:
        classification = "loop4_matrix_invalid"
        terminal = "matrix_invalid"
    elif promotion_eligible:
        classification = "loop4_matrix_complete"
        terminal = "passing_candidates_available"
    else:
        classification = "loop4_matrix_complete"
        terminal = "no_passing_candidates"

    return {
        "ok": matrix_valid,
        "classification": classification,
        "terminalOutcome": terminal,
        "rows": outcomes,
        "passingCount": passing_count,
        "failedCount": failed_count,
        "promotionEligible": promotion_eligible,
        "errors": errors,
    }


def _complexity(row: dict[str, Any], complexity: dict[str, int]) -> int:
    declared = row.get("policyComplexity")
    if isinstance(declared, int) and declared > 0:
        return declared
    strategy = str(row.get("strategy") or "")
    if strategy not in complexity:
        raise ValueError(f"passing candidate has no declared complexity: {strategy or 'unknown'}")
    return int(complexity[strategy])


def rank_passing_candidates(
    proof: dict[str, Any], *, complexity: dict[str, int] | None = None
) -> dict[str, Any]:
    """Rank only exact-digest Loop 4 passes while retaining all outcomes."""

    if proof.get("ok") is not True:
        raise ValueError("cannot rank an invalid Loop 4 matrix")
    if proof.get("errors"):
        raise ValueError("cannot rank a Loop 4 matrix with global errors")
    outcomes = _copied_rows(proof.get("rows") or [])
    validation = summarize_matrix(outcomes)
    if validation["ok"] is not True:
        raise ValueError("; ".join(validation["errors"]))
    for field in ("passingCount", "failedCount", "promotionEligible"):
        if field in proof and proof.get(field) != validation[field]:
            raise ValueError(f"Loop 4 matrix summary mismatch: {field}")

    complexity_map = complexity if complexity is not None else DEFAULT_COMPLEXITY
    passing: list[dict[str, Any]] = []
    disqualified: list[dict[str, Any]] = []
    for row in outcomes:
        if row.get("loop4Passed") is True:
            candidate = dict(row)
            candidate["policyComplexity"] = _complexity(candidate, complexity_map)
            passing.append(candidate)
        else:
            candidate = dict(row)
            candidate["disqualification"] = "loop4_regression_failed"
            disqualified.append(candidate)

    passing.sort(
        key=lambda row: (
            row["policyComplexity"],
            int(row.get("promptTokens") or 0),
            int(row.get("providerCalls") or 0),
            int(row.get("toolCalls") or 0),
            int(row.get("latencyMs") or 0),
            str(row.get("candidateDigest") or ""),
        )
    )
    for rank, row in enumerate(passing, 1):
        row["rank"] = rank

    winner = passing[0] if passing else None
    if winner:
        terminal = "promoted_candidate_selected"
        decision = "eligible_for_reviewed_registry_promotion"
        reason = (
            "Regression-passing variants were ranked independently; the smallest "
            "compatible generic policy is eligible for reviewed promotion."
        )
    else:
        terminal = "rejected_no_passing_candidate"
        decision = "no_regression_passing_candidate"
        reason = "All nine typed candidate outcomes failed their exact-digest Loop 4 gate."

    return {
        "schema": "wasm-agent.safe-lab.loop5-promotion-decision.v1",
        "ok": True,
        "terminalOutcome": terminal,
        "winningVariant": winner,
        "ranking": passing,
        "candidateOutcomes": outcomes,
        "disqualifiedVariants": disqualified,
        "passingCount": len(passing),
        "disqualifiedCount": len(disqualified),
        "decision": decision,
        "reason": reason,
        "activeRegistryMutated": False,
    }
