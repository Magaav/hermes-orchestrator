#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_ROOT))

from master_frontier import controller_v3, cyphers_v3, token_ledger  # noqa: E402


def envelope(*, intent: str = "answer", floor: str = "route") -> dict[str, object]:
    return {
        "schema": cyphers_v3.SCHEMA,
        "objective": "preserve a useful human conversation while bounded tools run",
        "route_id": "wasm-agent.avatar-chat.ui",
        "surface": "avatar-chat",
        "route_contract": {
            "route_id": "wasm-agent.avatar-chat.ui",
            "surface": "avatar-chat",
            "workspace_root": "/local/plugins/wasm-agent",
        },
        "task_contract": {
            "intent": intent,
            "evidence_floor": floor,
            "budget": {"provider_tokens_max": 100000, "api_calls_max": 8},
        },
    }


class MasterFrontierSessionReplayTests(unittest.TestCase):
    def test_empty_token_scope_is_not_reported_as_exact_zero(self) -> None:
        summary = token_ledger.summary_from_calls([], quest_id="quest")

        self.assertFalse(summary["exact"])
        self.assertEqual(summary["status"], "empty")
        self.assertEqual(summary["provider_call_count"], 0)

    def test_conversation_finishes_without_defensive_tool_work(self) -> None:
        outcome = controller_v3.run_loop(
            envelope(),
            receiver="stub",
            complete=lambda *_: {"reply": "Yes. I am here and ready.", "usage": {"total_tokens": 12}},
            execute=lambda _action: self.fail("conversation should not require a tool"),
        )

        self.assertEqual(outcome.answer, "Yes. I am here and ready.")
        self.assertEqual(len(outcome.prompts), 1)

    def test_misselected_v3_source_investigation_cannot_finish_from_route_only(self) -> None:
        source = envelope()
        source["objective_kind"] = "source-investigation"
        responses = iter([
            {"reply": "The widget is missing.", "usage": {"total_tokens": 20}},
            {"reply": "The widget is missing.", "usage": {"total_tokens": 20}},
        ])
        with self.assertRaises(controller_v3.V3LoopError) as raised:
            controller_v3.run_loop(source, receiver="stub", complete=lambda *_: next(responses), execute=lambda _action: self.fail("route-only final should not execute a tool"))
        self.assertEqual(raised.exception.code, "proof_gate_unsatisfied")

    def test_stale_search_is_not_executed_again_with_different_words(self) -> None:
        responses = iter([
            {"reply": "@search query='token ledger'", "usage": {"total_tokens": 20}},
            {"reply": "@search query='usage accounting'", "usage": {"total_tokens": 20}},
            {"reply": "@files", "usage": {"total_tokens": 20}},
            {"reply": "The declared files provide the next bounded path.", "usage": {"total_tokens": 20}},
        ])
        executed: list[str] = []

        def execute(action: dict[str, object]) -> dict[str, object]:
            executed.append(str(action["action"]))
            if action["action"] == "code.memory.search":
                return {
                    "tool": action["action"],
                    "ok": False,
                    "result": {"ok": False, "code": "code_memory_stale", "items": []},
                }
            return {
                "tool": action["action"],
                "ok": True,
                "result": {"ok": True, "files": [{"path": "server/master_frontier/controller_v3.py", "exists": True}]},
            }

        outcome = controller_v3.run_loop(
            envelope(), receiver="stub", complete=lambda *_: next(responses), execute=execute
        )

        self.assertEqual(executed, ["code.memory.search", "lookup.files"])
        self.assertIn("next bounded path", outcome.answer)

    def test_trusted_negative_search_can_finish_an_impossible_mission_honestly(self) -> None:
        responses = iter([
            {"reply": "@search query='object-that-does-not-exist'", "usage": {"total_tokens": 20}},
            {"reply": "I searched the trusted route scope and found no matching object.", "usage": {"total_tokens": 20}},
        ])

        outcome = controller_v3.run_loop(
            envelope(floor="source"),
            receiver="stub",
            complete=lambda *_: next(responses),
            execute=lambda action: {
                "tool": action["action"],
                "ok": True,
                "result": {"ok": True, "code": "ok", "items": []},
            },
        )

        self.assertEqual(outcome.history[0]["evidence_class"], "not_found_trusted")
        self.assertTrue(outcome.history[0]["conclusive"])
        self.assertIn("no matching object", outcome.answer)

    def test_stale_search_cannot_support_a_not_found_final(self) -> None:
        responses = iter([
            {"reply": "@search query='possibly-real-object'", "usage": {"total_tokens": 20}},
            {"reply": "That object does not exist.", "usage": {"total_tokens": 20}},
            {"reply": "@symbol query='possibly-real-object'", "usage": {"total_tokens": 20}},
            {"reply": "The independent symbol lookup found no matching object in the trusted route scope.", "usage": {"total_tokens": 20}},
        ])

        def execute(action: dict[str, object]) -> dict[str, object]:
            if action["action"] == "code.memory.search":
                return {
                    "tool": action["action"],
                    "ok": False,
                    "result": {"ok": False, "code": "code_memory_stale", "items": []},
                }
            return {
                "tool": action["action"],
                "ok": True,
                "result": {"ok": True, "code": "ok", "matches": []},
            }

        outcome = controller_v3.run_loop(
            envelope(floor="source"), receiver="stub", complete=lambda *_: next(responses), execute=execute
        )

        self.assertEqual([item["evidence_class"] for item in outcome.history if item.get("operation") != "gate"], ["capability_unavailable", "not_found_trusted"])
        self.assertTrue(any(item.get("line") == "gate:proof_gate_unsatisfied" for item in outcome.history))
        self.assertIn("independent symbol lookup", outcome.answer)

    def test_invalid_action_gets_one_typed_repair_instead_of_ending_the_turn(self) -> None:
        responses = iter([
            {"reply": "@cost(extra=true)", "usage": {"total_tokens": 20}},
            {"reply": "@cost()", "usage": {"total_tokens": 20}},
            {"reply": "The visible ledger now reflects the active quest.", "usage": {"total_tokens": 20}},
        ])
        executed: list[str] = []

        outcome = controller_v3.run_loop(
            envelope(),
            receiver="stub",
            complete=lambda *_: next(responses),
            execute=lambda action: executed.append(str(action["action"])) or {
                "tool": action["action"],
                "ok": True,
                "result": {"ok": True, "token_ledger": {"provider_call_count": 2, "total_tokens": 40}},
            },
        )

        self.assertEqual(executed, ["cost.status"])
        self.assertTrue(any(item.get("line") == "gate:action_invalid" for item in outcome.history))
        self.assertIn("visible ledger", outcome.answer)

    def test_implementation_claim_without_receipts_cannot_complete(self) -> None:
        responses = iter([
            {"reply": "I fixed it.", "usage": {"total_tokens": 20}},
            {"reply": "I fixed it.", "usage": {"total_tokens": 20}},
        ])

        with self.assertRaises(controller_v3.V3LoopError) as raised:
            controller_v3.run_loop(
                envelope(intent="implementation", floor="proof"),
                receiver="stub",
                complete=lambda *_: next(responses),
                execute=lambda _action: self.fail("invalid inline edit must not execute"),
            )

        self.assertIn(raised.exception.code, {"proof_gate_unsatisfied", "cypher_action_invalid"})


if __name__ == "__main__":
    unittest.main()
