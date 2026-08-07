import sys
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier.v5 import verification_answer


class VerificationAnswerTests(unittest.TestCase):
    def test_completed_verification_is_shaped_from_receipts(self) -> None:
        answer = verification_answer.build(
            {
                "checks": [{"check_id": "focused", "returncode": 0, "duration_ms": 164}],
                "observed_changed_files": ["public/widget.js", "tests/widget.test.js"],
            },
            [
                {"path": "public/widget.js", "sha256": "a" * 64},
                {
                    "result": {
                        "schema": "hermes.wasm_agent.route.git_diff_summary.v2",
                        "receipt_sha256": "b" * 64,
                    }
                },
            ],
        )
        self.assertIn("Verification completed with revision-bound proof.", answer)
        self.assertIn("Check `focused`: passed", answer)
        self.assertIn("Files changed by this run: none.", answer)
        self.assertIn("Observed worktree changes:", answer)
        self.assertIn("public/widget.js", answer)
        self.assertNotIn("evidence unavailable", answer.lower())


if __name__ == "__main__":
    unittest.main()
