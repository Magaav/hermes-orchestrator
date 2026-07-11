#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "tools" / "context" / "watch-master-frontier-loop.py"
QUEST_SUITE = ROOT / "plugins" / "wasm-agent" / "tests" / "fixtures" / "master_frontier_quests.json"

spec = importlib.util.spec_from_file_location("watch_master_frontier_loop", SCRIPT_PATH)
assert spec and spec.loader
watch_loop = importlib.util.module_from_spec(spec)
sys.modules["watch_master_frontier_loop"] = watch_loop
spec.loader.exec_module(watch_loop)


class MasterFrontierWatchLoopTests(unittest.TestCase):
    def test_compact_quest_suite_passes_and_reports_capability_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = watch_loop.run(
                QUEST_SUITE,
                Path(tmp) / "watch.json",
                avatar_report=None,
                node_report=None,
            )

        self.assertTrue(report["ok"])
        self.assertEqual(report["summary"]["passed"], report["summary"]["total"])
        self.assertEqual(report["summary"]["capability"]["current"], "L4_bounded_subagent")
        outcome = report["summary"]["engineeringOutcome"]
        self.assertEqual(outcome["status"], "useful")
        self.assertEqual(outcome["acceptedMetricCount"], 3)
        self.assertEqual(outcome["requiredMetricCount"], 5)
        self.assertTrue(outcome["metrics"]["riskReduced"])
        self.assertFalse(outcome["humanExpertiseHarvested"])
        self.assertEqual(report["gatekeeper"]["decision"], "promote")
        self.assertTrue(any(item["id"] == "fake-dispatch-prose-caught" for item in report["watcher"]["results"]))
        self.assertFalse(report["watcher"]["proofArtifacts"], "static watcher must not manufacture live proof artifacts")

    def test_behavioral_and_runtime_artifacts_promote_capability_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            avatar_report = tmp_path / "avatar.json"
            avatar_report.write_text(json.dumps({
                "status": "passed",
                "score": 100,
                "runId": "avatar-proof",
                "assertions": [
                    {"name": "Master:frontier selected", "status": "passed"},
                    {"name": "route.resolved before provider dispatch on every turn", "status": "passed"},
                    {"name": "no Hermes broad fallback", "status": "passed"},
                    {"name": "exact quest token ledger persisted", "status": "passed"},
                    {"name": "quest aggregate equals sum of turns", "status": "passed"},
                    {"name": "objective-only route fails", "status": "passed"},
                ],
            }), encoding="utf-8")
            node_report = tmp_path / "node.json"
            node_report.write_text(json.dumps({
                "ok": True,
                "nodeId": "paracelsus",
                "capabilities": {"ok": True},
                "chat": {
                    "ok": True,
                    "source": "bridge_runs",
                    "usageModel": "deepseek-v4-flash",
                    "usageTotalTokens": 21040,
                },
            }), encoding="utf-8")

            report = watch_loop.run(
                QUEST_SUITE,
                tmp_path / "watch.json",
                avatar_report=avatar_report,
                node_report=node_report,
                require_proof_artifacts=True,
            )

        self.assertTrue(report["ok"])
        self.assertEqual(report["summary"]["proofArtifactsPassed"], 2)
        self.assertEqual(report["summary"]["capability"]["current"], "L6_node_runtime")
        outcome = report["summary"]["engineeringOutcome"]
        self.assertEqual(outcome["primaryObjective"], "report only independently observed Master:frontier capability")
        self.assertEqual(outcome["status"], "useful")
        self.assertTrue(outcome["metrics"]["liveBehaviorObserved"])
        self.assertTrue(outcome["metrics"]["liveNodeObserved"])
        self.assertFalse(report["summary"]["capability"]["missingProofArtifactIds"])


if __name__ == "__main__":
    unittest.main()
