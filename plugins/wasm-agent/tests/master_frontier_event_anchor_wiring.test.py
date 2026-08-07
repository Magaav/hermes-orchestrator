from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import static_server  # noqa: E402
from master_frontier import event_anchor_adapter  # noqa: E402


class EventAnchorWiringTests(unittest.TestCase):
    def test_terminal_anchor_failure_does_not_erase_completed_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "runs.sqlite3"
            invalid_anchor_target = root / "anchor-directory"
            invalid_anchor_target.mkdir()
            environment = {
                "HERMES_WASM_AGENT_DB_PATH": str(database),
                event_anchor_adapter.FLAG: "1",
                event_anchor_adapter.PATH_ENV: str(invalid_anchor_target),
            }
            server = SimpleNamespace(state_dir=root)
            body = {
                "turn_id": "turn-anchor-failure",
                "session_id": "session-anchor-failure",
                "message": "prove fail-soft terminal persistence",
            }
            with patch.dict(os.environ, environment, clear=False):
                started, created = static_server.begin_agent_run(
                    server, body, user={"id": "42"},
                )
                result = static_server.finish_agent_run(
                    server,
                    started["run_id"],
                    status="completed",
                    final={"reply": "primary answer remains available"},
                )

        self.assertTrue(created)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["final"]["reply"], "primary answer remains available")
        self.assertEqual(result["integrity_proof"]["status"], "unavailable")
        self.assertFalse(result["integrity_proof"]["anchor"]["ok"])


if __name__ == "__main__":
    unittest.main()
