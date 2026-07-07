#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import base64
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PLUGIN_ROOT / "server" / "static_server.py"

spec = importlib.util.spec_from_file_location("wasm_agent_static_server", SERVER_PATH)
assert spec and spec.loader
server_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_mod)


class ProviderStubHandler(BaseHTTPRequestHandler):
    status = 200
    body: dict[str, Any] = {
        "model": "stub-model",
        "choices": [{"message": {"content": "wasm-agent-provider-ok"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    response_bodies: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        payload = json.loads(raw or "{}")
        self.__class__.requests.append({
            "path": self.path,
            "authorization": self.headers.get("Authorization", ""),
            "content_type": self.headers.get("Content-Type", ""),
            "payload": payload,
        })
        response_body = self.__class__.response_bodies.pop(0) if self.__class__.response_bodies else self.__class__.body
        if payload.get("stream"):
            choices = response_body.get("choices") if isinstance(response_body.get("choices"), list) else []
            message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
            content = str(message.get("content") or "")
            events = [
                {
                    "choices": [{
                        "delta": {"content": content},
                        "finish_reason": None,
                    }]
                },
                {
                    "choices": [{
                        "delta": {},
                        "finish_reason": "stop",
                    }],
                    "usage": response_body.get("usage"),
                },
            ]
            data = "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode("utf-8") + b"data: [DONE]\n\n"
            self.send_response(self.__class__.status)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        data = json.dumps(response_body).encode("utf-8")
        self.send_response(self.__class__.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ProviderStub:
    def __enter__(self) -> "ProviderStub":
        ProviderStubHandler.status = 200
        ProviderStubHandler.body = {
            "model": "stub-model",
            "choices": [{"message": {"content": "wasm-agent-provider-ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        ProviderStubHandler.response_bodies = []
        ProviderStubHandler.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ProviderStubHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class OpenAIResponsesStubHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    delay_before_body_sec: float = 0

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        payload = json.loads(raw or "{}")
        self.__class__.requests.append({
            "path": self.path,
            "authorization": self.headers.get("Authorization", ""),
            "originator": self.headers.get("originator", ""),
            "chatgpt_account_id": self.headers.get("ChatGPT-Account-ID", ""),
            "user_agent": self.headers.get("User-Agent", ""),
            "content_type": self.headers.get("Content-Type", ""),
            "payload": payload,
        })
        chunks = []
        for event in self.__class__.events:
            chunks.append(f"data: {json.dumps(event)}\n\n")
        chunks.append("data: [DONE]\n\n")
        data = "".join(chunks).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.__class__.delay_before_body_sec > 0:
            time.sleep(self.__class__.delay_before_body_sec)
        self.wfile.write(data)


class OpenAIResponsesStub:
    def __enter__(self) -> "OpenAIResponsesStub":
        OpenAIResponsesStubHandler.requests = []
        OpenAIResponsesStubHandler.delay_before_body_sec = 0
        OpenAIResponsesStubHandler.events = [
            {"type": "response.output_text.delta", "delta": "Hello "},
            {"type": "response.output_text.delta", "delta": "from OpenAI"},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_test",
                    "status": "completed",
                    "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
                    "output": [],
                },
            },
        ]
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), OpenAIResponsesStubHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        return self

    def __exit__(self, *_: object) -> None:
        OpenAIResponsesStubHandler.delay_before_body_sec = 0
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class ProviderProxyTests(unittest.TestCase):
    def user(self) -> dict[str, Any]:
        return {"id": 123, "role": "user", "email": "normal@example.test"}

    def admin(self) -> dict[str, Any]:
        return {"id": 1, "role": "admin", "email": "admin@example.test"}

    def body(self, base_url: str) -> dict[str, Any]:
        return {
            "provider_config": {
                "base_url": base_url,
                "model": "stub-model",
                "api_key": "test-key",
                "provider": "stub",
            },
            "messages": [{"role": "user", "content": "Reply with exactly: wasm-agent-provider-ok"}],
        }

    def codex_token(self, account_id: str = "acct_test") -> str:
        header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode("utf-8")).decode("ascii").rstrip("=")
        payload = base64.urlsafe_b64encode(json.dumps({
            "https://api.openai.com/auth": {"chatgpt_account_id": account_id},
        }).encode("utf-8")).decode("ascii").rstrip("=")
        return f"{header}.{payload}.sig"

    def test_openai_compatible_endpoint_normalization(self) -> None:
        cases = {
            "https://x.com": "https://x.com/v1/chat/completions",
            "https://x.com/": "https://x.com/v1/chat/completions",
            "https://x.com/v1": "https://x.com/v1/chat/completions",
            "https://x.com/v1/": "https://x.com/v1/chat/completions",
            "https://x.com/v1/chat/completions": "https://x.com/v1/chat/completions",
            "https://opencode.ai/zen/go/v1": "https://opencode.ai/zen/go/v1/chat/completions",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                endpoint = server_mod.provider_endpoint_for_base_url(source)
                self.assertEqual(endpoint, expected)
                self.assertNotIn("/v1/v1/", endpoint)

    def test_opencode_go_model_prefix_is_normalized(self) -> None:
        config = server_mod.provider_config_from_body({
            "provider_config": {
                "base_url": "https://opencode.ai/zen/go/v1",
                "model": "opencode-go/kimi-k2.6",
                "api_key": "test-key",
            },
        })
        self.assertEqual(config["provider"], "opencode-go")
        self.assertEqual(config["model"], "kimi-k2.6")

    def test_provider_model_catalog_parses_openrouter_and_opencode(self) -> None:
        self.assertEqual(server_mod.normalize_provider_models_name("OpenCode-Go"), "opencode-go")
        openrouter_models = server_mod.provider_models_from_payload("openrouter", {
            "data": [
                {"id": "anthropic/claude-opus-4.7-fast", "name": "Anthropic: Claude Opus 4.7 (Fast)"},
                {"id": "openrouter/auto", "name": "Auto Router"},
            ],
        })
        self.assertEqual(openrouter_models[0]["id"], "anthropic/claude-opus-4.7-fast")
        self.assertEqual(openrouter_models[0]["label"], "Anthropic: Claude Opus 4.7 (Fast)")
        opencode_models = server_mod.provider_models_from_payload("opencode-go", {
            "data": [
                {"id": "minimax-m2.7", "object": "model"},
                {"id": "kimi-k2.6", "object": "model"},
            ],
        })
        self.assertEqual([model["id"] for model in opencode_models], ["minimax-m2.7", "kimi-k2.6"])

    def test_config_validation_categories(self) -> None:
        failures = [
            ({}, "missing-base-url"),
            ({"provider_config": {"base_url": "not a url", "model": "m", "api_key": "k"}}, "malformed-base-url"),
            ({"provider_config": {"base_url": "https://x.com", "api_key": "k"}}, "missing-model"),
            ({"provider_config": {"base_url": "https://x.com", "model": "m"}}, "missing-api-key"),
        ]
        for body, category in failures:
            with self.subTest(category=category):
                with self.assertRaises(server_mod.ProviderProxyError) as ctx:
                    server_mod.provider_config_from_body(body)
                self.assertEqual(ctx.exception.diagnostic["category"], category)

    def test_provider_error_message_summarizes_html_error_page(self) -> None:
        html = """<!DOCTYPE HTML>
        <html lang="en"><head><title>Error response</title></head>
        <body><h1>Error response</h1><p>Error code: 404</p>
        <p>Message: Endpoint was not found.</p></body></html>"""
        self.assertEqual(server_mod.provider_error_message({}, html), "Endpoint was not found.")
        diagnostic = server_mod.provider_http_diagnostic(
            404,
            server_mod.provider_error_message({}, html),
            endpoint="https://provider.example/responses",
            model="gpt-test",
        )
        self.assertEqual(diagnostic["category"], "model-not-found")
        self.assertEqual(diagnostic["message"], "Endpoint was not found.")
        self.assertNotIn("<html", diagnostic["message"].lower())

    def test_backend_proxy_dispatches_for_normal_user(self) -> None:
        with ProviderStub() as stub:
            result = server_mod.provider_proxy_completion(None, self.body(stub.base_url), user=self.user())
            self.assertEqual(result["mode"], "backend-proxy")
            self.assertEqual(result["category"], "ready")
            self.assertEqual(result["reply"], "wasm-agent-provider-ok")
            self.assertEqual(result["model"], "stub-model")
            request = ProviderStubHandler.requests[-1]
            self.assertEqual(request["path"], "/v1/chat/completions")
            self.assertEqual(request["authorization"], "Bearer test-key")
            self.assertEqual(request["payload"]["model"], "stub-model")
            self.assertFalse(request["payload"]["stream"])

    def test_direct_envelope_dispatches_compact_context(self) -> None:
        with ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Use the direct lane.",
                            "decision": "ship",
                            "actions": [],
                            "state_delta": {},
                            "needs": [],
                            "confidence": 0.91,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }
            body = {
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-direct-1",
                    "objective": "Decide the next Hermes head action.",
                    "compact_state": {
                        "screen": "avatar-chat",
                        "secret_token": "super-secret",
                    },
                    "allowed_actions": [{"id": "answer"}],
                    "budget": {"max_output_tokens": 256},
                },
            }
            result = server_mod.provider_envelope_completion(None, body, user=self.admin())
            self.assertEqual(result["schema"], "hermes.wasm_agent.direct_envelope_result.v1")
            self.assertEqual(result["mode"], "direct-envelope")
            self.assertEqual(result["content_type"], "json")
            self.assertEqual(result["parsed"]["decision"], "ship")
            self.assertEqual(result["envelope"]["trace_id"], "trace-direct-1")
            request = ProviderStubHandler.requests[-1]
            self.assertEqual(request["path"], "/v1/chat/completions")
            self.assertEqual(request["payload"]["max_tokens"], 256)
            self.assertEqual([message["role"] for message in request["payload"]["messages"]], ["system", "user"])
            sent_context = request["payload"]["messages"][1]["content"]
            self.assertIn("ENV agent-envelope-v1", sent_context)
            self.assertIn("OBJ Decide the next Hermes head action.", sent_context)
            self.assertIn('"secret_token":"[redacted]"', sent_context)
            self.assertNotIn("super-secret", sent_context)
            self.assertNotIn("test-key", sent_context)
            self.assertIn("HEAD", sent_context)
            self.assertIn('"provider":"stub"', sent_context)
            self.assertIn('"model":"stub-model"', sent_context)
            self.assertIn('"api_key_present":true', sent_context)
            self.assertLessEqual(result["context_measurement"]["estimated_tokens"], 900)

    def test_direct_envelope_can_use_server_default_provider(self) -> None:
        with ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Server provider wired.",
                            "decision": "answer",
                            "actions": [],
                            "state_delta": {},
                            "needs": [],
                            "confidence": 0.9,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }
            body = {
                "use_server_provider": True,
                "provider_config_source": "server-default",
                "envelope": {
                    "trace_id": "trace-server-provider",
                    "objective": "Use the server-owned direct head provider.",
                    "surface": "avatar-chat",
                    "allowed_actions": [{"id": "answer"}],
                    "budget": {"max_output_tokens": 128},
                },
            }
            env = {
                "HERMES_WASM_AGENT_DIRECT_HEAD_BASE_URL": stub.base_url,
                "HERMES_WASM_AGENT_DIRECT_HEAD_PROVIDER": "stub",
                "HERMES_WASM_AGENT_DIRECT_HEAD_MODEL": "stub-model",
                "HERMES_WASM_AGENT_DIRECT_HEAD_API_KEY": "server-test-key",
            }
            with patch.dict(os.environ, env, clear=False):
                result = server_mod.provider_envelope_completion(None, body, user=self.admin())

            self.assertEqual(result["parsed"]["answer"], "Server provider wired.")
            request = ProviderStubHandler.requests[-1]
            self.assertEqual(request["authorization"], "Bearer server-test-key")
            self.assertEqual(request["payload"]["model"], "stub-model")
            sent_context = request["payload"]["messages"][1]["content"]
            self.assertIn("HEAD", sent_context)
            self.assertIn('"provider":"stub"', sent_context)
            self.assertIn('"model":"stub-model"', sent_context)
            self.assertIn('"api_key_present":true', sent_context)
            self.assertNotIn("server-test-key", sent_context)

    def test_direct_envelope_carries_csc_continuity_and_transcript_read_cache(self) -> None:
        with ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Continuity readable.",
                            "decision": "answer",
                            "actions": [],
                            "state_delta": {},
                            "needs": [],
                            "confidence": 0.9,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }
            body = {
                "provider_config": self.body(stub.base_url)["provider_config"],
                "transcript_cache": {
                    "handle": "ctx://avatar-chat/session/agent_test",
                    "covers": "1..3",
                    "digest": "digest123",
                    "turns": [
                        {"i": 1, "role": "user", "kind": "goal", "anchor": "first_goal", "sha16": "aaa111", "content": "First goal"},
                        {"i": 2, "role": "assistant", "kind": "proof", "anchor": "first_proof", "sha16": "bbb222", "content": "First proof"},
                        {"i": 3, "role": "user", "kind": "question", "anchor": "current_question", "sha16": "ccc333", "content": "What did we decide?"},
                    ],
                },
                "envelope": {
                    "trace_id": "trace-continuity",
                    "objective": "What did we decide earlier?",
                    "surface": "avatar-chat",
                    "compact_state": {
                        "continuity": {
                            "schema": "continuity_protocol.v1",
                            "handle": "ctx://avatar-chat/session/agent_test",
                            "covers": "1..3",
                            "digest": "digest123",
                            "csc": "CSC/1 legend: G=goal D=fact P=decision Q=open R=recall\nTRC/1 cols=i,role,kind,anchor,sha16\n1,u,goal,first_goal,aaa111",
                        }
                    },
                    "allowed_actions": [{"id": "answer"}, {"id": "transcript.read"}],
                    "budget": {"max_output_tokens": 128},
                },
            }
            result = server_mod.provider_envelope_completion(None, body, user=self.admin())

            self.assertEqual(result["parsed"]["answer"], "Continuity readable.")
            sent_context = ProviderStubHandler.requests[-1]["payload"]["messages"][1]["content"]
            self.assertIn("CONT CSC/1", sent_context)
            self.assertIn("TRC/1", sent_context)
            self.assertIn("transcript.read", sent_context)
            self.assertNotIn("First proof", sent_context)

            read = server_mod.transcript_read_tool({
                "transcript_cache": body["transcript_cache"],
                "start": 1,
                "end": 2,
                "format": "full",
            })
            self.assertTrue(read["ok"])
            self.assertEqual(read["turn_count"], 2)
            self.assertEqual(read["turns"][0]["content"], "First goal")
            self.assertEqual(read["proof"]["source"], "request.transcript_cache")

    def test_node_bridge_tools_expose_capabilities_and_chat(self) -> None:
        fake_server = type("FakeServer", (), {"bridge_url": "http://bridge.example"})()

        def fake_bridge_proxy(server, method, path, body, *, timeout=20):
            self.assertEqual(method, "GET")
            self.assertEqual(path, "/nodes/paracelsus")
            return {
                "node": {
                    "id": "paracelsus",
                    "status": "ok",
                    "actions": [{"action": "inspect_node"}, {"action": "tail_logs"}],
                    "activity": {"model": "deepseek-v4-flash"},
                    "hermes": {"api_model": "deepseek-v4-flash", "inference_provider": ""},
                    "raw": {"default_model_provider_env": "opencode-go", "default_model_env": "deepseek-v4-flash"},
                }
            }

        def fake_bridge_runs(*_args, **kwargs):
            self.assertEqual(kwargs["target_node"], "paracelsus")
            self.assertEqual(kwargs["model_id"], "")
            return (
                "Paracelsus answered.",
                "bridge_runs",
                {"total_tokens": 7},
                {"id": "task_node_chat", "steps": []},
            )

        with patch.object(server_mod, "bridge_proxy", side_effect=fake_bridge_proxy), patch.object(server_mod, "call_agent_bridge_runs", side_effect=fake_bridge_runs):
            caps = server_mod.agent_kernel_tool(
                fake_server,
                "/agent/tools/node.capabilities",
                {"node_id": "paracelsus"},
                user=self.admin(),
            )
            chat = server_mod.agent_kernel_tool(
                fake_server,
                "/agent/tools/node.chat",
                {"node_id": "paracelsus", "objective": "What did you do in Discord?"},
                user=self.admin(),
            )

        self.assertTrue(caps["ok"])
        self.assertTrue(caps["can_answer"])
        self.assertEqual(caps["model"]["provider"], "opencode-go")
        self.assertEqual(caps["model"]["model"], "deepseek-v4-flash")
        self.assertEqual(caps["chat_tool"], "node.chat")
        self.assertEqual(chat["reply"], "Paracelsus answered.")
        self.assertEqual(chat["proof"]["model_source"], "node-runtime-default")

    def test_node_scoped_kernel_capabilities_action_routes_to_node_capabilities(self) -> None:
        fake_server = type("FakeServer", (), {"bridge_url": "http://bridge.example"})()

        def fake_bridge_proxy(server, method, path, body, *, timeout=20):
            self.assertEqual(method, "GET")
            self.assertEqual(path, "/nodes/paracelsus")
            return {
                "node": {
                    "id": "paracelsus",
                    "status": "ok",
                    "actions": [{"action": "inspect_node"}, {"action": "run_prompt"}],
                    "provider": "opencode-go",
                    "model": "deepseek-v4-flash",
                }
            }

        action = {
            "action": "kernel.capabilities",
            "args": {
                "node": "paracelsus",
                "route_id": "hermes-node.paracelsus.runtime",
            },
        }
        with patch.object(server_mod, "bridge_proxy", side_effect=fake_bridge_proxy):
            self.assertEqual(server_mod.direct_head_canonical_action_name(action), "node.capabilities")
            results = server_mod.execute_direct_head_local_tool_actions(
                fake_server,
                [action],
                {"route_id": "wasm-agent.avatar-chat.ui"},
                user=self.admin(),
                run_id="run_node_caps_alias",
            )

        self.assertEqual(results[0]["tool"], "node.capabilities")
        self.assertTrue(results[0]["ok"])
        self.assertEqual(results[0]["result"]["node_id"], "paracelsus")
        self.assertEqual(results[0]["result"]["model"]["model"], "deepseek-v4-flash")

    def test_paracelsus_config_uses_opencode_go_deepseek_flash(self) -> None:
        config = (Path("/local/agents/nodes/paracelsus/.hermes/config.yaml")).read_text(encoding="utf-8")
        self.assertIn("provider: opencode-go", config)
        self.assertIn("default: deepseek-v4-flash", config)
        self.assertNotIn("provider: minimax\n", config)
        self.assertNotIn("default: MiniMax-M2.7", config)

    def test_direct_envelope_openai_responses_receiver_streams_raw_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, OpenAIResponsesStub() as stub:
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
                "WASM_AGENT_OPENAI_BASE_URL": stub.base_url,
                "WASM_AGENT_OPENAI_MODEL": "gpt-5.5",
                "OPENAI_API_KEY": "openai-test-key",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "openai-turn",
                "receiver": "openai-responses",
                "envelope": {
                    "trace_id": "trace-openai",
                    "objective": "Answer directly.",
                    "compact_state": {"screen": "avatar-chat", "secret_token": "super-secret"},
                    "allowed_actions": [{"id": "answer"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
                "instructions": "Use the envelope.",
            }
            fake_server = type("FakeServer", (), {})()
            with patch.dict(os.environ, env, clear=True):
                result = server_mod.provider_envelope_run_completion(fake_server, body, user=self.admin())
                duplicate = server_mod.provider_envelope_run_completion(fake_server, body, user=self.admin())
                events = server_mod.read_agent_run_events(self.admin(), result["run_id"])["events"]
                stored = server_mod.read_agent_run(self.admin(), result["run_id"])["run"]["final"]

            self.assertEqual(result["receiver"], "openai-responses")
            self.assertEqual(result["reply"], "Hello from OpenAI")
            self.assertEqual(duplicate["reply"], "Hello from OpenAI")
            self.assertEqual(len(OpenAIResponsesStubHandler.requests), 1)
            self.assertIn('"secret_token":"[redacted]"', result["envelope_text"])
            self.assertNotIn("super-secret", result["envelope_text"])
            self.assertEqual(result["model"], "gpt-5.5")
            request = OpenAIResponsesStubHandler.requests[-1]
            self.assertEqual(request["path"], "/responses")
            self.assertEqual(request["authorization"], "Bearer openai-test-key")
            self.assertTrue(request["payload"]["stream"])
            self.assertEqual(request["payload"]["model"], "gpt-5.5")
            user_input = request["payload"]["input"][1]["content"]
            self.assertIn("RAW true", user_input)
            self.assertIn('"secret_token":"[redacted]"', user_input)
            self.assertIn("kernel.inspect", user_input)
            self.assertNotIn("super-secret", user_input)
            event_types = [event["type"] for event in events]
            self.assertIn("head.delta", event_types)
            self.assertIn("head.decision", event_types)
            self.assertEqual(event_types[-1], "run.final")
            preview_text = json.dumps(stored.get("context_preview", []))
            self.assertIn("[redacted]", preview_text)
            self.assertNotIn("super-secret", preview_text)

    def test_direct_envelope_openai_codex_receiver_uses_chatgpt_oauth_auth_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, OpenAIResponsesStub() as stub:
            root = Path(tmp)
            token = self.codex_token("acct_from_jwt")
            auth_json = root / "auth.json"
            auth_json.write_text(json.dumps({
                "providers": {
                    "openai-codex": {
                        "tokens": {"access_token": token}
                    }
                }
            }), encoding="utf-8")
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(root / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
                "WASM_AGENT_CODEX_BASE_URL": f"{stub.base_url}/responses",
                "WASM_AGENT_CODEX_MODEL": "gpt-5.5",
                "WASM_AGENT_CODEX_AUTH_JSON": str(auth_json),
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "codex-turn",
                "receiver": "openai-codex",
                "envelope": {
                    "trace_id": "trace-codex",
                    "objective": "Answer through ChatGPT subscription auth.",
                    "surface": "avatar-chat",
                    "allowed_actions": [{"id": "answer"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
                "instructions": "Use the envelope.",
            }
            fake_server = type("FakeServer", (), {})()
            with patch.dict(os.environ, env, clear=True):
                result = server_mod.provider_envelope_run_completion(fake_server, body, user=self.admin())
                events = server_mod.read_agent_run_events(self.admin(), result["run_id"])["events"]

            self.assertEqual(result["receiver"], "openai-codex")
            self.assertEqual(result["provider"], "openai-codex")
            self.assertEqual(result["reply"], "Hello from OpenAI")
            self.assertEqual(result["credential_source"], str(auth_json))
            request = OpenAIResponsesStubHandler.requests[-1]
            self.assertEqual(request["path"], "/responses")
            self.assertEqual(request["authorization"], f"Bearer {token}")
            self.assertEqual(request["originator"], "codex_cli_rs")
            self.assertEqual(request["chatgpt_account_id"], "acct_from_jwt")
            self.assertIn("codex_cli_rs", request["user_agent"])
            self.assertEqual(request["payload"]["model"], "gpt-5.5")
            self.assertIs(request["payload"]["store"], False)
            self.assertNotIn("metadata", request["payload"])
            self.assertNotIn("max_output_tokens", request["payload"])
            self.assertIn("RECEIVER openai-codex", request["payload"]["input"][1]["content"])
            event_types = [event["type"] for event in events]
            self.assertIn("head.delta", event_types)
            self.assertIn("head.decision", event_types)
            self.assertEqual(event_types[-1], "run.final")

    def test_direct_envelope_openai_codex_missing_token_is_typed_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "HOME": tmp,
                "HERMES_WASM_AGENT_ENV_PATH": str(Path(tmp) / "empty-wa.env"),
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
                "WASM_AGENT_CODEX_BASE_URL": "https://chatgpt.example/backend-api/codex",
                "WASM_AGENT_CODEX_MODEL": "gpt-5.5",
            }
            body = {
                "receiver": "openai-codex",
                "envelope": {
                    "trace_id": "trace-codex-missing",
                    "objective": "Require Codex OAuth.",
                    "surface": "avatar-chat",
                    "allowed_actions": [{"id": "answer"}],
                },
            }
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(server_mod.ProviderProxyError) as ctx:
                    server_mod.provider_envelope_completion(None, body, user=self.admin())
            self.assertEqual(ctx.exception.diagnostic["mode"], "config-missing")
            self.assertEqual(ctx.exception.diagnostic["category"], "missing-codex-oauth")

    def test_direct_envelope_openai_responses_worker_streams_replayable_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, OpenAIResponsesStub() as stub:
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
                "WASM_AGENT_OPENAI_BASE_URL": stub.base_url,
                "WASM_AGENT_OPENAI_MODEL": "gpt-5.5",
                "OPENAI_API_KEY": "openai-test-key",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "openai-worker-turn",
                "receiver": "openai-responses",
                "envelope": {
                    "trace_id": "trace-openai-worker",
                    "objective": "Answer directly from a worker.",
                    "surface": "avatar-chat",
                    "allowed_actions": [{"id": "answer"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
                "instructions": "Use the envelope.",
            }
            fake_server = type("FakeServer", (), {})()
            with patch.dict(os.environ, env, clear=True):
                context = server_mod.provider_envelope_run_context(body)
                run, created = server_mod.begin_agent_run(fake_server, dict(context["run_body"]), user=self.admin(), direct_head=True)
                started = server_mod.start_provider_envelope_run_worker(fake_server, body, user=self.admin(), run=run, context=context)
                final = server_mod.wait_for_agent_run_terminal(self.admin(), run["run_id"], timeout_sec=5)
                events = server_mod.read_agent_run_events(self.admin(), run["run_id"])["events"]
                stream_payloads = [
                    server_mod.agent_run_event_stream_payload(fake_server, event, user=self.admin())
                    for event in events
                ]

            self.assertTrue(created)
            self.assertTrue(started)
            self.assertEqual(final["reply"], "Hello from OpenAI")
            self.assertEqual(len(OpenAIResponsesStubHandler.requests), 1)
            self.assertIn("head.delta", [event["type"] for event in events])
            deltas = [payload for payload in stream_payloads if payload and payload.get("type") == "delta"]
            self.assertEqual("".join(delta["delta"] for delta in deltas), "Hello from OpenAI")

    def test_openai_responses_direct_head_can_dispatch_hermes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, OpenAIResponsesStub() as stub:
            decision = json.dumps({
                "answer": "Dispatch Hermes.",
                "decision": "dispatch.hermes",
                "actions": [{
                    "action": "dispatch.hermes",
                    "role": "subagent_harness",
                    "objective": "Inspect compact refs from OpenAI direct head.",
                    "caps": ["repo.read", "proof.report"],
                    "escalation_reason": "OpenAI head needs Hermes bridge proof for a capability outside local deterministic lookup.",
                    "refs": ["ctx://repo/map"],
                    "proof": ["summary"],
                    "target_node": "frontier",
                    "stream": True,
                }],
                "state_delta": {},
                "needs": [],
                "confidence": 0.86,
            })
            OpenAIResponsesStubHandler.events = [
                {"type": "response.output_text.delta", "delta": decision},
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_dispatch",
                        "status": "completed",
                        "usage": {"input_tokens": 14, "output_tokens": 6, "total_tokens": 20},
                        "output": [],
                    },
                },
            ]
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
                "WASM_AGENT_OPENAI_BASE_URL": stub.base_url,
                "WASM_AGENT_OPENAI_MODEL": "gpt-5.5",
                "OPENAI_API_KEY": "openai-test-key",
            }
            server = type("FakeServer", (), {"bridge_url": "http://bridge.example"})()
            body = {
                "session_id": "direct-session",
                "turn_id": "openai-dispatch-turn",
                "receiver": "openai-responses",
                "envelope": {
                    "trace_id": "trace-openai-dispatch",
                    "objective": "Use Hermes only for this bounded proof work.",
                    "surface": "avatar-chat",
                    "capabilities": ["repo.read", "proof.report"],
                    "allowed_actions": [{"id": "answer"}, {"id": "dispatch.hermes"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
                "instructions": "Use the envelope.",
            }

            def fake_bridge_runs(*_args, **kwargs):
                action_callback = kwargs.get("action_callback")
                if action_callback:
                    action_callback({
                        "id": "bridge_run",
                        "topic": "run-hermes",
                        "kind": "model",
                        "label": "bridge.run.completed",
                        "status": "done",
                        "detail": "completed",
                    })
                return "Hermes handled the OpenAI request.", "bridge_runs", {"total_tokens": 11}, {"id": "run_openai_dispatch", "steps": [], "tool_calls": []}

            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs", side_effect=fake_bridge_runs):
                result = server_mod.provider_envelope_run_completion(server, body, user=self.admin())
                events = server_mod.read_agent_run_events(self.admin(), result["run_id"])["events"]
                stored_run = server_mod.read_agent_run(self.admin(), result["run_id"])["run"]
                stored = stored_run["final"]

            self.assertEqual(result["reply"], "Hermes handled the OpenAI request.")
            self.assertEqual(result["hermes_dispatch"]["source"], "bridge_runs")
            self.assertEqual(result["hermes_dispatch"]["target_node"], "orchestrator")
            self.assertLessEqual(result["context_measurement"]["estimated_tokens"], 900)
            self.assertLessEqual(result["hermes_dispatch"]["context_measurement"]["estimated_tokens"], 1500)
            request = OpenAIResponsesStubHandler.requests[-1]
            self.assertIn("RAW true", request["payload"]["input"][1]["content"])
            event_types = [event["type"] for event in events]
            self.assertIn("head.delta", event_types)
            self.assertIn("route.resolved", event_types)
            self.assertIn("head.decision", event_types)
            self.assertIn("hermes.dispatch", event_types)
            self.assertIn("hermes.progress", event_types)
            self.assertIn("tokens.used", event_types)
            self.assertEqual(event_types[-1], "run.final")
            token_event = next(event for event in events if event["type"] == "tokens.used")
            self.assertEqual(token_event["payload"]["usage"]["total_tokens"], 31)
            self.assertEqual(token_event["payload"]["primary"], "total")
            self.assertEqual(token_event["payload"]["components"]["head"]["total_tokens"], 20)
            self.assertEqual(token_event["payload"]["components"]["bridge"]["total_tokens"], 11)
            ledger = stored_run["token_ledger"]
            self.assertEqual(ledger["provider_call_count"], 2)
            self.assertTrue(ledger["exact"])
            self.assertEqual(ledger["input_tokens"], 14)
            self.assertEqual(ledger["output_tokens"], 6)
            self.assertEqual(ledger["total_tokens"], 31)
            self.assertEqual({call["route_id"] for call in ledger["calls"]}, {"wasm-agent.avatar-chat.ui"})
            self.assertTrue(any(call["raw_usage"].get("input_tokens") == 14 for call in ledger["calls"]))
            self.assertEqual(stored["reply"], "Hermes handled the OpenAI request.")
            self.assertEqual(stored["diagnostics"]["source"], "openai_responses_hermes_dispatch")

    def test_direct_envelope_stream_route_emits_run_delta_and_final(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, OpenAIResponsesStub() as stub:
            root = Path(tmp)
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(root / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
                "WASM_AGENT_OPENAI_BASE_URL": stub.base_url,
                "WASM_AGENT_OPENAI_MODEL": "gpt-5.5",
                "OPENAI_API_KEY": "openai-test-key",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "openai-http-turn",
                "receiver": "openai-responses",
                "envelope": {
                    "trace_id": "trace-openai-http",
                    "objective": "Answer directly through the stream route.",
                    "surface": "avatar-chat",
                    "allowed_actions": [{"id": "answer"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
                "instructions": "Use the envelope.",
            }
            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "authenticated_request_user", return_value=self.admin()):
                server = server_mod.WasmAgentServer(
                    ("127.0.0.1", 0),
                    server_mod.WasmAgentHandler,
                    plugin_root=PLUGIN_ROOT,
                    public_root=PLUGIN_ROOT / "public",
                    state_dir=root / "state",
                    bridge_url="http://127.0.0.1:8790",
                    browser_timeout_sec=1.0,
                )
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    def post_agent_tool(path: str, payload: dict[str, Any]) -> dict[str, Any]:
                        tool_request = Request(
                            f"http://127.0.0.1:{server.server_address[1]}{path}",
                            data=json.dumps(payload).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urlopen(tool_request, timeout=5) as response:
                            return json.loads(response.read().decode("utf-8"))

                    route_resolve = post_agent_tool(
                        "/agent/tools/route.resolve",
                        {
                            "route_id": "wasm-agent.avatar-chat.ui",
                            "surface_hint": "avatar-chat",
                            "objective": "Runtime route proof from avatar-chat.",
                        },
                    )
                    objective_only_route = post_agent_tool(
                        "/agent/tools/route.resolve",
                        {"objective": "Fix the agent timeline and token report UI."},
                    )
                    map_summary = post_agent_tool(
                        "/agent/tools/map.summary",
                        {"route_id": "wasm-agent.avatar-chat.ui"},
                    )
                    lookup_files = post_agent_tool(
                        "/agent/tools/lookup.files",
                        {"route_id": "wasm-agent.avatar-chat.ui", "paths": ["public/index.html"]},
                    )
                    request = Request(
                        f"http://127.0.0.1:{server.server_address[1]}/agent/provider/envelope/stream",
                        data=json.dumps(body).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urlopen(request, timeout=5) as response:
                        self.assertEqual(response.status, 200)
                        self.assertIn("application/x-ndjson", response.headers.get("Content-Type", ""))
                        lines = [
                            json.loads(line)
                            for line in response.read().decode("utf-8").splitlines()
                            if line.strip()
                        ]
                    final_lines = [line for line in lines if isinstance(line, dict) and line.get("type") == "final"]
                    run_id = final_lines[-1]["agent"]["run_id"]
                    list_request = Request(
                        f"http://127.0.0.1:{server.server_address[1]}/agent/runs?session_id=direct-session&limit=20",
                        method="GET",
                    )
                    with urlopen(list_request, timeout=5) as response:
                        listed = json.loads(response.read().decode("utf-8"))
                    discovered_run = next(
                        run
                        for run in listed["runs"]
                        if run["turn_id"] == "openai-http-turn"
                    )
                    cost_status = post_agent_tool(
                        "/agent/tools/cost.status",
                        {"run_id": discovered_run["run_id"]},
                    )
                    replay_request = Request(
                        f"http://127.0.0.1:{server.server_address[1]}/agent/runs/{discovered_run['run_id']}/stream?after_seq=1",
                        method="GET",
                    )
                    with urlopen(replay_request, timeout=5) as response:
                        replay_lines = [
                            json.loads(line)
                            for line in response.read().decode("utf-8").splitlines()
                            if line.strip()
                        ]
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

                object_event_types = [line["type"] for line in lines if isinstance(line, dict)]
                self.assertEqual(object_event_types[-1], "final")
                self.assertEqual("".join(line for line in lines if isinstance(line, str)), "Hello from OpenAI")
                final = final_lines[-1]["agent"]
                self.assertEqual(final["reply"], "Hello from OpenAI")
                self.assertTrue(final["run_id"].startswith("wa_run_"))
                self.assertTrue(final["context_preview"])
                self.assertEqual(discovered_run["run_id"], run_id)
                self.assertEqual(discovered_run["session_id"], "direct-session")
                self.assertEqual(discovered_run["status"], "completed")
                self.assertTrue(discovered_run["direct_head"])
                self.assertEqual(route_resolve["summary"]["route_id"], "wasm-agent.avatar-chat.ui")
                self.assertFalse(objective_only_route["ok"])
                self.assertEqual(objective_only_route["error"]["code"], "route_contract_missing")
                self.assertEqual(map_summary["summary"]["route_id"], "wasm-agent.avatar-chat.ui")
                self.assertEqual(lookup_files["files"][0]["path"], "public/index.html")
                self.assertTrue(lookup_files["files"][0]["sha256"])
                self.assertEqual(cost_status["ledger"]["provider_call_count"], 1)
                self.assertTrue(cost_status["ledger"]["exact"])
                self.assertEqual(cost_status["ledger"]["input_tokens"], 10)
                self.assertEqual(cost_status["ledger"]["output_tokens"], 4)
                self.assertEqual(cost_status["ledger"]["total_tokens"], 14)
                self.assertIn("delta", [line["type"] for line in replay_lines])
                self.assertEqual(replay_lines[-1]["type"], "final")
                self.assertEqual(replay_lines[-1]["agent"]["reply"], "Hello from OpenAI")
                events = server_mod.read_agent_run_events(self.admin(), final["run_id"])["events"]
                self.assertIn("head.delta", [event["type"] for event in events])

    def test_cost_status_groups_quest_turn_history_and_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            fake_server = object()
            with patch.dict(os.environ, env, clear=True):
                run_ids = []
                for turn_id, usage in [
                    ("quest-turn-a", {
                        "input_tokens": 8,
                        "output_tokens": 4,
                        "total_tokens": 12,
                        "usage_accuracy": "provider_exact",
                        "usage_scope": "llm_api_call",
                    }),
                    ("quest-turn-b", {
                        "input_tokens": 3,
                        "output_tokens": 2,
                        "total_tokens": 5,
                        "usage_accuracy": "estimated",
                        "usage_scope": "llm_api_call",
                    }),
                ]:
                    run, _created = server_mod.begin_agent_run(
                        fake_server,
                        {
                            "session_id": "quest-history",
                            "turn_id": turn_id,
                            "message": f"ledger history {turn_id}",
                            "mode": "direct-head",
                            "target_node": "direct-head",
                        },
                        user=self.admin(),
                        direct_head=True,
                    )
                    run_ids.append(run["run_id"])
                    server_mod.persist_agent_run_token_ledger(
                        fake_server,
                        run["run_id"],
                        {"route_id": "wasm-agent.avatar-chat.ui"},
                        {"components": {"head": usage}},
                    )

                quest = server_mod.agent_kernel_tool(
                    fake_server,
                    "/agent/tools/cost.status",
                    {"quest_id": "quest-history"},
                    user=self.admin(),
                )["ledger"]
                turn_a = server_mod.agent_kernel_tool(
                    fake_server,
                    "/agent/tools/cost.status",
                    {"quest_id": "quest-history", "turn_id": "quest-turn-a"},
                    user=self.admin(),
                )["ledger"]
                turn_b = server_mod.agent_kernel_tool(
                    fake_server,
                    "/agent/tools/cost.status",
                    {"turn_id": "quest-turn-b"},
                    user=self.admin(),
                )["ledger"]
                run_a = server_mod.agent_kernel_tool(
                    fake_server,
                    "/agent/tools/cost.status",
                    {"run_id": run_ids[0]},
                    user=self.admin(),
                )["ledger"]
                exact_only = server_mod.agent_kernel_tool(
                    fake_server,
                    "/agent/tools/cost.status",
                    {"quest_id": "quest-history", "exact_only": True},
                    user=self.admin(),
                )["ledger"]

            self.assertEqual(quest["quest_id"], "quest-history")
            self.assertEqual(quest["provider_call_count"], 2)
            self.assertEqual(quest["exact_provider_call_count"], 1)
            self.assertFalse(quest["exact"])
            self.assertEqual(quest["input_tokens"], 8)
            self.assertEqual(quest["output_tokens"], 4)
            self.assertEqual(quest["total_tokens"], 12)
            self.assertEqual(quest["estimated_input_tokens"], 3)
            self.assertEqual(quest["estimated_output_tokens"], 2)
            self.assertEqual(quest["estimated_total_tokens"], 5)
            self.assertEqual(quest["turn_count"], 2)
            self.assertEqual([turn["turn_id"] for turn in quest["turns"]], ["quest-turn-a", "quest-turn-b"])
            self.assertEqual(quest["turns"][0]["provider_calls"][0]["route_id"], "wasm-agent.avatar-chat.ui")
            self.assertTrue(quest["turns"][0]["provider_calls"][0]["provider_call_id"].startswith("pc_"))
            self.assertEqual(quest["turns"][0]["total_tokens"], 12)
            self.assertEqual(quest["turns"][1]["total_tokens"], 0)
            self.assertEqual(quest["turns"][1]["estimated_total_tokens"], 5)
            self.assertEqual(turn_a["provider_call_count"], 1)
            self.assertEqual(turn_a["turn_count"], 1)
            self.assertEqual(turn_a["total_tokens"], 12)
            self.assertEqual(turn_b["provider_call_count"], 1)
            self.assertFalse(turn_b["exact"])
            self.assertEqual(turn_b["estimated_total_tokens"], 5)
            self.assertEqual(run_a["run_id"], run_ids[0])
            self.assertEqual(run_a["turns"][0]["turn_id"], "quest-turn-a")
            self.assertEqual(exact_only["provider_call_count"], 1)
            self.assertEqual(exact_only["turn_count"], 1)
            self.assertEqual(exact_only["turns"][0]["turn_id"], "quest-turn-a")
            self.assertEqual(exact_only["estimated_total_tokens"], None)

    def test_agent_kernel_local_tools_are_route_scoped_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            route_root = root / "route"
            route_root.mkdir()
            source_path = route_root / "app.py"
            source_path.write_text("alpha = 1\napi_key = 'secret'\nomega = 3\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=route_root, check=True, capture_output=True)
            subprocess.run(["git", "add", "app.py"], cwd=route_root, check=True, capture_output=True)
            subprocess.run(
                ["git", "-c", "user.name=test", "-c", "user.email=test@example.test", "commit", "-m", "init"],
                cwd=route_root,
                check=True,
                capture_output=True,
            )
            registry = root / "routes.json"
            registry.write_text(json.dumps({
                "schema": "hermes.wasm_agent.route_contracts.v1",
                "routes": [{
                    "route_id": "test.local.tools",
                    "surface": "local-tools",
                    "owner": "test",
                    "workspace_root": str(route_root),
                    "allowed_read_roots": [str(route_root)],
                    "allowed_write_roots": [str(route_root)],
                    "likely_paths": ["app.py"],
                    "lookup_handles": ["route.files", "route.symbols", "route.tests"],
                    "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
                    "provider_policy": {"default": "local-first", "hermes": "bounded-skill-only"},
                    "budget": {"head_tokens_max": 100, "provider_tokens_max": 200, "api_calls_max": 2},
                    "proof": ["route_id", "changed_files", "checks", "token_ledger"],
                    "checks": [{
                        "id": "python-inline",
                        "command": ["python3", "-c", "print('focused-ok')"],
                        "timeout_sec": 10,
                        "description": "inline focused test",
                    }],
                }],
            }), encoding="utf-8")
            env = {
                "WASM_AGENT_ROUTE_CONTRACTS_PATH": str(registry),
                "HERMES_WASM_AGENT_DB_PATH": str(root / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            fake_server = object()
            with patch.dict(os.environ, env, clear=True):
                resolved = server_mod.agent_kernel_tool(fake_server, "/agent/tools/route.resolve", {"route_id": "test.local.tools"}, user=self.admin())
                files = server_mod.agent_kernel_tool(fake_server, "/agent/tools/lookup.files", {"route_id": "test.local.tools"}, user=self.admin())
                read = server_mod.agent_kernel_tool(
                    fake_server,
                    "/agent/tools/file.read_bounded",
                    {"route_id": "test.local.tools", "path": "app.py", "max_bytes": 80},
                    user=self.admin(),
                )
                symbol = server_mod.agent_kernel_tool(
                    fake_server,
                    "/agent/tools/lookup.symbol",
                    {"route_id": "test.local.tools", "query": "alpha"},
                    user=self.admin(),
                )
                patched = server_mod.agent_kernel_tool(
                    fake_server,
                    "/agent/tools/patch.apply_scoped",
                    {
                        "route_id": "test.local.tools",
                        "patch": {"operations": [{"op": "replace", "path": "app.py", "find": "omega = 3", "replace": "omega = 4"}]},
                    },
                    user=self.admin(),
                )
                focused = server_mod.agent_kernel_tool(
                    fake_server,
                    "/agent/tools/test.run_focused",
                    {"route_id": "test.local.tools", "check_id": "python-inline"},
                    user=self.admin(),
                )
                diff = server_mod.agent_kernel_tool(
                    fake_server,
                    "/agent/tools/git.diff_summary",
                    {"route_id": "test.local.tools"},
                    user=self.admin(),
                )
                with patch.object(server_mod.master_frontier_code_memory.shutil, "which", return_value=None):
                    code_memory = server_mod.agent_kernel_tool(
                        fake_server,
                        "/agent/tools/code.memory.search",
                        {"route_id": "test.local.tools", "query": "alpha"},
                        user=self.admin(),
                    )
                with self.assertRaises(server_mod.BrowserError) as denied_read:
                    server_mod.agent_kernel_tool(fake_server, "/agent/tools/file.read_bounded", {"route_id": "test.local.tools", "path": "../outside.txt"}, user=self.admin())
                with self.assertRaises(server_mod.BrowserError) as denied_patch:
                    server_mod.agent_kernel_tool(
                        fake_server,
                        "/agent/tools/patch.apply_scoped",
                        {"route_id": "test.local.tools", "patch": {"operations": [{"op": "append", "path": "../outside.py", "insert": "x = 1\n"}]}},
                        user=self.admin(),
                    )
                with self.assertRaises(server_mod.BrowserError) as denied_check:
                    server_mod.agent_kernel_tool(fake_server, "/agent/tools/test.run_focused", {"route_id": "test.local.tools", "check_id": "shell"}, user=self.admin())

            self.assertTrue(resolved["ok"])
            self.assertEqual(resolved["route_id"], "test.local.tools")
            self.assertEqual(files["files"][0]["path"], "app.py")
            self.assertTrue(files["files"][0]["sha256"])
            self.assertTrue(read["redacted"])
            self.assertIn("[redacted]", read["text"])
            self.assertEqual(symbol["matches"][0]["path"], "app.py")
            self.assertTrue(patched["applied"])
            self.assertEqual(patched["changed_files"], ["app.py"])
            self.assertIn("omega = 4", source_path.read_text(encoding="utf-8"))
            self.assertTrue(focused["ok"])
            self.assertIn("focused-ok", focused["stdout"])
            self.assertEqual(diff["changed_files"][0]["path"], "app.py")
            self.assertFalse(code_memory["ok"])
            self.assertEqual(code_memory["code"], "code_memory_unavailable")
            self.assertEqual(code_memory["route_id"], "test.local.tools")
            self.assertEqual(denied_read.exception.code, "route_path_invalid")
            self.assertEqual(denied_patch.exception.code, "route_path_invalid")
            self.assertEqual(denied_check.exception.code, "test_check_not_registered")

    def test_proof_collect_and_hermes_tools_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "routes.json"
            registry.write_text(json.dumps({
                "schema": "hermes.wasm_agent.route_contracts.v1",
                "routes": [{
                    "route_id": "test.hermes.tools",
                    "surface": "hermes-tools",
                    "owner": "test",
                    "workspace_root": str(root),
                    "allowed_read_roots": [str(root)],
                    "allowed_write_roots": [str(root)],
                    "likely_paths": [],
                    "lookup_handles": ["cost.status", "run.timeline"],
                    "caps": ["repo.read", "proof.report"],
                    "provider_policy": {"default": "local-first", "hermes": "bounded-skill-only"},
                    "budget": {"provider_tokens_max": 200, "api_calls_max": 2},
                    "proof": ["route_id", "checks", "token_ledger"],
                }],
            }), encoding="utf-8")
            env = {
                "WASM_AGENT_ROUTE_CONTRACTS_PATH": str(registry),
                "HERMES_WASM_AGENT_DB_PATH": str(root / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            fake_server = type("FakeServer", (), {"bridge_url": "http://bridge.example"})()

            def fake_bridge_runs(*_args, **kwargs):
                self.assertEqual(kwargs.get("run_options", {}).get("workspace_root"), str(root.resolve()))
                return "Hermes bounded result.", "bridge_runs", {"total_tokens": 6}, {"id": "run_tool", "steps": [], "tool_calls": []}

            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs", side_effect=fake_bridge_runs) as bridge:
                run, _created = server_mod.begin_agent_run(
                    fake_server,
                    {
                        "session_id": "proof-quest",
                        "turn_id": "proof-turn",
                        "message": "proof run",
                        "mode": "direct-head",
                        "target_node": "direct-head",
                    },
                    user=self.admin(),
                    direct_head=True,
                )
                server_mod.append_agent_run_event(fake_server, run["run_id"], "route.resolved", summary="resolved", payload={"route_id": "test.hermes.tools"})
                server_mod.persist_agent_run_token_ledger(
                    fake_server,
                    run["run_id"],
                    {"route_id": "test.hermes.tools"},
                    {"components": {"head": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3, "usage_accuracy": "provider_exact"}}},
                )
                proof = server_mod.agent_kernel_tool(fake_server, "/agent/tools/proof.collect", {"run_id": run["run_id"]}, user=self.admin())
                caps = server_mod.agent_kernel_tool(
                    fake_server,
                    "/agent/tools/hermes.capabilities",
                    {"route_id": "test.hermes.tools", "capability_need": ["repo.read"]},
                    user=self.admin(),
                )
                missing_caps = server_mod.agent_kernel_tool(
                    fake_server,
                    "/agent/tools/hermes.capabilities",
                    {"route_id": "test.hermes.tools", "capability_need": ["root.secret"]},
                    user=self.admin(),
                )
                with self.assertRaises(server_mod.BrowserError) as no_reason:
                    server_mod.agent_kernel_tool(
                        fake_server,
                        "/agent/tools/hermes.dispatch_bounded",
                        {"route_id": "test.hermes.tools", "capability_need": ["repo.read"], "objective": "inspect"},
                        user=self.admin(),
                    )
                dispatch = server_mod.agent_kernel_tool(
                    fake_server,
                    "/agent/tools/hermes.dispatch_bounded",
                    {
                        "route_id": "test.hermes.tools",
                        "run_id": run["run_id"],
                        "task_contract": {
                            "objective": "Inspect only compact proof.",
                            "capability_need": ["repo.read", "proof.report"],
                            "escalation_reason": "local deterministic tools cannot navigate the requested external browser state",
                            "proof": ["summary"],
                            "budget": {"provider_tokens_max": 200, "api_calls_max": 2},
                        },
                    },
                    user=self.admin(),
                )

            self.assertEqual(proof["event_count"], 3)
            self.assertIn("tool.started", [event["type"] for event in proof["events"]])
            self.assertEqual(proof["token_ledger"]["total_tokens"], 3)
            self.assertTrue(caps["ok"])
            self.assertFalse(missing_caps["ok"])
            self.assertEqual(missing_caps["code"], "capability_missing")
            self.assertEqual(no_reason.exception.code, "hermes_escalation_missing")
            self.assertTrue(dispatch["ok"])
            self.assertTrue(dispatch["last_resort"])
            self.assertEqual(dispatch["route_id"], "test.hermes.tools")
            bridge.assert_called_once()

    def test_direct_envelope_stream_disconnect_does_not_cancel_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, OpenAIResponsesStub() as stub:
            OpenAIResponsesStubHandler.delay_before_body_sec = 0.2
            root = Path(tmp)
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(root / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
                "WASM_AGENT_OPENAI_BASE_URL": stub.base_url,
                "WASM_AGENT_OPENAI_MODEL": "gpt-5.5",
                "OPENAI_API_KEY": "openai-test-key",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "openai-http-disconnect",
                "receiver": "openai-responses",
                "envelope": {
                    "trace_id": "trace-openai-disconnect",
                    "objective": "Keep running after the stream subscriber disconnects.",
                    "surface": "avatar-chat",
                    "allowed_actions": [{"id": "answer"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
                "instructions": "Use the envelope.",
            }
            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "authenticated_request_user", return_value=self.admin()):
                server = server_mod.WasmAgentServer(
                    ("127.0.0.1", 0),
                    server_mod.WasmAgentHandler,
                    plugin_root=PLUGIN_ROOT,
                    public_root=PLUGIN_ROOT / "public",
                    state_dir=root / "state",
                    bridge_url="http://127.0.0.1:8790",
                    browser_timeout_sec=1.0,
                )
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    request = Request(
                        f"http://127.0.0.1:{server.server_address[1]}/agent/provider/envelope/stream",
                        data=json.dumps(body).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    response = urlopen(request, timeout=5)
                    try:
                        first_line = json.loads(response.readline().decode("utf-8"))
                        runs = server_mod.list_agent_runs(self.admin(), {"session_id": ["direct-session"]})["runs"]
                        run_id = next(run["run_id"] for run in runs if run["turn_id"] == "openai-http-disconnect")
                    finally:
                        response.close()
                    final = server_mod.wait_for_agent_run_terminal(self.admin(), run_id, timeout_sec=5)
                    events = server_mod.read_agent_run_events(self.admin(), run_id)["events"]
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

            self.assertIsInstance(first_line, dict)
            self.assertIn(first_line.get("type"), {"action", "run", "delta"})
            self.assertEqual(final["reply"], "Hello from OpenAI")
            self.assertEqual(len(OpenAIResponsesStubHandler.requests), 1)
            event_types = [event["type"] for event in events]
            self.assertIn("head.delta", event_types)
            self.assertEqual(event_types[-1], "run.final")

    def test_direct_envelope_stream_route_is_admin_only(self) -> None:
        body = {
            "session_id": "direct-session",
            "turn_id": "openai-http-denied",
            "receiver": "openai-responses",
            "envelope": {
                "trace_id": "trace-openai-denied",
                "objective": "This should be denied.",
                "allowed_actions": [{"id": "answer"}],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(root / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
                "OPENAI_API_KEY": "openai-test-key",
            }
            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "authenticated_request_user", return_value=self.user()):
                server = server_mod.WasmAgentServer(
                    ("127.0.0.1", 0),
                    server_mod.WasmAgentHandler,
                    plugin_root=PLUGIN_ROOT,
                    public_root=PLUGIN_ROOT / "public",
                    state_dir=root / "state",
                    bridge_url="http://127.0.0.1:8790",
                    browser_timeout_sec=1.0,
                )
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    request = Request(
                        f"http://127.0.0.1:{server.server_address[1]}/agent/provider/envelope/stream",
                        data=json.dumps(body).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with self.assertRaises(HTTPError) as raised:
                        urlopen(request, timeout=5)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

            self.assertEqual(raised.exception.code, 403)

    def test_direct_head_run_replay_routes_are_admin_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(root / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            auth_user = {"value": self.admin()}

            def fake_auth(_handler):
                return auth_user["value"]

            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "authenticated_request_user", side_effect=fake_auth):
                server = server_mod.WasmAgentServer(
                    ("127.0.0.1", 0),
                    server_mod.WasmAgentHandler,
                    plugin_root=PLUGIN_ROOT,
                    public_root=PLUGIN_ROOT / "public",
                    state_dir=root / "state",
                    bridge_url="http://127.0.0.1:8790",
                    browser_timeout_sec=1.0,
                )
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    run, _created = server_mod.begin_agent_run(
                        server,
                        {
                            "session_id": "direct-session",
                            "turn_id": "direct-http-replay-denied",
                            "message": "Direct head private trace",
                            "mode": "direct-head",
                            "target_node": "direct-head",
                        },
                        user=self.admin(),
                        direct_head=True,
                    )
                    auth_user["value"] = {"id": 1, "role": "user", "email": "normal@example.test"}
                    with self.assertRaises(HTTPError) as read_denied:
                        urlopen(f"http://127.0.0.1:{server.server_address[1]}/agent/runs/{run['run_id']}", timeout=5)
                    with self.assertRaises(HTTPError) as stream_denied:
                        urlopen(f"http://127.0.0.1:{server.server_address[1]}/agent/runs/{run['run_id']}/stream", timeout=5)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

            self.assertEqual(read_denied.exception.code, 403)
            self.assertEqual(stream_denied.exception.code, 403)

    def test_direct_envelope_openai_responses_receiver_can_read_wa_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, OpenAIResponsesStub() as stub:
            env_path = Path(tmp) / "wa.env"
            env_path.write_text(
                "\n".join([
                    "WASM_AGENT_MASTER_FRONTIER_RECEIVER=openai-responses",
                    "WASM_AGENT_OPENAI_BASE_URL=" + stub.base_url,
                    "WASM_AGENT_OPENAI_MODEL=gpt-5.5",
                    "OPENAI_API_KEY=openai-env-key",
                ]),
                encoding="utf-8",
            )
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
                "HERMES_WASM_AGENT_ENV_PATH": str(env_path),
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "openai-env-turn",
                "envelope": {
                    "trace_id": "trace-openai-env",
                    "objective": "Answer through the wa.env receiver.",
                    "surface": "avatar-chat",
                    "allowed_actions": [{"id": "answer"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
                "instructions": "Use the envelope.",
            }
            with patch.dict(os.environ, env, clear=True):
                result = server_mod.provider_envelope_run_completion(object(), body, user=self.admin())

            self.assertEqual(result["receiver"], "openai-responses")
            self.assertEqual(result["reply"], "Hello from OpenAI")
            request = OpenAIResponsesStubHandler.requests[-1]
            self.assertEqual(request["path"], "/responses")
            self.assertEqual(request["authorization"], "Bearer openai-env-key")
            self.assertEqual(request["payload"]["model"], "gpt-5.5")

    def test_server_default_provider_can_read_wa_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "wa.env"
            env_path.write_text(
                "\n".join([
                    "HERMES_WASM_AGENT_DIRECT_HEAD_BASE_URL=https://provider.example/v1",
                    "HERMES_WASM_AGENT_DIRECT_HEAD_PROVIDER=stub",
                    "HERMES_WASM_AGENT_DIRECT_HEAD_MODEL=stub-model",
                    "HERMES_WASM_AGENT_DIRECT_HEAD_API_KEY=server-env-key",
                ]),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"HERMES_WASM_AGENT_ENV_PATH": str(env_path)}, clear=True):
                config = server_mod.server_default_provider_proxy_config()

            self.assertEqual(config["base_url"], "https://provider.example/v1")
            self.assertEqual(config["provider"], "stub")
            self.assertEqual(config["model"], "stub-model")
            self.assertEqual(config["api_key"], "server-env-key")

    def test_direct_envelope_route_wrapper_records_replayable_run_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Dispatch is not needed.",
                            "decision": "answer",
                            "actions": [],
                            "state_delta": {},
                            "needs": [],
                            "confidence": 0.8,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-turn",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-direct-run",
                    "objective": "Answer directly.",
                    "surface": "avatar-chat",
                    "capabilities": ["answer"],
                    "allowed_actions": [{"id": "answer"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }
            fake_server = object()
            with patch.dict(os.environ, env, clear=True):
                result = server_mod.provider_envelope_run_completion(fake_server, body, user=self.admin())

                self.assertTrue(result["run_id"].startswith("wa_run_"))
                events = server_mod.read_agent_run_events(self.admin(), result["run_id"])["events"]
                event_types = [event["type"] for event in events]
                self.assertEqual(event_types[0], "run.started")
                self.assertIn("envelope.created", event_types)
                self.assertIn("route.resolved", event_types)
                self.assertIn("head.started", event_types)
                self.assertIn("head.decision", event_types)
                self.assertEqual(event_types[-1], "run.final")
                stored_run = server_mod.read_agent_run(self.admin(), result["run_id"])["run"]
                self.assertEqual(stored_run["token_ledger"]["provider_call_count"], 1)
                self.assertEqual(stored_run["token_ledger"]["total_tokens"], 5)
                self.assertTrue(all(event["redacted"] for event in events))

    def test_direct_head_can_execute_local_tool_action_without_hermes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Used local lookup.",
                            "decision": "local-tool",
                            "actions": [{
                                "action": "lookup.files",
                                "args": {
                                    "route_id": "wasm-agent.avatar-chat.ui",
                                    "paths": ["public/index.html"],
                                },
                            }],
                            "state_delta": {},
                            "needs": [],
                            "confidence": 0.9,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-local-tool",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-local-tool",
                    "objective": "Use local lookup before any bridge provider.",
                    "surface": "avatar-chat",
                    "capabilities": ["repo.read", "proof.report"],
                    "allowed_actions": [{"id": "lookup.files"}, {"id": "answer"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }
            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs") as bridge:
                result = server_mod.provider_envelope_run_completion(object(), body, user=self.admin())
                run = server_mod.read_agent_run(self.admin(), result["run_id"])["run"]
                events = server_mod.read_agent_run_events(self.admin(), result["run_id"])["events"]

            bridge.assert_not_called()
            self.assertEqual(result["reply"], "Used local lookup.")
            self.assertEqual(run["final"]["local_tools"][0]["tool"], "lookup.files")
            self.assertTrue(run["final"]["local_tools"][0]["ok"])
            event_types = [event["type"] for event in events]
            self.assertIn("tool.started", event_types)
            self.assertIn("tool.finished", event_types)
            self.assertLess(event_types.index("tool.finished"), event_types.index("run.final"))

    def test_agent_kernel_primitives_are_generic_local_first_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            route_root = root / "route"
            route_root.mkdir()
            (route_root / "kernel.txt").write_text("alpha kernel proof\n", encoding="utf-8")
            registry = root / "routes.json"
            registry.write_text(json.dumps({
                "schema": "hermes.wasm_agent.route_contracts.v1",
                "routes": [{
                    "route_id": "test.kernel.contract",
                    "surface": "kernel-contract",
                    "owner": "test",
                    "workspace_root": str(route_root),
                    "allowed_read_roots": [str(route_root)],
                    "allowed_write_roots": [str(route_root)],
                    "likely_paths": ["kernel.txt"],
                    "lookup_handles": ["route.files", "route.symbols", "run.timeline", "cost.status"],
                    "caps": ["repo.read", "repo.edit", "test.run", "runtime.inspect", "proof.report"],
                    "provider_policy": {"default": "local-first", "hermes": "bounded-skill-only"},
                    "budget": {"head_tokens_max": 100, "provider_tokens_max": 200, "api_calls_max": 2},
                    "proof": ["route_id", "checks", "token_ledger"],
                    "checks": [{
                        "id": "kernel-inline",
                        "command": ["python3", "-c", "print('kernel-ok')"],
                        "timeout_sec": 10,
                        "description": "kernel focused test",
                    }],
                }],
            }), encoding="utf-8")
            env = {
                "WASM_AGENT_ROUTE_CONTRACTS_PATH": str(registry),
                "HERMES_WASM_AGENT_DB_PATH": str(root / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            fake_server = object()
            with patch.dict(os.environ, env, clear=True):
                run, _created = server_mod.begin_agent_run(
                    fake_server,
                    {
                        "session_id": "kernel-quest",
                        "turn_id": "kernel-turn",
                        "message": "kernel proof",
                        "mode": "direct-head",
                        "target_node": "direct-head",
                    },
                    user=self.admin(),
                    direct_head=True,
                )
                server_mod.persist_agent_run_token_ledger(
                    fake_server,
                    run["run_id"],
                    {"route_id": "test.kernel.contract"},
                    {"components": {"head": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6, "usage_accuracy": "provider_exact"}}},
                )
                caps = server_mod.agent_kernel_tool(
                    fake_server,
                    "/agent/tools/kernel.capabilities",
                    {"route_id": "test.kernel.contract"},
                    user=self.admin(),
                )
                resolved = server_mod.agent_kernel_tool(
                    fake_server,
                    "/agent/tools/kernel.resolve",
                    {"surface": "kernel-contract", "objective": "unknown entity requires local route first"},
                    user=self.admin(),
                )
                inspected = server_mod.agent_kernel_tool(
                    fake_server,
                    "/agent/tools/kernel.inspect",
                    {
                        "route_id": "test.kernel.contract",
                        "inspect": ["map", "files", "symbols", "runtime"],
                        "query": "alpha",
                    },
                    user=self.admin(),
                )
                acted = server_mod.agent_kernel_tool(
                    fake_server,
                    "/agent/tools/kernel.act",
                    {
                        "route_id": "test.kernel.contract",
                        "local_action": "file.read_bounded",
                        "args": {"path": "kernel.txt", "max_bytes": 80},
                    },
                    user=self.admin(),
                )
                proved = server_mod.agent_kernel_tool(
                    fake_server,
                    "/agent/tools/kernel.prove",
                    {"route_id": "test.kernel.contract", "run_id": run["run_id"]},
                    user=self.admin(),
                )
                with self.assertRaises(server_mod.BrowserError) as denied_external:
                    server_mod.agent_kernel_tool(
                        fake_server,
                        "/agent/tools/kernel.act",
                        {"route_id": "test.kernel.contract", "local_action": "hermes.dispatch_bounded"},
                        user=self.admin(),
                    )

            self.assertTrue(caps["manifest"]["local_first"])
            self.assertIn("kernel.inspect", [item["id"] for item in caps["manifest"]["primitives"]])
            self.assertTrue(caps["manifest"]["master_frontier"]["features"]["empty_provider_repair"])
            self.assertTrue(caps["manifest"]["master_frontier"]["features"]["local_evidence_continuation"])
            self.assertIn("head.repair", caps["manifest"]["master_frontier"]["required_event_types"])
            self.assertEqual(resolved["route_id"], "test.kernel.contract")
            self.assertEqual(resolved["root_cause_class"], "route")
            self.assertEqual(inspected["route_id"], "test.kernel.contract")
            self.assertTrue(any(item["kind"] == "files" for item in inspected["observations"]))
            self.assertTrue(any(item["kind"] == "symbols" for item in inspected["observations"]))
            runtime_observation = next(item for item in inspected["observations"] if item["kind"] == "runtime_entity")
            self.assertTrue(runtime_observation["result"]["capabilities"]["runtime_inspect"])
            self.assertGreaterEqual(runtime_observation["result"]["run_count"], 1)
            self.assertEqual(inspected["unknowns"][0]["code"], "entity_not_observed")
            self.assertEqual(inspected["root_cause_class"], "inspected_with_unknowns")
            self.assertEqual(acted["result"]["path"], "kernel.txt")
            cost_proof = next(item for item in proved["proofs"] if item["kind"] == "cost")
            self.assertEqual(cost_proof["result"]["ledger"]["total_tokens"], 6)
            self.assertEqual(denied_external.exception.code, "kernel_external_provider_denied")

    def test_direct_head_can_use_kernel_inspect_for_unknown_state_without_hermes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "I inspected through the local kernel. The route exposes bounded runtime inspection, but this entity was not observed in the available run evidence.",
                            "decision": "kernel.inspect",
                            "actions": [{
                                "action": "kernel.inspect",
                                "args": {
                                    "route_id": "wasm-agent.avatar-chat.ui",
                                    "inspect": ["runtime", "entity"],
                                    "entity": "fixture-unknown-entity",
                                },
                            }],
                            "state_delta": {},
                            "needs": ["entity-specific runtime evidence"],
                            "confidence": 0.72,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-kernel-inspect",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-kernel-inspect",
                    "objective": "Answer an unknown runtime/entity question without guessing.",
                    "surface": "avatar-chat",
                    "capabilities": ["runtime.inspect", "proof.report"],
                    "allowed_actions": [{"id": "answer"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }
            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs") as bridge:
                result = server_mod.provider_envelope_run_completion(object(), body, user=self.admin())
                run = server_mod.read_agent_run(self.admin(), result["run_id"])["run"]
                events = server_mod.read_agent_run_events(self.admin(), result["run_id"])["events"]

            bridge.assert_not_called()
            self.assertEqual(run["final"]["local_tools"][0]["tool"], "kernel.inspect")
            inspect_result = run["final"]["local_tools"][0]["result"]
            runtime_observation = next(item for item in inspect_result["observations"] if item["kind"] == "runtime_entity")
            self.assertTrue(runtime_observation["result"]["capabilities"]["runtime_inspect"])
            self.assertGreaterEqual(runtime_observation["result"]["run_count"], 1)
            self.assertEqual(inspect_result["unknowns"][0]["code"], "entity_not_observed")
            self.assertEqual(run["token_ledger"]["total_tokens"], 10)
            event_types = [event["type"] for event in events]
            self.assertIn("tool.started", event_types)
            self.assertIn("tool.finished", event_types)
            self.assertNotIn("hermes.dispatch", event_types)

    def test_direct_head_runtime_dispatch_uses_local_kernel_preflight_before_hermes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Dispatch Hermes.",
                            "decision": "dispatch.hermes",
                            "actions": [{
                                "action": "dispatch.hermes",
                                "objective": "Inspect the Paracelsus node runtime history.",
                                "caps": ["runtime.inspect", "proof.report"],
                            }],
                            "state_delta": {},
                            "needs": ["Paracelsus runtime proof"],
                            "confidence": 0.65,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-runtime-dispatch-no-inspect",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-runtime-dispatch-no-inspect",
                    "objective": "Tell me about Paracelsus runtime history.",
                    "surface": "avatar-chat",
                    "capabilities": ["runtime.inspect", "proof.report"],
                    "allowed_actions": [{"id": "dispatch.hermes"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }
            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs") as bridge:
                result = server_mod.provider_envelope_run_completion(object(), body, user=self.admin())
                run = server_mod.read_agent_run(self.admin(), result["run_id"])["run"]
                events = server_mod.read_agent_run_events(self.admin(), result["run_id"])["events"]

            bridge.assert_not_called()
            self.assertEqual(run["status"], "completed")
            self.assertIn("Kernel inspection proof", run["final"]["reply"])
            self.assertIn("bootstrapped_at=2026-04-24T21:41:55Z", run["final"]["reply"])
            self.assertIn("tool.finished", [event["type"] for event in events])
            inspect_events = [event for event in events if event["type"] == "tool.finished" and event["summary"].startswith("kernel.inspect")]
            self.assertTrue(any("hermes-node.paracelsus.runtime" in json.dumps(event["payload"], sort_keys=True) for event in inspect_events))
            self.assertNotIn("hermes.dispatch", [event["type"] for event in events])

    def test_direct_head_dispatch_rejects_paths_outside_resolved_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Dispatch Hermes.",
                            "decision": "dispatch.hermes",
                            "actions": [{
                                "action": "dispatch.hermes",
                                "role": "subagent_harness",
                                "objective": "Inspect explicit external path.",
                                "caps": ["repo.read", "proof.report"],
                                "escalation_reason": "Need external filesystem proof.",
                                "scope": {"path": "/local/agents/nodes/paracelsus"},
                            }],
                            "state_delta": {},
                            "needs": [],
                            "confidence": 0.65,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-dispatch-outside-route",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-dispatch-outside-route",
                    "objective": "Use Hermes to inspect explicit external path.",
                    "surface": "avatar-chat",
                    "capabilities": ["repo.read", "proof.report"],
                    "allowed_actions": [{"id": "dispatch.hermes"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }
            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs") as bridge:
                with self.assertRaises(server_mod.ProviderProxyError) as raised:
                    server_mod.provider_envelope_run_completion(object(), body, user=self.admin())

            self.assertEqual(raised.exception.diagnostic["category"], "hermes-route-scope-denied")
            bridge.assert_not_called()

    def test_direct_head_dispatch_uses_explicit_registered_runtime_route_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Dispatch Hermes.",
                            "decision": "dispatch.hermes",
                            "actions": [{
                                "action": "dispatch.hermes",
                                "route_id": "hermes-node.paracelsus.runtime",
                                "role": "subagent_harness",
                                "objective": "Inspect the Paracelsus node workspace.",
                                "caps": ["repo.read", "runtime.inspect", "proof.report"],
                                "escalation_reason": "The action explicitly selected the declared Paracelsus runtime route.",
                                "refs": ["ctx://avatar-chat/session/test", "hermes-node.paracelsus.runtime"],
                                "proof": [
                                    "route_id=hermes-node.paracelsus.runtime",
                                    "workspace_root=/local/agents/nodes/paracelsus",
                                ],
                            }],
                            "state_delta": {},
                            "needs": [],
                            "confidence": 0.75,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-dispatch-runtime-route-scope",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-dispatch-runtime-route-scope",
                    "objective": "Use Hermes with the declared Paracelsus runtime route.",
                    "surface": "avatar-chat",
                    "capabilities": ["repo.read", "runtime.inspect", "proof.report"],
                    "allowed_actions": [{"id": "dispatch.hermes"}, {"id": "kernel.inspect"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }

            def fake_bridge_runs(*_args, **kwargs):
                self.assertEqual(kwargs["run_options"]["workspace_root"], "/local/agents/nodes/paracelsus")
                return "Runtime route dispatch handled.", "bridge_runs", {"total_tokens": 11}, {"id": "run_runtime_route", "steps": []}

            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs", side_effect=fake_bridge_runs) as bridge:
                result = server_mod.provider_envelope_run_completion(object(), body, user=self.admin())

            self.assertEqual(result["reply"], "Runtime route dispatch handled.")
            self.assertEqual(result["hermes_dispatch"]["workspace"]["route_id"], "hermes-node.paracelsus.runtime")
            bridge.assert_called_once()

    def test_direct_head_dispatch_path_scope_wins_over_runtime_route_proof_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Dispatch Hermes.",
                            "decision": "dispatch.hermes",
                            "actions": [{
                                "action": "dispatch.hermes",
                                "role": "subagent_harness",
                                "objective": "Inspect /local/plugins/wasm-agent repo structure and Paracelsus runtime.",
                                "caps": ["repo.read", "runtime.inspect", "proof.report"],
                                "escalation_reason": "User requested concrete inspection across the owned repo and runtime evidence.",
                                "refs": ["ctx://avatar-chat/session/test"],
                                "proof": [
                                    "route_id:hermes-node.paracelsus.runtime",
                                    "workspace_root:/local/plugins/wasm-agent",
                                ],
                            }],
                            "state_delta": {},
                            "needs": [],
                            "confidence": 0.75,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-dispatch-path-over-runtime-proof",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-dispatch-path-over-runtime-proof",
                    "objective": "Use Hermes with the owned repo route and runtime proof hints.",
                    "surface": "avatar-chat",
                    "capabilities": ["repo.read", "runtime.inspect", "proof.report"],
                    "runtime_entity_routes": [{
                        "route_id": "hermes-node.paracelsus.runtime",
                        "workspace_root": "/local/agents/nodes/paracelsus",
                        "caps": ["runtime.inspect", "proof.report"],
                    }],
                    "allowed_actions": [{"id": "dispatch.hermes"}, {"id": "kernel.inspect"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }

            def fake_bridge_runs(*_args, **kwargs):
                self.assertEqual(kwargs["run_options"]["workspace_root"], "/local/plugins/wasm-agent")
                return "Repo route dispatch handled.", "bridge_runs", {"total_tokens": 11}, {"id": "run_repo_route", "steps": []}

            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs", side_effect=fake_bridge_runs) as bridge:
                result = server_mod.provider_envelope_run_completion(object(), body, user=self.admin())

            self.assertEqual(result["reply"], "Repo route dispatch handled.")
            self.assertEqual(result["hermes_dispatch"]["workspace"]["route_id"], "wasm-agent.avatar-chat.ui")
            bridge.assert_called_once()

    def test_paracelsus_runtime_route_contract_is_declared(self) -> None:
        resolved = server_mod.agent_kernel_tool(
            object(),
            "/agent/tools/kernel.resolve",
            {"route_id": "hermes-node.paracelsus.runtime"},
            user=self.admin(),
        )
        self.assertEqual(resolved["route_id"], "hermes-node.paracelsus.runtime")
        self.assertIn("/local/agents/nodes/paracelsus", resolved["route_contract"]["allowed_read_roots"])
        self.assertIn("/local/datas/paracelsus", resolved["route_contract"]["allowed_read_roots"])
        self.assertEqual(resolved["route_contract"]["entities"][0]["id"], "paracelsus")
        _messages, envelope, semantic, _measurement = server_mod.direct_envelope_with_metrics({
            "envelope": {
                "objective": "Tell me about the Paracelsus node.",
                "surface": "avatar-chat",
                "route_id": "wasm-agent.avatar-chat.ui",
            }
        })
        self.assertEqual(envelope["runtime_entity_routes"][0]["route_id"], "hermes-node.paracelsus.runtime")
        self.assertIn("RUNTIME_ROUTES", semantic)

    def test_direct_head_runtime_entity_objective_attaches_local_kernel_before_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-runtime-provider-502",
                "receiver": "openai-codex",
                "envelope": {
                    "trace_id": "trace-runtime-provider-502",
                    "objective": "Tell me about the Paracelsus node and what has happened there since creation.",
                    "surface": "avatar-chat",
                    "route_id": "wasm-agent.avatar-chat.ui",
                    "capabilities": ["runtime.inspect", "proof.report"],
                    "allowed_actions": [{"id": "answer"}, {"id": "dispatch.hermes"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }
            provider_error = server_mod.ProviderProxyError(
                "network-failed",
                "HTTP 502",
                diagnostic=server_mod.provider_diagnostic("direct-envelope", "network-failed", "HTTP 502", server_mod.HTTPStatus.BAD_GATEWAY),
                status=server_mod.HTTPStatus.BAD_GATEWAY,
            )
            with (
                patch.dict(os.environ, env, clear=True),
                patch.object(server_mod, "openai_responses_completion", side_effect=provider_error) as provider,
                patch.object(server_mod, "call_agent_bridge_runs") as bridge,
            ):
                result = server_mod.provider_envelope_run_completion(object(), body, user=self.admin())
                run = server_mod.read_agent_run(self.admin(), result["run_id"])["run"]
                events = server_mod.read_agent_run_events(self.admin(), result["run_id"], {"limit": ["500"]})["events"]

            provider.assert_called_once()
            bridge.assert_not_called()
            self.assertEqual(run["status"], "completed")
            self.assertEqual(run["final"]["diagnostics"]["source"], "provider_transport_fallback")
            self.assertIn("Kernel inspection proof", run["final"]["reply"])
            self.assertIn("bootstrapped_at=2026-04-24T21:41:55Z", run["final"]["reply"])
            provider_envelope = provider.call_args.args[2]
            self.assertIn("local_kernel_evidence", provider_envelope)
            self.assertTrue(any(item.get("tool") == "kernel.inspect" for item in provider_envelope["local_kernel_evidence"]))
            self.assertTrue(any(event["type"] == "tool.finished" and "kernel.inspect" in event["summary"] for event in events))
            self.assertIsNone(run["final"]["hermes_dispatch"])

    def test_direct_head_implementation_intent_does_not_runtime_entity_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Dispatching owned repo implementation work.",
                            "decision": "dispatch.hermes",
                            "actions": [{
                                "action": "dispatch.hermes",
                                "role": "subagent_harness",
                                "route_id": "wasm-agent.avatar-chat.ui",
                                "workspace_root": "/local/plugins/wasm-agent",
                                "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
                                "objective": "Inspect widget extension points, edit the owned route, and prove the widget.",
                                "escalation_reason": "Implementation requires scoped repo edits and focused proof.",
                            }],
                            "state_delta": {},
                            "needs": [],
                            "confidence": 0.82,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-implementation-entity",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-implementation-entity",
                    "objective": "Use Hermes to implement the shared-space widget for the Paracelsus meta-analysis workflow.",
                    "surface": "avatar-chat",
                    "route_id": "wasm-agent.avatar-chat.ui",
                    "capabilities": ["repo.read", "repo.edit", "test.run", "runtime.inspect", "proof.report"],
                    "allowed_actions": [{"id": "answer"}, {"id": "dispatch.hermes"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }
            with (
                patch.dict(os.environ, env, clear=True),
                patch.object(server_mod, "call_agent_bridge_runs", return_value=(
                    "Implementation bridge accepted.",
                    "hermes",
                    {"total_tokens": 11},
                    {"changed_files": ["public/app.js"]},
                )) as bridge,
            ):
                result = server_mod.provider_envelope_run_completion(object(), body, user=self.admin())
                run = server_mod.read_agent_run(self.admin(), result["run_id"])["run"]
                events = server_mod.read_agent_run_events(self.admin(), result["run_id"], {"limit": ["500"]})["events"]

            bridge.assert_called_once()
            provider_payload = ProviderStubHandler.requests[-1]["payload"]
            provider_text = json.dumps(provider_payload)
            self.assertNotIn("local_runtime_route_inspection", [event["summary"] for event in events])
            self.assertFalse(any(event["type"] == "tool.finished" and "kernel.inspect" in event["summary"] for event in events))
            self.assertNotIn("\\nLOCAL_KERNEL_EVIDENCE ", provider_text)
            self.assertIn("implementation_uses_owned_repo_action_lane_before_entity_inspection", provider_text)
            self.assertEqual(run["final"]["diagnostics"]["route_id"], "wasm-agent.avatar-chat.ui")
            self.assertEqual(run["final"]["hermes_dispatch"]["workspace"]["workspace_root"], "/local/plugins/wasm-agent")

    def test_direct_head_continue_implementation_goal_does_not_auto_dispatch_hermes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Paracelsus space inspection complete.",
                            "decision": "answer",
                            "actions": [],
                            "state_delta": {},
                            "needs": [],
                            "confidence": 0.74,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-continue-runtime-only",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-continue-runtime-only",
                    "objective": "Continue",
                    "surface": "avatar-chat",
                    "route_id": "wasm-agent.avatar-chat.ui",
                    "capabilities": ["repo.read", "repo.edit", "test.run", "runtime.inspect", "proof.report"],
                    "compact_state": {
                        "continuity": {
                            "csc": "Previous goal: implement the shared-space widget for the Paracelsus meta-analysis workflow.",
                        },
                    },
                    "allowed_actions": [{"id": "answer"}, {"id": "dispatch.hermes"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }
            with (
                patch.dict(os.environ, env, clear=True),
                patch.object(server_mod, "call_agent_bridge_runs") as bridge,
            ):
                with self.assertRaises(server_mod.ProviderProxyError) as raised:
                    server_mod.provider_envelope_run_completion(object(), body, user=self.admin())
                runs = server_mod.list_agent_runs(self.admin(), {"session_id": ["direct-session"]})["runs"]
                run = runs[0]
                events = server_mod.read_agent_run_events(self.admin(), run["run_id"], {"limit": ["500"]})["events"]

            bridge.assert_not_called()
            self.assertEqual(raised.exception.diagnostic["category"], "implementation_goal_incomplete")
            self.assertEqual(run["status"], "failed")
            self.assertTrue(any(event["summary"] == "Implementation result needs local change proof; Hermes auto-repair is disabled" for event in events))
            self.assertFalse(any(event["type"] == "hermes.dispatch" for event in events))
            self.assertEqual(events[-1]["type"], "run.error")

    def test_direct_head_widget_availability_question_does_not_require_changed_files(self) -> None:
        envelope = {
            "objective": "Amazing. I would like to check the availability for you to make widgets in the realure space",
            "surface": "avatar-chat",
            "route_id": "wasm-agent.avatar-chat.ui",
            "capabilities": ["repo.read", "repo.edit", "test.run", "runtime.inspect", "proof.report"],
        }

        self.assertFalse(server_mod.direct_head_objective_is_implementation_intent(envelope))
        self.assertFalse(server_mod.direct_head_goal_requires_change_artifact(envelope))

    def test_direct_head_widget_possibility_inquiry_does_not_require_changed_files(self) -> None:
        envelope = {
            "objective": "check out the possibility to ship widgets to the spaces",
            "surface": "avatar-chat",
            "route_id": "wasm-agent.avatar-chat.ui",
            "capabilities": ["repo.read", "repo.edit", "test.run", "runtime.inspect", "proof.report"],
        }

        self.assertFalse(server_mod.direct_head_objective_is_implementation_intent(envelope))
        self.assertFalse(server_mod.direct_head_goal_requires_change_artifact(envelope))

    def test_direct_head_widget_can_we_ship_question_does_not_require_changed_files(self) -> None:
        envelope = {
            "objective": "amazing. can we ship a widget to the realure space?",
            "surface": "avatar-chat",
            "route_id": "wasm-agent.avatar-chat.ui",
            "capabilities": ["repo.read", "repo.edit", "test.run", "runtime.inspect", "proof.report"],
        }

        self.assertTrue(server_mod.direct_head_text_is_capability_inquiry(envelope["objective"]))
        self.assertFalse(server_mod.direct_head_objective_is_implementation_intent(envelope))
        self.assertFalse(server_mod.direct_head_goal_requires_change_artifact(envelope))

    def test_direct_head_widget_build_request_still_requires_changed_files(self) -> None:
        envelope = {
            "objective": "Go ahead and build the widget in the Realure space",
            "surface": "avatar-chat",
            "route_id": "wasm-agent.avatar-chat.ui",
            "capabilities": ["repo.read", "repo.edit", "test.run", "runtime.inspect", "proof.report"],
        }

        self.assertTrue(server_mod.direct_head_objective_is_implementation_intent(envelope))
        self.assertTrue(server_mod.direct_head_goal_requires_change_artifact(envelope))

    def test_direct_head_missing_state_needs_kernel_action_before_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "I would need runtime proof before answering.",
                            "decision": "answer",
                            "actions": [],
                            "state_delta": {},
                            "needs": ["runtime proof"],
                            "confidence": 0.3,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-kernel-required",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-kernel-required",
                    "objective": "Answer an unknown runtime question.",
                    "surface": "avatar-chat",
                    "capabilities": ["runtime.inspect", "proof.report"],
                    "allowed_actions": [{"id": "answer"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }
            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs") as bridge:
                with self.assertRaises(server_mod.ProviderProxyError) as raised:
                    server_mod.provider_envelope_run_completion(object(), body, user=self.admin())
                runs = server_mod.list_agent_runs(self.admin(), {"session_id": ["direct-session"]})["runs"]
                events = server_mod.read_agent_run_events(self.admin(), runs[0]["run_id"])["events"]

            self.assertEqual(raised.exception.diagnostic["category"], "kernel_inspection_required")
            bridge.assert_not_called()
            self.assertEqual(runs[0]["status"], "failed")
            self.assertEqual(events[-1]["type"], "run.error")

    def test_direct_head_replaces_stale_tool_request_answer_after_local_tools_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "I need to inspect the widget code before I can give accurate testing instructions.",
                            "decision": "Dispatch kernel.inspect to locate the widget.",
                            "actions": [{
                                "action": "kernel.inspect",
                                "args": {
                                    "route_id": "wasm-agent.avatar-chat.ui",
                                    "inspect": ["files"],
                                    "query": "meta-analysis widget",
                                },
                            }],
                            "state_delta": {},
                            "needs": ["widget_file_path"],
                            "confidence": 0.45,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-stale-local-tool-answer",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-stale-local-tool-answer",
                    "objective": "Instruct me on how to use the meta-analysis widget.",
                    "surface": "avatar-chat",
                    "route_id": "wasm-agent.avatar-chat.ui",
                    "capabilities": ["repo.read", "runtime.inspect", "proof.report"],
                    "allowed_actions": [{"id": "answer"}, {"id": "kernel.inspect"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }

            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs") as bridge:
                result = server_mod.provider_envelope_run_completion(object(), body, user=self.admin())
                run = server_mod.read_agent_run(self.admin(), result["run_id"])["run"]
                events = server_mod.read_agent_run_events(self.admin(), result["run_id"])["events"]

            bridge.assert_not_called()
            self.assertEqual(run["status"], "completed")
            self.assertNotIn("I need to inspect", result["reply"])
            self.assertIn("Kernel inspection proof", result["reply"])
            self.assertTrue(any(event["type"] == "tool.finished" and event["summary"].startswith("kernel.inspect") for event in events))

    def test_direct_head_replaces_dispatching_inspection_now_after_local_tools_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "I need to inspect the widget code and runtime state. Dispatching inspection actions now.",
                            "decision": "route_to_kernel_inspect",
                            "actions": [{
                                "action": "kernel.inspect",
                                "args": {
                                    "route_id": "wasm-agent.avatar-chat.ui",
                                    "inspect": ["files"],
                                    "query": "meta-analysis widget",
                                },
                            }],
                            "state_delta": {},
                            "needs": ["runtime error logs"],
                            "confidence": 0.55,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-dispatching-inspection-stale-answer",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-dispatching-inspection-stale-answer",
                    "objective": "Why is the meta-analysis widget not working?",
                    "surface": "avatar-chat",
                    "route_id": "wasm-agent.avatar-chat.ui",
                    "capabilities": ["repo.read", "runtime.inspect", "proof.report"],
                    "allowed_actions": [{"id": "answer"}, {"id": "kernel.inspect"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }

            with patch.dict(os.environ, env, clear=True):
                result = server_mod.provider_envelope_run_completion(object(), body, user=self.admin())

            self.assertNotIn("Dispatching inspection actions now", result["reply"])
            self.assertIn("Kernel inspection proof", result["reply"])

    def test_direct_head_local_continuation_can_patch_after_inspection_without_hermes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            root = Path(tmp)
            (root / "app.py").write_text("value = 1\n", encoding="utf-8")
            registry = root / "routes.json"
            registry.write_text(json.dumps({
                "routes": [{
                    "route_id": "test.local.tools",
                    "surface": "avatar-chat",
                    "owner": "test",
                    "workspace_root": str(root),
                    "allowed_read_roots": [str(root)],
                    "allowed_write_roots": [str(root)],
                    "likely_paths": ["app.py"],
                    "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
                    "provider_policy": {"default": "local-first", "hermes": "bounded-skill-only", "missing_route": "fail"},
                    "budget": {"head_tokens_max": 3000, "provider_tokens_max": 8000, "api_calls_max": 6, "wall_ms_max": 90000},
                    "proof": ["route_id", "workspace_root", "changed_files"],
                }]
            }), encoding="utf-8")
            ProviderStubHandler.response_bodies = [
                {
                    "model": "stub-model",
                    "choices": [{
                        "message": {
                            "content": json.dumps({
                                "answer": "I need to inspect the file before editing.",
                                "decision": "kernel.inspect",
                                "actions": [{
                                    "action": "kernel.inspect",
                                    "args": {"route_id": "test.local.tools", "inspect": ["files"]},
                                }],
                                "state_delta": {},
                                "needs": ["file receipt"],
                                "confidence": 0.5,
                            })
                        }
                    }],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
                },
                {
                    "model": "stub-model",
                    "choices": [{
                        "message": {
                            "content": json.dumps({
                                "answer": "Patched the local file.",
                                "decision": "patch.apply_scoped",
                                "actions": [{
                                    "action": "patch.apply_scoped",
                                    "args": {
                                        "route_id": "test.local.tools",
                                        "patch": {
                                            "operations": [{
                                                "op": "replace",
                                                "path": "app.py",
                                                "find": "value = 1",
                                                "replace": "value = 2",
                                            }]
                                        },
                                    },
                                }],
                                "state_delta": {},
                                "needs": [],
                                "confidence": 0.9,
                            })
                        }
                    }],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 4, "total_tokens": 11},
                },
            ]
            env = {
                "WASM_AGENT_ROUTE_CONTRACTS_PATH": str(registry),
                "HERMES_WASM_AGENT_DB_PATH": str(root / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-local-continuation-patch",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-local-continuation-patch",
                    "objective": "go ahead and update app.py",
                    "surface": "avatar-chat",
                    "route_id": "test.local.tools",
                    "capabilities": ["repo.read", "repo.edit", "test.run", "proof.report"],
                    "allowed_actions": [{"id": "kernel.inspect"}, {"id": "patch.apply_scoped"}, {"id": "answer"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }

            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs") as bridge:
                result = server_mod.provider_envelope_run_completion(object(), body, user=self.admin())
                events = server_mod.read_agent_run_events(self.admin(), result["run_id"], {"limit": ["500"]})["events"]
                run = server_mod.read_agent_run(self.admin(), result["run_id"])["run"]

            bridge.assert_not_called()
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "value = 2\n")
            self.assertEqual(run["status"], "completed")
            self.assertIn("app.py", run["final"]["changed_files"])
            self.assertTrue(any(event["type"] == "head.continued" for event in events))
            self.assertTrue(any(event["type"] == "tool.finished" and "patch.apply_scoped" in event["summary"] for event in events))

    def test_direct_head_repairs_empty_provider_content_into_local_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            root = Path(tmp)
            (root / "app.py").write_text("value = 1\n", encoding="utf-8")
            registry = root / "routes.json"
            registry.write_text(json.dumps({
                "routes": [{
                    "route_id": "test.empty.repair",
                    "surface": "avatar-chat",
                    "owner": "test",
                    "workspace_root": str(root),
                    "allowed_read_roots": [str(root)],
                    "allowed_write_roots": [str(root)],
                    "likely_paths": ["app.py"],
                    "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
                    "provider_policy": {"default": "local-first", "hermes": "bounded-skill-only", "missing_route": "fail"},
                    "budget": {"head_tokens_max": 3000, "provider_tokens_max": 8000, "api_calls_max": 6, "wall_ms_max": 90000},
                    "proof": ["route_id", "workspace_root", "changed_files"],
                }]
            }), encoding="utf-8")
            ProviderStubHandler.response_bodies = [
                {
                    "model": "stub-model",
                    "choices": [{"message": {"content": ""}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 0, "total_tokens": 5},
                },
                {
                    "model": "stub-model",
                    "choices": [{
                        "message": {
                            "content": json.dumps({
                                "answer": "Patched after empty response repair.",
                                "decision": "patch.apply_scoped",
                                "actions": [{
                                    "action": "patch.apply_scoped",
                                    "args": {
                                        "route_id": "test.empty.repair",
                                        "patch": {
                                            "operations": [{
                                                "op": "replace",
                                                "path": "app.py",
                                                "find": "value = 1",
                                                "replace": "value = 2",
                                            }]
                                        },
                                    },
                                }],
                                "state_delta": {},
                                "needs": [],
                                "confidence": 0.9,
                            })
                        }
                    }],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
                },
            ]
            env = {
                "WASM_AGENT_ROUTE_CONTRACTS_PATH": str(registry),
                "HERMES_WASM_AGENT_DB_PATH": str(root / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-empty-provider-repair",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-empty-provider-repair",
                    "objective": "go ahead and update app.py",
                    "surface": "avatar-chat",
                    "route_id": "test.empty.repair",
                    "capabilities": ["repo.read", "repo.edit", "test.run", "proof.report"],
                    "allowed_actions": [{"id": "patch.apply_scoped"}, {"id": "answer"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }

            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs") as bridge:
                result = server_mod.provider_envelope_run_completion(object(), body, user=self.admin())
                events = server_mod.read_agent_run_events(self.admin(), result["run_id"], {"limit": ["500"]})["events"]
                run = server_mod.read_agent_run(self.admin(), result["run_id"])["run"]

            bridge.assert_not_called()
            self.assertEqual(len(ProviderStubHandler.requests), 2)
            repair_messages = ProviderStubHandler.requests[1]["payload"]["messages"]
            self.assertIn("STRICT ACTION REPAIR", repair_messages[-1]["content"])
            self.assertIn("EMPTY RESPONSE REPAIR", repair_messages[-1]["content"])
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "value = 2\n")
            self.assertEqual(run["status"], "completed")
            self.assertIn("app.py", run["final"]["changed_files"])
            self.assertTrue(any(event["type"] == "head.repair" for event in events))
            self.assertTrue(any(event["type"] == "tool.finished" and "patch.apply_scoped" in event["summary"] for event in events))

    def test_direct_head_rejects_malformed_dispatch_intent_without_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": (
                            "```json\n"
                            "{\n"
                            "  \"answer\": \"Dispatching bounded inspections now.\",\n"
                            "  \"decision\": \"dispatch.hermes for kernel.inspect\"\n"
                        )
                    }
                }],
                "usage": {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-malformed-dispatch",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-malformed-dispatch",
                    "objective": "Inspect the current space and dispatch bounded work.",
                    "surface": "avatar-chat",
                    "capabilities": ["repo.read", "runtime.inspect", "proof.report"],
                    "allowed_actions": [{"id": "answer"}, {"id": "dispatch.hermes"}, {"id": "kernel.inspect"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }
            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs") as bridge:
                with self.assertRaises(server_mod.ProviderProxyError) as raised:
                    server_mod.provider_envelope_run_completion(object(), body, user=self.admin())
                runs = server_mod.list_agent_runs(self.admin(), {"session_id": ["direct-session"]})["runs"]
                events = server_mod.read_agent_run_events(self.admin(), runs[0]["run_id"])["events"]

            self.assertEqual(raised.exception.diagnostic["category"], "structured_action_required")
            bridge.assert_not_called()
            self.assertEqual(runs[0]["status"], "failed")
            self.assertEqual(events[-1]["type"], "run.error")
            self.assertFalse(any(event["type"] == "run.final" for event in events))

    def test_direct_head_rejects_plain_dispatch_claim_without_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": "I see the needed inspection. Dispatching bounded inspections now."
                    }
                }],
                "usage": {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-plain-dispatch-claim",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-plain-dispatch-claim",
                    "objective": "Inspect the current space and dispatch bounded work.",
                    "surface": "avatar-chat",
                    "capabilities": ["repo.read", "runtime.inspect", "proof.report"],
                    "allowed_actions": [{"id": "answer"}, {"id": "dispatch.hermes"}, {"id": "kernel.inspect"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }
            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs") as bridge:
                with self.assertRaises(server_mod.ProviderProxyError) as raised:
                    server_mod.provider_envelope_run_completion(object(), body, user=self.admin())
                runs = server_mod.list_agent_runs(self.admin(), {"session_id": ["direct-session"]})["runs"]
                events = server_mod.read_agent_run_events(self.admin(), runs[0]["run_id"])["events"]

            self.assertEqual(raised.exception.diagnostic["category"], "structured_action_required")
            bridge.assert_not_called()
            self.assertEqual(runs[0]["status"], "failed")
            self.assertEqual(events[-1]["type"], "run.error")
            self.assertFalse(any(event["type"] == "run.final" for event in events))

    def test_direct_head_repairs_invalid_dispatch_intent_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.response_bodies = [
                {
                    "model": "stub-model",
                    "choices": [{
                        "message": {
                            "content": (
                                "Here's what I understand. I'm dispatching to Hermes for proof and file work.\n\n"
                                "```json\n{\"answer\":\"Dispatching that now.\",\"decision\":\"dispatch.hermes for Paracelsus"
                            )
                        }
                    }],
                    "usage": {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
                },
                {
                    "model": "stub-model",
                    "choices": [{
                        "message": {
                            "content": json.dumps({
                                "answer": "Dispatching bounded proof work.",
                                "decision": "dispatch.hermes",
                                "actions": [{
                                    "action": "dispatch.hermes",
                                    "role": "subagent_harness",
                                    "objective": "Inspect declared refs and summarize the implementation path.",
                                    "caps": ["repo.read", "proof.report"],
                                    "refs": ["ctx://workspace/compact-state"],
                                    "proof": ["summary"],
                                    "escalation_reason": "The requested implementation path needs bounded repo/proof inspection before answering.",
                                }],
                                "state_delta": {},
                                "needs": [],
                                "confidence": 0.8,
                            }, separators=(",", ":"))
                        }
                    }],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 6, "total_tokens": 14},
                },
            ]
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            server = type("FakeServer", (), {"bridge_url": "http://bridge.example"})()
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-dispatch-repair",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-dispatch-repair",
                    "objective": "Use Hermes to inspect declared refs before answering.",
                    "surface": "avatar-chat",
                    "capabilities": ["repo.read", "proof.report"],
                    "allowed_actions": [{"id": "answer"}, {"id": "dispatch.hermes"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }

            def fake_bridge_runs(*_args, **kwargs):
                return "Hermes repaired dispatch handled it.", "bridge_runs", {"total_tokens": 9}, {"id": "run_repair", "steps": [], "tool_calls": []}

            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs", side_effect=fake_bridge_runs) as bridge:
                result = server_mod.provider_envelope_run_completion(server, body, user=self.admin())
                events = server_mod.read_agent_run_events(self.admin(), result["run_id"], {"limit": ["500"]})["events"]

            bridge.assert_called_once()
            self.assertEqual(result["reply"], "Hermes repaired dispatch handled it.")
            self.assertEqual(len(ProviderStubHandler.requests), 2)
            event_types = [event["type"] for event in events]
            self.assertIn("hermes.dispatch", event_types)
            self.assertEqual(event_types[-1], "run.final")

    def test_direct_head_action_repair_body_tightens_output_contract(self) -> None:
        body = {
            "instructions": "Use the envelope.",
            "max_output_tokens": 128,
            "envelope": {
                "trace_id": "trace-repair-body",
                "objective": "Need bounded work.",
                "allowed_actions": [{"id": "answer"}, {"id": "dispatch.hermes"}],
            },
        }
        bad_reply = "I'm dispatching to Hermes now.\n```json\n{\"decision\":\"dispatch.hermes"
        capped_action_reply = (
            '{"answer":"Reading exact turn 6 content before self-criticism.",'
            '"decision":"transcript.read for turns 5-6 before answering",'
            '"actions":[{"action"'
        )
        complete_answer_json = {
            "answer": "I can answer from the provided context.",
            "decision": "answer",
            "actions": [],
        }

        self.assertTrue(server_mod.direct_head_requires_structured_action(None, bad_reply))
        self.assertTrue(server_mod.direct_head_requires_structured_action({}, capped_action_reply))
        self.assertFalse(server_mod.direct_head_requires_structured_action(complete_answer_json, json.dumps(complete_answer_json)))
        repaired = server_mod.direct_head_action_repair_body(body, bad_reply)

        self.assertIn("STRICT ACTION REPAIR", repaired["instructions"])
        self.assertIn("first character", repaired["instructions"])
        self.assertGreaterEqual(repaired["max_output_tokens"], 1200)
        self.assertEqual(body["max_output_tokens"], 128)

    def test_direct_head_dispatches_hermes_through_bridge_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Dispatch Hermes.",
                            "decision": "dispatch",
                            "actions": [{
                                "action": "dispatch.hermes",
                                "role": "subagent_harness",
                                "objective": "Inspect compact refs.",
                                "caps": ["repo.read", "proof.report"],
                                "escalation_reason": "Provider head requested bridge proof that local deterministic tools cannot complete alone.",
                                "refs": ["ctx://repo/map"],
                                "proof": ["summary"],
                                "stream": True,
                            }],
                            "state_delta": {},
                            "needs": [],
                            "confidence": 0.85,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            server = type("FakeServer", (), {"bridge_url": "http://bridge.example"})()
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-dispatch",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-dispatch",
                    "objective": "Use Hermes for this bounded bridge proof.",
                    "surface": "avatar-chat",
                    "capabilities": ["repo.read", "proof.report"],
                    "allowed_actions": [{"id": "dispatch.hermes"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }

            def fake_bridge_runs(*_args, **kwargs):
                action_callback = kwargs.get("action_callback")
                if action_callback:
                    action_callback({
                        "id": "bridge_run",
                        "topic": "run-hermes",
                        "kind": "model",
                        "label": "bridge.run.completed",
                        "status": "done",
                        "detail": "completed",
                    })
                return "Hermes handled it.", "bridge_runs", {"total_tokens": 9}, {"id": "run_bridge", "steps": [], "tool_calls": []}

            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs", side_effect=fake_bridge_runs):
                result = server_mod.provider_envelope_run_completion(server, body, user=self.admin())

                self.assertEqual(result["reply"], "Hermes handled it.")
                self.assertEqual(result["hermes_dispatch"]["source"], "bridge_runs")
                self.assertLessEqual(result["hermes_dispatch"]["context_measurement"]["estimated_tokens"], 1500)
                events = server_mod.read_agent_run_events(self.admin(), result["run_id"])["events"]
                event_types = [event["type"] for event in events]
                self.assertIn("hermes.dispatch", event_types)
                self.assertIn("hermes.progress", event_types)
                self.assertIn("tokens.used", event_types)
                self.assertEqual(event_types[-1], "run.final")
                token_event = next(event for event in events if event["type"] == "tokens.used")
                self.assertEqual(token_event["payload"]["usage"]["total_tokens"], 14)
                self.assertEqual(token_event["payload"]["primary"], "total")
                self.assertEqual(token_event["payload"]["components"]["head"]["total_tokens"], 5)
                self.assertEqual(token_event["payload"]["components"]["bridge"]["total_tokens"], 9)
                stored_run = server_mod.read_agent_run(self.admin(), result["run_id"])["run"]
                self.assertEqual(stored_run["token_ledger"]["provider_call_count"], 2)
                self.assertEqual(stored_run["token_ledger"]["input_tokens"], 3)
                self.assertEqual(stored_run["token_ledger"]["output_tokens"], 2)
                self.assertEqual(stored_run["token_ledger"]["total_tokens"], 14)
                cost = server_mod.agent_kernel_tool(
                    server,
                    "/agent/tools/cost.status",
                    {"run_id": result["run_id"]},
                    user=self.admin(),
                )
                self.assertEqual(cost["ledger"]["input_tokens"], 3)
                self.assertEqual(cost["ledger"]["output_tokens"], 2)
                self.assertEqual(cost["ledger"]["total_tokens"], 14)

    def test_direct_head_dispatch_requires_explicit_hermes_user_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Dispatch Hermes.",
                            "decision": "dispatch",
                            "actions": [{
                                "action": "dispatch.hermes",
                                "role": "subagent_harness",
                                "objective": "Inspect compact refs.",
                                "caps": ["repo.read", "proof.report"],
                                "escalation_reason": "Provider head requested bridge proof.",
                                "refs": ["ctx://repo/map"],
                                "proof": ["summary"],
                            }],
                            "state_delta": {},
                            "needs": [],
                            "confidence": 0.85,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-dispatch-no-hermes-opt-in",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-dispatch-no-hermes-opt-in",
                    "objective": "Decide using local kernel/provider capabilities.",
                    "surface": "avatar-chat",
                    "capabilities": ["repo.read", "proof.report"],
                    "allowed_actions": [{"id": "dispatch.hermes"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }

            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs") as bridge:
                with self.assertRaises(server_mod.ProviderProxyError) as raised:
                    server_mod.provider_envelope_run_completion(object(), body, user=self.admin())

            self.assertEqual(raised.exception.diagnostic["category"], "hermes_explicit_request_required")
            bridge.assert_not_called()

    def test_direct_head_dispatch_requires_hermes_subagent_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Dispatch Hermes.",
                            "decision": "dispatch",
                            "actions": [{
                                "action": "dispatch.hermes",
                                "objective": "Inspect compact refs.",
                                "caps": ["repo.read", "proof.report"],
                                "escalation_reason": "Need bounded bridge proof after local route resolution.",
                                "refs": ["ctx://repo/map"],
                                "proof": ["summary"],
                            }],
                            "state_delta": {},
                            "needs": [],
                            "confidence": 0.85,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-dispatch-without-subagent-contract",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-dispatch-without-subagent-contract",
                    "objective": "Use Hermes for this bounded bridge proof.",
                    "surface": "avatar-chat",
                    "capabilities": ["repo.read", "proof.report"],
                    "allowed_actions": [{"id": "dispatch.hermes"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }

            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs") as bridge:
                with self.assertRaises(server_mod.ProviderProxyError) as raised:
                    server_mod.provider_envelope_run_completion(object(), body, user=self.admin())

            self.assertEqual(raised.exception.diagnostic["category"], "hermes_subagent_contract_required")
            bridge.assert_not_called()

    def test_direct_head_without_server_provider_key_fails_without_hermes_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "wa.env"
            env_path.write_text("", encoding="utf-8")
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
                "HERMES_WASM_AGENT_ENV_PATH": str(env_path),
            }
            server = type("FakeServer", (), {"bridge_url": "http://bridge.example"})()
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-no-provider-key",
                "use_server_provider": True,
                "provider_config_source": "server-default",
                "envelope": {
                    "trace_id": "trace-no-provider-key",
                    "objective": "Answer through the master frontier lane.",
                    "surface": "avatar-chat",
                    "capabilities": ["repo.read", "proof.report"],
                    "allowed_actions": [{"id": "dispatch.hermes"}],
                    "budget": {"max_output_tokens": 128},
                    "stream": True,
                },
            }

            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs") as bridge:
                with self.assertRaises(server_mod.ProviderProxyError) as raised:
                    server_mod.provider_envelope_run_completion(server, body, user=self.admin())
                runs = server_mod.list_agent_runs(self.admin(), {"session_id": ["direct-session"]})["runs"]
                events = server_mod.read_agent_run_events(self.admin(), runs[0]["run_id"])["events"]

            bridge.assert_not_called()
            self.assertEqual(raised.exception.diagnostic["category"], "provider_head_unavailable")
            self.assertEqual(runs[0]["status"], "failed")
            event_types = [event["type"] for event in events]
            self.assertIn("head.decision", event_types)
            self.assertNotIn("hermes.dispatch", event_types)
            self.assertEqual(events[-1]["type"], "run.error")

    def test_direct_head_dispatch_requires_resolved_route_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Dispatch Hermes.",
                            "decision": "dispatch",
                            "actions": [{
                                "action": "dispatch.hermes",
                                "objective": "Search wherever needed.",
                                "caps": ["repo.read", "proof.report"],
                            }],
                            "state_delta": {},
                            "needs": [],
                            "confidence": 0.7,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-missing-route",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-missing-route",
                    "objective": "Use Hermes for this bounded bridge proof.",
                    "capabilities": ["repo.read", "proof.report"],
                    "allowed_actions": [{"id": "dispatch.hermes"}],
                    "budget": {"max_output_tokens": 128},
                },
            }
            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs") as bridge:
                with self.assertRaises(server_mod.ProviderProxyError) as raised:
                    server_mod.provider_envelope_run_completion(object(), body, user=self.admin())

                self.assertEqual(raised.exception.diagnostic["category"], "route_contract_missing")
                bridge.assert_not_called()
                runs = server_mod.list_agent_runs(self.admin(), {"session_id": ["direct-session"]})["runs"]
                self.assertEqual(runs[0]["status"], "failed")

    def test_direct_head_dispatch_requires_escalation_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Dispatch Hermes.",
                            "decision": "dispatch",
                            "actions": [{
                                "action": "dispatch.hermes",
                                "objective": "Use Hermes without saying why.",
                                "caps": ["repo.read", "proof.report"],
                            }],
                            "state_delta": {},
                            "needs": [],
                            "confidence": 0.7,
                        })
                    }
                }],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-missing-escalation",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-missing-escalation",
                    "objective": "Use Hermes for this bounded bridge proof.",
                    "surface": "avatar-chat",
                    "capabilities": ["repo.read", "proof.report"],
                    "allowed_actions": [{"id": "dispatch.hermes"}],
                    "budget": {"max_output_tokens": 128},
                },
            }
            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs") as bridge:
                with self.assertRaises(server_mod.ProviderProxyError) as raised:
                    server_mod.provider_envelope_run_completion(object(), body, user=self.admin())

                self.assertEqual(raised.exception.diagnostic["category"], "hermes-escalation-missing")
                bridge.assert_not_called()

    def test_direct_head_rejects_unknown_hermes_capability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Dispatch Hermes.",
                            "decision": "dispatch",
                            "actions": [{
                                "action": "dispatch.hermes",
                                "objective": "Do a forbidden thing.",
                                "caps": ["repo.read", "root.secret"],
                                "escalation_reason": "Exercise unknown capability rejection after route resolution.",
                            }],
                            "state_delta": {},
                            "needs": [],
                            "confidence": 0.4,
                        })
                    }
                }],
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-bad-cap",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-bad-cap",
                    "objective": "Use Hermes for this bounded bridge proof.",
                    "surface": "avatar-chat",
                    "allowed_actions": [{"id": "dispatch.hermes"}],
                },
            }
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(server_mod.ProviderProxyError) as raised:
                    server_mod.provider_envelope_run_completion(object(), body, user=self.admin())

                self.assertEqual(raised.exception.diagnostic["category"], "unknown-hermes-capability")
                runs = server_mod.list_agent_runs(self.admin(), {"session_id": ["direct-session"]})["runs"]
                self.assertEqual(runs[0]["status"], "failed")
                events = server_mod.read_agent_run_events(self.admin(), runs[0]["run_id"])["events"]
                self.assertEqual(events[-1]["type"], "run.error")

    def test_direct_envelope_is_admin_only(self) -> None:
        body = {
            "provider_config": self.body("https://provider.example")["provider_config"],
            "envelope": {"objective": "Decide whether to dispatch Hermes."},
        }
        with self.assertRaises(server_mod.ProviderProxyError) as ctx:
            server_mod.provider_envelope_completion(None, body, user=self.user())
        self.assertEqual(ctx.exception.status, server_mod.HTTPStatus.FORBIDDEN)
        self.assertEqual(ctx.exception.diagnostic["category"], "admin-required")

    def test_direct_envelope_requires_objective(self) -> None:
        body = {
            "provider_config": self.body("https://provider.example")["provider_config"],
            "envelope": {"compact_state": {"screen": "avatar-chat"}},
        }
        with self.assertRaises(server_mod.ProviderProxyError) as ctx:
            server_mod.provider_envelope_completion(None, body, user=self.admin())
        self.assertEqual(ctx.exception.diagnostic["category"], "missing-objective")

    def test_backend_proxy_preserves_image_content_parts(self) -> None:
        with ProviderStub() as stub:
            body = self.body(stub.base_url)
            body["messages"] = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is in this image?"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA", "detail": "low"}},
                ],
            }]
            server_mod.provider_proxy_completion(None, body, user=self.user())
            content = ProviderStubHandler.requests[-1]["payload"]["messages"][0]["content"]
            self.assertIsInstance(content, list)
            self.assertEqual(content[0], {"type": "text", "text": "What is in this image?"})
            self.assertEqual(content[1]["type"], "image_url")
            self.assertEqual(content[1]["image_url"]["url"], "data:image/png;base64,AAAA")
            self.assertEqual(content[1]["image_url"]["detail"], "low")

    def test_backend_proxy_preserves_video_content_parts(self) -> None:
        with ProviderStub() as stub:
            body = self.body(stub.base_url)
            body["messages"] = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "What happens in this clip?"},
                    {"type": "video_url", "videoUrl": {"url": "data:video/mp4;base64,AAAA"}},
                ],
            }]
            server_mod.provider_proxy_completion(None, body, user=self.user())
            content = ProviderStubHandler.requests[-1]["payload"]["messages"][0]["content"]
            self.assertIsInstance(content, list)
            self.assertEqual(content[1]["type"], "video_url")
            self.assertEqual(content[1]["videoUrl"]["url"], "data:video/mp4;base64,AAAA")

    def test_backend_proxy_uses_existing_v1_without_duplication(self) -> None:
        with ProviderStub() as stub:
            server_mod.provider_proxy_completion(None, self.body(f"{stub.base_url}/v1/"), user=self.user())
            self.assertEqual(ProviderStubHandler.requests[-1]["path"], "/v1/chat/completions")

    def test_backend_proxy_http_diagnostics(self) -> None:
        cases = [
            (401, "auth-failed"),
            (403, "auth-failed"),
            (404, "model-not-found"),
            (400, "request-shape-error"),
            (422, "request-shape-error"),
            (503, "provider-unavailable"),
        ]
        for status, category in cases:
            with self.subTest(status=status):
                with ProviderStub() as stub:
                    ProviderStubHandler.status = status
                    ProviderStubHandler.body = {"error": {"message": f"status {status}"}}
                    with self.assertRaises(server_mod.ProviderProxyError) as ctx:
                        server_mod.provider_proxy_completion(None, self.body(stub.base_url), user=self.user())
                    self.assertEqual(ctx.exception.diagnostic["category"], category)
                    self.assertEqual(ctx.exception.diagnostic["http_status"], status)

    def test_backend_proxy_cloudflare_403_is_not_labeled_bad_key(self) -> None:
        with ProviderStub() as stub:
            ProviderStubHandler.status = 403
            ProviderStubHandler.body = {
                "title": "Error 1010: Access denied",
                "detail": "The site owner has blocked access based on your browser's signature.",
                "cloudflare_error": True,
            }
            with self.assertRaises(server_mod.ProviderProxyError) as ctx:
                server_mod.provider_proxy_completion(None, self.body(stub.base_url), user=self.user())
            self.assertEqual(ctx.exception.diagnostic["category"], "provider-access-denied")
            self.assertEqual(ctx.exception.diagnostic["mode"], "unreachable")


if __name__ == "__main__":
    unittest.main()
