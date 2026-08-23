#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import sqlite3
import unittest
from http import HTTPStatus
from pathlib import Path
import sys


SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER))

from master_frontier import controller_v6, repository_actions, repository_checks, repository_diff  # noqa: E402
from master_frontier.v6 import projection  # noqa: E402


def call(name, arguments, reply=""):
    return {"reply": reply, "tool_calls": [{"id": f"call-{name}", "name": name, "arguments": arguments}], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}


class RuntimeFixture:
    HTTPStatus = HTTPStatus

    def __init__(self, route, decisions, clients=None, db_path=None, command_result=None):
        self.route = route
        self.decisions = list(decisions)
        self.clients = clients or []
        self.events = []
        self.finished = []
        self.commands = []
        self.kernel_actions = []
        self.provider_bodies = []
        self.command_result = command_result or {"ok": True}
        self.db_path = Path(db_path) if db_path else Path(tempfile.mkdtemp(prefix="mf6-owned-")) / "state.sqlite3"

    def values(self):
        return {
            "HTTPStatus": self.HTTPStatus,
            "require_direct_envelope_route_contract": lambda _envelope: self.route,
            "direct_envelope_error": lambda code, message, _status: (_ for _ in ()).throw(controller_v6.V6Error(code, message)),
            "user_id": lambda user: str((user or {}).get("id") or "anonymous"),
            "append_agent_run_event": self.append,
            "provider_config_for_proxy_body": lambda _body: {},
            "provider_proxy_completion": self.provider,
            "append_envelope_v2_inference_usage": lambda *_args, **_kwargs: [],
            "record_agent_run_token_usage_event": lambda *_args, **_kwargs: None,
            "finish_agent_run": self.finish,
            "native_control_clients_payload": lambda _server: {"clients": self.clients},
            "create_native_control_command": self.command,
            "native_control_command_path": lambda _server, device, command: f"{device}/{command}",
            "read_json_file": lambda _path, _fallback: {"status": "finished", "result": self.command_result},
            "auth_connect": self.connect,
            "kernel_inspect_tool": lambda *_args, **_kwargs: {"ok": True},
            "kernel_act_tool": self.kernel_act,
            "kernel_prove_tool": self.kernel_prove,
        }

    def append(self, _server, run_id, event_type, *, summary="", payload=None):
        self.events.append({"run_id": run_id, "type": event_type, "summary": summary, "payload": payload or {}})

    def provider(self, _server, _body, *, user=None):
        del user
        self.provider_bodies.append(_body)
        decision = self.decisions.pop(0)
        if isinstance(decision, Exception):
            raise decision
        return decision

    def finish(self, _server, run_id, *, status, final=None, error=None):
        self.finished.append({"run_id": run_id, "status": status, "final": final, "error": error})
        return {}

    def command(self, _server, command, _handler, _user):
        self.commands.append(command)
        return {"command_id": "cmd-1"}

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def kernel_act(self, _server, payload, _user):
        self.kernel_actions.append(payload)
        action = payload.get("local_action")
        if action == "patch.apply_scoped":
            return {"ok": True, "result": {"ok": True, "applied": True, "changed_files": ["a.py"]}}
        if action == "test.run_focused":
            return {"ok": True, "result": {"ok": True, "check_id": "focused", "returncode": 0}}
        if action == "git.diff_summary":
            return {"ok": True, "result": {"ok": True, "changed_files": [{"path": "a.py"}]}}
        return {"ok": True}

    def kernel_prove(self, _server, payload, _user):
        self.kernel_actions.append(payload)
        return {"ok": True, "primitive": "kernel.prove"}


class RepositoryAdapterRuntime(RuntimeFixture):
    """Exercise the production repository owners without the HTTP monolith."""

    def __init__(self, route, decisions, *, journal_root):
        super().__init__(route, decisions)
        self.root = Path(route["workspace_root"]).resolve()
        self.journal_root = Path(journal_root)

    def _resolve(self, value):
        candidate = (self.root / str(value)).resolve()
        candidate.relative_to(self.root)
        return candidate

    def _relative(self, path):
        return Path(path).resolve().relative_to(self.root).as_posix()

    def kernel_act(self, _server, payload, _user):
        self.kernel_actions.append(payload)
        action = payload.get("local_action")
        arguments = payload.get("args") if isinstance(payload.get("args"), dict) else {}
        if action == "patch.apply_scoped":
            previous = os.environ.get(repository_actions.TRANSACTION_ROOT_ENV)
            os.environ[repository_actions.TRANSACTION_ROOT_ENV] = str(self.journal_root)
            try:
                result = repository_actions.apply(
                    arguments.get("operations") or [], dry_run=arguments.get("dry_run") is True,
                    resolve=self._resolve, relative=self._relative,
                    max_operations=24, max_file_bytes=1_000_000, max_payload_bytes=1_000_000,
                )
            finally:
                if previous is None:
                    os.environ.pop(repository_actions.TRANSACTION_ROOT_ENV, None)
                else:
                    os.environ[repository_actions.TRANSACTION_ROOT_ENV] = previous
            return {"ok": True, "result": {"ok": True, **result}}
        if action == "test.run_focused":
            check_id = str(arguments.get("check_id") or "")
            check = next(item for item in self.route["checks"] if item["id"] == check_id)
            result = repository_checks.run(
                check["command"], cwd=self.root, timeout_sec=check.get("timeout_sec", 10),
            )
            return {"ok": result["ok"], "result": result}
        if action == "git.diff_summary":
            result = repository_diff.collect(
                self.route, include_paths=arguments.get("paths") if isinstance(arguments.get("paths"), list) else None,
            )
            return {"ok": result["ok"], "result": result}
        return {"ok": False, "code": "fixture_action_missing"}

    def kernel_prove(self, _server, payload, _user):
        self.kernel_actions.append(payload)
        diff = repository_diff.collect(self.route, include_paths=["a.py"])
        return {
            "ok": diff["ok"] and any(item.get("path") == "a.py" for item in diff["changed_files"]),
            "proof": [diff.get("receipt_sha256", "")], "diff": diff,
        }


