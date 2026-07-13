#!/usr/bin/env python3
"""Validate the bounded five-loop self-improvement contract."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "docs/context/HARNESS_LOOPS.json"
REPORT_PATH = ROOT / "reports/context/latest/harness-loops-result.json"
LOOP_IDS = ["human-agent-operation", "candidate-adjudication", "parallel-harness-benchmark", "regression-protection", "bounded-improvement"]
FINAL_OUTCOMES = {"promoted", "rejected", "reclassified", "deferred", "unresolved_bounded", "saturated", "needs_human_decision"}
REPEAT_REASONS = {"new_evidence", "materially_different_hypothesis", "measurable_improvement"}


def nonempty_strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item.strip() for item in value)


def validate_loop(loop: Any, ordinal: int, errors: list[str]) -> None:
    prefix = f"loops[{ordinal - 1}]"
    if not isinstance(loop, dict):
        errors.append(f"{prefix} must be an object")
        return
    if loop.get("id") != LOOP_IDS[ordinal - 1] or loop.get("ordinal") != ordinal:
        errors.append(f"{prefix} must be canonical loop {ordinal}: {LOOP_IDS[ordinal - 1]}")
    for field in ("states", "rules", "terminalOutcomes", "outputs"):
        if not nonempty_strings(loop.get(field)):
            errors.append(f"{prefix}.{field} must be a non-empty string list")
    states = set(loop.get("states") or [])
    if loop.get("initialState") not in states:
        errors.append(f"{prefix}.initialState must name a declared state")
    reached = {loop.get("initialState")}
    transitions = loop.get("transitions")
    if not isinstance(transitions, list) or not transitions:
        errors.append(f"{prefix}.transitions must be non-empty")
    else:
        for index, transition in enumerate(transitions):
            if not isinstance(transition, dict):
                errors.append(f"{prefix}.transitions[{index}] must be an object")
                continue
            source, target = transition.get("from"), transition.get("to")
            if source not in states or target not in states:
                errors.append(f"{prefix}.transitions[{index}] references an unknown state")
            if source not in reached:
                errors.append(f"{prefix}.transitions[{index}] source is unreachable")
            reached.add(target)
        if states - reached:
            errors.append(f"{prefix} contains unreachable states: {sorted(states - reached)}")
    budgets = loop.get("budgets")
    if not isinstance(budgets, dict) or not budgets:
        errors.append(f"{prefix}.budgets must be non-empty")


def validate(contract: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(contract, dict):
        return ["contract root must be an object"]
    if contract.get("schema") != "wasm-agent.harness.five-loop-contract.v2" or contract.get("version") != 2:
        errors.append("schema/version must identify five-loop-contract.v2")
    required_banks = {"candidate", "classifierDispute", "golden", "regression", "insight"}
    if set(contract.get("banks") or {}) != required_banks:
        errors.append("banks must define candidate, classifierDispute, golden, regression, and insight exactly")
    shared = contract.get("sharedRequirements")
    if not isinstance(shared, dict) or not all(shared.get(key) is True for key in ("redaction", "boundedTrajectoryWindow", "immutableReplayInput", "provenance")):
        errors.append("shared requirements must enforce redaction, bounds, immutable replay, and provenance")
    if not isinstance(shared, dict) or set(shared.get("repeatRequiresAny") or []) != REPEAT_REASONS:
        errors.append("repeatRequiresAny must contain the three canonical progress reasons")
    loops = contract.get("loops")
    if not isinstance(loops, list) or len(loops) != 5:
        errors.append("contract must contain exactly five loops")
        loops = loops if isinstance(loops, list) else []
    for ordinal, loop in enumerate(loops, 1):
        validate_loop(loop, ordinal, errors)
    matrix = contract.get("benchmarkMatrix")
    slots = matrix.get("harnessSlots") if isinstance(matrix, dict) else []
    if not isinstance(matrix, dict) or matrix.get("model") != "frank/GLM-5.2" or matrix.get("harnessCount") != 9 or matrix.get("parallel") is not True:
        errors.append("benchmarkMatrix must declare nine parallel harnesses using frank/GLM-5.2")
    if not isinstance(slots, list) or len(slots) != 9 or len(set(slots)) != 9:
        errors.append("benchmarkMatrix must contain nine unique harness slots")
    comparability = matrix.get("comparabilityRequires") if isinstance(matrix, dict) else []
    if not nonempty_strings(comparability) or len(comparability) < 6:
        errors.append("benchmarkMatrix must declare bounded comparability proof")

    improvement_matrix = contract.get("improvementMatrix")
    variant_slots = improvement_matrix.get("variantSlots") if isinstance(improvement_matrix, dict) else []
    if not isinstance(improvement_matrix, dict) or improvement_matrix.get("model") != "frank/GLM-5.2" or improvement_matrix.get("variantCount") != 9 or improvement_matrix.get("parallel") is not True:
        errors.append("improvementMatrix must declare nine parallel V5 variants using frank/GLM-5.2")
    if not isinstance(variant_slots, list) or len(variant_slots) != 9 or len(set(variant_slots)) != 9:
        errors.append("improvementMatrix must contain nine unique V5 variant slots")
    diversity = improvement_matrix.get("diversityRequires") if isinstance(improvement_matrix, dict) else []
    if not nonempty_strings(diversity) or len(diversity) < 6:
        errors.append("improvementMatrix must require independent strategy and workspace diversity")
    if "Every variant" not in str((improvement_matrix or {}).get("regressionRule") or ""):
        errors.append("improvementMatrix must require independent regression proof for every variant")

    benchmark = loops[2] if len(loops) == 5 and isinstance(loops[2], dict) else {}
    if int((benchmark.get("budgets") or {}).get("maxParallelHarnesses") or 0) != 9:
        errors.append("loop three must run at most and exactly nine declared parallel harness slots")
    regression = loops[3] if len(loops) == 5 and isinstance(loops[3], dict) else {}
    regression_rules = " ".join(regression.get("rules") or [])
    safety_regressions = (regression.get("budgets") or {}).get("maxSafetyRegressionCount")
    if "exact candidate digest" not in regression_rules or safety_regressions != 0:
        errors.append("loop four must bind regression proof to the exact candidate digest and allow zero safety regressions")
    improvement = loops[4] if len(loops) == 5 and isinstance(loops[4], dict) else {}
    if set(improvement.get("terminalOutcomes") or []) != FINAL_OUTCOMES:
        errors.append("loop five must declare all canonical terminal outcomes")
    budgets = improvement.get("budgets") if isinstance(improvement, dict) else {}
    required_bounds = ("requiresExplicitTokenBudget", "requiresExplicitWallClockBudget", "requiresMinimumMeaningfulImprovement")
    if not isinstance(budgets, dict) or not all(budgets.get(key) is True for key in required_bounds) or int(budgets.get("noProgressPatienceRounds") or 0) < 1:
        errors.append("loop five must require explicit resource/improvement bounds and positive no-progress patience")
    improvement_rules = " ".join(improvement.get("rules") or [])
    if "Loop 4 proof" not in improvement_rules:
        errors.append("loop five must require a passing loop four regression proof")
    improvement_budgets = improvement.get("budgets") if isinstance(improvement, dict) else {}
    if not isinstance(improvement_budgets, dict) or improvement_budgets.get("variantsPerRound") != 9 or improvement_budgets.get("maxParallelVariants") != 9:
        errors.append("loop five must generate exactly nine parallel variants per round")
    if "per_variant_regression_proof_refs" not in (improvement.get("outputs") or []):
        errors.append("loop five must expose independent per-variant regression proof references")
    transitions = contract.get("crossLoopTransitions")
    if not isinstance(transitions, list) or len(transitions) < 9:
        errors.append("cross-loop transitions must include benchmark, regression, improvement, reclassification, and evidence-return paths")
    return errors


def main() -> int:
    try:
        errors = validate(json.loads(CONTRACT_PATH.read_text(encoding="utf-8")))
    except Exception as exc:  # noqa: BLE001
        errors = [f"failed to read contract: {exc}"]
    report = {
        "ok": not errors,
        "classification": "harness_loops_pass" if not errors else "harness_loops_invalid",
        "checkedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "contractPath": str(CONTRACT_PATH.relative_to(ROOT)),
        "errors": errors,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Harness loops: {'PASS' if report['ok'] else 'FAIL'} ({report['classification']})")
    print(f"Report JSON: {REPORT_PATH.relative_to(ROOT)}")
    for error in errors:
        print(f"- {error}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
