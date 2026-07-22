from __future__ import annotations

import unittest

from decision_isolation_matrix import evaluate, load


class DecisionIsolationMatrixTests(unittest.TestCase):
    def test_matrix_has_ordered_categorical_stages(self) -> None:
        matrix = load()
        self.assertEqual([item["id"] for item in matrix["stages"]], list("ABCDE"))
        self.assertEqual(len({item["category"] for item in matrix["stages"]}), 5)

    def test_first_failure_stops_at_missing_planning_handoff(self) -> None:
        matrix = load()
        observations = []
        for stage in matrix["stages"]:
            evidence = list(stage["requires"])
            if stage["id"] == "C":
                evidence.remove("selected_handoff")
            observations.append({"id": stage["id"], "evidence": evidence, "run_id": f"run-{stage['id']}"})
        result = evaluate(observations, matrix=matrix)
        self.assertFalse(result["ok"])
        self.assertEqual(result["first_failure"], {
            "stage": "C", "category": "planning_to_execution",
            "missing": ["selected_handoff"], "run_id": "run-C",
        })

    def test_complete_evidence_passes_all_stages(self) -> None:
        matrix = load()
        result = evaluate([
            {"id": stage["id"], "evidence": stage["requires"]}
            for stage in matrix["stages"]
        ], matrix=matrix)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["first_failure"])


if __name__ == "__main__":
    unittest.main()
