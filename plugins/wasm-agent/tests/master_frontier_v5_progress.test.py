#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/wasm-agent/server"))
from master_frontier.v5 import progress, trajectory, wire


class MasterFrontierV5ProgressTests(unittest.TestCase):
    def test_overlap_and_unmet_implementation_stage_are_visible(self) -> None:
        state = trajectory.new("r", "t", "fix it", "fixture.ui")
        state["loop_counters"].update({"provider_attempts": 9, "tool_calls": 4, "duplicate_actions": 2})
        state["completed_actions"] = {
            "a": {"tool": "read", "observation": {"ok": True, "path": "widget.js", "start_line": 1, "end_line": 100}},
            "b": {"tool": "read", "observation": {"ok": True, "path": "widget.js", "start_line": 51, "end_line": 150}},
        }
        result = progress.project(state, {"task_contract": {"request_class": "implementation"}})
        self.assertEqual((result["requested_lines"], result["unique_lines"], result["overlap_lines"]), (200, 150, 50))
        self.assertEqual(result["duplicate_actions"], 2)
        self.assertTrue(result["stages"][0]["done"])
        self.assertFalse(result["stages"][1]["done"])
        self.assertEqual(result["choices"][0], "edit_or_explain_why_no_edit_is_correct")
        encoded = wire.encode({"objective": "fix it", "progress": result})
        self.assertIn("\nW\t", encoded)
        self.assertLess(len(encoded), 3000)


if __name__ == "__main__":
    unittest.main()
