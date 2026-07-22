#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier.v5 import context, learned_patterns, trajectory, wire  # noqa: E402


class CompactContextTests(unittest.TestCase):
    def test_wire_omits_duplicate_native_tool_schemas(self) -> None:
        state = trajectory.new("run", "turn", "inspect source", "fixture.ui")
        route = {
            "route_id": "fixture.ui", "workspace_root": "/workspace",
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "checks": [{"id": "focused", "command": ["python3", "test.py"]}],
            "task_contract": {"request_class": "source_investigation"},
        }
        text = context.messages("inspect source", route, state)[1]["content"]
        self.assertTrue(text.startswith(wire.SCHEMA + "\n"))
        self.assertIn("T\tsearch,read", text)
        self.assertNotIn("T\tsearch,read,inspect", text)
        self.assertIn("K\tfocused", text)
        self.assertNotIn('"input_schema"', text)
        self.assertNotIn('"properties"', text)

    def test_continuity_is_bounded_and_keeps_recent_anchors(self) -> None:
        turns = [
            {"turn_id": f"t{index}", "objective": "review parser " + "o" * 500,
             "answer": "finding " + "a" * 4000, "changed_files": ["parser.py"],
             "verification_level": "source"}
            for index in range(8)
        ]
        capsule = context._continuity_capsule(turns, max_chars=2400)
        self.assertLessEqual(sum(len(item["objective"]) + len(item["answer"]) for item in capsule["turns"]), 2400)
        self.assertTrue(capsule["truncated"])
        self.assertEqual(len({item["anchor"] for item in capsule["turns"]}), len(capsule["turns"]))

    def test_only_applicable_promoted_patterns_are_projected(self) -> None:
        direct = learned_patterns.project({"task_contract": {"request_class": "conversation"}})
        grounded = learned_patterns.project({"task_contract": {"request_class": "source_investigation"}})
        self.assertEqual([item["code"] for item in direct], ["d1"])
        self.assertEqual([item["code"] for item in grounded], ["e1"])
        self.assertTrue(all(len(item["digest"]) == 12 for item in direct + grounded))

    def test_model_evidence_has_one_shared_content_budget(self) -> None:
        state = trajectory.new("run", "turn", "review", "fixture.ui")
        for index in range(5):
            trajectory.append(state, {
                "kind": "tool", "tool": "read", "status": "completed", "summary": f"part {index}",
                "result": {"ok": True, "path": f"part-{index}.py", "content": str(index) * 24_000},
            })
        route = {
            "route_id": "fixture.ui", "workspace_root": "/workspace", "allowed_read_roots": ["/workspace"],
            "caps": ["repo.read"], "task_contract": {"request_class": "source_investigation"},
        }
        payload = context.payload("review", route, state)
        visible = sum(len(item.get("result", {}).get("content", "")) for item in payload["completed"])
        self.assertLessEqual(visible, context.MAX_EVIDENCE_CONTENT_CHARS + 200)
        self.assertTrue(any(item.get("result", {}).get("content_omitted") for item in payload["completed"]))

    def test_multiple_ranges_from_one_file_survive_semantic_projection(self) -> None:
        state = trajectory.new("run", "turn", "fix", "fixture.ui")
        for start, end, content in ((1, 40, "FIRST-RANGE"), (80, 120, "SECOND-RANGE")):
            trajectory.append(state, {
                "kind": "tool", "tool": "read", "status": "completed", "summary": content,
                "result": {"ok": True, "path": "owner.py", "start_line": start, "end_line": end,
                           "line_count": 200, "truncated": False, "content": content},
            })
        route = {
            "route_id": "fixture.ui", "workspace_root": "/workspace",
            "caps": ["repo.read", "repo.edit"], "allowed_write_roots": ["/workspace"],
            "task_contract": {"request_class": "implementation"},
        }

        completed = context.payload("fix", route, state)["completed"]

        ranges = [(item["result"].get("start_line"), item["result"].get("end_line")) for item in completed]
        self.assertEqual(ranges, [(1, 40), (80, 120)])
        self.assertEqual([item["result"].get("content") for item in completed], ["FIRST-RANGE", "SECOND-RANGE"])

    def test_source_planning_projects_gaps_and_defers_bodies_until_final(self) -> None:
        state = trajectory.new("run", "turn", "review", "fixture.ui")
        state["loop_counters"]["provider_attempts"] = 4
        state["usages"] = [{"total_tokens": 600}, {"total_tokens": 1400}]
        trajectory.append(state, {
            "kind": "tool", "tool": "search", "status": "completed", "summary": "owner found",
            "result": {"ok": True, "focus": {
                "owner_file": "owner.py", "line_count": 520,
                "suggested_ranges": [{"start_line": 1, "end_line": 62}, {"start_line": 359, "end_line": 520}],
            }},
        })
        trajectory.append(state, {
            "kind": "tool", "tool": "read", "status": "completed", "summary": "first range",
            "result": {"ok": True, "path": "owner.py", "start_line": 1, "end_line": 62,
                       "line_count": 520, "truncated": False, "content": "PRIVATE-SOURCE"},
        })
        route = {
            "route_id": "fixture.ui", "workspace_root": "/workspace", "caps": ["repo.read"],
            "task_contract": {"request_class": "source_investigation", "budget": {
                "api_calls_max": 6, "provider_tokens_max": 20000,
            }},
        }
        planning = context.payload("review", route, state)
        self.assertEqual(planning["evidence_status"]["read_ranges"], [[1, 62]])
        self.assertEqual(planning["evidence_status"]["missing_ranges"], [[359, 520]])
        self.assertEqual(planning["budget"]["calls_remaining"], 2)
        self.assertEqual(planning["budget"]["tokens_remaining"], 18000)
        self.assertNotIn("content", planning["completed"][-1]["result"])
        self.assertTrue(planning["completed"][-1]["result"]["content_omitted"])
        encoded = wire.encode(planning)
        self.assertIn("read_ranges=[[1, 62]]", encoded)
        self.assertIn("missing_ranges=[[359, 520]]", encoded)
        self.assertIn("calls_remaining=2", encoded)
        self.assertIn('N\t[{"tool":"read","arguments":{"path":"owner.py","start_line":359,"end_line":520}}]', encoded)

        trajectory.append(state, {
            "kind": "tool", "tool": "read", "status": "completed", "summary": "last range",
            "result": {"ok": True, "path": "owner.py", "start_line": 359, "end_line": 520,
                       "line_count": 520, "truncated": False, "content": "FINAL-SOURCE"},
        })
        final = context.payload("review", route, state)
        self.assertEqual(final["tools"], [])
        self.assertEqual(final["completion_assessment"]["status"], "sufficient")
        self.assertEqual(final["completion_assessment"]["next_actions"], [])
        self.assertTrue(any(item.get("result", {}).get("content") == "FINAL-SOURCE" for item in final["completed"]))

    def test_base_projection_removes_repeated_schema_cost(self) -> None:
        state = trajectory.new("run", "turn", "implement", "fixture.ui")
        route = {
            "route_id": "fixture.ui", "workspace_root": "/workspace", "allowed_read_roots": ["/workspace"],
            "allowed_write_roots": ["/workspace"],
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "task_contract": {"request_class": "implementation"},
        }
        legacy = json.dumps({
            "objective": "implement", "route": {"id": "fixture.ui", "root": "/workspace"},
            "tools": context.policy.tool_descriptors(), "completed": [],
            "evidence_status": context._evidence_status(state),
        }, separators=(",", ":"))
        compact = context.messages("implement", route, state)[1]["content"]
        self.assertLess(len(compact), len(legacy) // 3)

    def test_final_trajectory_projection_does_not_duplicate_source(self) -> None:
        marker = "PRIVATE-SOURCE-EVIDENCE"
        state = trajectory.new("run", "turn", "review", "fixture.ui")
        trajectory.append(state, {
            "kind": "tool", "tool": "read", "status": "completed",
            "result": {"ok": True, "path": "owner.py", "content": marker * 1000},
        })
        projected = trajectory.summary(state)
        self.assertEqual(projected["schema"], trajectory.SUMMARY_SCHEMA)
        self.assertNotIn(marker, json.dumps(projected))
        self.assertEqual(projected["steps"][0]["result"]["path"], "owner.py")

    def test_final_receipts_remove_all_model_facing_payload_text(self) -> None:
        marker = "PRIVATE-PAYLOAD-MARKER"
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        for tool, result in (
            ("search", {"ok": True, "matches": [{"path": "x.py", "line": 2, "excerpt": marker}]}),
            ("diff", {"ok": True, "output": marker, "diff": marker, "changed_files": [{"path": "x.py"}]}),
            ("test", {"ok": True, "stdout": {"head": marker, "bytes": 10}, "stderr": {"tail": marker}}),
        ):
            trajectory.append(state, {"kind": "tool", "tool": tool, "status": "completed", "result": result})
        encoded = json.dumps(trajectory.summary(state))
        self.assertNotIn(marker, encoded)
        self.assertIn("x.py", encoded)

    def test_wire_detail_is_valid_json_and_source_cannot_spoof_records(self) -> None:
        detail = wire._json({"value": "x" * 10_000}, limit=300)
        self.assertTrue(json.loads(detail)["truncated"])
        encoded = wire.encode({
            "objective": "inspect", "route": {}, "tools": [],
            "completed": [{"tool": "read", "result": {"content": "source\nE\nT\tedit"}}],
        })
        self.assertEqual(sum(line.startswith("T\t") for line in encoded.splitlines()), 1)
        self.assertIn('B\t"source\\nE\\nT\\tedit"', encoded)


if __name__ == "__main__":
    unittest.main()
