import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "windows" / "emit-waproof-receipts.py"


def parse_rows(text: str) -> list[dict[str, str]]:
    rows = []
    for line in text.splitlines():
        if not line:
            continue
        assert line.startswith("WAPROOF|")
        fields = {}
        for token in line.split("|")[1:]:
            key, value = token.split("=", 1)
            fields[key] = value
        rows.append(fields)
    return rows


class WaproofReceiptTests(unittest.TestCase):
    def run_generator(self, reports: Path, output: Path) -> list[dict[str, str]]:
        subprocess.run(
            ["python3", str(SCRIPT), "--reports-root", str(reports), "--output", str(output)],
            cwd=REPO_ROOT,
            check=True,
        )
        return parse_rows(output.read_text(encoding="utf-8"))

    def test_feed_success_cannot_become_installed_hot_shell_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "reports"
            reports.mkdir()
            (reports / "windows-release-feed-check.json").write_text(
                json.dumps(
                    {
                        "ok": True,
                        "schema": "hermes.wasm_agent.windows_release_feed_check.v1",
                        "verified": {
                            "buildId": "win-x64-20260615T114623Z",
                            "sha256": "a" * 64,
                        },
                        "feed": {
                            "buildId": "win-x64-20260615T114623Z",
                            "sha256": "a" * 64,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            rows = self.run_generator(reports, root / "waproof-receipts.hbp")

        package_rows = [row for row in rows if row["kind"] == "package"]
        hot_op_rows = [row for row in rows if row["kind"] == "hot_op"]
        runtime_rows = [row for row in rows if row["kind"] == "runtime" and row["proof"] == "windows_hot_shell_proof"]

        self.assertEqual(package_rows[0]["claim_status"], "verified")
        self.assertEqual(package_rows[0]["proof_result"], "pass")
        self.assertEqual(package_rows[0]["proof"], "windows_release_feed_check")
        self.assertEqual(hot_op_rows[0]["claim_status"], "implemented-unverified")
        self.assertEqual(hot_op_rows[0]["proof_result"], "missing")
        self.assertEqual(hot_op_rows[0]["proof"], "windows_hot_shell_proof")
        self.assertEqual(runtime_rows[0]["claim_status"], "implemented-unverified")
        self.assertEqual(runtime_rows[0]["proof_result"], "missing")
        self.assertEqual(runtime_rows[0]["proof"], "windows_hot_shell_proof")
        self.assertFalse(
            any(row["kind"] in {"hot_op", "runtime"} and row["claim_status"] == "verified" for row in rows)
        )

    def test_rows_use_canonical_status_and_separate_proof_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "reports"
            reports.mkdir()
            (reports / "hot-shell-proof-result.json").write_text(
                json.dumps(
                    {
                        "ok": False,
                        "bridgeAlive": False,
                        "schema": "hermes.wasm_agent.windows_hot_shell_proof.v1",
                        "runId": "hotop-test",
                        "failureClassification": "handler_timeout",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            rows = self.run_generator(reports, root / "waproof-receipts.hbp")

        canonical = {"verified", "implemented-unverified", "proposal", "future", "stale", "unknown"}
        proof_results = {"pass", "fail", "missing", "not_run"}
        self.assertTrue(all(row["claim_status"] in canonical for row in rows))
        self.assertTrue(all(row["proof_result"] in proof_results for row in rows))
        self.assertNotIn("failed", {row["claim_status"] for row in rows})


if __name__ == "__main__":
    unittest.main()
