#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier.v6 import reasoning  # noqa: E402


class V6ReasoningTests(unittest.TestCase):
    def test_defaults_to_light_api_effort(self) -> None:
        self.assertEqual(reasoning.effort(None), "low")
        self.assertEqual(reasoning.effort("unsupported"), "low")

    def test_accepts_supported_efforts(self) -> None:
        for value in ("none", "low", "medium", "high", "xhigh", "max"):
            self.assertEqual(reasoning.effort(value), value)


if __name__ == "__main__":
    unittest.main()
