#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools/context/evaluate-wasm-agent-product-readiness.py"
SPEC = importlib.util.spec_from_file_location("wasm_agent_product_readiness_evaluation", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("product readiness evaluator import unavailable")
evaluation = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = evaluation
SPEC.loader.exec_module(evaluation)


PROMISE_IDS = (
    "master-frontier-v6-live-model-self-host",
    "production-native-control-authority",
    "master-frontier-v6-production-client-ui",
    "windows-hot-shell-proof",
    "android-shell-v2-wake-loop",
)


class ProductReadinessEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.registry_path = self.root / "HARNESS_PROMISES.json"
        self.schema_path = self.root / "PRODUCT_READINESS_RESULT_SCHEMA.json"
        self.schema_path.write_text(json.dumps({"$id": evaluation.SCHEMA_ID}), encoding="utf-8")
        self.write_registry()
        self.patchers = (
            patch.object(evaluation, "ROOT", self.root),
            patch.object(evaluation, "REGISTRY_PATH", self.registry_path),
            patch.object(evaluation, "SCHEMA_PATH", self.schema_path),
            patch.object(evaluation, "source_fingerprint", return_value={
                "gitHead": "fixture-head",
                "dirty": False,
                "changedPathCount": 0,
                "worktreeStateSha256": "0" * 64,
            }),
            patch.object(
                evaluation,
                "utc_now",
                return_value=datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc),
            ),
        )
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary.cleanup()

    def write_registry(self, invalidated_by: dict[str, list[str]] | None = None) -> None:
        invalidated_by = invalidated_by or {}
        document = {
            "schemaVersion": 1,
            "updatedAt": "2026-08-20",
            "promises": [
                {
                    "id": promise_id,
                    "invalidatedBy": invalidated_by.get(promise_id, []),
                }
                for promise_id in PROMISE_IDS
            ],
        }
        self.registry_path.write_text(json.dumps(document), encoding="utf-8")

    def write_artifact(self, relative_path: str, payload: dict[str, object]) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def write_passing_artifacts(self) -> None:
        self.write_artifact(
            "reports/context/latest/master-frontier-v6-live-model-result.json",
            {
                "ok": True,
                "classification": "master_frontier_v6_live_model_pass",
                "changedFiles": ["a.py"],
                "durationMs": 100,
                "providerCalls": 2,
                "tokenUsage": {"exact": True, "calls": 2, "total_tokens": 20},
                "checks": {"completionGatePassed": True, "terminalIntegrityVerified": True},
            },
        )
        self.write_artifact(
            "reports/context/latest/production-native-control-authority.json",
            {"status": "pass", "summary": "fixture authority is live"},
        )
        self.write_artifact(
            "reports/context/latest/master-frontier-v6-client-ui.json",
            {
                "ok": True,
                "changedFiles": [],
                "providerCalls": 1,
                "clientWidgetAcknowledged": True,
                "clientCommandArtifactVerified": True,
                "integrityProof": {"status": "verified"},
            },
        )
        self.write_artifact(
            "reports/windows/latest/hot-shell-proof-result.json",
            {"ok": True},
        )
        self.write_artifact(
            "reports/android/wake-shell-v2/latest-shell-v2-wake-loop.json",
            {
                "status": "pass",
                "durationMs": 200,
                "policy": {"wakeThreshold": 0.999},
                "phases": [{"label": "stimulus", "durationMs": 50}],
            },
        )

    def test_canonical_journey_ids_are_stable_and_ordered(self) -> None:
        self.assertEqual(
            [journey.journey_id for journey in evaluation.JOURNEYS],
            ["repository-agent", "electron-browser-agent", "android-voice-agent"],
        )

    def test_historical_pass_becomes_stale_after_an_invalidator_changes(self) -> None:
        invalidator = "owned/repository_adapter.py"
        self.write_registry({
            "master-frontier-v6-live-model-self-host": [invalidator],
        })
        artifact = self.write_artifact(
            "reports/context/latest/master-frontier-v6-live-model-result.json",
            {
                "ok": True,
                "classification": "master_frontier_v6_live_model_pass",
                "changedFiles": ["a.py"],
            },
        )
        invalidator_path = self.root / invalidator
        invalidator_path.parent.mkdir(parents=True)
        invalidator_path.write_text("changed\n", encoding="utf-8")
        old_time = 1_700_000_000
        os.utime(artifact, (old_time, old_time))
        os.utime(invalidator_path, (old_time + 10, old_time + 10))

        _, promises = evaluation.registry()
        result = evaluation.evidence_result(evaluation.JOURNEYS[0].evidence[0], promises)

        self.assertEqual(result["observedStatus"], "pass")
        self.assertEqual(result["status"], "stale")
        self.assertFalse(result["fresh"])
        self.assertEqual(result["failureClass"], "evidence_invalidated")
        self.assertEqual(result["invalidatedByPaths"], [invalidator])

    def test_missing_artifacts_emit_typed_blockers_and_null_metrics(self) -> None:
        report = evaluation.build_report()

        for journey in report["journeys"].values():
            with self.subTest(journey=journey["id"]):
                self.assertEqual(journey["status"], "blocked")
                self.assertEqual(journey["failureClass"], "evidence_artifact_missing")
                self.assertEqual(journey["blocker"]["failureClass"], "evidence_artifact_missing")
                self.assertTrue(journey["failureStage"])
                for metric in journey["metrics"]["missingMetrics"]:
                    value = journey["metrics"].get(metric)
                    if value is None and journey["metrics"].get("voice") is not None:
                        value = journey["metrics"]["voice"].get(metric)
                    self.assertIn(value, (None, {}))

    def test_evaluation_completion_does_not_claim_product_readiness(self) -> None:
        self.write_passing_artifacts()

        report = evaluation.build_report()

        self.assertTrue(report["evaluationCompleted"])
        self.assertFalse(report["ready"])
        self.assertEqual(report["journeys"]["repository-agent"]["status"], "pass")
        self.assertEqual(report["journeys"]["electron-browser-agent"]["status"], "inconclusive")
        self.assertEqual(report["journeys"]["android-voice-agent"]["status"], "inconclusive")
        self.assertTrue(any(journey["metrics"]["missingMetrics"] for journey in report["journeys"].values()))

    def test_android_device_absence_is_a_typed_access_prerequisite(self) -> None:
        self.write_passing_artifacts()
        self.write_artifact(
            "reports/android/wake-shell-v2/latest-shell-v2-wake-loop.json",
            {
                "status": "fail",
                "failureClass": "android_device_missing",
                "durationMs": 200,
                "phases": [{"label": "windows_hot_op", "durationMs": 50}],
            },
        )

        journey = evaluation.build_report()["journeys"]["android-voice-agent"]

        self.assertEqual(journey["status"], "fail")
        self.assertEqual(journey["failureClass"], "android_device_missing")
        self.assertEqual(journey["blocker"]["kind"], "missing-access")
        self.assertIn("Windows bridge", journey["blocker"]["prerequisite"])
        self.assertEqual(
            evaluation.build_report()["highestPriorityBottleneck"]["contractClass"],
            "runtime-access",
        )


if __name__ == "__main__":
    unittest.main()
