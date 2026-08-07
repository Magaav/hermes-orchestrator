from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools/context/watch-avatar-chat-run.py"
SPEC = importlib.util.spec_from_file_location("avatar_chat_run_watch", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AvatarChatRunWatchTest(unittest.TestCase):
    def test_ui_terminal_backend_running_is_unhealthy(self) -> None:
        backend = {
            "terminal": False, "attempts": 18, "mutations": 0, "tokens": 42_000,
            "duplicates": 8, "cancel_requested": False,
        }
        classification, signals = MODULE.classify(
            backend, {"interrupted": True}, {"page": {"interrupted_visible": True}},
        )
        self.assertEqual(classification, "unhealthy")
        self.assertIn("ui_terminal_backend_running", signals)
        self.assertIn("runaway_no_mutation", signals)
        self.assertIn("token_target_exceeded", signals)
        self.assertIn("novelty_loop", signals)

    def test_cancelled_run_is_terminal_without_false_runaway(self) -> None:
        backend = {
            "terminal": True, "attempts": 118, "mutations": 0, "tokens": 500_000,
            "duplicates": 100, "cancel_requested": True,
        }
        classification, signals = MODULE.classify(backend, {"interrupted": True}, {"page": {}})
        self.assertEqual(classification, "terminal")
        self.assertEqual(signals, [])


if __name__ == "__main__":
    unittest.main()
