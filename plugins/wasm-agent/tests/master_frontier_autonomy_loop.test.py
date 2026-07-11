#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "tools" / "context" / "run-master-frontier-autonomy-loop.py"

spec = importlib.util.spec_from_file_location("master_frontier_autonomy_loop", SCRIPT_PATH)
assert spec and spec.loader
loop = importlib.util.module_from_spec(spec)
sys.modules["master_frontier_autonomy_loop"] = loop
spec.loader.exec_module(loop)


class MasterFrontierAutonomyLoopTests(unittest.TestCase):
    def write_watch(self, path: Path, capability: str = "L6_node_runtime") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "ok": True,
            "summary": {
                "proofArtifactsPassed": 2,
                "capability": {
                    "current": capability,
                    "missingQuestIds": [],
                    "missingProofArtifactIds": [],
                },
                "engineeringOutcome": {
                    "status": "useful",
                    "acceptedMetricCount": 6,
                    "requiredMetricCount": 6,
                    "realEngineeringProblemSolved": "replaces repeated manual babysitting with bounded proof",
                },
            },
        }), encoding="utf-8")

    def test_autonomy_loop_runs_watch_before_production_and_promotes(self) -> None:
        calls: list[list[str]] = []

        with tempfile.TemporaryDirectory() as tmp:
            watch_path = Path(tmp) / "watch.json"
            with patch.object(loop, "WATCH_REPORT", watch_path):
                def scoped_runner(argv: list[str], timeout_sec: int) -> tuple[int | None, str, str, int]:
                    calls.append(argv)
                    if argv[:2] == ["python3", "tools/context/watch-master-frontier-loop.py"]:
                        self.write_watch(watch_path)
                    return 0, "ok", "", 5

                report = loop.run(report_path=Path(tmp) / "loop.json", runner=scoped_runner)

        self.assertTrue(report["ok"])
        self.assertEqual([step["name"] for step in report["watcher"]["steps"]], ["watch-loop", "production-gate"])
        self.assertEqual(report["watcher"]["watchSummary"]["capability"], "L6_node_runtime")
        self.assertEqual(report["watcher"]["watchSummary"]["engineeringOutcome"]["status"], "useful")
        self.assertEqual(report["gatekeeper"]["decision"], "promote")
        self.assertEqual(calls[0][:2], ["python3", "tools/context/watch-master-frontier-loop.py"])

    def test_failed_watch_loop_skips_production_and_requests_repair(self) -> None:
        calls: list[list[str]] = []

        def runner(argv: list[str], timeout_sec: int) -> tuple[int | None, str, str, int]:
            calls.append(argv)
            return 1, "", "watch failed", 5

        with tempfile.TemporaryDirectory() as tmp:
            report = loop.run(report_path=Path(tmp) / "loop.json", runner=runner)

        self.assertFalse(report["ok"])
        self.assertEqual([step["name"] for step in report["watcher"]["steps"]], ["watch-loop"])
        self.assertEqual(report["gatekeeper"]["decision"], "repair")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
