#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))
import native_control_auth  # noqa: E402


class NativeControlAuthTest(unittest.TestCase):
    def test_environment_precedes_private_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wa.env"
            path.write_text("WASM_AGENT_NATIVE_CONTROL_KEY=file-key\n", encoding="utf-8")
            self.assertEqual(native_control_auth.resolve_key(path, environ={}), "file-key")
            self.assertEqual(native_control_auth.resolve_key(path, environ={"WASM_AGENT_NATIVE_CONTROL_KEY": "env-key"}), "env-key")

    def test_header_match_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wa.env"
            self.assertFalse(native_control_auth.header_matches("anything", path, environ={}))
            path.write_text("WASM_AGENT_NATIVE_CONTROL_KEY=expected\n", encoding="utf-8")
            self.assertTrue(native_control_auth.header_matches("expected", path, environ={}))
            self.assertFalse(native_control_auth.header_matches("wrong", path, environ={}))


if __name__ == "__main__":
    unittest.main()
