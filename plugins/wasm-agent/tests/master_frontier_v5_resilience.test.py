#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier.v5 import completion, context, loop, reliability, trajectory  # noqa: E402


SOURCE_ROUTE = {
    "route_id": "fixture.source",
    "caps": ["repo.read"],
    "task_contract": {"request_class": "source_investigation"},
}
RUNTIME_ROUTE = {
    "route_id": "fixture.runtime",
    "caps": ["runtime.inspect"],
    "task_contract": {"request_class": "runtime_inspection"},
}


def append_result(state: dict, tool: str, result: dict) -> None:
    trajectory.append(state, {
        "kind": "tool",
        "tool": tool,
        "status": "completed",
        "result": result,
    })


class MasterFrontierV5ResilienceTests(unittest.TestCase):
    def test_arbitrary_successful_read_is_not_conclusive_source_coverage(self) -> None:
        state = trajectory.new("run", "turn", "review", "fixture.source")
        append_result(state, "read", {"ok": True, "path": "unrelated.py", "content": "1: value = 1"})

        assessment = completion.assess(state, SOURCE_ROUTE)

        self.assertEqual(assessment["status"], "incomplete")
        self.assertEqual(assessment["required_gaps"], ["source_coverage"])
        self.assertFalse(context.completion_only(state, SOURCE_ROUTE))

    def test_complete_standalone_read_is_conclusive_source_coverage(self) -> None:
        state = trajectory.new("run", "turn", "review", "fixture.source")
        append_result(state, "read", {
            "ok": True,
            "path": "owner.py",
            "start_line": 1,
            "end_line": 3,
            "line_count": 3,
            "truncated": False,
            "content": "1: one\n2: two\n3: three",
        })

        status = completion.evidence_status(state)

        self.assertTrue(status["owner_fully_read"])
        self.assertEqual(status["coverage_kind"], "owner_file")
        self.assertTrue(context.completion_only(state, SOURCE_ROUTE))

    def test_all_declared_focus_ranges_are_required(self) -> None:
        state = trajectory.new("run", "turn", "review", "fixture.source")
        append_result(state, "search", {
            "ok": True,
            "focus": {
                "owner_file": "owner.py",
                "line_count": 200,
                "suggested_ranges": [
                    {"start_line": 20, "end_line": 40},
                    {"start_line": 120, "end_line": 150},
                ],
            },
        })
        append_result(state, "read", {
            "ok": True,
            "path": "owner.py",
            "start_line": 20,
            "end_line": 40,
            "line_count": 200,
            "truncated": False,
            "content": "focused part one",
        })
        first = completion.assess(state, SOURCE_ROUTE)
        self.assertEqual(first["status"], "incomplete")
        self.assertEqual(first["next_actions"], [{
            "tool": "read",
            "arguments": {"path": "owner.py", "start_line": 120, "end_line": 150},
        }])

        append_result(state, "read", {
            "ok": True,
            "path": "owner.py",
            "start_line": 120,
            "end_line": 150,
            "line_count": 200,
            "truncated": False,
            "content": "focused part two",
        })
        status = completion.evidence_status(state)
        self.assertFalse(status["owner_fully_read"])
        self.assertTrue(status["focused_ranges_read"])
        self.assertEqual(completion.assess(state, SOURCE_ROUTE)["status"], "sufficient")

    def test_runtime_completion_requires_scoped_snapshot_or_proof(self) -> None:
        state = trajectory.new("run", "turn", "inspect", "fixture.runtime")
        append_result(state, "inspect", {"ok": True, "summary": "generic inspection succeeded"})
        self.assertEqual(completion.assess(state, RUNTIME_ROUTE)["status"], "incomplete")

        append_result(state, "inspect", {
            "ok": True,
            "runtime": {
                "action": "runtime.snapshot.get",
                "result": {"e": {"id": "entity-a"}, "s": "unknown", "u": [{"code": "not_collected"}]},
            },
        })
        self.assertEqual(completion.assess(state, RUNTIME_ROUTE)["status"], "sufficient")
        self.assertTrue(context.completion_only(state, RUNTIME_ROUTE))

    def test_runtime_context_names_exact_authorized_entities(self) -> None:
        state = trajectory.new("run", "turn", "inspect", "fixture.runtime")
        route = {
            **RUNTIME_ROUTE,
            "entities": [{"id": "runtime-a", "kind": "scoped-run-history"}],
        }

        prompt = context.messages("inspect", route, state)[1]["content"]

        self.assertIn("E\truntime-a:scoped-run-history", prompt)

    def test_evidence_from_other_modality_does_not_force_completion(self) -> None:
        source_state = trajectory.new("run-source", "turn", "review", "fixture.source")
        append_result(source_state, "read", {
            "ok": True,
            "path": "owner.py",
            "start_line": 1,
            "end_line": 1,
            "line_count": 1,
            "truncated": False,
            "content": "1: value = 1",
        })
        self.assertFalse(context.completion_only(source_state, RUNTIME_ROUTE))

        runtime_state = trajectory.new("run-runtime", "turn", "inspect", "fixture.runtime")
        append_result(runtime_state, "inspect", {
            "ok": True,
            "runtime": {
                "action": "runtime.proof.get",
                "result": {"proof": {"id": "proof-a"}},
            },
        })
        self.assertFalse(context.completion_only(runtime_state, SOURCE_ROUTE))

    def test_source_coverage_does_not_short_circuit_mutation_workflow(self) -> None:
        state = trajectory.new("run", "turn", "implement", "fixture.source")
        append_result(state, "read", {
            "ok": True,
            "path": "owner.py",
            "start_line": 1,
            "end_line": 1,
            "line_count": 1,
            "truncated": False,
            "content": "1: value = 1",
        })
        implementation_route = {
            "route_id": "fixture.source",
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "task_contract": {
                "request_class": "implementation",
                "declared_classes": ["source_investigation", "implementation"],
            },
        }

        self.assertEqual(completion.assess(state, implementation_route)["status"], "incomplete")
        self.assertFalse(context.completion_only(state, implementation_route))

    def test_provider_success_restores_planning_and_next_incident_retry_without_resetting_total(self) -> None:
        state = trajectory.new("run", "turn", "review", "fixture.source")
        append_result(state, "read", {
            "ok": True,
            "path": "owner.py",
            "content": "head\n" + ("evidence\n" * 500) + "tail",
        })
        reliability.record_retry(state, "network-timeout")

        during_retry = context.payload("review", SOURCE_ROUTE, state)["completed"][-1]["result"]["content"]
        self.assertTrue(reliability.retry_active(state))
        self.assertLessEqual(len(during_retry), 1_240)

        summary = reliability.record_success(state)
        after_success = context.payload("review", SOURCE_ROUTE, state)["completed"][-1]["result"]
        self.assertFalse(summary["retry_active"])
        self.assertEqual(summary["transient_retries"], 1)
        self.assertEqual(summary["consecutive_retries"], 0)
        self.assertEqual(summary["last_code"], "network-timeout")
        self.assertNotIn("content", after_success)
        self.assertTrue(after_success["content_omitted"])
        state["pending"] = "frontier_completion"
        final_content = context.payload("review", SOURCE_ROUTE, state)["completed"][-1]["result"]["content"]
        self.assertGreater(len(final_content), len(during_retry) * 2)
        self.assertTrue(reliability.can_retry(state, "network-timeout"))

    def test_legacy_mid_retry_checkpoint_remains_active_until_success(self) -> None:
        state = {
            "provider_reliability": {
                "transient_retries": 1,
                "retry_limit": 1,
                "last_code": "upstream_unavailable",
            },
        }
        self.assertTrue(reliability.retry_active(state))
        self.assertFalse(reliability.record_success(state)["retry_active"])

    def test_loop_success_resets_retry_projection_before_next_decision(self) -> None:
        class Timeout(RuntimeError):
            code = "network-timeout"

        state = trajectory.new("run", "turn", "review", "fixture.source")
        prompts: list[str] = []

        def complete(messages: list[dict[str, str]], _index: int) -> dict:
            prompts.append(messages[1]["content"])
            if len(prompts) == 1:
                raise Timeout("temporary failure")
            if len(prompts) == 2:
                return {"reply": '{"tool":"read","arguments":{"path":"owner.py"}}'}
            return {"reply": "Recovered with complete source evidence."}

        large_content = "head\n" + ("evidence\n" * 500) + "tail"
        outcome = loop.run(
            "review",
            SOURCE_ROUTE,
            state,
            complete=complete,
            execute=lambda *_: {
                "ok": True,
                "path": "owner.py",
                "start_line": 1,
                "end_line": 502,
                "line_count": 502,
                "truncated": False,
                "content": large_content,
            },
        )

        self.assertEqual(outcome.answer, "Recovered with complete source evidence.")
        self.assertGreater(len(prompts[2]), 1_200)
        self.assertFalse(reliability.retry_active(state))
        self.assertEqual(state["provider_reliability"]["transient_retries"], 1)


if __name__ == "__main__":
    unittest.main()
