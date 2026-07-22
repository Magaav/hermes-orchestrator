#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))
from master_frontier.v5 import continuity, operation_ledger, trajectory  # noqa: E402


def edit(path: str = "x.py", *, dry_run: bool = False) -> dict:
    return {"ok": True, "local_action": "patch.apply_scoped", "result": {
        "changed_files": [path], "applied": not dry_run, "dry_run": dry_run, "postimage_sha256": {path: "abc"},
    }}


def check(ok: bool = True) -> dict:
    return {"ok": True, "local_action": "test.run_focused", "result": {
        "ok": ok, "check_id": "focused", "returncode": 0 if ok else 1, "code": "ok" if ok else "test_failed",
    }}


def diff(*paths: str) -> dict:
    values = paths or ("x.py",)
    return {"ok": True, "local_action": "git.diff_summary", "result": {
        "schema": "git_diff_summary", "ok": True, "code": "ok", "returncode": 0,
        "changed_files": [{"path": path} for path in values], "stat": {"complete": True}, "truncation": {},
    }}


def prove() -> dict:
    return {"ok": True, "primitive": "kernel.prove", "schema": "kernel.prove"}


def large_edit(paths: list[str], batch: int) -> dict:
    return {"ok": True, "local_action": "patch.apply_scoped", "result": {
        "changed_files": paths, "applied": True, "dry_run": False,
        "postimage_sha256": {
            path: f"{batch * len(paths) + index + 1:064x}"
            for index, path in enumerate(paths)
        },
    }}


def long_paths(batch: int) -> list[str]:
    owner = "very-long-owned-module-" + "x" * 150
    return [
        f"packages/{owner}/generated/feature-{batch:02d}/component-{index:02d}-{'y' * 35}.py"
        for index in range(24)
    ]


def record(ledger: dict, tool: str, observed: dict, **kwargs) -> dict:
    if tool in {"test", "diff", "prove"} and ledger.get("mutations"):
        observed = {**observed, "worktree_sha256": operation_ledger.worktree_digest(ledger)}
    return operation_ledger.record(ledger, tool, observed, **kwargs)


