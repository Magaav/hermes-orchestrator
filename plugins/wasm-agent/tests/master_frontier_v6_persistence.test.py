#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier.v6 import persistence  # noqa: E402


class V6PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.sqlite3"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def route():
        return {"route_id": "fixture.ui", "owner": "fixture", "workspace_root": "/workspace", "allowed_read_roots": ["/workspace"], "caps": ["repo.read"]}

    def test_round_trip_is_scope_and_digest_bound(self) -> None:
        snapshot = {"schema": persistence.SNAPSHOT_SCHEMA, "kernel": {"large": "x" * 100_000}, "discovered": ["repo.read"]}
        ref = persistence.save(
            self.connect, user_id="u1", session_id="s1", route=self.route(),
            run_id="run-1", turn_id="turn-1", snapshot=snapshot,
        )
        loaded = persistence.load(
            self.connect, user_id="u1", session_id="s1", route=self.route(),
            source_run_id="run-1", expected_sha256=ref["sha256"],
        )
        self.assertEqual(loaded, snapshot)
        with self.assertRaisesRegex(persistence.PersistenceError, "v6_checkpoint_not_found"):
            persistence.load(self.connect, user_id="u2", session_id="s1", route=self.route(), source_run_id="run-1")
        stale = {**self.route(), "caps": ["repo.read", "repo.edit"]}
        with self.assertRaisesRegex(persistence.PersistenceError, "v6_checkpoint_route_stale"):
            persistence.load(self.connect, user_id="u1", session_id="s1", route=stale, source_run_id="run-1")
        mcp_stale = {**self.route(), "mcp": {"servers": [{"id": "github", "tools": ["get_issue"], "mode": "read-only"}]}}
        with self.assertRaisesRegex(persistence.PersistenceError, "v6_checkpoint_route_stale"):
            persistence.load(self.connect, user_id="u1", session_id="s1", route=mcp_stale, source_run_id="run-1")

    def test_tampered_blob_is_rejected(self) -> None:
        ref = persistence.save(
            self.connect, user_id="u1", session_id="s1", route=self.route(), run_id="run-1", turn_id="turn-1",
            snapshot={"schema": persistence.SNAPSHOT_SCHEMA, "kernel": {}, "discovered": []},
        )
        with self.connect() as conn:
            conn.execute("UPDATE master_frontier_v6_snapshot_tb SET snapshot_sha256 = ? WHERE run_id = ?", ("0" * 64, "run-1"))
        with self.assertRaisesRegex(persistence.PersistenceError, "v6_checkpoint_digest_mismatch"):
            persistence.load(
                self.connect, user_id="u1", session_id="s1", route=self.route(),
                source_run_id="run-1", expected_sha256=ref["sha256"],
            )


if __name__ == "__main__":
    unittest.main()
