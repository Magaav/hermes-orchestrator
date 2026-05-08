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
