#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier import runtime_actions


class RuntimeActionsTests(unittest.TestCase):
    def authority(self) -> dict:
        return {
            "user_id": "user-a",
            "route_id": "route.a",
            "capabilities": ["runtime.inspect"],
            "entities": [{"id": "entity-a", "kind": "agent"}],
            "max_age_ms": 30_000,
        }

    def database(self, root: Path) -> Path:
        path = root / "runtime.sqlite3"
        connection = sqlite3.connect(path)
        connection.execute("""CREATE TABLE agent_run_tb (
            user_id TEXT NOT NULL, status TEXT NOT NULL, created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL, terminal_at INTEGER NOT NULL,
            request_summary_json TEXT NOT NULL
        )""")
        connection.execute("INSERT INTO agent_run_tb VALUES (?,?,?,?,?,?)", (
            "user-a", "completed", 1_000, 9_000, 9_000, json.dumps({"route_id": "route.a", "objective": "private"}),
        ))
        connection.commit(); connection.close()
        return path

    def test_schemas_exclude_host_authority_and_control(self) -> None:
        serialized = json.dumps(runtime_actions.action_schemas())
        self.assertIn(runtime_actions.SNAPSHOT_GET, serialized)
        self.assertIn(runtime_actions.PROOF_GET, serialized)
        for forbidden in ("user_id", "db_path", "control", "command", "host"):
            self.assertNotIn(forbidden, serialized)
        self.assertTrue(all(item["input_schema"]["additionalProperties"] is False for item in runtime_actions.action_schemas()))

    def test_snapshot_then_proof_resolve_under_exact_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.database(Path(tmp)); args = {"route_id": "route.a", "entity_id": "entity-a"}
            snapshot = runtime_actions.execute(runtime_actions.SNAPSHOT_GET, args, authority=self.authority(), db_path=path, now_ms=10_000)
            proof_id = snapshot["snapshot"]["p"][0]["id"]
            proof = runtime_actions.execute(runtime_actions.PROOF_GET, {**args, "proof_id": proof_id}, authority=self.authority(), db_path=path, now_ms=10_000)
        self.assertTrue(snapshot["ok"])
        self.assertEqual(proof["proof"]["proof"]["id"], proof_id)

    def test_scope_denials_happen_before_adapter_invocation(self) -> None:
        cases = [
            ({"route_id": "route.b", "entity_id": "entity-a"}, "runtime_action_route_denied"),
            ({"route_id": "route.a", "entity_id": "entity-b"}, "runtime_action_entity_denied"),
            ({"route_id": "route.a", "entity_id": "entity-a", "user_id": "injected"}, "runtime_action_arguments_invalid"),
        ]
        with patch.object(runtime_actions.runtime_snapshot_collector, "collect") as collect:
            for args, code in cases:
                with self.assertRaisesRegex(runtime_actions.ActionError, code):
                    runtime_actions.execute(runtime_actions.SNAPSHOT_GET, args, authority=self.authority(), db_path=Path("missing"), now_ms=1)
            collect.assert_not_called()

    def test_capability_and_proof_id_fail_before_adapter_invocation(self) -> None:
        denied = {**self.authority(), "capabilities": []}
        args = {"route_id": "route.a", "entity_id": "entity-a"}
        with patch.object(runtime_actions.runtime_snapshot_collector, "collect") as collect:
            with self.assertRaisesRegex(runtime_actions.ActionError, "runtime_action_capability_denied"):
                runtime_actions.execute(runtime_actions.SNAPSHOT_GET, args, authority=denied, db_path=Path("missing"), now_ms=1)
            collect.assert_not_called()
        with patch.object(runtime_actions.runtime_proof, "resolve") as resolve:
            with self.assertRaisesRegex(runtime_actions.ActionError, "runtime_action_proof_id_invalid"):
                runtime_actions.execute(runtime_actions.PROOF_GET, {**args, "proof_id": "/host/proof"}, authority=self.authority(), db_path=Path("missing"), now_ms=1)
            resolve.assert_not_called()

    def test_malformed_host_freshness_authority_fails_typed(self) -> None:
        authority = {**self.authority(), "max_age_ms": "unbounded"}
        with patch.object(runtime_actions.runtime_snapshot_collector, "collect") as collect:
            with self.assertRaisesRegex(runtime_actions.ActionError, "runtime_action_freshness_invalid"):
                runtime_actions.execute(
                    runtime_actions.SNAPSHOT_GET,
                    {"route_id": "route.a", "entity_id": "entity-a"},
                    authority=authority, db_path=Path("missing"), now_ms=1,
                )
            collect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
