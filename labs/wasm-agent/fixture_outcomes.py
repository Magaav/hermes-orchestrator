"""Stable satisfaction outcomes for safe-lab fixture runs.

The harness reports observations; it does not fail merely because a candidate
answer, provider, or lane is unsatisfactory. Promotion remains fail-closed.
"""

from __future__ import annotations

from typing import Any


def fixture_outcome(
    errors: list[str],
    benchmark_errors: list[str],
    semantic_score: dict[str, Any],
    lane: dict[str, Any],
    ranking_allowed: bool,
) -> dict[str, Any]:
    execution_ready = not errors
    candidate_answer_available = lane.get("readinessCandidatePassed") is True
    evaluation_available = candidate_answer_available and semantic_score.get("passed") in {True, False}
    semantic_passed = semantic_score.get("passed") is True if evaluation_available else candidate_answer_available
    satisfactory = execution_ready and not benchmark_errors and semantic_passed and ranking_allowed
    blockers = [*errors, *benchmark_errors]
    return {
        "ok": True,
        "harnessStatus": "completed",
        "classification": (
            "live_fixture_answer_satisfactory" if satisfactory else "live_fixture_answer_unsatisfactory"
        ),
        "answerSatisfaction": "satisfactory" if satisfactory else "unsatisfactory",
        "executionStatus": "ready" if execution_ready else "unavailable",
        "evaluationStatus": "evaluated" if evaluation_available else "unavailable",
        "candidateAnswerAvailable": candidate_answer_available,
        "promotionEligible": satisfactory,
        "improvementRequired": not satisfactory,
        "blockers": blockers,
    }


def lane_outcome(candidate_answer_available: bool) -> dict[str, Any]:
    """Describe candidate readiness without turning it into lane failure."""

    return {
        "status": "completed",
        "reason": (
            "live fixture answer satisfactory candidate produced"
            if candidate_answer_available
            else "live fixture answer unsatisfactory; improvement required"
        ),
        "answerSatisfaction": "satisfactory" if candidate_answer_available else "unsatisfactory",
        "executionStatus": "ready" if candidate_answer_available else "unavailable",
        "improvementRequired": not candidate_answer_available,
    }


def suite_outcome(results: list[dict[str, Any]]) -> dict[str, Any]:
    unsatisfactory = [row for row in results if row.get("answerSatisfaction") != "satisfactory"]
    promotion_eligible = bool(results) and not unsatisfactory and all(
        row.get("promotionEligible") is True for row in results
    )
    return {
        "ok": True,
        "harnessStatus": "completed",
        "classification": (
            "promoted_v5_suite_satisfactory" if promotion_eligible else "promoted_v5_suite_unsatisfactory"
        ),
        "suiteSatisfaction": "satisfactory" if promotion_eligible else "unsatisfactory",
        "promotionEligible": promotion_eligible,
        "improvementRequired": not promotion_eligible,
        "unsatisfactoryFixtureIds": [str(row.get("fixtureId") or "") for row in unsatisfactory],
    }
