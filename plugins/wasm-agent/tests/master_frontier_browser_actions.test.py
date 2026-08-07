#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier import authority, browser_actions, planner, route_contracts
from master_frontier.v5 import policy


class BrowserActionsTests(unittest.TestCase):
    def route(self, *, control: bool = True) -> dict:
        caps = ["repo.read", "browser.inspect"]
        if control:
            caps.append("browser.control")
        return {
            "route_id": "fixture.ui", "workspace_root": "/tmp", "allowed_read_roots": ["/tmp"],
            "caps": caps, "browser_entry_url": "https://wa.colmeio.com/",
            "task_contract": {"request_class": "source_investigation"},
        }

    def test_browser_is_a_native_declared_tool(self) -> None:
        self.assertTrue(authority.tool_allowed("browser", self.route()))
        descriptor = next(item for item in policy.descriptors_for(self.route()) if item["name"] == "browser")
        self.assertEqual(descriptor["input_schema"]["properties"]["operation"]["enum"], ["snapshot", "navigate", "click", "type", "key"])

    def test_real_avatar_route_projects_repository_and_browser_tools(self) -> None:
        plugin_root = Path(__file__).resolve().parents[1]
        loaded = route_contracts.load_contracts(plugin_root / "server/agent_route_contracts.json", plugin_root)
        route = next(item for item in loaded if item["route_id"] == "wasm-agent.avatar-chat.ui")
        envelope = {"objective": "review the live widget", "objective_kind": "diagnosis", "route_contract": route}
        envelope["task_contract"] = planner.task_contract(envelope)
        route["task_contract"] = authority.project_task_contract(envelope, route)
        self.assertEqual(authority.request_class(route), "source_investigation")
        self.assertEqual([item["name"] for item in policy.descriptors_for(route)], ["search", "read", "memory", "browser", "client"])
        self.assertEqual(route["browser_entry_url"], "https://wa.colmeio.com/")

    def test_control_requires_separate_route_capability(self) -> None:
        result = browser_actions.execute({"operation": "navigate", "url": "https://example.com"}, self.route(control=False))
        self.assertEqual(result["code"], "browser_control_denied")

    def test_snapshot_returns_bounded_native_observation(self) -> None:
        completed = mock.Mock(stdout=json.dumps({"ok": True, "url": "https://example.com/", "title": "Example", "items": [], "text": "Example"}), returncode=0)
        with mock.patch.object(browser_actions.subprocess, "run", return_value=completed) as invoked:
            result = browser_actions.execute({"operation": "snapshot"}, self.route())
        self.assertTrue(result["ok"])
        self.assertIn("bounded page snapshot", result["summary"])
        self.assertEqual(invoked.call_args.args[0][0], "node")
        self.assertIn('"target_url":"https://wa.colmeio.com/"', invoked.call_args.args[0][3])


if __name__ == "__main__":
    unittest.main()
