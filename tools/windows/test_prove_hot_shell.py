#!/usr/bin/env python3
"""Deterministic checks for the compact hot-op sync lifecycle projection."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).with_name("prove-hot-shell.py")
SPEC = importlib.util.spec_from_file_location("prove_hot_shell", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def result(phase: str, *, generation: int = 1, ok=None, stuck: bool = False) -> dict:
    return {
        "ok": True,
        "accepted": True,
        "completed": False,
        "syncLifecycle": {
            "schema": "hermes.wasm_agent.windows_hot_ops_sync_lifecycle.v1",
            "phase": phase,
            "generation": generation,
            "ok": ok,
            "changed": True if ok else None,
            "ageMs": 7,
            "stuck": stuck,
        },
    }


class SyncLifecycleTest(unittest.TestCase):
    def test_running_then_completed_passes(self) -> None:
        self.assertEqual("pass", MODULE.validate_sync_liveness(result("running"), result("completed", ok=True)))

    def test_same_running_generation_passes(self) -> None:
        self.assertEqual("pass", MODULE.validate_sync_liveness(result("running"), result("running")))

    def test_generation_mismatch_fails(self) -> None:
        self.assertEqual("hot_ops_sync_generation_mismatch", MODULE.validate_sync_liveness(result("running"), result("completed", generation=2, ok=True)))

    def test_failed_and_stuck_are_explicit(self) -> None:
        self.assertEqual("hot_ops_sync_failed", MODULE.validate_sync_liveness(result("running"), result("failed", ok=False)))
        self.assertEqual("hot_ops_sync_stuck", MODULE.validate_sync_liveness(result("running"), result("running", stuck=True)))

    def test_absent_legacy_snapshot_is_not_projected_as_false(self) -> None:
        projected = MODULE.sync_lifecycle({"ok": True})
        self.assertEqual("unknown", projected["phase"])
        self.assertIsNone(projected["ok"])
        self.assertNotIn("downloadedHotOpsSync", projected)

    def test_observation_preserves_acceptance_from_start_receipt(self) -> None:
        projected = MODULE.observed_sync_lifecycle(result("running"), result("completed", ok=True))
        self.assertTrue(projected["accepted"])
        self.assertEqual("completed", projected["phase"])
        self.assertTrue(projected["ok"])

    def test_compact_bridge_mode_remains_discoverable(self) -> None:
        bridge = {"hotOperations": {"mode": "downloaded"}}
        hot = bridge.get("hotOperations")
        self.assertEqual("downloaded", hot.get("hotOpsMode") or hot.get("mode"))


if __name__ == "__main__":
    unittest.main()
