#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


TEST_ROOT = Path(__file__).resolve().parent
PROVIDER_TEST_PATH = TEST_ROOT / "provider_proxy.test.py"
COST_FIXTURE_PATH = TEST_ROOT / "fixtures/master_frontier_c3_cost_metrics.json"
COST_FIXTURE = json.loads(COST_FIXTURE_PATH.read_text(encoding="utf-8"))
C3_PROVIDER_USAGES = COST_FIXTURE["providerUsages"]
spec = importlib.util.spec_from_file_location("wasm_agent_provider_test_support_v3", PROVIDER_TEST_PATH)
assert spec and spec.loader
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


class MasterFrontierV3IntegrationTests(unittest.TestCase):
    def test_server_runs_semantic_search_read_then_answer_with_internal_cypher_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, support.ProviderStub() as stub:
            support.ProviderStubHandler.response_bodies = [
                {
                    "model": "stub-model",
                    "choices": [{"message": {"content": "@search query='meta-analysis'"}}],
                    "usage": dict(C3_PROVIDER_USAGES[0]),
                },
                {
                    "model": "stub-model",
                    "choices": [{"message": {"content": "@read path='public/modules/meta-analysis/meta-analysis-widget.js' bytes=12000"}}],
                    "usage": dict(C3_PROVIDER_USAGES[1]),
                },
                {
                    "model": "stub-model",
                    "choices": [{"message": {"content": "The meta-analysis widget queues subjects and turns ranked research findings into a persisted, integrity-scored, exportable report."}}],
                    "usage": dict(C3_PROVIDER_USAGES[2]),
                },
            ]
            body = {
                **support.ProviderProxyTests().body(stub.base_url),
                "session_id": "c3-integration-session",
                "turn_id": "c3-integration-turn",
                "max_output_tokens": 1800,
                "envelope": {
                    "schema": "hermes.wasm_agent.master_frontier.v3",
                    "trace_id": "c3-integration-turn",
                    "objective": "search the code base to understand what the meta-analysis widget does",
                    "surface": "avatar-chat",
                    "route_id": "wasm-agent.avatar-chat.ui",
                    "budget": {"max_output_tokens": 1800},
                    "stream": True,
                },
            }
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(Path(tmp) / "wa.sqlite3"),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }

            def fake_kernel_tool(_server, path, payload, *, user=None):
                if path.endswith("/code.memory.search"):
                    self.assertEqual(payload["query"], "meta-analysis")
                    return {
                        "ok": True,
                        "code": "ok",
                        "schema": "hermes.wasm_agent.code_memory.v1",
                        "route_id": "wasm-agent.avatar-chat.ui",
                        "items": [{
                            "label": "File",
                            "file_path": "public/modules/meta-analysis/meta-analysis-widget.js",
                            "name": "meta-analysis-widget.js",
                        }],
                    }
                self.assertTrue(path.endswith("/file.read_bounded"))
                self.assertEqual(payload["path"], "public/modules/meta-analysis/meta-analysis-widget.js")
                return {
                    "ok": True,
                    "code": "ok",
                    "schema": "hermes.wasm_agent.route.file_read_bounded.v1",
                    "route_id": "wasm-agent.avatar-chat.ui",
                    "path": payload["path"],
                    "text": "rankSubject assessIntegrity persist exportFindings",
                }

            with patch.dict(os.environ, env, clear=True), patch.object(support.server_mod, "agent_kernel_tool", side_effect=fake_kernel_tool):
                result = support.server_mod.provider_envelope_run_completion(object(), body, user=support.ProviderProxyTests().admin())
                stored = support.server_mod.read_agent_run(support.ProviderProxyTests().admin(), result["run_id"])["run"]
                events = support.server_mod.read_agent_run_events(support.ProviderProxyTests().admin(), result["run_id"], {"limit": ["500"]})["events"]

            self.assertIn("queues subjects", result["reply"])
            self.assertEqual(stored["status"], "completed")
            self.assertEqual(stored["final"]["diagnostics"]["protocol"], "c3")
            self.assertEqual(stored["token_ledger"]["provider_call_count"], len(C3_PROVIDER_USAGES))
            self.assertEqual(stored["token_ledger"]["total_tokens"], sum(item["total_tokens"] for item in C3_PROVIDER_USAGES))
            self.assertEqual(len([event for event in events if event["type"] == "evidence.received"]), 2)
            self.assertFalse([event for event in events if event["type"] == "head.delta"])
            buffered = [
                event for event in events
                if event["type"] == "llm.reason.summary"
                and event["payload"].get("action", {}).get("label") == "LLM decision"
            ]
            self.assertEqual(len(buffered), len(C3_PROVIDER_USAGES))
            self.assertTrue(all(event["payload"].get("action", {}).get("kind") == "trace" for event in buffered))
            decisions = [event for event in events if event["type"] == "head.decision"]
            self.assertTrue(all(event["payload"].get("action", {}).get("arguments") is not None for event in decisions[:2]))
            evidence = [event for event in events if event["type"] == "evidence.received"]
            self.assertTrue(all(event["payload"].get("action", {}).get("preview") for event in evidence))
            self.assertGreaterEqual(len([event for event in events if event["type"] == "tokens.used"]), len(C3_PROVIDER_USAGES))
            self.assertEqual(events[-1]["type"], "run.final")
            sent = [request["payload"]["messages"][1]["content"] for request in support.ProviderStubHandler.requests]
            self.assertTrue(all("I e:C3 g:" in content for content in sent))
            self.assertTrue(all("q=code.memory.search" not in content for content in sent))
            self.assertIn("search(query,limit) read(path,bytes,offset,length)", sent[0])
            self.assertIn("search ok n=1", sent[1])
            self.assertIn("file path=public/modules/meta-analysis/meta-analysis-widget.js", sent[1])
            self.assertIn("read ok n=", sent[2])
            self.assertIn("rankSubject", sent[2])
            self.assertNotIn("allowed_actions", sent[0])
            self.assertNotIn("output_schema", sent[0])


if __name__ == "__main__":
    unittest.main()
