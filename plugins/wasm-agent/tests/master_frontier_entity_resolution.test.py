#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = PLUGIN_ROOT / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from master_frontier import entity_resolution  # noqa: E402


class MasterFrontierEntityResolutionTests(unittest.TestCase):
    def test_source_paths_fall_back_to_symbol_matches(self) -> None:
        paths = entity_resolution.source_paths([
            {"tool": "code.memory.search", "ok": False, "result": {"items": []}},
            {
                "tool": "lookup.symbol",
                "ok": True,
                "result": {"matches": [{"path": "public/modules/meta-analysis/meta-analysis-widget.js", "line": 1}]},
            },
        ])

        self.assertEqual(paths, ["public/modules/meta-analysis/meta-analysis-widget.js"])

    def test_meta_analysis_widget_inside_realure_resolves_object_scope_and_source_first(self) -> None:
        resolved = entity_resolution.resolve({
            "objective": "great, can you check the meta-analysis widget inside realure?",
            "route_id": "wasm-agent.avatar-chat.ui",
        })

        self.assertTrue(resolved["is_repo_object_question"])
        self.assertEqual(resolved["kind"], "widget")
        self.assertEqual(resolved["object_id"], "meta-analysis")
        self.assertEqual(resolved["scope_id"], "realure")
        self.assertEqual(resolved["query"], "meta-analysis")
        self.assertEqual(resolved["evidence_needed"], ["source", "runtime_scope"])
        self.assertTrue(entity_resolution.needs_runtime_scope_proof({"objective": resolved["objective"]}))
        self.assertEqual(resolved["next_tool"], "code.memory.search")

    def test_other_widget_and_space_questions_use_same_contract(self) -> None:
        cases = [
            ("check the browser widget in home", "browser", "home"),
            ("where is the security loop widget inside fleet", "security-loop", "fleet"),
            ("describe the timeline panel in admin", "timeline", "admin"),
        ]

        for objective, object_id, scope_id in cases:
            with self.subTest(objective=objective):
                resolved = entity_resolution.resolve({"objective": objective})
                self.assertTrue(resolved["is_repo_object_question"])
                self.assertEqual(resolved["object_id"], object_id)
                self.assertEqual(resolved["scope_id"], scope_id)
                self.assertEqual(resolved["query"], object_id)

    def test_repo_object_question_without_scope_needs_source_only(self) -> None:
        resolved = entity_resolution.resolve({"objective": "what are space widgets for this UI?"})

        self.assertTrue(resolved["is_repo_object_question"])
        self.assertEqual(resolved["kind"], "widget")
        self.assertEqual(resolved["object_id"], "space")
        self.assertEqual(resolved["query"], "widget")
        self.assertEqual(resolved["scope_id"], "")
        self.assertEqual(resolved["evidence_needed"], ["source"])
        self.assertFalse(entity_resolution.needs_runtime_scope_proof({"objective": "what are space widgets for this UI?"}))

    def test_from_scope_and_auxiliary_question_words_do_not_pollute_object_id(self) -> None:
        resolved = entity_resolution.resolve({
            "objective": "what does the meta-analysis widget from realure space does?",
            "route_id": "wasm-agent.avatar-chat.ui",
        })

        self.assertTrue(resolved["is_repo_object_question"])
        self.assertEqual(resolved["kind"], "widget")
        self.assertEqual(resolved["object_id"], "meta-analysis")
        self.assertEqual(resolved["scope_id"], "realure")
        self.assertEqual(resolved["query"], "meta-analysis")
        self.assertEqual(resolved["evidence_needed"], ["source", "runtime_scope"])

    def test_repo_object_probe_and_source_read_contracts_are_module_owned(self) -> None:
        envelope = {
            "objective": "what does the meta-analysis widget from realure space does?",
            "route_id": "wasm-agent.avatar-chat.ui",
        }
        actions = entity_resolution.probe_actions(envelope, [])

        self.assertEqual([action["action"] for action in actions], ["code.memory.search", "lookup.symbol"])
        self.assertEqual(actions[0]["args"]["query"], "meta-analysis")

        local_results = [{
            "tool": "code.memory.search",
            "result": {
                "items": [{
                    "file_path": "public/modules/meta-analysis/meta-analysis-widget.js",
                }],
            },
        }]
        read_action = entity_resolution.source_read_action(envelope, local_results)

        self.assertIsNotNone(read_action)
        self.assertEqual(read_action["action"], "file.read_bounded")
        self.assertEqual(read_action["args"]["path"], "public/modules/meta-analysis/meta-analysis-widget.js")

    def test_quest_state_line_advances_scoped_repo_object_proof(self) -> None:
        envelope = {
            "objective": "what does the meta-analysis widget from realure space does?",
            "route_id": "wasm-agent.avatar-chat.ui",
        }
        source_only = [{
            "tool": "code.memory.search",
            "ok": True,
            "result": {
                "query": "meta-analysis",
                "items": [{"file_path": "public/modules/meta-analysis/meta-analysis-widget.js"}],
            },
        }]
        blocked = entity_resolution.quest_state_from_evidence(envelope, source_only, block_code="runtime_scope_route_missing")

        self.assertEqual(blocked["line"], "QS/1 G:realure-meta-analysis-widget S:realure O:w:meta-analysis K:src:meta-analysis-widget-js M:rt:realure NX:answer|inspect BLK:runtime-scope-route-missing")
        parsed = entity_resolution.parse_quest_state_line(blocked["line"])
        self.assertEqual(parsed["space"], "realure")
        self.assertEqual(parsed["known"], ["src:meta-analysis-widget-js"])
        self.assertEqual(parsed["missing"], ["rt:realure"])

        proved = entity_resolution.quest_state_from_evidence(envelope, [*source_only, {"tool": "kernel.inspect", "ok": True, "summary": {"scope": "realure"}}])

        self.assertIn("K:src:meta-analysis-widget-js,rt:realure", proved["line"])
        self.assertNotIn("M:rt:realure", proved["line"])
        self.assertIn("NX:answer", proved["line"])

    def test_unrelated_runtime_inspection_does_not_satisfy_scope_proof(self) -> None:
        envelope = {
            "objective": "what does the meta-analysis widget from realure space does?",
            "route_id": "wasm-agent.avatar-chat.ui",
        }
        unrelated = [{
            "tool": "kernel.inspect",
            "ok": True,
            "route_id": "hermes-node.paracelsus.runtime",
            "summary": {"entity": "paracelsus"},
        }]
        related = [{
            "tool": "kernel.inspect",
            "ok": True,
            "route_id": "wasm-agent.realure.runtime",
            "summary": {"scope": "realure"},
        }]

        self.assertFalse(entity_resolution.runtime_scope_proof_satisfied(envelope, unrelated))
        self.assertTrue(entity_resolution.runtime_scope_proof_satisfied(envelope, related))

    def test_repo_object_source_summary_names_behavior_not_just_receipts(self) -> None:
        local_results = [{
            "tool": "file.read_bounded",
            "result": {
                "path": "public/modules/meta-analysis/meta-analysis-widget.js",
                "text": "rankSubject postJson('/agent/tools/node.chat', {node_id:'paracelsus', objective:'scientific-paper-meta-analysis'}); assessIntegrity(); exportFindings(); persist(); localStorage.setItem('x','y');",
            },
        }]

        summaries = entity_resolution.source_summaries(local_results)

        self.assertEqual(len(summaries), 1)
        self.assertIn("The meta-analysis widget is a browser-side research workflow panel", summaries[0])
        self.assertIn("sends the subject to the `paracelsus` research node's `scientific-paper-meta-analysis` workflow", summaries[0])
        self.assertIn("flags bias/integrity signals from the returned finding text", summaries[0])
        self.assertIn("turns saved findings into an exportable report", summaries[0])
        self.assertNotIn("The source-backed understanding is", summaries[0])
        self.assertNotIn("Source anchor", summaries[0])


if __name__ == "__main__":
    unittest.main()
