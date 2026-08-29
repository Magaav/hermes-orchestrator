#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier.v6 import stall_diagnostic  # noqa: E402


class V6StallDiagnosticTests(unittest.TestCase):
    def packet(self):
        return stall_diagnostic.build_packet(
            objective="open the requested UI target", phase="final_answer",
            missing=["completion:goal_action", "goal:open-target"], repeated_decisions=3,
            state={"status": "blocked", "open": [], "goals": [{
                "id": "open-target", "outcome": "requested target is open", "status": "blocked",
            }]},
            capabilities=[{
                "id": "client.widget.open", "kind": "act", "mode": "write",
                "summary": "Open a declared widget only when present in the active surface.",
                "detail": "active_widgets:none;space:space-home",
            }],
            evidence=[{
                "kind": "route.contract", "subject": "route:fixture.ui",
                "summary": "The route grants client inspection and control.", "proof": [],
            }],
            receipts=[],
            host={
                "route_id": "fixture.ui", "surface": "avatar-chat",
                "active_client": {
                    "runtime_type": "electron", "space_name": "space-home",
                    "widget_manifest": "active-surface-v1", "available_widget_ids": [],
                    "capabilities": ["control.widget.open"],
                },
            },
        )

    def test_valid_model_diagnostic_is_rendered_with_host_owned_uncertainty(self) -> None:
        packet = self.packet()
        result = stall_diagnostic.interpret({"reply": json.dumps({
            "schema": stall_diagnostic.MODEL_SCHEMA,
            "facts": ["The active client reports space-home with no available widgets."],
            "hypotheses": [{
                "cause": "The requested target is unavailable on the active surface.",
                "confidence": "high",
                "because": "The active-surface manifest reports no available widgets.",
                "next_check": "Inspect the target list for the current space.",
            }, {
                "cause": "The surface manifest may be stale.",
                "confidence": "low",
                "because": "No action receipt independently refreshed the manifest.",
                "next_check": "Refresh the read-only client manifest once.",
            }],
            "next_check": "Inspect the target list for the current space.",
        })}, packet)

        self.assertTrue(result["model_valid"])
        self.assertIn("Most likely possibilities:", result["answer"])
        self.assertIn("high confidence", result["answer"])
        self.assertIn("inferred from the recorded stall evidence", result["answer"])
        self.assertIn("I did not verify the root cause or complete the action", result["answer"])
        projected = stall_diagnostic.messages(packet)
        self.assertEqual([item["role"] for item in projected], ["system", "user"])
        self.assertIn("STALL/1", projected[1]["content"])
        self.assertLess(len(projected[1]["content"]), 48_000)

    def test_invalid_model_diagnostic_falls_back_without_retry_or_success_claim(self) -> None:
        result = stall_diagnostic.interpret({"reply": "not structured"}, self.packet())

        self.assertFalse(result["model_valid"])
        self.assertEqual(result["error"], "stall_diagnostic_response_invalid")
        self.assertIn("active client surface may not expose", result["answer"].lower())
        self.assertIn("did not complete", result["answer"].lower())

    def test_packet_remains_bounded_under_maximal_controller_inputs(self) -> None:
        repeated = "x" * 1_000
        packet = stall_diagnostic.build_packet(
            objective=repeated * 8, phase=repeated, missing=[repeated] * 40,
            repeated_decisions=999, state={
                "status": "blocked", "open": [repeated] * 200,
                "goals": [{"id": repeated, "outcome": repeated, "status": repeated}] * 40,
            },
            capabilities=[{
                "id": repeated, "kind": repeated, "mode": repeated,
                "summary": repeated, "detail": repeated,
            }] * 100,
            evidence=[{
                "kind": repeated, "subject": repeated, "summary": repeated,
                "proof": [repeated] * 40,
            }] * 100,
            receipts=[{
                "op": repeated, "ok": False, "state": repeated,
                "error": {"code": repeated, "summary": repeated}, "proof": [repeated] * 40,
            }] * 100,
            host={"active_client": {
                "runtime_type": repeated, "client_id": repeated, "space_id": repeated,
                "space_name": repeated, "widget_manifest": repeated,
                "available_widget_ids": [repeated] * 100, "capabilities": [repeated] * 100,
            }},
        )

        encoded = stall_diagnostic.messages(packet)[1]["content"].encode("utf-8")
        self.assertLess(len(encoded), 48_000)
        self.assertEqual(len(packet["capabilities"]), 16)
        self.assertEqual(len(packet["evidence"]), 8)
        self.assertEqual(len(packet["receipts"]), 8)
        self.assertEqual(packet["repeated_decisions"], 128)


if __name__ == "__main__":
    unittest.main()
