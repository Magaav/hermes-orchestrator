#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_ROOT))

from master_frontier import budget  # noqa: E402


class MasterFrontierBudgetTests(unittest.TestCase):
    def envelope(self) -> dict[str, object]:
        return {
            "budget": {"max_output_tokens": 5000},
            "task_contract": {
                "budget": {
                    "head_tokens_max": 3000,
                    "provider_tokens_max": 8000,
                    "api_calls_max": 3,
                    "wall_ms_max": 90000,
                    "max_output_tokens": 900,
                }
            },
        }

    def test_caller_cannot_expand_contract_limits(self) -> None:
        resolved = budget.from_envelope(self.envelope())
        self.assertEqual(resolved["head_tokens_max"], 3000)
        self.assertEqual(resolved["max_output_tokens"], 900)

    def test_output_ceiling_is_not_clamped_to_advisory_head_target(self) -> None:
        resolved = budget.resolve(
            {"head_tokens_max": 3000, "provider_tokens_max": 8000},
            {"max_output_tokens": 32768},
        )

        self.assertEqual(resolved["head_tokens_max"], 3000)
        self.assertEqual(resolved["max_output_tokens"], 32768)

    def test_continuations_reserve_already_used_calls(self) -> None:
        self.assertEqual(budget.continuation_limit(self.envelope(), calls_used=1), 2)
        self.assertEqual(budget.continuation_limit(self.envelope(), calls_used=3), 0)

    def test_token_and_call_overages_are_typed(self) -> None:
        calls = [{"total_tokens": 1000}, {"total_tokens": 1001}, {"total_tokens": 1000}]
        self.assertEqual(budget.violation(self.envelope(), calls)["code"], "provider_token_budget_exhausted")
        calls.append({"total_tokens": 1})
        self.assertEqual(budget.violation(self.envelope(), calls)["code"], "api_call_budget_exhausted")


if __name__ == "__main__":
    unittest.main()
