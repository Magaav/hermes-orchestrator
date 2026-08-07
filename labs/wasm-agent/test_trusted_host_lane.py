#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import json
import unittest
from pathlib import Path
from unittest import mock

import trusted_host_lane as lane


class TrustedHostLaneTests(unittest.TestCase):
    def test_digest_is_path_and_content_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runner.py").write_text("print('ok')\n", encoding="utf-8")
            first = lane.artifact_digest(root, ["runner.py"])
            (root / "runner.py").write_text("print('changed')\n", encoding="utf-8")
            self.assertNotEqual(first, lane.artifact_digest(root, ["runner.py"]))

    def test_environment_does_not_forward_arbitrary_secret(self) -> None:
        with mock.patch.dict(lane.os.environ, {"UNRELATED_SECRET": "never", "HOME": "/tmp/home"}, clear=True):
            env = lane._environment({"runtimeModel": "chatgpt/codex-subscription:gpt-5.6-sol"}, Path("/local"))
        self.assertNotIn("UNRELATED_SECRET", env)
        self.assertEqual(env["HOME"], "/tmp/home")

    def test_command_must_be_artifact_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runner.py").write_text("", encoding="utf-8")
            with self.assertRaises(lane.TrustedHostLaneError):
                lane._command(root, {"liveCommand": ["python3", "runner.py"], "trustedHostFiles": []}, root / "task.json")

    def test_codex_subscription_candidate_binds_current_closure(self) -> None:
        root = Path(__file__).resolve().parents[2]
        candidate = json.loads((
            root / "labs/wasm-agent/fixtures/master-frontier-v5-codex-subscription-candidate.json"
        ).read_text(encoding="utf-8"))
        observed = lane.artifact_digest(root, candidate["trustedHostFiles"])
        self.assertEqual(observed, candidate["adapterArtifactSha256"])
        self.assertEqual(observed, candidate["candidateDigest"])
        self.assertEqual(candidate["executionBoundary"], "trusted_host")
        self.assertIn("browser.inspect", candidate["routeCapabilities"])


if __name__ == "__main__":
    unittest.main()
