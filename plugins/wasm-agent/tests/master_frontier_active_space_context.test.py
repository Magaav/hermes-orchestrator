#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
sys.path.insert(0, str(SERVER))

import static_server as server  # noqa: E402


class ActiveSpaceContextTests(unittest.TestCase):
    def test_direct_envelope_run_preserves_active_space_identity(self) -> None:
        body = {
            "protocol": "v6",
            "session_id": "agent-test",
            "turn_id": "turn-test",
            "space_id": "space_mqzddgni_2vzsq",
            "space_name": "Realure",
            "active_space": {"id": "space_mqzddgni_2vzsq", "name": "Realure", "display_name": "Realure"},
            "envelope": {
                "schema": "hermes.wasm_agent.master_frontier.v6",
                "trace_id": "trace-test",
                "objective": "What space am I viewing?",
                "route_id": "wasm-agent.avatar-chat.ui",
            },
        }
        run = server.provider_envelope_run_context(body)["run_body"]
        self.assertEqual(run["space_id"], "space_mqzddgni_2vzsq")
        self.assertEqual(run["space_name"], "Realure")
        self.assertEqual(run["active_space"]["display_name"], "Realure")


if __name__ == "__main__":
    unittest.main()
