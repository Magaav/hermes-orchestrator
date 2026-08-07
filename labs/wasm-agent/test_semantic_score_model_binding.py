#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from private_evaluator.semantic_score import score_answer


class SemanticScoreModelBindingTests(unittest.TestCase):
    def overlay(self, root: Path) -> Path:
        path = root / "overlay.sqlite3"
        connection = sqlite3.connect(path)
        connection.execute(
            "create table fixture_adjudication (fixture_id text primary key, split text, "
            "expected_contract_json text, expected_contract_sha256 text)"
        )
        contract = {"nonempty": True, "containsAnyGroups": [["glm-5.2"]]}
        payload = json.dumps(contract, sort_keys=True, separators=(",", ":"))
        connection.execute(
            "insert into fixture_adjudication values (?,?,?,?)",
            ("fx_model", "golden", payload, hashlib.sha256(payload.encode()).hexdigest()),
        )
        connection.commit()
        connection.close()
        return path

    def test_model_bound_group_uses_declared_candidate_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = score_answer(
                self.overlay(Path(directory)), "fx_model", "I am GPT-5.6 Sol.",
                baseline_model="frank/GLM-5.2",
                runtime_model="chatgpt/codex-subscription:gpt-5.6-sol",
            )
        self.assertTrue(result["passed"])
        self.assertTrue(result["runtimeModelBound"])
        self.assertEqual(result["checks"][-1]["property"], "runtimeModelIdentity:0")

    def test_model_bound_group_rejects_old_runtime_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = score_answer(
                self.overlay(Path(directory)), "fx_model", "I am GLM-5.2.",
                baseline_model="frank/GLM-5.2",
                runtime_model="chatgpt/codex-subscription:gpt-5.6-sol",
            )
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
