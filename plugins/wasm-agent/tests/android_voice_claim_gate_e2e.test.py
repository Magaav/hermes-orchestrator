#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools/context/prove-android-voice-readiness-claim.py"
MATRIX = ROOT / "docs/context/CLAIM_RISK_PROOF_MATRIX.json"


class AndroidVoiceClaimGateEndToEndTests(unittest.TestCase):
    def make_fixture(self, root: Path, passing: bool) -> Path:
        observed = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        refs = (
            ("production-native-control-authority", "production", "reports/context/authority.json"),
            ("windows-hot-shell-proof", "behavioral", "reports/windows/hot-shell.json"),
            ("android-shell-v2-wake-loop", "behavioral", "reports/android/wake-loop.json"),
        )
        evidence = []
        for promise_id, evidence_class, reference in refs:
            artifact = root / reference
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps({"status": "pass", "promiseId": promise_id}), encoding="utf-8")
            evidence.append({
                "promiseId": promise_id,
                "class": evidence_class,
                "ref": reference,
                "status": "pass" if passing else ("fail" if promise_id == "android-shell-v2-wake-loop" else "pass"),
                "freshness": "fresh",
                "observedAt": observed,
            })
        voice = {
            "positiveTrialCount": 3,
            "negativeTrialCount": 3,
            "duplicateWakeCount": 0,
            "falseWakeCount": 0,
            "effectiveWakeThreshold": 0.999,
            "responsivenessHealthy": True,
            "wakeToAvatarMs": 200,
            "wakeToListeningMs": 400,
            "transcriptionMs": 4000,
            "routingMs": 800,
            "acknowledgementMs": 1200,
        }
        if not passing:
            voice["wakeToAvatarMs"] = None
        readiness = {
            "runId": "fixture-android-voice",
            "journeys": {
                "android-voice-agent": {
                    "status": "pass" if passing else "fail",
                    "failureClass": None if passing else "android_device_missing",
                    "evidence": evidence,
                    "metrics": {
                        "evidenceCompleteness": {"ratio": 1.0 if passing else 0.9},
                        "unauthorizedActionCount": 0,
                        "voice": voice,
                    },
                }
            },
        }
        path = root / "readiness.json"
        path.write_text(json.dumps(readiness), encoding="utf-8")
        return path

    def run_gate(self, root: Path, readiness: Path) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        receipt = root / "receipt.json"
        report = root / "report.json"
        completed = subprocess.run(
            [
                sys.executable, str(SCRIPT), "--root", str(root), "--matrix", str(MATRIX),
                "--readiness", str(readiness), "--receipt", str(receipt), "--report", str(report),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        return completed, json.loads(report.read_text(encoding="utf-8"))

    def test_complete_fresh_installed_device_fixture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture_root = Path(temporary)
            completed, report = self.run_gate(fixture_root, self.make_fixture(fixture_root, passing=True))
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["gate"]["checks"]["independentGroups"], 3)
            self.assertTrue(all(item["passed"] for item in report["gate"]["checks"]["thresholds"]))

    def test_failed_device_fixture_is_rejected_without_metric_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture_root = Path(temporary)
            completed, report = self.run_gate(fixture_root, self.make_fixture(fixture_root, passing=False))
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(report["status"], "fail")
            self.assertIn("acceptance_threshold_failed", report["failureClasses"])
            wake_metric = next(item for item in report["gate"]["checks"]["thresholds"] if item["metric"] == "wake_to_avatar_ms")
            self.assertIsNone(wake_metric["actual"])
            self.assertFalse(wake_metric["passed"])


if __name__ == "__main__":
    unittest.main()
