#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import hot_shell_common


class HotShellCommonTest(unittest.TestCase):
    def test_wait_for_result_reads_terminal_cloud_receipt(self) -> None:
        record = {
            "schema": "hermes.wasm_agent.native_control_result.v1",
            "received_at": "2026-08-11T12:00:00Z",
            "result": {"ok": True, "shellProtocolVersion": 2},
        }
        receipt = {"ok": True, "found": True, "terminal": True, "record": record}
        status = {"ok": True, "commandReceipt": receipt}
        with tempfile.TemporaryDirectory() as tempdir, patch.object(
            hot_shell_common, "safe_request", return_value=(status, "")
        ) as request:
            found = hot_shell_common.wait_for_result(
                Path(tempdir),
                "windows-test",
                "command-test",
                wait_sec=1,
                poll_sec=0.01,
                origin="https://wa.example.test",
            )
        self.assertEqual(found, record)
        self.assertIn("/native/frontier/status?", request.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
