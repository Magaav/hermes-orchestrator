#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "tools/context/prove-master-frontier-production.py"
spec = importlib.util.spec_from_file_location("prove_master_frontier_production", SCRIPT_PATH)
assert spec and spec.loader
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)


class MasterFrontierProductionProofTests(unittest.TestCase):
    def test_commands_cover_current_master_frontier_tests_without_self_recursion(self) -> None:
        result = proof.command_coverage_result()
        targets = proof.command_target_paths()

        self.assertEqual(result["status"], "pass")
        self.assertFalse(result["recursiveProofCommand"])
        self.assertTrue(proof.relevant_master_frontier_tests().issubset(targets))
        self.assertIn("plugins/wasm-agent/tests/agent_run_store.test.py", targets)
        self.assertIn("tools/context/check-context-sync.py", targets)
        self.assertNotIn(proof.PROOF_TEST_PATH, targets)
        self.assertNotIn("tools/context/prove-master-frontier-production.py", targets)

    def test_command_coverage_fails_typed_for_a_new_unlisted_test(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            test_path = root / "plugins/wasm-agent/tests/master_frontier_new_contract.test.py"
            test_path.parent.mkdir(parents=True)
            test_path.write_text("# new contract\n", encoding="utf-8")

            result = proof.command_coverage_result(root)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["errorType"], "production_command_coverage_incomplete")
        self.assertEqual(result["missingPaths"], ["plugins/wasm-agent/tests/master_frontier_new_contract.test.py"])

    def test_source_change_is_detected_with_a_typed_integrity_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "plugins/wasm-agent/server/master_frontier/owner.py"
            source_path.parent.mkdir(parents=True)
            source_path.write_text("VALUE = 1\n", encoding="utf-8")
            before = proof.source_snapshot(root)
            source_path.write_text("VALUE = 2\n", encoding="utf-8")
            after = proof.source_snapshot(root)

            result = proof.source_integrity_result(before, after)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["errorType"], "source_changed_during_proof")
        self.assertEqual(result["changedPaths"], ["plugins/wasm-agent/server/master_frontier/owner.py"])
        self.assertNotEqual(result["beforeFingerprint"], result["afterFingerprint"])

    def test_fingerprint_manifest_covers_owned_sources_registries_tests_fixtures_and_proof(self) -> None:
        paths = set(proof.fingerprint_paths())

        self.assertIn("plugins/wasm-agent/server/master_frontier/controller_v3.py", paths)
        self.assertIn("plugins/wasm-agent/public/modules/master-frontier/cyphers-v3.js", paths)
        self.assertIn("plugins/wasm-agent/server/agent_route_contracts.json", paths)
        self.assertIn("docs/context/HARNESS_PROMISES.json", paths)
        self.assertIn("plugins/wasm-agent/tests/master_frontier_controller_v3.test.py", paths)
        self.assertIn(proof.C3_COST_FIXTURE_PATH, paths)
        self.assertIn("tools/context/prove-master-frontier-production.py", paths)

    def test_source_addition_and_deletion_change_the_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "plugins/wasm-agent/server/master_frontier/owner.py"
            source_path.parent.mkdir(parents=True)
            before_add = proof.source_snapshot(root)
            source_path.write_text("VALUE = 1\n", encoding="utf-8")
            after_add = proof.source_snapshot(root)
            source_path.unlink()
            after_delete = proof.source_snapshot(root)

        added = proof.source_integrity_result(before_add, after_add)
        deleted = proof.source_integrity_result(after_add, after_delete)
        self.assertEqual(added["changedPaths"], ["plugins/wasm-agent/server/master_frontier/owner.py"])
        self.assertEqual(deleted["changedPaths"], ["plugins/wasm-agent/server/master_frontier/owner.py"])
        self.assertEqual((added["status"], deleted["status"]), ("fail", "fail"))

    def test_report_records_integrity_and_non_live_cost_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = proof.source_snapshot(root)
            report_path = root / "proof.json"
            report = proof.write_report(
                [{"name": "focused", "status": "pass", "evidenceClass": "static"}],
                include_runtime=False,
                source_before=snapshot,
                source_after=snapshot,
                report_path=report_path,
            )
            stored = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertTrue(report["ok"])
        self.assertEqual(stored["schema"], "hermes.context.master_frontier.production_proof.v2")
        self.assertEqual(stored["sourceIntegrity"]["status"], "pass")
        self.assertEqual(stored["sourceIntegrity"]["beforeFingerprint"], snapshot["fingerprint"])
        self.assertEqual(stored["sourceIntegrity"]["afterFingerprint"], snapshot["fingerprint"])
        current = stored["costMetrics"]["current"]
        self.assertEqual((current["calls"], current["tokens"]), (3, 1112))
        self.assertFalse(current["live"])
        self.assertEqual(stored["costMetrics"]["lastKnownGood"]["status"], "unavailable")
        self.assertEqual(stored["costMetrics"]["comparison"]["status"], "unknown")

    def test_report_fails_when_sources_changed_during_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "plugins/wasm-agent/public/modules/master-frontier/owner.js"
            source_path.parent.mkdir(parents=True)
            source_path.write_text("export const value = 1;\n", encoding="utf-8")
            before = proof.source_snapshot(root)
            source_path.write_text("export const value = 2;\n", encoding="utf-8")
            after = proof.source_snapshot(root)
            report = proof.write_report(
                [],
                include_runtime=False,
                source_before=before,
                source_after=after,
                report_path=root / "proof.json",
            )

        self.assertFalse(report["ok"])
        self.assertEqual(report["gatekeeper"]["failed"], ["source-integrity"])
        self.assertEqual(report["sourceIntegrity"]["errorType"], "source_changed_during_proof")

    def test_cli_summary_is_bounded_and_keeps_full_evidence_pull_only(self) -> None:
        huge_tail = "diagnostic-" * 5000
        report = {
            "ok": False,
            "includeRuntime": False,
            "sourceFingerprint": "a" * 64,
            "watcher": {
                "results": [
                    {
                        "name": f"failed-{index}",
                        "status": "fail",
                        "errorType": "focused_failure",
                        "returncode": 1,
                        "stdoutTail": huge_tail,
                        "stderrTail": huge_tail,
                    }
                    for index in range(8)
                ]
            },
        }

        rendered = proof.render_cli_summary(report)
        summary = json.loads(rendered)

        self.assertLessEqual(len(rendered.encode("utf-8")), proof.CLI_OUTPUT_MAX_BYTES)
        self.assertEqual(summary["schema"], "MF_PROOF/1")
        self.assertEqual(len(summary["failed"]), proof.CLI_FAILURE_MAX_ITEMS)
        self.assertEqual(summary["failedOmitted"], 5)
        self.assertEqual(summary["artifact"], "reports/context/latest/master-frontier-production-proof.json")
        self.assertNotIn(huge_tail, rendered)

    def test_cli_summary_reports_pass_counts_without_command_output(self) -> None:
        report = {
            "ok": True,
            "includeRuntime": True,
            "sourceFingerprint": "1234567890abcdef-extra",
            "watcher": {
                "results": [
                    {"name": "one", "status": "pass", "stdoutTail": "verbose output"},
                    {"name": "two", "status": "pass", "stderrTail": "more output"},
                ]
            },
        }

        summary = json.loads(proof.render_cli_summary(report))

        self.assertEqual((summary["checked"], summary["passed"], summary["failed"]), (2, 2, []))
        self.assertTrue(summary["runtime"])
        self.assertEqual(summary["source"], "1234567890abcdef")


if __name__ == "__main__":
    unittest.main()
