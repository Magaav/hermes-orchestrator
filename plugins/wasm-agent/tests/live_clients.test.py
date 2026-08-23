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

    def test_browser_control_registry_and_payloads_are_bounded(self) -> None:
        self.assertEqual(
            live_clients.BROWSER_CONTROL_COMMAND_TYPES,
            {"open_widget", "space_open", "browser_navigate", "browser_input_receipt", "browser_pointer_dispatch", "browser_javascript_execute_unrestricted"},
        )
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
        self.assertEqual(
            live_clients.normalize_control_payload("windows_shell_execute_unrestricted", {"command": "whoami"}),
            {"command": "whoami", "shell": "powershell", "cwd": "", "environment": {}, "timeout_ms": 60000},
        )
        for command, payload in (
            ("browser_input_receipt", {"enabled": 1}),
            ("browser_input_receipt", {"enabled": True, "extra": "denied"}),
            ("browser_pointer_dispatch", {"x": True, "y": 4}),
            ("browser_pointer_dispatch", {"x": 1.5, "y": 4}),
            ("browser_pointer_dispatch", {"x": 65_536, "y": 4}),
            ("browser_pointer_dispatch", {"x": 3, "y": 4, "command_id": "model-supplied"}),
            ("browser_javascript_execute_unrestricted", {"javascript": ""}),
            ("windows_shell_execute_unrestricted", {"command": "whoami", "shell": "bash"}),
        ):
            with self.subTest(command=command, payload=payload), self.assertRaises(ValueError):
                live_clients.normalize_control_payload(command, payload)

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
