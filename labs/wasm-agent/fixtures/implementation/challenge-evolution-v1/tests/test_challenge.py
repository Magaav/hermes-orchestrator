from __future__ import annotations

import unittest

from challenge_evaluator import evaluate


class ChallengeEvolutionTests(unittest.TestCase):
    def test_curriculum_kills_registered_mutants(self) -> None:
        result = evaluate()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["total"], 5)
        self.assertLessEqual(result["cases"], 6)


if __name__ == "__main__":
    unittest.main()