class OperationLedgerTests(unittest.TestCase):
    def test_invalid_verification_receipt_requires_refresh(self) -> None:
        ledger = operation_ledger.new("fixture.ui")
        ledger = record(ledger, "edit", edit(), action_id="edit-1")
        ledger = record(ledger, "prove", prove())
        self.assertFalse(operation_ledger.verification_receipt_satisfied(ledger, "prove"))
        ledger = record(ledger, "test", check())
        ledger = record(ledger, "diff", diff())
        ledger = record(ledger, "prove", prove())
        self.assertTrue(operation_ledger.verification_receipt_satisfied(ledger, "prove"))

    def test_two_large_multi_file_edits_compact_and_restore_exact_proof(self) -> None:
        state = trajectory.new("run-1", "turn-1", "Apply allowed edits. " + "o" * 1800, "r")
        all_paths: list[str] = []
        expected_postimages: dict[str, str] = {}
        for batch in range(2):
            paths = long_paths(batch)
            all_paths.extend(paths)
            observed = large_edit(paths, batch)
            action_id = f"act-large-edit-{batch}"
            state["operation_ledger"] = record(
                state["operation_ledger"], "edit", observed, action_id=action_id,
            )
            state["completed_actions"][action_id] = {
                "tool": "edit", "observation": trajectory.receipt(observed),
            }
            trajectory.append(state, {
                "kind": "tool", "action_id": action_id, "tool": "edit",
                "status": "completed", "result": trajectory.compact_observation(observed),
            })
            expected_postimages.update(observed["result"]["postimage_sha256"])

        state["operation_ledger"] = record(state["operation_ledger"], "test", check())
        state["operation_ledger"] = record(state["operation_ledger"], "diff", diff(*all_paths))
        state["operation_ledger"] = record(state["operation_ledger"], "prove", prove())
        checkpoint = continuity.create(state, scope=continuity.binding(
            user_id="u", session_id="s", route_id="r",
            source_run_id="run-1", source_turn_id="turn-1",
        ))
        unsigned = {key: value for key, value in checkpoint.items() if key != "sha256"}
        self.assertLessEqual(
            len(json.dumps(unsigned, ensure_ascii=True, sort_keys=True, separators=(",", ":"))),
            continuity.MAX_CHECKPOINT_CHARS,
        )
        self.assertEqual(
            checkpoint["state"]["operation_ledger"]["encoding"],
            operation_ledger.CHECKPOINT_ENCODING,
        )

        restored = continuity.restore(
            checkpoint, expected_scope=continuity.binding(user_id="u", session_id="s", route_id="r"),
            previous_run_id="run-1", run_id="run-2", turn_id="turn-2",
            objective="continue", route_id="r",
        )
        self.assertEqual(restored["operation_ledger"]["postimages"], expected_postimages)
        self.assertEqual(restored["operation_ledger"]["changed_files"], sorted(all_paths))
        self.assertEqual(operation_ledger.missing(restored["operation_ledger"]), [])
        self.assertEqual(operation_ledger.worktree_digest(restored["operation_ledger"]), operation_ledger.worktree_digest(state["operation_ledger"]))
        self.assertTrue({"act-large-edit-0", "act-large-edit-1"}.issubset(restored["completed_actions"]))

    def test_large_checkpoint_restore_preserves_missing_proof_gaps(self) -> None:
        state = trajectory.new("run-1", "turn-1", "patch", "r")
        paths = long_paths(0) + long_paths(1)
        state["operation_ledger"] = record(
            state["operation_ledger"], "edit", large_edit(paths[:24], 0), action_id="act-0",
        )
        state["operation_ledger"] = record(
            state["operation_ledger"], "edit", large_edit(paths[24:], 1), action_id="act-1",
        )
        state["operation_ledger"] = record(state["operation_ledger"], "test", check())
        checkpoint = continuity.create(state, scope=continuity.binding(
            user_id="u", session_id="s", route_id="r", source_run_id="run-1",
        ))
        restored = continuity.restore(
            checkpoint, expected_scope=continuity.binding(user_id="u", session_id="s", route_id="r"),
            previous_run_id="run-1", run_id="run-2", turn_id="turn-2",
            objective="continue", route_id="r",
        )
        self.assertEqual(operation_ledger.missing(restored["operation_ledger"]), [
            "diff inspection at current revision", "scoped proof at current revision",
        ])

    def test_mutation_capacity_has_a_typed_pre_execution_bound(self) -> None:
        unrelated = [f"root-{index:03d}/{'z' * 240}/file.py" for index in range(80)]
        with self.assertRaises(operation_ledger.OperationLedgerError) as raised:
            operation_ledger.ensure_mutation_capacity(operation_ledger.new("r"), unrelated)
        self.assertEqual(raised.exception.code, "operation_checkpoint_budget_exceeded")

    def test_proof_before_edit_does_not_authorize_later_revision(self) -> None:
        ledger = record(operation_ledger.new("r"), "prove", prove())
        ledger = record(ledger, "edit", edit())
        self.assertEqual(ledger["revision"], 1)
        self.assertEqual(len(operation_ledger.missing(ledger)), 3)

    def test_check_and_diff_must_follow_latest_edit(self) -> None:
        ledger = record(operation_ledger.new("r"), "edit", edit())
        ledger = record(ledger, "test", check())
        ledger = record(ledger, "diff", diff())
        ledger = record(ledger, "prove", prove())
        self.assertEqual(operation_ledger.missing(ledger), [])
        ledger = record(ledger, "edit", edit("y.py"))
        self.assertEqual(len(operation_ledger.missing(ledger)), 3)
        self.assertEqual(ledger["changed_files"], ["x.py", "y.py"])

    def test_failed_check_and_dry_run_never_satisfy_mutation_proof(self) -> None:
        ledger = record(operation_ledger.new("r"), "edit", edit(dry_run=True))
        self.assertEqual(ledger["revision"], 0)
        ledger = record(ledger, "edit", edit())
        ledger = record(ledger, "test", check(False))
        ledger = record(ledger, "diff", diff())
        ledger = record(ledger, "prove", prove())
        self.assertIn("passing focused test at current revision", operation_ledger.missing(ledger))
        self.assertFalse(ledger["proof"]["ok"])

    def test_diff_must_cover_every_mutated_file(self) -> None:
        ledger = record(operation_ledger.new("r"), "edit", edit("x.py"))
        ledger = record(ledger, "edit", edit("y.py"))
        ledger = record(ledger, "test", check())
        ledger = record(ledger, "diff", diff("x.py"))
        ledger = record(ledger, "prove", prove())
        self.assertIn("diff inspection at current revision", operation_ledger.missing(ledger))
        self.assertFalse(ledger["proof"]["ok"])

    def test_restart_preserves_current_revision_and_remaining_gaps(self) -> None:
        state = trajectory.new("run-1", "turn-1", "patch", "r")
        state["operation_ledger"] = record(state["operation_ledger"], "edit", edit())
        state["operation_ledger"] = record(state["operation_ledger"], "test", check())
        checkpoint = continuity.create(state, scope=continuity.binding(
            user_id="u", session_id="s", route_id="r", source_run_id="run-1", source_turn_id="turn-1",
        ))
        restored = continuity.restore(
            checkpoint, expected_scope=continuity.binding(user_id="u", session_id="s", route_id="r"),
            previous_run_id="run-1", run_id="run-2", turn_id="turn-2", objective="continue", route_id="r",
        )
        self.assertEqual(restored["operation_ledger"]["revision"], 1)
        self.assertEqual(operation_ledger.missing(restored["operation_ledger"]), [
            "diff inspection at current revision", "scoped proof at current revision",
        ])

    def test_replayed_durable_edit_event_is_idempotent_by_action(self) -> None:
        ledger = record(operation_ledger.new("r"), "edit", edit(), action_id="act-edit")
        replayed = record(ledger, "edit", edit(), action_id="act-edit")
        self.assertEqual(replayed["revision"], 1)
        self.assertEqual(len(replayed["mutations"]), 1)

    def test_rename_diff_covers_source_and_destination(self) -> None:
        moved = {"ok": True, "local_action": "patch.apply_scoped", "result": {
            "applied": True, "dry_run": False, "changed_files": ["old.py", "new.py"],
            "postimage_sha256": {"old.py": "deleted", "new.py": "a" * 64},
        }}
        ledger = record(operation_ledger.new("r"), "edit", moved)
        ledger = record(ledger, "test", check())
        ledger = record(ledger, "diff", {"ok": True, "local_action": "git.diff_summary", "result": {
            "ok": True, "code": "ok", "returncode": 0,
            "changed_files": [{"path": "new.py", "old_path": "old.py"}],
            "stat": {"complete": True}, "truncation": {},
        }})
        ledger = record(ledger, "prove", prove())
        self.assertEqual(operation_ledger.missing(ledger), [])

    def test_truncated_or_failed_nested_diff_never_satisfies_proof(self) -> None:
        ledger = record(operation_ledger.new("r"), "edit", edit())
        ledger = record(ledger, "test", check())
        ledger = record(ledger, "diff", {
            "ok": True, "local_action": "git.diff_summary", "result": {
                "ok": False, "code": "diff_receipt_truncated", "returncode": 0,
                "changed_files": [{"path": "x.py"}], "stat": {"complete": False},
                "truncation": {"entries": True},
            },
        })
        self.assertIn("diff inspection at current revision", operation_ledger.missing(ledger))
        self.assertFalse(ledger["diff"]["ok"])

    def test_proof_rejects_a_route_state_digest_changed_after_test_and_diff(self) -> None:
        ledger = operation_ledger.record(operation_ledger.new("r"), "edit", edit(), action_id="act-edit")
        first = "1" * 64
        changed = "2" * 64
        ledger = operation_ledger.record(ledger, "test", {**check(), "worktree_sha256": first})
        ledger = operation_ledger.record(ledger, "diff", {**diff(), "worktree_sha256": first})
        ledger = operation_ledger.record(ledger, "prove", {**prove(), "worktree_sha256": changed})
        self.assertFalse(ledger["proof"]["ok"])
        self.assertEqual(operation_ledger.missing(ledger, worktree=changed), [
            "passing focused test at current revision",
            "diff inspection at current revision",
            "scoped proof at current revision",
        ])


if __name__ == "__main__":
    unittest.main()
