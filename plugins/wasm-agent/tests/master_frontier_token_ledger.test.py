#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_ROOT))

from master_frontier.token_ledger import aggregate_provider_usages, summary_from_calls, with_status_metadata


class MasterFrontierTokenLedgerStatusTests(unittest.TestCase):
    def test_preserves_latest_status_metadata_without_adding_it(self) -> None:
        usage, components = aggregate_provider_usages([{
            "prompt_tokens": 10356,
            "completion_tokens": 119,
            "total_tokens": 10475,
            "context_window_tokens": 258000,
            "rate_limits": {"seven_day": {"percent_left": 37, "resets_at": 1786467572}},
        }])
        self.assertEqual(usage["total_tokens"], 10475)
        self.assertEqual(usage["context_window_tokens"], 258000)
        self.assertEqual(usage["rate_limits"]["seven_day"]["percent_left"], 37)
        self.assertEqual(components["provider_1"]["context_window_tokens"], 258000)

    def test_persistence_projection_and_summary_retain_status_metadata(self) -> None:
        payload = with_status_metadata(
            {"usage": {"total_tokens": 5}, "components": {"run": {"total_tokens": 5}}},
            {"diagnostics": {"token_usage_total": {
                "context_window_tokens": 258400,
                "rate_limits": {"seven_day": {"percent_left": 37}},
            }}},
        )
        self.assertEqual(payload["components"]["run"]["context_window_tokens"], 258400)
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
