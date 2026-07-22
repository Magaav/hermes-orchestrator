#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen
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


class AgentRunStoreTest(unittest.TestCase):
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

    def test_begin_agent_run_is_idempotent_and_conflict_guarded(self) -> None:
        body = {
            "session_id": "agent_session",
            "turn_id": "turn-one",
            "message": "Hello",
            "mode": "local",
            "target_node": "account-sandbox",
            "transcript": [],
        }
        with patch.dict(os.environ, self.env, clear=True):
            run, created = static_server.begin_agent_run(self.server, dict(body), user=self.user)
            same_run, same_created = static_server.begin_agent_run(self.server, dict(body), user=self.user)

            self.assertTrue(created)
            self.assertFalse(same_created)
            self.assertEqual(same_run["run_id"], run["run_id"])

            events = static_server.read_agent_run_events(self.user, run["run_id"])["events"]
            self.assertEqual([event["type"] for event in events], ["run.started"])
            self.assertEqual(events[0]["seq"], 1)
            self.assertNotIn("Hello", static_server.json.dumps(events[0]))

            listed = static_server.list_agent_runs(self.user, {"session_id": ["agent_session"]})["runs"]
            self.assertEqual(listed[0]["run_id"], run["run_id"])

            with self.assertRaises(static_server.BrowserError) as raised:
                static_server.begin_agent_run(self.server, {**body, "message": "Different"}, user=self.user)
            self.assertEqual(raised.exception.code, "agent_turn_conflict")

    def test_run_protocol_defaults_v3_and_v4_is_explicit_persisted_immutable(self) -> None:
        base = {"session_id": "protocol-session", "message": "inspect source", "mode": "direct-head"}
        with patch.dict(os.environ, self.env, clear=True):
            legacy, _ = static_server.begin_agent_run(self.server, {**base, "turn_id": "legacy"}, user=self.user)
            self.assertEqual(legacy["protocol"], "v3")
            with self.assertRaises(static_server.master_frontier_run_protocol.ProtocolError):
                static_server.begin_agent_run(self.server, {**base, "turn_id": "missing-flag", "protocol": "v4-source-investigation"}, user=self.user)
            request = {**base, "turn_id": "v4", "protocol": "v4-source-investigation", "investigation_mode": "source-investigation-read-only"}
            selected, _ = static_server.begin_agent_run(self.server, dict(request), user=self.user)
            replay, created = static_server.begin_agent_run(self.server, dict(request), user=self.user)
            self.assertFalse(created)
            self.assertEqual(selected["protocol"], "v4-source-investigation")
            self.assertEqual(replay["request_summary"]["protocol"], "v4-source-investigation")
            with self.assertRaises(static_server.BrowserError) as raised:
                static_server.begin_agent_run(self.server, {**base, "turn_id": "v4"}, user=self.user)
            self.assertEqual(raised.exception.code, "agent_turn_conflict")

    def test_run_worker_records_action_and_final_event(self) -> None:
        body = {
            "session_id": "agent_session",
            "turn_id": "turn-worker",
            "message": "Hello",
            "mode": "local",
            "target_node": "account-sandbox",
            "transcript": [],
        }

        def fake_embedded_message(server, request_body, *, user=None, action_callback=None):
            if action_callback:
                action_callback({
                    "id": "node_reply",
                    "topic": "run-hermes",
                    "kind": "model",
                    "label": "Final response",
                    "status": "done",
                    "detail": "local",
                })
            return {
                "schema": "hermes.wasm_agent.embedded_agent.message.v1",
                "session_id": request_body["session_id"],
                "target_node": request_body["target_node"],
                "reply": "Done",
                "duration_ms": 1,
                "actions": [],
                "diagnostics": {
                    "source": "local_deterministic",
                    "token_usage": {"total_tokens": 0},
                    "auto_checkpoint": {"ref": "proof://checkpoint", "label": "chat-proof"},
                    "test_results": {"passed": 1, "failed": 0},
                },
                "touched_files": [{"path": "plugins/wasm-agent/server/README.md", "content": "do-not-store"}],
                "changed_files": [{"path": "plugins/wasm-agent/public/app.js", "status": "modified"}],
                "context_preview": [],
            }

        with patch.dict(os.environ, self.env, clear=True), patch.object(
            static_server,
            "embedded_agent_message",
            side_effect=fake_embedded_message,
        ):
            result = static_server.run_embedded_agent_message(self.server, dict(body), user=self.user)
            self.assertEqual(result["reply"], "Done")
            self.assertTrue(result["run_id"].startswith("wa_run_"))

            events = static_server.read_agent_run_events(self.user, result["run_id"])["events"]
            event_types = [event["type"] for event in events]
            self.assertEqual(event_types[0], "run.started")
            self.assertIn("hermes.progress", event_types)
            self.assertIn("files.touched", event_types)
            self.assertIn("files.changed", event_types)
            self.assertIn("proof.collected", event_types)
            self.assertIn("tests.finished", event_types)
            self.assertEqual(event_types[-1], "run.final")
            self.assertTrue(all(event["redacted"] for event in events))
            self.assertLess(max(len(static_server.json.dumps(event["payload"])) for event in events), static_server.AGENT_RUN_EVENT_MAX_JSON_CHARS)
            touched_event = next(event for event in events if event["type"] == "files.touched")
            self.assertEqual(touched_event["payload"]["touched_files"][0]["path"], "plugins/wasm-agent/server/README.md")
            self.assertNotIn("do-not-store", static_server.json.dumps(touched_event["payload"]))

            # Compact timeline contract: no topic/kind/arguments, presence of event_type/meta/label
            for event in events:
                if event["type"] in {"hermes.progress", "files.touched", "files.changed", "proof.collected", "tests.finished", "run.started"}:
                    action = event["payload"].get("action") if isinstance(event["payload"], dict) else None
                    if isinstance(action, dict):
                        self.assertNotIn("topic", action)
                        self.assertNotIn("kind", action)
                        self.assertNotIn("arguments", action)
                        self.assertIn("event_type", action)
                        self.assertIn("meta", action)
                        self.assertIn("label", action)
                        self.assertEqual(action["label"], event["type"])
                        self.assertEqual(action["meta"], event["type"])

            run = static_server.read_agent_run(self.user, result["run_id"])["run"]
            self.assertEqual(run["status"], "completed")
            self.assertEqual(run["final"]["reply"], "Done")
            self.assertEqual(run["final"]["changed_files"][0]["path"], "plugins/wasm-agent/public/app.js")

            with self.assertRaises(static_server.BrowserError) as raised:
                static_server.read_agent_run(make_user("202"), result["run_id"])
            self.assertEqual(raised.exception.code, "agent_run_not_found")

    def test_message_stream_disconnect_preserves_worker_final_and_replay(self) -> None:
        body = {
            "session_id": "agent_session",
            "turn_id": "turn-http-disconnect",
            "message": "Hello over HTTP",
            "mode": "local",
            "target_node": "account-sandbox",
            "transcript": [],
        }

        def fake_embedded_message(server, request_body, *, user=None, action_callback=None):
            time.sleep(0.2)
            if action_callback:
                action_callback({
                    "id": "node_reply",
                    "topic": "run-hermes",
                    "kind": "model",
                    "label": "HTTP final response",
                    "status": "done",
                    "detail": "local",
                })
            return {
                "schema": "hermes.wasm_agent.embedded_agent.message.v1",
                "session_id": request_body["session_id"],
                "target_node": request_body["target_node"],
                "reply": "HTTP Done",
                "duration_ms": 2,
                "actions": [],
                "diagnostics": {
                    "source": "local_deterministic",
                    "token_usage": {"total_tokens": 0},
                    "auto_checkpoint": {"ref": "proof://http-checkpoint", "label": "http-proof"},
                    "test_results": {"passed": 2, "failed": 0},
                },
                "tools": [{"tool": "read_file", "path": "plugins/wasm-agent/server/README.md", "returncode": 0}],
                "changed_files": [{"path": "plugins/wasm-agent/server/static_server.py", "status": "modified"}],
                "context_preview": [{"tool": "fake", "preview": "compact"}],
            }

        with patch.dict(os.environ, self.env, clear=True), \
            patch.object(static_server, "authenticated_request_user", return_value=self.user), \
            patch.object(static_server, "embedded_agent_message", side_effect=fake_embedded_message):
            server = static_server.WasmAgentServer(
                ("127.0.0.1", 0),
                static_server.WasmAgentHandler,
                plugin_root=PLUGIN_ROOT,
                public_root=PLUGIN_ROOT / "public",
                state_dir=self.root / "state",
                bridge_url="http://127.0.0.1:8790",
                browser_timeout_sec=1.0,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}/agent/session/message/stream",
                    data=json.dumps(body).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                response = urlopen(request, timeout=5)
                try:
                    first_line = json.loads(response.readline().decode("utf-8"))
                    run_id = first_line["run"]["run_id"]
                finally:
                    response.close()

                final = static_server.wait_for_agent_run_terminal(self.user, run_id, timeout_sec=5)
                list_request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}/agent/runs?session_id=agent_session&limit=20",
                    method="GET",
                )
                with urlopen(list_request, timeout=5) as list_response:
                    listed = json.loads(list_response.read().decode("utf-8"))
                discovered_run = next(
                    run
                    for run in listed["runs"]
                    if run["turn_id"] == "turn-http-disconnect"
                )
                replay_request = Request(
                    f"http://127.0.0.1:{server.server_address[1]}/agent/runs/{discovered_run['run_id']}/stream?after_seq=1",
                    method="GET",
                )
                with urlopen(replay_request, timeout=5) as replay_response:
                    replay_lines = [
                        json.loads(line)
                        for line in replay_response.read().decode("utf-8").splitlines()
                        if line.strip()
                    ]
                events = static_server.read_agent_run_events(self.user, run_id)["events"]
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(first_line["type"], "run")
        self.assertEqual(discovered_run["run_id"], run_id)
        self.assertEqual(discovered_run["session_id"], "agent_session")
        self.assertEqual(discovered_run["status"], "completed")
        self.assertFalse(discovered_run["direct_head"])
        self.assertEqual(final["reply"], "HTTP Done")
        self.assertEqual(final["changed_files"][0]["path"], "plugins/wasm-agent/server/static_server.py")
        self.assertEqual(final["diagnostics"]["test_results"]["passed"], 2)
        self.assertEqual(replay_lines[-1]["type"], "final")
        self.assertEqual(replay_lines[-1]["agent"]["reply"], "HTTP Done")
        replay_actions = [line["action"] for line in replay_lines if line.get("type") == "action" and isinstance(line.get("action"), dict)]
        replay_action_meta = [action.get("meta") for action in replay_actions]
        self.assertIn("files.touched", replay_action_meta)
        self.assertIn("files.changed", replay_action_meta)
        self.assertIn("proof.collected", replay_action_meta)
        self.assertIn("tests.finished", replay_action_meta)
        event_types = [event["type"] for event in events]
        self.assertIn("hermes.progress", event_types)
        self.assertIn("files.touched", event_types)
        self.assertIn("files.changed", event_types)
        self.assertIn("proof.collected", event_types)
        self.assertIn("tests.finished", event_types)
        self.assertEqual(event_types[-1], "run.final")

    def test_restart_marks_running_run_interrupted(self) -> None:
        body = {
            "session_id": "agent_session",
            "turn_id": "turn-interrupted",
            "message": "Hello",
            "mode": "local",
            "target_node": "account-sandbox",
            "transcript": [],
        }
        with patch.dict(os.environ, self.env, clear=True):
            run, _created = static_server.begin_agent_run(self.server, dict(body), user=self.user)
            static_server.append_agent_run_event(
                self.server,
                run["run_id"],
                "envelope.created",
                summary="checkpoint",
                payload={"envelope": {"objective": "Hello"}},
            )
            with static_server.auth_connect() as connection:
                row = connection.execute("SELECT request_summary_json FROM agent_run_tb WHERE run_id=?", (run["run_id"],)).fetchone()
                summary = json.loads(row["request_summary_json"]); summary["worker"] = {"host": "dead-host", "pid": 1, "start": "dead"}
                connection.execute("UPDATE agent_run_tb SET request_summary_json=?,updated_at=0 WHERE run_id=?", (json.dumps(summary), run["run_id"]))
                connection.commit()
            static_server.mark_interrupted_agent_runs(self.server)

            interrupted = static_server.read_agent_run(self.user, run["run_id"])["run"]
            self.assertEqual(interrupted["status"], "interrupted")
            self.assertEqual(interrupted["error"]["code"], "agent_run_interrupted")
            checkpoint = interrupted["error"]["resume_checkpoint"]
            self.assertEqual(checkpoint["original_objective"], "Hello")
            self.assertEqual(checkpoint["previous_run_id"], run["run_id"])
            self.assertEqual(checkpoint["previous_turn_id"], "turn-interrupted")
            self.assertTrue(checkpoint["resume_key"])

            events = static_server.read_agent_run_events(self.user, run["run_id"])["events"]
            self.assertEqual(events[-1]["type"], "run.error")

    def test_restart_reconciliation_pages_without_skipping_runs(self) -> None:
        runs = []
        with patch.dict(os.environ, self.env, clear=True):
            for index in range(3):
                run, _created = static_server.begin_agent_run(
                    self.server,
                    {
                        "session_id": "agent_session",
                        "turn_id": f"turn-paged-{index}",
                        "message": "Hello",
                    },
                    user=self.user,
                )
                runs.append(run)
            with static_server.auth_connect() as connection:
                for run in runs:
                    row = connection.execute(
                        "SELECT request_summary_json FROM agent_run_tb WHERE run_id=?",
                        (run["run_id"],),
                    ).fetchone()
                    summary = json.loads(row["request_summary_json"])
                    summary["worker"] = {"host": "dead-host", "pid": 1, "start": "dead"}
                    connection.execute(
                        "UPDATE agent_run_tb SET request_summary_json=?,updated_at=0 WHERE run_id=?",
                        (json.dumps(summary), run["run_id"]),
                    )
                connection.commit()

            with patch.object(static_server.master_frontier_run_recovery, "RECONCILE_BATCH_SIZE", 1):
                static_server.mark_interrupted_agent_runs(self.server)

            statuses = [static_server.read_agent_run(self.user, run["run_id"])["run"]["status"] for run in runs]
            self.assertEqual(statuses, ["interrupted", "interrupted", "interrupted"])

    def test_auxiliary_server_startup_does_not_mark_running_run_interrupted(self) -> None:
        primary = SimpleNamespace(server_port=8877)
        auxiliary = SimpleNamespace(server_port=40287)
        with patch.dict(os.environ, self.env, clear=True):
            self.assertTrue(static_server.should_mark_interrupted_agent_runs_on_startup(primary))
            self.assertFalse(static_server.should_mark_interrupted_agent_runs_on_startup(auxiliary))

        with patch.dict(os.environ, {**self.env, "HERMES_WASM_AGENT_MARK_INTERRUPTED_ON_STARTUP": "1"}, clear=True):
            self.assertTrue(static_server.should_mark_interrupted_agent_runs_on_startup(auxiliary))

        with patch.dict(os.environ, {**self.env, "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "cloud"}, clear=True):
            self.assertTrue(static_server.should_mark_interrupted_agent_runs_on_startup(auxiliary))

    def test_startup_recovery_preserves_run_owned_by_live_worker(self) -> None:
        body = {"session_id": "agent_session", "turn_id": "turn-live-worker", "message": "Hello"}
        with patch.dict(os.environ, self.env, clear=True):
            run, _created = static_server.begin_agent_run(self.server, body, user=self.user)
            static_server.mark_interrupted_agent_runs(self.server)
            current = static_server.read_agent_run(self.user, run["run_id"])["run"]
            self.assertEqual(current["status"], "running")
            static_server.finish_agent_run(self.server, run["run_id"], status="cancelled", error={"code":"test_cleanup"})

    def test_direct_head_timeline_events_are_compact_and_replayable(self) -> None:
        admin_user = {"id": "101", "role": "admin", "email": "admin@example.test"}
        body = {
            "session_id": "agent_session",
            "turn_id": "turn-direct-head-timeline",
            "message": "Direct head timeline test",
            "mode": "direct-head",
            "target_node": "direct-head",
        }
        with patch.dict(os.environ, self.env, clear=True):
            run, _created = static_server.begin_agent_run(self.server, dict(body), user=admin_user, direct_head=True)
            # Simulate key timeline events via the production path
            static_server.record_agent_run_action(self.server, run["run_id"], {"id": "patch", "topic": "run-hermes", "kind": "tool", "label": "patch", "status": "running", "detail": "editing"})
            static_server.record_agent_run_action(self.server, run["run_id"], {"id": "patch", "topic": "run-hermes", "kind": "tool", "label": "patch", "status": "done", "detail": "done"})
            static_server.record_agent_run_action(self.server, run["run_id"], {"id": "pytest", "topic": "test", "kind": "test", "label": "pytest", "status": "running", "detail": "starting"})
            static_server.record_agent_run_action(self.server, run["run_id"], {"id": "pytest", "topic": "test", "kind": "test", "label": "pytest", "status": "done", "detail": "5 passed"})
            static_server.finish_agent_run(self.server, run["run_id"], status="completed", final={"reply": "Done", "changed_files": []})

            events = static_server.read_agent_run_events(admin_user, run["run_id"])["events"]
            event_types = [event["type"] for event in events]
            self.assertEqual(event_types[0], "run.started")
            self.assertIn("tool.started", event_types)
            self.assertIn("tool.finished", event_types)
            self.assertIn("tests.started", event_types)
            self.assertIn("tests.finished", event_types)
            self.assertEqual(event_types[-1], "run.final")

            # Verify stream payload compactness for replay (tool/test events pass through generic action branch)
            replay_payloads = [static_server.agent_run_event_stream_payload(self.server, event, user=admin_user) for event in events]
            for payload in replay_payloads:
                if payload and payload.get("type") == "action" and payload.get("action"):
                    action = payload["action"]
                    self.assertNotIn("topic", action)
                    self.assertNotIn("kind", action)
                    self.assertNotIn("arguments", action)
                    self.assertIn("event_type", action)
                    self.assertIn("meta", action)
                    self.assertEqual(action["label"], action["event_type"])

    def test_non_admin_cannot_list_or_read_direct_head_runs(self) -> None:
        admin_user = {"id": "303", "role": "admin", "email": "admin@example.test"}
        same_account_non_admin = {"id": "303", "role": "user", "email": "admin@example.test"}
        body = {
            "session_id": "agent_session",
            "turn_id": "turn-direct-head",
            "message": "Direct head",
            "mode": "direct-head",
            "target_node": "direct-head",
        }
        with patch.dict(os.environ, self.env, clear=True):
            run, _created = static_server.begin_agent_run(self.server, dict(body), user=admin_user, direct_head=True)

            listed = static_server.list_agent_runs(same_account_non_admin, {"session_id": ["agent_session"]})["runs"]
            self.assertEqual(listed, [])

            with self.assertRaises(static_server.BrowserError) as raised:
                static_server.read_agent_run(same_account_non_admin, run["run_id"])
            self.assertEqual(raised.exception.code, "admin_required")


if __name__ == "__main__":
    unittest.main()
