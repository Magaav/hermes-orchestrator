#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier import authority, client_ui_actions, route_contracts  # noqa: E402
from master_frontier.v5 import policy  # noqa: E402


class ClientUiActionsTests(unittest.TestCase):
    def route(self) -> dict:
        return {"caps": ["client.ui.inspect", "client.ui.control"], "client_ui": {"runtime_types": ["electron"], "widget_ids": ["browser"]}, "task_contract": {"request_class": "conversation"}}

    def clients(self, capabilities=None) -> dict:
        return {"clients": [{"client_id": "electron-a", "device_id": "electron-a", "runtime_type": "electron", "live": True, "capabilities": capabilities or ["control.widget.open", "control.browser.navigate"], "route": "https://wa.colmeio.com/home?native=electron"}]}

    def test_route_exposes_distinct_client_tool(self) -> None:
        self.assertTrue(authority.tool_allowed("client", self.route()))
        descriptor = next(item for item in policy.descriptors_for(self.route()) if item["name"] == "client")
        self.assertIn("open_widget", descriptor["input_schema"]["properties"]["operation"]["enum"])

    def test_open_browser_widget_requires_and_returns_client_ack(self) -> None:
        queued = []
        result = client_ui_actions.execute(
            {"operation": "open_widget", "widget_id": "browser", "wait_sec": 0}, self.route(),
            list_clients=self.clients,
            queue_command=lambda command: queued.append(command) or {"command_id": "cmd-1"},
            read_command=lambda _device, _command: {"status": "finished", "result": {"ok": True, "widget_id": "browser", "opened": True}},
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["acknowledged"])
        self.assertEqual(queued[0]["type"], "open_widget")
        self.assertEqual(queued[0]["payload"], {"widget_id": "browser"})

    def test_widget_and_runtime_capability_are_fail_closed(self) -> None:
        denied = client_ui_actions.execute(
            {"operation": "open_widget", "widget_id": "settings", "wait_sec": 0}, self.route(),
            list_clients=self.clients, queue_command=lambda _command: {}, read_command=lambda *_args: {},
        )
        missing = client_ui_actions.execute(
            {"operation": "open_widget", "widget_id": "browser", "wait_sec": 0}, self.route(),
            list_clients=lambda: self.clients(["observe.status"]), queue_command=lambda _command: {}, read_command=lambda *_args: {},
        )
        self.assertEqual(denied["code"], "client_widget_denied")
        self.assertEqual(missing["code"], "live_electron_client_missing")

    def test_control_requires_separate_route_capability(self) -> None:
        route = self.route()
        route["caps"].remove("client.ui.control")
        result = client_ui_actions.execute(
            {"operation": "open_widget", "widget_id": "browser", "wait_sec": 0}, route,
            list_clients=self.clients, queue_command=lambda _command: {}, read_command=lambda *_args: {},
        )
        self.assertEqual(result["code"], "client_ui_control_denied")

    def test_avatar_route_preserves_client_ui_contract(self) -> None:
        plugin_root = Path(__file__).resolve().parents[1]
        loaded = route_contracts.load_contracts(plugin_root / "server/agent_route_contracts.json", plugin_root)
        route = next(item for item in loaded if item["route_id"] == "wasm-agent.avatar-chat.ui")
        self.assertEqual(route["client_ui"]["widget_ids"], ["browser"])
        self.assertIn("client.ui.control", route["caps"])


if __name__ == "__main__":
    unittest.main()
