from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = PLUGIN_ROOT / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from routes import (
    BridgeSettings,
    OrchestratorClient,
    TaskStore,
    activity_from_running_task,
    compact_run_event,
    read_node_session_token_usage,
    render_node_env,
    rewrite_exhaust_slash_prompt,
    run_options_from_payload,
)


def _settings(tmp_path: Path) -> BridgeSettings:
    return BridgeSettings(
        plugin_root=PLUGIN_ROOT,
        repo_root=tmp_path,
        host="127.0.0.1",
        port=8790,
        token="",
        horc_path="/bin/true",
        agents_root=tmp_path,
        state_dir=tmp_path,
        timeout_sec=1,
        space_agent_url="",
        space_agent_repo="",
        agent_root=tmp_path,
        agent_env_path=tmp_path / "env",
        agent_python=Path(sys.executable),
        api_server_url="http://127.0.0.1:8642",
        api_server_key="",
        api_server_timeout_sec=1,
        api_server_poll_interval_sec=0.1,
    )


class RoutesTest(unittest.TestCase):
    def test_compact_run_event_keeps_thinking_and_cli_command(self) -> None:
        thinking = compact_run_event({"event": "reasoning.available", "text": "Checking files."})
        compact = compact_run_event(
            {
                "type": "tool.started",
                "run_id": "run_1",
                "toolCallId": "call_123",
                "payload": {
                    "tool": "terminal",
                    "arguments_preview": {"command": "pwd"},
                    "result_preview": "cwd",
                },
            }
        )

        self.assertEqual(thinking["event"], "reasoning.available")
        self.assertEqual(thinking["text"], "Checking files.")
        self.assertEqual(compact["event"], "tool.started")
        self.assertEqual(compact["tool"], "terminal")
        self.assertEqual(compact["tool_call_id"], "call_123")
        self.assertEqual(compact["command"], "pwd")
        self.assertEqual(compact["args"]["command"], "pwd")
        self.assertEqual(compact["output"], "cwd")

    def test_task_store_records_thinking_delta_and_cancel_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store = TaskStore(tmp_path)
            task = store.create_running("prompt", "orchestrator")

            store.record_event(task["task_id"], {"event": "thinking.delta", "delta": "Checking files."})
            store.request_cancel(task["task_id"], reason="modal closed")

            updated = store.get(task["task_id"])
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(updated["result"]["thinking_stream"], "Checking files.")
            self.assertIs(updated["result"]["cancel_requested"], True)
            self.assertEqual(updated["result"]["run_status"], "stopping")

    def test_task_store_records_live_usage_for_running_activity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store = TaskStore(tmp_path)
            task = store.create_running("prompt", "orchestrator")
            store.update_running(task["task_id"], result={"run_id": "run_123"})

            store.record_event(
                task["task_id"],
                {
                    "event": "message.delta",
                    "delta": "hello",
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 5,
                        "total_tokens": 17,
                    },
                },
            )

            updated = store.get(task["task_id"])
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(updated["result"]["token_usage"]["total_tokens"], 17)
            self.assertEqual(updated["result"]["response_stream"], "hello")

            activity = activity_from_running_task(updated)
            self.assertEqual(activity["total_tokens"], 17)
            self.assertEqual(activity["input_tokens"], 12)
            self.assertEqual(activity["output_tokens"], 5)
            self.assertEqual(activity["api_calls"], 1)

    def test_task_store_records_hermes_camelcase_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store = TaskStore(tmp_path)
            task = store.create_running("prompt", "orchestrator")
            store.update_running(task["task_id"], result={"run_id": "run_123"})

            store.record_event(
                task["task_id"],
                {
                    "event": "run.completed",
                    "tokenUsage": {
                        "inputTokens": 42,
                        "outputTokens": 8,
                        "totalTokens": 50,
                        "cachedInputTokens": 12,
                        "reasoningOutputTokens": 3,
                    },
                },
            )

            updated = store.get(task["task_id"])
            self.assertIsNotNone(updated)
            assert updated is not None
            usage = updated["result"]["token_usage"]
            self.assertEqual(usage["total_tokens"], 50)
            self.assertEqual(usage["input_tokens"], 42)
            self.assertEqual(usage["output_tokens"], 8)
            self.assertEqual(usage["cache_read_tokens"], 12)
            self.assertEqual(usage["reasoning_tokens"], 3)

    def test_reads_exact_node_session_usage_from_state_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_dir = tmp_path / "nodes" / "orchestrator" / ".hermes"
            db_dir.mkdir(parents=True)
            import sqlite3

            conn = sqlite3.connect(db_dir / "state.db")
            conn.execute(
                """
                CREATE TABLE sessions (
                  id TEXT PRIMARY KEY,
                  source TEXT,
                  model TEXT,
                  input_tokens INTEGER,
                  output_tokens INTEGER,
                  cache_read_tokens INTEGER,
                  cache_write_tokens INTEGER,
                  reasoning_tokens INTEGER,
                  api_call_count INTEGER
                )
                """
            )
            conn.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("space-ui-orchestrator-test", "api_server", "kimi-k2.6", 100, 20, 300, 4, 6, 3),
            )
            conn.commit()
            conn.close()

            usage = read_node_session_token_usage(_settings(tmp_path), "orchestrator", "space-ui-orchestrator-test")

            self.assertEqual(usage["input_tokens"], 100)
            self.assertEqual(usage["output_tokens"], 20)
            self.assertEqual(usage["cache_read_tokens"], 300)
            self.assertEqual(usage["cache_write_tokens"], 4)
            self.assertEqual(usage["reasoning_tokens"], 6)
            self.assertEqual(usage["total_tokens"], 430)
            self.assertEqual(usage["api_calls"], 3)
            self.assertEqual(usage["usage_accuracy"], "provider_exact")

    def test_exact_session_usage_replaces_provisional_folded_cache_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store = TaskStore(tmp_path)
            task = store.create_running("prompt", "orchestrator")

            store.update_running(
                task["task_id"],
                result={
                    "token_usage": {
                        "input_tokens": 3610808,
                        "output_tokens": 24124,
                        "total_tokens": 3634932,
                        "api_calls": 0,
                    }
                },
            )
            store.update_running(
                task["task_id"],
                result={
                    "token_usage": {
                        "input_tokens": 108407,
                        "output_tokens": 24124,
                        "cache_read_tokens": 3502401,
                        "total_tokens": 3634932,
                        "api_calls": 46,
                        "source": "hermes_state_db",
                        "model": "kimi-k2.6",
                    }
                },
            )

            updated = store.get(task["task_id"])
            self.assertIsNotNone(updated)
            assert updated is not None
            usage = updated["result"]["token_usage"]
            self.assertEqual(usage["input_tokens"], 108407)
            self.assertEqual(usage["output_tokens"], 24124)
            self.assertEqual(usage["cache_read_tokens"], 3502401)
            self.assertEqual(usage["total_tokens"], 3634932)
            self.assertEqual(usage["api_calls"], 46)
            self.assertEqual(usage["source"], "hermes_state_db")

    def test_run_options_keep_dispatch_workspace_root(self) -> None:
        options = run_options_from_payload({
            "model": "embedded-hermes",
            "cwd": "/local/plugins/wasm-agent",
            "workspace_root": "/local/plugins/wasm-agent",
            "timeout_sec": 12,
        })

        self.assertIsNotNone(options)
        assert options is not None
        self.assertEqual(options["cwd"], "/local/plugins/wasm-agent")
        self.assertEqual(options["workspace_root"], "/local/plugins/wasm-agent")
        self.assertEqual(options["model"], "embedded-hermes")

    def test_running_task_preserves_dispatch_workspace_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store = TaskStore(tmp_path)
            task = store.create_running("prompt", "orchestrator")

            updated = store.update_running(
                task["task_id"],
                result={
                    "run_id": "run_123",
                    "run_options": {
                        "model": "embedded-hermes",
                        "cwd": "/local/plugins/wasm-agent",
                        "workspace_root": "/local/plugins/wasm-agent",
                    },
                },
            )

            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(updated["result"]["run_options"]["cwd"], "/local/plugins/wasm-agent")
            self.assertEqual(updated["result"]["run_options"]["workspace_root"], "/local/plugins/wasm-agent")

    def test_stop_task_calls_node_run_stop_and_marks_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store = TaskStore(tmp_path)
            task = store.create_running("prompt", "orchestrator")
            store.update_running(task["task_id"], result={"run_id": "run_123"})
            client = OrchestratorClient(_settings(tmp_path), store)
            calls = []

            def fake_api_request(node_id, method, path, **kwargs):
                calls.append((node_id, method, path, kwargs))
                return {"run_id": "run_123", "status": "stopping"}

            client._api_request = fake_api_request

            stopped = client.stop_task(task["task_id"], reason="stop button")

            self.assertEqual(calls[0][0:3], ("orchestrator", "POST", "/v1/runs/run_123/stop"))
            self.assertEqual(stopped["status"], "cancelled")
            self.assertEqual(stopped["result"]["run_status"], "cancelled")
            self.assertEqual(stopped["error"]["code"], "task_cancelled")

    def test_api_server_url_falls_back_to_node_env_and_container_ip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            settings = _settings(tmp_path)
            settings = BridgeSettings(
                **{
                    **settings.__dict__,
                    "api_server_url": "",
                    "agents_root": tmp_path,
                }
            )
            env_dir = tmp_path / "envs"
            env_dir.mkdir()
            (env_dir / "worker-one.env").write_text(
                "API_SERVER_HOST=0.0.0.0\nAPI_SERVER_PORT=8642\nAPI_SERVER_KEY=sk-node\n",
                encoding="utf-8",
            )
            client = OrchestratorClient(settings, TaskStore(tmp_path / "tasks"))
            import routes

            original = routes.container_ip_for_node
            routes.container_ip_for_node = lambda node: "172.17.0.8"
            try:
                self.assertEqual(client._api_server_url_for_node("worker-one"), "http://172.17.0.8:8642")
                self.assertEqual(client._api_server_key_for_node("worker-one"), "sk-node")
            finally:
                routes.container_ip_for_node = original

    def test_render_node_env_uses_docker_env_file_values(self) -> None:
        text = render_node_env(
            "worker-one",
            {
                "NODE_STATE": "4",
                "OPENROUTER_API_KEY": "sk-test",
                "HERMES_EPHEMERAL_SYSTEM_PROMPT": "line one\nline two",
            },
        )

        self.assertIn("NODE_STATE=4\n", text)
        self.assertIn("OPENROUTER_API_KEY=sk-test\n", text)
        self.assertIn("HERMES_EPHEMERAL_SYSTEM_PROMPT=line one\\nline two\n", text)
        self.assertNotIn('OPENROUTER_API_KEY="sk-test"', text)

    def test_exhaust_slash_prompt_accepts_newline_after_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_dir = tmp_path / "envs"
            env_dir.mkdir()
            (env_dir / "orchestrator.env").write_text("PLUGINS_EXHAUST=true\n", encoding="utf-8")

            previous_runtime = os.environ.get("HERMES_WASM_AGENT_BRIDGE_EXHAUST_RUNTIME")
            os.environ["HERMES_WASM_AGENT_BRIDGE_EXHAUST_RUNTIME"] = str(tmp_path / "missing-runtime.py")
            try:
                rewritten = rewrite_exhaust_slash_prompt(
                    "/exhaust\nI need you to summarize the latest video.",
                    node="orchestrator",
                    agents_root=tmp_path,
                )
            finally:
                if previous_runtime is None:
                    os.environ.pop("HERMES_WASM_AGENT_BRIDGE_EXHAUST_RUNTIME", None)
                else:
                    os.environ["HERMES_WASM_AGENT_BRIDGE_EXHAUST_RUNTIME"] = previous_runtime

            self.assertIn("HERMES_EXHAUST_MODE=active", rewritten)
            self.assertIn("Trigger: /exhaust", rewritten)
            self.assertIn("Task: I need you to summarize the latest video.", rewritten)


if __name__ == "__main__":
    unittest.main()
