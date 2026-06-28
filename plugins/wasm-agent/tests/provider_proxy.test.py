#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import base64
import json
import os
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
        if payload.get("stream"):
            choices = self.__class__.body.get("choices") if isinstance(self.__class__.body.get("choices"), list) else []
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
                    "usage": self.__class__.body.get("usage"),
                },
            ]
            data = "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode("utf-8") + b"data: [DONE]\n\n"
            self.send_response(self.__class__.status)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        data = json.dumps(self.__class__.body).encode("utf-8")
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
            self.assertIn('"secret_token":"super-secret"', user_input)
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
                    "objective": "Inspect compact refs from OpenAI direct head.",
                    "caps": ["repo.read", "proof.report"],
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
                    "objective": "Decide and dispatch only if proof work is needed.",
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
                stored = server_mod.read_agent_run(self.admin(), result["run_id"])["run"]["final"]

            self.assertEqual(result["reply"], "Hermes handled the OpenAI request.")
            self.assertEqual(result["hermes_dispatch"]["source"], "bridge_runs")
            self.assertEqual(result["hermes_dispatch"]["target_node"], "orchestrator")
            self.assertLessEqual(result["context_measurement"]["estimated_tokens"], 900)
            self.assertLessEqual(result["hermes_dispatch"]["context_measurement"]["estimated_tokens"], 1500)
            request = OpenAIResponsesStubHandler.requests[-1]
            self.assertIn("RAW true", request["payload"]["input"][1]["content"])
            event_types = [event["type"] for event in events]
            self.assertIn("head.delta", event_types)
            self.assertIn("head.decision", event_types)
            self.assertIn("hermes.dispatch", event_types)
            self.assertIn("hermes.progress", event_types)
            self.assertEqual(event_types[-1], "run.final")
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
                self.assertIn("delta", [line["type"] for line in replay_lines])
                self.assertEqual(replay_lines[-1]["type"], "final")
                self.assertEqual(replay_lines[-1]["agent"]["reply"], "Hello from OpenAI")
                events = server_mod.read_agent_run_events(self.admin(), final["run_id"])["events"]
                self.assertIn("head.delta", [event["type"] for event in events])

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

            self.assertIsInstance(first_line, str)
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
                self.assertIn("head.started", event_types)
                self.assertIn("head.decision", event_types)
                self.assertEqual(event_types[-1], "run.final")
                self.assertTrue(all(event["redacted"] for event in events))

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
                                "objective": "Inspect compact refs.",
                                "caps": ["repo.read", "proof.report"],
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
                    "objective": "Decide whether Hermes should act.",
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
                self.assertEqual(event_types[-1], "run.final")

    def test_direct_head_dispatch_uses_id_before_generic_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Dispatch via id.",
                            "decision": "dispatch.hermes",
                            "actions": [{
                                "id": "dispatch.hermes",
                                "type": "bridge",
                                "objective": "Apply a bounded implementation lane.",
                                "caps": ["repo.read", "proof.report"],
                                "proof_requests": ["runtime"],
                            }],
                            "confidence": 0.86,
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
                "turn_id": "direct-dispatch-id-before-type",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-dispatch-id-before-type",
                    "objective": "Decide whether Hermes should act.",
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
                return "Hermes handled id-first dispatch.", "bridge_runs", {"total_tokens": 9}, {"id": "run_id_first", "steps": [{"status": "completed"}], "tool_calls": []}

            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs", side_effect=fake_bridge_runs):
                result = server_mod.provider_envelope_run_completion(server, body, user=self.admin())
                run = server_mod.read_agent_run(self.admin(), result["run_id"])["run"]
                events = server_mod.read_agent_run_events(self.admin(), result["run_id"])["events"]

            self.assertEqual(result["reply"], "Hermes handled id-first dispatch.")
            self.assertEqual(result["hermes_dispatch"]["source"], "bridge_runs")
            self.assertEqual(run["status"], "completed")
            self.assertIn("hermes.dispatch", [event["type"] for event in events])
            self.assertEqual(run["bridge_obligation"]["state"], "satisfied")

    def test_direct_head_dispatch_prompt_binds_local_workspace_and_proof(self) -> None:
        action = {
            "id": "dispatch.hermes",
            "type": "bridge",
            "objective": "Run bounded streaming-performance improvement lane for avatar-chat.",
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "proof_requests": ["tests", "runtime"],
        }
        envelope = {
            "objective": "go ahead and do that",
            "evidence_refs": ["ctx://avatar-chat/current-turn"],
        }

        prompt = server_mod.direct_head_hermes_dispatch_prompt(action, envelope)

        self.assertIn("/local", prompt)
        self.assertIn("executable wasm-agent bridge handoff", prompt)
        self.assertIn("not role-play", prompt)
        self.assertIn("Do not refuse because you lack a wasm-agent bridge", prompt)
        self.assertIn("Do not ask the user to restate the task", prompt)
        self.assertIn("files/tests/runtime proof", prompt)
        self.assertIn("Run bounded streaming-performance improvement lane", prompt)

    def test_bridge_reply_test_report_satisfies_test_proof_code(self) -> None:
        final = {
            "reply": (
                "Bounded avatar-chat streaming-performance pass complete.\n\n"
                "Test results\n"
                "- agent_run_store.test.py      5/5 passed\n"
                "- bridge_routes.test.py        7/7 passed\n"
                "- streaming_performance.test.py 2/2 passed\n\n"
                "Syntax checks\n"
                "- static_server.py: py_compile OK\n"
            ),
            "hermes_dispatch": {
                "bridge_trace": {
                    "id": "run_tests",
                    "tool_calls": [{"name": "execute_code"}],
                },
            },
        }

        self.assertIn("tests", server_mod.final_proof_codes(final))

    def test_bridge_reply_without_passing_test_evidence_does_not_satisfy_tests(self) -> None:
        final = {
            "reply": "I inspected the tests and can run them if you want.",
            "hermes_dispatch": {
                "bridge_trace": {
                    "id": "run_no_tests",
                    "tool_calls": [{"name": "read_file"}],
                },
            },
        }

        self.assertNotIn("tests", server_mod.final_proof_codes(final))

    def test_direct_head_implementation_dispatch_creates_and_satisfies_bridge_obligation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "answer": "Dispatch implementation.",
                            "decision": "dispatch",
                            "actions": [{
                                "action": "dispatch.hermes",
                                "objective": "Implement the compact bridge lifecycle guard.",
                                "caps": ["repo.read", "repo.edit", "proof.report"],
                                "proof": ["files", "timeline"],
                            }],
                            "confidence": 0.9,
                        })
                    }
                }],
                "usage": {"total_tokens": 5},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            server = type("FakeServer", (), {"bridge_url": "http://bridge.example"})()
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-impl-obligation",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-impl-obligation",
                    "objective": "Implement lifecycle guard.",
                    "capabilities": ["repo.read", "repo.edit", "proof.report"],
                    "allowed_actions": [{"id": "dispatch.hermes"}],
                },
            }

            def fake_bridge_runs(*_args, **kwargs):
                return "Implemented with proof.", "bridge_runs", {"total_tokens": 9}, {"id": "run_impl", "steps": [{"status": "completed"}], "tool_calls": []}

            change_proof = {
                "changed_files": [{"path": "plugins/wasm-agent/server/static_server.py", "status": "modified"}],
                "before_checkpoint": {"ref": "timeline://before", "label": "before"},
                "auto_checkpoint": {"ref": "timeline://after", "label": "after"},
            }

            with patch.dict(os.environ, env, clear=True), \
                patch.object(server_mod, "call_agent_bridge_runs", side_effect=fake_bridge_runs), \
                patch.object(server_mod, "direct_head_change_proof", return_value=change_proof):
                result = server_mod.provider_envelope_run_completion(server, body, user=self.admin())
                run = server_mod.read_agent_run(self.admin(), result["run_id"])["run"]
                events = server_mod.read_agent_run_events(self.admin(), result["run_id"])["events"]

            self.assertEqual(run["status"], "completed")
            self.assertEqual(run["bridge_obligation"]["state"], "satisfied")
            self.assertEqual(run["bridge_obligation"]["bridge_run_id"], "run_impl")
            self.assertIn("OBL run=run_impl s=satisfied proof=files,timeline", run["bridge_obligation"]["summary"])
            self.assertTrue(any(event["payload"].get("bridge_obligation") for event in events))
            preview = json.dumps(run["final"].get("context_preview", []))
            self.assertIn("OBL run=run_impl", preview)
            self.assertNotIn("final_json", preview)
            self.assertNotIn("bridge_trace", preview)
            self.assertNotIn("diff", preview)
            self.assertNotIn("logs", preview)

    def test_direct_head_interrupted_bridge_obligation_cannot_complete_successfully(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "decision": "dispatch",
                            "actions": [{
                                "action": "dispatch.hermes",
                                "objective": "Fix the avatar-chat bridge lifecycle bug.",
                                "caps": ["repo.read", "repo.edit", "proof.report"],
                                "proof": ["files", "timeline"],
                            }],
                        })
                    }
                }],
                "usage": {"total_tokens": 5},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            server = type("FakeServer", (), {"bridge_url": "http://bridge.example"})()
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-impl-interrupted",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-impl-interrupted",
                    "objective": "Fix lifecycle guard.",
                    "allowed_actions": [{"id": "dispatch.hermes"}],
                },
            }

            def interrupted_bridge(*_args, **_kwargs):
                raise server_mod.BrowserError("agent_run_interrupted", "Agent run was interrupted by a server restart.")

            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs", side_effect=interrupted_bridge):
                with self.assertRaises(server_mod.BrowserError):
                    server_mod.provider_envelope_run_completion(server, body, user=self.admin())
                runs = server_mod.list_agent_runs(self.admin(), {"session_id": ["direct-session"]})["runs"]
                run = next(item for item in runs if item["turn_id"] == "direct-impl-interrupted")
                loaded = server_mod.read_agent_run(self.admin(), run["run_id"])["run"]

            self.assertEqual(loaded["status"], "failed")
            self.assertEqual(loaded["error"]["code"], "agent_run_interrupted")
            self.assertEqual(loaded["bridge_obligation"]["state"], "interrupted")
            self.assertEqual(loaded["bridge_obligation"]["err_code"], "agent_run_interrupted")

    def test_direct_head_missing_proof_blocks_successful_finalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, ProviderStub() as stub:
            ProviderStubHandler.body = {
                "model": "stub-model",
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "decision": "dispatch",
                            "actions": [{
                                "action": "dispatch.hermes",
                                "objective": "Implement a source change.",
                                "caps": ["repo.read", "repo.edit", "proof.report"],
                                "proof": ["files", "timeline"],
                            }],
                        })
                    }
                }],
                "usage": {"total_tokens": 5},
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            server = type("FakeServer", (), {"bridge_url": "http://bridge.example"})()
            body = {
                "session_id": "direct-session",
                "turn_id": "direct-impl-missing-proof",
                "provider_config": self.body(stub.base_url)["provider_config"],
                "envelope": {
                    "trace_id": "trace-impl-missing-proof",
                    "objective": "Implement source change.",
                    "allowed_actions": [{"id": "dispatch.hermes"}],
                },
            }

            def fake_bridge_runs(*_args, **_kwargs):
                return "Text without proof.", "bridge_runs", {"total_tokens": 9}, {"id": "run_missing", "steps": [{"status": "completed"}]}

            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs", side_effect=fake_bridge_runs):
                result = server_mod.provider_envelope_run_completion(server, body, user=self.admin())
                run = server_mod.read_agent_run(self.admin(), result["run_id"])["run"]

            self.assertEqual(run["status"], "failed")
            self.assertEqual(run["error"]["code"], "missing_proof:files,timeline")
            self.assertEqual(run["bridge_obligation"]["state"], "blocked")
            self.assertIn("OBL run=run_missing s=blocked proof=files,timeline", run["bridge_obligation"]["summary"])

    def test_direct_head_without_server_provider_key_dispatches_hermes_directly(self) -> None:
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
                return "Hermes direct fallback.", "bridge_runs", {"total_tokens": 7}, {"id": "run_fallback", "steps": [], "tool_calls": []}

            with patch.dict(os.environ, env, clear=True), patch.object(server_mod, "call_agent_bridge_runs", side_effect=fake_bridge_runs):
                result = server_mod.provider_envelope_run_completion(server, body, user=self.admin())

                self.assertEqual(result["reply"], "Hermes direct fallback.")
                self.assertTrue(result["parsed"]["provider_head_unavailable"])
                self.assertEqual(result["hermes_dispatch"]["source"], "bridge_runs")
                self.assertEqual(result["hermes_dispatch"]["target_node"], "orchestrator")
                events = server_mod.read_agent_run_events(self.admin(), result["run_id"])["events"]
                event_types = [event["type"] for event in events]
                self.assertIn("head.decision", event_types)
                self.assertIn("hermes.dispatch", event_types)
                self.assertIn("hermes.progress", event_types)
                self.assertEqual(event_types[-1], "run.final")

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
                    "objective": "Decide whether Hermes should act.",
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
