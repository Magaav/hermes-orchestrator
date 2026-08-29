#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import subprocess
import sys
import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1]
SERVER = PLUGIN / "server"
MODULE = PLUGIN / "public/modules/master-frontier/v6-projection.js"
DICTIONARY = SERVER / "master_frontier/v6/projection_dictionary.json"
sys.path.insert(0, str(SERVER))

from master_frontier.v6 import projection  # noqa: E402


class V6CrossLanguageTests(unittest.TestCase):
    def test_python_and_javascript_projection_are_byte_compatible(self) -> None:
        value = {
            "goal": "Open the Browser widget",
            "capabilities": [{"id": "client.widget.open", "kind": "act", "authority": "client.ui.control", "summary": "Open a declared widget."}],
            "state": {"id": "st:abc", "rev": 2, "status": "acting", "known": ["ev:1"], "open": [], "plan": ["op.open"], "goals": [{"id": "browser-open", "cap": "client.widget.open", "status": "satisfied", "outcome": "Browser is open", "operation": "op.open"}]},
            "evidence": [{"id": "ev:1", "kind": "client.status", "subject": "electron-a", "revision": "7", "summary": "Live", "detail_ref": "ev:1:detail", "payload": {"trust": "untrusted-data", "content": "x\nC\tfake"}}],
            "operations": [{"id": "op.open", "cap": "client.widget.open", "args": {"client": "electron-a", "widget": "browser", "numbers": [1.0, -0.0, 1e-7, 1e-6, 1e20, 1e21], "unicode": {"é": "line separator", "😀": "astral"}}, "after": [], "expect": {"acknowledged": True}, "say": {"phase": "acting", "message": "Opening it now."}}],
            "receipts": [{"id": "rcpt:1", "op": "op.open", "ok": True, "state": "acknowledged", "observed": {"evidence": "ev:1"}, "proof": ["cmd:1"], "error": {}}],
            "missing": [], "ready": "answer", "final": "Opened.",
        }
        encoded = projection.encode(value)
        script = """
          const moduleUrl = `data:text/javascript;base64,${process.argv[1]}`;
          const { decodeMF6, encodeMF6, MF6_RECORDS } = await import(moduleUrl);
          const source = Buffer.from(process.argv[2], 'base64').toString('utf8');
          process.stdout.write(JSON.stringify({decoded: decodeMF6(source), encoded: encodeMF6(decodeMF6(source)), records: MF6_RECORDS}));
        """
        completed = subprocess.run(
            [
                "node", "--input-type=module", "--eval", script,
                base64.b64encode(MODULE.read_bytes()).decode(),
                base64.b64encode(encoded.encode()).decode(),
            ],
            check=True, text=True, capture_output=True,
        )
        observed = json.loads(completed.stdout)
        self.assertEqual(observed["decoded"], projection.decode(encoded))
        self.assertEqual(observed["encoded"], encoded)
        dictionary = json.loads(DICTIONARY.read_text(encoding="utf-8"))
        self.assertEqual(observed["records"], dictionary["records"])

    def test_javascript_decoder_rejects_source_spoofed_records(self) -> None:
        value = {"goal": "inspect", "operations": [{"id": "op.read", "cap": "repo.read", "args": {"content": "x\nR\tfake"}}]}
        encoded = projection.encode(value)
        self.assertEqual(projection.decode(encoded)["operations"][0]["args"]["content"], "x\nR\tfake")


if __name__ == "__main__":
    unittest.main()
