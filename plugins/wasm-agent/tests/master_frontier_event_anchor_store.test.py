from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from master_frontier import event_anchor_store, event_integrity  # noqa: E402


def anchor(run_id: str, count: int) -> dict:
    events = [
        {"seq": seq, "type": "evidence.received", "summary": f"event-{seq}", "created_at": seq}
        for seq in range(1, count + 1)
    ]
    return event_integrity.anchor(event_integrity.seal(run_id, events))


class EventAnchorStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "anchors.sqlite3"
        self.store = event_anchor_store.EventAnchorStore(self.path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_append_chain_idempotency_and_finalization(self) -> None:
        first = self.store.append(user_id="user-1", run_id="run-1", anchor=anchor("run-1", 2), created_at=10)
        self.assertEqual((first["checkpoint"], first["declared"], first["idempotent"]), (1, 2, False))
        retry = self.store.append(user_id="user-1", run_id="run-1", anchor=anchor("run-1", 2), created_at=99)
        self.assertTrue(retry["idempotent"])
        second = self.store.append(
            user_id="user-1", run_id="run-1", anchor=anchor("run-1", 4), final=True, created_at=20,
        )
        self.assertEqual((second["checkpoint"], second["declared"], second["final"]), (2, 4, True))
        verified = self.store.verify_chain(user_id="user-1", run_id="run-1")
        self.assertTrue(verified["ok"])
        self.assertEqual((verified["checkpoints"], verified["declared"], verified["final"]), (2, 4, True))
        with self.assertRaises(event_anchor_store.EventAnchorStoreError) as raised:
            self.store.append(user_id="user-1", run_id="run-1", anchor=anchor("run-1", 5))
        self.assertEqual(raised.exception.code, "anchor_run_finalized")

    def test_declared_count_must_advance_and_scope_must_match(self) -> None:
        self.store.append(user_id="user-1", run_id="run-1", anchor=anchor("run-1", 3))
        with self.assertRaises(event_anchor_store.EventAnchorStoreError) as raised:
            self.store.append(user_id="user-1", run_id="run-1", anchor=anchor("run-1", 2))
        self.assertEqual(raised.exception.code, "anchor_declared_not_monotonic")
        with self.assertRaises(event_anchor_store.EventAnchorStoreError) as raised:
            self.store.append(user_id="user-1", run_id="run-2", anchor=anchor("run-1", 4))
        self.assertEqual(raised.exception.code, "anchor_scope_mismatch")

    def test_database_triggers_reject_update_and_delete(self) -> None:
        self.store.append(user_id="user-1", run_id="run-1", anchor=anchor("run-1", 2))
        with sqlite3.connect(self.path) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE event_anchor SET declared = 1")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM event_anchor")

    def test_scope_hashing_and_lookup_isolation(self) -> None:
        self.store.append(user_id="user-1", run_id="run-1", anchor=anchor("run-1", 2))
        self.assertIsNotNone(self.store.latest(user_id="user-1", run_id="run-1"))
        self.assertIsNone(self.store.latest(user_id="user-2", run_id="run-1"))
        with sqlite3.connect(self.path) as connection:
            stored = connection.execute("SELECT principal_hash, run_hash FROM event_anchor").fetchone()
        self.assertNotIn("user-1", stored)
        self.assertNotIn("run-1", stored)

    def test_chain_verifier_detects_privileged_row_corruption(self) -> None:
        self.store.append(user_id="user-1", run_id="run-1", anchor=anchor("run-1", 2), created_at=10)
        self.store.append(user_id="user-1", run_id="run-1", anchor=anchor("run-1", 4), created_at=20)
        with sqlite3.connect(self.path) as connection:
            connection.execute("DROP TRIGGER event_anchor_no_update")
            connection.execute("UPDATE event_anchor SET head = ? WHERE checkpoint = 1", ("f" * 64,))
        verified = self.store.verify_chain(user_id="user-1", run_id="run-1")
        self.assertFalse(verified["ok"])
        self.assertIn("digest:1", verified["failures"])

    def test_missing_store_and_default_path_are_explicit(self) -> None:
        missing = self.store.verify_chain(user_id="user-1", run_id="run-1")
        self.assertEqual((missing["status"], missing["ok"]), ("missing", False))
        expected = Path("/private") / "event-anchors" / "sqlite" / "mf_event_anchors.sqlite3"
        self.assertEqual(event_anchor_store.default_path("/private"), expected)


if __name__ == "__main__":
    unittest.main()
