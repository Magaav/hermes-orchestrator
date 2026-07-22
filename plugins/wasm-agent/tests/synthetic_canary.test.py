#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/wasm-agent/server"))
import synthetic_canary


class SyntheticCanaryTests(unittest.TestCase):
    def test_grant_is_exactly_objective_session_and_expiry_bound(self) -> None:
        conn = sqlite3.connect(":memory:")
        synthetic_canary.ensure_schema(conn)
        conn.execute(
            "INSERT INTO synthetic_canary_grant_tb VALUES (?, ?, ?, ?, ?)",
            (7, synthetic_canary.objective_sha256("read only"), "s1", 200, 100),
        )
        body = {"session_id": "s1", "envelope": {"objective": "read only"}}
        self.assertTrue(synthetic_canary.authorize(conn, "7", body, now=150))
        self.assertFalse(synthetic_canary.authorize(conn, "7", {**body, "session_id": "s2"}, now=150))
        self.assertFalse(synthetic_canary.authorize(conn, "7", {**body, "envelope": {"objective": "edit"}}, now=150))
        self.assertFalse(synthetic_canary.authorize(conn, "7", body, now=201))


if __name__ == "__main__":
    unittest.main()
