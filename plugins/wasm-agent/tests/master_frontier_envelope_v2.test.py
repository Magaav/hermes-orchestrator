#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = PLUGIN_ROOT / "server"
MODULE_PATH = SERVER_ROOT / "master_frontier" / "envelope_v2.py"

sys.path.insert(0, str(SERVER_ROOT))

spec = importlib.util.spec_from_file_location("master_frontier.envelope_v2", MODULE_PATH)
assert spec and spec.loader
envelope_v2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(envelope_v2)


class MasterFrontierEnvelopeV2Tests(unittest.TestCase):
    def envelope(self) -> dict[str, object]:
        return {
            "objective": "inspect the meta-analysis widget",
            "route_id": "wasm-agent.avatar-chat.ui",
            "surface": "avatar-chat",
        }

    def test_semantic_decision_projects_command_proposal(self) -> None:
        parsed = {
            "answer": "I need bounded source evidence first.",
            "decision": "kernel.inspect",
            "actions": [{
                "action": "kernel.inspect",
                "args": {
                    "route_id": "wasm-agent.avatar-chat.ui",
                    "inspect": ["files"],
                    "query": "meta-analysis widget",
                },
            }],
            "needs": ["file receipt"],
        }

        events = envelope_v2.decision_events(
            parsed,
            "",
            self.envelope(),
            turn_id="turn-1",
            inference_id="inf-1",
            stage="head",
        )
        types = [event["type"] for event in events]

        self.assertEqual(types, ["llm.reason.summary", "semantic.decision", "command.proposed"])
        decision = events[1]["payload"]["semantic_decision"]
        self.assertEqual(decision["intent"], "kernel.inspect")
        self.assertEqual(decision["proposed_command"]["action"], "kernel.inspect")
        self.assertEqual(decision["proposed_command"]["route_id"], "wasm-agent.avatar-chat.ui")

    def test_usage_events_keep_per_inference_and_turn_totals(self) -> None:
        events, calls = envelope_v2.inference_completed_events(
            {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14, "model": "stub"},
            [],
            turn_id="turn-1",
            inference_id="inf-1",
            stage="head",
        )
        more_events, calls = envelope_v2.inference_completed_events(
            {"input_tokens": 6, "output_tokens": 3, "total_tokens": 9, "cached_input_tokens": 2},
            calls,
            turn_id="turn-1",
            inference_id="inf-2",
            stage="head",
        )

        self.assertEqual([event["type"] for event in events], ["llm.inference.completed", "turn.usage.updated"])
        self.assertEqual(more_events[-1]["payload"]["ledger"]["inference_count"], 2)
        self.assertEqual(more_events[-1]["payload"]["ledger"]["prompt_tokens_total"], 16)
        self.assertEqual(more_events[-1]["payload"]["ledger"]["completion_tokens_total"], 7)
        self.assertEqual(more_events[-1]["payload"]["ledger"]["cached_input_tokens_total"], 2)
        self.assertEqual(more_events[-1]["payload"]["ledger"]["total_tokens"], 23)

    def test_tool_result_becomes_command_and_evidence_receipt(self) -> None:
        events = envelope_v2.command_receipt_events(
            [{
                "tool": "kernel.inspect",
                "ok": True,
                "code": "ok",
                "route_id": "wasm-agent.avatar-chat.ui",
                "summary": {"observations": [{"kind": "files", "count": 3}]},
            }],
            turn_id="turn-1",
            inference_id="inf-1",
        )

        self.assertEqual(
            [event["type"] for event in events],
            ["command.accepted", "command.dispatched", "command.started", "evidence.received"],
        )
        evidence = events[-1]["payload"]["evidence"]
        self.assertEqual(evidence["status"], "received")
        self.assertEqual(evidence["kind"], "kernel.inspect")

    def test_hard_loop_law_blocks_continuation_without_new_evidence(self) -> None:
        self.assertIsNone(
            envelope_v2.loop_violation_event(
                turn_id="turn-1",
                inference_id="inf-2",
                previous_evidence_count=1,
                current_evidence_count=2,
            )
        )

        violation = envelope_v2.loop_violation_event(
            turn_id="turn-1",
            inference_id="inf-3",
            previous_evidence_count=2,
            current_evidence_count=2,
        )

        self.assertIsNotNone(violation)
        assert violation is not None
        self.assertEqual(violation["type"], "loop_contract_violation")
        self.assertEqual(violation["payload"]["code"], "loop_contract_violation")

    def test_final_gate_and_answer_events_use_required_names(self) -> None:
        events = envelope_v2.final_gate_events(
            turn_id="turn-1",
            status="finished",
            reason="answer_from_proof",
            proof_refs=["evidence.received"],
        )
        events.extend(envelope_v2.answer_events(turn_id="turn-1", answer="Final answer."))

        self.assertEqual(
            [event["type"] for event in events],
            ["gate.started", "gate.decision", "answer.started", "answer.final"],
        )
        self.assertEqual(events[1]["payload"]["final_gate"]["allowed_answer_kind"], "answer_from_proof")


if __name__ == "__main__":
    unittest.main()
