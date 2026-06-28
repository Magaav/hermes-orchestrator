#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PLUGIN_ROOT / "server" / "static_server.py"

spec = importlib.util.spec_from_file_location("wasm_agent_static_server", SERVER_PATH)
assert spec and spec.loader
static_server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(static_server)


def make_user(user_id: str = "101") -> dict[str, object]:
    return {
        "id": user_id,
        "provider": "test",
        "email": f"user{user_id}@example.test",
        "email_verified": True,
        "role": "user",
        "name": "User",
        "picture_url": "",
        "created_at": 0,
        "last_login_at": 0,
    }


class StreamingPerformanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.env = {
            "HERMES_WASM_AGENT_DB_PATH": str(self.root / "db" / "wa.sqlite3"),
            "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
        }
        self.server = SimpleNamespace(
            plugin_root=PLUGIN_ROOT,
            public_root=PLUGIN_ROOT / "public",
            state_dir=self.root / "state",
            bridge_url="http://127.0.0.1:8790",
            browser_timeout_sec=1.0,
            chat_turn_results={},
            chat_turn_results_lock=threading.Lock(),
            agent_run_workers={},
            agent_run_workers_lock=threading.Lock(),
        )
        self.user = make_user()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_stream_text_ndjson_coalesces_deltas_and_instruments(self) -> None:
        body = {
            "session_id": "agent_session",
            "turn_id": "turn-stream-perf",
            "message": "Hello",
            "mode": "local",
            "target_node": "account-sandbox",
            "transcript": [],
        }

        with patch.dict(os.environ, self.env, clear=True):
            run, _created = static_server.begin_agent_run(self.server, dict(body), user=self.user)
            run_id = run["run_id"]

            # Insert delta events and a final event using the helper
            with static_server.auth_connect() as conn:
                run_row = static_server.get_agent_run_for_user(conn, run_id, self.user)
                for delta in ["Hello", " ", "world", "!"]:
                    static_server.agent_run_append_event_conn(
                        conn, run_row, "head.delta", payload={"delta": delta}
                    )
                static_server.agent_run_append_event_conn(
                    conn, run_row, "run.final", payload={}
                )

            # Mock handler
            output = io.BytesIO()
            handler = SimpleNamespace(wfile=output)

            static_server.stream_agent_run_text_ndjson(
                handler, run_id, user=self.user, after_seq=0
            )

            output.seek(0)
            raw = output.read()
            lines = [line for line in raw.split(b"\n") if line.strip()]

            # The first line should be the coalesced delta string
            self.assertTrue(lines, "No output lines")
            first_line = lines[0]
            parsed = json.loads(first_line.decode("utf-8"))
            self.assertEqual(parsed, "Hello world!", f"Expected coalesced delta, got {parsed}")

            # The last line should be the final JSON object
            last_line = lines[-1]
            final_payload = json.loads(last_line.decode("utf-8"))
            self.assertEqual(final_payload.get("type"), "final")

            # Should be exactly 2 lines: one coalesced delta string, one final object
            self.assertEqual(len(lines), 2, f"Expected 2 lines (coalesced delta + final), got {len(lines)}: {lines}")

    def test_stream_text_ndjson_no_sleep_when_rows_exist(self) -> None:
        body = {
            "session_id": "agent_session",
            "turn_id": "turn-stream-no-sleep",
            "message": "Hello",
            "mode": "local",
            "target_node": "account-sandbox",
            "transcript": [],
        }

        with patch.dict(os.environ, self.env, clear=True):
            run, _created = static_server.begin_agent_run(self.server, dict(body), user=self.user)
            run_id = run["run_id"]

            # Pre-insert many delta events
            with static_server.auth_connect() as conn:
                run_row = static_server.get_agent_run_for_user(conn, run_id, self.user)
                for i in range(2, 12):
                    static_server.agent_run_append_event_conn(
                        conn, run_row, "head.delta", payload={"delta": f"t{i}"}
                    )
                static_server.agent_run_append_event_conn(
                    conn, run_row, "run.final", payload={}
                )

            output = io.BytesIO()
            handler = SimpleNamespace(wfile=output)

            start = time.monotonic()
            static_server.stream_agent_run_text_ndjson(
                handler, run_id, user=self.user, after_seq=0
            )
            elapsed = time.monotonic() - start

            # With 50ms sleep and 10 deltas + final, if sleep were unconditional,
            # elapsed would be at least ~50ms. With no sleep when rows exist,
            # it should complete in well under 50ms (SQLite is fast).
            self.assertLess(elapsed, 0.05, f"Streamer slept unnecessarily; elapsed={elapsed:.3f}s")

            output.seek(0)
            raw = output.read()
            lines = [line for line in raw.split(b"\n") if line.strip()]
            # First line should be coalesced deltas
            first = json.loads(lines[0].decode("utf-8"))
            self.assertTrue(first.startswith("t2"))
            # Last line final
            last = json.loads(lines[-1].decode("utf-8"))
            self.assertEqual(last.get("type"), "final")


if __name__ == "__main__":
    unittest.main()
