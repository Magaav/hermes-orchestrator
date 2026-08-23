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
        return {"caps": ["client.ui.inspect", "client.ui.control"], "client_ui": {"runtime_types": ["electron"], "widget_ids": ["browser"], "operations": sorted(client_ui_actions.OPERATIONS)}, "task_contract": {"request_class": "conversation"}}

    def clients(self, capabilities=None) -> dict:
        return {"clients": [{"client_id": "electron-a", "device_id": "electron-a", "runtime_type": "electron", "live": True, "capabilities": capabilities or ["control.widget.open", "control.browser.navigate"], "route": "https://wa.colmeio.com/home?native=electron"}]}

    def test_route_exposes_distinct_client_tool(self) -> None:
        self.assertTrue(authority.tool_allowed("client", self.route()))
        descriptor = next(item for item in policy.descriptors_for(self.route()) if item["name"] == "client")
        self.assertIn("open_widget", descriptor["input_schema"]["properties"]["operation"]["enum"])
        self.assertIn("space_open", descriptor["input_schema"]["properties"]["operation"]["enum"])
        self.assertIn("browser_input_receipt", descriptor["input_schema"]["properties"]["operation"]["enum"])
        self.assertIn("browser_pointer_dispatch", descriptor["input_schema"]["properties"]["operation"]["enum"])
        self.assertIn("browser_javascript_execute_unrestricted", descriptor["input_schema"]["properties"]["operation"]["enum"])
        self.assertIn("windows_shell_execute_unrestricted", descriptor["input_schema"]["properties"]["operation"]["enum"])
        self.assertEqual(descriptor["input_schema"]["properties"]["enabled"], {"type": "boolean"})
        self.assertEqual(descriptor["input_schema"]["properties"]["x"]["maximum"], 65_535)

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

    def test_open_space_queues_generic_reference_and_requires_ack(self) -> None:
        queued = []
        result = client_ui_actions.execute(
            {"operation": "space_open", "space": "Realure", "wait_sec": 0}, self.route(),
            list_clients=lambda: self.clients(["control.space.open"]),
            queue_command=lambda command: queued.append(command) or {"command_id": "cmd-space"},
            read_command=lambda *_args: {"status": "finished", "result": {"ok": True, "space_id": "space-realure", "space_name": "Realure", "opened": True}},
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["acknowledged"])
        self.assertEqual(queued[0]["type"], "space_open")
        self.assertEqual(queued[0]["payload"], {"space": "Realure"})
        self.assertEqual(result["answer"], "Opened the Realure space.")
        self.assertEqual(result["proof"], ["client.ack", "client.space.active"])

    def test_open_space_accepts_live_pwa_client(self) -> None:
        clients = self.clients(["control.space.open"])
        clients["clients"][0]["runtime_type"] = "pwa"
        result = client_ui_actions.execute(
            {"operation": "space_open", "space": "Realure", "wait_sec": 0}, self.route(),
            list_clients=lambda: clients,
            queue_command=lambda _command: {"command_id": "cmd-pwa-space"},
            read_command=lambda *_args: {"status": "finished", "result": {"ok": True, "space_name": "Realure"}},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["client"]["runtime_type"], "pwa")

    def test_browser_inspection_uses_native_observability_command(self) -> None:
        queued = []
        result = client_ui_actions.execute(
            {"operation": "browser_inspect", "wait_sec": 0}, self.route(),
            list_clients=lambda: self.clients(["observe.browser.inspect"]),
            queue_command=lambda command: queued.append(command) or {"command_id": "cmd-browser"},
            read_command=lambda _device, _command: {"status": "finished", "result": {
                "ok": True, "browser": {"url": "https://web.whatsapp.com/", "title": "WhatsApp", "loading": False},
                "proof": ["native.web_surface.status"],
            }},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(queued[0]["type"], "observability_browser_surface")
        self.assertEqual(result["result"]["browser"]["title"], "WhatsApp")
        self.assertEqual(
            result["answer"],
            "Yes—I can inspect the Browser widget. It is not currently visible. It has WhatsApp loaded. "
            "The installed shell lacks Browser input-receipt support.",
        )
        self.assertEqual(result["proof"], ["native.web_surface.status"])

    def test_browser_answer_describes_receipt_without_claiming_dom_activation(self) -> None:
        answer = client_ui_actions._browser_answer({"proof": ["native.web_surface.input_receipt"], "browser": {
            "visible": True,
            "title": "WhatsApp",
            "input_receipt_state": "enabled",
            "input_receipt": {
                "schema": "hermes.wasm_agent.native_web_surface_input_receipt.v1",
                "id": "receipt-7",
                "surface_id": "browser",
                "at": "2026-08-20T15:59:59.250Z",
                "action": "pointer.primary_gesture",
                "outcome": "observed_pre_dispatch",
                "button": "left",
                "input_source": "unattributed_native_input",
                "x": 123,
                "y": 46,
                "viewport": {"width": 800, "height": 600},
                "current_document": True,
                "age_ms": 750,
                "redacted": True,
            },
        }})
        self.assertEqual(
            answer,
            "Yes—I can inspect the Browser widget. It is visible. It has WhatsApp loaded. "
            "The native Browser boundary observed a recent unattributed primary pointer gesture before page dispatch at (123, 46) within a viewport measuring 800×600 pixels "
            "on the current loaded document, 750 ms ago. This receipt does not identify its physical source, a DOM target, or successful page handling.",
        )

        without_coordinates = client_ui_actions._browser_answer({"proof": ["native.web_surface.input_receipt"], "browser": {
            "input_receipt_state": "enabled",
            "input_receipt": {
                "schema": "hermes.wasm_agent.native_web_surface_input_receipt.v1",
                "action": "pointer.primary_gesture",
                "outcome": "observed_pre_dispatch",
                "button": "left",
                "input_source": "unattributed_native_input",
                "current_document": True,
                "age_ms": 2000,
                "redacted": True,
            },
        }})
        self.assertIn("no fresh primary pointer gesture was observed in the last 120 seconds", without_coordinates)

    def test_browser_answer_explains_input_receipt_states(self) -> None:
        disabled = client_ui_actions._browser_answer({"browser": {"input_receipt_state": "disabled"}})
        enabled = client_ui_actions._browser_answer({"browser": {"input_receipt_state": "enabled", "input_receipt": None}})
        unsupported = client_ui_actions._browser_answer({"browser": {"input_receipt_state": "unsupported"}})
        self.assertIn("enable Agent in the Browser widget before the next gesture", disabled)
        self.assertIn("no fresh primary pointer gesture was observed in the last 120 seconds", enabled)
        self.assertIn("installed shell lacks Browser input-receipt support", unsupported)

    def test_synthetic_browser_answer_proves_plumbing_not_physical_click(self) -> None:
        answer = client_ui_actions._browser_answer({"proof": ["native.web_surface.input_receipt"], "browser": {
            "visible": True,
            "input_receipt_state": "enabled",
            "input_receipt": {
                "schema": "hermes.wasm_agent.native_web_surface_input_receipt.v1",
                "id": "receipt-synthetic",
                "surface_id": "browser",
                "action": "pointer.primary_gesture",
                "outcome": "observed_pre_dispatch",
                "button": "left",
                "input_source": "electron_synthetic",
                "command_id": "cmd-pointer-7",
                "x": 10,
                "y": 20,
                "viewport": {"width": 800, "height": 600},
                "current_document": True,
                "age_ms": 50,
                "redacted": True,
            },
        }})
        self.assertIn("synthetic Electron pointer dispatch", answer)
        self.assertIn("proves the bounded dispatch/receipt plumbing", answer)
        self.assertIn("not a physical user click", answer)

    def test_browser_input_controls_queue_exact_bounded_payloads(self) -> None:
        queued = []
        capabilities = ["control.browser.input_receipt", "control.browser.pointer.dispatch"]
        for arguments, expected_type, expected_payload in (
            ({"operation": "browser_input_receipt", "enabled": True, "wait_sec": 0}, "browser_input_receipt", {"enabled": True}),
            ({"operation": "browser_pointer_dispatch", "x": 123, "y": 456, "wait_sec": 0}, "browser_pointer_dispatch", {"x": 123, "y": 456}),
        ):
            with self.subTest(operation=expected_type):
                result = client_ui_actions.execute(
                    arguments, self.route(), list_clients=lambda: self.clients(capabilities),
                    queue_command=lambda command: queued.append(command) or {"command_id": f"cmd-{expected_type}"},
                    read_command=lambda _device, _command: {"status": "finished", "result": {"ok": True}},
                )
                self.assertTrue(result["ok"])
                self.assertEqual(queued[-1]["type"], expected_type)
                self.assertEqual(queued[-1]["payload"], expected_payload)

        invalid = client_ui_actions.execute(
            {"operation": "browser_pointer_dispatch", "x": 1, "y": 2, "command_id": "model-value"},
            self.route(), list_clients=lambda: self.clients(capabilities),
            queue_command=lambda _command: self.fail("invalid pointer payload must not queue"),
            read_command=lambda *_args: {},
        )
        self.assertEqual(invalid["code"], "client_ui_arguments_invalid")

        non_boolean = client_ui_actions.execute(
            {"operation": "browser_input_receipt", "enabled": 1}, self.route(),
            list_clients=lambda: self.clients(capabilities),
            queue_command=lambda _command: self.fail("invalid receipt config must not queue"),
            read_command=lambda *_args: {},
        )
        self.assertEqual(non_boolean["code"], "client_browser_input_receipt_invalid")

    def test_full_power_controls_queue_arbitrary_source_and_commands(self) -> None:
        queued = []
        cases = (
            ({"operation": "windows_shell_execute_unrestricted", "command": "Get-ChildItem C:\\\\", "shell": "powershell", "cwd": "C:\\\\", "environment": {"X": "1"}, "timeout_ms": 90000, "wait_sec": 0}, ["windows.shell.execute.unrestricted"], {"command": "Get-ChildItem C:\\\\", "shell": "powershell", "cwd": "C:\\\\", "environment": {"X": "1"}, "timeout_ms": 90000}),
        )
        for arguments, capabilities, expected_payload in cases:
            result = client_ui_actions.execute(
                arguments, self.route(), list_clients=lambda caps=capabilities: self.clients(caps),
                queue_command=lambda command: queued.append(command) or {"command_id": "cmd-full-power"},
                read_command=lambda *_args: {"status": "finished", "result": {"ok": True}},
            )
            self.assertTrue(result["ok"])
            self.assertEqual(queued[-1]["payload"], expected_payload)

    def test_browser_javascript_requires_typed_observation_or_observed_postcondition(self) -> None:
        def execute(result_json: str) -> dict:
            return client_ui_actions.execute(
                {"operation": "browser_javascript_execute_unrestricted", "javascript": "run()", "wait_sec": 0},
                self.route(), list_clients=lambda: self.clients(["control.browser.javascript.execute.unrestricted"]),
                queue_command=lambda _command: {"command_id": "cmd-js"},
                read_command=lambda *_args: {"status": "finished", "result": {"ok": True, "browser": {"javascript_execution": {"result_json": result_json}}, "proof": ["native.web_surface.javascript.execute.unrestricted"]}},
            )

        unverified = execute('{"ok":true,"sent":true}')
        self.assertFalse(unverified["ok"])
        self.assertEqual(unverified["code"], "client_page_postcondition_unverified")
        observation = execute('{"observation":{"observed":true,"target":"conversation list","predicate":"Laura is present","result":true}}')
        self.assertTrue(observation["ok"])
        self.assertIs(observation["observation"]["observed"], True)
        self.assertEqual(observation["observation"]["result"], "true")
        self.assertIn("client.page.observation.observed", observation["proof"])
        broad_observation = execute('{"observation":{"observed":true,"target":"conversation list","predicate":"Laura is present","result":{"name":"Laura"}}}')
        self.assertFalse(broad_observation["ok"])
        verified = execute('{"postcondition":{"observed":true,"action":"message.send","target":"Laura","predicate":"outgoing message present","before":"count:4","after":"count:5"}}')
        self.assertTrue(verified["ok"])
        self.assertIn("client.page.postcondition.observed", verified["proof"])

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
        self.assertEqual(route["client_ui"]["runtime_types"], ["electron", "pwa", "android-kotlin"])
        self.assertIn("browser_inspect", route["client_ui"]["operations"])
        self.assertIn("space_open", route["client_ui"]["operations"])
        self.assertIn("browser_input_receipt", route["client_ui"]["operations"])
        self.assertIn("browser_pointer_dispatch", route["client_ui"]["operations"])
        self.assertIn("browser_javascript_execute_unrestricted", route["client_ui"]["operations"])
        self.assertIn("windows_shell_execute_unrestricted", route["client_ui"]["operations"])
        self.assertIn("client.ui.control", route["caps"])


if __name__ == "__main__":
    unittest.main()
