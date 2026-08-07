#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from fixture_outcomes import lane_outcome, suite_outcome


PATH = Path(__file__).with_name("live-fixture-orchestrator.py")
SPEC = importlib.util.spec_from_file_location("live_fixture_orchestrator", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LiveFixtureResultSemanticsTests(unittest.TestCase):
    def test_semantic_miss_is_unsatisfactory_not_execution_failure(self) -> None:
        result = MODULE.fixture_outcome([], ["answer missed contract"], {"passed": False}, {"readinessCandidatePassed": True}, False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["answerSatisfaction"], "unsatisfactory")
        self.assertEqual(result["classification"], "live_fixture_answer_unsatisfactory")
        self.assertTrue(result["improvementRequired"])
        self.assertFalse(result["promotionEligible"])

    def test_infrastructure_error_is_iterable_unsatisfactory_outcome(self) -> None:
        result = MODULE.fixture_outcome(["gateway unavailable"], [], {"passed": False}, {}, False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["harnessStatus"], "completed")
        self.assertEqual(result["answerSatisfaction"], "unsatisfactory")
        self.assertEqual(result["classification"], "live_fixture_answer_unsatisfactory")
        self.assertEqual(result["executionStatus"], "unavailable")
        self.assertEqual(result["evaluationStatus"], "unavailable")
        self.assertEqual(result["blockers"], ["gateway unavailable"])

    def test_semantic_pass_is_satisfactory(self) -> None:
        result = MODULE.fixture_outcome([], [], {"passed": True}, {"readinessCandidatePassed": True}, True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["answerSatisfaction"], "satisfactory")
        self.assertTrue(result["promotionEligible"])

    def test_suite_completes_unsatisfactory_without_promoting(self) -> None:
        result = suite_outcome([
            {"fixtureId": "fx_good", "answerSatisfaction": "satisfactory", "promotionEligible": True},
            {"fixtureId": "fx_retry", "answerSatisfaction": "unsatisfactory", "promotionEligible": False},
        ])
        self.assertTrue(result["ok"])
        self.assertEqual(result["harnessStatus"], "completed")
        self.assertEqual(result["suiteSatisfaction"], "unsatisfactory")
        self.assertFalse(result["promotionEligible"])
        self.assertEqual(result["unsatisfactoryFixtureIds"], ["fx_retry"])

    def test_lane_completes_with_unsatisfactory_candidate(self) -> None:
        result = lane_outcome(False)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["answerSatisfaction"], "unsatisfactory")
        self.assertTrue(result["improvementRequired"])


if __name__ == "__main__":
    unittest.main()
