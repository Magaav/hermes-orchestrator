#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PLUGIN_ROOT / "server" / "static_server.py"

spec = importlib.util.spec_from_file_location("wasm_agent_static_server", SERVER_PATH)
assert spec and spec.loader
static_server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(static_server)


def make_user(user_id: str, email: str, role: str = "user") -> dict[str, object]:
    return {
        "id": user_id,
        "provider": "test",
        "email": email,
        "email_verified": True,
        "role": role,
        "name": email.split("@", 1)[0],
        "picture_url": "",
        "created_at": 0,
        "last_login_at": 0,
    }


def insert_account(conn, user_id: int, email: str) -> None:
    now = int(static_server.time.time())
    conn.execute(
        """
        INSERT INTO user_tb (
          id, provider, provider_sub, email, email_verified, name,
          picture_url, created_at, updated_at, last_login_at
        ) VALUES (?, 'test', ?, ?, 1, ?, '', ?, ?, ?)
        """,
        (user_id, str(user_id), email, email.split("@", 1)[0], now, now, now),
    )


HARNESS_PROVIDER_CONFIG = {
    "base_url": "https://opencode.ai/zen/go/v1",
    "provider": "opencode-go",
    "model": "opencode-go/kimi-k2.6",
    "api_key": "sk-or-harness",
}


class ReadinessCreditsProvisioningTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.state_dir = self.root / "state"
        self.agents_root = self.root / "agents"
        self.env_root = self.agents_root / "envs"
        self.env_root.mkdir(parents=True)
        self.wa_env = self.root / "wa.env"
        self.wa_env.write_text("ADMIN_EMAIL=admin@example.test\nUSER_EMAILS=user@example.test,target@example.test\n", encoding="utf-8")
        self.env = {
            "HERMES_WASM_AGENT_DB_PATH": str(self.state_dir / "db" / "wa.sqlite3"),
            "HERMES_WASM_AGENT_ENV_PATH": str(self.wa_env),
            "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            "HERMES_AGENTS_ROOT": str(self.agents_root),
            "HERMES_WASM_AGENT_MAIN_NODE_FLUX_COST": "100",
        }
        self.server = SimpleNamespace(
            plugin_root=PLUGIN_ROOT,
            public_root=PLUGIN_ROOT / "public",
            state_dir=self.state_dir,
            bridge_url="http://127.0.0.1:8790",
            browser_timeout_sec=1.0,
        )
        self.user = make_user("101", "user@example.test")
        self.target = make_user("202", "target@example.test")
        self.admin = make_user("1", "admin@example.test", "admin")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def seed_accounts(self) -> None:
        with static_server.auth_connect() as conn:
            insert_account(conn, 1, "admin@example.test")
            insert_account(conn, 101, "user@example.test")
            insert_account(conn, 202, "target@example.test")

    def test_csp_allows_wasm_eval_without_broad_eval(self) -> None:
        with patch.dict(os.environ, {"HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local"}, clear=True):
            csp = static_server.content_security_policy()
        script_src = csp.split("script-src ", 1)[1].split(";", 1)[0].split()
        self.assertIn("'wasm-unsafe-eval'", script_src)
        self.assertNotIn("'unsafe-eval'", script_src)

    def test_readiness_states_for_missing_sandbox_global_bridge_and_bridge_outage(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
            self.seed_accounts()

            missing = static_server.agent_readiness(self.server, self.user, target_node="account-sandbox")
            self.assertEqual(missing["schema"], static_server.AGENT_READINESS_SCHEMA)
            self.assertEqual(missing["status"], "sandbox_not_provisioned")
            self.assertEqual(missing["missing_dependency"], "account_sandbox_api_url")

            def ready_admin_bridge(server, method, path, body):
                if method == "GET" and path == "/health":
                    return {"ok": True, "health": {"status": "ok"}}
                if method == "GET" and path == "/nodes/orchestrator":
                    return {"ok": True, "node": {"id": "orchestrator", "running": True, "status": "running"}}
                raise AssertionError((method, path, body))

            with patch.object(static_server, "bridge_proxy", side_effect=ready_admin_bridge):
                ready = static_server.agent_readiness(self.server, self.admin, target_node="orchestrator")
            self.assertEqual(ready["status"], "ready")
            self.assertEqual(ready["bridge_url_source"], "global_bridge_url")
            self.assertEqual(ready["backend"]["node"]["status"], "running")

            def stopped_admin_bridge(server, method, path, body):
                if method == "GET" and path == "/health":
                    return {"ok": True, "health": {"status": "ok"}}
                if method == "GET" and path == "/nodes/orchestrator":
                    return {"ok": True, "node": {"id": "orchestrator", "running": False, "status": "stopped"}}
                raise AssertionError((method, path, body))

            with patch.object(static_server, "bridge_proxy", side_effect=stopped_admin_bridge):
                stopped = static_server.agent_readiness(self.server, self.admin, target_node="orchestrator")
            self.assertEqual(stopped["status"], "backend_unavailable")
            self.assertEqual(stopped["missing_dependency"], "selected_node_not_running")

            node_id = static_server.account_main_node_id(self.user)
            (self.env_root / f"{node_id}.env").write_text("API_SERVER_HOST=127.0.0.1\nAPI_SERVER_PORT=9876\n", encoding="utf-8")
            with patch.object(
                static_server,
                "bridge_proxy",
                side_effect=static_server.BrowserError(
                    "bridge_unavailable",
                    "bridge returned 503",
                    status=static_server.HTTPStatus.SERVICE_UNAVAILABLE,
                ),
            ):
                outage = static_server.agent_readiness(self.server, self.user, target_node="account-sandbox")
            self.assertEqual(outage["status"], "backend_unavailable")
            self.assertEqual(outage["missing_dependency"], "wasm_agent_bridge")

    def test_message_dispatch_guard_returns_clear_missing_dependency(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
            self.seed_accounts()
            with patch.object(static_server, "bridge_proxy") as bridge:
                result = static_server.embedded_agent_message(
                    self.server,
                    {"message": "Hello", "mode": "bridge", "target_node": "account-sandbox", "transcript": []},
                    user=self.user,
                )
            bridge.assert_not_called()
            self.assertEqual(result["diagnostics"]["readiness"]["status"], "sandbox_not_provisioned")
            self.assertEqual(result["diagnostics"]["missing_dependency"], "account_sandbox_api_url")
            self.assertIn("Missing dependency: `account_sandbox_api_url`", result["reply"])
            self.assertTrue(any(action["id"] == "agent_readiness" and action["status"] == "error" for action in result["actions"]))

    def test_credit_grants_are_admin_only_idempotent_and_target_guarded(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
            self.seed_accounts()
            grant = static_server.grant_flux_credits(
                self.admin,
                "202",
                {"amount": 150, "reason": "pilot", "idempotency_key": "grant-one"},
            )
            self.assertEqual(grant["balance"], 150)
            self.assertEqual(static_server.account_credits(self.target)["balance"], 150)

            cases = [
                (self.user, "202", {"amount": 1, "reason": "bad", "idempotency_key": "non-admin"}, "admin_required"),
                (self.admin, "1", {"amount": 1, "reason": "bad", "idempotency_key": "self"}, "credit_self_grant_denied"),
                (self.admin, "1", {"amount": 1, "reason": "bad", "idempotency_key": "admin-target"}, "credit_self_grant_denied"),
                (self.admin, "202", {"amount": 0, "reason": "bad", "idempotency_key": "zero"}, "invalid_credit_amount"),
                (self.admin, "202", {"amount": -5, "reason": "bad", "idempotency_key": "negative"}, "invalid_credit_amount"),
                (self.admin, "202", {"amount": 150, "reason": "dupe", "idempotency_key": "grant-one"}, "duplicate_idempotency_key"),
            ]
            for actor, target_id, body, code in cases:
                with self.subTest(code=code):
                    with self.assertRaises(static_server.BrowserError) as denied:
                        static_server.grant_flux_credits(actor, target_id, body)
                    self.assertEqual(denied.exception.code, code)
            with static_server.auth_connect() as conn:
                grant_audits = conn.execute(
                    "SELECT COUNT(*) AS total FROM instance_audit_tb WHERE action = 'credits.grant.denied'"
                ).fetchone()
            self.assertGreaterEqual(int(grant_audits["total"]), len(cases))

    def test_admin_target_grant_is_denied_for_non_self_admin(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
            self.seed_accounts()
            other_admin_id = 303
            with static_server.auth_connect() as conn:
                insert_account(conn, other_admin_id, "admin@example.test")
            with self.assertRaises(static_server.BrowserError) as denied:
                static_server.grant_flux_credits(
                    self.admin,
                    str(other_admin_id),
                    {"amount": 1, "reason": "bad", "idempotency_key": "admin-target"},
                )
            self.assertEqual(denied.exception.code, "credit_admin_target_denied")
            with static_server.auth_connect() as conn:
                row = conn.execute(
                    "SELECT metadata_json FROM instance_audit_tb WHERE action = 'credits.grant.denied' ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
            self.assertIn("admin_target", row["metadata_json"])

    def test_provisioning_debits_once_starts_deterministic_main_and_blocks_exploits(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
            self.seed_accounts()
            node_id = static_server.account_main_node_id(self.user)
            calls: list[tuple[str, str, dict | None]] = []

            def fake_bridge(server, method, path, body):
                calls.append((method, path, body))
                if method == "POST" and path == "/nodes":
                    self.assertEqual(body["node_id"], node_id)
                    self.assertEqual(body["node_state"], "4")
                    self.assertEqual(body["default_model_provider"], "opencode-go")
                    self.assertEqual(body["default_model"], "deepseek-v4-flash")
                    self.assertIn("Agent name: Research helper", body["personality"])
                    self.assertIn("Instructions: Focus on workspace research.", body["personality"])
                    (self.env_root / f"{node_id}.env").write_text(
                        "API_SERVER_HOST=127.0.0.1\nAPI_SERVER_PORT=9876\n",
                        encoding="utf-8",
                    )
                    return {"ok": True, "node_create": {"node_id": node_id}}
                if method == "GET" and path == "/health":
                    return {"ok": True, "health": {"status": "ok"}}
                if method == "GET" and path == f"/nodes/{node_id}":
                    return {"ok": True, "node": {"id": node_id, "running": True, "status": "running"}}
                raise AssertionError((method, path, body))

            with patch.object(static_server, "bridge_proxy", side_effect=fake_bridge):
                with self.assertRaises(static_server.BrowserError) as admin_denied:
                    static_server.provision_main_fleet_node(self.server, self.admin, {})
                self.assertEqual(admin_denied.exception.code, "admin_provision_denied")

                with self.assertRaises(static_server.BrowserError) as insufficient:
                    static_server.provision_main_fleet_node(self.server, self.user, {})
                self.assertEqual(insufficient.exception.code, "insufficient_flux_credits")
                self.assertFalse(any(call[0] == "POST" for call in calls))

                static_server.grant_flux_credits(
                    self.admin,
                    "101",
                    {"amount": 100, "reason": "provision", "idempotency_key": "grant-provision"},
                )
                provisioned = static_server.provision_main_fleet_node(
                    self.server,
                    self.user,
                    {
                        "idempotency_key": "provision-one",
                        "agent_name": "Research helper",
                        "agent_role": "Focus on workspace research.",
                        "agent_type": "hermes",
                    },
                )
                self.assertTrue(provisioned["provisioned"])
                self.assertTrue(provisioned["debited"])
                self.assertEqual(provisioned["credits"]["balance"], 0)
                self.assertEqual(sum(1 for call in calls if call[0] == "POST" and call[1] == "/nodes"), 1)

                existing = static_server.provision_main_fleet_node(
                    self.server,
                    self.user,
                    {"idempotency_key": "provision-two"},
                )
                self.assertTrue(existing["already_provisioned"])
                self.assertFalse(existing["debited"])
                self.assertEqual(existing["credits"]["balance"], 0)
                self.assertEqual(sum(1 for call in calls if call[0] == "POST" and call[1] == "/nodes"), 1)

                with self.assertRaises(static_server.BrowserError) as arbitrary_node:
                    static_server.provision_main_fleet_node(self.server, self.user, {"node_id": "other-node"})
                self.assertEqual(arbitrary_node.exception.code, "provision_node_denied")

                with self.assertRaises(static_server.BrowserError) as arbitrary_model:
                    static_server.provision_main_fleet_node(self.server, self.user, {"model": "other-model"})
                self.assertEqual(arbitrary_model.exception.code, "provision_model_denied")

                with self.assertRaises(static_server.BrowserError) as arbitrary_type:
                    static_server.provision_main_fleet_node(self.server, self.user, {"agent_type": "claude"})
                self.assertEqual(arbitrary_type.exception.code, "provision_agent_type_denied")
                with static_server.auth_connect() as conn:
                    provision_denials = conn.execute(
                        "SELECT COUNT(*) AS total FROM instance_audit_tb WHERE action = 'fleet.provision_main.denied'"
                    ).fetchone()
                self.assertGreaterEqual(int(provision_denials["total"]), 4)

    def test_agent_harness_hermes_backend_charges_ten_flux_and_binds_node(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
            self.seed_accounts()
            node_id = static_server.account_main_node_id(self.user)
            static_server.grant_flux_credits(
                self.admin,
                "101",
                {"amount": 10, "reason": "harness", "idempotency_key": "grant-harness"},
            )

            def fake_bridge(server, method, path, body):
                if method == "POST" and path == "/nodes":
                    self.assertEqual(body["node_id"], node_id)
                    self.assertEqual(body["default_model_provider"], "opencode-go")
                    self.assertEqual(body["default_model"], "kimi-k2.6")
                    self.assertEqual(body["OPENROUTER_API_KEY"], "sk-or-harness")
                    self.assertEqual(body["OPENAI_BASE_URL"], "https://opencode.ai/zen/go/v1")
                    self.assertIn("Agent name: Research harness", body["personality"])
                    self.assertIn("Instructions: Work inside the sandbox.", body["personality"])
                    (self.env_root / f"{node_id}.env").write_text(
                        "API_SERVER_HOST=127.0.0.1\nAPI_SERVER_PORT=9876\n",
                        encoding="utf-8",
                    )
                    return {"ok": True, "node_create": {"node_id": node_id}}
                if method == "GET" and path == "/health":
                    return {"ok": True, "health": {"status": "ok"}}
                if method == "GET" and path == f"/nodes/{node_id}":
                    return {"ok": True, "node": {"id": node_id, "running": True, "status": "running"}}
                raise AssertionError((method, path, body))

            with patch.object(static_server, "bridge_proxy", side_effect=fake_bridge):
                result = static_server.provision_agent_harness_node(
                    self.server,
                    self.user,
                    {
                        "idempotency_key": "harness-one",
                        "harness_name": "Research harness",
                        "harness_type": "hermes",
                        "infra_mode": "hermes_backend",
                        "instructions": "Work inside the sandbox.",
                        "provider_config": HARNESS_PROVIDER_CONFIG,
                    },
                )
            self.assertTrue(result["charged"])
            self.assertEqual(result["cost"], 10)
            self.assertEqual(result["credits"]["balance"], 0)
            self.assertEqual(result["harness"]["lifecycle_state"], "ready")
            self.assertEqual(result["harness"]["node_id"], node_id)
            self.assertEqual(result["harness"]["user_id"], str(self.user["id"]))
            self.assertEqual(result["harness"]["harness_type"], "hermes")

    def test_agent_harness_custom_bridge_does_not_charge_flux(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
            self.seed_accounts()
            with patch.object(
                static_server,
                "probe_custom_bridge_url",
                return_value={"routes": {"health": "/health", "models": "/bridge/v1/models", "chat": ["/bridge/v1/chat"]}},
            ) as probe:
                result = static_server.provision_agent_harness_node(
                    self.server,
                    self.user,
                    {
                        "harness_name": "Private bridge",
                        "harness_type": "hermes",
                        "infra_mode": "custom_bridge",
                        "bridge_url": "https://your-domain.example/bridge",
                    },
                )
            probe.assert_called_once()
            self.assertFalse(result["charged"])
            self.assertEqual(result["credits"]["balance"], 0)
            self.assertEqual(result["harness"]["infra_mode"], "custom_bridge")
            self.assertEqual(result["harness"]["harness_type"], "hermes")
            self.assertEqual(result["harness"]["lifecycle_state"], "ready")

    def test_agent_harness_insufficient_flux_unavailable_provider_and_failure_refund(self) -> None:
        with patch.dict(os.environ, self.env, clear=True):
            self.seed_accounts()
            with self.assertRaises(static_server.BrowserError) as insufficient:
                static_server.provision_agent_harness_node(
                    self.server,
                    self.user,
                    {"harness_name": "No credits", "harness_type": "hermes", "infra_mode": "hermes_backend"},
                )
            self.assertEqual(insufficient.exception.code, "insufficient_flux_credits")

            with self.assertRaises(static_server.BrowserError) as unavailable:
                static_server.provision_agent_harness_node(
                    self.server,
                    self.user,
                    {"harness_name": "Claude", "harness_type": "claude", "infra_mode": "hermes_backend"},
                )
            self.assertEqual(unavailable.exception.code, "provider_not_available")

            with self.assertRaises(static_server.BrowserError) as direct_harness:
                static_server.provision_agent_harness_node(
                    self.server,
                    self.user,
                    {"harness_name": "Browser direct", "harness_type": "hermes", "infra_mode": "browser_direct"},
                )
            self.assertEqual(direct_harness.exception.code, "provider_not_available")

            static_server.grant_flux_credits(
                self.admin,
                "101",
                {"amount": 10, "reason": "refund", "idempotency_key": "grant-refund"},
            )
            with patch.object(
                static_server,
                "bridge_proxy",
                side_effect=static_server.BrowserError(
                    "bridge_unavailable",
                    "orchestrator down",
                    status=static_server.HTTPStatus.BAD_GATEWAY,
                ),
            ):
                with self.assertRaises(static_server.BrowserError):
                    static_server.provision_agent_harness_node(
                        self.server,
                        self.user,
                        {
                            "idempotency_key": "harness-fails",
                            "harness_name": "Refund me",
                            "harness_type": "hermes",
                            "infra_mode": "hermes_backend",
                            "provider_config": HARNESS_PROVIDER_CONFIG,
                        },
                    )
            self.assertEqual(static_server.account_credits(self.user)["balance"], 10)
            with static_server.auth_connect() as conn:
                row = conn.execute(
                    "SELECT lifecycle_state, failure_reason FROM agent_harness_tb WHERE harness_name = 'Refund me' ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
            self.assertEqual(row["lifecycle_state"], "failed")
            self.assertIn("orchestrator down", row["failure_reason"])


if __name__ == "__main__":
    unittest.main()
