#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools/context/prove-claim-risk-proof.py"
MATRIX = ROOT / "docs/context/CLAIM_RISK_PROOF_MATRIX.json"


class ClaimRiskProofEndToEndTests(unittest.TestCase):
    def test_campaign_accepts_healthy_receipt_and_rejects_four_faults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report_path = Path(temporary) / "report.json"
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--matrix", str(MATRIX), "--self-test", "--report", str(report_path)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "pass")
            self.assertEqual(
                [case["id"] for case in report["cases"]],
                ["healthy", "stale-evidence", "missing-class", "threshold-regression", "artifact-tamper"],
            )
            self.assertTrue(all(case["detected"] for case in report["cases"]))
            self.assertEqual(report["cases"][0]["evaluation"]["status"], "pass")
            self.assertTrue(all(case["evaluation"]["status"] == "fail" for case in report["cases"][1:]))

    def test_invalid_matrix_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            matrix_path = directory / "matrix.json"
            report_path = directory / "report.json"
            matrix_path.write_text('{"schemaVersion": 1, "claims": []}', encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--matrix", str(matrix_path), "--self-test", "--report", str(report_path)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "fail")
            self.assertIn("matrix_claims_missing", report["errors"])


if __name__ == "__main__":
    unittest.main()
