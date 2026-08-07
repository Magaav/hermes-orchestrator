#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
import unittest
from unittest import mock
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier import provider_step  # noqa: E402


STATIC_SERVER_PATH = SERVER / "static_server.py"


class V6ProviderStepTests(unittest.TestCase):
    def test_subscription_uses_configured_lower_codex_model(self) -> None:
        captured = {}
        module = types.SimpleNamespace(complete=lambda *args, **kwargs: captured.update(kwargs) or {"reply": "ok"})
        with mock.patch.dict(sys.modules, {"codex_subscription_provider": module}), mock.patch.dict(
            os.environ,
            {"HERMES_WASM_AGENT_FRONTIER_PROVIDER": "codex_subscription", "WASM_AGENT_CODEX_MODEL": "gpt-5.5"},
            clear=False,
        ), mock.patch.dict(os.environ, {"MASTER_FRONTIER_CODEX_MODEL": "", "MF5_CODEX_MODEL": ""}):
            provider_step.complete(
                {}, object(), {}, {}, {"messages": [], "tools": []},
                protocol="v6", receiver="openai-codex", run_id="run", user=None,
            )
        self.assertEqual(captured["model"], "gpt-5.5")

    def test_protocol_state_precedes_redundant_route_and_tool_metadata(self) -> None:
        captured = {}

        def complete(_server, body, envelope, **kwargs):
            captured.update({"body": body, "envelope": envelope, "kwargs": kwargs})
            return {"reply": "ok"}

        tools = [{"type": "function", "function": {
            "name": "discover", "description": "Search capabilities",
            "parameters": {"type": "object"},
        }}]
        result = provider_step.complete(
            {"openai_responses_completion": complete}, object(),
            {"message": "change the repository"},
            {
                "objective": "change the repository", "route_id": "fixture.v6",
                "route_contract": {"noise": "route-junk" * 2_000},
            },
            {
                "messages": [
                    {"role": "system", "content": "V6 instructions"},
                    {"role": "user", "content": "MF6/1\nG\t\"change\""},
                ],
                "tools": tools, "tool_choice": "auto",
            },
            protocol="v6", receiver="openai-codex", run_id="run-1", user={"id": "1"},
        )

        self.assertEqual(result, {"reply": "ok"})
        envelope = captured["envelope"]
        self.assertNotIn("route_contract", envelope)
        self.assertNotIn("tools", envelope["compact_state"])
        self.assertEqual(captured["body"]["tools"], tools)
        serialized_prefix = json.dumps(envelope, ensure_ascii=True, separators=(",", ":"))[:3_200]
        self.assertIn("MF6/1", serialized_prefix)
        self.assertNotIn("route-junk", serialized_prefix)

    def test_v6_gets_protocol_sized_input_and_keeps_legacy_limit(self) -> None:
        self.assertEqual(
            provider_step.direct_envelope_limit({"schema": provider_step.V6_PROVIDER_SCHEMA}, 3_200),
            128_000,
        )
        self.assertEqual(
            provider_step.direct_envelope_limit({"schema": "hermes.wasm_agent.master_frontier.v5.provider.v1"}, 3_200),
            3_200,
        )

    def test_host_preserves_large_v6_protocol_projection(self) -> None:
        spec = importlib.util.spec_from_file_location("mf6_provider_step_static_server", STATIC_SERVER_PATH)
        assert spec and spec.loader
        static_server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(static_server)
        payload = "MF6/1\nP\tdata\tuntrusted-data\t" + ("x" * 8_000) + "TAIL"
        v6 = {
            "schema": provider_step.V6_PROVIDER_SCHEMA,
            "compact_state": {"messages": [{"role": "user", "content": payload}]},
        }
        legacy = {**v6, "schema": "hermes.wasm_agent.master_frontier.v5.provider.v1"}

        v6_text = static_server.openai_direct_envelope_text({"receiver": "openai-codex"}, v6)
        legacy_text = static_server.openai_direct_envelope_text({"receiver": "openai-codex"}, legacy)

        self.assertIn("TAIL", v6_text)
        self.assertGreater(len(v6_text), 8_000)
        self.assertNotIn("TAIL", legacy_text)

    def test_stream_run_context_preserves_bounded_transcript(self) -> None:
        spec = importlib.util.spec_from_file_location("mf6_transcript_static_server", STATIC_SERVER_PATH)
        assert spec and spec.loader
        static_server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(static_server)
        transcript = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
        context = static_server.provider_envelope_run_context({
            "protocol": "v6", "session_id": "s", "turn_id": "t", "transcript": transcript,
            "envelope": {"schema": "hermes.wasm_agent.master_frontier.v6", "objective": "again"},
        })
        self.assertEqual(context["run_body"]["transcript"], transcript)

    def test_legacy_provider_projection_keeps_nested_tools_and_route(self) -> None:
        captured = {}
        tools = [{"type": "function", "name": "read"}]
        provider_step.complete(
            {
                "openai_responses_completion": (
                    lambda _server, body, envelope, **_kwargs:
                    captured.update({"body": body, "envelope": envelope}) or {"reply": "ok"}
                ),
            },
            object(), {"message": "read"},
            {"objective": "read", "route_id": "fixture.v5", "route_contract": {"route_id": "fixture.v5"}},
            {"messages": [{"role": "user", "content": "MF5"}], "tools": tools, "tool_choice": "auto"},
            protocol="v5", receiver="openai-codex", run_id="run-v5", user={"id": "1"},
        )

        self.assertEqual(captured["envelope"]["route_contract"], {"route_id": "fixture.v5"})
        self.assertEqual(captured["envelope"]["compact_state"]["tools"], tools)


if __name__ == "__main__":
    unittest.main()
