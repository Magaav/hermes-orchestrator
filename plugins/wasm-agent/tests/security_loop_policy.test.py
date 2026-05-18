#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PLUGIN_ROOT / "server" / "static_server.py"

spec = importlib.util.spec_from_file_location("wasm_agent_static_server", SERVER_PATH)
server_mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(server_mod)


class SecurityLoopPolicyTest(unittest.TestCase):
    @staticmethod
    def fake_handler(headers: dict[str, str]) -> SimpleNamespace:
        class HeaderMap(dict):
            def get(self, key: str, default: str = "") -> str:  # type: ignore[override]
                return super().get(key, default)

        return SimpleNamespace(headers=HeaderMap(headers))

    def test_admin_route_policy_is_explicit(self) -> None:
        self.assertTrue(server_mod.is_public_request("GET", "/admin"))
        self.assertFalse(server_mod.requires_admin_request("GET", "/admin"))
        self.assertTrue(server_mod.requires_admin_request("GET", "/bridge/nodes"))
        self.assertTrue(server_mod.requires_admin_request("GET", "/security-loop/status"))
        self.assertTrue(server_mod.requires_admin_request("POST", "/security-loop/findings"))
        self.assertFalse(server_mod.requires_admin_request("GET", "/spaces"))
        self.assertFalse(server_mod.requires_admin_request("POST", "/spaces"))

    def test_bridge_route_allowlist_blocks_unknown_paths(self) -> None:
        self.assertTrue(server_mod.bridge_route_allowed("GET", "/health"))
        self.assertTrue(server_mod.bridge_route_allowed("GET", "/nodes/orchestrator/logs"))
        self.assertTrue(server_mod.bridge_route_allowed("POST", "/nodes/hermes-defense/prompt"))
        self.assertTrue(server_mod.bridge_route_allowed("POST", "/tasks/task_123/stop"))
        self.assertFalse(server_mod.bridge_route_allowed("GET", "/../../state/db/sqlite/wa_auth_secret"))
        self.assertFalse(server_mod.bridge_route_allowed("POST", "/shell"))
        self.assertFalse(server_mod.bridge_route_allowed("GET", "http://127.0.0.1:8790/nodes"))

    def test_agent_mutation_policy_separates_orchestrator_and_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = Path(tmp) / "plugins" / "wasm-agent"
            state_dir = plugin_root / "state"
            state_dir.mkdir(parents=True)
            fake_server = SimpleNamespace(plugin_root=plugin_root, state_dir=state_dir)
            admin = {"id": "1", "email": "admin@example.com", "role": "admin"}
            user = {"id": "2", "email": "user@example.com", "role": "user"}

            global_policy = server_mod.agent_mutation_policy(fake_server, admin, "orchestrator")
            sandbox_policy = server_mod.agent_mutation_policy(fake_server, user, "worker-2")

            self.assertEqual(global_policy["scope"], "global-orchestrator")
            self.assertTrue(global_policy["can_modify_core_firmware"])
            self.assertEqual(sandbox_policy["scope"], "user-sandbox")
            self.assertFalse(sandbox_policy["can_modify_core_firmware"])
            self.assertEqual(server_mod.default_agent_target_node(admin), "orchestrator")
            self.assertEqual(server_mod.default_agent_target_node(user), "account-sandbox")
            server_mod.ensure_agent_target_allowed(admin, "orchestrator")
            with self.assertRaises(server_mod.BrowserError):
                server_mod.ensure_agent_target_allowed(user, "orchestrator")
            self.assertEqual(
                server_mod.ensure_timeline_paths_allowed(
                    fake_server,
                    user,
                    ["plugins/wasm-agent/state/users/2/spaces/home/app.json"],
                ),
                "user-sandbox",
            )
            with self.assertRaises(server_mod.BrowserError):
                server_mod.ensure_timeline_paths_allowed(fake_server, user, ["plugins/wasm-agent/public/app.js"])

    def test_bridge_trace_from_task_summarizes_reasoning_without_raw_text(self) -> None:
        task = {
            "task_id": "space-ui-1",
            "status": "completed",
            "result": {
                "run_id": "run_1",
                "thinking_stream": "private reasoning text",
                "events": [
                    {"event": "run.started", "status": "running", "source": "run_status"},
                    {"event": "run.started", "status": "running", "message": "Run started"},
                    {"event": "tool.started", "tool": "read_file", "preview": "/local/README.md"},
                    {"event": "tool.completed", "tool": "read_file", "status": "ok"},
                    {"event": "reasoning.available", "text": "private reasoning text"},
                    {"event": "run.completed", "status": "completed", "message": "Run completed"},
                    {"event": "run.completed", "status": "completed", "source": "run_status"},
                ],
            },
        }
        trace = server_mod.bridge_trace_from_task(task)
        self.assertEqual(trace["id"], "run_1")
        self.assertEqual(len(trace["tool_calls"]), 1)
        self.assertGreaterEqual(len(trace["steps"]), 1)
        self.assertEqual(trace["tool_calls"][0]["name"], "read_file")
        self.assertEqual(trace["tool_calls"][0]["status"], "done")
        kinds = [step["kind"] for step in trace["steps"]]
        self.assertEqual(kinds.count("backend.run.started"), 1)
        self.assertEqual(kinds.count("backend.run.completed"), 1)
        self.assertIn("model.reasoning.available", kinds)
        self.assertIn("Provider returned", trace["reasoning_summary"])
        self.assertNotIn("private reasoning text", trace["reasoning_summary"])

    def test_ui_symbol_resolver_prevents_false_not_found_claims(self) -> None:
        fake_server = SimpleNamespace(plugin_root=PLUGIN_ROOT, state_dir=PLUGIN_ROOT / "state")
        tool = server_mod.agent_ui_symbol_resolver(
            fake_server,
            "`agentModelSelect` right padding should match the visible select",
        )
        self.assertIsNotNone(tool)
        summary = server_mod.symbol_resolution_summary(tool)
        self.assertIn("agentModelSelect", summary)
        self.assertIn("plugins/wasm-agent/public/index.html", summary)
        self.assertIn("plugins/wasm-agent/public/styles.css", summary)
        corrected = server_mod.correct_negative_symbol_reply(
            fake_server,
            "`agentModelSelect` right padding should match the visible select",
            "I cannot find `agentModelSelect` in the source tree.",
        )
        self.assertIn("Adapter symbol check", corrected)
        self.assertIn(".agent-model-select", corrected)

    def test_final_agent_actions_and_token_usage_are_normalized(self) -> None:
        actions = server_mod.finalize_agent_actions([
            {"id": "bridge_run", "status": "running"},
            {"id": "tool_read", "status": "failed"},
        ])
        self.assertEqual(actions[0]["status"], "done")
        self.assertEqual(actions[1]["status"], "error")
        usage = server_mod.normalize_token_usage({
            "input_tokens": "1,200",
            "output_tokens": 34.8,
        }, source="bridge_runs")
        self.assertEqual(usage["prompt_tokens"], 1200)
        self.assertEqual(usage["completion_tokens"], 34)
        self.assertEqual(usage["total_tokens"], 1234)
        self.assertEqual(usage["source"], "bridge_runs")
        task_usage = server_mod.bridge_task_usage({
            "result": {
                "usage": {
                    "totals": {
                        "input_tokens": "50",
                        "output_tokens": "7",
                    }
                }
            }
        })
        self.assertEqual(task_usage["total_tokens"], 57)

    def test_browser_stream_requires_same_origin_websocket(self) -> None:
        same_origin = self.fake_handler({
            "Host": "wa.example.test",
            "Origin": "http://wa.example.test",
        })
        cross_origin = self.fake_handler({
            "Host": "wa.example.test",
            "Origin": "https://evil.example.test",
        })
        missing_origin = self.fake_handler({"Host": "wa.example.test"})

        self.assertTrue(server_mod.same_origin_websocket(same_origin))
        self.assertFalse(server_mod.same_origin_websocket(cross_origin))
        self.assertFalse(server_mod.same_origin_websocket(missing_origin))
        self.assertTrue(server_mod.same_origin_post(missing_origin))

    def test_security_finding_lifecycle_is_append_only_with_current_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_server = SimpleNamespace(state_dir=Path(tmp))
            admin = {"id": "1", "email": "admin@example.com", "role": "admin"}
            saved = server_mod.save_security_loop_finding(fake_server, {
                "source_node": "hermes-attack",
                "target_surface": "auth",
                "category": "role-separation",
                "severity": "critical",
                "confidence": 0.9,
                "exploitability": 0.8,
                "summary": "Standard user reached an admin route.",
                "evidence_preview": "GET /bridge/nodes returned 200",
                "proposed_action": "Require admin role before bridge proxy.",
                "task_id": "task_security_1",
            }, admin)
            finding = saved["finding"]
            self.assertEqual(finding["schema"], "hermes.security_loop.finding.v1")
            self.assertEqual(finding["source_node"], "hermes-attack")
            self.assertTrue(finding["fingerprint"])
            self.assertEqual(finding["occurrence_count"], 1)
            self.assertGreaterEqual(finding["score"], 90)
            self.assertEqual(saved["security_loop"]["critical_count"], 1)

            decided = server_mod.decide_security_loop_finding(fake_server, finding["id"], {"status": "accepted"}, admin)
            self.assertEqual(decided["finding"]["status"], "accepted")
            self.assertEqual(decided["security_loop"]["accepted_count"], 1)

            lines = (Path(tmp) / "security-loop" / "findings.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)

    def test_repeated_security_findings_dedupe_by_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_server = SimpleNamespace(state_dir=Path(tmp))
            admin = {"id": "1", "email": "admin@example.com", "role": "admin"}
            body = {
                "id": "run-1-auth",
                "source_node": "wasm-agent-security-loop",
                "target_surface": "auth",
                "category": "auth-gate",
                "severity": "high",
                "summary": "Protected route returned 200.",
                "evidence_preview": "first run",
            }
            first = server_mod.save_security_loop_finding(fake_server, body, admin)["finding"]
            server_mod.decide_security_loop_finding(fake_server, first["id"], {"status": "rejected", "reason": "false positive"}, admin)

            second = server_mod.save_security_loop_finding(fake_server, {
                **body,
                "id": "run-2-auth",
                "evidence_preview": "second run",
            }, admin)

            findings = second["security_loop"]["finding_count"]
            self.assertEqual(findings, 1)
            self.assertEqual(second["finding"]["id"], first["id"])
            self.assertEqual(second["finding"]["status"], "rejected")
            self.assertEqual(second["finding"]["decision_reason"], "false positive")
            self.assertEqual(second["finding"]["occurrence_count"], 2)
            self.assertEqual(second["finding"]["evidence_preview"], "second run")

    def test_security_loop_status_includes_latest_runner_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_server = SimpleNamespace(state_dir=Path(tmp))
            run_dir = Path(tmp) / "security-loop"
            run_dir.mkdir(parents=True)
            server_mod.write_json_file(run_dir / "latest-run.json", {
                "run_id": "security-run-test",
                "runner_status": "running",
                "mode": "nodes",
                "delivery": "runs-api",
                "probe_count": 0,
                "failed_probe_count": 0,
                "finding_count": 0,
                "tasks": [{
                    "target_node": "hermes-attack",
                    "task": {
                        "run_id": "run_123",
                        "status": "started",
                        "api_url": "http://172.17.0.2:8643",
                    },
                }],
            })

            status = server_mod.security_loop_status(fake_server)["security_loop"]

            self.assertEqual(status["latest_run"]["run_id"], "security-run-test")
            self.assertEqual(status["latest_run"]["runner_status"], "running")
            self.assertEqual(status["latest_run"]["tasks"][0]["target_node"], "hermes-attack")
            self.assertEqual(status["latest_run"]["tasks"][0]["status"], "started")


if __name__ == "__main__":
    unittest.main()
