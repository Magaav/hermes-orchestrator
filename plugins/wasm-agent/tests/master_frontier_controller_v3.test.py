#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_ROOT))

from master_frontier import controller_v3, cyphers_v3  # noqa: E402


class MasterFrontierControllerV3Tests(unittest.TestCase):
    def envelope(self, *, total: int = 8000, enforcement: str = "soft") -> dict[str, object]:
        return {
            "schema": cyphers_v3.SCHEMA,
            "objective": "understand the meta-analysis widget",
            "route_id": "wasm-agent.avatar-chat.ui",
            "surface": "avatar-chat",
            "route_contract": {
                "route_id": "wasm-agent.avatar-chat.ui",
                "surface": "avatar-chat",
                "workspace_root": "/local/plugins/wasm-agent",
            },
            "task_contract": {
                "budget": {
                    "provider_tokens_max": total,
                    "api_calls_max": 6,
                    "max_output_tokens": 8192,
                    "enforcement": enforcement,
                },
            },
        }

    def test_model_leads_semantic_search_read_answer_loop(self) -> None:
        responses = iter([
            {"reply": "@search query='meta-analysis'", "usage": {"total_tokens": 320}},
            {"reply": "@read path='public/modules/meta-analysis/meta-analysis-widget.js' bytes=12000", "usage": {"total_tokens": 374}},
            {"reply": "The widget queues subjects, ranks research, checks integrity, persists results, and exports a report.", "usage": {"total_tokens": 540}},
        ])
        executed: list[str] = []

        def execute(action):
            executed.append(action["action"])
            if action["action"] == "code.memory.search":
                return {
                    "tool": action["action"],
                    "ok": True,
                    "result": {"ok": True, "items": [{"label": "File", "file_path": "public/modules/meta-analysis/meta-analysis-widget.js"}]},
                }
            return {
                "tool": action["action"],
                "ok": True,
                "result": {"ok": True, "path": action["args"]["path"], "text": "rankSubject assessIntegrity persist exportFindings"},
            }

        outcome = controller_v3.run_loop(
            self.envelope(),
            receiver="stub",
            complete=lambda *_: next(responses),
            execute=execute,
        )

        self.assertEqual(executed, ["code.memory.search", "file.read_bounded"])
        self.assertEqual(len(outcome.prompts), 3)
        self.assertEqual(len(outcome.history), 2)
        self.assertIn("queues subjects", outcome.answer)
        self.assertIn("search(query,limit) read(path,bytes,offset,length)", outcome.prompts[0])
        self.assertNotIn("q=code.memory.search", outcome.prompts[0])
        self.assertIn("file path=public/modules/meta-analysis/meta-analysis-widget.js", outcome.prompts[1])
        self.assertIn("rankSubject", outcome.prompts[2])
        self.assertLess(sum(cyphers_v3.estimate_tokens(prompt) for prompt in outcome.prompts), 1200)

    def test_identical_semantic_operation_is_blocked_without_reexecution(self) -> None:
        reply = {"reply": "@search query='missing-symbol'", "usage": {"total_tokens": 100}}
        executions = 0

        def execute(action):
            nonlocal executions
            executions += 1
            return {"tool": action["action"], "ok": True, "result": {"ok": True, "items": []}}

        with self.assertRaises(controller_v3.V3LoopError) as raised:
            controller_v3.run_loop(self.envelope(), receiver="stub", complete=lambda *_: reply, execute=execute)

        self.assertEqual(raised.exception.code, "no_progress")
        self.assertEqual(executions, 1)
        self.assertEqual(len(raised.exception.usages), 3)
        self.assertTrue(raised.exception.checkpoint["evidence"])

    def test_duplicate_operation_gets_typed_repair_and_can_be_replaced(self) -> None:
        responses = iter([
            {"reply": "@search query='missing-symbol'", "usage": {"total_tokens": 100}},
            {"reply": "@search query='missing-symbol'", "usage": {"total_tokens": 100}},
            {"reply": "@symbol query='Widget'", "usage": {"total_tokens": 100}},
            {"reply": "The symbol fallback found the owning widget module.", "usage": {"total_tokens": 100}},
        ])
        executed: list[str] = []

        def execute(action):
            executed.append(action["action"])
            if action["action"] == "lookup.symbol":
                return {
                    "tool": action["action"],
                    "ok": True,
                    "result": {"ok": True, "matches": [{"path": "widget.js", "line": 1}]},
                }
            return {"tool": action["action"], "ok": True, "result": {"ok": True, "items": []}}

        outcome = controller_v3.run_loop(
            self.envelope(),
            receiver="stub",
            complete=lambda *_: next(responses),
            execute=execute,
        )

        self.assertEqual(executed, ["code.memory.search", "lookup.symbol"])
        self.assertTrue(any(item.get("line") == "gate:no_progress" for item in outcome.history))
        self.assertIn("symbol fallback", outcome.answer)

    def test_semantic_operation_after_prose_continues_instead_of_finalizing(self) -> None:
        responses = iter([
            {"reply": "I need the source.\n\n@read path='widget.js' bytes=12000", "usage": {"total_tokens": 100}},
            {"reply": "The source-backed answer is complete.", "usage": {"total_tokens": 100}},
        ])
        executed: list[str] = []

        outcome = controller_v3.run_loop(
            self.envelope(),
            receiver="stub",
            complete=lambda *_: next(responses),
            execute=lambda action: executed.append(action["action"]) or {
                "tool": action["action"],
                "ok": True,
                "result": {"ok": True, "path": "widget.js", "text": "source"},
            },
        )

        self.assertEqual(executed, ["file.read_bounded"])
        self.assertIn("source-backed", outcome.answer)

    def test_pending_prose_is_rejected_until_source_evidence_exists(self) -> None:
        responses = iter([
            {"reply": "I will inspect the source next.", "usage": {"total_tokens": 100}},
            {"reply": "@search query='meta-analysis'", "usage": {"total_tokens": 100}},
            {"reply": "The evidence-backed answer is complete.", "usage": {"total_tokens": 100}},
        ])

        outcome = controller_v3.run_loop(
            self.envelope(),
            receiver="stub",
            complete=lambda *_: next(responses),
            execute=lambda action: {
                "tool": action["action"],
                "ok": True,
                "result": {"ok": True, "items": [{"label": "File", "file_path": "widget.js"}]},
            },
        )

        self.assertEqual(len(outcome.prompts), 3)
        self.assertTrue(any(item.get("line") == "gate:proof_gate_unsatisfied" for item in outcome.history))
        self.assertIn("evidence-backed", outcome.answer)

    def test_stale_memory_falls_through_to_symbol_lookup(self) -> None:
        responses = iter([
            {"reply": "@search query='Realure Meta-Analysis'", "usage": {"total_tokens": 100}},
            {"reply": "@symbol query='MetaAnalysisWidget'", "usage": {"total_tokens": 100}},
            {"reply": "The symbol fallback resolved the owner without trusting stale memory.", "usage": {"total_tokens": 100}},
        ])
        executed: list[str] = []

        def execute(action):
            executed.append(action["action"])
            if action["action"] == "code.memory.search":
                return {
                    "tool": action["action"],
                    "ok": False,
                    "result": {"ok": False, "code": "code_memory_stale", "items": []},
                }
            return {
                "tool": action["action"],
                "ok": True,
                "result": {"ok": True, "matches": [{"path": "public/modules/meta-analysis/meta-analysis-widget.js", "line": 1}]},
            }

        outcome = controller_v3.run_loop(
            self.envelope(), receiver="stub", complete=lambda *_: next(responses), execute=execute
        )

        self.assertEqual(executed, ["code.memory.search", "lookup.symbol"])
        self.assertIn("stale memory", outcome.answer)

    def test_unknown_semantic_operation_is_blocked(self) -> None:
        with self.assertRaises(controller_v3.V3LoopError) as raised:
            controller_v3.run_loop(
                self.envelope(),
                receiver="stub",
                complete=lambda *_: {"reply": "@invent target='anything'", "usage": {"total_tokens": 100}},
                execute=lambda _action: self.fail("unknown operation must not execute"),
            )

        self.assertEqual(raised.exception.code, "cypher_action_invalid")

    def test_explicit_hard_budget_blocks_before_overspending_call(self) -> None:
        calls = 0

        def complete(_envelope, _index):
            nonlocal calls
            calls += 1
            return {"reply": "@search query='meta-analysis'", "usage": {"total_tokens": 800}}

        with self.assertRaises(controller_v3.V3LoopError) as raised:
            controller_v3.run_loop(
                self.envelope(total=1000, enforcement="hard"),
                receiver="stub",
                complete=complete,
                execute=lambda action: {"tool": action["action"], "ok": True, "result": {"ok": True, "items": []}},
            )

        self.assertEqual(raised.exception.code, "provider_token_budget_exhausted")
        self.assertEqual(calls, 1)

    def test_soft_token_target_allows_synthesis(self) -> None:
        responses = iter([
            {"reply": "@search query='meta-analysis'", "usage": {"total_tokens": 900}},
            {"reply": "A complete answer after crossing the advisory target.", "usage": {"total_tokens": 500}},
        ])
        calls = 0

        def complete(_envelope, _index):
            nonlocal calls
            calls += 1
            return next(responses)

        outcome = controller_v3.run_loop(
            self.envelope(total=1000),
            receiver="stub",
            complete=complete,
            execute=lambda action: {
                "tool": action["action"],
                "ok": True,
                "result": {"ok": True, "items": [{"label": "File", "file_path": "widget.js"}]},
            },
        )

        self.assertEqual(calls, 2)
        self.assertIn("complete answer", outcome.answer)

    def test_implementation_requires_edit_test_diff_and_proof_receipts(self) -> None:
        envelope = self.envelope()
        envelope["task_contract"].update({"intent": "implementation", "evidence_floor": "proof"})
        responses = iter([
            {"reply": "@edit operations='[{\"op\":\"replace\",\"path\":\"a.py\",\"find\":\"1\",\"replace\":\"2\"}]'", "usage": {"total_tokens": 100}},
            {"reply": "I changed the file.", "usage": {"total_tokens": 100}},
            {"reply": "@test check_id='focused'", "usage": {"total_tokens": 100}},
            {"reply": "@diff", "usage": {"total_tokens": 100}},
            {"reply": "@prove run_id='wa_run_1'", "usage": {"total_tokens": 100}},
            {"reply": "Implemented and verified locally; live runtime remains unverified.", "usage": {"total_tokens": 100}},
        ])

        def execute(action):
            payloads = {
                "patch.apply_scoped": {"ok": True, "applied": True, "changed_files": ["a.py"]},
                "test.run_focused": {"ok": True, "check_id": "focused", "returncode": 0},
                "git.diff_summary": {"ok": True, "changed_files": [{"path": "a.py", "status": "M"}]},
                "proof.collect": {"ok": True, "runs": [{"run_id": "wa_run_1"}], "events": [{"type": "tool.finished"}]},
            }
            return {"tool": action["action"], "ok": True, "result": payloads[action["action"]]}

        outcome = controller_v3.run_loop(
            envelope, receiver="stub", complete=lambda *_: next(responses), execute=execute
        )

        self.assertEqual([item["operation"] for item in outcome.history if item.get("satisfying")], ["edit", "test", "diff", "prove"])
        self.assertTrue(any(item.get("line") == "gate:proof_gate_unsatisfied" for item in outcome.history))
        self.assertIn("live runtime remains unverified", outcome.answer)

    def test_conceptual_large_answer_is_not_truncated_by_completion_gate(self) -> None:
        envelope = self.envelope()
        envelope["task_contract"].update({"intent": "answer", "evidence_floor": "conceptual"})
        large_answer = "architecture evidence and explanation\n" * 1400

        outcome = controller_v3.run_loop(
            envelope,
            receiver="stub",
            complete=lambda *_: {"reply": large_answer, "usage": {"total_tokens": 12000}},
            execute=lambda _action: self.fail("conceptual answer should not need a tool"),
        )

        self.assertGreater(len(outcome.answer), 40000)
        self.assertEqual(outcome.answer, large_answer.strip())

    def test_emergency_call_ceiling_returns_resumable_checkpoint(self) -> None:
        envelope = self.envelope(total=100000)
        envelope["task_contract"]["budget"]["api_calls_max"] = 1
        envelope["budget"] = {"api_calls_absolute_max": 3, "max_output_tokens": 32768}
        calls = 0

        def complete(_envelope, _index):
            nonlocal calls
            calls += 1
            return {"reply": f"@search query='missing-{calls}'", "usage": {"total_tokens": 100}}

        with self.assertRaises(controller_v3.V3LoopError) as raised:
            controller_v3.run_loop(
                envelope,
                receiver="stub",
                complete=complete,
                execute=lambda action: {"tool": action["action"], "ok": True, "result": {"ok": True, "items": []}},
            )

        self.assertEqual(raised.exception.code, "api_call_safety_ceiling")
        self.assertEqual(calls, 3)
        self.assertEqual(raised.exception.checkpoint["provider_calls_used"], 3)
        self.assertEqual(raised.exception.checkpoint["previous_status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
