#!/usr/bin/env python3
"""Contract tests for Visão's internal Master:frontier image envelope."""

from __future__ import annotations

import base64
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parent))

import studio_master_frontier as frontier
from studio_runtime import CodexCredentials


PNG = b"\x89PNG\r\n\x1a\nvisao-proof"


def sse(*events: dict[str, object]) -> bytes:
    return b"".join(
        b"data: " + json.dumps(event, separators=(",", ":")).encode() + b"\n\n"
        for event in events
    ) + b"data: [DONE]\n\n"


class FakeResponse(io.BytesIO):
    headers = {"x-request-id": "request-1"}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class StudioMasterFrontierTest(unittest.TestCase):
    def test_envelope_is_bounded_owned_and_declares_reconstruction_rules(self) -> None:
        envelope = frontier.studio_envelope(
            media_type="image/jpeg",
            source_bytes=123,
            watermark_authorized=False,
            trace_id="trace-1",
        )

        self.assertEqual(envelope["schema"], "visao.studio.master_frontier.envelope.v1")
        self.assertEqual(envelope["model"], "master:frontier")
        self.assertEqual(envelope["allowed_actions"], [{"name": "image.generate.edit", "max_calls": 1}])
        serialized = json.dumps(envelope)
        self.assertIn("Preserve every watermark", serialized)
        self.assertIn("loose floor dirt", serialized)
        self.assertNotIn("image_base64", serialized)
        self.assertNotIn("/local/plugins/wasm-agent", serialized)

    def test_reconstruct_uses_one_codex_image_edit_and_real_reported_usage(self) -> None:
        captured: dict[str, object] = {}
        image_item = {
            "id": "image-1",
            "type": "image_generation_call",
            "status": "completed",
            "result": base64.b64encode(PNG).decode(),
            "usage": {
                "input_tokens": 100,
                "output_tokens": 200,
                "total_tokens": 300,
                "input_tokens_details": {"text_tokens": 20, "image_tokens": 80},
            },
        }
        completed = {
            "id": "response-1",
            "status": "completed",
            "output": [image_item],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30,
                "input_tokens_details": {"cached_tokens": 4},
            },
        }

        def opener(request: object, *, timeout: int) -> FakeResponse:
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse(
                sse(
                    {"type": "response.output_item.done", "item": image_item},
                    {"type": "response.completed", "response": completed},
                )
            )

        progress: list[str] = []
        body = {
            "cloud_consent": True,
            "watermark_authorized": False,
            "media_type": "image/png",
            "image_base64": base64.b64encode(PNG).decode(),
        }
        credentials = CodexCredentials("codex-access-token", "account-1")
        with patch.object(frontier, "codex_credentials", return_value=credentials):
            result = frontier.reconstruct(
                body,
                opener=opener,
                progress=lambda stage, _detail: progress.append(stage),
            )

        request = captured["request"]
        wire = json.loads(request.data)
        self.assertEqual(wire["model"], "gpt-5.5")
        self.assertFalse(wire["store"])
        self.assertTrue(wire["stream"])
        self.assertEqual(wire["tools"], [{"type": "image_generation", "action": "edit", "quality": "high"}])
        self.assertEqual(
            sum(
                item.get("type") == "input_image"
                for message in wire["input"]
                for item in message["content"]
            ),
            1,
        )
        self.assertEqual(request.get_header("Authorization"), "Bearer codex-access-token")
        self.assertEqual(request.get_header("Chatgpt-account-id"), "account-1")
        self.assertEqual(base64.b64decode(result["image_base64"]), PNG)
        self.assertEqual(result["model"], "master:frontier")
        self.assertEqual(result["proof"]["response_id"], "response-1")
        self.assertEqual(
            result["proof"]["usage"],
            {
                "available": True,
                "complete": True,
                "source": "provider_reported",
                "main_available": True,
                "image_available": True,
                "main_input_tokens": 10,
                "cached_main_input_tokens": 4,
                "main_output_tokens": 20,
                "reasoning_output_tokens": 0,
                "image_input_tokens": 100,
                "image_output_tokens": 200,
                "image_text_input_tokens": 20,
                "image_source_input_tokens": 80,
                "total_tokens": 330,
            },
        )
        self.assertEqual(
            progress,
            ["accepted", "envelope-starting", "reconstructing", "artifact-generated", "finalizing"],
        )

    def test_usage_remains_real_and_partial_when_image_item_has_no_usage(self) -> None:
        usage = frontier._normalized_usage(  # pylint: disable=protected-access
            {
                "usage": {
                    "input_tokens": 4000,
                    "output_tokens": 102,
                    "total_tokens": 4102,
                }
            },
            {"type": "image_generation_call", "result": "image"},
        )

        self.assertTrue(usage["available"])
        self.assertFalse(usage["complete"])
        self.assertTrue(usage["main_available"])
        self.assertFalse(usage["image_available"])
        self.assertEqual(usage["total_tokens"], 4102)

    def test_provider_rejection_is_typed_and_redacted(self) -> None:
        def opener(request: object, *, timeout: int) -> FakeResponse:
            raise HTTPError(request.full_url, 401, "private provider detail", {}, None)

        body = {
            "cloud_consent": True,
            "media_type": "image/jpeg",
            "image_base64": base64.b64encode(b"\xff\xd8\xffproof").decode(),
        }
        credentials = CodexCredentials("codex-secret-token", "account-1")
        with patch.object(frontier, "codex_credentials", return_value=credentials):
            with self.assertRaises(frontier.StudioEnvelopeError) as raised:
                frontier.reconstruct(body, opener=opener)

        self.assertEqual(raised.exception.code, "studio_codex_reconnect_required")
        self.assertNotIn("private provider detail", raised.exception.message)
        self.assertNotIn("secret-token", raised.exception.message)


if __name__ == "__main__":
    unittest.main()
