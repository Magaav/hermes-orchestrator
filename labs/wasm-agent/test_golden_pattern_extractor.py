#!/usr/bin/env python3
from __future__ import annotations

import unittest

from golden_pattern_extractor import extract


def run(instance: str, *, complete: bool = True, provenance: list[str] | None = None) -> dict:
    results = []
    for adapter in ("agent-a", "agent-b"):
        results.append({
            "answer": {"semantic": {"passed": True}},
            "lane": {
                "adapter": adapter,
                "trajectory": {
                    "completeness": "complete" if complete else "incomplete",
                    "admissibleForStrategyMining": complete,
                    "provenance": provenance if provenance is not None else ["adapter", "lane"],
                    "events": [
                        {"k": "read", "s": "ok", "o": "adapter"},
                        {"k": "edit", "s": "ok", "o": "adapter"},
                        {"k": "test", "s": "ok", "o": "adapter"},
                        {"k": "terminal", "s": "ok", "o": "lane"},
                    ],
                },
            },
        })
    return {"runId": f"run-{instance}", "task": {"fixture": {"id": instance}}, "results": results}


class GoldenPatternExtractorTests(unittest.TestCase):
    def test_extracts_only_observed_cross_agent_cross_instance_sequences(self) -> None:
        result = extract([run("one"), run("two"), run("three")])
        sequences = {tuple(row["sequence"]) for row in result["patterns"]}
        self.assertIn(("read", "edit"), sequences)
        self.assertIn(("edit", "test", "terminal"), sequences)
        self.assertNotIn(("search", "edit"), sequences)
        self.assertTrue(result["promotionEligible"])
        self.assertTrue(all(row["agentSupport"] == 2 for row in result["patterns"]))
        self.assertTrue(all(row["instanceSupport"] == 3 for row in result["patterns"]))

    def test_single_fixture_never_promotes(self) -> None:
        result = extract([run("one")])
        self.assertEqual(result["patterns"], [])
        self.assertFalse(result["promotionEligible"])

    def test_incomplete_or_untrusted_trajectory_is_rejected(self) -> None:
        result = extract([
            run("one", complete=False),
            run("two", provenance=["adapter", "unknown"]),
        ])
        self.assertEqual(result["eligibleTrajectories"], 0)
        self.assertEqual(result["rejected"], {"provenance_untrusted": 2, "trajectory_incomplete": 2})


if __name__ == "__main__":
    unittest.main()
