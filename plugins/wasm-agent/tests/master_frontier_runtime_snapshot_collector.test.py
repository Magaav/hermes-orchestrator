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

from master_frontier import runtime_snapshot_collector as collector


class RuntimeSnapshotCollectorTests(unittest.TestCase):
    def database(self, root: Path) -> Path:
        path = root / "wa.sqlite3"
        connection = sqlite3.connect(path)
        connection.execute("""CREATE TABLE agent_run_tb (
            user_id TEXT NOT NULL, status TEXT NOT NULL, created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL, terminal_at INTEGER NOT NULL,
            request_summary_json TEXT NOT NULL
        )""")
        rows = [
            ("u1", "completed", 1000, 2000, 2000, json.dumps({"route_id": "route.fixture"})),
            ("u1", "failed", 2100, 3000, 3000, json.dumps({"envelope": {"route_id": "route.fixture"}})),
            ("u1", "completed", 3100, 4000, 4000, json.dumps({"route_id": "route.other", "objective": "secret prompt"})),
            ("u2", "completed", 4100, 5000, 5000, json.dumps({"route_id": "route.fixture"})),
        ]
        connection.executemany("INSERT INTO agent_run_tb VALUES (?,?,?,?,?,?)", rows)
        connection.commit(); connection.close()
        return path

    def test_collects_only_scoped_aggregates_and_opaque_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = collector.collect(
                self.database(Path(tmp)), user_id="u1", route_id="route.fixture",
                entity_id="fixture", entity_kind="agent", now_ms=10_000,
            )
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["counters"], {"active": 0, "completed": 1, "failed": 1, "runs": 2})
        self.assertEqual(result["unknowns"], [{"code": "live_state_not_collected", "field": "status"}])
        self.assertEqual(len(result["proof_refs"]), 1)
        serialized = json.dumps(result)
        for forbidden in ("u1", "u2", "secret prompt", "wa.sqlite3", "route.other"):
            self.assertNotIn(forbidden, serialized)

    def test_unknown_entity_stays_fresh_but_unobserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = collector.collect(
                self.database(Path(tmp)), user_id="u1", route_id="route.missing",
                entity_id="missing", entity_kind="agent", now_ms=10_000,
            )
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["counters"]["runs"], 0)
        self.assertIn({"code": "entity_not_observed", "field": "run_history"}, result["unknowns"])
        self.assertTrue(result["freshness"]["trusted"])

    def test_missing_store_and_schema_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(collector.CollectorError, "runtime_store_unavailable"):
                collector.collect(root / "missing.sqlite3", user_id="u1", route_id="r", entity_id="e", entity_kind="agent", now_ms=1)
            bad = root / "bad.sqlite3"; sqlite3.connect(bad).close()
            with self.assertRaisesRegex(collector.CollectorError, "runtime_store_schema_invalid"):
                collector.collect(bad, user_id="u1", route_id="r", entity_id="e", entity_kind="agent", now_ms=1)

    def test_database_remains_writable_by_owner_after_read_only_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.database(Path(tmp))
            collector.collect(path, user_id="u1", route_id="route.fixture", entity_id="fixture", entity_kind="agent", now_ms=10_000)
            connection = sqlite3.connect(path)
            connection.execute("INSERT INTO agent_run_tb VALUES (?,?,?,?,?,?)", ("u1", "completed", 1, 1, 1, '{}'))
            connection.commit(); connection.close()


if __name__ == "__main__":
    unittest.main()
