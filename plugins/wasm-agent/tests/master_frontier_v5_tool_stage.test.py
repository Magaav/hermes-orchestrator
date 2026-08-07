#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/wasm-agent/server"))

from master_frontier.v5 import context, policy, tool_stage, trajectory


class MasterFrontierV5ToolStageTests(unittest.TestCase):
    def test_post_mutation_verification_selects_one_evidence_owner(self) -> None:
        route = {
            "workspace_root": "/workspace",
            "checks": [
                {"id": "widget", "evidence_paths": ["tests/widget.test.mjs", "public/widget.mjs"]},
                {"id": "proxy", "evidence_paths": ["server/proxy.py"]},
            ],
        }
        calls = tool_stage.post_mutation_verification_calls(
            route, {"changed_files": ["/workspace/tests/widget.test.mjs"]},
        )
        self.assertEqual(calls, [
            {"name": "test", "arguments": {"check_id": "widget"}},
            {"name": "diff", "arguments": {}},
            {"name": "prove", "arguments": {}},
        ])

    def test_post_mutation_verification_refuses_ambiguous_or_missing_owner(self) -> None:
        route = {
            "checks": [
                {"id": "one", "evidence_paths": ["shared.py"]},
                {"id": "two", "evidence_paths": ["shared.py"]},
            ],
        }
        self.assertEqual(
            tool_stage.post_mutation_verification_calls(route, {"changed_files": ["shared.py"]}),
            [],
        )
        self.assertEqual(
            tool_stage.post_mutation_verification_calls(route, {"changed_files": ["other.py"]}),
            [],
        )

    def test_post_mutation_verification_uses_only_declared_check_as_fallback(self) -> None:
        route = {"checks": [{"id": "space-ui-regression", "evidence_paths": []}]}
        self.assertEqual(
            tool_stage.post_mutation_verification_calls(route, {"changed_files": ["public/widget.js"]}),
            [
                {"name": "test", "arguments": {"check_id": "space-ui-regression"}},
                {"name": "diff", "arguments": {}},
                {"name": "prove", "arguments": {}},
            ],
        )

    def test_verification_retires_exhausted_tool_families(self) -> None:
        state = trajectory.new("run", "turn", "verify", "fixture.ui")
        trajectory.append(state, {
            "kind": "tool", "tool": "read", "status": "completed",
            "result": {"ok": True, "path": "owner.py"},
        })
        state["operation_ledger"]["check"] = {"rev": 0, "ok": True}
        state["operation_ledger"]["diff"] = {"rev": 0, "ok": False}
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read", "test.run", "proof.report"],
            "task_contract": {"request_class": "verification"},
        }
        names = [item["name"] for item in policy.active_descriptors(route, state)]
        native = [item["function"]["name"] for item in policy.active_provider_tools(route, state)]
        self.assertEqual(names, ["prove"])
        self.assertEqual(native, names)

    def test_source_authority_is_not_stage_guessed(self) -> None:
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read"],
            "task_contract": {"request_class": "source_investigation"},
        }
        self.assertEqual(policy.active_descriptors(route, state), policy.descriptors_for(route))
        self.assertFalse(context.completion_only(state, route))

    def test_implementation_retires_only_completed_workflow_stages(self) -> None:
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "task_contract": {"request_class": "implementation"},
        }
        state["operation_ledger"].update({"revision": 1, "check": {}})
        self.assertEqual(
            [item["name"] for item in policy.active_descriptors(route, state)],
            ["test", "diff", "prove"],
        )
        state["operation_ledger"]["check"] = {"rev": 1, "ok": True}
        self.assertEqual(
            [item["name"] for item in policy.active_descriptors(route, state)],
            ["diff", "prove"],
        )

    def test_failed_current_revision_check_reopens_edit_for_repair(self) -> None:
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        state["operation_ledger"].update({
            "revision": 1, "check": {"rev": 1, "ok": False},
        })
        route = {
            "route_id": "fixture.ui",
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "task_contract": {"request_class": "implementation"},
        }

        self.assertEqual([item["name"] for item in policy.active_descriptors(route, state)], ["edit"])

    def test_failed_check_repair_precedes_missing_owner_proof(self) -> None:
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        state["operation_ledger"].update({
            "revision": 1,
            "changed_files": ["public/widget.js"],
            "check": {"rev": 1, "ok": False},
        })
        route = {
            "route_id": "fixture.ui",
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "required_owner_paths": ["public/app-registry.js"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }

        descriptors = policy.active_descriptors(route, state)
        self.assertEqual([item["name"] for item in descriptors], ["edit"])
        operation = descriptors[0]["input_schema"]["properties"]["operations"]["items"]
        self.assertNotIn("enum", operation["properties"]["path"])

    def test_existing_create_target_requires_exact_read(self) -> None:
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        state["last_error"] = {
            "code": "patch_preimage_exists", "tool": "edit",
            "durable_targets": ["public/widget.js"],
        }
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        descriptors = policy.active_descriptors(route, state)
        self.assertEqual([item["name"] for item in descriptors], ["read"])
        self.assertEqual(
            descriptors[0]["input_schema"]["properties"]["path"]["enum"],
            ["public/widget.js"],
        )

    def test_complete_route_file_read_advances_autonomous_implementation_to_edit(self) -> None:
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        trajectory.append(state, {
            "kind": "tool", "tool": "search", "status": "completed",
            "result": {"ok": True, "focus": {"owner_file": "ranked.py"}},
        })
        trajectory.append(state, {
            "kind": "tool", "tool": "read", "status": "completed",
            "result": {"ok": True, "path": "ranked.py", "start_line": 1, "end_line": 40, "line_count": 40, "sha256": "a" * 64},
        })
        state["completed_actions"] = {
            "search": {"tool": "search", "observation": {"ok": True, "focus": {"owner_file": "ranked.py"}}},
            "read": {"tool": "read", "observation": {"ok": True, "path": "ranked.py", "start_line": 1, "end_line": 40, "line_count": 40}},
        }
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }

        self.assertEqual(
            [item["name"] for item in policy.active_descriptors(route, state)],
            ["edit"],
        )

    def test_missing_required_owner_accepts_fresh_exact_read_as_proof(self) -> None:
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        state["operation_ledger"].update({
            "revision": 1,
            "changed_files": ["public/new-widget.js"],
            "postimages": {"public/new-widget.js": "a" * 64},
            "mutations": [{"revision": 1, "changed_files": ["public/new-widget.js"]}],
            "check": {"rev": 1, "ok": True},
            "diff": {"rev": 1, "ok": True},
            "proof": {"rev": 1, "ok": True},
        })
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "required_owner_paths": ["public/app-registry.js"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }

        self.assertEqual(
            [item["name"] for item in policy.active_descriptors(route, state)],
            ["read"],
        )
        read = policy.active_descriptors(route, state)[0]
        self.assertEqual(read["input_schema"]["properties"]["path"]["enum"], ["public/app-registry.js"])
        self.assertNotIn("start_line", read["input_schema"]["properties"])
        self.assertNotIn("end_line", read["input_schema"]["properties"])
        trajectory.append(state, {
            "kind": "tool", "tool": "read", "status": "completed",
            "result": {
                "ok": True, "path": "public/app-registry.js", "start_line": 1,
                "end_line": 40, "line_count": 40, "sha256": "b" * 64,
                "content": 'entry: "/modules/new-widget.js"',
            },
        })
        self.assertEqual(policy.active_descriptors(route, state), [])
        assessment = context.completion.assess(state, route)
        self.assertFalse(any("required owner" in gap for gap in assessment["required_gaps"]))

    def test_existing_target_repair_stays_scoped_after_confirming_read(self) -> None:
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        trajectory.append(state, {
            "kind": "tool", "tool": "edit", "status": "failed",
            "result": {
                "ok": False, "code": "patch_preimage_exists",
                "summary": "Expected an absent target: public/widget.js",
            },
        })
        trajectory.append(state, {
            "kind": "tool", "tool": "read", "status": "completed",
            "result": {
                "ok": True, "path": "public/widget.js", "start_line": 1,
                "end_line": 20, "line_count": 20, "sha256": "a" * 64,
            },
        })
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }

        edit = policy.active_descriptors(route, state)[0]
        operation = edit["input_schema"]["properties"]["operations"]["items"]
        self.assertEqual(edit["name"], "edit")
        self.assertEqual(operation["properties"]["path"]["enum"], ["public/widget.js"])
        self.assertEqual(operation["properties"]["op"]["enum"], ["replace"])

    def test_unresolved_search_focus_constrains_the_next_read(self) -> None:
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        trajectory.append(state, {
            "kind": "tool", "tool": "search", "status": "completed",
            "result": {"ok": True, "focus": {"owner_file": "public/widget.js", "line_count": 20}},
        })
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }

        read = policy.active_descriptors(route, state)[0]
        self.assertEqual(read["name"], "read")
        self.assertEqual(read["input_schema"]["properties"]["path"]["enum"], ["public/widget.js"])

    def test_llm_autonomous_keeps_only_unexhausted_authorized_tools_visible(self) -> None:
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        state["operation_ledger"].update({"revision": 1, "check": {"rev": 1, "ok": True}})
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        self.assertEqual(
            [item["name"] for item in policy.active_descriptors(route, state)],
            ["diff", "prove"],
        )

    def test_autonomous_implementation_edit_schema_does_not_advertise_dry_run(self) -> None:
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        edit = next(item for item in policy.descriptors_for(route) if item["name"] == "edit")
        self.assertNotIn("dry_run", edit["input_schema"]["properties"])
        self.assertEqual(
            edit["input_schema"]["properties"]["operations"]["items"]["properties"]["op"]["enum"],
            ["create", "replace", "append"],
        )
        self.assertIn("dry_run", next(item for item in policy.tool_descriptors() if item["name"] == "edit")["input_schema"]["properties"])

    def test_autonomous_implementation_forces_edit_after_all_declared_evidence_is_read(self) -> None:
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        for path, line_count in (("public/widget.js", 20), ("tests/widget.test.mjs", 8)):
            trajectory.append(state, {
                "kind": "tool", "tool": "read", "status": "completed",
                "result": {
                    "ok": True, "path": path, "start_line": 1,
                    "end_line": line_count, "line_count": line_count,
                },
            })
        route = {
            "route_id": "fixture.ui",
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "checks": [{
                "id": "widget",
                "evidence_paths": ["public/widget.js", "tests/widget.test.mjs"],
            }],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }

        self.assertEqual(
            [item["name"] for item in policy.active_descriptors(route, state)],
            ["edit"],
        )

    def test_autonomous_implementation_keeps_read_open_for_partial_declared_file(self) -> None:
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        trajectory.append(state, {
            "kind": "tool", "tool": "read", "status": "completed",
            "result": {
                "ok": True, "path": "public/widget.js",
                "start_line": 1, "end_line": 200, "line_count": 597,
            },
        })
        route = {
            "route_id": "fixture.ui",
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "checks": [{"id": "widget", "evidence_paths": ["public/widget.js"]}],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }

        names = [item["name"] for item in policy.active_descriptors(route, state)]
        self.assertIn("read", names)
        self.assertNotIn("edit", names)
        self.assertNotIn("test", names)
        self.assertNotIn("diff", names)
        self.assertNotIn("prove", names)
        read = next(item for item in policy.active_descriptors(route, state) if item["name"] == "read")
        self.assertIn(
            "Read these exact missing ranges next: public/widget.js:201-597.",
            read["description"],
        )

    def test_registered_check_ids_constrain_the_model_visible_test_schema(self) -> None:
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read", "test.run", "proof.report"],
            "checks": [{"id": "focused"}, {"id": "smoke"}],
            "task_contract": {"request_class": "verification"},
        }

        test = next(item for item in policy.descriptors_for(route) if item["name"] == "test")

        self.assertEqual(test["input_schema"]["properties"]["check_id"]["enum"], ["focused", "smoke"])
        self.assertIn("Allowed checks: focused; smoke.", test["description"])

    def test_missing_patch_preimage_reopens_read_after_owner_coverage(self) -> None:
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        state["last_error"] = {"code": "patch_precondition_required"}
        state["operation_ledger"]["revision"] = 1
        route = {
            "route_id": "fixture.ui",
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "checks": [{"id": "owner", "evidence_paths": ["owner.py"]}],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }

        self.assertEqual(
            [item["name"] for item in policy.active_descriptors(route, state)],
            ["read", "edit", "test", "diff", "prove"],
        )

    def test_failed_pre_mutation_edit_retires_checkpoint_until_repair(self) -> None:
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        trajectory.append(state, {
            "kind": "tool", "tool": "read", "status": "completed",
            "result": {
                "ok": True, "path": "owner.py",
                "start_line": 1, "end_line": 10, "line_count": 10,
            },
        })
        state["last_error"] = {
            "code": "patch_non_unique_match", "tool": "edit",
            "message": "Replace match must be unique.",
        }
        route = {
            "route_id": "fixture.ui",
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "checks": [{"id": "owner", "evidence_paths": ["owner.py"]}],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }

        names = [item["name"] for item in policy.active_descriptors(route, state)]

        self.assertNotIn("checkpoint", names)
        self.assertIn("edit", names)


if __name__ == "__main__":
    unittest.main()
