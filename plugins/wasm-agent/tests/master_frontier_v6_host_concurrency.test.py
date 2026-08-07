#!/usr/bin/env python3
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch


PLUGIN = Path(__file__).resolve().parents[1]
SERVER_PATH = PLUGIN / "server/static_server.py"
SPEC = importlib.util.spec_from_file_location("wasm_agent_v6_host_concurrency", SERVER_PATH)
assert SPEC and SPEC.loader
static_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(static_server)


class V6HostConcurrencyTests(unittest.TestCase):
    def test_parallel_operation_events_keep_contiguous_ledger_and_final_anchor(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mf6-host-") as directory:
            root = Path(directory)
            environment = {
                "HERMES_WASM_AGENT_DB_PATH": str(root / "db" / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
                "WASM_AGENT_EVENT_ANCHORS": "1",
                "WASM_AGENT_EVENT_ANCHOR_INTERVAL": "16",
            }
            server = SimpleNamespace(
                plugin_root=PLUGIN, public_root=PLUGIN / "public", state_dir=root / "state",
                bridge_url="http://127.0.0.1:8790", chat_turn_results={},
                chat_turn_results_lock=threading.Lock(), agent_run_workers={},
                agent_run_workers_lock=threading.Lock(),
            )
            user = {"id": "101", "role": "admin", "email": "admin@example.test"}
            with patch.dict(os.environ, environment, clear=True):
                run, created = static_server.begin_agent_run(server, {
                    "session_id": "v6-concurrency", "turn_id": "parallel-events",
                    "message": "Stress V6 event persistence", "mode": "direct-head",
                    "target_node": "direct-head", "protocol": "v6",
                }, user=user, direct_head=True)
                self.assertTrue(created)

                def append(index):
                    return static_server.append_agent_run_event(
                        server, run["run_id"], "evidence.received",
                        summary=f"operation {index}", payload={"protocol": "v6", "operation": f"op.{index}"},
                    )

                with ThreadPoolExecutor(max_workers=16) as pool:
                    inserted = list(pool.map(append, range(64)))
                final = static_server.finish_agent_run(
                    server, run["run_id"], status="completed",
                    final={"reply": "Stress complete", "changed_files": []},
                )
                events = static_server.read_agent_run_events(
                    user, run["run_id"], {"limit": ["120"]},
                )["events"]

        self.assertEqual(len([item for item in inserted if item]), 64)
        self.assertEqual([item["seq"] for item in events], list(range(1, 67)))
        self.assertEqual(events[0]["type"], "run.started")
        self.assertEqual(events[-1]["type"], "run.final")
        self.assertEqual(final["integrity_proof"]["status"], "verified")
        self.assertEqual(final["integrity_proof"]["anchor"]["events"], 66)


if __name__ == "__main__":
    unittest.main()
