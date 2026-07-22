#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


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
        self.assertTrue(server_mod.requires_admin_request("POST", "/agent/provider/envelope"))
        self.assertTrue(server_mod.requires_admin_request("POST", "/agent/provider/envelope/stream"))
        self.assertTrue(server_mod.requires_admin_request("POST", "/agent/tools/route.resolve"))
        self.assertFalse(server_mod.requires_admin_request("POST", "/agent/provider/chat"))
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
            self.assertEqual(server_mod.default_agent_target_node(admin), "frontier")
            self.assertEqual(server_mod.default_agent_target_node(user), "frontier")
            self.assertEqual(server_mod.resolve_frontier_agent_node(admin, "frontier"), "orchestrator")
            self.assertEqual(server_mod.resolve_frontier_agent_node(user, "frontier"), "account-sandbox")
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
        hermes_usage = server_mod.normalize_token_usage({
            "inputTokens": "42",
            "outputTokens": 8,
            "totalTokens": 50,
            "cachedInputTokens": 12,
            "reasoningOutputTokens": 3,
        }, source="bridge_runs")
        self.assertEqual(hermes_usage["prompt_tokens"], 42)
        self.assertEqual(hermes_usage["completion_tokens"], 8)
        self.assertEqual(hermes_usage["total_tokens"], 50)
        self.assertEqual(hermes_usage["cached_input_tokens"], 12)
        self.assertEqual(hermes_usage["reasoning_output_tokens"], 3)
        exact_usage = server_mod.exact_llm_token_usage({
            "input_tokens": "12",
            "output_tokens": "3",
        }, source="provider_proxy", model="model-a")
        self.assertEqual(exact_usage["usage_scope"], "llm_api_call")
        self.assertEqual(exact_usage["usage_accuracy"], "provider_exact")
        self.assertTrue(exact_usage["billable"])
        self.assertEqual(exact_usage["model"], "model-a")
        task_usage = server_mod.bridge_task_usage({
            "result": {
                "usage": {
                    "totals": {
                        "input_tokens": "50",
                        "output_tokens": "7",
                        "api_calls": 1,
                    }
                }
            }
        })
        self.assertEqual(task_usage["total_tokens"], 57)
        self.assertEqual(task_usage["usage_scope"], "llm_api_call")
        self.assertEqual(task_usage["usage_accuracy"], "provider_exact")
        event_usage = server_mod.bridge_task_usage({
            "result": {
                "events": [
                    {"event": "run.started"},
                    {
                        "event": "run.completed",
                        "usage": {
                            "input_tokens": 20,
                            "output_tokens": 5,
                            "api_calls": 1,
                        },
                    },
                ]
            }
        })
        self.assertEqual(event_usage["total_tokens"], 25)
        self.assertEqual(event_usage["usage_scope"], "llm_api_call")
        self.assertEqual(event_usage["usage_accuracy"], "provider_exact")
        payload = server_mod.agent_run_token_usage_payload({
            "diagnostics": {
                "token_usage_head": {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "total_tokens": 12,
                    "api_calls": 1,
                    "usage_scope": "llm_api_call",
                    "usage_accuracy": "provider_exact",
                    "billable": True,
                },
                "token_usage_bridge": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cache_read_tokens": 300,
                    "total_tokens": 420,
                    "api_calls": 3,
                    "usage_scope": "llm_api_call",
                    "usage_accuracy": "provider_exact",
                    "billable": True,
                },
            }
        })
        self.assertEqual(payload["primary"], "total")
        self.assertEqual(payload["usage"]["total_tokens"], 432)
        self.assertEqual(payload["usage"]["prompt_tokens"], 110)
        self.assertEqual(payload["usage"]["completion_tokens"], 22)
        self.assertEqual(payload["usage"]["cached_input_tokens"], 300)
        self.assertEqual(payload["components"]["bridge"]["total_tokens"], 420)
        finalized = server_mod.agent_run_with_canonical_token_usage({
            "diagnostics": {
                "token_usage": [
                    {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
                    {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25},
                ],
                "token_usage_total": {"exact": True, "total_tokens": 37, "calls": 2, "metered_calls": 2},
            },
        })
        self.assertEqual(finalized["token_usage"]["total_tokens"], 37)
        self.assertEqual(finalized["diagnostics"]["token_usage_total"]["total_tokens"], 37)
        self.assertTrue(finalized["diagnostics"]["token_usage_total"]["exact"])
        self.assertEqual(finalized["diagnostics"]["token_usage_total"]["calls"], 2)
        self.assertEqual(len(finalized["diagnostics"]["token_usage_components"]), 2)
        zero_call_usage = server_mod.bridge_task_usage({
            "result": {
                "usage": {
                    "input_tokens": "1658690",
                    "output_tokens": "11132",
                    "api_calls": 0,
                }
            }
        })
        self.assertIsNotNone(zero_call_usage)
        assert zero_call_usage is not None
        self.assertEqual(zero_call_usage["total_tokens"], 1669822)
        self.assertEqual(zero_call_usage["api_calls"], 0)
        dispatch = server_mod.direct_head_hermes_dispatch_action({
            "decision": "dispatch.hermes",
            "actions": [{
                "id": "dispatch.hermes",
                "type": "bridge",
                "objective": "Apply a tiny edit.",
            }],
        })
        self.assertIsNotNone(dispatch)
        self.assertEqual(dispatch["objective"], "Apply a tiny edit.")

    def test_avatar_chat_dispatch_is_scoped_to_wasm_agent_workspace(self) -> None:
        action = {
            "id": "dispatch.hermes",
            "objective": "Set .agent-timeline gap and .agent-timeline-rows padding.",
            "caps": ["repo.read", "repo.edit", "proof.report"],
            "escalation_reason": "Exercise the bounded Hermes workspace prompt contract.",
        }
        envelope = {"objective": "CSS fix", "surface": "avatar-chat"}

        workspace = server_mod.direct_head_dispatch_workspace_contract(action, envelope)
        prompt = server_mod.direct_head_hermes_dispatch_prompt(action, envelope)

        self.assertIsNotNone(workspace)
        assert workspace is not None
        self.assertEqual(workspace["route_id"], "wasm-agent.avatar-chat.ui")
        self.assertEqual(workspace["workspace_root"], str(PLUGIN_ROOT.resolve()))
        self.assertIn('"route_contract":', prompt)
        self.assertIn(str(PLUGIN_ROOT.resolve()), prompt)
        self.assertIn("stay inside allowed roots", prompt)

    def test_route_tools_are_registry_scoped_and_receipted(self) -> None:
        resolved = server_mod.route_resolve_tool({
            "objective": "Fix agent timeline overflow",
            "surface_hint": "agent-run-timeline",
        })
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["route_contract"]["route_id"], "wasm-agent.agent-run.timeline")
        missing = server_mod.route_resolve_tool({
            "objective": "Fix agent timeline overflow",
            "surface_hint": "agent timeline",
        })
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"]["code"], "route_contract_missing")

        summary = server_mod.route_map_summary_tool({"route_id": "wasm-agent.agent-run.timeline"})
        self.assertEqual(summary["summary"]["route_id"], "wasm-agent.agent-run.timeline")
        self.assertGreater(summary["summary"]["likely_file_count"], 1)

        files = server_mod.route_lookup_files_tool({"route_id": "wasm-agent.frontier.provider"})
        static_receipt = next(item for item in files["files"] if item["path"] == "server/README.md")
        self.assertTrue(static_receipt["exists"])
        self.assertGreater(static_receipt["bytes"], 1000)
        self.assertRegex(static_receipt["sha256"], r"^[a-f0-9]{64}$")

        symbols = server_mod.route_lookup_symbol_tool({
            "route_id": "wasm-agent.frontier.provider",
            "query": "provider_envelope_run_execute",
        })
        self.assertTrue(symbols["ok"])
        self.assertGreaterEqual(symbols["count"], 1)
        self.assertTrue(any(match["path"] == "server/static_server.py" for match in symbols["matches"]))

    def test_route_resolve_missing_does_not_scan_source(self) -> None:
        with patch.object(server_mod.subprocess, "run") as run_mock:
            resolved = server_mod.route_resolve_tool({"objective": "Unknown surface should not search."})
        self.assertFalse(resolved["ok"])
        self.assertEqual(resolved["error"]["code"], "route_contract_missing")
        run_mock.assert_not_called()

    def test_explicit_workspace_root_is_not_a_route_contract(self) -> None:
        action = {
            "id": "dispatch.hermes",
            "objective": "Search wherever needed.",
            "workspace_root": str(PLUGIN_ROOT),
        }
        envelope = {"objective": "No registered route."}

        self.assertIsNone(server_mod.direct_head_dispatch_workspace_contract(action, envelope))
        with self.assertRaises(server_mod.ProviderProxyError) as raised:
            server_mod.direct_head_hermes_dispatch_prompt(action, envelope)
        self.assertEqual(raised.exception.diagnostic["category"], "route_contract_missing")

    def test_hermes_dispatch_fails_closed_without_route_contract(self) -> None:
        action = {
            "id": "dispatch.hermes",
            "objective": "Set .agent-timeline gap.",
            "caps": ["repo.read", "repo.edit", "proof.report"],
        }
        envelope = {"objective": "CSS fix"}

        self.assertIsNone(server_mod.direct_head_dispatch_workspace_contract(action, envelope))
        with self.assertRaises(server_mod.ProviderProxyError) as raised:
            server_mod.direct_head_hermes_dispatch_prompt(action, envelope)

        self.assertEqual(raised.exception.diagnostic["category"], "route_contract_missing")

    def test_static_server_has_no_product_selector_route_heuristic(self) -> None:
        source = SERVER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("WASM_AGENT_UI_ROUTE_TERMS", source)
        self.assertNotIn("WASM_AGENT_UI_SELECTOR_RE", source)
        self.assertIn("agent_route_contracts.json", source)

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

        with patch.object(server_mod, "public_origin", return_value=""):
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
