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
