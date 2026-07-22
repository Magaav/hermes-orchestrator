#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier import runtime_proof, runtime_snapshot_collector


class RuntimeProofTests(unittest.TestCase):
    def database(self, root: Path) -> Path:
        path = root / "runtime.sqlite3"
        connection = sqlite3.connect(path)
        connection.execute("""CREATE TABLE agent_run_tb (
            user_id TEXT NOT NULL, status TEXT NOT NULL, created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL, terminal_at INTEGER NOT NULL,
            request_summary_json TEXT NOT NULL
        )""")
        connection.executemany("INSERT INTO agent_run_tb VALUES (?,?,?,?,?,?)", [
            ("user-a", "completed", 1_000, 9_000, 9_000, json.dumps({"route_id": "route.a", "objective": "private objective"})),
            ("user-b", "failed", 2_000, 9_500, 9_500, json.dumps({"route_id": "route.a"})),
            ("user-a", "completed", 3_000, 9_700, 9_700, json.dumps({"route_id": "route.b"})),
        ])
        connection.commit(); connection.close()
        return path

    def reference(self, path: Path) -> dict:
        snapshot = runtime_snapshot_collector.collect(
            path, user_id="user-a", route_id="route.a", entity_id="entity-a",
            entity_kind="agent", now_ms=10_000,
        )
        return snapshot["proof_refs"][0]

    def test_resolves_exact_scoped_reference_without_raw_identifiers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.database(Path(tmp)); reference = self.reference(path)
            result = runtime_proof.resolve(
                path, user_id="user-a", route_id="route.a", entity_id="entity-a",
                proof_id=reference["id"], now_ms=10_000,
            )
        self.assertEqual(result["proof"], reference)
        self.assertEqual(result["evidence"]["run_status"], "completed")
        self.assertTrue(result["freshness"]["trusted"])
        serialized = json.dumps(result)
        for forbidden in ("user-a", "user-b", "private objective", "runtime.sqlite3"):
            self.assertNotIn(forbidden, serialized)

    def test_wrong_user_route_or_entity_cannot_resolve_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.database(Path(tmp)); reference = self.reference(path)
            for scope in (
                {"user_id": "user-b", "route_id": "route.a", "entity_id": "entity-a"},
                {"user_id": "user-a", "route_id": "route.b", "entity_id": "entity-a"},
                {"user_id": "user-a", "route_id": "route.a", "entity_id": "entity-b"},
            ):
                with self.assertRaisesRegex(runtime_proof.ProofError, "runtime_proof_not_found"):
                    runtime_proof.resolve(path, proof_id=reference["id"], now_ms=10_000, **scope)

    def test_invalid_and_stale_proofs_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.database(Path(tmp)); reference = self.reference(path)
            with self.assertRaisesRegex(runtime_proof.ProofError, "runtime_proof_id_invalid"):
                runtime_proof.resolve(path, user_id="user-a", route_id="route.a", entity_id="entity-a", proof_id="/host/proof", now_ms=10_000)
            result = runtime_proof.resolve(
                path, user_id="user-a", route_id="route.a", entity_id="entity-a",
                proof_id=reference["id"], now_ms=100_000, max_age_ms=30_000,
            )
        self.assertEqual(result["freshness"]["state"], "stale")
        self.assertFalse(result["freshness"]["trusted"])

    def test_resolution_does_not_mutate_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.database(Path(tmp)); before = path.read_bytes(); reference = self.reference(path)
            runtime_proof.resolve(path, user_id="user-a", route_id="route.a", entity_id="entity-a", proof_id=reference["id"], now_ms=10_000)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
