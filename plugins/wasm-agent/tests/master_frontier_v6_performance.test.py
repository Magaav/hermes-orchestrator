#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier.v6 import performance  # noqa: E402


class Clock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class V6PerformanceTests(unittest.TestCase):
    def test_timeline_is_partitioned_and_projection_bytes_are_exact(self) -> None:
        clock = Clock(10.0)
        trace = performance.Trace(started_monotonic=9.5, monotonic=clock)
        clock.value = 10.2
        call = trace.provider_started({
            "messages": [{"role": "user", "content": "olá"}], "tools": [],
        }, 1)
        clock.value = 11.7
        trace.provider_finished(call, ok=True)
        clock.value = 11.8
        checkpoint_started = clock()
        clock.value = 11.9
        trace.checkpoint_finished(checkpoint_started)
        clock.value = 12.0

        result = trace.snapshot()

        self.assertEqual(result["total_ms"], 2500)
        self.assertEqual(result["v6_internal_ms"], 2000)
        self.assertEqual(result["phases"], {
            "ingress_to_v6_ms": 500,
            "host_before_first_provider_ms": 200,
            "provider_ms": 1500,
            "host_between_providers_ms": 0,
            "host_after_last_provider_ms": 300,
        })
        self.assertEqual(result["checkpoint"], {"count": 1, "duration_ms": 100})
        self.assertEqual(result["projection"]["message_content_bytes"], 4)
        self.assertEqual(result["provider_calls"][0]["decision"], 1)
        self.assertTrue(result["provider_calls"][0]["ok"])


if __name__ == "__main__":
    unittest.main()
