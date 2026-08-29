#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier import authority, client_ui_actions, route_contracts, tool_runtime  # noqa: E402
from master_frontier.v5 import policy  # noqa: E402


class ClientUiActionsTests(unittest.TestCase):
    def route(self) -> dict:
        return {"caps": ["client.ui.inspect", "client.ui.control"], "client_ui": {"runtime_types": ["electron"], "widget_ids": ["settings"], "operations": sorted(client_ui_actions.OPERATIONS)}, "task_contract": {"request_class": "conversation"}}

    def test_internal_native_control_port_declares_loopback_host(self) -> None:
        handler = tool_runtime.InternalHandler()
        self.assertEqual(handler.client_address[0], "127.0.0.1")
        self.assertEqual(handler.headers["Host"], "127.0.0.1")

    def test_native_failure_preserves_cdp_cause_and_recovery(self) -> None:
        result = client_ui_actions._result({"status": "finished", "result": {
            "ok": False, "rawResult": {"failureClassification": "windows_cdp_page_missing"},
        }}, {"client_id": "windows"}, "cmd-status")
        self.assertEqual(result["code"], "windows_cdp_page_missing")
        self.assertEqual(result["cause"], "windows_cdp_page_missing")
        self.assertTrue(result["recovery"]["recoverable"])
        self.assertEqual(result["recovery"]["next"], "client.windows.browser.cdp.default.open")

    def test_windows_desktop_projection_is_bounded_and_semantic(self) -> None:
        projection = client_ui_actions._windows_desktop_projection({
            "snapshot_id": "s-0123456789abcdef",
            "window": {"name": "Calculator", "process_name": "CalculatorApp"},
            "elements": [
                {"ref": f"e{index}", "name": f"Button {index}", "control_type": "Button", "runtime_id": [1, index], "patterns": ["select"], "selected": index == 0}
                for index in range(60)
            ],
        })

        self.assertEqual(projection["window"]["name"], "Calculator")
        self.assertEqual(len(projection["controls"]), 40)
        self.assertTrue(projection["snapshot_truncated"])
        self.assertNotIn("runtime_id", projection["controls"][0])
        self.assertEqual(projection["controls"][0]["patterns"], ["select"])
        self.assertTrue(projection["controls"][0]["selected"])
        self.assertEqual(projection["enumeration"], {
            "element_count": 60, "conversion_errors": 0, "tree_view": "control",
        })

    def clients(self, capabilities=None) -> dict:
        return {"clients": [{"client_id": "electron-a", "device_id": "electron-a", "runtime_type": "electron", "live": True, "capabilities": capabilities or ["control.widget.open", "control.space.open"], "route": "https://wa.colmeio.com/home?native=electron", "space_id": "admin", "space_name": "space-admin", "widget_manifest": "active-surface-v1", "widget_ids": ["settings"]}]}

    def test_route_exposes_distinct_client_tool(self) -> None:
        self.assertTrue(authority.tool_allowed("client", self.route()))
        descriptor = next(item for item in policy.descriptors_for(self.route()) if item["name"] == "client")
        self.assertIn("open_widget", descriptor["input_schema"]["properties"]["operation"]["enum"])
        self.assertIn("space_catalog", descriptor["input_schema"]["properties"]["operation"]["enum"])
        self.assertIn("space_open", descriptor["input_schema"]["properties"]["operation"]["enum"])
        self.assertIn("runtime_diagnose", descriptor["input_schema"]["properties"]["operation"]["enum"])
        self.assertIn("runtime_refresh", descriptor["input_schema"]["properties"]["operation"]["enum"])
        self.assertIn("windows_shell_execute_unrestricted", descriptor["input_schema"]["properties"]["operation"]["enum"])
        self.assertIn("show_companion_overlay", descriptor["input_schema"]["properties"]["operation"]["enum"])
        self.assertIn("run_notepad_uia_canary", descriptor["input_schema"]["properties"]["operation"]["enum"])
        self.assertIn("windows_desktop_inspect", descriptor["input_schema"]["properties"]["operation"]["enum"])
        self.assertIn("windows_desktop_act", descriptor["input_schema"]["properties"]["operation"]["enum"])
        self.assertEqual(descriptor["input_schema"]["properties"]["max_elements"]["maximum"], 200)

    def test_runtime_diagnose_and_refresh_use_declared_bounded_commands(self) -> None:
        queued = []
        for operation, capability, arguments, expected in (
            ("runtime_diagnose", "observe.runtime.diagnose", {"lease_ms": 15000}, {"lease_ms": 15000}),
            ("runtime_refresh", "control.runtime.refresh", {}, {}),
        ):
            result = client_ui_actions.execute(
                {"operation": operation, **arguments, "wait_sec": 0}, self.route(),
                list_clients=lambda capability=capability: self.clients([capability]),
                queue_command=lambda command: queued.append(command) or {"command_id": f"cmd-{operation}"},
                read_command=lambda *_args, operation=operation: {"status": "finished", "result": {
                    "ok": True,
                    "proof": ["client.runtime.diagnostic_snapshot" if operation == "runtime_diagnose" else "client.runtime.refresh.scheduled"],
                }},
            )
            self.assertTrue(result["ok"])
            self.assertEqual(queued[-1]["type"], operation)
            self.assertEqual(queued[-1]["payload"], expected)

    def test_companion_and_notepad_canary_queue_bounded_native_operations(self) -> None:
        queued = []
        for operation, capability, arguments, expected in (
            ("show_companion_overlay", "companion.overlay.show", {}, {}),
            ("run_notepad_uia_canary", "windows.desktop.notepad_uia_canary", {"canary": "proof-123", "timeout_ms": 30000}, {"canary": "proof-123", "timeout_ms": 30000}),
        ):
            with self.subTest(operation=operation):
                result = client_ui_actions.execute(
                    {"operation": operation, **arguments, "wait_sec": 0}, self.route(),
                    list_clients=lambda capability=capability: self.clients([capability]),
                    queue_command=lambda command: queued.append(command) or {"command_id": f"cmd-{operation}"},
                    read_command=lambda *_args, operation=operation: {"status": "finished", "result": {"ok": True, "independently_verified": operation == "run_notepad_uia_canary", "observed": "proof-123" if operation == "run_notepad_uia_canary" else ""}},
                )
                self.assertTrue(result["ok"])
                self.assertEqual(queued[-1]["type"], operation)
                self.assertEqual(queued[-1]["payload"], expected)

    def test_windows_desktop_inspect_act_and_prove_are_revision_bound(self) -> None:
        queued = []
        cases = (
            ("windows_desktop_inspect", "windows.desktop.inspect", {"target": {"title_contains": "Calculator"}, "max_elements": 40}, {"target": {"title_contains": "Calculator"}, "max_elements": 40, "max_depth": 12, "include_values": False, "timeout_ms": 15000}),
            ("windows_desktop_act", "windows.desktop.act", {"snapshot_id": "s-0123456789abcdef", "ref": "e2", "action": "set_value", "value": "42", "expect": {"property": "value", "equals": "42"}}, {"snapshot_id": "s-0123456789abcdef", "ref": "e2", "action": "set_value", "value": "42", "expect": {"property": "value", "equals": "42"}, "timeout_ms": 15000}),
            ("windows_desktop_prove", "windows.desktop.prove", {"snapshot_id": "s-0123456789abcdef", "ref": "e2", "expect": {"property": "value", "equals": "42"}}, {"snapshot_id": "s-0123456789abcdef", "ref": "e2", "expect": {"property": "value", "equals": "42"}, "timeout_ms": 15000}),
        )
        for operation, capability, arguments, expected in cases:
            with self.subTest(operation=operation):
                result = client_ui_actions.execute(
                    {"operation": operation, **arguments, "wait_sec": 0}, self.route(),
                    list_clients=lambda capability=capability: self.clients([capability]),
                    queue_command=lambda command: queued.append(command) or {"command_id": f"cmd-{operation}"},
                    read_command=lambda *_args, operation=operation: {"status": "finished", "result": {"ok": True, "window": {"name": "Calculator"} if operation == "windows_desktop_inspect" else {}, "independently_verified": True, "proof": ["windows.uia.postcondition"]}},
                )
                self.assertTrue(result["ok"])
                self.assertEqual(queued[-1]["payload"], expected)
                if operation != "windows_desktop_inspect":
                    self.assertIn("client.windows.uia.postcondition", result["proof"])

    def test_windows_desktop_windows_list_uses_bounded_downloaded_hot_operation(self) -> None:
        queued = []
        result = client_ui_actions.execute(
            {"operation": "windows_desktop_windows_list", "wait_sec": 0}, self.route(),
            list_clients=lambda: self.clients(["run_hot_operation"]),
            queue_command=lambda command: queued.append(command) or {"command_id": "cmd-windows"},
            read_command=lambda *_args: {"status": "finished", "result": {
                "ok": True, "hotOpSource": "downloaded", "rawResult": {
                    "schema": "hermes.wasm_agent.windows_open_apps.v1",
                    "operation": "inspect_windows_open_apps", "ok": True,
                    "windowCount": 2, "truncated": False,
                    "windows": [
                        {"title": "WASM Agent", "processName": "WASM Agent", "processId": 12, "visible": True, "minimized": False},
                        {"title": "notes.txt - Notepad", "processName": "Notepad", "processId": 44, "visible": True, "minimized": True},
                    ],
                },
            }},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(queued[0]["type"], "run_hot_operation")
        self.assertEqual(queued[0]["payload"], {"operationName": "inspect_windows_open_apps", "args": {}})
        self.assertEqual(result["model_projection"]["windowCount"], 2)
        self.assertEqual(result["model_projection"]["windows"][1]["processName"], "Notepad")
        self.assertEqual(result["proof"], ["client.ack", "windows.desktop.top_level_windows"])

    def test_windows_desktop_screenshot_returns_metadata_without_pixels(self) -> None:
        queued = []
        result = client_ui_actions.execute(
            {"operation": "windows_desktop_screenshot", "wait_sec": 0}, self.route(),
            list_clients=lambda: self.clients(["run_hot_operation"]),
            queue_command=lambda command: queued.append(command) or {"command_id": "cmd-shot"},
            read_command=lambda *_args: {"status": "finished", "result": {
                "ok": True, "hotOpSource": "downloaded", "rawResult": {
                    "schema": "hermes.wasm_agent.windows_desktop_screenshot.v1",
                    "operation": "capture_windows_desktop_screenshot", "ok": True,
                    "artifact": {"path": "C:\\proof.png", "sha256": "a" * 64, "width": 1920, "height": 1080, "left": 0, "top": 0, "capturedAt": "now", "scope": "virtual_desktop", "containsSensitivePixels": True},
                    "proof": ["windows.desktop.screenshot"],
                },
            }},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(queued[0]["payload"], {"operationName": "capture_windows_desktop_screenshot", "args": {}})
        self.assertNotIn("pixels", result["model_projection"])
        self.assertEqual(result["proof"], ["client.ack", "windows.desktop.screenshot"])
        self.assertIn("1920×1080", result["answer"])

    def test_windows_default_cdp_resolves_to_verified_persistent_realm(self) -> None:
        queued = []
        result = client_ui_actions.execute(
            {"operation": "windows_browser_cdp_persistent_open", "wait_sec": 0}, self.route(),
            list_clients=lambda: self.clients(["run_hot_operation"]),
            queue_command=lambda command: queued.append(command) or {"command_id": "cmd-cdp"},
            read_command=lambda *_args: {"status": "finished", "result": {
                "ok": True, "hotOpSource": "downloaded", "rawResult": {
                    "schema": "hermes.wasm_agent.windows_cdp_session.v1",
                    "operation": "open_windows_cdp_persistent", "ok": True,
                    "realm": "browser_cdp_persistent", "defaultRealm": True,
                    "sessionId": "browser-cdp-persistent", "processId": 91, "port": 49152,
                    "endpoint": "http://127.0.0.1:49152", "settings": "Chrome/140",
                    "protocolVersion": "1.3", "webSocketDebuggerUrl": "ws://127.0.0.1:49152/devtools/browser/abc",
                    "profile": "wasm_agent_persistent", "storage": "durable",
                    "isolation": "dedicated_profile", "cleanup": "retain_on_browser_exit",
                },
            }},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(queued[0]["type"], "run_hot_operation")
        self.assertEqual(queued[0]["payload"]["operationName"], "open_windows_cdp_persistent")
        self.assertEqual(result["proof"], ["client.ack", "windows.browser.cdp.persistent.ready"])
        self.assertIn("http://127.0.0.1:49152", result["answer"])
        self.assertIn("retains authenticated state", result["answer"])

    def test_windows_cdp_navigation_returns_observed_target_proof(self) -> None:
        queued = []
        result = client_ui_actions.execute(
            {"operation": "windows_browser_cdp_navigate", "url": "https://web.whatsapp.com", "wait_sec": 0}, self.route(),
            list_clients=lambda: self.clients(["run_hot_operation"]),
            queue_command=lambda command: queued.append(command) or {"command_id": "cmd-cdp-nav"},
            read_command=lambda *_args: {"status": "finished", "result": {
                "ok": True, "hotOpSource": "downloaded", "rawResult": {
                    "schema": "hermes.wasm_agent.windows_cdp_navigation.v1",
                    "operation": "navigate_windows_cdp_persistent", "ok": True,
                    "realm": "browser_cdp_persistent", "requestedUrl": "https://web.whatsapp.com/",
                    "observedUrl": "https://web.whatsapp.com/", "targetId": "target-1",
                    "proof": ["windows.browser.cdp.navigation.observed"],
                    "answer": "Navigated the persistent CDP browser to https://web.whatsapp.com/",
                },
            }},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(queued[0]["payload"], {
            "operationName": "navigate_windows_cdp_persistent",
            "args": {"url": "https://web.whatsapp.com"},
        })
        self.assertEqual(result["proof"], ["client.ack", "windows.browser.cdp.navigation.observed"])
        self.assertIn("web.whatsapp.com", result["answer"])

    def test_windows_cdp_inspect_and_act_return_bounded_native_proof(self) -> None:
        queued = []
        responses = iter([
            {"status": "finished", "result": {"ok": True, "rawResult": {
                "schema": "hermes.wasm_agent.windows_cdp_inspection.v1", "operation": "inspect_windows_cdp_persistent",
                "ok": True, "targetId": "target-1", "url": "https://web.whatsapp.com/", "title": "WhatsApp",
                "controls": [{"ref": "c1", "locator": "#laura", "name": "Laura"}], "text": "Laura",
                "matches": [{"ref": "t1", "locator": "#laura", "actionLocator": "text=Laura", "name": "Laura", "ancestry": [{"role": "row"}], "hit": {"name": "Laura"}}],
                "selectorMatches": [{"ref": "s1", "locator": "#composer", "role": "textbox", "ancestry": []}],
                "editableTargets": [{"ref": "e1", "locator": "#composer", "scopeLocator": "#main", "role": "textbox", "name": "Message Laura"}],
                "proof": ["windows.browser.cdp.dom.snapshot"],
            }}},
            {"status": "finished", "result": {"ok": True, "rawResult": {
                "schema": "hermes.wasm_agent.windows_cdp_action.v1", "operation": "act_windows_cdp_persistent",
                "ok": True, "targetId": "target-1", "action": "click", "observed": {"name": "Laura"},
                "postconditionVerified": True, "proof": ["windows.browser.cdp.action.observed"],
            }}},
        ])
        common = dict(
            route=self.route(), list_clients=lambda: self.clients(["run_hot_operation"]),
            queue_command=lambda command: queued.append(command) or {"command_id": f"cmd-{len(queued)}"},
            read_command=lambda *_args: next(responses),
        )
        inspected = client_ui_actions.execute({
            "operation": "windows_browser_cdp_inspect", "target_url": "https://web.whatsapp.com",
            "query_text": "Laura", "query_selector": "[contenteditable=true]", "wait_sec": 0,
        }, **common)
        acted = client_ui_actions.execute({"operation": "windows_browser_cdp_act", "locator": "#laura", "action": "click", "expect": {"property": "name", "equals": "Laura"}, "wait_sec": 0}, **common)
        self.assertTrue(inspected["ok"])
        self.assertEqual(inspected["model_projection"]["controls"][0]["name"], "Laura")
        self.assertEqual(inspected["model_projection"]["matches"][0]["ref"], "t1")
        self.assertEqual(inspected["model_projection"]["matches"][0], {"ref": "t1", "actionLocator": "text=Laura", "name": "Laura"})
        self.assertEqual(inspected["model_projection"]["selectorMatches"][0]["ref"], "s1")
        self.assertEqual(inspected["model_projection"]["editableTargets"][0]["scopeLocator"], "#main")
        self.assertTrue(acted["ok"])
        self.assertEqual(acted["proof"], ["client.ack", "windows.browser.cdp.action.observed"])
        self.assertEqual([item["payload"]["operationName"] for item in queued], ["inspect_windows_cdp_persistent", "act_windows_cdp_persistent"])
        self.assertEqual(queued[0]["payload"]["args"]["query_text"], "Laura")
        self.assertEqual(queued[0]["payload"]["args"]["query_selector"], "[contenteditable=true]")

    def test_windows_cdp_action_failure_projects_postcondition_evidence(self) -> None:
        result = client_ui_actions.execute(
            {
                "operation": "windows_browser_cdp_act", "locator": "#target", "action": "click",
                "expect": {"property": "page_text_contains", "equals": "Target"}, "wait_sec": 0,
            },
            route=self.route(), list_clients=lambda: self.clients(["run_hot_operation"]),
            queue_command=lambda _command: {"command_id": "cmd-preexisting"},
            read_command=lambda *_args: {"status": "finished", "result": {"ok": True, "rawResult": {
                "schema": "hermes.wasm_agent.windows_cdp_action.v1", "operation": "act_windows_cdp_persistent",
                "ok": False, "targetId": "target-1", "action": "click", "changed": ["page_text"],
                "failedStepIndex": 1, "failedAction": "set_value", "failedLocator": "text=Type a message",
                "recovery": {"queryText": "Type a message", "querySelector": "[contenteditable=true],textarea,input", "matches": [], "selectorMatches": [{"locator": "#composer", "editable": True}]},
                "observed": {"name": "Target", "page_text": "Target after unrelated change", "controls": []},
                "postconditionVerified": False, "failureClassification": "browser_postcondition_preexisting",
                "postcondition": {"property": "page_text_contains", "beforeMatched": True, "afterMatched": True, "transitioned": False},
                "proof": [],
            }}},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "windows_cdp_action_unverified")
        self.assertEqual(result["model_projection"]["failureClassification"], "browser_postcondition_preexisting")
        self.assertFalse(result["model_projection"]["postcondition"]["transitioned"])
        self.assertEqual(result["model_projection"]["failedStepIndex"], 1)
        self.assertEqual(result["model_projection"]["failedLocator"], "text=Type a message")
        self.assertEqual(result["model_projection"]["recovery"]["selectorMatches"][0]["locator"], "#composer")

    def test_windows_cdp_runtime_inspect_is_getter_safe_and_bounded(self) -> None:
        queued = []
        result = client_ui_actions.execute(
            {"operation": "windows_browser_cdp_runtime_inspect", "locator": "text=hi", "max_ancestors": 6, "max_properties": 40, "wait_sec": 0},
            self.route(), list_clients=lambda: self.clients(["run_hot_operation"]),
            queue_command=lambda command: queued.append(command) or {"command_id": "cmd-runtime"},
            read_command=lambda *_args: {"status": "finished", "result": {"ok": True, "rawResult": {
                "schema": "hermes.wasm_agent.windows_cdp_runtime_inspection.v1", "operation": "inspect_windows_cdp_runtime", "ok": True,
                "read_only": True, "getter_invocations": 0, "targetId": "page-1", "revision": "r-1234", "handle": "webobj:1234",
                "document": {"url": "https://example.test/"}, "selection": {"found": True, "text": "hi"},
                "ancestors": [], "prototypes": [], "globals": [], "budgets": {"max_ancestors": 6, "max_properties": 40},
                "proof": ["windows.browser.cdp.runtime.snapshot"],
            }}},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(queued[0]["payload"]["operationName"], "inspect_windows_cdp_runtime")
        self.assertEqual(queued[0]["payload"]["args"]["locator"], "text=hi")
        self.assertEqual(result["model_projection"]["handle"], "webobj:1234")
        self.assertEqual(result["model_projection"]["selection"]["text"], "hi")
        self.assertLess(len(json.dumps(result["model_projection"])), 12_000)
        self.assertEqual(result["proof"], ["client.ack", "windows.browser.cdp.runtime.snapshot"])
        self.assertIn("was found", result["answer"])
        self.assertIn("targetId page-1", result["answer"])
        self.assertIn("read-only with zero getter invocations", result["answer"])

    def test_windows_cdp_procedure_requires_every_scoped_assertion(self) -> None:
        queued = []
        arguments = {
            "operation": "windows_browser_cdp_procedure",
            "page_target_id": "page-target-1",
            "steps": [
                {"locator": "#composer", "action": "set_value", "value": "hi", "target_contract": {"role": "textbox", "name_contains": "message", "scope_locator": "#conversation", "editable": True}},
                {"locator": "#composer", "action": "key", "key": "Enter", "target_contract": {"role": "textbox", "name_contains": "message", "scope_locator": "#conversation", "editable": True}},
            ],
            "assertions": [{"id": "sent", "selector": ".outgoing", "scope_locator": "#conversation", "property": "last_text", "transition": "became_equal", "equals": "hi"}],
            "wait_sec": 0,
        }
        base = dict(route=self.route(), list_clients=lambda: self.clients(["run_hot_operation"]), queue_command=lambda command: queued.append(command) or {"command_id": "cmd-procedure"})
        passed = client_ui_actions.execute(arguments, read_command=lambda *_args: {"status": "finished", "result": {"ok": True, "rawResult": {
            "schema": "hermes.wasm_agent.windows_cdp_procedure.v1", "operation": "execute_windows_cdp_procedure", "ok": True,
            "action": {"dispatched": True, "steps": []}, "observation": {"url": "https://example.test"},
            "completion_proof": {"ok": True, "assertions": [{"id": "sent", "passed": True}]},
            "proof": ["windows.browser.cdp.procedure.completed"],
        }}}, **base)
        self.assertTrue(passed["ok"])
        self.assertEqual(passed["proof"], ["client.ack", "windows.browser.cdp.procedure.completed"])
        self.assertEqual(queued[0]["payload"]["args"]["page_target_id"], "page-target-1")
        self.assertEqual(queued[0]["payload"]["args"]["steps"], arguments["steps"])
        self.assertEqual(queued[0]["payload"]["args"]["assertions"], arguments["assertions"])
        failed = client_ui_actions.execute(arguments, read_command=lambda *_args: {"status": "finished", "result": {"ok": True, "rawResult": {
            "schema": "hermes.wasm_agent.windows_cdp_procedure.v1", "operation": "execute_windows_cdp_procedure", "ok": False,
            "action": {"dispatched": True, "steps": []}, "observation": {"url": "https://example.test"},
            "completion_proof": {"ok": False, "assertions": [{"id": "sent", "passed": False}]},
            "failureClassification": "commit_unknown", "proof": [],
        }}}, **base)
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["cause"], "commit_unknown")
        self.assertEqual(failed["recovery"], {"recoverable": True, "next": "client.windows.browser.cdp.inspect"})
        self.assertTrue(failed["model_projection"]["action"]["dispatched"])

    def test_windows_desktop_inspect_rejects_an_unrelated_fallback_window(self) -> None:
        result = client_ui_actions.execute(
            {"operation": "windows_desktop_inspect", "target": {"title_contains": "Visual Studio Code"}, "wait_sec": 0},
            self.route(),
            list_clients=lambda: self.clients(["windows.desktop.inspect"]),
            queue_command=lambda _command: {"command_id": "cmd-target"},
            read_command=lambda *_args: {"status": "finished", "result": {
                "ok": True, "window": {"name": "Program Manager"}, "elements": [], "proof": ["windows.uia.snapshot"],
            }},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "windows_desktop_target_mismatch")

    def test_surface_manifest_separates_route_declaration_from_live_availability(self) -> None:
        client = self.clients()["clients"][0]
        manifest = client_ui_actions.surface_manifest(client, self.route()["client_ui"])
        self.assertEqual(manifest["widget_ids"], ["settings"])
        self.assertEqual(manifest["available_widget_ids"], ["settings"])
        client.update({"space_id": "home", "space_name": "space-home", "widget_ids": []})
        manifest = client_ui_actions.surface_manifest(client, self.route()["client_ui"])
        self.assertEqual(manifest["widget_ids"], ["settings"])
        self.assertEqual(manifest["available_widget_ids"], [])
        self.assertEqual(manifest["space_name"], "space-home")

    def test_open_browser_widget_requires_and_returns_client_ack(self) -> None:
        queued = []
        result = client_ui_actions.execute(
            {"operation": "open_widget", "widget_id": "settings", "wait_sec": 0}, self.route(),
            list_clients=self.clients,
            queue_command=lambda command: queued.append(command) or {"command_id": "cmd-1"},
            read_command=lambda _device, _command: {"status": "finished", "result": {"ok": True, "widget_id": "settings", "opened": True, "visible": True, "proof": ["client.widget.visible"]}},
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["acknowledged"])
        self.assertEqual(queued[0]["type"], "open_widget")
        self.assertEqual(queued[0]["payload"], {"widget_id": "settings"})
        self.assertEqual(result["proof"], ["client.ack", "client.widget.visible"])
        self.assertIn("verified it is visible", result["answer"])

    def test_space_catalog_is_bounded_and_intersected_with_route_widgets(self) -> None:
        queued = []
        result = client_ui_actions.execute(
            {"operation": "space_catalog", "wait_sec": 0}, self.route(),
            list_clients=lambda: self.clients(["observe.spaces.catalog"]),
            queue_command=lambda command: queued.append(command) or {"command_id": "cmd-catalog"},
            read_command=lambda *_args: {"status": "finished", "result": {
                "ok": True, "manifest": "space-catalog-v1", "proof": ["client.space.catalog"], "truncated": False,
                "spaces": [
                    {"id": "home", "name": "space-home", "kind": "home", "active": True, "widget_ids": []},
                    {"id": "admin", "name": "space-admin", "kind": "admin", "active": False, "widget_ids": ["settings", "settings"]},
                ],
            }},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(queued[0]["type"], "space_catalog")
        self.assertEqual(queued[0]["payload"], {})
        self.assertEqual(result["proof"], ["client.space.catalog"])
        self.assertEqual(result["catalog"]["spaces"][0]["widget_ids"], [])
        self.assertEqual(result["catalog"]["spaces"][1]["widget_ids"], ["settings"])

    def test_space_catalog_requires_manifest_and_proof(self) -> None:
        result = client_ui_actions.execute(
            {"operation": "space_catalog", "wait_sec": 0}, self.route(),
            list_clients=lambda: self.clients(["observe.spaces.catalog"]),
            queue_command=lambda _command: {"command_id": "cmd-bad-catalog"},
            read_command=lambda *_args: {"status": "finished", "result": {"ok": True, "spaces": []}},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "client_space_catalog_unverified")

    def test_space_home_rejects_widget_not_in_active_surface_before_queue(self) -> None:
        clients = self.clients()
        clients["clients"][0].update({"space_id": "home", "space_name": "space-home", "widget_ids": []})
        result = client_ui_actions.execute(
            {"operation": "open_widget", "widget_id": "settings", "wait_sec": 0}, self.route(),
            list_clients=lambda: clients,
            queue_command=lambda _command: self.fail("unavailable active-surface widget must not queue"),
            read_command=lambda *_args: {},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "client_widget_unavailable_on_active_surface")
        self.assertEqual(result["available_widget_ids"], [])
        self.assertIn("space-home", result["summary"])

    def test_widget_success_requires_visible_postcondition_proof(self) -> None:
        result = client_ui_actions.execute(
            {"operation": "open_widget", "widget_id": "settings", "wait_sec": 0}, self.route(),
            list_clients=self.clients,
            queue_command=lambda _command: {"command_id": "cmd-unverified"},
            read_command=lambda *_args: {"status": "finished", "result": {"ok": True, "widget_id": "settings", "opened": True}},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "client_widget_postcondition_unverified")

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

    def test_widget_and_runtime_capability_are_fail_closed(self) -> None:
        denied = client_ui_actions.execute(
            {"operation": "open_widget", "widget_id": "undeclared", "wait_sec": 0}, self.route(),
            list_clients=self.clients, queue_command=lambda _command: {}, read_command=lambda *_args: {},
        )
        missing = client_ui_actions.execute(
            {"operation": "open_widget", "widget_id": "settings", "wait_sec": 0}, self.route(),
            list_clients=lambda: self.clients(["observe.status"]), queue_command=lambda _command: {}, read_command=lambda *_args: {},
        )
        self.assertEqual(denied["code"], "client_widget_denied")
        self.assertEqual(missing["code"], "live_electron_client_missing")

    def test_control_requires_separate_route_capability(self) -> None:
        route = self.route()
        route["caps"].remove("client.ui.control")
        result = client_ui_actions.execute(
            {"operation": "open_widget", "widget_id": "settings", "wait_sec": 0}, route,
            list_clients=self.clients, queue_command=lambda _command: {}, read_command=lambda *_args: {},
        )
        self.assertEqual(result["code"], "client_ui_control_denied")

    def test_avatar_route_preserves_client_ui_contract(self) -> None:
        plugin_root = Path(__file__).resolve().parents[1]
        loaded = route_contracts.load_contracts(plugin_root / "server/agent_route_contracts.json", plugin_root)
        route = next(item for item in loaded if item["route_id"] == "wasm-agent.avatar-chat.ui")
        self.assertEqual(route["client_ui"]["widget_ids"], [])
        self.assertEqual(route["client_ui"]["runtime_types"], ["electron", "pwa", "android-kotlin"])
        self.assertNotIn("browser_inspect", route["client_ui"]["operations"])
        self.assertIn("space_open", route["client_ui"]["operations"])
        self.assertIn("space_catalog", route["client_ui"]["operations"])
        self.assertIn("windows_shell_execute_unrestricted", route["client_ui"]["operations"])
        self.assertIn("client.ui.control", route["caps"])


if __name__ == "__main__":
    unittest.main()
