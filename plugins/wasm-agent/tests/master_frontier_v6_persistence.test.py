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

    def seed_terminal_run(self, *, run_id="run-terminal", user_id="u1", session_id="s1", route_id="fixture.ui", reply="Verified Browser result.", gate=True, proof=True) -> None:
        final = {
            "route_id": route_id, "reply": reply,
            "local_tools": [{"capability": "client.browser.inspect", "status": "acknowledged", "ok": True}],
            "evidence": [{"proof": ["native.web_surface.status"] if proof else []}],
        }
        with self.connect() as conn:
            conn.execute("CREATE TABLE agent_run_tb (run_id TEXT, turn_id TEXT, user_id TEXT, session_id TEXT, protocol TEXT, status TEXT, created_at INTEGER, final_json TEXT)")
            conn.execute("CREATE TABLE agent_run_event_tb (run_id TEXT, user_id TEXT, session_id TEXT, type TEXT, payload_json TEXT)")
            conn.execute(
                "INSERT INTO agent_run_tb VALUES (?,?,?,?,?,?,?,?)",
                (run_id, "turn-terminal", user_id, session_id, "v6", "completed", 1000, json.dumps(final)),
            )
            if gate:
                conn.execute(
                    "INSERT INTO agent_run_event_tb VALUES (?,?,?,?,?)",
                    (run_id, user_id, session_id, "gate.decision", json.dumps({"status": "terminal_result"})),
                )

    def test_latest_terminal_evidence_requires_exact_transcript_and_scope_binding(self) -> None:
        self.seed_terminal_run()
        found = persistence.latest_terminal_evidence(
            self.connect, user_id="u1", session_id="s1", route_id="fixture.ui",
            exclude_run_id="run-current", assistant_content="Verified Browser result.",
        )
        self.assertEqual(found["run_id"], "run-terminal")
        self.assertEqual(found["capabilities"], ["client.browser.inspect"])
        self.assertEqual(found["proof"], ["native.web_surface.status"])
        for changes in (
            {"user_id": "u2"}, {"session_id": "s2"}, {"route_id": "fixture.other"},
            {"assistant_content": "Different assistant text."}, {"exclude_run_id": "run-terminal"},
        ):
            arguments = {
                "user_id": "u1", "session_id": "s1", "route_id": "fixture.ui",
                "exclude_run_id": "run-current", "assistant_content": "Verified Browser result.",
                **changes,
            }
            self.assertIsNone(persistence.latest_terminal_evidence(self.connect, **arguments))

    def test_latest_terminal_evidence_rejects_missing_gate_or_proof(self) -> None:
        for gate, proof in ((False, True), (True, False)):
            with self.subTest(gate=gate, proof=proof):
                self.temp.cleanup()
                self.temp = tempfile.TemporaryDirectory()
                self.path = Path(self.temp.name) / "state.sqlite3"
                self.seed_terminal_run(gate=gate, proof=proof)
                self.assertIsNone(persistence.latest_terminal_evidence(
                    self.connect, user_id="u1", session_id="s1", route_id="fixture.ui",
                    exclude_run_id="run-current", assistant_content="Verified Browser result.",
                ))


if __name__ == "__main__":
    unittest.main()
