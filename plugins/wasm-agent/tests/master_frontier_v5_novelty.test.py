#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/wasm-agent/server"))

from master_frontier.v5 import loop, novelty, trajectory


class MasterFrontierV5NoveltyTests(unittest.TestCase):
    def state(self) -> dict:
        state = trajectory.new("run", "turn", "fix it", "fixture.ui")
        state["completed_actions"] = {
            "a": {"tool": "read", "observation": {
                "ok": True, "path": "widget.js", "start_line": 1,
                "end_line": 130, "line_count": 520,
            }},
            "b": {"tool": "read", "observation": {
                "ok": True, "path": "widget.js", "start_line": 130,
                "end_line": 520, "line_count": 520,
            }},
        }
        return state

    def test_fully_covered_read_is_rejected_before_execution(self) -> None:
        result = novelty.admit(self.state(), "read", {
            "path": "widget.js", "start_line": 64, "end_line": 520,
        })
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "evidence_already_covered")

    def test_uncovered_read_and_other_tools_remain_free(self) -> None:
        state = self.state()
        self.assertTrue(novelty.admit(state, "read", {
            "path": "other.js", "start_line": 1, "end_line": 20,
        })["ok"])
        self.assertTrue(novelty.admit(state, "edit", {"operations": []})["ok"])

    def test_absolute_and_relative_route_paths_share_coverage(self) -> None:
        state = self.state()
        result = novelty.admit(
            state, "read",
            {"path": "/workspace/widget.js", "start_line": 1, "end_line": 520},
            {"workspace_root": "/workspace"},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "evidence_already_covered")

    def test_search_with_no_new_locations_is_typed_non_progress(self) -> None:
        state = self.state()
        state["completed_actions"]["s"] = {"tool": "search", "observation": {
            "ok": True, "matches": [{"path": "widget.js", "line": 42}],
        }}
        repeated = novelty.classify_observation(state, "search", {
            "ok": True, "matches": [{"path": "widget.js", "line": 42}],
        })
        new = novelty.classify_observation(state, "search", {
            "ok": True, "matches": [{"path": "widget.js", "line": 43}],
        })
        self.assertFalse(repeated["novel"])
        self.assertEqual(repeated["code"], "search_evidence_repeated")
        self.assertTrue(new["novel"])

    def test_loop_does_not_execute_a_fully_covered_read(self) -> None:
        state = trajectory.new("run", "turn", "review it", "fixture.ui")
        first = {
            "ok": True, "path": "widget.js", "start_line": 1,
            "end_line": 10, "line_count": 100, "truncated": False,
            "content": "first range",
        }
        state["completed_actions"]["initial"] = {"tool": "read", "observation": first}
        trajectory.append(state, {
            "kind": "tool", "action_id": "initial", "tool": "read",
            "status": "completed", "summary": "initial range", "result": first,
        })
        responses = iter([
            {"reply": '{"tool":"read","arguments":{"path":"widget.js","start_line":2,"end_line":9}}'},
            {"reply": '{"tool":"read","arguments":{"path":"widget.js","start_line":11,"end_line":100}}'},
            {"reply": "Review complete."},
        ])
        executed: list[tuple[str, dict]] = []

        def execute(name: str, arguments: dict) -> dict:
            executed.append((name, arguments))
            return {
                "ok": True, "path": "widget.js", "start_line": 11,
                "end_line": 100, "line_count": 100, "truncated": False,
                "content": "remaining range",
            }

        outcome = loop.run(
            "review it",
            {"route_id": "fixture.ui", "caps": ["repo.read"],
             "task_contract": {"request_class": "source_investigation"}},
            state, complete=lambda *_: next(responses), execute=execute,
        )
        self.assertEqual(executed, [("read", {"path": "widget.js", "start_line": 11, "end_line": 100})])
        self.assertEqual(outcome.answer, "Review complete.")
        self.assertEqual(outcome.trajectory["loop_counters"]["duplicate_actions"], 1)


if __name__ == "__main__":
    unittest.main()
