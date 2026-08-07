from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from master_frontier import event_integrity  # noqa: E402


def events() -> list[dict]:
    return [
        {"seq": 1, "type": "llm.inference.started", "summary": "head started", "created_at": 100},
        {"seq": 2, "type": "semantic.decision", "summary": "inspect source", "created_at": 101},
        {"seq": 3, "type": "command.started", "summary": "file.read_bounded", "created_at": 102},
        {"seq": 4, "type": "evidence.received", "summary": "bounded source evidence", "created_at": 103},
        {"seq": 5, "type": "gate.decision", "summary": "evidence sufficient", "created_at": 104},
        {"seq": 6, "type": "answer.final", "summary": "supported answer", "created_at": 105},
    ]


class EventIntegrityExperimentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events = events()
        self.ledger = event_integrity.seal("run-fixture", self.events)
        self.anchor = event_integrity.anchor(self.ledger)

    def assert_detected(self, ledger: dict, failure_prefix: str) -> None:
        result = event_integrity.verify(ledger, trusted_anchor=self.anchor)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any(item.startswith(failure_prefix) for item in result["failures"]),
            result,
        )

    def test_clean_real_shaped_run_passes_three_channel_verification(self) -> None:
        result = event_integrity.verify(self.ledger, trusted_anchor=self.anchor)
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"], "event-integrity pass 6/6/0")

    def test_tampered_summary_evades_current_count_but_chain_detects_it(self) -> None:
        tampered_events = copy.deepcopy(self.events)
        tampered_events[3]["summary"] = "fabricated evidence"
        current = event_integrity.legacy_projection(tampered_events)
        self.assertTrue(event_integrity.legacy_projection_self_consistent(current))

        tampered = copy.deepcopy(self.ledger)
        tampered["slots"][3]["event"]["summary"] = "fabricated evidence"
        self.assert_detected(tampered, "event:4")

    def test_deleted_and_renumbered_event_evades_current_count_but_anchor_detects_it(self) -> None:
        shortened = copy.deepcopy(self.events)
        shortened.pop(2)
        for seq, event in enumerate(shortened, start=1):
            event["seq"] = seq
        current = event_integrity.legacy_projection(shortened)
        self.assertTrue(event_integrity.legacy_projection_self_consistent(current))

        resealed = event_integrity.seal("run-fixture", shortened)
        self.assert_detected(resealed, "anchor:declared")

    def test_suffix_truncation_requires_external_anchor(self) -> None:
        shortened = self.events[:-1]
        resealed = event_integrity.seal("run-fixture", shortened)
        self.assertTrue(event_integrity.verify(resealed)["ok"])
        self.assert_detected(resealed, "anchor:declared")

    def test_declared_withholding_is_visible_and_verifiable(self) -> None:
        ledger = event_integrity.seal("run-fixture", self.events, withheld_sequences=[4])
        result = event_integrity.verify(ledger, trusted_anchor=event_integrity.anchor(ledger))
        self.assertTrue(result["ok"])
        self.assertEqual((result["produced"], result["declared"], result["withheld"]), (5, 6, 1))
        self.assertNotIn("event", ledger["slots"][3])

    def test_clearing_withheld_status_cannot_conceal_the_slot(self) -> None:
        ledger = event_integrity.seal("run-fixture", self.events, withheld_sequences=[4])
        trusted = event_integrity.anchor(ledger)
        ledger["slots"][3]["status"] = "present"
        ledger["slots"][3].pop("marker", None)
        self.assertFalse(event_integrity.verify(ledger, trusted_anchor=trusted)["ok"])

    def test_bounds_and_sequence_contract_fail_closed(self) -> None:
        with self.assertRaises(event_integrity.EventIntegrityError) as raised:
            event_integrity.seal("run-fixture", [{**self.events[0], "seq": 2}])
        self.assertEqual(raised.exception.code, "event_seq_gap")
        with self.assertRaises(event_integrity.EventIntegrityError) as raised:
            event_integrity.seal("run-fixture", [self.events[0]] * (event_integrity.MAX_EVENTS + 1))
        self.assertEqual(raised.exception.code, "event_ledger_bound_exceeded")


if __name__ == "__main__":
    unittest.main()
