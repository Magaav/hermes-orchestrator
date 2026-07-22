#!/usr/bin/env python3
"""Build the public redacted twelve-case session fixture suite."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from session_fixture_contract import canonical_digest, task_projection

LAB = Path(__file__).resolve().parent

CASES = [
    ("adjacent_followup", "Review the parser.", "Can you expand the second concern?", [], "resolve_recent_antecedent"),
    ("process_restart", "Diagnose the failing cache test.", "Continue with the fix.", ["restart"], "retain_objective_after_restart"),
    ("context_compaction", "Refactor the bounded reader and preserve its API.", "Now update its tests.", ["compact"], "retain_objective_after_compaction"),
    ("older_recall", "Remember the rollback handle named checkpoint-alpha.", "What rollback handle did we establish?", ["checkpoint"], "exact_older_recall"),
    ("interruption_resume", "Implement the scoped validation change.", "Continue.", ["tool_call", "interrupt"], "resume_without_repeating_side_effect"),
    ("new_topic", "Explain the route contract.", "Unrelated: write a haiku about rain.", [], "do_not_inherit_stale_task"),
    ("user_correction", "Rename the public method to parseFast.", "Correction: keep the method name and only optimize its body.", [], "latest_user_instruction_wins"),
    ("fix_all", "Criticize the meta-analysis widget.", "Can you fix them all?", ["tool_call", "tool_result"], "transition_diagnosis_to_implementation"),
    ("fix_second", "Identify three defects in the fixture module.", "Only fix the second one.", [], "select_referenced_subset"),
    ("continue_interrupted", "Add the feature and focused tests.", "Continue.", ["tool_call", "tool_result", "interrupt", "restart"], "resume_interrupted_implementation"),
    ("no_repeat", "Create the migration file.", "Now add the focused test.", ["tool_call", "tool_result", "checkpoint"], "honor_completed_action_receipt"),
    ("ambiguous_recall", "Compare the two candidate modules.", "Fix that one.", ["compact"], "bounded_recall_before_action"),
]

PRIOR_ANSWERS = {
    "adjacent_followup": "Concern one is ambiguous ownership. Concern two is that error offsets drift after normalization.",
    "process_restart": "The cache test fails because the persisted generation is read before invalidation; the fix belongs in the cache owner.",
    "context_compaction": "The bounded reader API is read_lines(path, start, end); preserve those arguments while moving byte accounting into the owner.",
    "older_recall": "The established rollback handle is checkpoint-alpha.",
    "interruption_resume": "The scoped validation mutation is action-mutation-01; its outcome must be reconciled before any repeat.",
    "new_topic": "A route contract binds a surface to an owner, roots, capabilities, checks, budget, and proof policy.",
    "user_correction": "The requested public rename is parseFast, pending confirmation before mutation.",
    "fix_all": "Three widget defects: stale derived state, duplicate resize listeners, and an unbounded evidence render.",
    "fix_second": "Defect one is a leaked handle. Defect two is non-atomic rollback. Defect three is an uncapped output buffer.",
    "continue_interrupted": "Feature mutation action-mutation-01 completed; focused tests remain pending after interruption.",
    "no_repeat": "Migration action-mutation-01 completed with receipt receipt-01; only the focused test remains.",
    "ambiguous_recall": "Candidate parser-alpha owns decoding; parser-beta owns validation. No candidate has yet been selected.",
}

SIDE_EFFECT_CASES = {"interruption_resume", "continue_interrupted", "no_repeat"}


def fixture(case: str, first: str, second: str, middle: list[str], terminal: str) -> dict:
    events: list[dict] = [{"seq": 1, "kind": "user", "turnRef": "turn-01", "content": first}]
    events.append({"seq": 2, "kind": "assistant", "turnRef": "turn-01", "content": PRIOR_ANSWERS[case], "receiptRefs": []})
    for kind in middle:
        event = {"seq": len(events) + 1, "kind": kind, "turnRef": "turn-01"}
        action_ref = "action-mutation-01" if case in SIDE_EFFECT_CASES else "action-inspect-01"
        if kind == "tool_call": event.update({"actionRef": action_ref, "tool": "kernel.act" if case in SIDE_EFFECT_CASES else "kernel.inspect", "argumentsDigest": "sha256:fixture-arguments"})
        if kind == "tool_result": event.update({"actionRef": action_ref, "status": "completed", "receiptRef": "receipt-01", "resultDigest": "sha256:fixture-result"})
        if kind == "checkpoint": event.update({"checkpointRef": "checkpoint-alpha", "completedActionRefs": [action_ref]})
        if kind == "interrupt": event.update({"reasonClass": "fixture_forced_interrupt", "resumable": True})
        if kind == "restart": event.update({"fromProcessRef": "process-01", "toProcessRef": "process-02"})
        if kind == "compact": event.update({"exactTailTurns": 1, "olderContextRef": "context-capsule-01"})
        events.append(event)
    events.append({"seq": len(events) + 1, "kind": "user", "turnRef": "turn-02", "content": second})
    item = {
        "id": f"session-{case.replace('_', '-')}-v1",
        "case": case,
        "origin": "redacted_observed_failure" if case == "fix_all" else "generic_contract_fixture",
        "session": {"sessionRef": f"session-ref-{case}", "initialProcessRef": "process-01", "branchRef": "main", "accountRef": "account-fixture", "routeRef": "wasm-agent.avatar-chat.ui"},
        "events": events,
        "expectations": {
            "perTurn": [
                {"turnRef": "turn-01", "taskClass": "diagnosis" if case == "fix_all" else "fixture_initial", "mustPreserveCapabilities": True},
                {"turnRef": "turn-02", "taskClass": "implementation" if case in {"fix_all", "fix_second", "continue_interrupted", "process_restart", "context_compaction", "user_correction", "no_repeat"} else "fixture_followup", "mustResolveHistory": case != "new_topic", "mustNotRepeatCompletedActions": case in {"interruption_resume", "continue_interrupted", "no_repeat"}},
            ],
            "terminal": terminal,
            "requiredProof": ["session_identity", "turn_identity", "provider_ledger", "tool_ledger", "terminal_status"],
        },
        "taskDigest": "",
    }
    return item


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output", required=True); args = parser.parse_args()
    route_path = LAB / "session-route-contract.json"
    tool_path = LAB / "tool-authority-contract.json"
    suite = {
        "schema": "wasm-agent.safe-lab.session-fixture-suite.v1",
        "model": "frank/GLM-5.2",
        "routeContractSha256": hashlib.sha256(route_path.read_bytes()).hexdigest(),
        "toolAuthoritySha256": hashlib.sha256(tool_path.read_bytes()).hexdigest(),
        "privateHoldoutExpectationsExposed": False,
        "budgets": {"providerCallsPerTurn": 6, "toolCallsPerTurn": 8, "wallClockSecondsPerTask": 300, "maxContextBytes": 32768},
        "fixtures": [fixture(*case) for case in CASES],
    }
    for item in suite["fixtures"]: item["taskDigest"] = canonical_digest(task_projection(item, suite))
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(suite, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "suiteSha256": canonical_digest(suite), "fixtures": len(suite["fixtures"])}, separators=(",", ":")))
    return 0


if __name__ == "__main__": raise SystemExit(main())
