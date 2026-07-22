#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
SPEC = importlib.util.spec_from_file_location("safe_lab_strategy_ranker", LAB / "rank-nine-lane-benchmark.py")
assert SPEC and SPEC.loader
RANKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RANKER)


def report(*, strategy: bool, tool_visibility: bool = True) -> dict:
    results = []
    receipts = []
    for index in range(1, 10):
        slot = f"harness-{index:02d}"
        results.append({
            "slot": slot,
            "lane": {
                "adapter": f"agent-{index}", "durationMs": 100 + index,
                "trajectory": {"admissibleForStrategyMining": strategy},
            },
            "answer": {"semantic": {"passed": True}},
        })
        receipt = {
            "laneId": slot, "status": 200, "upstreamCalled": True,
            "promptTokens": 100 + index, "completionTokens": 10,
        }
        if tool_visibility:
            receipt["toolCallCount"] = 0
        receipts.append(receipt)
    return {
        "status": "benchmark_complete", "semanticAllPassed": True,
        "rankingAllowed": True, "strategyComparable": strategy,
        "runId": "fixture", "results": results, "gatewayReceipts": receipts,
        "task": {"fixture": {"requestClass": "conversation"}},
    }


class StrategyRankingTests(unittest.TestCase):
    def test_efficiency_ranking_does_not_invent_strategy_candidates(self) -> None:
        result = RANKER.rank(report(strategy=False))
        self.assertTrue(result["ok"])
        self.assertTrue(result["comparability"]["efficiency"])
        self.assertFalse(result["comparability"]["strategy"])
        self.assertEqual(result["goldenPatternCandidates"], [])
        self.assertEqual(result["promotionDecision"], "cross_fixture_strategy_evidence_required")

    def test_single_fixture_never_invents_golden_candidates(self) -> None:
        result = RANKER.rank(report(strategy=True))
        self.assertFalse(result["comparability"]["strategy"])
        self.assertEqual(result["goldenPatternCandidates"], [])
        self.assertEqual(result["promotionDecision"], "cross_fixture_strategy_evidence_required")

    def test_missing_tool_observability_is_unknown_not_zero(self) -> None:
        result = RANKER.rank(report(strategy=True, tool_visibility=False))
        self.assertFalse(result["ok"])
        self.assertTrue(any("tool visibility is unknown" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
