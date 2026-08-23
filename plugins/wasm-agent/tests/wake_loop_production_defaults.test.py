#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools/voice/run-shell-v2-wake-loop.py"
SPEC = importlib.util.spec_from_file_location("shell_v2_wake_loop", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("shell-v2 wake loop import unavailable")
loop = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = loop
SPEC.loader.exec_module(loop)


class WakeLoopProductionDefaultsTests(unittest.TestCase):
    def test_registered_default_queue_matches_production_control_origin(self) -> None:
        self.assertEqual(loop.DEFAULT_ORIGIN, "https://wa.colmeio.com")
        self.assertEqual(
            loop.origin_authority(loop.DEFAULT_ORIGIN),
            loop.origin_authority(loop.SHELL_V2_CONTROL_URL),
        )
        self.assertNotIn("127.0.0.1", loop.DEFAULT_ORIGIN)
        self.assertEqual(sys.modules["hot_shell_common"].DEFAULT_ORIGIN, "https://wa.colmeio.com")

    def test_remote_result_uses_exact_terminal_command_receipt(self) -> None:
        record = {
            "command_id": "command-target",
            "received_at": "2026-08-20T14:48:11Z",
            "result": {"ok": False, "failureClassification": "android_device_missing"},
        }
        payload = {
            "commandReceipt": {"terminal": True, "record": record},
            "native_control": {"latest_result": {"command_id": "command-newer"}},
        }
        with patch.object(loop, "request_json", return_value=payload) as request:
            found = loop.read_remote_result(
                "https://wa.colmeio.com", "secret", "windows-device", "command-target"
            )
        self.assertEqual(found, record)
        self.assertIn("command_id=command-target", request.call_args.args[1])

    def test_remote_result_keeps_latest_result_compatibility(self) -> None:
        legacy = {"command_id": "command-target", "result": {"ok": True}}
        payload = {"native_control": {"latest_result": legacy}}
        with patch.object(loop, "request_json", return_value=payload):
            found = loop.read_remote_result(
                "https://wa.colmeio.com", "secret", "windows-device", "command-target"
            )
        self.assertEqual(found, legacy)


if __name__ == "__main__":
    unittest.main()
