#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


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
            self.assertIn('"objective":"Decide the next Hermes head action."', sent_context)
            self.assertIn('"secret_token":"[redacted]"', sent_context)
            self.assertNotIn("super-secret", sent_context)
            self.assertNotIn("test-key", sent_context)

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
