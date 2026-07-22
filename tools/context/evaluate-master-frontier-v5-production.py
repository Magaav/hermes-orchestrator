#!/usr/bin/env python3
"""Run the deterministic 50-case Master:frontier V5 production campaign."""

from __future__ import annotations

import importlib.util
import json
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = ROOT / "plugins/wasm-agent/tests"
REPORT_PATH = ROOT / "reports/context/latest/master-frontier-v5-production-campaign.json"

CAMPAIGN = {
    "lifecycle": ("master_frontier_v5.test.py", [
        "test_compact_budget_exposes_separate_call_and_task_clocks",
        "test_edit_preimage_is_bound_from_fresh_same_trajectory_read",
        "test_edit_requires_test_diff_and_proof_before_final",
        "test_expired_task_lease_allows_only_pending_final_synthesis",
        "test_interrupted_action_blocks_before_another_provider_call",
        "test_interrupted_read_is_released_for_safe_retry",
        "test_network_timeout_retries_only_once",
        "test_restart_checkpoint_is_bounded_scope_bound_and_content_free",
        "test_advisory_restart_counters_do_not_impose_a_hidden_decision_budget",
        "test_restored_trajectory_does_not_reset_retry_budget",
        "test_server_owned_resume_loader_scopes_checkpoint_and_rehydrates_evidence",
        "test_task_lineage_never_grants_edit_from_unverified_conversation",
        "test_task_lineage_requires_immediate_same_route_parent",
        "test_timeout_resume_preserves_completed_actions",
        "test_zero_task_lease_never_dispatches_provider",
    ]),
    "cost": ("master_frontier_v5_budget.test.py", [
        "test_advisory_target_accepts_five_calls_beyond_head_and_provider_targets",
        "test_api_diagnostics_count_unmetered_failed_attempts",
        "test_exact_hard_provider_budget_can_finish_but_overage_is_rejected",
        "test_hard_budget_reserves_declared_input_before_output",
        "test_host_request_bound_overrides_understated_route_reservation",
        "test_resume_at_budget_does_not_make_another_provider_call",
        "test_routed_budget_requires_measurable_provider_usage",
    ]),
    "causal_proof": ("master_frontier_v5_operation_ledger.test.py", [
        "test_check_and_diff_must_follow_latest_edit",
        "test_diff_must_cover_every_mutated_file",
        "test_invalid_verification_receipt_requires_refresh",
        "test_proof_before_edit_does_not_authorize_later_revision",
        "test_replayed_durable_edit_event_is_idempotent_by_action",
        "test_restart_preserves_current_revision_and_remaining_gaps",
        "test_two_large_multi_file_edits_compact_and_restore_exact_proof",
    ]),
    "transactions": ("master_frontier_repository_actions.test.py", [
        "test_commit_failure_rolls_back_already_replaced_files",
        "test_configured_durable_journal_recovers_after_volatile_runtime_loss",
        "test_corrupt_recovery_journal_blocks_new_mutation",
        "test_create_replace_append_move_delete_batch",
        "test_invalid_later_operation_does_not_commit_earlier_change",
        "test_preimage_assertion_and_postimage_receipt",
        "test_restart_recovery_restores_journaled_preimage",
    ]),
    "diff": ("master_frontier_repository_diff.test.py", [
        "test_entry_and_projection_caps_are_explicit_and_fail_closed",
        "test_includes_index_worktree_delete_rename_and_untracked",
        "test_nested_route_paths_are_route_relative",
        "test_non_repository_returns_typed_failure",
        "test_output_cap_does_not_discard_complete_machine_receipt",
    ]),
    "worktree": ("master_frontier_repository_state.test.py", [
        "test_deleted_postimage_and_scope_are_fail_closed",
        "test_exact_postimages_bind_and_external_change_invalidates_digest",
        "test_route_state_digest_detects_other_dirty_file_changes",
    ]),
    "detached_restart": ("agent_run_store.test.py", [
        "test_begin_agent_run_is_idempotent_and_conflict_guarded",
        "test_message_stream_disconnect_preserves_worker_final_and_replay",
        "test_restart_marks_running_run_interrupted",
        "test_startup_recovery_preserves_run_owned_by_live_worker",
    ]),
    "authority": ("master_frontier_v5_authority.test.py", [
        "test_each_tool_requires_its_individual_route_capability",
        "test_v5_edit_requires_an_observed_preimage",
    ]),
}


def case_count() -> int:
    return sum(len(names) for _path, names in CAMPAIGN.values())


def _load(path: Path):
    name = "mf5_campaign_" + path.name.replace(".", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _flatten(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


class Recorder(unittest.TestResult):
    def __init__(self) -> None:
        super().__init__(); self.rows: list[dict] = []

    def startTest(self, test) -> None:  # noqa: N802
        super().startTest(test); test.__campaign_started = time.monotonic()

    def stopTest(self, test) -> None:  # noqa: N802
        status, detail = "pass", ""
        for collection, label in ((self.failures, "fail"), (self.errors, "error"), (self.skipped, "skip")):
            match = next((value for case, value in collection if case is test), None)
            if match is not None: status, detail = label, str(match)[-1000:]
        self.rows.append({
            "id": test._testMethodName,
            "status": status,
            "durationMs": int((time.monotonic() - test.__campaign_started) * 1000),
            "detail": detail,
        })
        super().stopTest(test)


def run_campaign(report_path: Path = REPORT_PATH) -> dict:
    suite = unittest.TestSuite(); categories: dict[str, str] = {}
    missing = []
    for category, (filename, names) in CAMPAIGN.items():
        module = _load(TEST_ROOT / filename)
        available = {test._testMethodName: test for test in _flatten(unittest.defaultTestLoader.loadTestsFromModule(module))}
        for name in names:
            case_id = f"{category}:{name}"
            if name not in available:
                missing.append(case_id); continue
            categories[name] = category; suite.addTest(available[name])
    result = Recorder(); suite.run(result)
    rows = [{**row, "category": categories.get(row["id"], "unknown")} for row in result.rows]
    failed = [row for row in rows if row["status"] != "pass"]
    ok = case_count() == 50 and len(rows) == 50 and not missing and not failed
    report = {
        "schema": "hermes.context.master_frontier.v5.production_campaign.v1",
        "checkedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "ok": ok,
        "total": len(rows),
        "passed": len(rows) - len(failed),
        "failed": len(failed),
        "missing": missing,
        "categories": {category: len(names) for category, (_path, names) in CAMPAIGN.items()},
        "cases": rows,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    report = run_campaign()
    print(json.dumps({"schema": "MF5_CAMPAIGN/1", "ok": report["ok"], "passed": report["passed"], "total": report["total"], "artifact": REPORT_PATH.relative_to(ROOT).as_posix()}, separators=(",", ":")))
    raise SystemExit(0 if report["ok"] else 1)
