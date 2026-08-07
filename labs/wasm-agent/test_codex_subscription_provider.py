#!/usr/bin/env python3
from __future__ import annotations

import unittest
from unittest import mock

import codex_subscription_provider as provider


class CodexSubscriptionProviderTests(unittest.TestCase):
    def test_schema_limits_tool_names(self) -> None:
        schema = provider._schema(["search", "read"])
        name = schema["properties"]["tool_calls"]["items"]["properties"]["name"]
        self.assertEqual(name["enum"], ["search", "read"])

    def test_prompt_denies_codex_owned_tools(self) -> None:
        prompt = provider._prompt([], [{"function": {"name": "read"}}], False, True)
        self.assertIn("Do not inspect files, run commands, browse, call MCP", prompt)
        self.assertIn("enclosing V5 host exclusively executes", prompt)
        self.assertIn("Select exactly one declared native tool", prompt)

    def test_tool_observation_allows_grounded_final(self) -> None:
        prompt = provider._prompt(
            [{"role": "tool", "content": "bounded evidence"}],
            [{"function": {"name": "read"}}],
            False,
            False,
        )
        self.assertIn("return the final reply grounded in prior observations", prompt)

    def test_tool_decision_requires_public_progress_update(self) -> None:
        prompt = provider._prompt([], [{"function": {"name": "read"}}], False, False)
        self.assertIn("user-visible progress update", prompt)

    def test_continuation_sends_changed_state_without_stable_contract(self) -> None:
        prompt = provider._continuation_prompt([
            {"role": "system", "content": "stable contract"},
            {"role": "user", "content": "latest state"},
        ], completion_only=False, require_tool=False)
        self.assertNotIn("stable contract", prompt)
        self.assertNotIn('"tools"', prompt)
        self.assertIn("latest state", prompt)
        self.assertIn("supersedes prior host state", prompt)

    def test_worker_key_is_stable_and_scoped_by_session(self) -> None:
        tools = [{"function": {"name": "read"}}]
        first = provider._worker_key("session-a", "route", "model", tools)
        self.assertEqual(first, provider._worker_key("session-a", "route", "model", tools))
        self.assertNotEqual(first, provider._worker_key("session-b", "route", "model", tools))

    def test_rate_limit_projection_uses_secondary_seven_day_window(self) -> None:
        projected = provider._rate_limits_from_app_server({"rateLimits": {"primary": {
            "usedPercent": 61, "resetsAt": 1786492800, "windowDurationMins": 10080,
        }, "secondary": None}})
        self.assertEqual(projected["seven_day"]["percent_left"], 39)
        self.assertEqual(projected["seven_day"]["resets_at"], 1786492800)

    def test_usage_projection_retains_app_server_context_window(self) -> None:
        usage = provider._usage_from_app_server({"inputTokens": 205703, "totalTokens": 205703}, "terra")
        usage["context_window_tokens"] = 258000
        self.assertEqual(usage["context_window_tokens"], 258000)

    def test_response_preserves_notifications_that_arrive_first(self) -> None:
        worker = provider._AppServerWorker.__new__(provider._AppServerWorker)
        worker.notifications = []
        messages = iter([
            {"method": "item/completed", "params": {"item": {"type": "agentMessage"}}},
            {"id": 7, "result": {"turn": {"id": "turn-1"}}},
        ])
        worker._read = mock.Mock(side_effect=lambda _deadline: next(messages))
        self.assertEqual(worker._response(7, 1)["turn"]["id"], "turn-1")
        self.assertEqual(worker._notification(1)["method"], "item/completed")

    def test_missing_app_server_executable_fails_without_alternate_transport(self) -> None:
        with mock.patch.dict(provider.os.environ, {"MF5_CODEX_EXECUTABLE": ""}), mock.patch.object(
            provider.shutil, "which", return_value=None,
        ):
            with self.assertRaisesRegex(provider.CodexAppServerFailure, "executable is unavailable"):
                provider.complete([], [], completion_only=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
