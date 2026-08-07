#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier.v5 import context_accounting  # noqa: E402


class ContextAccountingTests(unittest.TestCase):
    def request(self, evidence: str = "one") -> dict:
        return {
            "messages": [
                {"role": "system", "content": "stable system"},
                {"role": "user", "content": f"MF5/2\nO\topen browser\nR\tid=avatar\nS\tread\tcompleted\t{evidence}\nD\t{{\"ok\":true}}\nZ\tfinish"},
            ],
            "tools": [{"type": "function", "name": "client", "parameters": {"type": "object"}}],
            "tool_choice": "auto",
        }

    def test_classifies_without_enforcing(self) -> None:
        measured, fingerprints = context_accounting.measure(self.request())
        self.assertFalse(measured["enforced"])
        self.assertGreater(measured["group_chars"]["evidence"], 0)
        self.assertGreater(measured["group_chars"]["objective"], 0)
        self.assertEqual(measured["tool_count"], 1)
        self.assertTrue(fingerprints)

    def test_distinguishes_unchanged_and_new_records(self) -> None:
        first, fingerprints = context_accounting.measure(self.request())
        second, _ = context_accounting.measure(self.request("two"), fingerprints)
        self.assertGreater(first["new_chars"], 0)
        self.assertGreater(second["repeated_chars"], second["new_chars"])

    def test_attaches_exact_provider_usage_without_estimating(self) -> None:
        measured, _ = context_accounting.measure(self.request())
        enriched = context_accounting.attach_usage(measured, {"prompt_tokens": 15800, "completion_tokens": 102})
        self.assertEqual(enriched["provider_usage"], {"prompt_tokens": 15800, "completion_tokens": 102})
        self.assertNotIn("estimated_tokens", enriched)


if __name__ == "__main__":
    unittest.main()
