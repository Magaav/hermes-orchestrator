#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import time
import unittest
from unittest import mock

import codex_subscription_provider as provider


class CodexSubscriptionProviderTests(unittest.TestCase):
    def test_decision_thread_rotation_is_bounded(self) -> None:
        self.assertFalse(provider.decision_thread_rotation_due(3))
        self.assertTrue(provider.decision_thread_rotation_due(4))

    def test_rotation_starts_fresh_thread_and_preserves_tool_contract(self) -> None:
        worker = provider._AppServerWorker.__new__(provider._AppServerWorker)
        worker.thread_params = {"model": "gpt-5.6-luna", "sandbox": "read-only"}
        worker.thread_id = "old"
        worker.turn_count = 4
        worker.compaction_status = "completed"
        worker.resumed = True
        worker.fork_reason = ""
        worker._send = mock.Mock(return_value=7)
        worker._response = mock.Mock(return_value={"thread": {"id": "fresh"}})
        worker._persist = mock.Mock()

        worker._rotate_thread(123.0, "bounded_decision_turns")

        self.assertEqual(worker.thread_id, "fresh")
        self.assertEqual(worker.turn_count, 0)
        self.assertEqual(worker.compaction_status, "none")
        self.assertFalse(worker.resumed)
        self.assertEqual(worker.fork_reason, "bounded_decision_turns")
        worker._send.assert_called_once_with("thread/start", {
            "model": "gpt-5.6-luna", "sandbox": "read-only", "ephemeral": False,
            "serviceName": "wasm-agent-master-frontier",
        })
        worker._persist.assert_called_once()

    def test_decision_thread_disables_codex_owned_capability_surfaces(self) -> None:
        self.assertEqual(provider.DECISION_THREAD_ISOLATION, {
            "dynamicTools": [],
            "environments": [],
            "selectedCapabilityRoots": [],
            "personality": "none",
        })
        with mock.patch.dict(provider.os.environ, {"MF_CODEX_DECISION_THREAD_ISOLATION": "0"}):
            self.assertEqual(provider.decision_thread_isolation(), {})

    def test_initialize_negotiates_experimental_isolation_fields(self) -> None:
        worker = provider._AppServerWorker.__new__(provider._AppServerWorker)
        worker.notifications = []
        worker._send = mock.Mock(side_effect=[1, 2])
        worker._response = mock.Mock(side_effect=provider.CodexAppServerFailure("stop after initialize"))
        with self.assertRaisesRegex(provider.CodexAppServerFailure, "stop after initialize"):
            worker._initialize()
        worker._send.assert_called_once_with("initialize", {
            "clientInfo": {
                "name": "wasm_agent_master_frontier", "title": "WASM Agent Master Frontier", "version": "6",
            },
            "capabilities": {"experimentalApi": True},
        })

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

    def test_tool_arguments_accept_json_text_or_structured_object(self) -> None:
        self.assertEqual(provider._tool_arguments('{"query":"browser"}'), {"query": "browser"})
        self.assertEqual(provider._tool_arguments({"query": "browser"}), {"query": "browser"})

    def test_tool_arguments_reject_non_object_payloads(self) -> None:
        with self.assertRaisesRegex(provider.CodexDecisionContractFailure, "non-object"):
            provider._tool_arguments('["browser"]')
        with self.assertRaisesRegex(provider.CodexDecisionContractFailure, "invalid"):
            provider._tool_arguments("{broken")

    def test_prompt_requires_complete_json_object_tool_arguments(self) -> None:
        prompt = provider._prompt([], [{"function": {"name": "read"}}], False, False)
        self.assertIn("one complete valid JSON object, never a fragment", prompt)

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

    def test_worker_key_survives_tool_contract_change(self) -> None:
        self.assertEqual(
            provider._worker_key("session", "route", "model", [{"function": {"name": "read"}}]),
            provider._worker_key("session", "route", "model", [{"function": {"name": "inspect"}}]),
        )

    def test_compaction_requests_native_app_server_operation(self) -> None:
        worker = provider._AppServerWorker.__new__(provider._AppServerWorker)
        worker.thread_id = "thread-1"
        worker.compaction_generation = 1
        worker.compaction_status = "none"
        worker._send = mock.Mock(return_value=9)
        worker._response = mock.Mock(return_value={})
        worker._persist = mock.Mock()
        worker._compact(100)
        worker._send.assert_called_once_with("thread/compact/start", {"threadId": "thread-1"})
        self.assertEqual(worker.compaction_generation, 2)
        self.assertEqual(worker.compaction_status, "requested")

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

    def test_status_contract_requires_model_and_context_window(self) -> None:
        with self.assertRaisesRegex(provider.CodexAppServerFailure, "resolved model"):
            provider._enforce_status_telemetry({}, "", {})
        with self.assertRaisesRegex(provider.CodexAppServerFailure, "context window"):
            provider._enforce_status_telemetry({}, "unknown-model", {})

    def test_status_contract_marks_optional_weekly_limit_as_provider_omitted(self) -> None:
        usage = provider._enforce_status_telemetry({}, "gpt-5.6-luna", {})
        self.assertEqual(usage["model"], "gpt-5.6-luna")
        self.assertEqual(usage["context_window_tokens"], 258400)
        self.assertEqual(usage["status_telemetry"]["seven_day"]["status"], "provider_omitted")
        self.assertEqual(usage["status_telemetry"]["context_window"]["source"], "model_capability_registry")

    def test_status_contract_preserves_reported_weekly_limit(self) -> None:
        usage = provider._enforce_status_telemetry(
            {"context_window_tokens": 258400}, "gpt-5.6-luna",
            {"seven_day": {"percent_left": 64}}, context_window_source="codex_app_server.token_usage",
        )
        self.assertEqual(usage["status_telemetry"]["seven_day"]["status"], "reported")
        self.assertEqual(usage["status_telemetry"]["seven_day"]["percent_left"], 64)

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

    def test_read_drains_multiple_json_lines_from_one_pipe_burst(self) -> None:
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import sys,time; "
                    "sys.stdout.buffer.write(b'{\\\"n\\\":1}\\n{\\\"n\\\":2}\\n'); "
                    "sys.stdout.buffer.flush(); time.sleep(1)"
                ),
            ],
            stdout=subprocess.PIPE,
            bufsize=0,
        )
        worker = provider._AppServerWorker.__new__(provider._AppServerWorker)
        worker.process = process
        worker.stdout_buffer = bytearray()
        try:
            self.assertEqual(worker._read(time.monotonic() + 0.5), {"n": 1})
            self.assertEqual(worker._read(time.monotonic() + 0.2), {"n": 2})
        finally:
            process.terminate()
            process.wait(timeout=2)
            process.stdout.close()

    def test_missing_app_server_executable_fails_without_alternate_transport(self) -> None:
        with mock.patch.object(provider, "resolve_codex_executable", return_value=""):
            with self.assertRaisesRegex(provider.CodexAppServerFailure, "executable is unavailable"):
                provider.complete([], [], completion_only=True, timeout=5)

    def test_stale_configured_executable_falls_through_to_path(self) -> None:
        with mock.patch.object(provider.shutil, "which", return_value="/working/codex"), mock.patch.object(
            provider.os.path, "isfile", side_effect=lambda value: value == "/working/codex",
        ), mock.patch.object(provider.os, "access", return_value=True):
            self.assertEqual(provider.resolve_codex_executable("/stale/codex"), "/working/codex")

    def test_cold_worker_timeout_retries_once_inside_total_deadline(self) -> None:
        first = mock.Mock(turn_count=0)
        first.complete.side_effect = provider.CodexAppServerFailure("Codex app-server response timed out.")
        second = mock.Mock(turn_count=0)
        second.complete.return_value = {"reply": "recovered"}
        with mock.patch.object(provider, "resolve_codex_executable", return_value="/codex"), mock.patch.object(
            provider, "_worker", side_effect=[first, second],
        ) as worker_factory, mock.patch.object(provider, "_discard_worker") as discard:
            result = provider.complete([], [], completion_only=True, timeout=90)

        self.assertEqual(result["reply"], "recovered")
        self.assertEqual(worker_factory.call_count, 2)
        self.assertEqual(worker_factory.call_args_list[0].args[3], "gpt-5.6-luna")
        self.assertEqual(worker_factory.call_args_list[1].args[3], provider.LUNA_RECOVERY_MODEL)
        self.assertEqual(first.complete.call_args.kwargs["timeout"], provider.PRIMARY_ATTEMPT_MAX_SEC)
        self.assertGreater(second.complete.call_args.kwargs["timeout"], 0)
        discard.assert_called_once_with(mock.ANY, first)

    def test_established_worker_timeout_replays_full_contract_on_fresh_worker(self) -> None:
        first = mock.Mock(turn_count=1)
        first.complete.side_effect = provider.CodexAppServerFailure("Codex app-server response timed out.")
        second = mock.Mock(turn_count=0)
        second.complete.return_value = {"reply": "recovered established turn"}
        messages = [{"role": "system", "content": "stable"}, {"role": "user", "content": "state"}]
        tools = [{"function": {"name": "inspect"}}]
        with mock.patch.object(provider, "resolve_codex_executable", return_value="/codex"), mock.patch.object(
            provider, "_worker", side_effect=[first, second],
        ) as worker_factory, mock.patch.object(provider, "_discard_worker") as discard:
            result = provider.complete(messages, tools, completion_only=False, timeout=90)

        self.assertEqual(result["reply"], "recovered established turn")
        self.assertEqual(first.complete.call_args.kwargs["timeout"], provider.PRIMARY_ATTEMPT_MAX_SEC)
        self.assertEqual(second.complete.call_args.args, (messages, tools))
        self.assertGreater(second.complete.call_args.kwargs["timeout"], 0)
        self.assertEqual(worker_factory.call_count, 2)
        self.assertEqual(worker_factory.call_args_list[0].args[3], "gpt-5.6-luna")
        self.assertEqual(worker_factory.call_args_list[1].args[3], provider.LUNA_RECOVERY_MODEL)
        discard.assert_called_once_with(mock.ANY, first)

    def test_non_luna_timeout_recovers_with_the_requested_model(self) -> None:
        first = mock.Mock(turn_count=1)
        first.complete.side_effect = provider.CodexAppServerFailure("Codex app-server response timed out.")
        second = mock.Mock(turn_count=0)
        second.complete.return_value = {"reply": "terra recovered"}
        with mock.patch.object(provider, "resolve_codex_executable", return_value="/codex"), mock.patch.object(
            provider, "_worker", side_effect=[first, second],
        ) as worker_factory, mock.patch.object(provider, "_discard_worker"):
            provider.complete([], [], completion_only=True, timeout=90, model="gpt-5.6-terra")
        self.assertEqual([call.args[3] for call in worker_factory.call_args_list], ["gpt-5.6-terra", "gpt-5.6-terra"])

    def test_non_timeout_provider_failure_is_not_retried(self) -> None:
        worker = mock.Mock(turn_count=1)
        worker.complete.side_effect = provider.CodexAppServerFailure("Codex emitted invalid output.")
        with mock.patch.object(provider, "resolve_codex_executable", return_value="/codex"), mock.patch.object(
            provider, "_worker", return_value=worker,
        ) as worker_factory, mock.patch.object(provider, "_discard_worker"):
            with self.assertRaisesRegex(provider.CodexAppServerFailure, "invalid output"):
                provider.complete([], [], completion_only=True, timeout=90)

        worker_factory.assert_called_once()

    def test_invalid_native_tool_json_replays_once_on_fresh_worker(self) -> None:
        first = mock.Mock(turn_count=1)
        first.complete.side_effect = provider.CodexDecisionContractFailure(
            "Codex emitted invalid native-tool argument JSON."
        )
        second = mock.Mock(turn_count=0)
        second.complete.return_value = {
            "reply": "continuing", "tool_calls": [{"name": "discover", "arguments": {"query": "codebase"}}],
        }
        messages = [{"role": "system", "content": "contract"}, {"role": "user", "content": "state"}]
        tools = [{"function": {"name": "discover"}}]
        with mock.patch.object(provider, "resolve_codex_executable", return_value="/codex"), mock.patch.object(
            provider, "_worker", side_effect=[first, second],
        ) as worker_factory, mock.patch.object(provider, "_discard_worker") as discard:
            result = provider.complete(
                messages, tools, completion_only=False, timeout=90,
                session_key="agent_msyjw6ie_j69f94", route_id="wasm-agent.avatar-chat.ui",
            )

        self.assertEqual(result["tool_calls"][0]["arguments"], {"query": "codebase"})
        self.assertEqual(worker_factory.call_count, 2)
        self.assertEqual(second.complete.call_args.args, (messages, tools))
        discard.assert_called_once_with(mock.ANY, first)

    def test_invalid_native_tool_json_is_retried_only_once(self) -> None:
        workers = [mock.Mock(turn_count=1), mock.Mock(turn_count=0)]
        for worker in workers:
            worker.complete.side_effect = provider.CodexDecisionContractFailure(
                "Codex emitted invalid native-tool argument JSON."
            )
        with mock.patch.object(provider, "resolve_codex_executable", return_value="/codex"), mock.patch.object(
            provider, "_worker", side_effect=workers,
        ) as worker_factory, mock.patch.object(provider, "_discard_worker") as discard:
            with self.assertRaisesRegex(provider.CodexDecisionContractFailure, "invalid native-tool"):
                provider.complete([], [{"function": {"name": "discover"}}], completion_only=False, timeout=90)

        self.assertEqual(worker_factory.call_count, 2)
        self.assertEqual(discard.call_count, 2)


if __name__ == "__main__":
    unittest.main()
