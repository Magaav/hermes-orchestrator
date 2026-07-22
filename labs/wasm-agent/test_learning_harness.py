#!/usr/bin/env python3
"""Deterministic tests for candidate selection and learning trajectories."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from agent_trajectory import FIELD_DICTIONARY, KIND_CODES, MAX_EVENTS, STATUS_CODES, build_trajectory, write_trajectory
from loop5_candidate_policy import rank_passing_candidates, summarize_matrix


STRATEGIES = [
    "minimal_class_allowlist",
    "deny_first_class_policy",
    "explicit_completion_mode",
    "proof_policy_gate",
    "capability_requirement_gate",
    "evidence_requirement_gate",
    "route_owned_execution_profile",
    "structured_policy_decision",
    "single_context_profile_constructor",
]


def candidate_rows(failed: set[int] | None = None) -> list[dict]:
    failed = failed or set()
    rows = []
    for index, strategy in enumerate(STRATEGIES, 1):
        passed = index not in failed
        rows.append({
            "slot": f"harness-{index:02d}",
            "variantSlot": f"v5-variant-{index:02d}",
            "strategy": strategy,
            "candidateDigest": f"{index:064x}",
            "loop4Passed": passed,
            "semanticPassed": passed,
            "providerCalls": 1,
            "toolCalls": 0,
            "promptTokens": 200 + index,
            "completionTokens": 20,
            "latencyMs": 1000 + index,
            "errors": [] if passed else ["semantic_regression"],
        })
    return rows


class CandidatePolicyTests(unittest.TestCase):
    def test_mixed_matrix_preserves_nine_typed_outcomes(self) -> None:
        summary = summarize_matrix(candidate_rows({1, 5, 9}))
        self.assertTrue(summary["ok"])
        self.assertTrue(summary["promotionEligible"])
        self.assertEqual(summary["passingCount"], 6)
        self.assertEqual(summary["failedCount"], 3)
        self.assertEqual(len(summary["rows"]), 9)
        self.assertEqual(summary["rows"][0]["errors"], ["semantic_regression"])

    def test_ranker_excludes_failed_variant_without_blocking_winner(self) -> None:
        rows = candidate_rows({1, 8})
        result = rank_passing_candidates({"ok": True, "rows": rows})
        self.assertEqual(result["passingCount"], 7)
        self.assertEqual(result["disqualifiedCount"], 2)
        self.assertEqual(result["winningVariant"]["slot"], "harness-02")
        self.assertNotIn("harness-01", {row["slot"] for row in result["ranking"]})
        self.assertEqual({row["slot"] for row in result["disqualifiedVariants"]}, {"harness-01", "harness-08"})
        self.assertEqual(len(result["candidateOutcomes"]), 9)

    def test_all_failed_is_a_typed_rejection(self) -> None:
        rows = candidate_rows(set(range(1, 10)))
        summary = summarize_matrix(rows)
        self.assertTrue(summary["ok"])
        self.assertFalse(summary["promotionEligible"])
        result = rank_passing_candidates({"ok": True, "rows": rows})
        self.assertEqual(result["terminalOutcome"], "rejected_no_passing_candidate")
        self.assertIsNone(result["winningVariant"])
        self.assertEqual(result["disqualifiedCount"], 9)

    def test_incomplete_matrix_is_invalid(self) -> None:
        summary = summarize_matrix(candidate_rows()[:-1])
        self.assertFalse(summary["ok"])
        self.assertFalse(summary["promotionEligible"])
        self.assertIn("nine typed candidate outcomes required", summary["errors"])

    def test_noncanonical_digest_is_invalid(self) -> None:
        rows = candidate_rows()
        rows[3]["candidateDigest"] = "not-a-digest"
        summary = summarize_matrix(rows)
        self.assertFalse(summary["ok"])
        self.assertIn("candidate digests must be canonical and unique", summary["errors"])

    def test_global_failure_retains_all_typed_rows(self) -> None:
        rows = candidate_rows(set(range(1, 10)))
        summary = summarize_matrix(rows, global_errors=["shared regression bank unavailable"])
        self.assertFalse(summary["ok"])
        self.assertEqual(len(summary["rows"]), 9)
        self.assertTrue(all(row["errors"] for row in summary["rows"]))

    def test_ranker_rejects_inconsistent_matrix_summary(self) -> None:
        with self.assertRaisesRegex(ValueError, "passingCount"):
            rank_passing_candidates({"ok": True, "rows": candidate_rows(), "passingCount": 8})


class TrajectoryTests(unittest.TestCase):
    def test_lane_runner_projects_optional_event_path(self) -> None:
        path = Path(__file__).with_name("lane-runner.py")
        spec = importlib.util.spec_from_file_location("safe_lab_lane_runner", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        env = module.adapter_environment({"PRESERVE": "yes"}, Path("/workspace/optional-events.jsonl"))
        self.assertEqual(env["PRESERVE"], "yes")
        self.assertEqual(env["WASM_AGENT_EVENTS_PATH"], "/workspace/optional-events.jsonl")

    def test_normalizer_redacts_and_never_copies_reasoning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "adapter.jsonl"
            source.write_text("\n".join([
                json.dumps({
                    "kind": "search", "status": "completed", "actionId": "act-1",
                    "path": "/source/pkg/owner.py", "arguments": {"query": "secret query"},
                    "summary": "Bearer abcdefghijklmnop api_key=topsecret for person@example.com",
                    "durationMs": 12,
                }),
                json.dumps({"kind": "reasoning", "message": "private chain of thought"}),
                json.dumps({"kind": "edit", "status": "passed", "changedFiles": ["a.py", "b.py"]}),
            ]) + "\n", encoding="utf-8")
            trajectory = build_trajectory(
                source, terminal_status="completed", slot="harness-01", terminal_summary="lane completed",
            )

        serialized = json.dumps(trajectory)
        self.assertNotIn("abcdefghijklmnop", serialized)
        self.assertNotIn("topsecret", serialized)
        self.assertNotIn("person@example.com", serialized)
        self.assertNotIn("private chain of thought", serialized)
        self.assertNotIn("secret query", serialized)
        self.assertEqual(trajectory["events"][0]["p"], "src:pkg/owner.py")
        self.assertTrue(trajectory["events"][0]["d"].startswith("sha256:"))
        self.assertEqual(trajectory["events"][1]["n"]["fc"], 2)
        self.assertEqual(trajectory["events"][-1]["k"], "terminal")
        self.assertEqual(trajectory["events"][-1]["s"], "ok")
        self.assertIn("private_reasoning_ignored", trajectory["metadata"]["warnings"])
        self.assertFalse(trajectory["metadata"]["admissibleForStrategyMining"])

    def test_missing_or_invalid_adapter_events_still_preserve_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.jsonl"
            absent = build_trajectory(
                missing, terminal_status="failed", slot="harness-02", terminal_summary="adapter failed",
            )
            self.assertEqual(len(absent["events"]), 1)
            self.assertEqual(absent["events"][0]["k"], "terminal")
            self.assertEqual(absent["events"][0]["s"], "err")
            self.assertTrue(absent["metadata"]["terminalPreserved"])

            clean_failed_path = Path(directory) / "clean-failed.jsonl"
            clean_failed_path.write_text(json.dumps({"kind": "test", "status": "failed"}) + "\n")
            clean_failed = build_trajectory(
                clean_failed_path, terminal_status="failed", slot="harness-02", terminal_summary="test failed",
            )
            self.assertFalse(clean_failed["metadata"]["admissibleForStrategyMining"])

            invalid = Path(directory) / "invalid.jsonl"
            invalid.write_text("not-json\n" + json.dumps({"kind": "test", "status": "passed"}) + "\n")
            observed = build_trajectory(
                invalid, terminal_status="completed", slot="harness-03", terminal_summary="done",
            )
            self.assertEqual([event["k"] for event in observed["events"]], ["test", "terminal"])
            self.assertIn("adapter_event_invalid_json:1", observed["metadata"]["warnings"])

    def test_writer_emits_compact_jsonl_with_terminal_last(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "adapter.jsonl"
            output = root / "events.jsonl"
            source.write_text(json.dumps({"type": "command", "status": "completed", "returncode": 0}) + "\n")
            result = write_trajectory(
                output, source, terminal_status="completed", slot="harness-04", terminal_summary="complete",
            )
            lines = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual([line["q"] for line in lines], [1, 2])
            self.assertEqual(lines[-1]["k"], "terminal")
            self.assertTrue(all(set(line).issubset(FIELD_DICTIONARY) for line in lines))
            self.assertTrue(all(line["k"] in KIND_CODES for line in lines))
            self.assertTrue(all(line.get("s", "ok") in STATUS_CODES for line in lines))
            self.assertTrue(result["metadata"]["admissibleForStrategyMining"])
            self.assertEqual(result["metadata"]["completeness"], "complete")
            self.assertEqual(result["metadata"]["provenance"], ["adapter", "lane"])

    def test_event_cap_keeps_authoritative_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "many.jsonl"
            source.write_text(
                "".join(json.dumps({"kind": "read", "status": "completed"}) + "\n" for _ in range(MAX_EVENTS + 10)),
                encoding="utf-8",
            )
            result = build_trajectory(
                source, terminal_status="completed", slot="harness-05", terminal_summary="complete",
            )
            self.assertEqual(len(result["events"]), MAX_EVENTS)
            self.assertEqual(result["events"][-1]["k"], "terminal")
            self.assertIn("adapter_event_count_truncated", result["metadata"]["warnings"])


if __name__ == "__main__":
    unittest.main()
