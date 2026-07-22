#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from master_frontier import provider_transport


class ProviderTransportTests(unittest.TestCase):
    def test_default_allows_reasoning_synthesis(self) -> None:
        self.assertEqual(provider_transport.timeout_sec({}), 90.0)

    def test_override_is_bounded_and_invalid_values_fail_to_default(self) -> None:
        key = provider_transport.TIMEOUT_ENV
        self.assertEqual(provider_transport.timeout_sec({key: "5"}), 15.0)
        self.assertEqual(provider_transport.timeout_sec({key: "240"}), 180.0)
        self.assertEqual(provider_transport.timeout_sec({key: "invalid"}), 90.0)
        self.assertEqual(provider_transport.timeout_sec({key: "nan"}), 90.0)

    def test_server_owned_remaining_wall_budget_can_only_reduce_timeout(self) -> None:
        self.assertEqual(provider_transport.timeout_sec({}, requested=7), 7.0)
        self.assertEqual(provider_transport.timeout_sec({}, requested=900), 90.0)
        self.assertEqual(provider_transport.timeout_sec({}, requested=0.5), 0.5)
        self.assertEqual(provider_transport.timeout_sec({}, requested=0), 0.001)


if __name__ == "__main__":
    unittest.main()
