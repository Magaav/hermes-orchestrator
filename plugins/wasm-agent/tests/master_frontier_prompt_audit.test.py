#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = PLUGIN_ROOT / "server"
STATIC_SERVER_PATH = SERVER_ROOT / "static_server.py"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


envelope = load_module("master_frontier.envelope", SERVER_ROOT / "master_frontier" / "envelope.py")
intent = load_module("master_frontier.intent", SERVER_ROOT / "master_frontier" / "intent.py")
protocol = load_module("master_frontier.protocol", SERVER_ROOT / "master_frontier" / "protocol.py")
planner = load_module("master_frontier.planner", SERVER_ROOT / "master_frontier" / "planner.py")
repair = load_module("master_frontier.repair", SERVER_ROOT / "master_frontier" / "repair.py")


class MasterFrontierPromptAuditTests(unittest.TestCase):
    def test_prompt_is_compact_and_owned_by_master_frontier(self) -> None:
        static_source = STATIC_SERVER_PATH.read_text(encoding="utf-8")

        self.assertLessEqual(len(envelope.SYSTEM_PROMPT), 1400)
        self.assertIn("local Agent Kernel before Hermes", envelope.SYSTEM_PROMPT)
        self.assertIn("Keep normal answers as plain text", envelope.SYSTEM_PROMPT)
        self.assertNotIn("You are wasm-agent's direct LLM-native head", static_source)
        self.assertIn("master_frontier_envelope.SYSTEM_PROMPT", static_source)

    def test_tool_manifest_preserves_exact_ids_with_short_descriptions(self) -> None:
        expected = {
            "kernel.capabilities",
            "kernel.resolve",
            "kernel.inspect",
            "kernel.act",
            "kernel.prove",
            "code.memory.search",
            "code.memory.impact",
        }
        actions = list(protocol.KERNEL_ACTIONS)
        ids = {str(action.get("id") or "") for action in actions}

        self.assertTrue(expected.issubset(ids))
        for action in actions:
            self.assertLessEqual(len(str(action.get("description") or "")), 140)

    def test_capability_inquiry_beats_implementation_verbs(self) -> None:
        inquiry = {
            "objective": "check out the possibility to ship widgets to the spaces",
            "surface": "avatar-chat",
            "route_id": "wasm-agent.avatar-chat.ui",
            "capabilities": ["repo.read", "repo.edit", "test.run", "runtime.inspect", "proof.report"],
        }
        implementation = {
            **inquiry,
            "objective": "go ahead and ship widgets to the spaces",
        }

        self.assertTrue(intent.text_is_capability_inquiry(inquiry["objective"]))
        self.assertFalse(intent.objective_is_implementation_intent(inquiry))
        self.assertFalse(intent.goal_requires_change_artifact(inquiry))
        self.assertFalse(intent.text_is_capability_inquiry(implementation["objective"]))
        self.assertTrue(intent.objective_is_implementation_intent(implementation))
        self.assertTrue(intent.goal_requires_change_artifact(implementation))

    def test_direct_can_we_ship_question_is_capability_inquiry(self) -> None:
        envelope = {
            "objective": "amazing. can we ship a widget to the realure space?",
            "surface": "avatar-chat",
            "route_id": "wasm-agent.avatar-chat.ui",
            "capabilities": ["repo.read", "repo.edit", "test.run", "runtime.inspect", "proof.report"],
        }

        self.assertTrue(intent.text_is_capability_inquiry(envelope["objective"]))
        self.assertFalse(intent.objective_is_implementation_intent(envelope))
        self.assertFalse(intent.goal_requires_change_artifact(envelope))

    def test_tool_claims_require_executable_actions(self) -> None:
        self.assertTrue(envelope.requires_structured_action({}, "I'm dispatching to Hermes now."))
        self.assertTrue(envelope.requires_structured_action({}, '{"decision":"transcript.read","actions":[{"action"'))
        self.assertFalse(envelope.requires_structured_action({"answer": "Done.", "decision": "answer", "actions": []}, "Done."))

    def test_conversation_repair_salvages_action_claim_without_retry(self) -> None:
        calls = []

        def completion(**_kwargs):
            calls.append(_kwargs)
            return {"reply": "retry should not run", "parsed": {"answer": "retry should not run"}}

        parsed, result = repair.repair_structured_action(
            body={"instructions": "Use the envelope."},
            route_envelope={"objective_kind": "conversation"},
            receiver="test",
            result={
                "reply": "Here is my critique. I'm dispatching to Hermes now. The envelope should keep objective kind explicit.",
                "parsed": {
                    "answer": "Here is my critique. I'm dispatching to Hermes now. The envelope should keep objective kind explicit.",
                    "decision": "answer",
                    "actions": [],
                },
            },
            completion=completion,
            completion_kwargs={},
            record_event=lambda *_args: None,
        )

        self.assertEqual(calls, [])
        self.assertEqual(parsed["decision"], "answer")
        self.assertEqual(parsed["actions"], [])
        self.assertIn("objective kind explicit", result["reply"])
        self.assertNotIn("dispatching to Hermes", result["reply"])

    def test_code_memory_is_in_manifest_before_broad_file_reads(self) -> None:
        self.assertEqual(protocol.LOCAL_TOOL_PATHS["code.memory.search"], "/agent/tools/code.memory.search")
        self.assertEqual(protocol.LOCAL_TOOL_PATHS["code.memory.impact"], "/agent/tools/code.memory.impact")

    def test_task_contract_is_projected_into_compact_prompt(self) -> None:
        direct = load_module("wasm_agent_static_server_for_prompt_audit", STATIC_SERVER_PATH)
        _messages, built, semantic, measurement = direct.direct_envelope_with_metrics({
            "envelope": {
                "objective": "amazing. can we ship a widget to the realure space?",
                "surface": "avatar-chat",
                "route_id": "wasm-agent.avatar-chat.ui",
                "capabilities": ["repo.read", "repo.edit", "test.run", "runtime.inspect", "proof.report"],
                "allowed_actions": [{"id": "answer"}],
            }
        })
        contract = built["task_contract"]

        self.assertEqual(contract["intent"], "capability_inquiry")
        self.assertEqual(contract["executor"], "provider_head")
        self.assertIn("code.memory.search", contract["tools_first"])
        self.assertIn("PLAN ", semantic)
        self.assertIn("subagent_harness_only", semantic)
        self.assertLessEqual(measurement["estimated_tokens"], 1200)
        self.assertEqual(planner.task_contract(built)["intent"], "capability_inquiry")


if __name__ == "__main__":
    unittest.main()
