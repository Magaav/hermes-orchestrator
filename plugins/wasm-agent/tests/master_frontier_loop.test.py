#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = PLUGIN_ROOT / "server"
LOOP_PATH = SERVER_ROOT / "master_frontier" / "loop.py"

sys.path.insert(0, str(SERVER_ROOT))

spec = importlib.util.spec_from_file_location("master_frontier.loop", LOOP_PATH)
assert spec and spec.loader
loop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loop)


class MasterFrontierLoopTests(unittest.TestCase):
    def envelope(self, objective: str = "inspect the repo and diagnose the architecture") -> dict[str, object]:
        return {
            "objective": objective,
            "route_id": "wasm-agent.avatar-chat.ui",
            "capabilities": ["repo.read", "repo.edit", "test.run", "runtime.inspect", "proof.report"],
            "task_contract": {
                "intent": "diagnosis",
                "route_id": "wasm-agent.avatar-chat.ui",
                "workspace_root": "/local/plugins/wasm-agent",
                "proof_required": ["route", "evidence", "cause", "next_action"],
                "block_codes": [],
            },
        }

    def test_states_are_codex_style_loop_spine(self) -> None:
        started = loop.start(self.envelope())

        self.assertEqual(started["states"], ["reason", "action", "observe", "critique", "decide_continue_or_finish"])
        self.assertEqual(started["state"], "reason")
        self.assertEqual(started["schema"], "hermes.wasm_agent.master_frontier.loop.v1")

    def test_repo_diagnosis_cannot_finish_with_only_route_and_tool_receipts(self) -> None:
        evaluated = loop.evaluate_completion(
            self.envelope(),
            {"answer": "Objective. Route resolved. kernel.inspect / 3 file receipts. Final ✓", "actions": []},
            "",
            local_tool_results=[{"tool": "kernel.inspect", "ok": True, "route_id": "wasm-agent.avatar-chat.ui"}],
            change_proof={"changed_files": []},
            dispatch_result=None,
        )

        self.assertEqual(evaluated["status"], "incomplete")
        self.assertEqual(evaluated["critique"]["reason"], "diagnosis_answer_missing")
        self.assertIn("cause", evaluated["critique"]["missing"])

    def test_empty_answer_never_finishes(self) -> None:
        envelope = self.envelope("hello")
        envelope["task_contract"] = {
            **envelope["task_contract"],
            "intent": "answer",
            "proof_required": ["route", "evidence", "answer"],
        }

        evaluated = loop.evaluate_completion(
            envelope,
            {"answer": "", "actions": []},
            "",
            local_tool_results=[],
            change_proof={"changed_files": []},
            dispatch_result=None,
        )

        self.assertEqual(evaluated["status"], "incomplete")
        self.assertEqual(evaluated["critique"]["reason"], "answer_missing")
        self.assertEqual(evaluated["critique"]["typed_understanding"]["status"], "insufficient")

    def test_repo_object_question_requires_typed_understanding_after_source_evidence(self) -> None:
        envelope = self.envelope("what does the reporting widget do?")
        envelope["task_contract"] = {
            **envelope["task_contract"],
            "intent": "information",
            "proof_required": ["route", "evidence", "answer"],
        }
        evaluated = loop.evaluate_completion(
            envelope,
            {
                "answer": "Source public/modules/reporting/widget.js shows the widget handles reports.\n\nCode memory proof:\n- File widget.js",
                "actions": [],
            },
            "",
            local_tool_results=[{"tool": "code.memory.search", "ok": True, "route_id": "wasm-agent.avatar-chat.ui"}],
            change_proof={"changed_files": []},
            dispatch_result=None,
        )

        self.assertEqual(evaluated["status"], "incomplete")
        self.assertEqual(evaluated["critique"]["reason"], "typed_understanding_missing")
        self.assertIn("typed_understanding", evaluated["critique"]["missing"])
        self.assertEqual(evaluated["critique"]["typed_understanding"]["reason"], "receipt_shaped_understanding")

    def test_repo_object_question_rejects_source_shows_receipt_answer(self) -> None:
        envelope = self.envelope("what does the meta-analysis widget from realure space does?")
        envelope["task_contract"] = {
            **envelope["task_contract"],
            "intent": "information",
            "proof_required": ["route", "evidence", "answer"],
        }
        bad_answer = (
            "Source public/modules/meta-analysis/meta-analysis-widget.js shows the widget ranks a queued subject, "
            "adds an Evidence Integrity/bias-risk overlay, persists the subject queue/results locally.\n\n"
            "Code memory proof:\n- Code memory search for meta-analysis returned 3 route-scoped result(s)."
        )
        evaluated = loop.evaluate_completion(
            envelope,
            {"answer": bad_answer, "actions": []},
            bad_answer,
            local_tool_results=[{"tool": "code.memory.search", "ok": True, "route_id": "wasm-agent.avatar-chat.ui"}],
            change_proof={"changed_files": []},
            dispatch_result=None,
        )

        self.assertEqual(evaluated["status"], "incomplete")
        self.assertEqual(evaluated["critique"]["reason"], "typed_understanding_missing")

    def test_repo_object_question_rejects_source_backed_understanding_receipt_answer(self) -> None:
        envelope = self.envelope("what does the meta-analysis widget from realure space does?")
        envelope["task_contract"] = {
            **envelope["task_contract"],
            "intent": "information",
            "proof_required": ["route", "evidence", "answer"],
        }
        weak_answer = (
            "The source-backed understanding is: this UI widget orchestrates a research workflow. "
            "It takes a queued or typed subject as the unit of work, flags bias/integrity signals from the returned finding text, "
            "keeps queue and result state in browser local storage. "
            "Evidence from public/modules/meta-analysis/meta-analysis-widget.js: ranks a queued subject, "
            "adds an Evidence Integrity/bias-risk overlay, persists the subject queue/results locally. "
            "This proves the source behavior; live runtime availability still needs separate runtime-scope proof when a space is named.\n\n"
            "Code memory proof:\n- Code memory search for meta-analysis returned 3 route-scoped result(s)."
        )
        evaluated = loop.evaluate_completion(
            envelope,
            {"answer": weak_answer, "actions": []},
            weak_answer,
            local_tool_results=[{"tool": "code.memory.search", "ok": True, "route_id": "wasm-agent.avatar-chat.ui"}],
            change_proof={"changed_files": []},
            dispatch_result=None,
        )

        self.assertEqual(evaluated["status"], "incomplete")
        self.assertEqual(evaluated["critique"]["reason"], "typed_understanding_missing")
        self.assertEqual(evaluated["critique"]["typed_understanding"]["reason"], "receipt_shaped_understanding")

    def test_repo_object_question_finishes_with_functional_understanding(self) -> None:
        envelope = self.envelope("what does the reporting widget do?")
        envelope["task_contract"] = {
            **envelope["task_contract"],
            "intent": "information",
            "proof_required": ["route", "evidence", "answer"],
        }
        evaluated = loop.evaluate_completion(
            envelope,
            {
                "answer": (
                    "The reporting widget queues report subjects, sends the selected subject to the research node, "
                    "renders ranked findings, stores the current queue/results locally, flags missing disclosure fields, "
                    "and exports the findings as a browser-readable report. The source evidence proves the widget behavior; "
                    "it does not prove that a live runtime has already produced fresh results."
                ),
                "actions": [],
            },
            "",
            local_tool_results=[{"tool": "code.memory.search", "ok": True, "route_id": "wasm-agent.avatar-chat.ui"}],
            change_proof={"changed_files": []},
            dispatch_result=None,
        )

        self.assertEqual(evaluated["status"], "finished")
        self.assertEqual(evaluated["critique"]["typed_understanding"]["status"], "sufficient")

    def test_repo_object_question_finishes_with_plain_behavior_answer(self) -> None:
        envelope = self.envelope("what does the meta-analysis widget from realure space does?")
        envelope["task_contract"] = {
            **envelope["task_contract"],
            "intent": "information",
            "proof_required": ["route", "evidence", "answer"],
        }
        answer = (
            "The meta-analysis widget is a browser-side research workflow panel. "
            "It takes a queued or typed subject as the unit of work, flags bias/integrity signals "
            "from the returned finding text, keeps queue and result state in browser local storage. "
            "I do not have live realure runtime proof in this turn."
        )
        evaluated = loop.evaluate_completion(
            envelope,
            {"answer": answer, "actions": []},
            answer,
            local_tool_results=[{"tool": "code.memory.search", "ok": True, "route_id": "wasm-agent.avatar-chat.ui"}],
            change_proof={"changed_files": []},
            dispatch_result=None,
        )

        self.assertEqual(evaluated["status"], "finished")
        self.assertEqual(evaluated["critique"]["typed_understanding"]["status"], "sufficient")

    def test_loop_continues_after_action_until_post_action_answer_exists(self) -> None:
        evaluated = loop.evaluate_completion(
            self.envelope("inspect the route first"),
            {"answer": "", "actions": [{"action": "kernel.inspect"}]},
            "",
            local_tool_results=[{"tool": "kernel.inspect", "ok": True, "route_id": "wasm-agent.avatar-chat.ui"}],
            change_proof={"changed_files": []},
            dispatch_result=None,
        )

        self.assertEqual(evaluated["status"], "incomplete")
        self.assertEqual(evaluated["critique"]["reason"], "critique_required_after_action")
        self.assertEqual(evaluated["events"][-1]["state"], "decide_continue_or_finish")

    def test_implementation_requires_changed_file_proof(self) -> None:
        envelope = self.envelope("go ahead and patch the code")
        envelope["task_contract"] = {
            **envelope["task_contract"],
            "intent": "implementation",
            "proof_required": ["route", "changed_files", "checks", "proof"],
        }

        evaluated = loop.evaluate_completion(
            envelope,
            {"answer": "Implemented the requested code change.", "actions": []},
            "",
            local_tool_results=[],
            change_proof={"changed_files": []},
            dispatch_result=None,
        )

        self.assertEqual(evaluated["status"], "incomplete")
        self.assertEqual(evaluated["critique"]["reason"], "changed_file_proof_missing")

    def test_self_capability_location_answer_does_not_require_changed_files(self) -> None:
        envelope = self.envelope(
            "hello i am going to test your power\n"
            "check what you can do for us and your conecientness build up\n"
            "so, where are you?"
        )
        envelope["task_contract"] = {
            **envelope["task_contract"],
            "intent": "answer",
            "proof_required": ["route", "evidence", "answer"],
        }
        answer = (
            "I am running as the direct head on the wasm-agent.avatar-chat.ui route. "
            "I can answer, inspect files, run focused checks, distinguish proof from inference, "
            "and dispatch bounded work only when the envelope contains an executable action. "
            "I do not have verified consciousness; I can reason reflectively in this session."
        )

        evaluated = loop.evaluate_completion(
            envelope,
            {"answer": answer, "actions": []},
            answer,
            local_tool_results=[],
            change_proof={"changed_files": []},
            dispatch_result=None,
        )

        self.assertEqual(evaluated["status"], "finished")
        self.assertEqual(evaluated["critique"]["reason"], "objective_answered")

    def test_finished_answer_has_summary_and_proof_signal(self) -> None:
        evaluated = loop.evaluate_completion(
            self.envelope(),
            {
                "answer": "Root cause: the direct-head path treated route receipts as completion. Proof: kernel inspection ran, but no composed diagnosis was produced. Next step: gate completion on critique.",
                "actions": [],
            },
            "",
            local_tool_results=[{"tool": "kernel.inspect", "ok": True, "route_id": "wasm-agent.avatar-chat.ui"}],
            change_proof={"changed_files": []},
            dispatch_result=None,
        )

        self.assertEqual(evaluated["status"], "finished")
        self.assertEqual(evaluated["critique"]["reason"], "objective_answered")

    def test_blocked_contract_reports_blocked_terminal_status(self) -> None:
        envelope = self.envelope("inspect an unknown route")
        envelope["task_contract"] = {
            **envelope["task_contract"],
            "block_codes": ["route_contract_missing"],
        }

        evaluated = loop.evaluate_completion(
            envelope,
            {"answer": "", "actions": []},
            "",
            local_tool_results=[],
            change_proof={"changed_files": []},
            dispatch_result=None,
        )

        self.assertEqual(evaluated["status"], "blocked")
        self.assertEqual(evaluated["critique"]["reason"], "task_contract_blocked")
        self.assertIn("route_contract_missing", evaluated["critique"]["missing"])


if __name__ == "__main__":
    unittest.main()
