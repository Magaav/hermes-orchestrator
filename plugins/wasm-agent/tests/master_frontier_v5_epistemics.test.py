#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/wasm-agent/server"))

from master_frontier.v5 import context, epistemics, trajectory, wire


class MasterFrontierV5EpistemicsTests(unittest.TestCase):
    def test_incomplete_diff_forbids_absence_claims(self) -> None:
        value = epistemics.project([{
            "result": {"ok": True, "result": {
                "code": "diff_receipt_truncated", "stat": {"complete": False},
            }},
        }])
        self.assertEqual(value, {
            "universe": "incomplete",
            "claim_rule": "presence_only_no_absence_claims",
        })

    def test_early_primary_evidence_survives_many_rejections(self) -> None:
        state = trajectory.new("run", "turn", "verify", "fixture.ui")
        trajectory.append(state, {
            "kind": "tool", "tool": "read", "status": "completed",
            "summary": "owning source", "result": {
                "ok": True, "path": "owner.py", "start_line": 1, "end_line": 2,
                "line_count": 2, "content": "PRIMARY-EVIDENCE",
            },
        })
        for index in range(15):
            trajectory.append(state, {
                "kind": "system", "tool": "read", "status": "rejected",
                "summary": f"duplicate {index}", "result": {"ok": False},
            })
        route = {"route_id": "fixture.ui", "task_contract": {"request_class": "verification"}}
        encoded = wire.encode(context.payload("verify", route, state))
        self.assertIn("PRIMARY-EVIDENCE", encoded)
        self.assertIn("owner.py", encoded)


if __name__ == "__main__":
    unittest.main()
