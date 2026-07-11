#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = PLUGIN_ROOT / "server"
PLANNER_PATH = SERVER_ROOT / "master_frontier" / "planner.py"

sys.path.insert(0, str(SERVER_ROOT))

spec = importlib.util.spec_from_file_location("master_frontier.planner", PLANNER_PATH)
assert spec and spec.loader
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)


class MasterFrontierPlannerTests(unittest.TestCase):
    def route_envelope(self, objective: str) -> dict[str, object]:
        return {
            "objective": objective,
            "surface": "avatar-chat",
            "route_id": "wasm-agent.avatar-chat.ui",
            "capabilities": ["repo.read", "repo.edit", "test.run", "runtime.inspect", "proof.report"],
            "route_contract": {
                "route_id": "wasm-agent.avatar-chat.ui",
                "workspace_root": "/local/plugins/wasm-agent",
                "caps": ["repo.read", "repo.edit", "test.run", "runtime.inspect", "proof.report"],
                "provider_policy": {
                    "default": "local-first",
                    "hermes": "bounded-skill-only",
                    "missing_route": "fail",
                },
                "budget": {
                    "head_tokens_max": 3000,
                    "provider_tokens_max": 8000,
                    "api_calls_max": 6,
                    "wall_ms_max": 90000,
                },
            },
        }

    def test_widget_can_we_ship_is_capability_inquiry_with_code_memory_first(self) -> None:
        contract = planner.task_contract(self.route_envelope("amazing. can we ship a widget to the realure space?"))

        self.assertEqual(contract["intent"], "capability_inquiry")
        self.assertEqual(contract["route_id"], "wasm-agent.avatar-chat.ui")
        self.assertEqual(contract["executor"], "provider_head")
        self.assertIn("code.memory.search", contract["tools_first"])
        self.assertIn("kernel.inspect", contract["tools_first"])
        self.assertEqual(contract["hermes"], "subagent_harness_only")
        self.assertEqual(contract["provider_policy"]["default"], "local-first")
        self.assertEqual(contract["provider_policy"]["hermes"], "bounded-skill-only")
        self.assertEqual(contract["budget"]["provider_tokens_max"], 8000)
        self.assertEqual(contract["budget"]["api_calls_max"], 6)
        self.assertEqual(contract["block_codes"], [])

    def test_hard_widget_build_requires_local_change_proof(self) -> None:
        contract = planner.task_contract(self.route_envelope("go ahead and build the widget in the realure space"))

        self.assertEqual(contract["intent"], "implementation")
        self.assertEqual(contract["executor"], "local_kernel")
        self.assertIn("code.memory.impact", contract["tools_first"])
        self.assertIn("changed_files", contract["proof_required"])

    def test_explicit_conversation_kind_keeps_plain_chat_in_answer_lane(self) -> None:
        envelope = self.route_envelope("hello, tell me a short story")
        envelope["objective_kind"] = "conversation"

        contract = planner.task_contract(envelope)

        self.assertEqual(contract["intent"], "answer")
        self.assertEqual(contract["executor"], "provider_head")
        self.assertEqual(contract["evidence_floor"], "conceptual")
        self.assertEqual(contract["depth"]["level"], "normal")
        self.assertEqual(contract["recall_budget"]["mode"], "on_demand")
        self.assertNotIn("changed_files", contract["proof_required"])

    def test_explicit_answer_directly_proof_prompt_stays_answer_lane(self) -> None:
        envelope = self.route_envelope("avatar-chat quest proof turn one: answer directly with route and token proof only.")
        envelope["objective_kind"] = "conversation"

        contract = planner.task_contract(envelope)

        self.assertEqual(contract["intent"], "answer")
        self.assertEqual(contract["executor"], "provider_head")
        self.assertEqual(contract["evidence_floor"], "conceptual")
        self.assertEqual(contract["tools_first"], ["kernel.resolve"])
        self.assertNotIn("cause", contract["proof_required"])

    def test_critique_infers_evidence_backed_diagnosis_without_prompt_fixture(self) -> None:
        contract = planner.task_contract(self.route_envelope(
            "check out the current node and critisize its architecture"
        ))

        self.assertEqual(contract["intent"], "diagnosis")
        self.assertEqual(contract["evidence_floor"], "runtime")
        self.assertEqual(contract["route_intent"], "runtime_support")
        self.assertEqual(contract["depth"]["level"], "deep")
        self.assertEqual(contract["recall_budget"]["mode"], "bounded_recent")
        self.assertIn("code.memory.search", contract["tools_first"])
        self.assertIn("kernel.inspect", contract["tools_first"])

    def test_free_depth_is_open_budget_hint_not_model_metadata(self) -> None:
        envelope = self.route_envelope("critique your envelope from within")
        envelope["depth"] = "free"

        contract = planner.task_contract(envelope)

        self.assertEqual(contract["depth"]["level"], "free")
        self.assertEqual(contract["depth"]["budget_hint"], "open")
        self.assertEqual(contract["recall_budget"]["mode"], "bounded_recent")
        self.assertIn("harness/proof loops", contract["depth"]["rule"])
        self.assertNotIn("model", contract)
        self.assertNotIn("model_caps", contract)

    def test_implementation_gets_proof_floor(self) -> None:
        contract = planner.task_contract(self.route_envelope("go ahead and build the widget in the realure space"))

        self.assertEqual(contract["evidence_floor"], "proof")
        self.assertEqual(contract["route_intent"], "implementation")

    def test_runtime_question_gets_runtime_floor(self) -> None:
        contract = planner.task_contract(self.route_envelope("what happened in the node runtime since creation?"))

        self.assertEqual(contract["evidence_floor"], "runtime")
        self.assertEqual(contract["route_intent"], "runtime_support")

    def test_explicit_evidence_floor_override_is_preserved(self) -> None:
        envelope = self.route_envelope("answer from route proof only")
        envelope["evidence_floor"] = "route"

        contract = planner.task_contract(envelope)

        self.assertEqual(contract["evidence_floor"], "route")

    def test_repository_ui_object_question_requires_conclusive_source_investigation(self) -> None:
        contract = planner.task_contract(self.route_envelope("explain what an unknown space is in this UI"))

        self.assertEqual(contract["evidence_floor"], "source")
        self.assertEqual(contract["route_intent"], "informational")

    def test_envelope_budget_override_is_preserved_in_contract(self) -> None:
        envelope = self.route_envelope("answer from this route")
        envelope["budget"] = {
            "head_tokens_max": 1200,
            "max_output_tokens": 300,
        }

        contract = planner.task_contract(envelope)

        self.assertEqual(contract["budget"]["head_tokens_max"], 1200)
        self.assertEqual(contract["budget"]["provider_tokens_max"], 8000)
        self.assertEqual(contract["budget"]["max_output_tokens"], 300)

    def test_envelope_budget_cannot_expand_route_limits(self) -> None:
        envelope = self.route_envelope("answer from this route")
        envelope["budget"] = {
            "head_tokens_max": 99999,
            "provider_tokens_max": 99999,
            "api_calls_max": 99,
            "wall_ms_max": 999999,
            "max_output_tokens": 99999,
        }

        contract = planner.task_contract(envelope)

        self.assertEqual(contract["budget"]["head_tokens_max"], 3000)
        self.assertEqual(contract["budget"]["provider_tokens_max"], 8000)
        self.assertEqual(contract["budget"]["api_calls_max"], 6)
        self.assertEqual(contract["budget"]["wall_ms_max"], 90000)
        self.assertEqual(contract["budget"]["max_output_tokens"], 65536)

    def test_missing_route_blocks_before_executor_choice(self) -> None:
        contract = planner.task_contract({"objective": "inspect this unknown surface", "capabilities": ["repo.read"]})

        self.assertEqual(contract["executor"], "blocked")
        self.assertIn("route_contract_missing", contract["block_codes"])

    def test_route_without_workspace_blocks_before_provider_selection(self) -> None:
        contract = planner.task_contract({
            "objective": "answer from this route",
            "route_id": "wasm-agent.avatar-chat.ui",
            "capabilities": ["repo.read", "proof.report"],
            "route_contract": {
                "route_id": "wasm-agent.avatar-chat.ui",
                "caps": ["repo.read", "proof.report"],
            },
        })

        self.assertEqual(contract["executor"], "blocked")
        self.assertIn("workspace_root_missing", contract["block_codes"])


if __name__ == "__main__":
    unittest.main()
