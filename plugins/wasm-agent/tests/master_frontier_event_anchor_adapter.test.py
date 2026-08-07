from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from master_frontier import event_anchor_adapter, event_anchor_store, event_integrity, persistence  # noqa: E402


def events(count: int, *, terminal: bool = False) -> list[dict]:
    rows = [
        {"seq": seq, "type": "evidence.received", "summary": f"event-{seq}", "created_at": seq}
        for seq in range(1, count + 1)
    ]
    if terminal:
        rows[-1]["type"] = "run.final"
    return rows


class EventAnchorAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "anchors.sqlite3"
        self.store = event_anchor_store.EventAnchorStore(self.path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_config_is_disabled_by_default_and_resolves_private_path(self) -> None:
        value = event_anchor_adapter.config(self.root, environ={})
        self.assertFalse(value["enabled"])
        self.assertEqual(value["path"], event_anchor_store.default_path(self.root))
        enabled = event_anchor_adapter.config(self.root, environ={
            event_anchor_adapter.FLAG: "true",
            event_anchor_adapter.PATH_ENV: "custom/anchors.sqlite3",
            event_anchor_adapter.INTERVAL_ENV: "8",
        })
        self.assertTrue(enabled["enabled"])
        self.assertEqual(enabled["path"], self.root / "custom/anchors.sqlite3")
        self.assertEqual(enabled["interval"], 8)

    def test_disabled_and_non_interval_paths_do_not_open_store(self) -> None:
        disabled = event_anchor_adapter.persist(
            adapter_config={"enabled": False},
            user_id="u",
            run_id="r",
            events=events(4),
            store=self.store,
        )
        self.assertEqual(disabled["status"], "disabled")
        skipped = event_anchor_adapter.persist(
            adapter_config={"enabled": True, "path": self.path, "interval": 4},
            user_id="u",
            run_id="r",
            events=events(3),
            store=self.store,
        )
        self.assertEqual((skipped["status"], skipped["next_checkpoint"]), ("skipped", 4))
        self.assertFalse(self.path.exists())

    def test_interval_checkpoint_then_terminal_finalization(self) -> None:
        value = {"enabled": True, "path": self.path, "interval": 4}
        first = event_anchor_adapter.persist(
            adapter_config=value,
            user_id="u",
            run_id="r",
            events=events(4),
            store=self.store,
            created_at=10,
        )
        self.assertEqual((first["status"], first["checkpoint"], first["terminal"]), ("stored", 1, False))
        final = event_anchor_adapter.persist(
            adapter_config=value,
            user_id="u",
            run_id="r",
            events=events(5, terminal=True),
            store=self.store,
            created_at=20,
        )
        self.assertEqual((final["status"], final["checkpoint"], final["terminal"]), ("stored", 2, True))
        verified = self.store.verify_chain(user_id="u", run_id="r")
        self.assertTrue(verified["ok"])
        self.assertTrue(verified["final"])

    def test_terminal_retry_is_exactly_idempotent(self) -> None:
        value = {"enabled": True, "path": self.path, "interval": 16}
        first = event_anchor_adapter.persist(
            adapter_config=value,
            user_id="u",
            run_id="r",
            events=events(3, terminal=True),
            store=self.store,
            created_at=10,
        )
        retry = event_anchor_adapter.persist(
            adapter_config=value,
            user_id="u",
            run_id="r",
            events=events(3, terminal=True),
            store=self.store,
            created_at=99,
        )
        self.assertFalse(first["idempotent"])
        self.assertTrue(retry["idempotent"])
        self.assertEqual(self.store.verify_chain(user_id="u", run_id="r")["checkpoints"], 1)

    def test_invalid_event_sequence_returns_typed_failure(self) -> None:
        rows = events(3)
        rows[1]["seq"] = 9
        failed = event_anchor_adapter.persist(
            adapter_config={"enabled": True, "path": self.path, "interval": 1},
            user_id="u",
            run_id="r",
            events=rows,
            store=self.store,
        )
        self.assertEqual((failed["status"], failed["ok"], failed["code"]), ("failed", False, "event_seq_gap"))

    def test_event_bound_failure_is_explicit_and_does_not_truncate(self) -> None:
        failed = event_anchor_adapter.persist(
            adapter_config={"enabled": True, "path": self.path, "interval": 1},
            user_id="u",
            run_id="r",
            events=events(event_integrity.MAX_EVENTS + 1),
            terminal=True,
            store=self.store,
        )
        self.assertEqual(failed["code"], "event_ledger_bound_exceeded")
        self.assertEqual(failed["events"], event_integrity.MAX_EVENTS + 1)
        self.assertFalse(self.path.exists())

    def test_post_commit_hook_is_zero_work_when_disabled(self) -> None:
        loaded = False

        def load_events():
            nonlocal loaded
            loaded = True
            return []

        result = persistence.anchor_committed_event(
            private_state_root=self.root,
            run={"user_id": "u", "run_id": "r"},
            event={"run_id": "r", "seq": 1, "type": "run.started"},
            load_events=load_events,
            environ={},
        )
        self.assertIsNone(result)
        self.assertFalse(loaded)

    def test_private_state_root_supports_lightweight_server_fixture(self) -> None:
        fallback = self.root / "fallback"
        self.assertEqual(persistence.private_state_root(object(), fallback), fallback)
        self.assertEqual(
            persistence.private_state_root(type("Server", (), {"state_dir": self.root})(), fallback),
            self.root,
        )

    def test_post_commit_failure_demotes_proof_without_raising(self) -> None:
        def fail_load():
            raise RuntimeError("read unavailable")

        result = persistence.anchor_committed_event(
            private_state_root=self.root,
            run={"user_id": "u", "run_id": "r"},
            event={"run_id": "r", "seq": 1, "type": "run.final"},
            load_events=fail_load,
            environ={event_anchor_adapter.FLAG: "1"},
        )
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "event_anchor_hook_failed")
        self.assertFalse(result["anchor"]["ok"])


if __name__ == "__main__":
    unittest.main()
