#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
import json
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier import provider_tools, run_protocol
from master_frontier.v5 import completion, loop, task_policy, tools, trajectory
from master_frontier.v5 import context
from master_frontier.v5.errors import V5Error


def route(root: Path) -> dict[str, object]:
    return {"route_id": "fixture.ui", "workspace_root": str(root), "allowed_read_roots": [str(root)], "owner": "fixture"}


class MasterFrontierV5Tests(unittest.TestCase):
    def test_declared_conversation_uses_direct_completion_without_tools(self) -> None:
        state = trajectory.new("run", "turn", "hello", "fixture.ui")
        direct_route = {"route_id": "fixture.ui", "task_contract": {"request_class": "conversation"}}
        calls = []
        def complete(messages, _index):
            calls.append(messages)
            self.assertEqual(json.loads(messages[1]["content"])["tools"], [])
            self.assertIn("self-contained conversation", messages[0]["content"])
            return {"reply": "Hello."}
        outcome = loop.run("hello", direct_route, state, complete=complete, execute=lambda *_: self.fail("tool execution must not occur"))
        self.assertEqual(outcome.answer, "Hello.")
        self.assertEqual(outcome.calls, 1)
        self.assertEqual(outcome.tools, [])

    def test_direct_completion_requires_declared_class_not_prompt_heuristics(self) -> None:
        self.assertTrue(task_policy.direct_completion({"task_contract": {"objective_kind": "general_conversation"}}))
        self.assertFalse(task_policy.direct_completion({"task_contract": {"request_class": "source_investigation"}}))
        self.assertFalse(task_policy.direct_completion({"objective": "hello conversation answer directly"}))

    def test_all_loop5_strategies_preserve_declared_direct_and_grounded_modes(self) -> None:
        matrix = json.loads((Path(__file__).resolve().parents[3] / "labs/wasm-agent/loop5-v5-strategies.json").read_text())
        direct_fields = {"request_class":"conversation","declared_classes":["conversation"],"completion_mode":"direct","proof_policy":"none","required_capabilities":[],"evidence_requirements":[],"execution_profile":"answer_only","authority_source":"declared_task_contract","context_profile":"direct"}
        grounded_fields = {"request_class":"source_investigation","declared_classes":["source_investigation"],"completion_mode":"tool_loop","proof_policy":"grounded","required_capabilities":["inspect"],"evidence_requirements":["grounded"],"execution_profile":"grounded","authority_source":"declared_task_contract","context_profile":"natural_tool_loop"}
        for item in matrix["variants"]:
            self.assertTrue(task_policy.direct_completion({"task_contract":{**direct_fields,"strategy":item["strategy"]}}), item["strategy"])
            self.assertFalse(task_policy.direct_completion({"task_contract":{**grounded_fields,"strategy":item["strategy"]}}), item["strategy"])

    def test_context_exposes_bounded_declared_runtime_identity(self) -> None:
        state = trajectory.new("run", "turn", "which model", "fixture.ui")
        messages = context.messages("which model", {"route_id":"fixture.ui","runtime_identity":{"model":"frank/GLM-5.2"}}, state)
        payload = json.loads(messages[1]["content"])
        self.assertEqual(payload["runtime_identity"], {"model":"frank/GLM-5.2"})
        self.assertIn("runtime_identity", messages[0]["content"])

    def test_protocol_is_explicit_and_resume_immutable(self) -> None:
        self.assertEqual(run_protocol.select({"protocol": "v5"}), "v5")
        self.assertEqual(run_protocol.request_fields({"protocol": "v5"}), {"protocol": "v5", "investigation_mode": ""})
        with self.assertRaises(run_protocol.ProtocolError):
            run_protocol.require_resume("v5", {"protocol": "v3"})

    def test_natural_search_then_read_then_final(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "ARTIFACTS.md").write_text("\n".join("generic widget" for _ in range(40)))
            target = root / "modules" / "meta-analysis-widget.js"; target.parent.mkdir(); target.write_text("export function renderMetaAnalysis() {\n  return false;\n}\n")
            state = trajectory.new("run", "turn", "criticize meta-analysis widget", "fixture.ui")
            responses = iter([
                {"reply": '{"tool":"search","arguments":{"query":"meta-analysis widget","limit":5}}'},
                {"reply": '{"tool":"read","arguments":{"path":"modules/meta-analysis-widget.js","start_line":1,"end_line":20}}'},
                {"reply": '{"final":"The render path always returns false, so it cannot present a successful result."}'},
            ])
            executed = []
            def execute(name: str, arguments: dict[str, object]) -> dict[str, object]:
                executed.append(name)
                return tools.execute(name, arguments, route(root), invoke=lambda *_: {})
            outcome = loop.run("criticize meta-analysis widget", route(root), state, complete=lambda *_: next(responses), execute=execute)
            self.assertEqual(executed, ["search", "read"])
            self.assertIn("always returns false", outcome.answer)
            self.assertEqual(outcome.trajectory["status"], "completed")
            read = outcome.tools[-1]
            self.assertIn("renderMetaAnalysis", read["content"])
            search_step = next(step for step in outcome.trajectory["steps"] if step.get("tool") == "search")
            self.assertLessEqual(len(search_step["result"]["matches"]), 8)
            self.assertTrue(all(len(item.get("excerpt", "")) <= 320 for item in search_step["result"]["matches"]))
            self.assertEqual(search_step["result"]["focus"]["owner_file"], "modules/meta-analysis-widget.js")
            self.assertIn("renderMetaAnalysis", {item["name"] for item in search_step["result"]["focus"]["key_symbols"]})

    def test_timeout_resume_preserves_completed_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "widget.js").write_text("export const widget = true;\n")
            state = trajectory.new("run", "turn", "review widget", "fixture.ui")
            responses = iter([
                {"reply": '{"tool":"search","arguments":{"query":"widget"}}'},
                {"reply": '{"tool":"read","arguments":{"path":"widget.js"}}'},
            ])
            executed = []
            def complete(*_):
                try: return next(responses)
                except StopIteration: raise TimeoutError("provider timed out")
            def execute(name, arguments):
                executed.append(name); return tools.execute(name, arguments, route(root), invoke=lambda *_: {})
            with self.assertRaises(V5Error) as raised:
                loop.run("review widget", route(root), state, complete=complete, execute=execute)
            self.assertEqual(executed, ["search", "read"])
            checkpoint = raised.exception.checkpoint
            outcome = loop.run("review widget", route(root), checkpoint, complete=lambda *_: {"reply": '{"final":"The source was preserved across timeout."}'}, execute=execute)
            self.assertEqual(executed, ["search", "read"])
            self.assertEqual(outcome.trajectory["status"], "completed")

    def test_duplicate_action_synthesizes_only_after_primary_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "x.js").write_text("x\n")
            state = trajectory.new("run", "turn", "find x", "fixture.ui")
            responses = iter([
                {"reply": '{"tool":"search","arguments":{"query":"x"}}'},
                {"reply": '{"tool":"read","arguments":{"path":"x.js"}}'},
                {"reply": '{"tool":"search","arguments":{"query":"x"}}'},
                {"reply": "The source contains x."},
            ])
            executed = []
            def execute(name, args):
                executed.append(name)
                return tools.execute(name, args, route(root), invoke=lambda *_: {})
            outcome = loop.run("find x", route(root), state, complete=lambda *_: next(responses), execute=execute)
            self.assertEqual(executed, ["search", "read"])
            self.assertEqual(outcome.answer, "The source contains x.")
            self.assertEqual(outcome.trajectory["status"], "completed")
            self.assertEqual(outcome.trajectory["steps"][-1]["status"], "duplicate")
            self.assertEqual(outcome.trajectory["completion_assessment"]["status"], "sufficient")

    def test_duplicate_search_identifies_read_gap_before_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "x.js").write_text("x\n")
            state = trajectory.new("run", "turn", "find x", "fixture.ui")
            response = {"reply": '{"tool":"search","arguments":{"query":"x"}}'}
            with self.assertRaises(V5Error) as raised:
                loop.run("find x", route(root), state, complete=lambda *_: response, execute=lambda name, args: tools.execute(name, args, route(root), invoke=lambda *_: {}))
            self.assertEqual(raised.exception.code, "evidence_incomplete")
            assessment = raised.exception.checkpoint["completion_assessment"]
            self.assertEqual(assessment["status"], "incomplete")
            self.assertEqual(assessment["required_gaps"], ["primary_source_read"])
            self.assertEqual(assessment["next_actions"][0]["tool"], "read")

    def test_completion_assessment_blocks_without_primary_evidence(self) -> None:
        state = trajectory.new("run", "turn", "answer", "fixture.ui")
        self.assertEqual(completion.assess(state)["status"], "blocked")

    def test_network_timeout_without_evidence_preserves_tool_mode(self) -> None:
        class NetworkTimeout(RuntimeError):
            code = "network-timeout"

        state = trajectory.new("run", "turn", "explain x", "fixture.ui")
        calls = []
        def complete(messages, index):
            calls.append(messages)
            if len(calls) == 1:
                raise NetworkTimeout("Provider request timed out.")
            return {"reply": "Recovered from accumulated evidence."}
        outcome = loop.run("explain x", {"route_id": "fixture.ui"}, state, complete=complete, execute=lambda *_: {})
        self.assertEqual(outcome.answer, "Recovered from accumulated evidence.")
        self.assertEqual(len(calls), 2)
        self.assertTrue(json.loads(calls[-1][1]["content"])["tools"])

    def test_network_timeout_with_primary_evidence_retries_completion_only(self) -> None:
        class NetworkTimeout(RuntimeError):
            code = "network-timeout"

        state = trajectory.new("run", "turn", "explain x", "fixture.ui")
        trajectory.append(state, {"kind": "tool", "tool": "read", "status": "completed", "result": {"ok": True, "path": "x.js", "content": "1: x"}})
        calls = []
        def complete(messages, index):
            calls.append(messages)
            if len(calls) == 1: raise NetworkTimeout("Provider request timed out.")
            return {"reply": "Recovered from primary evidence."}
        outcome = loop.run("explain x", {"route_id": "fixture.ui"}, state, complete=complete, execute=lambda *_: {})
        self.assertEqual(outcome.answer, "Recovered from primary evidence.")
        self.assertEqual(json.loads(calls[-1][1]["content"])["tools"], [])

    def test_network_timeout_retries_only_once(self) -> None:
        class NetworkTimeout(RuntimeError):
            code = "network-timeout"

        state = trajectory.new("run", "turn", "explain x", "fixture.ui")
        with self.assertRaises(V5Error) as raised:
            loop.run("explain x", {"route_id": "fixture.ui"}, state, complete=lambda *_: (_ for _ in ()).throw(NetworkTimeout("Provider request timed out.")), execute=lambda *_: {})
        self.assertEqual(raised.exception.code, "network-timeout")

    def test_completion_only_rejects_ignored_tool_instruction(self) -> None:
        state = trajectory.new("run", "turn", "find x", "fixture.ui")
        state["pending"] = "frontier_completion"
        action = trajectory.action_id("search", {"query": "x"})
        state["completed_actions"][action] = {"ok": True, "summary": "Found x."}
        with self.assertRaises(V5Error) as raised:
            loop.run("find x", {"route_id": "fixture.ui"}, state, complete=lambda *_: {"reply": '{"tool":"search","arguments":{"query":"x"}}'}, execute=lambda *_: {})
        self.assertEqual(raised.exception.code, "no_semantic_progress")

    def test_malformed_output_repairs_once_then_stops(self) -> None:
        state = trajectory.new("run", "turn", "hello", "fixture.ui")
        with self.assertRaises(V5Error) as raised:
            loop.run("hello", {"route_id": "fixture.ui"}, state, complete=lambda *_: {"reply": "{not json"}, execute=lambda *_: {})
        self.assertEqual(raised.exception.code, "model_output_invalid")

    def test_plain_provider_text_is_a_natural_final_answer(self) -> None:
        state = trajectory.new("run", "turn", "hello", "fixture.ui")
        outcome = loop.run("hello", {"route_id": "fixture.ui"}, state, complete=lambda *_: {"reply": "Hello. How can I help?"}, execute=lambda *_: {})
        self.assertEqual(outcome.answer, "Hello. How can I help?")

    def test_flattened_provider_tool_arguments_are_normalized(self) -> None:
        self.assertEqual(loop.normalize({"reply": '{"tool":"search","query":"widget","limit":5}'}), {
            "kind": "tool", "tool": "search", "arguments": {"query": "widget", "limit": 5},
        })

    def test_native_provider_tool_call_is_normalized(self) -> None:
        self.assertEqual(loop.normalize({"tool_calls": [{"id": "c1", "name": "read", "arguments": {"path": "x.js"}}]}), {
            "kind": "tool", "tool": "read", "arguments": {"path": "x.js"},
        })

    def test_common_structured_final_answer_is_normalized(self) -> None:
        self.assertEqual(loop.normalize({"reply": '{"answer":"Useful critique"}'}), {"kind": "final", "answer": "Useful critique"})

    def test_provider_transport_forwards_and_extracts_native_tools(self) -> None:
        fields = provider_tools.request_fields({"tools": [{"type": "function", "function": {"name": "search", "description": "Find source", "parameters": {"type": "object"}}}]})
        self.assertEqual(fields["tool_choice"], "auto")
        self.assertEqual(fields["tools"][0]["function"]["name"], "search")
        calls = provider_tools.response_calls({"choices": [{"message": {"tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search", "arguments": '{"query":"widget"}'}}]}}]})
        self.assertEqual(calls, [{"id": "c1", "name": "search", "arguments": {"query": "widget"}}])

    def test_absolute_native_read_path_normalizes_to_route_relative_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "modules" / "x.js"; source.parent.mkdir(); source.write_text("x\n")
            result = tools.execute("read", {"path": str(source)}, route(root), invoke=lambda *_: {})
            self.assertEqual(result["path"], "modules/x.js")

    def test_no_objective_token_ceiling_exists(self) -> None:
        state = trajectory.new("run", "turn", "hello", "fixture.ui")
        outcome = loop.run("hello", {"route_id": "fixture.ui"}, state, complete=lambda *_: {"reply": '{"final":"hello"}', "usage": {"total_tokens": 999999}}, execute=lambda *_: {})
        self.assertEqual(outcome.answer, "hello")

    def test_complete_owner_coverage_requires_answer_signal(self) -> None:
        state = trajectory.new("run", "turn", "review", "fixture.ui")
        state["steps"] = [
            {"result": {"focus": {"owner_file": "x.js", "line_count": 100}}},
            {"result": {"path": "x.js", "start_line": 1, "end_line": 40}},
            {"result": {"path": "x.js", "start_line": 41, "end_line": 100}},
        ]
        status = context._evidence_status(state)
        self.assertTrue(status["owner_fully_read"])
        self.assertIn("Answer now", status["instruction"])
        payload = json.loads(context.messages("review", {"route_id": "fixture.ui"}, state)[1]["content"])
        self.assertEqual(payload["tools"], [])
        self.assertIn("plain text", context.messages("review", {"route_id": "fixture.ui"}, state)[0]["content"])


if __name__ == "__main__": unittest.main()
