#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = PLUGIN_ROOT / "server"
ENVELOPE_PATH = PLUGIN_ROOT / "server" / "master_frontier" / "envelope.py"
STATIC_SERVER_PATH = PLUGIN_ROOT / "server" / "static_server.py"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

spec = importlib.util.spec_from_file_location("master_frontier.envelope", ENVELOPE_PATH)
assert spec and spec.loader
envelope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(envelope)


class MasterFrontierEnvelopeTests(unittest.TestCase):
    def test_capped_action_json_requires_structured_action_repair(self) -> None:
        capped_action_reply = (
            '{"answer":"Reading exact turn 6 content before self-criticism.",'
            '"decision":"transcript.read for turns 5-6 before answering",'
            '"actions":[{"action"'
        )

        self.assertTrue(envelope.requires_structured_action({}, capped_action_reply))

    def test_complete_answer_json_does_not_require_repair(self) -> None:
        parsed = {
            "answer": "I can answer from provided context.",
            "decision": "answer",
            "actions": [],
        }

        self.assertFalse(envelope.requires_structured_action(parsed, json.dumps(parsed)))

    def test_repair_body_is_owned_by_master_frontier_contract(self) -> None:
        body = {"instructions": "Use the envelope.", "max_output_tokens": 128}
        repaired = envelope.action_repair_body(body, '{"decision":"dispatch.hermes"')

        self.assertIn("STRICT ACTION REPAIR", repaired["instructions"])
        self.assertGreaterEqual(repaired["max_output_tokens"], 1200)
        self.assertEqual(body["max_output_tokens"], 128)

    def test_static_server_does_not_own_envelope_repair_policy(self) -> None:
        source = STATIC_SERVER_PATH.read_text(encoding="utf-8")

        self.assertIn("master_frontier_envelope.action_repair_body", source)
        self.assertIn("master_frontier_envelope.requires_structured_action", source)
        self.assertNotIn("STRICT ACTION REPAIR: your previous response", source)
        self.assertNotIn("DIRECT_HEAD_TOOL_INTENT_RE = re.compile", source)
        self.assertNotIn("DIRECT_HEAD_EXECUTIVE_INTENT_RE = re.compile", source)
        self.assertNotIn("def direct_head_reply_looks_like_action_json(reply: str) -> bool:\n    text =", source)


if __name__ == "__main__":
    unittest.main()
