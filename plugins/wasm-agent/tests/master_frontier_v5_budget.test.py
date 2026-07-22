#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier import budget  # noqa: E402
from master_frontier.v5 import continuity, loop, trajectory  # noqa: E402
from master_frontier.v5.errors import V5Error  # noqa: E402


def routed(limit: int = 100, *, hard: bool = False) -> dict[str, object]:
    route: dict[str, object] = {
        "route_id": "fixture.budget",
        "budget": {
            "head_tokens_max": limit,
            "provider_tokens_max": limit * 2,
            "api_calls_max": 4,
            "wall_ms_max": 60_000,
        },
    }
    if hard:
        route["budget"]["enforcement"] = "hard"
        route["budget"]["input_tokens_max"] = 1
    return route


class MasterFrontierV5BudgetTests(unittest.TestCase):
    def test_advisory_target_accepts_five_calls_beyond_head_and_provider_targets(self) -> None:
        route = routed()
        usages = [{"prompt_tokens": 50, "completion_tokens": 25} for _ in range(5)]

        self.assertEqual(budget.provider_tokens_used(usages), 375)
        self.assertEqual(budget.provider_token_diagnostics(route, usages), {
            "used": 375,
            "target": 200,
            "over_target": True,
            "hard": False,
        })
        self.assertEqual(budget.api_call_diagnostics(route, usages), {
            "used": 5,
            "target": 4,
            "over_target": True,
            "hard": False,
        })
        self.assertIsNone(budget.provider_token_status(route, usages))
        self.assertIsNone(budget.violation(route, usages))
        self.assertEqual(budget.continuation_limit(route, calls_used=5, hard_max=12), 12)

    def test_api_diagnostics_count_unmetered_failed_attempts(self) -> None:
        route = routed()
        usages = [{"total_tokens": 25}]

        self.assertEqual(budget.api_call_diagnostics(route, usages, calls_used=2), {
            "used": 2,
            "target": 4,
            "over_target": False,
            "hard": False,
        })

    def test_exact_hard_provider_budget_can_finish_but_overage_is_rejected(self) -> None:
        exact = loop.run(
            "hello", routed(hard=True), trajectory.new("exact", "turn", "hello", "fixture.budget"),
            complete=lambda *_: {"reply": "done", "usage": {"total_tokens": 200}},
            execute=lambda *_: {},
        )
        self.assertEqual(exact.answer, "done")

        state = trajectory.new("over", "turn", "hello", "fixture.budget")
        with self.assertRaises(V5Error) as raised:
            loop.run(
                "hello", routed(hard=True), state,
                complete=lambda *_: {"reply": "must not complete", "usage": {"total_tokens": 201}},
                execute=lambda *_: {},
            )
        self.assertEqual(raised.exception.code, "provider_token_budget_exhausted")
        self.assertEqual(state["usages"], [{"total_tokens": 201}])

    def test_resume_at_budget_does_not_make_another_provider_call(self) -> None:
        state = trajectory.new("resume", "turn", "hello", "fixture.budget")
        state["usages"] = [{"prompt_tokens": 160, "completion_tokens": 40}]
        called = []
        with self.assertRaises(V5Error) as raised:
            loop.run(
                "hello", routed(hard=True), state,
                complete=lambda *_: called.append(True) or {"reply": "unexpected"},
                execute=lambda *_: {},
            )
        self.assertEqual(raised.exception.code, "provider_token_budget_exhausted")
        self.assertEqual(called, [])

    def test_cumulative_usage_survives_recent_ring_and_checkpoint_restore(self) -> None:
        state = trajectory.new("many", "turn", "hello", "fixture.budget")
        state["usages"] = [{"total_tokens": index} for index in range(5, 21)]
        state["usage_totals"] = {
            "prompt_tokens": 2100, "completion_tokens": 210,
            "total_tokens": 2310, "cached_input_tokens": 0,
            "reasoning_tokens": 0, "metered_calls": 21,
        }
        scope = continuity.binding(
            user_id="user", session_id="session", route_id="fixture.budget",
            route_digest="digest", source_run_id="many", source_turn_id="turn",
        )
        checkpoint = continuity.create(state, scope=scope)
        restored = continuity.restore(
            checkpoint, expected_scope=scope, previous_run_id="many",
            run_id="resumed", turn_id="next", objective="hello", route_id="fixture.budget",
        )

        self.assertEqual(len(restored["usages"]), 16)
        self.assertEqual(restored["usage_totals"]["metered_calls"], 21)
        self.assertEqual(restored["usage_totals"]["total_tokens"], 2310)

    def test_loop_accumulates_more_calls_than_recent_ring_retains(self) -> None:
        decisions = [
            {"reply": '{"tool":"search","arguments":{"query":"q%d"}}' % index,
             "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}
            for index in range(20)
        ]
        decisions.append({"reply": "done", "usage": {"total_tokens": 10}})
        responses = iter(decisions)
        location = iter(range(1, 21))
        state = trajectory.new("many", "turn", "hello", "fixture.budget")

        outcome = loop.run(
            "hello", routed(), state,
            complete=lambda *_: next(responses),
            execute=lambda *_: {
                "ok": True, "matches": [{"path": "owner.py", "line": next(location)}],
            },
        )

        self.assertEqual(outcome.calls, 21)
        self.assertEqual(len(outcome.usages), 16)
        self.assertEqual(outcome.usage_totals["metered_calls"], 21)
        self.assertEqual(outcome.usage_totals["total_tokens"], 210)
        self.assertEqual(state["usage_totals"], outcome.usage_totals)

    def test_hard_budget_uses_cumulative_total_beyond_recent_ring(self) -> None:
        state = trajectory.new("resume", "turn", "hello", "fixture.budget")
        state["usages"] = [{"total_tokens": 1} for _ in range(16)]
        state["usage_totals"] = {
            "prompt_tokens": 160, "completion_tokens": 40,
            "total_tokens": 200, "cached_input_tokens": 0,
            "reasoning_tokens": 0, "metered_calls": 20,
        }
        called = []
        with self.assertRaises(V5Error) as raised:
            loop.run(
                "hello", routed(hard=True), state,
                complete=lambda *_: called.append(True) or {"reply": "unexpected"},
                execute=lambda *_: {},
            )
        self.assertEqual(raised.exception.code, "provider_token_budget_exhausted")
        self.assertEqual(called, [])

    def test_routed_budget_requires_measurable_provider_usage(self) -> None:
        with self.assertRaises(V5Error) as raised:
            loop.run(
                "hello", routed(hard=True), trajectory.new("missing", "turn", "hello", "fixture.budget"),
                complete=lambda *_: {"reply": "unmetered"}, execute=lambda *_: {},
            )
        self.assertEqual(raised.exception.code, "provider_usage_unavailable")

    def test_next_output_is_per_call_and_cumulative_only_when_hard(self) -> None:
        route = routed()
        route["budget"]["max_output_tokens"] = 80
        self.assertEqual(budget.output_tokens_remaining(route, [{"total_tokens": 30}]), 80)
        self.assertEqual(budget.output_tokens_remaining(route, [{"total_tokens": 195}]), 80)
        route["budget"]["head_tokens_max"] = 50
        self.assertEqual(budget.output_tokens_remaining(route, [{"total_tokens": 195}]), 50)

        hard_route = routed(hard=True)
        hard_route["budget"]["max_output_tokens"] = 80
        self.assertEqual(budget.output_tokens_remaining(hard_route, [{"total_tokens": 195}]), 4)
        self.assertIsNone(budget.output_tokens_remaining({"route_id": "unbounded"}, []))

    def test_hard_budget_reserves_declared_input_before_output(self) -> None:
        bounded = routed(hard=True)
        bounded["budget"]["input_tokens_max"] = 30
        self.assertEqual(budget.output_tokens_remaining(bounded, [{"total_tokens": 150}]), 20)

        unbounded = routed()
        unbounded["budget"]["enforcement"] = "hard"
        with self.assertRaises(V5Error) as raised:
            loop.run(
                "hello", unbounded, trajectory.new("hard", "turn", "hello", "fixture.budget"),
                complete=lambda *_: self.fail("unbounded hard call must not reach provider"),
                execute=lambda *_: {},
            )
        self.assertEqual(raised.exception.code, "provider_input_budget_unbounded")

    def test_host_request_bound_overrides_understated_route_reservation(self) -> None:
        bounded = routed(limit=5_000, hard=True)
        bounded["budget"]["input_tokens_max"] = 1
        payload = {"messages": [{"role": "user", "content": "x" * 2_000}], "tools": []}
        host_bound = budget.request_input_token_upper_bound(payload)

        remaining = budget.output_tokens_remaining(bounded, [], request_payload=payload)

        self.assertGreater(host_bound, 2_000)
        self.assertEqual(remaining, min(5_000, 10_000 - host_bound))

        schema_payload = {**payload, "response_format": {"schema": {"description": "y" * 4_000}}}
        self.assertGreater(
            budget.request_input_token_upper_bound(schema_payload),
            host_bound + 3_900,
        )

    def test_only_explicit_request_enforcement_makes_targets_hard(self) -> None:
        advisory = budget.resolve(
            {"provider_tokens_max": 200, "api_calls_max": 4, "enforcement": "hard"},
            {},
        )
        explicit = budget.resolve(
            {"provider_tokens_max": 200, "api_calls_max": 4},
            {"enforcement": "hard"},
        )

        self.assertNotIn("enforcement", advisory)
        self.assertEqual(explicit["enforcement"], "hard")

    def test_oversized_mutation_is_rejected_before_execute(self) -> None:
        paths = [f"root-{index:03d}/{'z' * 240}/file.py" for index in range(80)]
        operations = [{"op": "create", "path": path, "content": "x", "expected_absent": True} for path in paths]
        executed = []
        with self.assertRaises(V5Error) as raised:
            loop.run(
                "implement", routed(), trajectory.new("large", "turn", "implement", "fixture.budget"),
                complete=lambda *_: {
                    "reply": "", "usage": {"total_tokens": 1},
                    "tool_calls": [{"name": "edit", "arguments": {"operations": operations}}],
                },
                execute=lambda *_: executed.append(True) or {"ok": True},
            )
        self.assertEqual(raised.exception.code, "operation_checkpoint_budget_exceeded")
        self.assertEqual(executed, [])


if __name__ == "__main__":
    unittest.main()
