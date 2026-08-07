#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
import json
import hashlib
import sqlite3
import types
from pathlib import Path
from unittest.mock import patch

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier import authority, budget, controller_v5, persistence, planner, provider_tools, run_control, run_protocol, session_context, token_ledger
from master_frontier.v5 import answer_satisfaction, completion, continuity, decision_record, final_claims, loop, operation_ledger, policy, proof, reliability, task_lineage, task_policy, tools, trajectory, wire
from master_frontier.v5 import context
from master_frontier.v5.errors import V5Error


def route(root: Path) -> dict[str, object]:
    return {
        "route_id": "fixture.ui", "workspace_root": str(root), "allowed_read_roots": [str(root)],
        "caps": ["repo.read"], "task_contract": {"request_class": "source_investigation"}, "owner": "fixture",
    }


class MasterFrontierV5Tests(unittest.TestCase):
    def test_subscription_provider_receives_only_v5_messages_and_declared_tools(self) -> None:
        calls = []
        provider = types.SimpleNamespace(complete=lambda messages, tools, **kwargs: calls.append(
            (messages, tools, kwargs)
        ) or {"reply": "subscription answer", "tool_calls": [], "usage": {"total_tokens": 5}})
        proxy = {
            "messages": [{"role": "user", "content": "MF5/2"}],
            "tools": [{"type": "function", "function": {"name": "read"}}],
            "tool_choice": "required",
            "_timeout_sec": 12.4,
        }
        with patch.dict("sys.modules", {"codex_subscription_provider": provider}), patch.dict(
            "os.environ", {
                "HERMES_WASM_AGENT_FRONTIER_PROVIDER": "codex_subscription",
                "MF5_CODEX_MODEL": "gpt-5.6-sol",
            }, clear=False,
        ):
            result = controller_v5._provider_complete(
                {}, object(), {}, {}, proxy,
                receiver="openai-codex", run_id="run-sub", user={"id": "u1"},
            )

        self.assertEqual(result["reply"], "subscription answer")
        self.assertEqual(calls[0][0], proxy["messages"])
        self.assertEqual(calls[0][1], proxy["tools"])
        self.assertEqual(calls[0][2], {
            "completion_only": False, "require_tool": True, "timeout": 12, "model": "gpt-5.6-sol",
        })

    def test_search_is_grounded_in_distinctive_objective_terms(self) -> None:
        bound = loop.bind_search_objective(
            {"query": "space widget patterns"},
            "Create Anaminese and stream the TLS realtime transcript in Realuse.",
        )
        self.assertIn("space widget patterns", bound["query"])
        self.assertIn("Anaminese", bound["query"])
        self.assertIn("transcript", bound["query"])
        self.assertIn("Realuse", bound["query"])

    def test_codex_receiver_bypasses_provider_proxy(self) -> None:
        calls = []
        runtime = {
            "provider_proxy_completion": lambda *_a, **_kw: self.fail("Codex receiver must not use browser provider config"),
            "openai_responses_completion": lambda _server, body, envelope, **kwargs: calls.append((body, envelope, kwargs)) or {
                "reply": "Hello from Codex", "usage": {"total_tokens": 3},
            },
        }
        result = controller_v5._provider_complete(
            runtime, object(), {"message": "hello", "provider_config": {"provider": "opencode-go"}},
            {"objective": "hello", "route_id": "fixture.ui", "route_contract": {"route_id": "fixture.ui"}},
            {"messages": [{"role": "user", "content": "MF5 hello"}], "tools": [{"type": "function", "name": "read"}], "tool_choice": "auto", "max_tokens": 120},
            receiver="openai-codex", run_id="run-codex", user={"id": "user-1"},
        )
        self.assertEqual(result["reply"], "Hello from Codex")
        body, envelope, kwargs = calls[0]
        self.assertEqual(body["max_output_tokens"], 120)
        self.assertEqual(envelope["compact_state"]["messages"][0]["content"], "MF5 hello")
        self.assertEqual(envelope["compact_state"]["tools"][0]["name"], "read")
        self.assertEqual(kwargs["run_id"], "run-codex")

    def test_implementation_defaults_to_model_autonomy_without_overriding_policy(self) -> None:
        defaulted = controller_v5._apply_default_decision_mode({"task_contract": {"request_class": "implementation"}})
        conservative = controller_v5._apply_default_decision_mode({
            "task_contract": {"request_class": "implementation", "decision_mode": "proof_gated"},
        })
        self.assertEqual(defaulted["task_contract"]["decision_mode"], "llm_autonomous")
        self.assertEqual(conservative["task_contract"]["decision_mode"], "proof_gated")

    def test_advisory_call_target_does_not_stop_autonomous_implementation(self) -> None:
        state = trajectory.new("run", "turn", "fix", "fixture.ui")
        routed = {
            "route_id": "fixture.ui", "budget": {"api_calls_max": 2},
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        decisions = 0

        def complete(*_):
            nonlocal decisions
            decisions += 1
            if decisions <= 7:
                return {"tool_calls": [{"name": "checkpoint", "arguments": {"situation": f"still inspecting {decisions}"}}]}
            return {"reply": "No mutation was applied."}

        with self.assertRaises(V5Error) as raised:
            loop.run("fix", routed, state, complete=complete, execute=lambda name, args: tools.execute(name, args, routed, invoke=lambda *_: {}))
        self.assertEqual(raised.exception.code, "no_semantic_progress")
        self.assertEqual(decisions, 2)
        self.assertEqual(state["loop_counters"]["provider_attempts"], 2)

    def test_empty_provider_response_uses_bounded_transient_retry_policy(self) -> None:
        state = trajectory.new("run", "turn", "hello", "fixture.ui")
        self.assertTrue(reliability.can_retry(state, "provider-empty-response"))

    def test_cooperative_cancellation_stops_before_provider_or_tool_work(self) -> None:
        state = trajectory.new("cancel-me", "turn", "fix", "fixture.ui")
        run_control.request("cancel-me")
        try:
            with self.assertRaises(V5Error) as raised:
                loop.run(
                    "fix", {"route_id": "fixture.ui", "task_contract": {"request_class": "implementation"}}, state,
                    complete=lambda *_: self.fail("cancelled run must not call provider"),
                    execute=lambda *_: self.fail("cancelled run must not execute tools"),
                    cancelled=lambda: run_control.requested("cancel-me"),
                )
            self.assertEqual(raised.exception.code, "agent_run_cancelled")
        finally:
            run_control.clear("cancel-me")

    def test_cancelled_continuation_is_explicitly_resumable(self) -> None:
        self.assertTrue(controller_v5._resume_requested(None, {"previous_status": "cancelled"}))
        self.assertTrue(controller_v5._resume_requested(None, {"previous_status": "interrupted"}))
        self.assertFalse(controller_v5._resume_requested(None, {"previous_status": "completed"}))

    def test_autonomous_executive_capsule_is_model_owned_and_restart_durable(self) -> None:
        state = trajectory.new("run", "turn", "improve", "fixture.ui")
        routed = {"route_id": "fixture.ui", "task_contract": {"request_class": "conversation", "decision_mode": "llm_autonomous"}}
        replies = iter([
            {"tool_calls": [{"name": "checkpoint", "arguments": {"goal": "Improve the widget", "plan": "Inspect then patch", "next": "Read its owner", "outcomes": [{"id": "plan", "state": "done", "objective": "Record the plan", "evidence": "Checkpoint receipt"}]}}]},
            {"reply": "I chose to stop after recording the plan."},
        ])
        outcome = loop.run("improve", routed, state, complete=lambda *_: next(replies), execute=lambda name, args: tools.execute(name, args, routed, invoke=lambda *_: {}))
        self.assertEqual(outcome.answer, "I chose to stop after recording the plan.")
        self.assertEqual(state["executive"]["goal"], "Improve the widget")
        restored = trajectory.restore(state, run_id="run-2", turn_id="turn-2", objective="continue", route_id="fixture.ui")
        self.assertEqual(restored["executive"]["next"], "Read its owner")
        self.assertEqual(restored["executive"]["outcomes"][0]["state"], "done")

    def test_done_model_owned_outcome_allows_completion(self) -> None:
        state = trajectory.new("run", "turn", "inspect", "fixture.ui")
        routed = {"route_id": "fixture.ui", "caps": ["repo.read"], "task_contract": {"request_class": "conversation", "decision_mode": "llm_autonomous"}}
        replies = iter([
            {"tool_calls": [{"name": "checkpoint", "arguments": {"outcomes": [{"id": "inspect", "state": "done", "objective": "Inspect owner", "evidence": "Read receipt"}]}}]},
            {"reply": "Inspection complete."},
        ])
        outcome = loop.run("inspect", routed, state, complete=lambda *_: next(replies), execute=lambda name, args: tools.execute(name, args, routed, invoke=lambda *_: {}))
        self.assertEqual(outcome.answer, "Inspection complete.")
        self.assertEqual(state["executive"]["outcomes"][0]["state"], "done")

    def test_unavailable_required_tool_blocks_outcome_without_looping(self) -> None:
        state = trajectory.new("run", "turn", "inspect", "fixture.ui")
        routed = {"route_id": "fixture.ui", "caps": ["repo.read"], "task_contract": {"request_class": "conversation", "decision_mode": "llm_autonomous"}}
        replies = iter([
            {"tool_calls": [{"name": "checkpoint", "arguments": {"outcomes": [{"id": "patch", "state": "open", "objective": "Patch owner", "requires": "edit"}]}}]},
            {"reply": "Blocked because this route has no edit capability."},
        ])
        outcome = loop.run("inspect", routed, state, complete=lambda *_: next(replies), execute=lambda name, args: tools.execute(name, args, routed, invoke=lambda *_: {}))
        blocked = state["executive"]["outcomes"][0]
        self.assertEqual(outcome.answer, "Blocked because this route has no edit capability.")
        self.assertEqual(blocked["state"], "blocked")
        self.assertIn("unavailable", blocked["reason"])

    def test_repeated_final_with_open_outcome_terminates_resumably(self) -> None:
        state = trajectory.new("run", "turn", "inspect", "fixture.ui")
        routed = {"route_id": "fixture.ui", "caps": ["repo.read"], "task_contract": {"request_class": "conversation", "decision_mode": "llm_autonomous"}}
        replies = iter([
            {"tool_calls": [{"name": "checkpoint", "arguments": {"outcomes": [{"id": "read", "state": "open", "objective": "Read owner", "requires": "read"}]}}]},
            {"reply": "Finished without reading."},
            {"reply": "Still finished without reading."},
            {"reply": "Again finished without reading."},
        ])
        with self.assertRaises(V5Error) as raised:
            loop.run("inspect", routed, state, complete=lambda *_: next(replies), execute=lambda name, args: tools.execute(name, args, routed, invoke=lambda *_: {}))
        self.assertEqual(raised.exception.code, "outcomes_unresolved")
        self.assertEqual(state["loop_counters"]["outcome_repairs"], 3)

    def test_autonomous_implementation_cannot_claim_completion_without_mutation(self) -> None:
        state = trajectory.new("run", "turn", "improve", "fixture.ui")
        routed = {"route_id": "fixture.ui", "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"}}
        assessment = completion.assess(state, routed)
        self.assertEqual(assessment["status"], "incomplete")
        self.assertEqual(assessment["required_gaps"], ["repository mutation"])
        with self.assertRaisesRegex(V5Error, "no applied repository mutation") as raised:
            loop.run(
                "improve", routed, state,
                complete=lambda *_: {"reply": "I changed the widget."},
                execute=lambda *_: {},
            )
        self.assertEqual(raised.exception.code, "implementation_incomplete")

    def test_autonomous_implementation_denies_destructive_edit_operations(self) -> None:
        routed = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        for op in ("move", "delete"):
            result = tools.execute(
                "edit", {"operations": [{"op": op, "path": "widget.js", "expected_sha256": "a" * 64}]},
                routed, invoke=lambda *_: self.fail("denied edits must not reach the kernel"),
            )
            self.assertEqual(result["code"], "patch_operation_denied")

    def test_missing_edit_preimage_returns_exact_read_recovery(self) -> None:
        routed = {
            "route_id": "fixture.ui",
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }

        result = tools.execute(
            "edit", {"operations": [{"op": "append", "path": "tests/widget.test.js", "content": "\ncase();"}]},
            routed, invoke=lambda *_: self.fail("unbound edits must not reach the kernel"),
        )

        self.assertEqual(result["code"], "patch_precondition_required")
        self.assertEqual(result["paths"], ["tests/widget.test.js"])
        self.assertEqual(result["next_action"], {
            "tool": "read", "arguments": {"path": "tests/widget.test.js"},
        })

    def test_missing_read_path_is_not_mislabeled_as_invalid_line_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            owner = Path(tmp) / "public/modules/chat-composer"
            owner.mkdir(parents=True)
            (owner / "chat-composer.test.js").write_text("export const tests = [];\n")
            routed = {
                "route_id": "fixture.ui", "workspace_root": tmp,
                "allowed_read_roots": [tmp], "caps": ["repo.read"],
                "task_contract": {"request_class": "source_investigation"},
            }
            result = tools.execute(
                "read", {
                    "path": "public/modules/chat-composer/chat-composer.chat-composer.test.js",
                    "start_line": 1, "end_line": 80,
                },
                routed, invoke=lambda *_: self.fail("repository reads are host-owned"),
            )
        self.assertEqual(result["code"], "file_read_missing")
        self.assertEqual(result["candidates"][0], "public/modules/chat-composer/chat-composer.test.js")
        self.assertEqual(result["next_action"], {
            "tool": "read", "arguments": {"path": "public/modules/chat-composer/chat-composer.test.js"},
        })

    def test_comment_placeholder_and_probe_artifact_are_not_durable_mutations(self) -> None:
        routed = {
            "route_id": "fixture.ui",
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        placeholder = tools.execute(
            "edit", {"operations": [{
                "op": "create", "path": "widget.test.js",
                "content": "// placeholder", "expected_absent": True,
            }]}, routed, invoke=lambda *_: self.fail("placeholder must not reach kernel"),
        )
        probe = tools.execute(
            "edit", {"operations": [{
                "op": "create", "path": "__probe_integrity.txt",
                "content": "probe", "expected_absent": True,
            }]}, routed, invoke=lambda *_: self.fail("probe must not reach kernel"),
        )
        self.assertEqual(placeholder["code"], "implementation_placeholder_not_durable")
        self.assertEqual(probe["code"], "implementation_artifact_not_durable")

    def test_leading_slash_workspace_path_gets_safe_relative_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            owner = Path(tmp) / "public/modules/widget.js"
            owner.parent.mkdir(parents=True)
            owner.write_text("export const value = 1;\n")
            routed = {
                "route_id": "fixture.ui", "workspace_root": tmp,
                "allowed_read_roots": [tmp], "caps": ["repo.read"],
                "task_contract": {"request_class": "source_investigation"},
            }
            result = tools.execute(
                "read", {"path": "/public/modules/widget.js", "start_line": 1, "end_line": 20},
                routed, invoke=lambda *_: self.fail("repository reads are host-owned"),
            )
        self.assertEqual(result["code"], "file_read_scope_denied")
        self.assertEqual(result["next_action"], {
            "tool": "read", "arguments": {"path": "public/modules/widget.js"},
        })

    def test_directory_read_returns_bounded_route_relative_file_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "public/modules/widget"
            directory.mkdir(parents=True)
            (directory / "widget.js").write_text("export const value = 1;\n")
            (directory / "widget.test.js").write_text("test();\n")
            routed = {
                "route_id": "fixture.ui", "workspace_root": tmp,
                "allowed_read_roots": [tmp], "caps": ["repo.read"],
                "task_contract": {"request_class": "source_investigation"},
            }
            result = tools.execute(
                "read", {"path": str(directory)},
                routed, invoke=lambda *_: self.fail("repository reads are host-owned"),
            )

        self.assertEqual(result["code"], "file_read_missing")
        self.assertEqual(result["candidates"], [
            "public/modules/widget/widget.js",
            "public/modules/widget/widget.test.js",
        ])
        self.assertEqual(result["next_action"], {
            "tool": "read", "arguments": {"path": "public/modules/widget/widget.js"},
        })

    def test_edit_rejects_out_of_route_device_path_before_preimage_repair(self) -> None:
        routed = {
            "route_id": "fixture.ui", "workspace_root": "/workspace",
            "allowed_read_roots": ["/workspace"], "allowed_write_roots": ["/workspace"],
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        result = tools.execute(
            "edit", {"operations": [{"op": "replace", "path": "/dev/null", "content": "noop"}]},
            routed, invoke=lambda *_: self.fail("invalid path must not reach kernel"),
        )

        self.assertEqual(result["code"], "patch_path_scope_denied")
        self.assertNotIn("next_action", result)

    def test_proof_backed_rejected_implementation_can_finish_without_inventing_patch(self) -> None:
        routed = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/tmp"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        state = trajectory.new("run", "turn", "fix alleged defect", "fixture.ui")
        trajectory.append(state, {
            "kind": "tool", "tool": "read", "status": "completed",
            "result": {"ok": True, "path": "widget.js", "start_line": 1, "end_line": 40, "content": "already correct"},
        })
        state["operation_ledger"]["check"] = {"rev": 0, "ok": True, "check_id": "focused"}
        state["operation_ledger"]["diff"] = {"rev": 0, "ok": True}
        state["operation_ledger"]["proof"] = {"rev": 0, "ok": True}
        state["executive"]["decision"] = {
            "state": "rejected", "candidate": "Apply alleged fix", "targets": ["widget.js"],
            "acceptance": "Focused check passes", "blocker": "Source and baseline disprove the alleged defect.",
        }

        outcome = loop.run(
            "fix alleged defect", routed, state,
            complete=lambda *_: {"reply": "No patch was justified; source and the focused check disprove the premise."},
            execute=lambda *_: self.fail("verified no-op must not execute another tool"),
        )

        self.assertIn("No patch was justified", outcome.answer)
        self.assertEqual(outcome.trajectory["operation_ledger"]["revision"], 0)

    def test_blocked_label_without_noop_proof_cannot_skip_mutation(self) -> None:
        routed = {
            "route_id": "fixture.ui",
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        state = trajectory.new("run", "turn", "implement tests", "fixture.ui")
        trajectory.append(state, {
            "kind": "tool", "tool":"read", "status":"completed", "result":{"ok":True},
        })
        state["operation_ledger"]["check"] = {"rev": 0, "ok": True}
        state["operation_ledger"]["diff"] = {"rev": 0, "ok": True}
        state["executive"]["decision"] = {
            "state": "blocked", "candidate": "Implement tests",
            "targets": ["widget.test.js"], "acceptance": "Tests pass",
            "blocker": "More source reading is needed.",
        }
        self.assertFalse(completion.verified_noop(state, routed))
        self.assertEqual(completion.assess(state, routed)["required_gaps"], ["repository mutation"])

    def test_missing_mutation_repair_reopens_tools_after_forced_completion(self) -> None:
        state = trajectory.new("run", "turn", "improve", "fixture.ui")
        state["pending"] = "frontier_completion"
        routed = {
            "route_id": "fixture.ui", "caps": ["repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        replies = iter([
            {"reply": "I changed it."},
            {"tool_calls": [{"name": "edit", "arguments": {"operations": [{"op": "replace", "path": "widget.js", "find": "old", "replace": "new"}]}}]},
            {"tool_calls": [{"name": "test", "arguments": {"check_id": "focused"}}]},
            {"tool_calls": [{"name": "diff", "arguments": {}}]},
            {"tool_calls": [{"name": "prove", "arguments": {}}]},
            {"reply": "Applied and verified the widget.js change."},
        ])
        pending_seen = []

        def complete(*_args):
            pending_seen.append(state.get("pending"))
            return next(replies)

        def execute(name, _arguments):
            if name == "edit":
                return {
                    "ok": True, "applied": True, "dry_run": False,
                    "changed_files": ["widget.js"],
                    "postimage_sha256": {"widget.js": hashlib.sha256(b"new").hexdigest()},
                }
            if name == "test":
                return {"ok": True, "local_action": "test.run_focused", "result": {"ok": True, "check_id": "focused", "returncode": 0, "code": "ok"}}
            if name == "diff":
                return {"ok": True, "local_action": "git.diff_summary", "result": {"ok": True, "code": "ok", "returncode": 0, "changed_files": [{"path": "widget.js"}], "stat": {"complete": True}, "truncation": {}}}
            self.assertEqual(name, "prove")
            return {"ok": True, "primitive": "kernel.prove", "schema": "kernel.prove"}

        outcome = loop.run(
            "improve", routed, state, complete=complete, execute=execute,
            verify_worktree=lambda _ledger: {"ok": True, "digest": operation_ledger.worktree_digest(state["operation_ledger"])},
        )
        self.assertEqual(pending_seen[:2], ["frontier_completion", None])
        self.assertEqual(outcome.answer, "Applied and verified the widget.js change.")
        self.assertEqual(outcome.trajectory["operation_ledger"]["revision"], 1)
        self.assertEqual(operation_ledger.missing(outcome.trajectory["operation_ledger"]), [])

    def test_autonomous_mutation_remains_incomplete_until_current_revision_proof(self) -> None:
        state = trajectory.new("run", "turn", "fix", "fixture.ui")
        state["operation_ledger"] = operation_ledger.record(
            state["operation_ledger"], "edit",
            {"ok": True, "applied": True, "changed_files": ["widget.js"], "postimage_sha256": {"widget.js": "a" * 64}},
        )
        routed = {"route_id": "fixture.ui", "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"}}
        assessment = completion.assess(state, routed)
        self.assertEqual(assessment["status"], "incomplete")
        self.assertEqual(len(assessment["required_gaps"]), 3)
        self.assertEqual([item["tool"] for item in assessment["next_actions"]], ["test", "diff", "prove"])

    def test_mutation_final_claims_must_name_receipt_files_and_not_propose_code(self) -> None:
        ledger = {"changed_files": ["public/widget.js"]}
        normalized = final_claims.normalize("Implemented and verified the widget.", ledger)
        self.assertIn("public/widget.js", normalized)
        self.assertTrue(final_claims.validate(normalized, ledger)["ok"])
        self.assertTrue(final_claims.validate("Updated and verified public/widget.js.", ledger)["ok"])
        self.assertEqual(final_claims.validate("Done.", ledger)["code"], "final_claim_files_missing")
        self.assertEqual(final_claims.validate("Updated widget.js.\n```js\nnew code\n```", ledger)["code"], "final_claim_unapplied_patch_risk")

    def test_mutation_receipts_replace_false_tool_denial(self) -> None:
        ledger = {
            "route_id": "fixture.ui",
            "changed_files": ["public/widget.js", "public/registry.js"],
            "receipts": {
                "check": {"ok": True}, "diff": {"ok": True}, "proof": {"ok": True},
            },
        }
        normalized = final_claims.normalize(
            "I'm blocked: no repository tools are available. Changed files: none.", ledger,
        )
        self.assertEqual(
            normalized,
            "Implementation completed. Route: fixture.ui. Changed files: public/widget.js, public/registry.js. Verification receipts: check, diff, proof.",
        )
        self.assertTrue(final_claims.validate(normalized, ledger)["ok"])

    def test_runtime_claims_require_runtime_evidence(self) -> None:
        source_steps = [{
            "tool": "read", "status": "completed",
            "result": {"ok": True, "path": "public/widget.js"},
        }]
        runtime_steps = [{
            "tool": "inspect", "status": "completed",
            "result": {"ok": True, "runtime": {"result": {"visible": True}}},
        }]
        unsupported = final_claims.validate(
            "Verified runtime observations from bounded reads confirm the widget.",
            {},
            source_steps,
        )
        self.assertEqual(unsupported["code"], "final_claim_runtime_evidence_missing")
        self.assertTrue(final_claims.validate(
            "Source reads confirm the widget. No runtime evidence was collected.",
            {},
            source_steps,
        )["ok"])
        self.assertTrue(final_claims.validate(
            "Verified runtime observations confirm the widget is visible.",
            {},
            runtime_steps,
        )["ok"])
        self.assertEqual(proof.summarize(runtime_steps)["verification_level"], "runtime")
        self.assertEqual(proof.summarize([{
            "tool": "browser", "status": "completed",
            "result": {"ok": True, "snapshot": {"url": "https://example.test"}},
        }])["verification_level"], "runtime")
        self.assertEqual(proof.summarize([{
            "tool": "read", "status": "completed",
            "result": {"ok": True, "path": "cache.py", "content": "key = revision"},
        }])["verification_level"], "source")

    def test_verification_diff_does_not_claim_ambient_files_as_run_mutations(self) -> None:
        summary = proof.summarize(
            [{
                "ok": True,
                "local_action": "git.diff_summary",
                "result": {
                    "ok": True,
                    "changed_files": [{"path": "ambient.js"}],
                    "schema": "hermes.wasm_agent.route.git_diff_summary.v1",
                },
            }],
            operation_ledger.new("fixture.ui"),
        )

        self.assertEqual(summary["changed_files"], [])
        self.assertEqual(summary["observed_changed_files"], ["ambient.js"])
        self.assertFalse(summary["diff_seen"])

    def test_native_multi_tool_batch_executes_every_call_with_one_provider_charge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "x.py").write_text("x = 1\n", encoding="utf-8")
            routed = route(root); state = trajectory.new("run", "turn", "inspect", "fixture.ui")
            replies = iter([
                {"tool_calls": [
                    {"id": "one", "name": "search", "arguments": {"query": "x"}},
                    {"id": "two", "name": "read", "arguments": {"path": "x.py"}},
                ], "usage": {"total_tokens": 20}},
                {"reply": "Both observations were considered.", "usage": {"total_tokens": 5}},
            ])
            executed: list[str] = []
            def complete(_messages, _index):
                queued = state.get("queued_tool_calls") or []
                if queued:
                    call, state["queued_tool_calls"] = queued[0], queued[1:]
                    return {"tool_calls": [call], "usage": {}, "_mf5_replayed_tool_call": True}
                return next(replies)
            def execute(name, _arguments):
                executed.append(name)
                if name == "search": return {"ok": True, "matches": [], "summary": "searched"}
                return {"ok": True, "path": "x.py", "sha256": "a" * 64, "start_line": 1, "end_line": 1, "line_count": 1, "truncated": False, "content": "x = 1", "summary": "read"}
            outcome = loop.run("inspect", routed, state, complete=complete, execute=execute)
            self.assertEqual(executed, ["search", "read"])
            self.assertEqual(outcome.calls, 2)
            self.assertEqual(outcome.usage_totals["metered_calls"], 2)

    def test_system_prefers_direct_read_for_known_path(self) -> None:
        self.assertIn("Read an exact bounded repository path directly", context.SYSTEM)
        self.assertIn("Use search only to locate an unknown path", context.SYSTEM)
        self.assertIn("describing a proposed patch is not completion", context.SYSTEM)

    def test_registered_check_projects_bounded_evidence_paths_to_model(self) -> None:
        routed = {
            "route_id": "fixture.ui", "workspace_root": "/workspace",
            "allowed_read_roots": ["/workspace"], "caps": ["repo.read", "test.run", "proof.report"],
            "checks": [{
                "id": "widget",
                "command": ["node", "tests/widget.test.mjs"],
                "evidence_paths": ["public/widget.js", "tests/widget.test.mjs"],
            }],
            "task_contract": {"request_class": "verification"},
        }

        descriptor = next(item for item in policy.descriptors_for(routed) if item["name"] == "test")
        read_descriptor = next(item for item in policy.descriptors_for(routed) if item["name"] == "read")

        self.assertIn("widget (evidence: public/widget.js, tests/widget.test.mjs)", descriptor["description"])
        self.assertIn(
            "Required implementation evidence paths: public/widget.js, tests/widget.test.mjs.",
            read_descriptor["description"],
        )
        self.assertNotIn("node", descriptor["description"])

    def test_wire_always_projects_specific_durable_repair_targets(self) -> None:
        rendered = wire.encode({
            "objective": "implement",
            "last_error": {
                "code": "implementation_artifact_not_durable",
                "message": "Probe files are not durable.",
                "durable_targets": ["public/widget.js", "tests/widget.test.mjs"],
                "next_actions": [{"action": "edit_declared_target_with_substantive_content"}],
            },
            "completion_assessment": {
                "status": "incomplete", "reason": "Mutation required.",
                "next_actions": [{"tool": "edit", "arguments": {}}],
            },
        })

        self.assertIn(
            "durable_targets=['public/widget.js', 'tests/widget.test.mjs']",
            rendered,
        )

    def test_typed_tool_failures_remain_repairable_observations(self) -> None:
        class TypedFailure(Exception):
            code = "patch_invalid_replace"
            message = "Replace requires a non-empty find string."

        self.assertEqual(controller_v5._typed_tool_failure(TypedFailure()), {
            "ok": False,
            "code": "patch_invalid_replace",
            "summary": "Replace requires a non-empty find string.",
        })
        self.assertIsNone(controller_v5._typed_tool_failure(RuntimeError("transport broke")))

    def test_edit_preimage_is_bound_from_fresh_same_trajectory_read(self) -> None:
        digest = "a" * 64
        state = trajectory.new("run", "turn", "change it", "fixture.ui")
        trajectory.append(state, {
            "kind": "tool", "tool": "read", "status": "completed",
            "result": {"ok": True, "path": "x.py", "sha256": digest},
        })
        arguments = loop.bind_observed_preimages({
            "operations": [{"op": "replace", "path": "x.py", "find": "a", "replace": "b"}],
        }, state)
        self.assertEqual(arguments["operations"][0]["expected_sha256"], digest)
        explicit = loop.bind_observed_preimages({
            "operations": [{"op": "delete", "path": "x.py", "expected_sha256": "b" * 64}],
        }, state)
        self.assertEqual(explicit["operations"][0]["expected_sha256"], digest)

    def test_create_of_authoritatively_read_existing_path_becomes_replace(self) -> None:
        digest = "c" * 64
        state = trajectory.new("run", "turn", "work", "fixture.ui")
        state["observed_preimages"] = {"public/widget.js": digest}
        arguments = loop.bind_observed_preimages({
            "operations": [{"op": "create", "path": "public/widget.js", "content": "updated"}],
        }, state, {"workspace_root": "/workspace"})
        self.assertEqual(arguments["operations"][0]["op"], "replace")
        self.assertEqual(arguments["operations"][0]["expected_sha256"], digest)
        self.assertNotIn("expected_absent", arguments["operations"][0])

    def test_edit_preimage_binds_absolute_path_after_signed_restart(self) -> None:
        digest = "c" * 64
        state = trajectory.new("source", "turn", "change it", "fixture.ui")
        trajectory.append(state, {
            "kind": "tool", "tool": "read", "status": "completed",
            "result": {"ok": True, "path": "public/widget.js", "sha256": digest},
        })
        scope = continuity.binding(
            user_id="u", session_id="s", route_id="fixture.ui", route_digest="digest",
            source_run_id="source", source_turn_id="turn",
        )
        restored = continuity.restore(
            continuity.create(state, scope=scope), expected_scope=scope, previous_run_id="source",
            run_id="next", turn_id="next-turn", objective="continue", route_id="fixture.ui",
        )
        arguments = loop.bind_observed_preimages({
            "operations": [{"op": "replace", "path": "/workspace/public/widget.js", "find": "a", "replace": "b"}],
        }, restored, {"workspace_root": "/workspace"})
        self.assertEqual(arguments["operations"][0]["expected_sha256"], digest)

    def test_followup_edit_preimage_is_bound_from_current_mutation_postimage(self) -> None:
        before = "a" * 64
        after = "b" * 64
        state = trajectory.new("run", "turn", "change it", "fixture.ui")
        trajectory.append(state, {
            "kind": "tool", "tool": "read", "status": "completed",
            "result": {"ok": True, "path": "x.py", "sha256": before},
        })
        trajectory.append(state, {
            "kind": "tool", "tool": "edit", "status": "completed",
            "result": {"ok": True, "changed_files": ["x.py"]},
        })
        state["operation_ledger"]["postimages"] = {"x.py": after}

        arguments = loop.bind_observed_preimages({
            "operations": [{"op": "replace", "path": "x.py", "find": "b", "replace": "c"}],
        }, state)

        self.assertEqual(arguments["operations"][0]["expected_sha256"], after)

    def test_edit_preimage_survives_step_compaction_in_durable_map(self) -> None:
        digest = "d" * 64
        state = trajectory.new("run", "turn", "change it", "fixture.ui")
        state["observed_preimages"] = {"public/widget.js": digest}
        for index in range(trajectory.MAX_STEPS + 4):
            trajectory.append(state, {
                "kind": "tool", "tool": "checkpoint", "status": "completed",
                "summary": f"checkpoint {index}",
            })

        arguments = loop.bind_observed_preimages({
            "operations": [{
                "op": "replace", "path": "public/widget.js",
                "find": "before", "replace": "after",
            }],
        }, state)
        restored = trajectory.restore(
            state, run_id="next", turn_id="next-turn",
            objective="continue", route_id="fixture.ui",
        )

        self.assertEqual(arguments["operations"][0]["expected_sha256"], digest)
        self.assertEqual(restored["observed_preimages"], {"public/widget.js": digest})

    def test_create_automatically_binds_atomic_absence_precondition(self) -> None:
        state = trajectory.new("run", "turn", "create it", "fixture.ui")
        arguments = loop.bind_observed_preimages({
            "operations": [{"op": "create", "path": "new.py", "content": "value = 1\n"}],
        }, state)
        explicit = loop.bind_observed_preimages({
            "operations": [{"op": "create", "path": "new.py", "content": "value = 1\n", "expected_absent": False, "expected_sha256": "b" * 64}],
        }, state)

        self.assertIs(arguments["operations"][0]["expected_absent"], True)
        self.assertIs(explicit["operations"][0]["expected_absent"], True)
        self.assertNotIn("expected_sha256", explicit["operations"][0])

    def test_append_normalizes_advertised_insert_alias(self) -> None:
        state = trajectory.new("run", "turn", "append it", "fixture.ui")
        state["observed_preimages"] = {"owner.py": "a" * 64}
        arguments = loop.bind_observed_preimages({
            "operations": [{"op": "append", "path": "owner.py", "insert": "\nvalue = 2\n"}],
        }, state)

        self.assertEqual(arguments["operations"][0]["content"], "\nvalue = 2\n")
        self.assertEqual(arguments["operations"][0]["expected_sha256"], "a" * 64)

        replacement_alias = loop.bind_observed_preimages({
            "operations": [{"op": "append", "path": "owner.py", "replace": "\nvalue = 3\n"}],
        }, state)
        self.assertEqual(replacement_alias["operations"][0]["content"], "\nvalue = 3\n")
        after_alias = loop.bind_observed_preimages({
            "operations": [{"op": "append", "path": "owner.py", "after": "\nvalue = 4\n"}],
        }, state)
        self.assertEqual(after_alias["operations"][0]["content"], "\nvalue = 4\n")

    def test_edit_paths_collapse_a_repeated_workspace_root(self) -> None:
        state = trajectory.new("run", "turn", "create it", "fixture.ui")
        arguments = loop.bind_observed_preimages({
            "operations": [{
                "op": "create",
                "path": "local/plugins/wasm-agent/public/new-widget.js",
                "content": "export {}\n",
            }],
        }, state, {"workspace_root": "/local/plugins/wasm-agent"})

        self.assertEqual(arguments["operations"][0]["path"], "public/new-widget.js")

    def test_autonomous_implementation_rejects_dry_runs_and_temporary_creates(self) -> None:
        route_value = {
            "route_id": "fixture.ui",
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "checks": [{"id": "focused", "evidence_paths": ["owner.py", "tests/owner.test.py"]}],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        invoked = []

        dry_run = tools.execute("edit", {
            "dry_run": True,
            "operations": [{"op": "create", "path": "owner.py", "content": "x = 1\n", "expected_absent": True}],
        }, route_value, invoke=lambda primitive, payload: invoked.append((primitive, payload)) or {"ok": True})
        temporary = tools.execute("edit", {
            "operations": [{"op": "create", "path": ".tmp-plan.txt", "content": "plan", "expected_absent": True}],
        }, route_value, invoke=lambda primitive, payload: invoked.append((primitive, payload)) or {"ok": True})
        placeholder = tools.execute("edit", {
            "operations": [{"op": "create", "path": "new-module.txt", "content": "placeholder", "expected_absent": True}],
        }, route_value, invoke=lambda primitive, payload: invoked.append((primitive, payload)) or {"ok": True})
        empty_temp = tools.execute("edit", {
            "operations": [{"op": "create", "path": "tmp/new-module.js", "content": "", "expected_absent": True}],
        }, route_value, invoke=lambda primitive, payload: invoked.append((primitive, payload)) or {"ok": True})

        self.assertEqual(dry_run["code"], "implementation_dry_run_redundant")
        self.assertEqual(temporary["code"], "implementation_artifact_not_durable")
        self.assertEqual(placeholder["code"], "implementation_placeholder_not_durable")
        self.assertEqual(empty_temp["code"], "implementation_artifact_not_durable")
        self.assertEqual(placeholder["durable_targets"], ["owner.py", "tests/owner.test.py"])
        self.assertEqual(temporary["next_actions"], [
            {"action": "edit_declared_target_with_substantive_content"},
        ])
        self.assertEqual(invoked, [])

    def test_failed_tool_discards_stale_calls_from_the_same_provider_batch(self) -> None:
        state = trajectory.new("run", "turn", "fix", "fixture.ui")
        route_value = {
            "route_id": "fixture.ui",
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        responses = iter([{
            "tool_calls": [
                {"id": "one", "name": "edit", "arguments": {"dry_run": True, "operations": []}},
                {"id": "two", "name": "edit", "arguments": {"dry_run": True, "operations": []}},
            ],
        }, {"reply": "Blocked because no durable edit is justified."}])
        executed = []
        persisted = []

        with self.assertRaises(V5Error):
            loop.run(
                "fix", route_value, state,
                complete=lambda *_: next(responses),
                execute=lambda name, _args: executed.append(name) or {
                    "ok": False, "code": "implementation_dry_run_redundant", "summary": "Apply directly.",
                },
                persist=lambda current, reason: persisted.append((reason, dict(current.get("last_error") or {}))),
            )

        self.assertEqual(executed, ["edit"])
        action_error = next(error for reason, error in persisted if reason == "action_completed")
        self.assertEqual(action_error, {
            "code": "implementation_dry_run_redundant",
            "message": "Apply directly.",
            "tool": "edit",
        })

    def test_any_failed_edit_keeps_route_declared_durable_targets_in_repair(self) -> None:
        state = trajectory.new("run", "turn", "fix", "fixture.ui")
        routed = {
            "route_id": "fixture.ui",
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "checks": [{"id": "widget", "evidence_paths": ["public/widget.js", "tests/widget.test.mjs"]}],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        for path, count in (("public/widget.js", 10), ("tests/widget.test.mjs", 5)):
            trajectory.append(state, {
                "kind": "tool", "tool": "read", "status": "completed",
                "result": {
                    "ok": True, "path": path, "start_line": 1,
                    "end_line": count, "line_count": count,
                },
            })
        responses = iter([
            {"tool_calls": [{"name": "edit", "arguments": {
                "operations": [{"op": "replace", "path": "public/widget.js", "find": "x", "replace": "y"}],
            }}]},
        ])
        persisted = []

        with self.assertRaises(V5Error):
            loop.run(
                "fix", routed, state,
                complete=lambda *_: next(responses),
                execute=lambda *_: {
                    "ok": False, "code": "patch_non_unique_match",
                    "summary": "Replace match must be unique.",
                },
                persist=lambda current, reason: persisted.append((reason, dict(current.get("last_error") or {}))),
            )

        failure = next(error for reason, error in persisted if reason == "action_completed")
        self.assertEqual(failure["durable_targets"], ["public/widget.js", "tests/widget.test.mjs"])

    def test_existing_preimage_repair_keeps_only_the_exact_conflicting_target(self) -> None:
        state = trajectory.new("run", "turn", "fix", "fixture.ui")
        routed = {
            "route_id": "fixture.ui",
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/workspace"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        responses = iter([{"tool_calls": [{"name": "edit", "arguments": {"operations": [
            {"op": "create", "path": "public/widget.js", "content": "widget"},
            {"op": "create", "path": "public/registry.js", "content": "registry"},
        ]}}]}])
        persisted = []

        with self.assertRaises(V5Error):
            loop.run(
                "fix", routed, state,
                complete=lambda *_: next(responses),
                execute=lambda *_: {
                    "ok": False, "code": "patch_preimage_exists",
                    "summary": "Expected an absent target: public/widget.js",
                },
                persist=lambda current, reason: persisted.append((reason, dict(current.get("last_error") or {}))),
            )

        failure = next(error for reason, error in persisted if reason == "action_completed")
        self.assertEqual(failure["durable_targets"], ["public/widget.js"])

    def test_observed_replace_drops_contradictory_absent_precondition(self) -> None:
        digest = "a" * 64
        state = trajectory.new("run", "turn", "fix", "fixture.ui")
        state["observed_preimages"] = {"public/widget.js": digest}
        arguments = loop.bind_observed_preimages({
            "operations": [{
                "op": "replace", "path": "public/widget.js", "find": "old",
                "replace": "new", "expected_absent": True,
            }],
        }, state, {"workspace_root": "/workspace"})

        operation = arguments["operations"][0]
        self.assertNotIn("expected_absent", operation)
        self.assertEqual(operation["expected_sha256"], digest)

    def test_restart_checkpoint_is_bounded_scope_bound_and_content_free(self) -> None:
        state = trajectory.new("run-1", "turn-1", "Inspect owner", "fixture.ui")
        state["loop_counters"]["provider_attempts"] = 3
        state["observed_preimages"] = {"owner.py": "a" * 64}
        trajectory.append(state, {
            "kind": "tool", "action_id": "act-read", "tool": "read", "status": "completed",
            "result": {"ok": True, "path": "owner.py", "content": "PRIVATE-SOURCE-CONTENT" * 1000},
        })
        state["completed_actions"]["act-read"] = {
            "tool": "read", "observation": {"ok": True, "path": "owner.py", "content": "PRIVATE-SOURCE-CONTENT"},
        }
        scope = continuity.binding(user_id="u1", session_id="s1", route_id="fixture.ui", source_run_id="run-1", source_turn_id="turn-1")
        checkpoint = continuity.create(state, scope=scope)
        encoded = json.dumps(checkpoint, sort_keys=True)
        self.assertLessEqual(len(encoded), continuity.MAX_CHECKPOINT_CHARS + 100)
        self.assertNotIn("PRIVATE-SOURCE-CONTENT", encoded)
        restored = continuity.restore(
            checkpoint, expected_scope=continuity.binding(user_id="u1", session_id="s1", route_id="fixture.ui"),
            previous_run_id="run-1", run_id="run-2", turn_id="turn-2", objective="Continue", route_id="fixture.ui",
        )
        self.assertEqual(restored["root_objective"], "Inspect owner")
        self.assertEqual(restored["observed_preimages"], {"owner.py": "a" * 64})
        self.assertEqual(restored["loop_counters"]["provider_attempts"], 3)
        tampered = json.loads(json.dumps(checkpoint)); tampered["state"]["pending"] = "forged"
        with self.assertRaises(continuity.ContinuityError):
            continuity.restore(
                tampered, expected_scope=continuity.binding(user_id="u1", session_id="s1", route_id="fixture.ui"),
                previous_run_id="run-1", run_id="run-2", turn_id="turn-2", objective="Continue", route_id="fixture.ui",
            )

        routed_scope = continuity.binding(
            user_id="u1", session_id="s1", route_id="fixture.ui", route_digest="old",
            source_run_id="run-1", source_turn_id="turn-1",
        )
        routed = continuity.create(state, scope=routed_scope)
        with self.assertRaises(continuity.ContinuityError) as changed:
            continuity.restore(
                routed, expected_scope=continuity.binding(
                    user_id="u1", session_id="s1", route_id="fixture.ui", route_digest="new",
                ), previous_run_id="run-1", run_id="run-2", turn_id="turn-2",
                objective="Continue", route_id="fixture.ui",
            )
        self.assertEqual(changed.exception.code, "resume_checkpoint_scope_mismatch")

    def test_stale_route_checkpoint_starts_clean_with_signed_root_objective(self) -> None:
        state = trajectory.new("run-1", "turn-1", "Fix the bounded owner", "fixture.ui")
        state["loop_counters"]["provider_attempts"] = 9
        state["completed_actions"]["old-action"] = {"tool": "read", "observation": {"ok": True}}
        checkpoint = continuity.create(state, scope=continuity.binding(
            user_id="u1", session_id="s1", route_id="fixture.ui", route_digest="old",
            source_run_id="run-1", source_turn_id="turn-1",
        ))
        expected = continuity.binding(
            user_id="u1", session_id="s1", route_id="fixture.ui", route_digest="new",
        )

        replaced = continuity.replace_stale_route_checkpoint(
            checkpoint, expected_scope=expected, previous_run_id="run-1",
            run_id="run-2", turn_id="turn-2", objective="continue", route_id="fixture.ui",
        )

        self.assertEqual(replaced["root_objective"], "Fix the bounded owner")
        self.assertEqual(replaced["objective"], "continue")
        self.assertEqual(replaced["resumed_from"], "run-1")
        self.assertEqual(replaced["operation_ledger"]["revision"], 0)
        self.assertEqual(replaced["completed_actions"], {})
        self.assertEqual(replaced["loop_counters"]["provider_attempts"], 0)
        self.assertEqual(replaced["steps"][-1]["result"]["code"], "stale_checkpoint_replaced")

        wrong_principal = continuity.binding(
            user_id="u2", session_id="s1", route_id="fixture.ui", route_digest="new",
        )
        with self.assertRaises(continuity.ContinuityError) as cross_user:
            continuity.replace_stale_route_checkpoint(
                checkpoint, expected_scope=wrong_principal, previous_run_id="run-1",
                run_id="run-2", turn_id="turn-2", objective="continue", route_id="fixture.ui",
            )
        self.assertEqual(cross_user.exception.code, "resume_checkpoint_scope_mismatch")

        with self.assertRaises(continuity.ContinuityError) as already_current:
            continuity.replace_stale_route_checkpoint(
                checkpoint, expected_scope=continuity.binding(
                    user_id="u1", session_id="s1", route_id="fixture.ui", route_digest="old",
                ), previous_run_id="run-1", run_id="run-2", turn_id="turn-2",
                objective="continue", route_id="fixture.ui",
            )
        self.assertEqual(already_current.exception.code, "resume_checkpoint_not_stale")

    def test_controller_replaces_stale_route_checkpoint_for_continue(self) -> None:
        prior = trajectory.new("prior-run", "turn-1", "fix them all", "fixture.ui")
        checkpoint = continuity.create(prior, scope=continuity.binding(
            user_id="user-1", session_id="session-1", route_id="fixture.ui", route_digest="old",
            source_run_id="prior-run", source_turn_id="turn-1",
        ))
        continuation_context = {
            "requested": True, "previous_run_id": "prior-run", "previous_status": "interrupted",
            "resume_checkpoint": checkpoint,
        }
        events = []
        captured = []
        route_value = {
            "route_id": "fixture.ui", "owner": "fixture", "workspace_root": "/workspace",
            "allowed_read_roots": ["/workspace"], "allowed_write_roots": ["/workspace"],
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
        }
        runtime = {
            "auth_connect": lambda: None, "user_id": lambda _user: "user-1",
            "require_direct_envelope_route_contract": lambda _envelope: route_value,
            "append_agent_run_event": lambda _server, _run, kind, **kw: events.append((kind, kw.get("summary"))),
            "provider_config_for_proxy_body": lambda _body: {},
            "provider_proxy_completion": lambda _server, body, user=None: captured.append(body["messages"]) or {
                "reply": "Continued under the current route contract.", "usage": {"total_tokens": 5},
            },
            "append_envelope_v2_inference_usage": lambda *_a, **_kw: None,
            "record_agent_run_token_usage_event": lambda *_a, **_kw: None,
            "direct_envelope_redact": lambda value: value,
            "kernel_inspect_tool": lambda *_a, **_kw: {}, "kernel_act_tool": lambda *_a, **_kw: {},
            "kernel_prove_tool": lambda *_a, **_kw: {}, "finish_agent_run": lambda *_a, **_kw: None,
            "direct_envelope_error": lambda *_a, **_kw: self.fail("stale route digest must not abort continue"),
            "HTTPStatus": __import__("http").HTTPStatus,
        }
        envelope = {
            "objective": "continue", "objective_kind": "conversation",
            "compact_state": {"continuation_context": continuation_context},
        }
        with patch.object(controller_v5.session_context, "load_recent", return_value=[]), patch.object(
            controller_v5.session_context, "load_lineage_parent", return_value={}
        ), patch.object(
            controller_v5.session_context, "load_resume", return_value={
                "checkpoint": checkpoint, "previous_status": "interrupted", "evidence_steps": [],
            },
        ):
            result = controller_v5.execute_owned(
                object(), {"session_id": "session-1", "resume_checkpoint": checkpoint},
                user={"id": "user-1"}, run_record={"run_id": "current-run", "turn_id": "turn-2"},
                context={"envelope": envelope, "receiver": "stub"}, runtime=runtime,
            )

        self.assertEqual(result["reply"], "Continued under the current route contract.")
        self.assertIn(("state.writeback", "stale_checkpoint_replaced"), events)
        model_payload = captured[0][1]["content"]
        self.assertIn("J\tresumed=True;root_objective=fix them all", model_payload)
        self.assertIn("L\trev=0;mutations=0", model_payload)

    def test_interrupted_action_blocks_before_another_provider_call(self) -> None:
        state = trajectory.new("run", "turn", "edit", "fixture.ui")
        state["pending_action"] = {"action_id": "act-edit", "tool": "edit", "status": "started"}
        calls = []
        with self.assertRaises(V5Error) as raised:
            loop.run("edit", {"route_id": "fixture.ui"}, state, complete=lambda *_: calls.append(True) or {"reply": "done"}, execute=lambda *_: {})
        self.assertEqual(raised.exception.code, "action_outcome_unknown")
        self.assertEqual(calls, [])

    def test_interrupted_read_is_released_for_safe_retry(self) -> None:
        state = trajectory.new("run", "turn", "inspect", "fixture.ui")
        state["pending_action"] = {"action_id": "act-read", "tool": "read", "status": "started"}
        replies = iter([
            {"reply": '{"tool":"read","arguments":{"path":"x.py"}}'},
            {"reply": "Recovered from the repeated safe read."},
        ])
        outcome = loop.run(
            "inspect", {"route_id":"fixture.ui","task_contract":{"request_class":"source_investigation"}},
            state, complete=lambda *_: next(replies),
            execute=lambda *_: {
                "ok": True, "path": "x.py", "start_line": 1, "end_line": 1,
                "line_count": 1, "truncated": False, "content": "1: x = 1",
            },
        )
        self.assertEqual(outcome.answer, "Recovered from the repeated safe read.")
        self.assertIsNone(state["pending_action"])

    def test_advisory_restart_counters_do_not_impose_a_hidden_decision_budget(self) -> None:
        state = trajectory.new("run", "turn", "continue", "fixture.ui")
        state["loop_counters"]["provider_attempts"] = 120
        calls: list[bool] = []
        outcome = loop.run("continue", {"route_id": "fixture.ui", "budget": {"api_calls_max": 6}}, state, complete=lambda *_: calls.append(True) or {"reply": "done"}, execute=lambda *_: {})
        self.assertEqual(outcome.answer, "done")
        self.assertEqual(calls, [True])

    def test_explicit_hard_decision_budget_remains_enforced(self) -> None:
        state = trajectory.new("run", "turn", "continue", "fixture.ui")
        state["loop_counters"]["provider_attempts"] = 2
        with self.assertRaises(V5Error) as raised:
            loop.run("continue", {"route_id": "fixture.ui", "budget": {"api_calls_max": 2, "enforcement": "hard", "input_tokens_max": 10}}, state, complete=lambda *_: {"reply": "done"}, execute=lambda *_: {})
        self.assertEqual(raised.exception.code, "provider_call_budget_exhausted")

    def test_server_owned_resume_loader_scopes_checkpoint_and_rehydrates_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.sqlite3"
            state = trajectory.new("prior", "turn-1", "Inspect owner", "fixture.ui")
            checkpoint = continuity.create(state, scope=continuity.binding(
                user_id="u1", session_id="s1", route_id="fixture.ui", source_run_id="prior", source_turn_id="turn-1",
            ))
            connection = sqlite3.connect(path)
            connection.executescript("""
                CREATE TABLE agent_run_tb(run_id TEXT,turn_id TEXT,user_id TEXT,session_id TEXT,status TEXT,protocol TEXT,error_json TEXT);
                CREATE TABLE agent_run_event_tb(run_id TEXT,user_id TEXT,session_id TEXT,type TEXT,seq INTEGER,summary TEXT,payload_json TEXT);
            """)
            connection.execute("INSERT INTO agent_run_tb VALUES(?,?,?,?,?,?,?)", ("prior","turn-1","u1","s1","cancelled","v5","{}"))
            connection.execute("INSERT INTO agent_run_event_tb VALUES(?,?,?,?,?,?,?)", (
                "prior","u1","s1","state.writeback",1,"saved",json.dumps({"protocol":"v5","checkpoint":checkpoint}),
            ))
            connection.execute("INSERT INTO agent_run_event_tb VALUES(?,?,?,?,?,?,?)", (
                "prior","u1","s1","evidence.received",2,"read owner",json.dumps({"protocol":"v5","action_id":"act-read","tool":"read","result":{"ok":True,"path":"owner.py","sha256":"d" * 64,"content":"trusted ledger evidence"}}),
            ))
            connection.commit(); connection.close()
            def connect():
                db = sqlite3.connect(path); db.row_factory = sqlite3.Row; return db
            loaded = session_context.load_resume(connect, previous_run_id="prior", session_id="s1", user_id="u1")
            self.assertEqual(loaded["checkpoint"]["sha256"], checkpoint["sha256"])
            self.assertEqual(loaded["previous_status"], "cancelled")
            self.assertEqual(loaded["evidence_steps"][0]["result"]["sha256"], "d" * 64)
            self.assertEqual(loaded["evidence_steps"][0]["result"]["content"], "trusted ledger evidence")
            self.assertEqual(session_context.load_resume(connect, previous_run_id="prior", session_id="s1", user_id="u2"), {})

    def test_large_read_event_stays_structured_and_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.sqlite3"
            state = trajectory.new("prior", "turn-1", "Inspect owner", "fixture.ui")
            checkpoint = continuity.create(state, scope=continuity.binding(
                user_id="u1", session_id="s1", route_id="fixture.ui",
                source_run_id="prior", source_turn_id="turn-1",
            ))
            durable = trajectory.compact_observation(
                {"ok": True, "path": "owner.py", "content": "evidence-line\n" * 10_000},
                content_limit=12_000, max_chars=18_000,
            )
            event_payload = {"protocol": "v5", "action_id": "act-large", "tool": "read", "result": durable}
            encoded = persistence.bounded_json_text(event_payload, 24_000)
            self.assertNotIn("truncated_json", encoded)
            connection = sqlite3.connect(path)
            connection.executescript("""
                CREATE TABLE agent_run_tb(run_id TEXT,turn_id TEXT,user_id TEXT,session_id TEXT,status TEXT,protocol TEXT,error_json TEXT);
                CREATE TABLE agent_run_event_tb(run_id TEXT,user_id TEXT,session_id TEXT,type TEXT,seq INTEGER,summary TEXT,payload_json TEXT);
            """)
            connection.execute("INSERT INTO agent_run_tb VALUES(?,?,?,?,?,?,?)", ("prior","turn-1","u1","s1","interrupted","v5","{}"))
            connection.execute("INSERT INTO agent_run_event_tb VALUES(?,?,?,?,?,?,?)", (
                "prior","u1","s1","state.writeback",1,"saved",json.dumps({"protocol":"v5","checkpoint":checkpoint}),
            ))
            connection.execute("INSERT INTO agent_run_event_tb VALUES(?,?,?,?,?,?,?)", (
                "prior","u1","s1","evidence.received",2,"large read",encoded,
            ))
            connection.commit(); connection.close()
            def connect():
                db = sqlite3.connect(path); db.row_factory = sqlite3.Row; return db
            loaded = session_context.load_resume(connect, previous_run_id="prior", session_id="s1", user_id="u1")
            self.assertEqual(loaded["evidence_steps"][0]["action_id"], "act-large")
            self.assertEqual(loaded["evidence_steps"][0]["tool"], "read")
            self.assertIn("evidence-line", loaded["evidence_steps"][0]["result"]["content"])

    def test_checkpoint_without_evidence_resumes_tool_mode(self) -> None:
        state = trajectory.new("run", "turn", "inspect", "fixture.ui")
        trajectory.checkpoint(state, "provider_failed", "down")
        self.assertIsNone(state["pending"])
        self.assertFalse(context.completion_only(state, {"task_contract": {"request_class": "source_investigation"}}))

    def test_controller_reconstructs_prior_turn_and_preserves_action_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript("""
                CREATE TABLE agent_run_tb(run_id TEXT,turn_id TEXT,user_id TEXT,session_id TEXT,status TEXT,terminal_at INTEGER,updated_at INTEGER,final_json TEXT);
                CREATE TABLE agent_run_event_tb(run_id TEXT,user_id TEXT,session_id TEXT,type TEXT,seq INTEGER,summary TEXT);
            """)
            connection.execute("INSERT INTO agent_run_tb VALUES(?,?,?,?,?,?,?,?)", ("prior-run","turn-1","user-1","session-1","completed",1,1,json.dumps({"reply":"Two grounded defects.","route_id":"fixture.ui","diagnostics":{"verification_level":"source"}})))
            connection.execute("INSERT INTO agent_run_event_tb VALUES(?,?,?,?,?,?)", ("prior-run","user-1","session-1","envelope.created",1,"Criticize the widget"))
            connection.commit(); connection.close()
            captured: list[list[dict]] = []
            events: list[str] = []
            source = Path(tmp) / "x.py"; source.write_text("a")

            def connect():
                db = sqlite3.connect(path); db.row_factory = sqlite3.Row; return db
            replies = iter([
                '{"tool":"edit","arguments":{"operations":[{"op":"replace","path":"x.py","find":"a","replace":"b","expected_sha256":"' + hashlib.sha256(b"a").hexdigest() + '"}]}}',
                '{"tool":"test","arguments":{"check_id":"focused"}}',
                '{"tool":"diff","arguments":{}}',
                '{"tool":"prove","arguments":{}}',
                "I retained the prior defects, applied the x.py fix, and verified it.",
            ])
            def complete(_server, proxy_body, user=None):
                captured.append(proxy_body["messages"]); return {"reply": next(replies), "usage": {"total_tokens": 10}}
            def act(_server, payload, _user=None):
                action = payload["local_action"]
                if action == "patch.apply_scoped":
                    source.write_text("b")
                    result = {"ok": True, "applied": True, "dry_run": False, "changed_files": ["x.py"], "postimage_sha256": {"x.py": hashlib.sha256(b"b").hexdigest()}}
                elif action == "test.run_focused":
                    result = {"ok": True, "code": "ok", "check_id": "focused", "returncode": 0}
                else:
                    result = {"ok": True, "code": "ok", "returncode": 0, "changed_files": [{"path": "x.py"}], "stat": {"complete": True}, "truncation": {}}
                return {"ok": True, "primitive": "kernel.act", "local_action": action, "result": result}

            runtime = {
                "auth_connect": connect, "user_id": lambda _user: "user-1",
                "require_direct_envelope_route_contract": lambda _envelope: {"route_id":"fixture.ui","workspace_root":tmp,"allowed_read_roots":[tmp],"allowed_write_roots":[tmp],"caps":["repo.read","repo.edit","test.run","proof.report"]},
                "append_agent_run_event": lambda _server, _run, kind, **_kw: events.append(kind),
                "provider_config_for_proxy_body": lambda _body: {}, "provider_proxy_completion": complete,
                "append_envelope_v2_inference_usage": lambda *_a, **_kw: None, "record_agent_run_token_usage_event": lambda *_a, **_kw: None,
                "direct_envelope_redact": lambda value: value, "kernel_inspect_tool": lambda *_a, **_kw: {},
                "kernel_act_tool": act, "kernel_prove_tool": lambda *_a, **_kw: {"ok": True, "primitive": "kernel.prove"},
                "finish_agent_run": lambda *_a, **_kw: None, "direct_envelope_error": lambda *_a, **_kw: None,
                "HTTPStatus": __import__("http").HTTPStatus,
            }
            result = controller_v5.execute_owned(
                object(), {"session_id":"session-1","message":"Can you fix them all?"}, user={"id":"user-1"},
                run_record={"run_id":"current-run","turn_id":"turn-2"},
                context={"envelope":{"objective":"Can you fix them all?","objective_kind":"conversation"},"receiver":"stub"}, runtime=runtime,
            )
            prompt = captured[0][1]["content"]
            self.assertIn("Criticize the widget", prompt)
            self.assertIn("T\tsearch,read", prompt)
            self.assertEqual(result["reply"], "I retained the prior defects, applied the x.py fix, and verified it.")
            self.assertEqual(result["diagnostics"]["token_usage_total"], {
                "exact": True, "total_tokens": 50, "calls": 5, "metered_calls": 5,
            })

    def test_task_lineage_never_grants_edit_from_unverified_conversation(self) -> None:
        base = {"request_class": "conversation", "objective_kind": "conversation"}
        grounded = task_lineage.project(
            base,
            objective="Can you fix them all?",
            session_context=[{"turn_id": "t1", "route_id": "fixture.ui", "verification_level": "source"}],
            route_caps=["repo.read", "repo.edit"],
            route_id="fixture.ui",
        )
        ungrounded = task_lineage.project(
            base,
            objective="Can you fix them all?",
            session_context=[{"turn_id": "t1", "route_id": "fixture.ui", "verification_level": "route"}],
            route_caps=["repo.read", "repo.edit"],
            route_id="fixture.ui",
        )
        no_write_cap = task_lineage.project(
            base,
            objective="Can you fix them all?",
            session_context=[{"turn_id": "t1", "route_id": "fixture.ui", "verification_level": "source"}],
            route_caps=["repo.read"],
            route_id="fixture.ui",
        )
        self.assertEqual(grounded["request_class"], "implementation")
        self.assertEqual(grounded["lineage"]["parent_turn_id"], "t1")
        self.assertEqual(grounded["lineage"]["root_objective"], "Can you fix them all?")
        self.assertEqual(ungrounded["request_class"], "conversation")
        self.assertEqual(no_write_cap["request_class"], "conversation")

        update_me = task_lineage.project(
            base,
            objective="Can you update me on the issues?",
            session_context=[{"turn_id": "t1", "route_id": "fixture.ui", "verification_level": "source"}],
            route_caps=["repo.read", "repo.edit"],
            route_id="fixture.ui",
        )
        change_explanation = task_lineage.project(
            base,
            objective="Could you change your explanation?",
            session_context=[{"turn_id": "t1", "route_id": "fixture.ui", "verification_level": "source"}],
            route_caps=["repo.read", "repo.edit"],
            route_id="fixture.ui",
        )
        self.assertEqual(update_me["request_class"], "conversation")
        self.assertEqual(change_explanation["request_class"], "conversation")

    def test_bound_grounded_continuation_inherits_implementation_authority(self) -> None:
        base = {"request_class": "conversation", "objective_kind": "conversation"}
        parent = [{
            "run_id": "wa_run_parent", "turn_id": "turn-parent", "route_id": "fixture.ui",
            "status": "completed", "verification_level": "source",
            "root_objective": "Fix every verified widget defect",
        }]
        inherited = task_lineage.project(
            base, objective="continue", session_context=parent,
            route_caps=["repo.read", "repo.edit"], route_id="fixture.ui",
            continuation_context={"requested": True, "previous_run_id": "wa_run_parent"},
        )
        mismatched = task_lineage.project(
            base, objective="continue", session_context=parent,
            route_caps=["repo.read", "repo.edit"], route_id="fixture.ui",
            continuation_context={"requested": True, "previous_run_id": "different-run"},
        )
        self.assertEqual(inherited["request_class"], "implementation")
        self.assertEqual(inherited["lineage"]["kind"], "bound_continuation")
        self.assertEqual(inherited["lineage"]["parent_run_id"], "wa_run_parent")
        self.assertEqual(inherited["lineage"]["root_objective"], "Fix every verified widget defect")
        self.assertEqual(mismatched["request_class"], "conversation")

        source_classified = task_lineage.project(
            {"request_class": "source_investigation", "objective_kind": "source_investigation"},
            objective="continue", session_context=parent,
            route_caps=["repo.read", "repo.edit"], route_id="fixture.ui",
            continuation_context={"requested": True, "previous_run_id": "wa_run_parent"},
        )
        self.assertEqual(source_classified["request_class"], "implementation")
        self.assertEqual(source_classified["lineage"]["kind"], "bound_continuation")

    def test_bound_interrupted_continuation_inherits_implementation_authority(self) -> None:
        base = {"request_class": "conversation", "objective_kind": "conversation"}
        parent = [{
            "run_id": "wa_run_interrupted", "turn_id": "turn-parent", "route_id": "fixture.ui",
            "status": "interrupted", "verification_level": "source",
        }]

        inherited = task_lineage.project(
            base, objective="continue", session_context=parent,
            route_caps=["repo.read", "repo.edit"], route_id="fixture.ui",
            continuation_context={"requested": True, "previous_run_id": "wa_run_interrupted"},
        )
        unbound = task_lineage.project(
            base, objective="fix it", session_context=parent,
            route_caps=["repo.read", "repo.edit"], route_id="fixture.ui",
        )

        self.assertEqual(inherited["request_class"], "implementation")
        self.assertEqual(inherited["lineage"]["kind"], "bound_continuation")
        self.assertEqual(unbound["request_class"], "conversation")

    def test_task_lineage_requires_immediate_same_route_parent(self) -> None:
        base = {"request_class": "conversation", "objective_kind": "conversation"}
        cross_route = task_lineage.project(
            base,
            objective="Can you fix them all?",
            session_context=[{"turn_id": "t1", "route_id": "other.ui", "verification_level": "source"}],
            route_caps=["repo.read", "repo.edit"],
            route_id="fixture.ui",
        )
        intervening = task_lineage.project(
            base,
            objective="Can you fix them all?",
            session_context=[
                {"turn_id": "t1", "route_id": "fixture.ui", "verification_level": "source"},
                {"turn_id": "t2", "route_id": "fixture.ui", "verification_level": "route"},
            ],
            route_caps=["repo.read", "repo.edit"],
            route_id="fixture.ui",
        )
        self.assertEqual(cross_route["request_class"], "conversation")
        self.assertEqual(intervening["request_class"], "conversation")

    def test_restart_regression_source_critique_completes_with_old_quality_usage_shape(self) -> None:
        objective = "critisize meta-analysis widget inside realure space"
        route_value = {
            "route_id": "wasm-agent.avatar-chat.ui",
            "workspace_root": "/fixture",
            "allowed_read_roots": ["/fixture"],
            "caps": ["repo.read", "runtime.inspect"],
            "entities": [{"id": "wasm-agent.avatar-chat.ui", "kind": "scoped-run-history"}],
            "budget": {
                "head_tokens_max": 3000,
                "provider_tokens_max": 20000,
                "api_calls_max": 6,
                "wall_ms_max": 90000,
            },
        }
        planned = planner.task_contract({
            "objective": objective,
            "objective_kind": "diagnosis",
            "capabilities": route_value["caps"],
            "route_contract": route_value,
        })
        route_value["task_contract"] = authority.project_task_contract({
            "objective": objective,
            "objective_kind": "diagnosis",
            "task_contract": planned,
        }, route_value)
        self.assertEqual(planned["evidence_floor"], "source")
        self.assertNotIn("kernel.inspect", planned["tools_first"])
        self.assertTrue(authority.coherence(route_value)["ok"])
        self.assertEqual(
            [item["name"] for item in context.policy.descriptors_for(route_value)],
            ["search", "read"],
        )

        usage_totals = [964, 1947, 3600, 3910, 5790]
        replies = iter([
            {"reply": '{"tool":"search","arguments":{"query":"meta-analysis widget"}}'},
            {"reply": '{"tool":"read","arguments":{"path":"widget.js","start_line":1,"end_line":2}}'},
            {"reply": '{"tool":"read","arguments":{"path":"widget.js","start_line":3,"end_line":4}}'},
            {"reply": '{"tool":"read","arguments":{"path":"widget.js","start_line":5,"end_line":6}}'},
            {"reply": "The source-backed critique is complete."},
        ])

        def complete(*_):
            result = next(replies)
            result["usage"] = {"total_tokens": usage_totals.pop(0)}
            return result

        def execute(name, arguments):
            if name == "search":
                return {
                    "ok": True,
                    "focus": {
                        "owner_file": "widget.js",
                        "line_count": 6,
                        "suggested_ranges": [
                            {"start_line": 1, "end_line": 2},
                            {"start_line": 3, "end_line": 4},
                            {"start_line": 5, "end_line": 6},
                        ],
                    },
                }
            start = int(arguments["start_line"]); end = int(arguments["end_line"])
            return {
                "ok": True,
                "path": "widget.js",
                "start_line": start,
                "end_line": end,
                "line_count": 6,
                "truncated": False,
                "content": f"{start}: source\n{end}: source",
            }

        outcome = loop.run(
            objective,
            route_value,
            trajectory.new("restart-regression", "turn", objective, route_value["route_id"]),
            complete=complete,
            execute=execute,
        )
        self.assertEqual(outcome.answer, "The source-backed critique is complete.")
        self.assertEqual([item.get("path") for item in outcome.tools[1:]], ["widget.js"] * 3)
        self.assertEqual(budget.provider_tokens_used(outcome.usages), 16211)
        self.assertLess(16211, route_value["budget"]["provider_tokens_max"])

    def test_edit_runs_owned_verification_without_more_provider_decisions(self) -> None:
        implementation_route = {
            "route_id": "fixture.ui", "caps": ["repo.edit", "test.run", "proof.report"],
            "task_contract": {"request_class": "implementation"},
            "checks": [{"id": "focused", "evidence_paths": ["x.py"]}],
        }
        state = trajectory.new("run", "turn", "implement", "fixture.ui")
        state["executive"]["outcomes"] = [{
            "id": "stale-edit-plan", "state": "open",
            "objective": "Edit and verify x.py", "requires": "edit",
        }]
        responses = iter([
            {"reply": '{"tool":"edit","arguments":{"operations":[{"op":"replace","path":"x.py","find":"a","replace":"b"}]}}'},
            {"reply": '{"final":"Implemented and verified x.py."}'},
        ])
        provider_calls = 0
        diff_arguments = []

        def complete(*_args):
            nonlocal provider_calls
            queued = state.get("queued_tool_calls") or []
            if queued:
                call, state["queued_tool_calls"] = queued[0], queued[1:]
                return {"tool_calls": [call], "_mf5_replayed_tool_call": True}
            provider_calls += 1
            return next(responses)

        def execute(name, _arguments):
            if name == "edit": return {"ok": True, "primitive": "kernel.act", "local_action": "patch.apply_scoped", "result": {"applied": True, "dry_run": False, "changed_files": ["x.py"], "postimage_sha256": {"x.py": "a" * 64}}}
            if name == "test": return {"ok": True, "primitive": "kernel.act", "local_action": "test.run_focused", "result": {"schema": "hermes.wasm_agent.route.test_run_focused.v1", "ok": True, "check_id": "focused", "returncode": 0, "code": "ok"}}
            if name == "diff":
                diff_arguments.append(_arguments)
                return {"ok": True, "primitive": "kernel.act", "local_action": "git.diff_summary", "result": {"schema": "hermes.wasm_agent.route.git_diff_summary.v1", "ok": True, "code": "ok", "returncode": 0, "changed_files": [{"path": "x.py"}], "stat": {"complete": True}, "truncation": {}}}
            return {"ok": True, "schema": "hermes.wasm_agent.kernel.prove_result.v1", "primitive": "kernel.prove"}

        outcome = loop.run(
            "implement", implementation_route, state, complete=complete, execute=execute,
            verify_worktree=lambda ledger: {"ok": True, "digest": operation_ledger.worktree_digest(ledger)},
        )
        self.assertEqual(outcome.answer, "Implemented and verified x.py.")
        self.assertEqual(provider_calls, 2)
        self.assertEqual(diff_arguments, [{"paths": ["x.py"]}])
        self.assertEqual([item.get("local_action") or item.get("primitive") for item in outcome.tools], ["patch.apply_scoped", "test.run_focused", "git.diff_summary", "kernel.prove"])

    def test_implementation_cannot_finalize_without_applied_mutation(self) -> None:
        state = trajectory.new("run", "turn", "implement", "fixture.ui")
        route_value = {"route_id": "fixture.ui", "task_contract": {"request_class": "implementation"}}
        with self.assertRaises(V5Error) as raised:
            loop.run("implement", route_value, state, complete=lambda *_: {"reply": "Done."}, execute=lambda *_: {})
        self.assertEqual(raised.exception.code, "implementation_incomplete")
        self.assertEqual(state["loop_counters"]["implementation_repairs"], 2)

    def test_route_provider_and_wall_budgets_are_enforced(self) -> None:
        state = trajectory.new("run", "turn", "inspect", "fixture.ui")
        budget_route = {"route_id": "fixture.ui", "budget": {"api_calls_max": 1, "wall_ms_max": 60_000, "input_tokens_max": 1, "enforcement": "hard"}, "task_contract": {"request_class": "source_investigation"}}
        with self.assertRaises(V5Error) as calls:
            loop.run("inspect", budget_route, state, complete=lambda *_: {"reply": "No evidence."}, execute=lambda *_: {})
        self.assertEqual(calls.exception.code, "provider_call_budget_exhausted")

        ticks = iter([0.0, 0.0, 0.0, 2.0, 2.0, 2.0])
        with self.assertRaises(V5Error) as wall:
            loop.run("inspect", {**budget_route, "budget": {"task_lease_ms_max": 1_000}}, trajectory.new("r", "t", "inspect", "fixture.ui"), complete=lambda *_: {"reply": "No evidence."}, execute=lambda *_: {}, monotonic=lambda: next(ticks))
        self.assertEqual(wall.exception.code, "task_lease_exhausted")

    def test_action_descriptors_require_declared_route_capability(self) -> None:
        self.assertNotIn("edit", [item["name"] for item in context.policy.descriptors_for({"route_id": "fixture"})])
        with tempfile.TemporaryDirectory() as tmp:
            names = [item["name"] for item in context.policy.descriptors_for({
                "route_id": "fixture", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
                "allowed_write_roots": [tmp], "task_contract": {"request_class": "implementation"},
            })]
        self.assertEqual(names, ["search", "read", "edit", "test", "diff", "prove"])

    def test_autonomous_implementation_withdraws_exhausted_discovery_tools(self) -> None:
        routed = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/tmp"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        state = trajectory.new("run", "turn", "fix it", "fixture.ui")
        state["completed_actions"] = {
            "search": {"tool": "search", "observation": {"ok": True, "focus": {"owner_file": "widget.js"}}},
            "read-a": {"tool": "read", "observation": {"ok": True, "path": "widget.js", "start_line": 1, "end_line": 60, "line_count": 100}},
            "read-b": {"tool": "read", "observation": {"ok": True, "path": "widget.js", "start_line": 61, "end_line": 100, "line_count": 100}},
        }
        names = [item["name"] for item in policy.active_descriptors(routed, state)]
        self.assertEqual(names, ["edit"])

    def test_passing_baseline_check_preserves_edit_and_retires_discovery(self) -> None:
        routed = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/tmp"], "budget": {"api_calls_max": 6},
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        state = trajectory.new("run", "turn", "fix it", "fixture.ui")
        state["completed_actions"] = {
            "read": {"tool": "read", "observation": {"ok": True, "path": "widget.js", "start_line": 1, "end_line": 40, "line_count": 100}},
        }
        state["steps"] = [
            {"tool": "read", "status": "completed", "result": {"ok": True}},
            {"tool": "test", "status": "completed", "result": {"ok": True}},
        ]
        state["operation_ledger"]["check"] = {"rev": 0, "ok": True}
        state["executive"]["decision"] = {"state": "selected", "candidate": "Fix widget"}

        names = [item["name"] for item in policy.active_descriptors(routed, state)]

        self.assertEqual(names, ["edit"])

    def test_exact_read_retires_search_but_advisory_target_keeps_needed_read(self) -> None:
        routed = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/tmp"], "budget": {"api_calls_max": 2},
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        state = trajectory.new("run", "turn", "fix it", "fixture.ui")
        state["completed_actions"] = {
            "read": {"tool": "read", "observation": {"ok": True, "path": "widget.js", "start_line": 1, "end_line": 40, "line_count": 100}},
        }
        state["steps"] = [{"tool": "read", "status": "completed", "result": {"ok": True}}]
        state["loop_counters"]["provider_attempts"] = 2
        state["executive"]["decision"] = {"state": "selected", "candidate": "Fix widget"}
        state["executive"]["outcomes"] = [
            {"id": "more-source", "state": "open", "objective": "Read exact source", "requires": "read"},
        ]

        names = [item["name"] for item in policy.active_descriptors(routed, state)]

        self.assertEqual(names, ["read"])

    def test_model_owned_open_search_outcome_keeps_search_available(self) -> None:
        routed = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/tmp"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        state = trajectory.new("run", "turn", "fix it", "fixture.ui")
        state["completed_actions"] = {
            "read": {"tool": "read", "observation": {"ok": True, "path": "known.js", "start_line": 1, "end_line": 40, "line_count": 100}},
        }
        state["executive"]["outcomes"] = [
            {"id": "locate-owner", "state": "open", "objective": "Locate unknown owner", "requires": "search"},
        ]

        names = [item["name"] for item in policy.active_descriptors(routed, state)]

        self.assertIn("search", names)
        self.assertIn("read", names)
        self.assertNotIn("edit", names)

    def test_three_consecutive_discovery_misses_retire_discovery_not_edit(self) -> None:
        routed = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/tmp"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        state = trajectory.new("run", "turn", "fix it", "fixture.ui")
        state["completed_actions"] = {
            "read": {"tool": "read", "observation": {"ok": True, "path": "known.js", "start_line": 1, "end_line": 40, "line_count": 100}},
        }
        state["executive"]["outcomes"] = [
            {"id": "keep-looking", "state": "open", "objective": "Find more evidence", "requires": "search"},
            {"id": "keep-reading", "state": "open", "objective": "Read more evidence", "requires": "read"},
        ]
        state["loop_counters"]["no_progress"] = 3

        names = [item["name"] for item in policy.active_descriptors(routed, state)]

        self.assertEqual(names, ["search", "read"])

    def test_implementation_retires_checkpoint_without_spending_a_tool_turn(self) -> None:
        routed = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/tmp"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        state = trajectory.new("run", "turn", "fix it", "fixture.ui")
        names = [item["name"] for item in policy.active_descriptors(routed, state)]

        self.assertNotIn("checkpoint", names)
        self.assertNotIn("edit", names)
        state["steps"].append({"kind": "tool", "tool": "read", "status": "completed", "result": {"ok": True}})
        self.assertNotIn("checkpoint", [item["name"] for item in policy.active_descriptors(routed, state)])

    def test_stale_discovery_batch_is_rejected_after_baseline_check(self) -> None:
        routed = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/tmp"],
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }
        state = trajectory.new("run", "turn", "fix it", "fixture.ui")
        state["completed_actions"] = {
            "read": {"tool": "read", "observation": {"ok": True, "path": "widget.js", "start_line": 1, "end_line": 40, "line_count": 100}},
        }
        state["steps"] = [
            {"tool": "read", "status": "completed", "result": {"ok": True}},
            {"tool": "test", "status": "completed", "result": {"ok": True}},
        ]
        state["operation_ledger"]["check"] = {"rev": 0, "ok": True}
        replies = iter([
            {"tool_calls": [
                {"name": "search", "arguments": {"query": "first"}},
                {"name": "search", "arguments": {"query": "stale queued"}},
            ]},
            {"reply": "No mutation."},
            {"reply": "Still no mutation."},
        ])
        executed: list[str] = []

        with self.assertRaises(V5Error) as raised:
            loop.run(
                "fix it", routed, state, complete=lambda *_: next(replies),
                execute=lambda name, _arguments: executed.append(name) or {"ok": True},
            )

        self.assertEqual(raised.exception.code, "implementation_incomplete")
        self.assertEqual(executed, [])
        self.assertEqual(state["queued_tool_calls"], [])
        self.assertTrue(any(step.get("summary", "").startswith("The search tool is no longer active") for step in state["steps"]))

    def test_session_context_disables_self_contained_shortcut_and_is_projected(self) -> None:
        state = trajectory.new("run", "turn-2", "fix them", "fixture.ui")
        followup_route = {
            "route_id": "fixture.ui",
            "caps": ["repo.read"],
            "task_contract": {"request_class": "conversation"},
            "session_context": [{"turn_id": "turn-1", "objective": "criticize it", "answer": "Two defects."}],
        }
        self.assertFalse(task_policy.direct_completion(followup_route))
        payload = context.payload("fix them", followup_route, state)
        self.assertEqual(payload["continuity"]["turns"][0]["objective"], "criticize it")
        self.assertNotEqual(payload["tools"], [])
        self.assertIn("ordinary referential follow-ups", context.SYSTEM)

    def test_resolved_source_owner_is_encoded_for_the_decision_head(self) -> None:
        encoded = wire.encode({
            "objective": "inspect planner",
            "resolved_entity": {
                "id": "fixture.planner", "kind": "source-owner",
                "route_symbol": "server/planner.py", "symbols": ["task_contract"],
            },
        })
        self.assertIn("O!\tid=fixture.planner;kind=source-owner;route_symbol=server/planner.py", encoded)

    def test_sufficient_source_read_projects_content_for_synthesis(self) -> None:
        state = trajectory.new("run", "turn", "inspect planner", "fixture.ui")
        state["steps"] = [{
            "tool": "search", "status": "completed",
            "result": {"ok": True, "focus": {
                "owner_file": "planner.py", "line_count": 1,
                "suggested_ranges": [{"start_line": 1, "end_line": 1}],
            }},
        }, {
            "tool": "read", "status": "completed",
            "result": {
                "ok": True, "path": "planner.py", "content": "def task_contract(): pass\n",
                "start_line": 1, "end_line": 1, "line_count": 1, "truncated": False,
            },
        }]
        routed = {"route_id": "fixture.ui", "task_contract": {"request_class": "source_investigation"}}
        projected = context.payload("inspect planner", routed, state)
        read = next(item for item in projected["completed"] if item["tool"] == "read")
        self.assertEqual(read["result"]["content"], "def task_contract(): pass\n")

    def test_grounded_followup_projects_parent_as_bounded_implementation_spec(self) -> None:
        state = trajectory.new("run", "turn-2", "fix them all", "fixture.ui")
        answer = "Owner: public/modules/widget.js\n" + ("actionable defect\n" * 180)
        route = {
            "route_id": "fixture.ui",
            "caps": ["repo.read", "repo.edit"],
            "task_contract": {
                "request_class": "implementation",
                "lineage": {"parent_run_id": "parent-run"},
            },
            "session_context": [{
                "run_id": "parent-run", "turn_id": "turn-1",
                "objective": "Critique the widget", "answer": answer,
                "verification_level": "source",
                "decision": {
                    "state": "selected", "candidate": "Fix widget boundary",
                    "targets": ["public/modules/widget.js"],
                    "acceptance": "Boundary fixture passes",
                    "next_action": "Read public/modules/widget.js", "confidence": 0.9,
                },
            }],
        }
        payload = context.payload("fix them all", route, state)
        parent = payload["continuity"]["turns"][0]
        self.assertEqual(parent["relation"], "parent_spec")
        self.assertGreater(len(parent["answer"]), 1600)
        encoded = context.wire.encode(payload)
        self.assertIn("\tparent_spec\tCritique the widget\t", encoded)
        self.assertIn("actionable defect", encoded)
        self.assertIn("\nd\t", encoded)
        self.assertIn("Fix widget boundary", encoded)

    def test_parent_outline_survives_answer_clipping(self) -> None:
        answer = "# Review\n## First defect\n" + ("detail\n" * 1000) + "## Seventh defect\n"
        capsule = context._continuity_capsule([{
            "run_id": "parent", "turn_id": "one", "objective": "Review it", "answer": answer,
        }], active_parent_run_id="parent")
        self.assertEqual(capsule["turns"][0]["outline"], ["Review", "First defect", "Seventh defect"])
        encoded = context.wire.encode({"objective": "fix them", "continuity": capsule})
        self.assertIn("h\tReview | First defect | Seventh defect", encoded)
        self.assertIn("choose and ship the highest-leverage coherent slice", context.SYSTEM)

    def test_empty_checkpoint_is_not_reported_as_durable_progress(self) -> None:
        observed = tools.execute("checkpoint", {}, {
            "route_id": "fixture.ui",
            "task_contract": {"request_class": "implementation", "decision_mode": "llm_autonomous"},
        }, invoke=lambda *_: {})
        self.assertFalse(observed["ok"])
        self.assertEqual(observed["code"], "checkpoint_empty")

    def test_operational_decision_requires_executable_fields(self) -> None:
        selected, missing = decision_record.validate({
            "state": "selected", "candidate": "Fix boundary handling",
            "targets": ["retry_window.py"], "acceptance": "Boundary test passes",
            "next_action": "Read retry_window.py", "confidence": 1.4,
        })
        self.assertEqual(missing, [])
        self.assertEqual(selected["confidence"], 1.0)
        _blocked, missing = decision_record.validate({"state": "blocked", "candidate": "Fix it"})
        self.assertEqual(missing, ["blocker"])

    def test_planning_mode_exposes_evidence_and_checkpoint_but_not_mutation(self) -> None:
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "allowed_write_roots": ["/tmp"],
            "task_contract": {
                "request_class": "implementation_planning",
                "declared_classes": ["implementation_planning"],
                "decision_mode": "llm_autonomous",
            },
        }
        state = trajectory.new("plan", "turn", "plan the fix", "fixture.ui")
        self.assertEqual(
            [item["name"] for item in policy.active_descriptors(route, state)],
            ["checkpoint", "search", "read"],
        )
        invalid = tools.execute("checkpoint", {"decision": {
            "state": "selected", "candidate": "Fix boundary",
        }}, route, invoke=lambda *_: {})
        self.assertEqual(invalid["code"], "decision_record_invalid")
        valid = tools.execute("checkpoint", {"decision": {
            "state": "selected", "candidate": "Fix boundary", "targets": ["retry_window.py"],
            "acceptance": "Exact-boundary test passes", "next_action": "Read retry_window.py", "confidence": 0.9,
        }}, route, invoke=lambda *_: {})
        state["executive"] = valid["executive"]
        self.assertTrue(completion.ready(state, route))

    def test_planning_loop_completes_from_model_authored_decision_without_edit(self) -> None:
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read", "repo.edit"],
            "allowed_write_roots": ["/tmp"],
            "task_contract": {
                "request_class": "implementation_planning",
                "declared_classes": ["implementation_planning"],
                "decision_mode": "llm_autonomous",
            },
        }
        responses = iter([
            {"tool_calls": [{"name": "checkpoint", "arguments": {"decision": {
                "state": "selected", "candidate": "Fix boundary", "targets": ["retry_window.py"],
                "acceptance": "Boundary test passes", "next_action": "Read retry_window.py", "confidence": 0.8,
            }}}]},
            {"reply": "Selected the bounded boundary fix for execution."},
        ])
        outcome = loop.run(
            "plan the fix", route, trajectory.new("plan", "turn", "plan the fix", "fixture.ui"),
            complete=lambda *_: next(responses),
            execute=lambda name, args: tools.execute(name, args, route, invoke=lambda *_: {}),
        )
        self.assertEqual(outcome.answer, "Selected the bounded boundary fix for execution.")
        self.assertEqual(outcome.trajectory["operation_ledger"]["mutations"], [])

    def test_planning_finalization_window_is_bounded_and_checkpoint_only(self) -> None:
        route = {
            "route_id": "fixture.ui", "caps": ["repo.read"],
            "budget": {"api_calls_max": 2},
            "task_contract": {
                "request_class": "implementation_planning",
                "declared_classes": ["implementation_planning"],
                "decision_mode": "llm_autonomous",
            },
        }
        state = trajectory.new("plan", "turn", "plan", "fixture.ui")
        prompts = []
        with self.assertRaises(V5Error) as raised:
            loop.run(
                "plan", route, state,
                complete=lambda messages, _index: prompts.append(messages) or {
                    "tool_calls": [{"name": "search", "arguments": {"query": f"q{len(prompts)}"}}],
                },
                execute=lambda *_: {"ok": True, "matches": [], "summary": "No matches."},
            )
        self.assertEqual(raised.exception.code, "decision_planning_stalled")
        self.assertEqual(state["loop_counters"]["provider_attempts"], 4)
        self.assertIn("\nT\tcheckpoint\n", prompts[-1][1]["content"])

    def test_signed_continuity_checkpoint_preserves_operational_decision_state(self) -> None:
        state = trajectory.new("source", "turn", "plan", "fixture.ui")
        state["decision_finalization"] = True
        state["executive"] = {
            "goal": "Plan the fix", "decision": {
                "state": "selected", "candidate": "Fix boundary", "targets": ["retry_window.py"],
                "acceptance": "Boundary test passes", "next_action": "Read retry_window.py", "confidence": 0.8,
            },
        }
        scope = continuity.binding(
            user_id="u", session_id="s", route_id="fixture.ui", route_digest="digest",
            source_run_id="source", source_turn_id="turn",
        )
        checkpoint = continuity.create(state, scope=scope)
        restored = continuity.restore(
            checkpoint, expected_scope=scope, previous_run_id="source",
            run_id="next", turn_id="next-turn", objective="execute", route_id="fixture.ui",
        )
        self.assertTrue(restored["decision_finalization"])
        self.assertEqual(restored["executive"]["decision"]["candidate"], "Fix boundary")

    def test_session_context_reconstruction_is_user_scoped_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript("""
                CREATE TABLE agent_run_tb(run_id TEXT,turn_id TEXT,user_id TEXT,session_id TEXT,status TEXT,terminal_at INTEGER,updated_at INTEGER,final_json TEXT);
                CREATE TABLE agent_run_event_tb(run_id TEXT,user_id TEXT,session_id TEXT,type TEXT,seq INTEGER,summary TEXT);
            """)
            final = json.dumps({
                "reply":"Found two defects.", "route_id":"fixture.ui", "changed_files":[],
                "trajectory":{"root_objective":"Criticize and then fix the widget"},
                "diagnostics":{"verification_level":"source"},
                "decision": {
                    "state": "selected", "candidate": "Fix widget boundary",
                    "targets": ["public/modules/widget.js"],
                    "acceptance": "Boundary fixture passes",
                    "next_action": "Read public/modules/widget.js", "confidence": 0.9,
                },
            })
            connection.execute("INSERT INTO agent_run_tb VALUES(?,?,?,?,?,?,?,?)", ("r1","t1","u1","s1","completed",1,1,final))
            connection.execute("INSERT INTO agent_run_tb VALUES(?,?,?,?,?,?,?,?)", ("r2","t2","u2","s1","completed",2,2,final))
            connection.execute("INSERT INTO agent_run_event_tb VALUES(?,?,?,?,?,?)", ("r1","u1","s1","envelope.created",1,"Criticize the widget"))
            connection.commit(); connection.close()

            def connect():
                db = sqlite3.connect(path)
                db.row_factory = sqlite3.Row
                return db

            turns = session_context.load_recent(connect, session_id="s1", turn_id="t3", user_id="u1")
            self.assertEqual([(item["turn_id"], item["objective"]) for item in turns], [("t1", "Criticize the widget")])
            self.assertEqual(turns[0]["route_id"], "fixture.ui")
            self.assertEqual(turns[0]["root_objective"], "Criticize and then fix the widget")
            self.assertEqual(turns[0]["decision"]["candidate"], "Fix widget boundary")

    def test_interrupted_lineage_parent_uses_signed_checkpoint_root_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript("""
                CREATE TABLE agent_run_tb(run_id TEXT,turn_id TEXT,user_id TEXT,session_id TEXT,status TEXT,final_json TEXT);
                CREATE TABLE agent_run_event_tb(run_id TEXT,user_id TEXT,session_id TEXT,type TEXT,seq INTEGER,summary TEXT,payload_json TEXT);
            """)
            state = trajectory.new("parent", "turn-parent", "Fix the integrity regression", "fixture.ui")
            trajectory.append(state, {"kind":"system", "tool":"read", "status":"duplicate", "result":{"ok":True}})
            checkpoint = continuity.create(state, scope=continuity.binding(
                user_id="u1", session_id="s1", route_id="fixture.ui", route_digest="digest",
                source_run_id="parent", source_turn_id="turn-parent",
            ))
            connection.execute("INSERT INTO agent_run_tb VALUES(?,?,?,?,?,?)", ("parent","turn-parent","u1","s1","interrupted","{}"))
            connection.execute("INSERT INTO agent_run_event_tb VALUES(?,?,?,?,?,?,?)", ("parent","u1","s1","envelope.created",1,"continue","{}"))
            connection.execute("INSERT INTO agent_run_event_tb VALUES(?,?,?,?,?,?,?)", (
                "parent","u1","s1","state.writeback",2,"provider_interrupted",
                json.dumps({"checkpoint": checkpoint}),
            ))
            connection.commit(); connection.close()

            def connect():
                db = sqlite3.connect(path)
                db.row_factory = sqlite3.Row
                return db

            parent = session_context.load_lineage_parent(
                connect, previous_run_id="parent", session_id="s1", user_id="u1",
            )
            self.assertEqual(parent["root_objective"], "Fix the integrity regression")
            self.assertEqual(parent["route_id"], "fixture.ui")
            self.assertEqual(parent["verification_level"], "source")
            self.assertEqual(parent["status"], "interrupted")

    def test_declared_conversation_uses_direct_completion_without_tools(self) -> None:
        state = trajectory.new("run", "turn", "hello", "fixture.ui")
        direct_route = {"route_id": "fixture.ui", "task_contract": {"request_class": "conversation"}}
        calls = []
        def complete(messages, _index):
            calls.append(messages)
            self.assertEqual(context.payload("hello", direct_route, state)["tools"], [])
            self.assertIn("self-contained conversation", messages[0]["content"])
            return {"reply": "Hello."}
        outcome = loop.run("hello", direct_route, state, complete=complete, execute=lambda *_: self.fail("tool execution must not occur"))
        self.assertEqual(outcome.answer, "Hello.")
        self.assertEqual(outcome.calls, 1)
        self.assertEqual(outcome.tools, [])

    def test_model_decision_can_answer_directly_in_one_call(self) -> None:
        state = trajectory.new("run", "turn", "hello", "fixture.ui")
        decision_route = {
            "route_id": "fixture.ui",
            "caps": ["repo.read"],
            "task_contract": {"request_class": "model_decision"},
        }
        calls = []

        def complete(messages, _index):
            calls.append(messages)
            self.assertEqual(
                [item["function"]["name"] for item in policy.active_provider_tools(decision_route, state)],
                ["search", "read"],
            )
            self.assertNotIn("self-contained conversation", messages[0]["content"])
            return {"reply": "Hello."}

        outcome = loop.run(
            "hello", decision_route, state, complete=complete,
            execute=lambda *_: self.fail("the model did not request a tool"),
        )
        self.assertEqual(outcome.answer, "Hello.")
        self.assertEqual(outcome.calls, 1)
        self.assertEqual(outcome.tools, [])

    def test_model_decision_can_choose_bounded_source_evidence(self) -> None:
        state = trajectory.new("run", "turn", "how does your cache work?", "fixture.ui")
        decision_route = {
            "route_id": "fixture.ui",
            "workspace_root": "/workspace",
            "allowed_read_roots": ["/workspace"],
            "caps": ["repo.read"],
            "task_contract": {"request_class": "model_decision", "evidence_floor": "conceptual"},
        }
        decisions = iter([
            {"reply": '{"tool":"read","arguments":{"path":"cache.py"}}'},
            {"reply": "The cache uses revision-bound keys."},
        ])
        invoked = []

        outcome = loop.run(
            "how does your cache work?", decision_route, state,
            complete=lambda *_: next(decisions),
            execute=lambda name, arguments: invoked.append((name, arguments)) or {
                "ok": True,
                "path": "cache.py",
                "start_line": 1,
                "end_line": 1,
                "line_count": 1,
                "truncated": False,
                "content": "key = revision",
            },
        )

        self.assertEqual(invoked, [("read", {"path": "cache.py"})])
        self.assertEqual(outcome.answer, "The cache uses revision-bound keys.")
        self.assertEqual(outcome.calls, 2)

    def test_model_decision_retains_evidence_choice_after_inherited_source_evidence(self) -> None:
        decision_route = {
            "route_id": "fixture.ui",
            "caps": ["repo.read"],
            "task_contract": {"request_class": "model_decision"},
        }
        state = trajectory.new("run", "turn", "inspect the named widget", "fixture.ui")
        state["steps"].append({
            "tool": "read",
            "status": "completed",
            "result": {
                "ok": True,
                "path": "public/widget.js",
                "content": "export const widget = {};",
                "start_line": 1,
                "end_line": 1,
                "line_count": 1,
                "truncated": False,
            },
        })
        self.assertTrue(completion.ready(state, decision_route))
        self.assertFalse(context.completion_only(state, decision_route))
        self.assertEqual(
            [item["function"]["name"] for item in policy.active_provider_tools(decision_route, state)],
            ["search", "read"],
        )

    def test_source_investigation_understands_misspelled_widget_question_through_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            widget = root / "public/modules/property-photo-cleaner/property-photo-cleaner.entry.js"
            widget.parent.mkdir(parents=True)
            widget.write_text(
                'export const widget = { id: "property-photo-cleaner", title: "Property Photo Cleaner" };\n'
            )
            decision_route = {
                **route(root),
                "task_contract": {"request_class": "source_investigation"},
            }
            state = trajectory.new(
                "run", "turn",
                "hello, can you se the Property Photo Cleaner widget?",
                "fixture.ui",
            )
            responses = iter([
                {
                    "reply": "",
                    "tool_calls": [{
                        "name": "search",
                        "arguments": {"query": "Property Photo Cleaner", "limit": 8},
                    }],
                },
                {
                    "reply": "",
                    "tool_calls": [{
                        "name": "read",
                        "arguments": {
                            "path": (
                                "public/modules/property-photo-cleaner/"
                                "property-photo-cleaner.entry.js"
                            ),
                        },
                    }],
                },
                {"reply": "Yes. The source registers the Property Photo Cleaner widget."},
            ])
            outcome = loop.run(
                state["objective"], decision_route, state,
                complete=lambda *_: next(responses),
                execute=lambda name, args: tools.execute(
                    name, args, decision_route, invoke=lambda *_: {},
                ),
            )
            self.assertEqual(outcome.answer, "Yes. The source registers the Property Photo Cleaner widget.")
            self.assertEqual([item["tool"] for item in outcome.trajectory["steps"]], ["search", "read"])
            self.assertEqual(outcome.calls, 3)

    def test_direct_completion_requires_declared_class_not_prompt_heuristics(self) -> None:
        self.assertTrue(task_policy.direct_completion({"task_contract": {"objective_kind": "general_conversation"}}))
        self.assertFalse(task_policy.direct_completion({"task_contract": {"request_class": "model_decision"}}))
        self.assertFalse(task_policy.direct_completion({"task_contract": {"request_class": "source_investigation"}}))
        self.assertFalse(task_policy.direct_completion({"objective": "hello conversation answer directly"}))

    def test_grounded_final_repairs_once_until_fresh_tool_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "README.md").write_text("current source evidence\n")
            grounded_route = {**route(root), "task_contract": {"request_class": "source_investigation"}}
            state = trajectory.new("run", "turn", "can you see the codebase", "fixture.ui")
            responses = iter([
                {"reply": "Yes, I can see it."},
                {"reply": '{"tool":"read","arguments":{"path":"README.md"}}'},
                {"reply": "The current README confirms source access."},
            ])
            outcome = loop.run(
                "can you see the codebase", grounded_route, state,
                complete=lambda *_: next(responses),
                execute=lambda name, args: tools.execute(name, args, route(root), invoke=lambda *_: {}),
            )
            self.assertEqual(outcome.calls, 3)
            self.assertEqual([item["path"] for item in outcome.tools], ["README.md"])

    def test_gate_repair_requires_a_tool_on_the_next_provider_call(self) -> None:
        self.assertEqual(policy.provider_tool_choice({}), "auto")
        self.assertEqual(policy.provider_tool_choice({"last_error": {"code": "fresh_tool_evidence_required"}}), "required")
        self.assertEqual(policy.provider_tool_choice({"last_error": {"code": "implementation_action_required"}}), "required")

    def test_grounded_final_without_evidence_completes_unsatisfactory_after_one_repair(self) -> None:
        state = trajectory.new("run", "turn", "inspect source", "fixture.ui")
        grounded_route = {"route_id": "fixture.ui", "task_contract": {"request_class": "source_investigation"}}
        outcome = loop.run("inspect source", grounded_route, state, complete=lambda *_: {"reply": "Unsupported final."}, execute=lambda *_: {})
        self.assertIn("no fresh tool evidence", outcome.answer)
        self.assertEqual(outcome.trajectory["status"], "completed")
        self.assertEqual(outcome.trajectory["answer_satisfaction"]["status"], "unsatisfactory")
        self.assertEqual(outcome.trajectory["answer_satisfaction"]["code"], "evidence_incomplete")

    def test_runtime_capability_unavailable_is_conclusive_negative_evidence(self) -> None:
        state = trajectory.new("run", "turn", "inspect runtime", "fixture.ui")
        runtime_route = {"route_id": "fixture.ui", "task_contract": {"request_class": "runtime_inspection"}}
        responses = iter([
            {"reply": '{"tool":"inspect","arguments":{"target":"runtime_entity","id":"fixture"}}'},
            {"reply": "The runtime entity cannot be inspected because that capability is unavailable."},
        ])
        outcome = loop.run(
            "inspect runtime", runtime_route, state, complete=lambda *_: next(responses),
            execute=lambda *_: {"ok": False, "code": "capability_unavailable", "summary": "Runtime inspection is unavailable."},
        )
        self.assertEqual(outcome.calls, 2)
        self.assertEqual(outcome.tools[0]["code"], "capability_unavailable")
        self.assertEqual(outcome.trajectory["steps"][-1]["status"], "failed")

    def test_runtime_entity_denial_is_conclusive_negative_evidence(self) -> None:
        runtime_route = {"task_contract": {"request_class": "runtime_inspection"}}
        self.assertTrue(task_policy.accepts_tool_evidence(
            runtime_route, {"ok": False, "code": "runtime_action_entity_denied"},
        ))
        self.assertTrue(task_policy.accepts_tool_evidence(
            runtime_route, {"ok": False, "code": "runtime_entity_not_found"},
        ))

    def test_runtime_task_exposes_only_runtime_inspect(self) -> None:
        runtime_route = {"caps": ["runtime.inspect"], "entities": [{"id": "entity-a", "kind": "fixture"}], "task_contract": {"request_class": "runtime_inspection"}}
        self.assertEqual([item["name"] for item in context.policy.descriptors_for(runtime_route)], ["inspect"])
        self.assertEqual([item["function"]["name"] for item in context.policy.provider_tools(runtime_route)], ["inspect"])

    def test_runtime_inspect_requests_snapshot_then_exposes_compact_evidence(self) -> None:
        runtime_route = {"route_id": "route.a", "caps": ["runtime.inspect"], "entities": [{"id": "entity-a", "kind": "fixture"}], "task_contract": {"request_class": "runtime_inspection"}}
        invoked = []
        def invoke(name, arguments):
            invoked.append((name, arguments))
            return {"ok": True, "observations": [{"kind": "runtime_entity", "result": {
                "action_result": {"ok": True, "action": "runtime.snapshot.get", "snapshot": {
                    "e": {"id": "entity-a"}, "s": "degraded", "c": {"runs": 1},
                    "p": [{"id": "run-store-" + "a" * 24}], "u": [{"code": "live_state_not_collected"}],
                }},
            }}]}
        result = tools.execute("inspect", {"target": "runtime_entity", "id": "entity-a"}, runtime_route, invoke=invoke)
        self.assertTrue(result["ok"])
        self.assertEqual(result["runtime"]["action"], "runtime.snapshot.get")
        self.assertEqual(invoked[0][0], "kernel.inspect")
        self.assertEqual(invoked[0][1]["runtime_action"]["arguments"], {"route_id": "route.a", "entity_id": "entity-a"})

    def test_runtime_inspect_resolves_only_supplied_opaque_proof(self) -> None:
        proof_id = "run-store-" + "b" * 24
        runtime_route = {"route_id": "route.a", "caps": ["runtime.inspect"], "entities": [{"id": "entity-a", "kind": "fixture"}], "task_contract": {"request_class": "runtime_inspection"}}
        invoked = []
        result = tools.execute(
            "inspect", {"target": "runtime_entity", "id": "entity-a", "proof_id": proof_id}, runtime_route,
            invoke=lambda name, arguments: invoked.append((name, arguments)) or {
                "ok": True, "observations": [{"kind": "runtime_entity", "result": {
                    "action_result": {"ok": True, "action": "runtime.proof.get", "proof": {"proof": {"id": proof_id}}},
                }}],
            },
        )
        self.assertEqual(result["runtime"]["action"], "runtime.proof.get")
        self.assertEqual(invoked[0][1]["runtime_action"]["arguments"]["proof_id"], proof_id)

    def test_runtime_grounded_answer_receives_snapshot_and_preserves_unknown(self) -> None:
        runtime_route = {"route_id": "route.a", "caps": ["runtime.inspect"], "entities": [{"id": "entity-a", "kind": "fixture"}], "task_contract": {"request_class": "runtime_inspection"}}
        state = trajectory.new("run", "turn", "is entity-a live", "route.a")
        calls = []
        def complete(messages, _index):
            calls.append(messages)
            if len(calls) == 1:
                return {"reply": '{"tool":"inspect","arguments":{"target":"runtime_entity","id":"entity-a"}}'}
            runtime = context.payload("is entity-a live", runtime_route, state)["completed"][-1]["result"]["runtime"]["result"]
            self.assertEqual(runtime["s"], "unknown")
            self.assertEqual(runtime["u"][0]["code"], "live_state_not_collected")
            return {"reply": "Historical runtime evidence exists, but current live state was not collected."}
        outcome = loop.run(
            "is entity-a live", runtime_route, state, complete=complete,
            execute=lambda name, arguments: tools.execute(name, arguments, runtime_route, invoke=lambda *_: {
                "ok": True, "observations": [{"kind": "runtime_entity", "result": {"action_result": {
                    "ok": True, "snapshot": {"e": {"id": "entity-a"}, "s": "unknown", "c": {"runs": 1}, "p": [], "u": [{"code": "live_state_not_collected"}]},
                }}}],
            }),
        )
        self.assertIn("current live state was not collected", outcome.answer)
        self.assertEqual(outcome.calls, 2)

    def test_source_capability_unavailable_does_not_authorize_completion(self) -> None:
        state = trajectory.new("run", "turn", "inspect source", "fixture.ui")
        source_route = {"route_id": "fixture.ui", "task_contract": {"request_class": "source_investigation"}}
        responses = iter([
            {"reply": '{"tool":"read","arguments":{"path":"missing"}}'},
            {"reply": "Unsupported source answer."},
            {"reply": "Still unsupported."},
        ])
        outcome = loop.run(
            "inspect source", source_route, state, complete=lambda *_: next(responses),
            execute=lambda *_: {"ok": False, "code": "capability_unavailable", "summary": "Source read unavailable."},
        )
        self.assertEqual(outcome.trajectory["answer_satisfaction"]["status"], "unsatisfactory")
        self.assertEqual(outcome.trajectory["answer_satisfaction"]["code"], "evidence_incomplete")

    def test_all_loop5_strategies_preserve_declared_direct_and_grounded_modes(self) -> None:
        matrix = json.loads((Path(__file__).resolve().parents[3] / "labs/wasm-agent/loop5-v5-strategies.json").read_text())
        direct_fields = {"request_class":"conversation","declared_classes":["conversation"],"completion_mode":"direct","proof_policy":"none","required_capabilities":[],"evidence_requirements":[],"execution_profile":"answer_only","authority_source":"declared_task_contract","context_profile":"direct"}
        grounded_fields = {"request_class":"source_investigation","declared_classes":["source_investigation"],"completion_mode":"tool_loop","proof_policy":"grounded","required_capabilities":["inspect"],"evidence_requirements":["grounded"],"execution_profile":"grounded","authority_source":"declared_task_contract","context_profile":"natural_tool_loop"}
        for item in matrix["variants"]:
            self.assertTrue(task_policy.direct_completion({"task_contract":{**direct_fields,"strategy":item["strategy"]}}), item["strategy"])
            self.assertFalse(task_policy.direct_completion({"task_contract":{**grounded_fields,"strategy":item["strategy"]}}), item["strategy"])

    def test_context_exposes_bounded_declared_runtime_identity(self) -> None:
        state = trajectory.new("run", "turn", "which model", "fixture.ui")
        messages = context.messages("which model", {"route_id":"fixture.ui","runtime_identity":{"model":"glm-5.2"}}, state)
        payload = context.payload("which model", {"route_id":"fixture.ui","runtime_identity":{"model":"glm-5.2"}}, state)
        self.assertEqual(payload["runtime_identity"], {"model":"glm-5.2"})
        self.assertIn("runtime_identity", messages[0]["content"])

    def test_protocol_is_explicit_and_resume_immutable(self) -> None:
        self.assertEqual(run_protocol.select({"protocol": "v5"}), "v5")
        self.assertEqual(run_protocol.select({"protocol": "v6"}), "v6")
        self.assertEqual(run_protocol.request_fields({"protocol": "v5"}), {"protocol": "v5", "investigation_mode": ""})
        self.assertEqual(
            run_protocol.request_fields({"protocol": "v5", "route_id": " route.a "})["route_id"],
            "route.a",
        )
        self.assertEqual(len(run_protocol.request_fields({"route_id": "r" * 200})["route_id"]), 160)
        with self.assertRaises(run_protocol.ProtocolError):
            run_protocol.require_resume("v5", {"protocol": "v3"})

    def test_natural_search_then_read_then_final(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "ARTIFACTS.md").write_text("\n".join("generic widget" for _ in range(40)))
            target = root / "modules" / "meta-analysis-widget.js"; target.parent.mkdir(); target.write_text("export function renderMetaAnalysis() {\n  return false;\n}\n")
            state = trajectory.new("run", "turn", "criticize meta-analysis widget", "fixture.ui")
            responses = iter([
                {"reply": '{"tool":"search","arguments":{"query":"meta-analysis widget","limit":5}}'},
                {"reply": '{"tool":"read","arguments":{"path":"modules/meta-analysis-widget.js","start_line":1,"end_line":20}}'},
                {"reply": '{"final":"The render path always returns false, so it cannot present a successful result."}'},
            ])
            executed = []
            def execute(name: str, arguments: dict[str, object]) -> dict[str, object]:
                executed.append(name)
                return tools.execute(name, arguments, route(root), invoke=lambda *_: {})
            outcome = loop.run("criticize meta-analysis widget", route(root), state, complete=lambda *_: next(responses), execute=execute)
            self.assertEqual(executed, ["search", "read"])
            self.assertIn("always returns false", outcome.answer)
            self.assertEqual(outcome.trajectory["status"], "completed")
            read = next(step["result"] for step in outcome.trajectory["steps"] if step.get("tool") == "read")
            self.assertIn("renderMetaAnalysis", read["content"])
            search_step = next(step for step in outcome.trajectory["steps"] if step.get("tool") == "search")
            self.assertLessEqual(len(search_step["result"]["matches"]), 8)
            self.assertTrue(all(len(item.get("excerpt", "")) <= 320 for item in search_step["result"]["matches"]))
            self.assertEqual(search_step["result"]["focus"]["owner_file"], "modules/meta-analysis-widget.js")
            self.assertIn("renderMetaAnalysis", {item["name"] for item in search_step["result"]["focus"]["key_symbols"]})

    def test_timeout_resume_preserves_completed_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "widget.js").write_text("export const widget = true;\n")
            state = trajectory.new("run", "turn", "review widget", "fixture.ui")
            responses = iter([
                {"reply": '{"tool":"search","arguments":{"query":"widget"}}'},
                {"reply": '{"tool":"read","arguments":{"path":"widget.js"}}'},
            ])
            executed = []
            def complete(*_):
                try: return next(responses)
                except StopIteration: raise TimeoutError("provider timed out")
            def execute(name, arguments):
                executed.append(name); return tools.execute(name, arguments, route(root), invoke=lambda *_: {})
            with self.assertRaises(V5Error) as raised:
                loop.run("review widget", route(root), state, complete=complete, execute=execute)
            self.assertEqual(executed, ["search", "read"])
            checkpoint = raised.exception.checkpoint
            outcome = loop.run("review widget", route(root), checkpoint, complete=lambda *_: {"reply": '{"final":"The source was preserved across timeout."}'}, execute=execute)
            self.assertEqual(executed, ["search", "read"])
            self.assertEqual(outcome.trajectory["status"], "completed")

    def test_duplicate_action_synthesizes_only_after_primary_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "x.js").write_text("x\n")
            state = trajectory.new("run", "turn", "find x", "fixture.ui")
            responses = iter([
                {"reply": '{"tool":"search","arguments":{"query":"x"}}'},
                {"reply": '{"tool":"read","arguments":{"path":"x.js"}}'},
                {"reply": '{"tool":"search","arguments":{"query":"x"}}'},
                {"reply": "The source contains x."},
            ])
            executed = []
            def execute(name, args):
                executed.append(name)
                return tools.execute(name, args, route(root), invoke=lambda *_: {})
            outcome = loop.run("find x", route(root), state, complete=lambda *_: next(responses), execute=execute)
            self.assertEqual(executed, ["search", "read"])
            self.assertEqual(outcome.answer, "The source contains x.")
            self.assertEqual(outcome.trajectory["status"], "completed")
            self.assertEqual(outcome.trajectory["steps"][-1]["status"], "duplicate")
            self.assertEqual(outcome.trajectory["completion_assessment"]["status"], "sufficient")

    def test_advisory_duplicate_search_terminates_after_two_repairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "x.js").write_text("x\n")
            state = trajectory.new("run", "turn", "find x", "fixture.ui")
            responses = iter([
                {"reply": '{"tool":"search","arguments":{"query":"x"}}'},
                {"reply": '{"tool":"search","arguments":{"query":"x"}}'},
                {"reply": '{"tool":"search","arguments":{"query":"x"}}'},
                {"reply": '{"tool":"read","arguments":{"path":"x.js"}}'},
                {"reply": "The source contains x."},
            ])
            prompts = []
            def complete(messages, *_):
                prompts.append(messages[-1]["content"])
                return next(responses)
            with self.assertRaises(V5Error) as raised:
                loop.run("find x", route(root), state, complete=complete, execute=lambda name, args: tools.execute(name, args, route(root), invoke=lambda *_: {}))
            self.assertEqual(raised.exception.code, "no_semantic_progress")
            self.assertEqual(state["loop_counters"]["provider_attempts"], 3)
            self.assertNotEqual(prompts[1], prompts[2])
            self.assertIn("X\trev=1", prompts[2])
            self.assertIn("rejected_action_id=", prompts[2])
            self.assertIn("rejected_tool=search", prompts[2])

    def test_completion_assessment_blocks_without_primary_evidence(self) -> None:
        state = trajectory.new("run", "turn", "answer", "fixture.ui")
        self.assertEqual(completion.assess(state)["status"], "blocked")

    def test_network_timeout_without_evidence_preserves_tool_mode(self) -> None:
        class NetworkTimeout(RuntimeError):
            code = "network-timeout"

        state = trajectory.new("run", "turn", "explain x", "fixture.ui")
        calls = []
        def complete(messages, index):
            calls.append(messages)
            if len(calls) == 1:
                raise NetworkTimeout("Provider request timed out.")
            if len(calls) == 2:
                return {"reply": '{"tool":"read","arguments":{"path":"x.py"}}'}
            return {"reply": "Recovered from accumulated evidence."}
        retry_route = {"route_id": "fixture.ui", "caps": ["repo.read"], "task_contract": {"request_class": "source_investigation"}}
        outcome = loop.run("explain x", retry_route, state, complete=complete, execute=lambda *_: {
            "ok": True, "path": "x.py", "start_line": 1, "end_line": 1,
            "line_count": 1, "truncated": False, "content": "1: x = 1",
        })
        self.assertEqual(outcome.answer, "Recovered from accumulated evidence.")
        self.assertEqual(len(calls), 3)
        self.assertIn("T\tsearch,read", calls[1][1]["content"])

    def test_network_timeout_with_primary_evidence_retries_completion_only(self) -> None:
        class NetworkTimeout(RuntimeError):
            code = "network-timeout"

        state = trajectory.new("run", "turn", "explain x", "fixture.ui")
        trajectory.append(state, {"kind": "tool", "tool": "read", "status": "completed", "result": {"ok": True, "path": "x.js", "content": "1: x"}})
        calls = []
        def complete(messages, index):
            calls.append(messages)
            if len(calls) == 1: raise NetworkTimeout("Provider request timed out.")
            return {"reply": "Recovered from primary evidence."}
        outcome = loop.run("explain x", {"route_id": "fixture.ui"}, state, complete=complete, execute=lambda *_: {})
        self.assertEqual(outcome.answer, "Recovered from primary evidence.")
        self.assertIn("\nT\t\n", calls[-1][1]["content"])

    def test_network_timeout_retries_only_once(self) -> None:
        class NetworkTimeout(RuntimeError):
            code = "network-timeout"

        state = trajectory.new("run", "turn", "explain x", "fixture.ui")
        with self.assertRaises(V5Error) as raised:
            loop.run("explain x", {"route_id": "fixture.ui"}, state, complete=lambda *_: (_ for _ in ()).throw(NetworkTimeout("Provider request timed out.")), execute=lambda *_: {})
        self.assertEqual(raised.exception.code, "network-timeout")

    def test_upstream_unavailable_uses_durable_retry_budget(self) -> None:
        class Unavailable(RuntimeError):
            code = "upstream_unavailable"

        state = trajectory.new("run", "turn", "hello", "fixture.ui")
        attempts = 0
        def complete(*_):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise Unavailable("temporary upstream failure")
            return {"reply": "Recovered."}
        outcome = loop.run("hello", {"route_id": "fixture.ui"}, state, complete=complete, execute=lambda *_: {})
        self.assertEqual(outcome.answer, "Recovered.")
        self.assertEqual((outcome.calls, outcome.attempts), (1, 2))
        self.assertEqual(outcome.trajectory["provider_reliability"], {
            "transient_retries": 1, "retry_limit": 3,
            "consecutive_retries": 0, "consecutive_limit": 1,
            "last_code": "upstream_unavailable", "retry_active": False,
        })

    def test_separate_transient_incidents_each_get_one_bounded_retry(self) -> None:
        class Timeout(RuntimeError):
            code = "network-timeout"

        state = trajectory.new("run", "turn", "hello", "fixture.ui")
        responses = iter([Timeout("first"), {"tool_calls": [{"name": "search", "arguments": {"query": "x"}}]}, Timeout("second"), {"reply": "Recovered twice."}])

        def complete(*_):
            value = next(responses)
            if isinstance(value, Exception):
                raise value
            return value

        outcome = loop.run("hello", {"route_id": "fixture.ui"}, state, complete=complete, execute=lambda *_: {"ok": True, "matches": []})
        self.assertEqual(outcome.answer, "Recovered twice.")
        self.assertEqual(outcome.trajectory["provider_reliability"]["transient_retries"], 2)

    def test_restored_trajectory_does_not_reset_retry_budget(self) -> None:
        class Timeout(RuntimeError):
            code = "network-timeout"

        original = trajectory.new("run", "turn", "hello", "fixture.ui")
        original["provider_reliability"] = {
            "transient_retries": 1, "retry_limit": 3, "last_code": "upstream_unavailable",
        }
        restored = trajectory.restore(original, run_id="run", turn_id="turn", objective="hello", route_id="fixture.ui")
        with self.assertRaises(V5Error) as raised:
            loop.run("hello", {"route_id": "fixture.ui"}, restored, complete=lambda *_: (_ for _ in ()).throw(Timeout("timed out")), execute=lambda *_: {})
        self.assertEqual(raised.exception.code, "network-timeout")
        self.assertEqual(raised.exception.checkpoint["provider_reliability"]["transient_retries"], 1)

    def test_transient_retry_compacts_evidence_and_checkpoint_stores_content_once(self) -> None:
        class Timeout(RuntimeError):
            code = "network-timeout"

        state = trajectory.new("run", "turn", "review", "fixture.ui")
        large_content = "HEAD-EVIDENCE\n" + ("middle evidence\n" * 400) + "TAIL-EVIDENCE"
        trajectory.append(state, {"kind": "tool", "tool": "read", "status": "completed", "summary": "Read owner.", "result": {
            "ok": True, "path": "owner.js", "start_line": 1, "end_line": 402, "content": large_content,
        }})
        state["completed_actions"]["act_fixture"] = {"ok": True, "path": "owner.js", "start_line": 1, "end_line": 402}
        prompts = []
        def complete(messages, _index):
            prompts.append(messages[1]["content"])
            if len(prompts) == 1:
                raise Timeout("timed out")
            return {"reply": "Recovered from compact evidence."}
        outcome = loop.run("review", {"route_id": "fixture.ui"}, state, complete=complete, execute=lambda *_: {})
        self.assertEqual(outcome.answer, "Recovered from compact evidence.")
        self.assertLess(len(prompts[1]), len(prompts[0]) // 2)
        self.assertIn("HEAD-EVIDENCE", prompts[1])
        self.assertIn("TAIL-EVIDENCE", prompts[1])
        self.assertNotIn("content", outcome.trajectory["completed_actions"]["act_fixture"])

    def test_completion_only_rejects_ignored_tool_instruction(self) -> None:
        state = trajectory.new("run", "turn", "find x", "fixture.ui")
        state["pending"] = "frontier_completion"
        action = trajectory.action_id("search", {"query": "x"})
        state["completed_actions"][action] = {"ok": True, "summary": "Found x."}
        with self.assertRaises(V5Error) as raised:
            loop.run("find x", {"route_id": "fixture.ui"}, state, complete=lambda *_: {"reply": '{"tool":"search","arguments":{"query":"x"}}'}, execute=lambda *_: {})
        self.assertEqual(raised.exception.code, "no_semantic_progress")

    def test_direct_completion_rejects_novel_raw_tool_without_execution(self) -> None:
        state = trajectory.new("run", "turn", "hello", "fixture.ui")
        executed = []
        route_value = {"route_id": "fixture.ui", "task_contract": {"request_class": "conversation"}}
        with self.assertRaises(V5Error) as raised:
            loop.run(
                "hello", route_value, state,
                complete=lambda *_: {"reply": '{"tool":"search","arguments":{"query":"secret"}}'},
                execute=lambda *_: executed.append(True) or {"ok": True},
            )
        self.assertEqual(raised.exception.code, "no_semantic_progress")
        self.assertEqual(executed, [])

    def test_verification_requires_passing_check_and_scoped_proof(self) -> None:
        state = trajectory.new("verify", "turn", "verify", "fixture.ui")
        route_value = {
            "route_id": "fixture.ui",
            "task_contract": {"request_class": "verification"},
        }
        responses = iter([
            {"reply": "Verified."},
            {"reply": '{"tool":"test","arguments":{"check_id":"focused"}}'},
            {"reply": '{"tool":"prove","arguments":{}}'},
            {"reply": "Verified with a passing check and scoped proof."},
        ])

        def execute(name, _arguments):
            if name == "test":
                return {
                    "ok": True, "local_action": "test.run_focused",
                    "result": {"ok": True, "code": "ok", "returncode": 0, "check_id": "focused"},
                }
            return {"ok": True, "primitive": "kernel.prove"}

        outcome = loop.run(
            "verify", route_value, state,
            complete=lambda *_: next(responses), execute=execute,
        )
        self.assertEqual(outcome.calls, 4)
        self.assertEqual([item.get("local_action") or item.get("primitive") for item in outcome.tools], [
            "test.run_focused", "kernel.prove",
        ])

    def test_verified_workflow_enters_completion_only_mode(self) -> None:
        state = trajectory.new("run", "turn", "verify", "fixture.ui")
        state["operation_ledger"]["check"] = {"rev": 0, "ok": True}
        state["operation_ledger"]["proof"] = {"rev": 0, "ok": True}
        route_value = {
            "route_id": "fixture.ui",
            "task_contract": {"request_class": "verification"},
        }

        self.assertEqual(completion.assess(state, route_value)["status"], "sufficient")
        self.assertTrue(context.completion_only(state, route_value))
        projected = context.payload("verify", route_value, state)["operations"]
        self.assertEqual(projected, {
            "rev": 0,
            "check_ok": True,
            "check_id": "",
            "diff_ok": False,
            "diff_files": [],
            "proof_ok": True,
            "gaps": [],
        })

    def test_verification_assessment_names_the_missing_proof_tool(self) -> None:
        state = trajectory.new("run", "turn", "verify", "fixture.ui")
        state["operation_ledger"]["check"] = {"rev": 0, "ok": True}
        route_value = {"task_contract": {"request_class": "verification"}}

        assessment = completion.assess(state, route_value)

        self.assertEqual(assessment["required_gaps"], ["scoped proof"])
        self.assertEqual(assessment["next_actions"], [{"tool": "prove", "arguments": {}}])

    def test_failed_diff_is_not_reexecuted_at_the_same_revision(self) -> None:
        state = trajectory.new("run", "turn", "verify", "fixture.ui")
        state["operation_ledger"]["check"] = {"rev": 0, "ok": True}
        diff_action = trajectory.action_id("diff", {}, "fixture.ui", 0)
        state["completed_actions"][diff_action] = {
            "tool": "diff",
            "observation": {"ok": True, "result": {"ok": False, "code": "diff_receipt_truncated"}},
        }
        responses = iter([
            {"reply": '{"tool":"diff","arguments":{}}'},
            {"reply": '{"tool":"prove","arguments":{}}'},
            {"reply": "Verification completed from current receipts."},
        ])
        executed = []

        outcome = loop.run(
            "verify", {"route_id": "fixture.ui", "task_contract": {"request_class": "verification"}},
            state, complete=lambda *_: next(responses),
            execute=lambda name, _args: executed.append(name) or {"ok": True, "primitive": "kernel.prove"},
        )

        self.assertEqual(executed, ["prove"])
        self.assertEqual(outcome.answer, "Verification completed from current receipts.")

    def test_request_tightened_provider_call_budget_sets_provider_timeout(self) -> None:
        route_value = {
            "budget": {"wall_ms_max": 90_000},
            "task_contract": {"budget": {"provider_call_ms_max": 5_000}},
        }
        state = trajectory.new("run", "turn", "hello", "fixture.ui")
        state["loop_counters"]["elapsed_ms"] = 1_000
        self.assertEqual(controller_v5._provider_timeout_sec(route_value, state), 5.0)
        self.assertEqual(controller_v5._provider_timeout_sec({"budget": {"wall_ms_max": 500}}, trajectory.new("r", "t", "x", "fixture.ui")), 0.5)
        self.assertEqual(controller_v5._provider_timeout_sec({"budget": {"wall_ms_max": 0}}, trajectory.new("r", "t", "x", "fixture.ui")), 0.001)

    def test_zero_task_lease_never_dispatches_provider(self) -> None:
        state = trajectory.new("wall", "turn", "hello", "fixture.ui")
        called = []
        with self.assertRaises(V5Error) as raised:
            loop.run(
                "hello", {"route_id": "fixture.ui", "budget": {"task_lease_ms_max": 0}}, state,
                complete=lambda *_: called.append(True) or {"reply": "unexpected"},
                execute=lambda *_: {}, monotonic=lambda: 0.0,
            )
        self.assertEqual(raised.exception.code, "task_lease_exhausted")

    def test_expired_task_lease_allows_only_pending_final_synthesis(self) -> None:
        route_value = {
            "route_id": "fixture.ui",
            "budget": {"task_lease_ms_max": 1_000},
            "task_contract": {"request_class": "source_investigation"},
        }
        state = trajectory.new("lease", "turn", "inspect", "fixture.ui")
        state["loop_counters"]["elapsed_ms"] = 2_000
        state["pending"] = "frontier_completion"
        trajectory.append(state, {
            "kind": "tool", "tool": "read", "status": "completed",
            "result": {"ok": True, "path": "x.py", "start_line": 1, "end_line": 1,
                       "line_count": 1, "truncated": False, "content": "1: x"},
        })
        executed = []
        outcome = loop.run(
            "inspect", route_value, state,
            complete=lambda *_: {"reply": "Inspected and verified."},
            execute=lambda *_: executed.append(True) or {"ok": True},
            monotonic=lambda: 1.0,
        )
        self.assertEqual(outcome.answer, "Inspected and verified.")
        self.assertEqual(executed, [])

    def test_compact_budget_exposes_separate_call_and_task_clocks(self) -> None:
        route_value = {
            "route_id": "fixture.ui",
            "budget": {"provider_call_ms_max": 5_000, "task_lease_ms_max": 20_000},
        }
        state = trajectory.new("budget", "turn", "inspect", "fixture.ui")
        state["loop_counters"]["elapsed_ms"] = 7_000
        projection = context.payload("inspect", route_value, state)["budget"]
        self.assertEqual(projection["provider_call_ms"], 5_000)
        self.assertEqual(projection["task_lease_ms"], 20_000)
        self.assertEqual(projection["task_remaining_ms"], 13_000)

    def test_missing_usage_is_never_reported_as_exact_zero_calls(self) -> None:
        self.assertEqual(controller_v5._token_usage_total([], attempts=1), {
            "exact": False,
            "total_tokens": 0,
            "calls": 1,
            "metered_calls": 0,
        })
        self.assertFalse(controller_v5._token_usage_total(
            [{"total_tokens": 5}], attempts=2,
        )["exact"])

    def test_terminal_usage_projection_aggregates_calls_and_preserves_exact_shape(self) -> None:
        raw = [
            {"input_tokens": 561, "output_tokens": 85, "total_tokens": 646, "model": "glm-5.2", "usage_scope": "llm_api_call", "usage_accuracy": "provider_exact", "billable": True, "transport": "codex_app_server", "provider_thread_id": "thread-1"},
            {"input_tokens": 1400, "output_tokens": 200, "total_tokens": 1600, "model": "glm-5.2", "usage_scope": "llm_api_call", "usage_accuracy": "provider_exact", "billable": True},
            {"input_tokens": 2384, "output_tokens": 112, "total_tokens": 2496, "model": "glm-5.2", "usage_scope": "llm_api_call", "usage_accuracy": "provider_exact", "billable": True},
            {"input_tokens": 3834, "output_tokens": 49, "total_tokens": 3883, "model": "glm-5.2", "usage_scope": "llm_api_call", "usage_accuracy": "provider_exact", "billable": True},
            {"input_tokens": 3519, "output_tokens": 1702, "total_tokens": 5221, "model": "glm-5.2", "usage_scope": "llm_api_call", "usage_accuracy": "provider_exact", "billable": True},
        ]
        projected = token_ledger.with_canonical_usage({
            "diagnostics": {
                "token_usage": raw,
                "token_usage_total": {"exact": True, "total_tokens": 13846, "calls": 5, "metered_calls": 5},
                "budget": {"provider": {"used": 13846}, "calls": {"used": 5}},
            },
        }, {"usage": raw[0], "components": {"run": raw[0]}})

        self.assertEqual(projected["token_usage"]["input_tokens"], 11698)
        self.assertEqual(projected["token_usage"]["output_tokens"], 2148)
        self.assertEqual(projected["token_usage"]["total_tokens"], 13846)
        self.assertEqual(projected["diagnostics"]["token_usage_components"]["provider_1"]["transport"], "codex_app_server")
        self.assertEqual(projected["diagnostics"]["token_usage_components"]["provider_1"]["provider_thread_id"], "thread-1")
        total = projected["diagnostics"]["token_usage_total"]
        self.assertEqual({key: total[key] for key in ("exact", "total_tokens", "calls", "metered_calls")}, {
            "exact": True, "total_tokens": 13846, "calls": 5, "metered_calls": 5,
        })
        components = projected["diagnostics"]["token_usage_components"]
        self.assertEqual(len(components), 5)
        self.assertEqual(sum(item["total_tokens"] for item in components.values()), 13846)

        missing = token_ledger.with_canonical_usage({
            "diagnostics": {
                "token_usage": raw[:1],
                "token_usage_total": {"exact": False, "total_tokens": 646, "calls": 2, "metered_calls": 1},
            },
        })
        self.assertFalse(missing["diagnostics"]["token_usage_total"]["exact"])
        self.assertEqual(missing["diagnostics"]["token_usage_total"]["calls"], 2)

    def test_malformed_output_repairs_once_then_stops(self) -> None:
        state = trajectory.new("run", "turn", "hello", "fixture.ui")
        with self.assertRaises(V5Error) as raised:
            loop.run("hello", {"route_id": "fixture.ui"}, state, complete=lambda *_: {"reply": "{not json"}, execute=lambda *_: {})
        self.assertEqual(raised.exception.code, "model_output_invalid")

    def test_plain_provider_text_is_a_natural_final_answer(self) -> None:
        state = trajectory.new("run", "turn", "hello", "fixture.ui")
        outcome = loop.run("hello", {"route_id": "fixture.ui"}, state, complete=lambda *_: {"reply": "Hello. How can I help?"}, execute=lambda *_: {})
        self.assertEqual(outcome.answer, "Hello. How can I help?")

    def test_session_answer_satisfaction_fixtures(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures/master_frontier_v5_answer_satisfaction.json"
        fixtures = json.loads(fixture_path.read_text())["fixtures"]
        for repeat in range(25):
            for fixture in fixtures:
                with self.subTest(repeat=repeat, fixture=fixture["id"]):
                    result = answer_satisfaction.assess(fixture["candidate"])
                    self.assertEqual(result["status"], fixture["expectedStatus"])
                    self.assertEqual(result["code"], fixture["expectedCode"])

    def test_tool_like_final_is_repaired_into_a_useful_answer(self) -> None:
        state = trajectory.new("run", "turn", "review widget", "fixture.ui")
        replies = iter([
            {"reply": "@read path='widget.js'"},
            {"reply": "The widget keeps transcript parsing small and event-driven; runtime behavior remains unverified."},
        ])
        outcome = loop.run(
            "review widget", {"route_id": "fixture.ui"}, state,
            complete=lambda *_: next(replies), execute=lambda *_: {},
        )
        self.assertIn("event-driven", outcome.answer)
        self.assertEqual(outcome.trajectory["loop_counters"]["answer_repairs"], 1)
        self.assertEqual(outcome.trajectory["answer_satisfaction"]["status"], "satisfactory")

    def test_repeated_unsatisfactory_final_returns_honest_answer_not_failure(self) -> None:
        state = trajectory.new("run", "turn", "review widget", "fixture.ui")
        outcome = loop.run(
            "review widget", {"route_id": "fixture.ui"}, state,
            complete=lambda *_: {"reply": "@read path='widget.js'"}, execute=lambda *_: {},
        )
        self.assertIn("could not synthesize a satisfactory answer", outcome.answer)
        self.assertTrue(outcome.trajectory["answer_satisfaction"]["fallback"])
        self.assertEqual(outcome.trajectory["loop_counters"]["answer_repairs"], 3)

    def test_flattened_provider_tool_arguments_are_normalized(self) -> None:
        self.assertEqual(loop.normalize({"reply": '{"tool":"search","query":"widget","limit":5}'}), {
            "kind": "tool", "tool": "search", "arguments": {"query": "widget", "limit": 5},
        })

    def test_native_provider_tool_call_is_normalized(self) -> None:
        self.assertEqual(loop.normalize({"tool_calls": [{"id": "c1", "name": "read", "arguments": {"path": "x.js"}}]}), {
            "kind": "tool", "tool": "read", "arguments": {"path": "x.js"},
        })

    def test_common_structured_final_answer_is_normalized(self) -> None:
        self.assertEqual(loop.normalize({"reply": '{"answer":"Useful critique"}'}), {"kind": "final", "answer": "Useful critique"})

    def test_provider_transport_forwards_and_extracts_native_tools(self) -> None:
        fields = provider_tools.request_fields({"tools": [{"type": "function", "function": {"name": "search", "description": "Find source", "parameters": {"type": "object"}}}]})
        self.assertEqual(fields["tool_choice"], "auto")
        self.assertEqual(fields["tools"][0]["function"]["name"], "search")
        calls = provider_tools.response_calls({"choices": [{"message": {"tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search", "arguments": '{"query":"widget"}'}}]}}]})
        self.assertEqual(calls, [{"id": "c1", "name": "search", "arguments": {"query": "widget"}}])
        responses_fields = provider_tools.responses_request_fields({
            "tools": [{"type": "function", "function": {"name": "read", "description": "Read source", "parameters": {"type": "object"}}}],
            "tool_choice": "required",
        })
        self.assertEqual(responses_fields["tool_choice"], "required")
        self.assertFalse(responses_fields["parallel_tool_calls"])
        self.assertEqual(responses_fields["tools"][0]["name"], "read")
        responses_calls = provider_tools.responses_calls({"output": [{
            "type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "read", "arguments": '{"path":"x.js"}',
        }]})
        self.assertEqual(responses_calls, [{"id": "call_1", "name": "read", "arguments": {"path": "x.js"}}])
        accumulator = provider_tools.ResponsesCallAccumulator()
        accumulator.ingest({"type": "response.output_item.added", "output_index": 0, "item": {
            "type": "function_call", "id": "fc_2", "call_id": "call_2", "name": "search", "arguments": "",
        }})
        accumulator.ingest({"type": "response.function_call_arguments.delta", "output_index": 0, "item_id": "fc_2", "delta": '{"query":'})
        accumulator.ingest({"type": "response.function_call_arguments.done", "output_index": 0, "item_id": "fc_2", "arguments": '{"query":"modules"}'})
        self.assertEqual(accumulator.calls({}), [{"id": "call_2", "name": "search", "arguments": {"query": "modules"}}])

    def test_absolute_native_read_path_normalizes_to_route_relative_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "modules" / "x.js"; source.parent.mkdir(); source.write_text("x\n")
            result = tools.execute("read", {"path": str(source)}, route(root), invoke=lambda *_: {})
            self.assertEqual(result["path"], "modules/x.js")

    def test_no_objective_token_ceiling_exists(self) -> None:
        state = trajectory.new("run", "turn", "hello", "fixture.ui")
        outcome = loop.run("hello", {"route_id": "fixture.ui"}, state, complete=lambda *_: {"reply": '{"final":"hello"}', "usage": {"total_tokens": 999999}}, execute=lambda *_: {})
        self.assertEqual(outcome.answer, "hello")

    def test_complete_owner_coverage_requires_answer_signal(self) -> None:
        state = trajectory.new("run", "turn", "review", "fixture.ui")
        state["steps"] = [
            {"tool": "search", "status": "completed", "result": {
                "ok": True, "focus": {"owner_file": "x.js", "line_count": 100},
            }},
            {"tool": "read", "status": "completed", "result": {
                "ok": True, "path": "x.js", "start_line": 1, "end_line": 40,
                "line_count": 100, "truncated": False, "content": "part one",
            }},
            {"tool": "read", "status": "completed", "result": {
                "ok": True, "path": "x.js", "start_line": 41, "end_line": 100,
                "line_count": 100, "truncated": False, "content": "part two",
            }},
        ]
        status = context._evidence_status(state)
        self.assertTrue(status["owner_fully_read"])
        self.assertEqual(status["missing_ranges"], [])
        self.assertIn("Answer now", status["instruction"])
        payload = context.payload("review", {"route_id": "fixture.ui"}, state)
        self.assertEqual(payload["tools"], [])
        self.assertIn("plain text", context.messages("review", {"route_id": "fixture.ui"}, state)[0]["content"])


if __name__ == "__main__": unittest.main()
