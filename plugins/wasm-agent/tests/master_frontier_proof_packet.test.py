#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = PLUGIN_ROOT / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from master_frontier import proof_packet  # noqa: E402


class MasterFrontierProofPacketTests(unittest.TestCase):
    def test_repo_object_packet_exposes_qs_src_tools_and_controller_decision(self) -> None:
        envelope = {
            "objective": "what does the meta-analysis widget from realure space does?",
            "route_id": "wasm-agent.avatar-chat.ui",
            "surface": "avatar-chat",
            "task_contract": {"intent": "informational"},
        }
        local_tool_results = [
            {
                "tool": "code.memory.search",
                "ok": True,
                "code": "ok",
                "route_id": "wasm-agent.avatar-chat.ui",
                "result": {
                    "query": "meta-analysis",
                    "items": [{"file_path": "public/modules/meta-analysis/meta-analysis-widget.js"}],
                },
            },
            {
                "tool": "file.read_bounded",
                "ok": True,
                "code": "ok",
                "route_id": "wasm-agent.avatar-chat.ui",
                "result": {
                    "path": "public/modules/meta-analysis/meta-analysis-widget.js",
                    "text": (
                        "rankSubject postJson('/agent/tools/node.chat', "
                        "{node_id:'paracelsus', objective:'scientific-paper-meta-analysis'}); "
                        "assessIntegrity(); exportFindings(); persist(); localStorage.setItem('x','y');"
                    ),
                },
            },
        ]

        packet = proof_packet.build(
            envelope,
            stage="repo_object_preflight",
            local_tool_results=local_tool_results,
            parsed={"decision": "route_to_kernel_inspect", "actions": []},
            loop_state={"status": "finished", "critique": {"reason": "objective_answered"}},
        )

        self.assertEqual(packet["schema"], proof_packet.SCHEMA)
        self.assertEqual(packet["object"]["id"], "meta-analysis")
        self.assertEqual(packet["object"]["scope"], "realure")
        self.assertEqual(packet["source_status"], "read")
        self.assertEqual(packet["runtime_scope"], "missing")
        self.assertEqual(packet["controller_decision"], "answer_with_runtime_caveat")
        self.assertIn("code.memory.search=ok", packet["tool_receipts"])
        self.assertIn("file.read_bounded=ok", packet["tool_receipts"])
        self.assertIn("QS/1", packet["qs_line"])
        self.assertIn("SRC/1", packet["source_line"])
        self.assertIn("MF/1", packet["line"])
        self.assertIn("ctrl:answer_with_runtime_caveat", packet["line"])
        self.assertIn("gate:finished", packet["line"])


if __name__ == "__main__":
    unittest.main()
