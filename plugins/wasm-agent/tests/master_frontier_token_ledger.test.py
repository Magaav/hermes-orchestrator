#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_ROOT))

from master_frontier.token_ledger import aggregate_provider_usages, provider_call_components, summary_from_calls, with_status_metadata, with_usage_metadata


class MasterFrontierTokenLedgerStatusTests(unittest.TestCase):
    def test_numeric_normalization_retains_bounded_thread_lifecycle_metadata(self) -> None:
        projected = with_usage_metadata({"total_tokens": 5}, {
            "provider_thread_id": "thread-1", "provider_thread_turn": 4,
            "provider_thread_resumed": True, "stable_context_mode": "thread_continuation",
            "stable_context_reused": True, "provider_compaction_generation": 1,
        })
        self.assertEqual(projected["provider_thread_id"], "thread-1")
        self.assertTrue(projected["provider_thread_resumed"])
        self.assertEqual(projected["provider_compaction_generation"], 1)

    def test_preserves_latest_status_metadata_without_adding_it(self) -> None:
        usage, components = aggregate_provider_usages([{
            "prompt_tokens": 10356,
            "completion_tokens": 119,
            "total_tokens": 10475,
            "context_window_tokens": 258000,
            "rate_limits": {"seven_day": {"percent_left": 37, "resets_at": 1786467572}},
            "status_telemetry": {"seven_day": {"status": "reported"}},
            "provider_thread_id": "thread-1",
            "provider_thread_turn": 4,
            "provider_thread_resumed": True,
            "stable_context_reused": True,
        }])
        self.assertEqual(usage["total_tokens"], 10475)
        self.assertEqual(usage["context_window_tokens"], 258000)
        self.assertEqual(usage["rate_limits"]["seven_day"]["percent_left"], 37)
        self.assertEqual(components["provider_1"]["context_window_tokens"], 258000)
        self.assertEqual(usage["status_telemetry"]["seven_day"]["status"], "reported")
        self.assertEqual(usage["provider_thread_turn"], 4)
        self.assertTrue(usage["provider_thread_resumed"])

    def test_persistence_projection_and_summary_retain_status_metadata(self) -> None:
        payload = with_status_metadata(
            {"usage": {"total_tokens": 5}, "components": {"run": {"total_tokens": 5}}},
            {"diagnostics": {"token_usage_total": {
                "context_window_tokens": 258400,
                "rate_limits": {"seven_day": {"percent_left": 37}},
                "provider_thread_id": "thread-1",
                "provider_thread_resumed": True,
                "provider_thread_turn": 4,
            }}},
        )
        self.assertEqual(payload["components"]["run"]["context_window_tokens"], 258400)
        self.assertEqual(payload["components"]["run"]["provider_thread_id"], "thread-1")
        self.assertTrue(payload["components"]["run"]["provider_thread_resumed"])
        summary = summary_from_calls([{
            "exact": True, "input_tokens": 4, "output_tokens": 1, "total_tokens": 5,
            "raw_usage": payload["components"]["run"],
        }])
        self.assertEqual(summary["context_window_tokens"], 258400)
        self.assertEqual(summary["rate_limits"]["seven_day"]["percent_left"], 37)
        self.assertEqual(summary["active_context_tokens"], 4)

    def test_summary_separates_latest_context_from_cumulative_session_usage(self) -> None:
        summary = summary_from_calls([
            {"exact": True, "input_tokens": 10_000, "output_tokens": 10, "total_tokens": 10_010},
            {"exact": True, "input_tokens": 2_000, "output_tokens": 5, "total_tokens": 2_005},
        ])

        self.assertEqual(summary["input_tokens"], 12_000)
        self.assertEqual(summary["active_context_tokens"], 2_000)
        self.assertEqual(summary["fresh_input_tokens"], 12_000)

    def test_persistence_projects_calls_without_run_aggregate(self) -> None:
        projected = provider_call_components({"components": {
            "provider_1": {"input_tokens": 10},
            "provider_2": {"input_tokens": 12},
            "run": {"input_tokens": 22, "api_calls": 2},
        }})
        self.assertEqual(list(projected), ["provider_1", "provider_2"])

    def test_summary_reports_fresh_input_after_cache_reads(self) -> None:
        summary = summary_from_calls([
            {"exact": True, "input_tokens": 10_750, "cached_input_tokens": 0, "output_tokens": 1, "total_tokens": 10_751},
            {"exact": True, "input_tokens": 11_658, "cached_input_tokens": 9_984, "output_tokens": 1, "total_tokens": 11_659},
        ])
        self.assertEqual(summary["input_tokens"], 22_408)
        self.assertEqual(summary["cached_input_tokens"], 9_984)
        self.assertEqual(summary["fresh_input_tokens"], 12_424)

    def test_summary_excludes_mathematically_proven_run_aggregate(self) -> None:
        run_id = "wa_run_browser"
        calls = [
            {"run_id": run_id, "turn_id": "browser", "exact": True, "input_tokens": 11_876, "output_tokens": 81, "cached_input_tokens": 0, "reasoning_tokens": 26, "total_tokens": 11_957},
            {"run_id": run_id, "turn_id": "browser", "exact": True, "input_tokens": 12_330, "output_tokens": 83, "cached_input_tokens": 11_008, "reasoning_tokens": 9, "total_tokens": 12_413},
            {"run_id": run_id, "turn_id": "browser", "exact": True, "input_tokens": 12_794, "output_tokens": 69, "cached_input_tokens": 12_032, "reasoning_tokens": 9, "total_tokens": 12_863},
            {"run_id": run_id, "turn_id": "browser", "exact": True, "input_tokens": 13_812, "output_tokens": 116, "cached_input_tokens": 12_032, "reasoning_tokens": 10, "total_tokens": 13_928},
            {
                "run_id": run_id, "turn_id": "browser", "exact": True,
                "input_tokens": 50_812, "output_tokens": 349, "cached_input_tokens": 35_072,
                "reasoning_tokens": 54, "total_tokens": 51_161,
                "raw_usage": {"api_calls": 4},
            },
            {
                "run_id": "wa_run_followup", "turn_id": "followup", "exact": True,
                "input_tokens": 11_586, "output_tokens": 182, "cached_input_tokens": 0,
                "reasoning_tokens": 101, "total_tokens": 11_768,
                "raw_usage": {"api_calls": 1},
            },
        ]

        summary = summary_from_calls(calls, quest_id="agent_msx31l5y_4s36uc")

        self.assertEqual(summary["provider_call_count"], 5)
        self.assertEqual(summary["input_tokens"], 62_398)
        self.assertEqual(summary["output_tokens"], 531)
        self.assertEqual(summary["reasoning_tokens"], 155)
        self.assertEqual(summary["total_tokens"], 62_929)
        self.assertEqual(summary["turn_count"], 2)
        self.assertEqual(summary["turns"][0]["provider_call_count"], 4)

    def test_summary_keeps_unproven_aggregate_only_usage(self) -> None:
        summary = summary_from_calls([{
            "run_id": "legacy", "exact": True,
            "input_tokens": 20, "output_tokens": 3, "total_tokens": 23,
            "raw_usage": {"api_calls": 2},
        }])

        self.assertEqual(summary["provider_call_count"], 1)
        self.assertEqual(summary["total_tokens"], 23)

    def test_persistence_projection_reads_precanonical_provider_call(self) -> None:
        payload = with_status_metadata(
            {"usage": {"total_tokens": 5}, "components": {"run": {"total_tokens": 5}}},
            {"diagnostics": {"token_usage": [{
                "context_window_tokens": 258400,
                "rate_limits": {"seven_day": {"percent_left": 36}},
            }]}},
        )
        self.assertEqual(payload["components"]["run"]["context_window_tokens"], 258400)
        self.assertEqual(payload["usage"]["rate_limits"]["seven_day"]["percent_left"], 36)


if __name__ == "__main__":
    unittest.main()
