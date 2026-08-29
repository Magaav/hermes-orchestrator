#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier.v6 import contracts, evidence, transition  # noqa: E402


class FakeKernel:
    def __init__(self) -> None:
        self.evidence = evidence.EvidenceStore()


class TransitionTests(unittest.TestCase):
    def projection(self, observed: dict, *, operation_id: str = "op", ok: bool = True) -> list[dict]:
        kernel = FakeKernel()
        receipt = contracts.receipt({"id": f"rcpt:{operation_id}", "op": operation_id, "ok": ok, "state": "completed" if ok else "failed", "observed": observed})
        item = kernel.evidence.put(kind="operation.receipt", subject=f"operation:{operation_id}", summary=receipt["state"], detail=receipt)
        return transition.project(kernel, [{"id": operation_id}], [receipt], [item])

    def test_small_terminal_or_repository_write_projects_once(self) -> None:
        values = self.projection({"exit_code": 0, "changed_files": ["README.md"]}, operation_id="repo-patch")
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]["kind"], "operation.transition")
        self.assertIn("README.md", values[0]["payload"]["content"])

    def test_large_windows_result_uses_compact_model_projection(self) -> None:
        values = self.projection({"raw": "x" * 100_000, "model_projection": {"window": "Notepad", "selected": True}}, operation_id="uia-select")
        self.assertEqual(values[0]["payload"]["pointer"], "/observed/model_projection")
        self.assertIn("Notepad", values[0]["payload"]["content"])
        self.assertNotIn("x" * 100, values[0]["payload"]["content"])

    def test_failed_action_projects_bounded_recovery_once(self) -> None:
        values = self.projection({
            "failureClassification": "browser_ref_missing",
            "recovery": {"selectorMatches": [{"actionLocator": "#composer", "name": "Escrever mensagem"}]},
        }, operation_id="open-laura", ok=False)
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]["kind"], "operation.transition")
        self.assertIn("One-shot recovery receipt", values[0]["summary"])
        self.assertIn("#composer", values[0]["payload"]["content"])

    def test_large_failed_action_without_model_projection_never_throws(self) -> None:
        values = self.projection({
            "raw": "x" * 100_000,
            "failedStepIndex": 1,
            "failedAction": "set_value",
            "failedLocator": "text=Type a message",
            "recovery": {"selectorMatches": [{"actionLocator": "#composer"}]},
        }, operation_id="failed-large", ok=False)
        self.assertEqual(len(values), 1)
        self.assertLess(len(values[0]["payload"]["content"]), transition.MODEL_PROJECTION_CHARS)
        self.assertIn("failedStepIndex", values[0]["payload"]["content"])
        self.assertNotIn("x" * 100, values[0]["payload"]["content"])

    def test_consume_discards_transition_but_retains_capability_schema(self) -> None:
        active = {
            "cap": {"kind": "capability.detail", "id": "cap"},
            "post": {"kind": "operation.transition", "id": "post"},
            "lens": {"kind": "operation.receipt", "id": "lens"},
        }
        self.assertEqual(transition.consume(active), 2)
        self.assertEqual(list(active), ["cap"])


if __name__ == "__main__":
    unittest.main()
