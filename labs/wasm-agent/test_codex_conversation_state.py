#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import codex_conversation_state as state


class CodexConversationStateTests(unittest.TestCase):
    def test_round_trip_is_bounded_and_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as root, mock.patch.dict(
            "os.environ", {"MF5_CODEX_THREAD_INDEX": str(Path(root) / "threads.json")}, clear=False,
        ):
            state.save("session", {
                "thread_id": "thread-1", "tool_digest": "a" * 64, "model": "gpt-5.6-luna",
                "turn_count": 7, "compaction_generation": 2, "compaction_status": "requested",
            })
            self.assertEqual(state.load("session")["thread_id"], "thread-1")
            self.assertEqual(state.load("session")["compaction_generation"], 2)
            payload = json.loads((Path(root) / "threads.json").read_text())
            self.assertEqual(payload["schema"], state.SCHEMA)
            self.assertNotIn("messages", payload["records"]["session"])


if __name__ == "__main__":
    unittest.main()