class V6OwnedControllerTests(unittest.TestCase):
    def test_conceptual_turn_is_answer_only_in_one_provider_call(self) -> None:
        route = {
            "route_id": "fixture.chat", "owner": "fixture", "workspace_root": "/workspace",
            "allowed_read_roots": ["/workspace"], "caps": ["repo.read"],
        }
        runtime = RuntimeFixture(route, [{
            "reply": "Hello!", "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        }])
        result = controller_v6.execute_owned(
            object(), {"message": "Hello", "session_id": "s1"}, user={"id": "u1"},
            run_record={"run_id": "run-chat", "turn_id": "turn-chat"},
            context={"receiver": "provider", "envelope": {
                "objective": "Hello", "task_contract": {
                    "request_class": "model_decision", "evidence_floor": "conceptual",
                },
            }}, runtime=runtime.values(),
        )
        self.assertEqual(result["reply"], "Hello!")
        self.assertEqual(result["diagnostics"]["provider_calls"], 1)
        self.assertEqual(runtime.provider_bodies[0]["tools"], [])
        self.assertEqual(result["diagnostics"]["context"][0]["tool_count"], 0)
        performance = result["diagnostics"]["performance"]
        self.assertEqual(performance["schema"], "master.frontier.v6.performance.v1")
        self.assertEqual(performance["projection"]["calls"], 1)
        self.assertEqual(len(performance["provider_calls"]), 1)
        self.assertIn("host_before_first_provider_ms", performance["phases"])

    def test_conceptual_followup_receives_transcript_bound_prior_terminal_proof(self) -> None:
        route = {
            "route_id": "fixture.ui", "owner": "fixture", "workspace_root": "/workspace",
            "allowed_read_roots": ["/workspace"], "caps": ["client.ui.inspect"],
        }
        prior_reply = "Yes—I can inspect the Browser widget. It is not currently visible. It has WhatsApp loaded."
        runtime = RuntimeFixture(route, [{
            "reply": "Yes. Hidden means it is not drawn, not that native inspection is unavailable.",
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        }])
        with runtime.connect() as conn:
            conn.execute("CREATE TABLE agent_run_tb (run_id TEXT, turn_id TEXT, user_id TEXT, session_id TEXT, protocol TEXT, status TEXT, created_at INTEGER, final_json TEXT)")
            conn.execute("CREATE TABLE agent_run_event_tb (run_id TEXT, user_id TEXT, session_id TEXT, type TEXT, payload_json TEXT)")
            final = {
                "route_id": "fixture.ui", "reply": prior_reply,
                "local_tools": [{"capability": "client.browser.inspect", "status": "acknowledged", "ok": True}],
                "evidence": [{"proof": ["native.web_surface.status"]}],
            }
            conn.execute(
                "INSERT INTO agent_run_tb VALUES (?,?,?,?,?,?,?,?)",
                ("run-prior", "turn-prior", "u1", "s1", "v6", "completed", 1000, json.dumps(final)),
            )
            conn.execute(
                "INSERT INTO agent_run_event_tb VALUES (?,?,?,?,?)",
                ("run-prior", "u1", "s1", "gate.decision", json.dumps({"status": "terminal_result"})),
            )
        result = controller_v6.execute_owned(
            object(), {"message": "If you know it has WhatsApp loaded, you can inspect it.", "session_id": "s1"},
            user={"id": "u1"}, run_record={"run_id": "run-followup", "turn_id": "turn-followup"},
            context={"receiver": "provider", "envelope": {
                "objective": "If you know it has WhatsApp loaded, you can inspect it.",
                "task_contract": {"request_class": "model_decision", "evidence_floor": "conceptual"},
                "compact_state": {"transcript": [
                    {"role": "user", "content": "Can you see the Browser widget opened?"},
                    {"role": "assistant", "content": prior_reply},
                ]},
            }}, runtime=runtime.values(),
        )
        projected = projection.decode(runtime.provider_bodies[0]["messages"][-1]["content"])
        prior = next(item for item in projected["evidence"] if item["kind"] == "prior.terminal_result")
        self.assertIn("Verified prior terminal result (historical;", prior["summary"])
        self.assertIn("proof: native.web_surface.status", prior["summary"])
        self.assertIn("Display visibility and inspection availability are independent", prior["summary"])
        self.assertIn("must not deny the verified prior inspection or its capability", prior["summary"])
        self.assertEqual(result["diagnostics"]["provider_calls"], 1)
        self.assertEqual(runtime.provider_bodies[0]["tools"], [])

    def test_route_scoped_read_uses_hosted_ports_and_exact_accounting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owner.py").write_text("VALUE = 1\n", encoding="utf-8")
            route = {
                "route_id": "fixture.source", "owner": "fixture", "workspace_root": str(root),
                "allowed_read_roots": [str(root)], "caps": ["repo.read"],
            }
            runtime = RuntimeFixture(route, [
                call("discover", {"query": "read exact repository content"}),
                call("execute", {"operations": [{
                    "id": "op.read", "cap": "repo.read", "args": {"path": "owner.py"},
                    "say": {"phase": "investigating", "message": "I found the owning repository. I’m reading the exact file now."},
                }]}),
                {"reply": "owner.py defines VALUE as 1.", "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}},
            ])
            result = controller_v6.execute_owned(
                object(), {"message": "Read owner.py", "session_id": "s1"}, user={"id": "u1"},
                run_record={"run_id": "run-v6", "turn_id": "turn-v6"},
                context={"receiver": "provider", "envelope": {"objective": "Read owner.py", "task_contract": {"request_class": "source_investigation"}}},
                runtime=runtime.values(),
            )
        self.assertEqual(result["protocol"], "v6")
        self.assertEqual(result["reply"], "owner.py defines VALUE as 1.")
        self.assertEqual(result["diagnostics"]["token_usage_total"]["total_tokens"], 340)
        self.assertTrue(result["diagnostics"]["token_usage_total"]["exact"])
        self.assertIn("llm.reason.summary", [item["type"] for item in runtime.events])
        commentary = next(item for item in runtime.events if item["type"] == "llm.reason.summary")
        self.assertEqual(commentary["payload"]["commentary"]["visibility"], "public")
        self.assertEqual(runtime.finished[-1]["status"], "completed")

    def test_source_investigation_completion_is_authority_scoped(self) -> None:
        route = {
            "route_id": "fixture.source", "owner": "fixture", "workspace_root": "/workspace",
            "allowed_read_roots": ["/workspace"], "caps": ["repo.read"],
            "task_contract": {"request_class": "source_investigation"},
        }
        self.assertEqual(
            controller_v6._completion_requirements({}, route), {"authority:repo.read"},
        )
        self.assertEqual(
            controller_v6._completion_requirements(
                {"completion_capabilities": ["repo.read"]}, route,
            ),
            {"repo.read"},
        )

    def test_client_action_completion_requires_goal_correlated_write(self) -> None:
        route = {"task_contract": {"request_class": "client_action"}}
        self.assertEqual(
            controller_v6._completion_requirements({}, route),
            {"goal_action"},
        )

    def test_live_client_widget_operation_is_acknowledged(self) -> None:
        route = {
            "route_id": "fixture.client", "owner": "fixture", "workspace_root": "/workspace",
            "allowed_read_roots": ["/workspace"], "caps": ["client.ui.inspect", "client.ui.control"],
            "client_ui": {
                "widget_ids": ["browser"],
                "operations": ["inspect", "open_widget", "browser_navigate", "command_status"],
            },
        }
        clients = [
            {
                "client_id": "electron-main", "device_id": "electron-main",
                "runtime_type": "electron", "live": True, "capabilities": [],
            },
            {
                "client_id": "electron-renderer", "device_id": "electron-renderer",
                "runtime_type": "electron", "live": True,
                "capabilities": ["control.widget.open", "control.browser.navigate"],
            },
        ]
        runtime = RuntimeFixture(route, [
            call("execute", {"goals": [{"id": "browser-open", "cap": "client.widget.open", "outcome": "Browser widget is open"}], "operations": [{
                "id": "op.open", "cap": "client.widget.open",
                "args": {"widget": "browser", "wait_sec": 0},
                "completes_goal": True, "goal_id": "browser-open",
                "expect": {"acknowledged": True},
                "say": {"phase": "acting", "message": "I found the live Electron client. I’m opening its Browser widget now."},
            }]}),
            call("execute", {"goals": [{"id": "browser-open", "cap": "client.widget.open", "outcome": "Browser widget is open"}], "operations": [{
                "id": "op.open", "cap": "client.widget.open", "args": {"widget": "browser", "wait_sec": 0},
                "completes_goal": True, "goal_id": "browser-open", "expect": {"acknowledged": True},
            }]}),
            {"reply": "The live Electron client acknowledged the Browser widget command.", "usage": {"total_tokens": 50}},
        ], clients=clients)
        result = controller_v6.execute_owned(
            object(), {"message": "Open the Browser widget", "session_id": "s1"}, user={"id": "u1"},
            run_record={"run_id": "run-client", "turn_id": "turn-client"},
            context={"receiver": "provider", "envelope": {
                "objective": "Open the Browser widget", "task_contract": {"request_class": "client_action"},
            }}, runtime=runtime.values(),
        )
        self.assertEqual(result["reply"], "The live Electron client acknowledged the Browser widget command.")
        self.assertEqual(runtime.commands[0]["device_id"], "electron-renderer")
        self.assertEqual(runtime.commands[0]["type"], "open_widget")
        self.assertEqual(runtime.commands[0]["payload"], {"widget_id": "browser"})
        self.assertEqual(result["local_tools"][0]["capability"], "client.widget.open")

    def test_greeting_prefixed_space_open_runs_inference_action_ack_answer_loop(self) -> None:
        route = {
            "route_id": "wasm-agent.avatar-chat.ui", "owner": "plugins/wasm-agent", "workspace_root": "/workspace",
            "allowed_read_roots": ["/workspace"], "caps": ["client.ui.inspect", "client.ui.control"],
            "client_ui": {"widget_ids": ["browser"], "operations": ["inspect", "space_open", "command_status"]},
        }
        clients = [{
            "client_id": "electron-renderer", "device_id": "electron-renderer",
            "runtime_type": "electron", "live": True, "capabilities": ["control.space.open"],
        }]
        runtime = RuntimeFixture(route, [
            call("execute", {"goals": [{"id": "space-open", "cap": "client.space.open", "outcome": "Realure space is open"}], "operations": [{
                "id": "op.open-space", "cap": "client.space.open", "args": {"space": "Realure", "wait_sec": 0},
                "completes_goal": True, "goal_id": "space-open",
                "expect": {"acknowledged": True},
                "say": {"phase": "acting", "message": "I found the live client and I’m opening the Realure space."},
            }]}),
            call("execute", {"goals": [{"id": "space-open", "cap": "client.space.open", "outcome": "Realure space is open"}], "operations": [{
                "id": "op.open-space", "cap": "client.space.open", "args": {"space": "Realure", "wait_sec": 0},
                "completes_goal": True, "goal_id": "space-open", "expect": {"acknowledged": True},
            }]}),
        ], clients=clients, command_result={
            "ok": True, "space_id": "space-realure", "space_name": "Realure", "opened": True,
            "proof": ["client.ack", "client.space.active"],
        })
        result = controller_v6.execute_owned(
            object(), {"message": "hello open realure space", "session_id": "s1"}, user={"id": "u1"},
            run_record={"run_id": "run-space", "turn_id": "turn-space"},
            context={"receiver": "provider", "envelope": {
                "objective": "hello open realure space", "task_contract": {"request_class": "client_action"},
            }}, runtime=runtime.values(),
        )
        self.assertEqual(result["reply"], "Opened the Realure space.")
        self.assertEqual(result["diagnostics"]["provider_calls"], 2)
        self.assertEqual(len(runtime.provider_bodies), 2)
        self.assertEqual(runtime.commands, [{
            "device_id": "electron-renderer", "type": "space_open", "payload": {"space": "Realure"},
            "reason": "master-frontier-client-ui",
        }])
        self.assertEqual(result["local_tools"][0]["capability"], "client.space.open")
        self.assertIn("client.space.active", {proof for item in result["evidence"] for proof in item.get("proof", [])})

    def test_compound_client_goals_require_both_correlated_receipts(self) -> None:
        route = {
            "route_id": "wasm-agent.avatar-chat.ui", "owner": "plugins/wasm-agent", "workspace_root": "/workspace",
            "allowed_read_roots": ["/workspace"], "caps": ["client.ui.inspect", "client.ui.control"],
            "client_ui": {"widget_ids": ["browser"], "operations": ["space_open", "open_widget", "command_status"]},
        }
        clients = [{
            "client_id": "electron-renderer", "device_id": "electron-renderer", "runtime_type": "electron", "live": True,
            "capabilities": ["control.space.open", "control.widget.open"], "widget_ids": ["browser"],
        }]
        runtime = RuntimeFixture(route, [
            call("execute", {"goals": [
                {"id": "space-open", "cap": "client.space.open", "outcome": "Realure space is open"},
                {"id": "browser-open", "cap": "client.widget.open", "outcome": "Browser widget is open"},
            ], "operations": [
                {"id": "open-space", "cap": "client.space.open", "args": {"space": "Realure", "wait_sec": 0}, "completes_goal": True, "goal_id": "space-open"},
                {"id": "open-browser", "cap": "client.widget.open", "args": {"widget": "browser", "wait_sec": 0}, "after": ["open-space"], "completes_goal": True, "goal_id": "browser-open"},
            ]}),
            call("execute", {"goals": [
                {"id": "space-open", "cap": "client.space.open", "outcome": "Realure space is open"},
                {"id": "browser-open", "cap": "client.widget.open", "outcome": "Browser widget is open"},
            ], "operations": [
                {"id": "open-space", "cap": "client.space.open", "args": {"space": "Realure", "wait_sec": 0}, "completes_goal": True, "goal_id": "space-open"},
                {"id": "open-browser", "cap": "client.widget.open", "args": {"widget": "browser", "wait_sec": 0}, "after": ["open-space"], "completes_goal": True, "goal_id": "browser-open"},
            ]}),
            {"reply": "Opened the Realure space and the Browser widget.", "usage": {"total_tokens": 50}},
        ], clients=clients, command_result={"ok": True, "acknowledged": True, "proof": ["client.ack", "client.space.active"]})
        result = controller_v6.execute_owned(
            object(), {"message": "open realure space than open browser widget", "session_id": "s1"}, user={"id": "u1"},
            run_record={"run_id": "run-compound-client", "turn_id": "turn-compound-client"},
            context={"receiver": "provider", "envelope": {"objective": "open realure space than open browser widget", "task_contract": {"request_class": "client_action"}}},
            runtime=runtime.values(),
        )
        self.assertEqual(result["reply"], "Opened the Realure space and the Browser widget.")
        self.assertEqual([item["status"] for item in result["state"]["goals"]], ["satisfied", "satisfied"])
        self.assertEqual(result["diagnostics"]["completion_gaps"], [])
        self.assertEqual([item["type"] for item in runtime.commands], ["space_open", "open_widget"])
        event_types = [item["type"] for item in runtime.events]
        self.assertLess(event_types.index("route.resolved"), event_types.index("llm.inference.started"))
        self.assertLess(event_types.index("llm.inference.started"), event_types.index("command.started"))
        self.assertLess(event_types.index("command.started"), event_types.index("evidence.received"))
        self.assertLess(event_types.index("evidence.received"), event_types.index("answer.final"))

    def test_browser_widget_state_question_inspects_live_client_in_one_inference(self) -> None:
        route = {
            "route_id": "wasm-agent.avatar-chat.ui", "owner": "plugins/wasm-agent", "workspace_root": "/workspace",
            "allowed_read_roots": ["/workspace"], "caps": ["client.ui.inspect"],
            "task_contract": {"request_class": "client_action", "completion_capabilities": ["authority:client.ui.inspect"]},
            "client_ui": {"widget_ids": ["browser"], "operations": ["browser_inspect", "command_status"]},
        }
        clients = [{
            "client_id": "electron-renderer", "device_id": "electron-renderer",
            "runtime_type": "electron", "live": True, "capabilities": ["observe.browser.inspect"],
        }]
        runtime = RuntimeFixture(route, [call("execute", {"operations": [{
            "id": "inspect-browser", "cap": "client.browser.inspect", "args": {"wait_sec": 0},
            "completes_goal": True,
        }]})], clients=clients, command_result={
            "ok": True, "browser": {"visible": True, "title": "Native Chromium", "url": "https://example.test/"},
            "proof": ["native.web_surface.status"],
        })
        result = controller_v6.execute_owned(
            object(), {"message": "hello is browser widget opened?", "session_id": "s1"}, user={"id": "u1"},
            run_record={"run_id": "run-browser-state", "turn_id": "turn-browser-state"},
            context={"receiver": "provider", "envelope": {
                "objective": "hello is browser widget opened?",
                "task_contract": {"request_class": "client_action", "completion_capabilities": ["authority:client.ui.inspect"]},
            }}, runtime=runtime.values(),
        )
        self.assertEqual(result["diagnostics"]["provider_calls"], 1)
        self.assertEqual(len(runtime.provider_bodies), 1)
        self.assertIn("It is visible", result["reply"])
        self.assertEqual(runtime.commands[0]["type"], "observability_browser_surface")
        self.assertIn("native.web_surface.status", {proof for item in result["evidence"] for proof in item.get("proof", [])})

    def test_live_browser_receipt_and_synthetic_pointer_controls_are_exact(self) -> None:
        route = {
            "route_id": "fixture.client", "owner": "fixture", "workspace_root": "/workspace",
            "allowed_read_roots": ["/workspace"], "caps": ["client.ui.inspect", "client.ui.control"],
            "client_ui": {
                "widget_ids": ["browser"],
                "operations": ["inspect", "browser_input_receipt", "browser_pointer_dispatch", "command_status"],
            },
        }
        clients = [{
            "client_id": "electron-renderer", "device_id": "electron-renderer",
            "runtime_type": "electron", "live": True,
            "capabilities": ["control.browser.input_receipt", "control.browser.pointer.dispatch"],
        }]
        runtime = RuntimeFixture(route, [
            call("discover", {"query": "enable native Browser input receipts and dispatch a synthetic pointer"}),
            call("execute", {"operations": [
                {
                    "id": "op.enable", "cap": "client.browser.input_receipt",
                    "args": {"enabled": True, "wait_sec": 0},
                },
                {
                    "id": "op.pointer", "cap": "client.browser.pointer.dispatch",
                    "args": {"x": 320, "y": 240, "wait_sec": 0},
                    "after": ["op.enable"],
                },
            ]}),
            {"reply": "The client acknowledged receipt enablement and the bounded synthetic pointer dispatch.", "usage": {"total_tokens": 50}},
        ], clients=clients)
        result = controller_v6.execute_owned(
            object(), {"message": "Prove the Browser receipt plumbing", "session_id": "s1"}, user={"id": "u1"},
            run_record={"run_id": "run-browser-control", "turn_id": "turn-browser-control"},
            context={"receiver": "provider", "envelope": {
                "objective": "Prove the Browser receipt plumbing",
                "task_contract": {"request_class": "conversation"},
                "completion_capabilities": ["client.browser.input_receipt", "client.browser.pointer.dispatch"],
            }}, runtime=runtime.values(),
        )
        self.assertEqual(result["protocol"], "v6")
        self.assertEqual([(item["type"], item["payload"]) for item in runtime.commands], [
            ("browser_input_receipt", {"enabled": True}),
            ("browser_pointer_dispatch", {"x": 320, "y": 240}),
        ])
        self.assertNotIn("command_id", runtime.commands[1]["payload"])
        self.assertEqual(
            [item["capability"] for item in result["local_tools"]],
            ["client.browser.input_receipt", "client.browser.pointer.dispatch"],
        )

    def test_live_browser_inspection_terminal_result_avoids_extra_provider_call(self) -> None:
        route = {
            "route_id": "fixture.client", "owner": "fixture", "workspace_root": "/workspace",
            "allowed_read_roots": ["/workspace"], "caps": ["client.ui.inspect"],
            "client_ui": {
                "widget_ids": ["browser"],
                "operations": ["inspect", "browser_inspect", "command_status"],
            },
        }
        clients = [{
            "client_id": "electron-renderer", "device_id": "electron-renderer",
            "runtime_type": "electron", "live": True,
            "capabilities": ["observe.browser.inspect"],
        }]
        runtime = RuntimeFixture(route, [
            call("discover", {"query": "inspect browser"}),
            call("execute", {"operations": [{
                "id": "inspect_browser", "cap": "client.browser.inspect",
                "args": {"wait_sec": 0},
            }]}),
        ], clients=clients)
        ports = runtime.values()
        ports["read_json_file"] = lambda _path, _fallback: {"status": "finished", "result": {
            "ok": True,
            "browser": {"url": "https://web.whatsapp.com/", "title": "(16) WhatsApp", "visible": False, "loading": False},
            "proof": ["native.web_surface.status"],
        }}
        result = controller_v6.execute_owned(
            object(), {"message": "Can you see the Browser widget?", "session_id": "s1"}, user={"id": "u1"},
            run_record={"run_id": "run-browser-terminal", "turn_id": "turn-browser-terminal"},
            context={"receiver": "provider", "envelope": {
                "objective": "Can you see the Browser widget?",
                "task_contract": {"request_class": "conversation"},
                "completion_capabilities": ["client.browser.inspect"],
            }}, runtime=ports,
        )
        self.assertEqual(len(runtime.provider_bodies), 2)
        self.assertEqual(result["diagnostics"]["provider_calls"], 2)
        self.assertEqual(
            result["reply"],
            "Yes—I can inspect the Browser widget. It is not currently visible. It has (16) WhatsApp loaded. "
            "The installed shell lacks Browser input-receipt support.",
        )
        self.assertEqual(result["diagnostics"]["completion_gaps"], [])
        self.assertEqual(runtime.finished[-1]["status"], "completed")
        self.assertIn("gate.decision", [item["type"] for item in runtime.events])

    def test_browser_status_terminal_result_cannot_finish_unbound_communication_goal(self) -> None:
        route = {
            "route_id": "fixture.client", "owner": "fixture", "workspace_root": "/workspace",
            "allowed_read_roots": ["/workspace"], "caps": ["client.ui.inspect"],
            "client_ui": {"widget_ids": ["browser"], "operations": ["browser_inspect", "command_status"]},
        }
        clients = [{
            "client_id": "electron-renderer", "device_id": "electron-renderer",
            "runtime_type": "electron", "live": True, "capabilities": ["observe.browser.inspect"],
        }]
        runtime = RuntimeFixture(route, [
            call("discover", {"query": "inspect browser"}),
            call("execute", {"operations": [{
                "id": "inspect_browser", "cap": "client.browser.inspect", "args": {"wait_sec": 0},
            }]}),
            {"reply": "The Browser is available. What message should I send?", "usage": {"total_tokens": 20}},
        ], clients=clients)
        ports = runtime.values()
        ports["read_json_file"] = lambda _path, _fallback: {"status": "finished", "result": {
            "ok": True,
            "browser": {"url": "https://example.test/", "title": "Messaging", "visible": False},
            "proof": ["native.web_surface.status"],
        }}
        result = controller_v6.execute_owned(
            object(), {"message": "Can you talk to a contact?", "session_id": "s1"}, user={"id": "u1"},
            run_record={"run_id": "run-browser-unbound", "turn_id": "turn-browser-unbound"},
            context={"receiver": "provider", "envelope": {
                "objective": "Can you talk to a contact?", "task_contract": {"request_class": "conversation"},
            }}, runtime=ports,
        )
        self.assertEqual(len(runtime.provider_bodies), 3)
        self.assertEqual(result["reply"], "The Browser is available. What message should I send?")
        self.assertNotIn("terminal_result", [
            (item.get("payload") or {}).get("status") for item in runtime.events
            if item.get("type") == "gate.decision"
        ])

    def test_failed_reviewed_action_returns_honest_terminal_failure(self) -> None:
        route = {
            "route_id": "fixture.client", "owner": "fixture", "workspace_root": "/workspace",
            "allowed_read_roots": ["/workspace"], "caps": ["client.ui.inspect", "client.ui.control"],
            "client_ui": {"widget_ids": ["browser"], "operations": ["browser_javascript_execute_unrestricted"]},
        }
        clients = [{
            "client_id": "electron-renderer", "device_id": "electron-renderer", "runtime_type": "electron",
            "live": True, "capabilities": ["control.browser.javascript.execute.unrestricted"],
        }]
        proposal = call("execute", {"goals": [{
            "id": "send-message", "cap": "client.browser.javascript.execute.unrestricted",
            "outcome": "The requested message is sent and observed.",
        }], "operations": [{
            "id": "send-message", "cap": "client.browser.javascript.execute.unrestricted",
            "args": {"javascript": "send()"}, "completes_goal": True, "goal_id": "send-message",
        }]})
        runtime = RuntimeFixture(route, [
            call("discover", {"query": "browser javascript"}), proposal, proposal,
            {"reply": "The client command failed.", "usage": {"total_tokens": 20}},
        ], clients=clients, command_result={"ok": False})
        result = controller_v6.execute_owned(
            object(), {"message": "Send the message", "session_id": "s1"}, user={"id": "u1"},
            run_record={"run_id": "run-action-failed", "turn_id": "turn-action-failed"},
            context={"receiver": "provider", "envelope": {
                "objective": "Send the message", "task_contract": {"request_class": "client_action"},
            }}, runtime=runtime.values(),
        )
        self.assertEqual(result["state"]["status"], "blocked")
        self.assertIn("couldn’t complete", result["reply"])
        self.assertIn("No success was verified", result["reply"])
        self.assertEqual(result["diagnostics"]["provider_calls"], 4)

    def test_interrupted_mutation_resumes_without_replay(self) -> None:
        route = {
            "route_id": "fixture.impl", "owner": "fixture", "workspace_root": "/workspace",
            "allowed_read_roots": ["/workspace"], "allowed_write_roots": ["/workspace"],
            "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
            "checks": [{"id": "focused", "command": ["python3", "test.py"]}],
        }
        first = RuntimeFixture(route, [
            call("discover", {"query": "patch test diff prove repository"}),
            call("execute", {"operations": [{
                "id": "op.patch", "cap": "repo.patch", "args": {"operations": [{
                    "op": "create", "path": "a.py", "content": "VALUE = 1\n", "expected_absent": True,
                }]},
            }]}),
            RuntimeError("provider connection reset"),
        ])
        base_context = {
            "receiver": "provider", "envelope": {
                "objective": "Implement a.py", "task_contract": {"request_class": "implementation"},
            },
        }
        with self.assertRaises(controller_v6.V6Error):
            controller_v6.execute_owned(
                object(), {"message": "Implement a.py", "session_id": "s1"}, user={"id": "u1"},
                run_record={"run_id": "run-first", "turn_id": "turn-first"}, context=base_context,
                runtime=first.values(),
            )
        checkpoint = first.finished[-1]["error"]["resume_checkpoint"]
        self.assertEqual(checkpoint["schema"], "master.frontier.v6.checkpoint.ref.v1")
        self.assertEqual([item.get("local_action") for item in first.kernel_actions], ["patch.apply_scoped"])

        second = RuntimeFixture(route, [
            {"reply": "Done too early.", "usage": {"total_tokens": 20}},
            call("execute", {"operations": [
                {"id": "op.test", "cap": "repo.test", "args": {"check_id": "focused"}},
                {"id": "op.diff", "cap": "repo.diff", "args": {}},
                {"id": "op.prove", "cap": "repo.prove", "args": {}},
            ]}),
            {"reply": "The restored patch passed its focused check and proof.", "usage": {"total_tokens": 30}},
        ], db_path=first.db_path)
        resumed_context = {
            "receiver": "provider", "envelope": {
                "objective": "Continue", "task_contract": {"request_class": "implementation"},
                "compact_state": {"continuation_context": {
                    "previous_run_id": "run-first", "previous_status": "interrupted",
                    "resume_checkpoint": checkpoint,
                }},
            },
        }
        result = controller_v6.execute_owned(
            object(), {"message": "Continue", "session_id": "s1"}, user={"id": "u1"},
            run_record={"run_id": "run-second", "turn_id": "turn-second"}, context=resumed_context,
            runtime=second.values(),
        )
        self.assertEqual(result["reply"], "The restored patch passed its focused check and proof.")
        self.assertNotIn("patch.apply_scoped", [item.get("local_action") for item in second.kernel_actions])
        self.assertEqual(result["changed_files"], ["a.py"])

    def test_route_authorized_mcp_host_is_compiled_on_demand(self) -> None:
        route = {
            "route_id": "fixture.mcp", "owner": "fixture", "workspace_root": "/workspace",
            "allowed_read_roots": ["/workspace"], "caps": [],
            "mcp": {"servers": [{"id": "github", "tools": ["get_issue"], "mode": "read-only"}]},
        }
        runtime = RuntimeFixture(route, [
            call("discover", {"query": "read github issue"}),
            call("execute", {"operations": [{"id": "op.issue", "cap": "mcp.github.get-issue", "args": {"number": 7}}]}),
            {"reply": "Issue 7 is titled Fix widget.", "usage": {"total_tokens": 40}},
        ])
        mcp_calls = []
        ports = runtime.values()
        ports["master_frontier_mcp_catalog"] = lambda _server, _user, _route: [{"id": "github", "tools": [{
            "name": "get_issue", "description": "Read one issue",
            "inputSchema": {"type": "object", "required": ["number"], "properties": {"number": {"type": "integer"}}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True},
        }]}]
        ports["master_frontier_mcp_call"] = lambda _server, _user, _route, server_id, tool, args: mcp_calls.append((server_id, tool, args)) or {"structuredContent": {"title": "Fix widget"}}
        result = controller_v6.execute_owned(
            object(), {"message": "Read issue 7", "session_id": "s1"}, user={"id": "u1"},
            run_record={"run_id": "run-mcp", "turn_id": "turn-mcp"},
            context={"receiver": "provider", "envelope": {
                "objective": "Read issue 7", "task_contract": {"request_class": "conversation"},
                "completion_capabilities": ["mcp.github.get-issue"],
            }}, runtime=ports,
        )
        self.assertEqual(result["reply"], "Issue 7 is titled Fix widget.")
        self.assertEqual(mcp_calls, [("github", "get_issue", {"number": 7})])

    def test_self_hosted_repository_change_uses_real_owned_adapters(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mf6-self-host-") as directory:
            root = Path(directory)
            source = "VALUE = 1\n"
            (root / "a.py").write_text(source, encoding="utf-8")
            subprocess.run(
                ["git", "init", "--quiet", str(root)], check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["git", "-C", str(root), "add", "a.py"], check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            route = {
                "route_id": "fixture.self-host", "owner": "master-frontier-v6",
                "workspace_root": str(root), "allowed_read_roots": [str(root)],
                "allowed_write_roots": [str(root)],
                "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
                "checks": [{
                    "id": "focused", "command": [
                        "python3", "-c", "from a import VALUE; assert VALUE == 2",
                    ],
                    "timeout_sec": 10, "evidence_paths": ["a.py"],
                }],
            }
            runtime = RepositoryAdapterRuntime(route, [
                call("discover", {"query": "read patch test diff prove repository"}),
                call("execute", {"operations": [{
                    "id": "op.read", "cap": "repo.read", "args": {"path": "a.py"},
                    "say": {"phase": "investigating", "message": "I found the routed owner and I’m binding the edit to its current source."},
                }]}),
                call("execute", {"operations": [{
                    "id": "op.patch", "cap": "repo.patch", "args": {"operations": [{
                        "op": "replace", "path": "a.py", "find": "VALUE = 1", "replace": "VALUE = 2",
                        "expected_sha256": hashlib.sha256(source.encode()).hexdigest(),
                    }]},
                    "say": {"phase": "acting", "message": "The preimage is bound. I’m applying the scoped transaction now."},
                }]}),
                call("execute", {"operations": [
                    {"id": "op.test", "cap": "repo.test", "args": {"check_id": "focused"},
                     "say": {"phase": "checking", "message": "The file changed. I’m running the route-registered focused check."}},
                    {"id": "op.diff", "cap": "repo.diff", "args": {"paths": ["a.py"]}},
                    {"id": "op.prove", "cap": "repo.prove", "args": {}},
                ]}),
                {"reply": "The scoped source change passed its registered check and Git proof.", "usage": {"total_tokens": 40}},
            ], journal_root=root / ".mf6-journal")
            result = controller_v6.execute_owned(
                object(), {"message": "Change VALUE to 2 and prove it", "session_id": "s1"}, user={"id": "u1"},
                run_record={"run_id": "run-self-host", "turn_id": "turn-self-host"},
                context={"receiver": "provider", "envelope": {
                    "objective": "Change VALUE to 2 and prove it",
                    "task_contract": {"request_class": "implementation"},
                }}, runtime=runtime.values(),
            )

            diff = repository_diff.collect(route, include_paths=["a.py"])
            self.assertEqual((root / "a.py").read_text(encoding="utf-8"), "VALUE = 2\n")
            self.assertTrue(any(item.get("path") == "a.py" for item in diff["changed_files"]))
            self.assertEqual(result["changed_files"], ["a.py"])
            self.assertEqual(result["diagnostics"]["completion_gaps"], [])
            self.assertEqual(runtime.finished[-1]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
