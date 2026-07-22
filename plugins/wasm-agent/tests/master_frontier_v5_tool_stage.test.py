#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/wasm-agent/server"))

from master_frontier.v5 import context, policy, trajectory


class MasterFrontierV5ToolStageTests(unittest.TestCase):
    def test_verification_retires_exhausted_tool_families(self) -> None:
        state = trajectory.new("run", "turn", "verify", "fixture.ui")
        trajectory.append(state, {
            "kind": "tool", "tool": "read", "status": "completed",
            "result": {"ok": True, "path": "owner.py"},
        })
        state["operation_ledger"]["check"] = {"rev": 0, "ok": True}
        state["operation_ledger"]["diff"] = {"rev": 0, "ok": False}
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read", "test.run", "proof.report"],
            "task_contract": {"request_class": "verification"},
        }
        names = [item["name"] for item in policy.active_descriptors(route, state)]
        native = [item["function"]["name"] for item in policy.active_provider_tools(route, state)]
        self.assertEqual(names, ["prove"])
        self.assertEqual(native, names)

    def test_source_authority_is_not_stage_guessed(self) -> None:
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read"],
            "task_contract": {"request_class": "source_investigation"},
        }
        self.assertEqual(policy.active_descriptors(route, state), policy.descriptors_for(route))
        self.assertFalse(context.completion_only(state, route))

    def test_implementation_retires_only_completed_workflow_stages(self) -> None:
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "task_contract": {"request_class": "implementation"},
        }
        state["operation_ledger"].update({"revision": 1, "check": {}})
        self.assertEqual(
            [item["name"] for item in policy.active_descriptors(route, state)],
            ["edit", "test", "diff", "prove"],
        )
        state["operation_ledger"]["check"] = {"rev": 1, "ok": True}
        self.assertEqual(
            [item["name"] for item in policy.active_descriptors(route, state)],
            ["diff", "prove"],
        )

    def test_llm_autonomous_keeps_only_unexhausted_authorized_tools_visible(self) -> None:
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        state["operation_ledger"].update({"revision": 1, "check": {"rev": 1, "ok": True}})
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        self.assertEqual(
            [item["name"] for item in policy.active_descriptors(route, state)],
            ["checkpoint", "diff", "prove"],
        )

    def test_autonomous_implementation_edit_schema_does_not_advertise_dry_run(self) -> None:
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        edit = next(item for item in policy.descriptors_for(route) if item["name"] == "edit")
        self.assertNotIn("dry_run", edit["input_schema"]["properties"])
        self.assertIn("dry_run", next(item for item in policy.tool_descriptors() if item["name"] == "edit")["input_schema"]["properties"])


if __name__ == "__main__":
    unittest.main()
