#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = PLUGIN_ROOT / "server"
REPAIR_PATH = SERVER_ROOT / "master_frontier" / "repair.py"

sys.path.insert(0, str(SERVER_ROOT))

spec = importlib.util.spec_from_file_location("master_frontier.repair", REPAIR_PATH)
assert spec and spec.loader
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


class MasterFrontierRepairTests(unittest.TestCase):
    def test_conceptual_plain_text_bypasses_strict_action_repair(self) -> None:
        calls = []

        def completion(**_kwargs):
            calls.append(_kwargs)
            return {}

        parsed, result = repair.repair_structured_action(
            body={},
            route_envelope={"task_contract": {"evidence_floor": "conceptual"}},
            receiver="stub",
            result={
                "parsed": None,
                "reply": "Plain text answer - I'll be honest about what this envelope does to me.",
            },
            completion=completion,
            completion_kwargs={},
            record_event=lambda *_args: None,
        )

        self.assertEqual(calls, [])
        self.assertEqual(parsed["decision"], "answer")
        self.assertEqual(parsed["actions"], [])
        self.assertEqual(result["reply"], parsed["answer"])


if __name__ == "__main__":
    unittest.main()
