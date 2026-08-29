#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))
import live_clients  # noqa: E402


class LiveClientsTest(unittest.TestCase):
    def test_unifies_pwa_electron_and_android_and_marks_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live_clients.save_client(root, {"device_id": "pwa-a", "runtime_type": "pwa", "received_at": "2026-08-01T12:00:00Z", "route": "https://wa.colmeio.com/home"}, now_epoch=1785585600)
            native = root / "native-control"
            heartbeats = native / "heartbeats"
            heartbeats.mkdir(parents=True)
            (heartbeats / "win-a.json").write_text(json.dumps({"device_id": "win-a", "runtime": "electron", "received_at": "2026-08-01T12:00:10Z"}))
            (heartbeats / "android-a.json").write_text(json.dumps({"device_id": "android-a", "received_at": "2026-08-01T11:55:00Z"}))
            result = live_clients.list_clients(root, native_root=native, now_epoch=1785585630)
            by_id = {item["client_id"]: item for item in result["clients"]}
            self.assertEqual(by_id["pwa-a"]["runtime_type"], "pwa")
            self.assertEqual(by_id["win-a"]["runtime_type"], "electron")
            self.assertEqual(by_id["android-a"]["runtime_type"], "android-kotlin")
            self.assertTrue(by_id["pwa-a"]["live"])
            self.assertFalse(by_id["android-a"]["live"])
            self.assertEqual(result["live_count"], 2)

    def test_capabilities_are_bounded(self) -> None:
        client = live_clients.normalize_client({"device_id": "x", "runtime_type": "pwa", "capabilities": [f"cap.{i}" for i in range(50)]})
        self.assertEqual(len(client["capabilities"]), 32)

    def test_missing_or_blank_capabilities_never_fabricate_control(self) -> None:
        missing = live_clients.normalize_client({"device_id": "win-a", "runtime_type": "electron"})
        blank = live_clients.normalize_client({"device_id": "win-b", "runtime_type": "electron", "capabilities": [""]})
        self.assertEqual(missing["capabilities"], [])
        self.assertEqual(blank["capabilities"], [])

    def test_active_surface_widget_manifest_is_explicit_and_bounded(self) -> None:
        heartbeat = live_clients.heartbeat_from_query({
            "device_id": ["electron-a"], "runtime_type": ["electron"],
            "space_id": ["home"], "space_name": ["space-home"],
            "widget_manifest": [live_clients.ACTIVE_SURFACE_MANIFEST],
            "widget_ids": ["browser,browser,artifact-foundry"],
            "capabilities": ["control.widget.open,observe.status"],
        }, remote_addr="127.0.0.1", received_at="2026-08-25T12:00:00Z")
        self.assertEqual(heartbeat["widget_ids"], ["artifact-foundry", "browser"])
        client = live_clients.normalize_client(heartbeat, now_epoch=1787659200)
        self.assertEqual(client["widget_manifest"], live_clients.ACTIVE_SURFACE_MANIFEST)
        self.assertEqual(client["widget_ids"], ["artifact-foundry", "browser"])
        self.assertEqual(client["space_name"], "space-home")

        legacy = live_clients.normalize_client({"device_id": "electron-old", "runtime_type": "electron"})
        self.assertEqual(legacy["widget_manifest"], "")
        self.assertEqual(legacy["widget_ids"], [])

    def test_proved_space_result_advances_cached_surface_without_waiting_for_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live_clients.save_client(root, {
                "device_id": "electron-a", "runtime_type": "electron", "received_at": "2026-08-25T12:00:00Z",
                "space_id": "home", "space_name": "space-home", "widget_manifest": "active-surface-v1",
                "widget_ids": [], "capabilities": ["control.widget.open", "observe.spaces.catalog"],
            })
            updated = live_clients.apply_command_result_surface(root, "electron-a", "space_open", {
                "ok": True, "space_id": "admin", "space_name": "space-admin",
                "surface": {"manifest": "active-surface-v1", "space_id": "admin", "space_name": "space-admin", "widget_ids": ["browser"]},
            }, received_at="2026-08-25T12:00:01Z")
            self.assertEqual(updated["space_id"], "admin")
            self.assertEqual(updated["widget_ids"], ["browser"])
            self.assertIn("observe.spaces.catalog", updated["capabilities"])
            self.assertIsNone(live_clients.apply_command_result_surface(root, "electron-a", "space_open", {
                "ok": True, "space_id": "admin", "surface": {"manifest": "wrong", "space_id": "admin"},
            }, received_at="2026-08-25T12:00:02Z"))

    def test_browser_control_registry_and_payloads_are_bounded(self) -> None:
        self.assertEqual(
            live_clients.BROWSER_CONTROL_COMMAND_TYPES,
            {"open_widget", "space_open", "browser_navigate", "browser_input_receipt", "browser_pointer_dispatch", "browser_transaction", "browser_javascript_execute_unrestricted"},
        )
        self.assertIn("space_catalog", live_clients.CLIENT_COMMAND_TYPES)
        self.assertEqual(live_clients.CLIENT_OPERATOR_COMMANDS["space_catalog"], "space_catalog")
        self.assertEqual(
            live_clients.normalize_control_payload("browser_input_receipt", {"enabled": False}),
            {"enabled": False},
        )
        self.assertEqual(
            live_clients.normalize_control_payload(
                "browser_pointer_dispatch", {"x": 123, "y": 456}, command_id="cmd:pointer-7",
            ),
            {"x": 123, "y": 456, "command_id": "cmd-pointer-7"},
        )
        self.assertEqual(
            live_clients.normalize_control_payload("browser_javascript_execute_unrestricted", {"javascript": "document.title"}),
            {"javascript": "document.title"},
        )
        transaction = {"transactionId": "tx-1", "steps": [{"op": "click", "selector": "#send"}], "postconditions": [{"selector": ".outgoing", "property": "text", "equals": "hi"}]}
        self.assertEqual(
            live_clients.normalize_control_payload("browser_transaction", {"transaction": transaction}),
            {"transaction": transaction},
        )
        self.assertEqual(
            live_clients.normalize_control_payload("windows_shell_execute_unrestricted", {"command": "whoami"}),
            {"command": "whoami", "shell": "powershell", "cwd": "", "environment": {}, "timeout_ms": 60000},
        )
        self.assertEqual(live_clients.normalize_control_payload("show_companion_overlay", {}), {})
        self.assertEqual(live_clients.normalize_control_payload("runtime_refresh", {}), {})
        self.assertIn("agent_prompt_submit", live_clients.CLIENT_COMMAND_TYPES)
        self.assertIn("agent_session_new", live_clients.CLIENT_COMMAND_TYPES)
        self.assertEqual(live_clients.normalize_control_payload("agent_session_new", {}), {})
        self.assertEqual(
            live_clients.normalize_control_payload("agent_prompt_submit", {"message": "hello"}),
            {"message": "hello"},
        )
        self.assertEqual(live_clients.normalize_control_payload("runtime_diagnose", {"lease_ms": 15000}), {"lease_ms": 15000})
        self.assertEqual(
            live_clients.normalize_control_payload("run_notepad_uia_canary", {"canary": "proof-123"}),
            {"canary": "proof-123", "timeout_ms": 30000},
        )
        self.assertEqual(
            live_clients.normalize_control_payload("windows_desktop_inspect", {"target": {"title_contains": "Calculator"}, "max_elements": 40}),
            {"target": {"title_contains": "Calculator"}, "max_elements": 40, "max_depth": 12, "include_values": False, "timeout_ms": 15000},
        )
        self.assertEqual(
            live_clients.normalize_control_payload("windows_desktop_act", {"snapshot_id": "s-0123456789abcdef", "ref": "e2", "action": "set_value", "value": "42", "expect": {"property": "value", "equals": "42"}}),
            {"snapshot_id": "s-0123456789abcdef", "ref": "e2", "action": "set_value", "timeout_ms": 15000, "value": "42", "expect": {"property": "value", "equals": "42"}},
        )
        self.assertEqual(
            live_clients.normalize_control_payload("windows_desktop_prove", {"snapshot_id": "s-0123456789abcdef", "ref": "e2", "expect": {"property": "enabled", "equals": True}}),
            {"snapshot_id": "s-0123456789abcdef", "ref": "e2", "expect": {"property": "enabled", "equals": True}, "timeout_ms": 15000},
        )
        for command, payload in (
            ("browser_input_receipt", {"enabled": 1}),
            ("browser_input_receipt", {"enabled": True, "extra": "denied"}),
            ("browser_pointer_dispatch", {"x": True, "y": 4}),
            ("browser_pointer_dispatch", {"x": 1.5, "y": 4}),
            ("browser_pointer_dispatch", {"x": 65_536, "y": 4}),
            ("browser_pointer_dispatch", {"x": 3, "y": 4, "command_id": "model-supplied"}),
            ("browser_javascript_execute_unrestricted", {"javascript": ""}),
            ("browser_transaction", {"transaction": []}),
            ("windows_shell_execute_unrestricted", {"command": "whoami", "shell": "bash"}),
            ("show_companion_overlay", {"hidden": True}),
            ("agent_prompt_submit", {"message": ""}),
            ("agent_prompt_submit", {"message": "hello", "extra": True}),
            ("run_notepad_uia_canary", {"canary": ""}),
            ("windows_desktop_inspect", {"max_elements": 201}),
            ("windows_desktop_act", {"snapshot_id": "stale", "ref": "e1", "action": "invoke"}),
            ("windows_desktop_prove", {"snapshot_id": "s-0123456789abcdef", "ref": "e1", "expect": {"property": "secret", "equals": "x"}}),
        ):
            with self.subTest(command=command, payload=payload), self.assertRaises(ValueError):
                live_clients.normalize_control_payload(command, payload)

    def test_device_identity_is_canonical_across_heartbeat_case(self) -> None:
        heartbeat = live_clients.heartbeat_from_query({
            "device_id": ["win-DESKTOP-MG9DJTG-aac75f59c54ad"],
            "runtime_type": ["electron"],
        })
        self.assertEqual(heartbeat["device_id"], "win-desktop-mg9djtg-aac75f59c54ad")

    def test_strict_operator_payload_keeps_audit_metadata_out_of_renderer_message(self) -> None:
        metadata = {"frontier_command": "browser_input_receipt", "requested_by": "operator"}
        self.assertEqual(
            live_clients.operator_control_payload("browser_input_receipt", {"enabled": True}, metadata),
            {"enabled": True},
        )
        self.assertEqual(
            live_clients.operator_control_payload("open_widget", {"widget_id": "browser"}, metadata),
            {"widget_id": "browser", **metadata},
        )


if __name__ == "__main__":
    unittest.main()
