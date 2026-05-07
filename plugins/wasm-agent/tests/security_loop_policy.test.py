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
            self.assertGreaterEqual(finding["score"], 90)
            self.assertEqual(saved["security_loop"]["critical_count"], 1)

            decided = server_mod.decide_security_loop_finding(fake_server, finding["id"], {"status": "accepted"}, admin)
            self.assertEqual(decided["finding"]["status"], "accepted")
            self.assertEqual(decided["security_loop"]["accepted_count"], 1)

            lines = (Path(tmp) / "security-loop" / "findings.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)


if __name__ == "__main__":
    unittest.main()
