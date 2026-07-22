#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins/wasm-agent/server"))
import app_config


class WasmAgentAppConfigTests(unittest.TestCase):
    def test_cloud_projects_same_origin_bridge_without_internal_url(self) -> None:
        config = app_config.payload(
            app_name="wasm-agent",
            app_version="1",
            internal_bridge_url="http://127.0.0.1:8790",
            agent_turn_timeout_sec=30,
            google_client_id="client",
            google_login_uri="https://wa.colmeio.com/auth/google/callback",
            public_origin="https://wa.colmeio.com",
            deployment_mode="cloud",
            instance_id="production",
            host_browser_enabled=False,
            public_default_disabled=True,
            shared_voice_enabled=False,
            shared_voice_ice_servers=[],
        )
        self.assertEqual(config["bridgeUrl"], "https://wa.colmeio.com/bridge")
        self.assertEqual(config["bridge"]["url"], "https://wa.colmeio.com/bridge")
        self.assertFalse(config["features"]["devHmr"]["enabled"])
        self.assertNotIn("127.0.0.1", str(config))

    def test_local_retains_direct_bridge(self) -> None:
        self.assertEqual(app_config.projected_bridge_url(
            internal_url="http://127.0.0.1:8790/",
            deployment_mode="local",
            public_origin="",
        ), "http://127.0.0.1:8790")

    def test_local_config_enables_development_hmr(self) -> None:
        config = app_config.payload(
            app_name="wasm-agent", app_version="1",
            internal_bridge_url="http://127.0.0.1:8790", agent_turn_timeout_sec=30,
            google_client_id="client", google_login_uri="http://127.0.0.1/auth/google/callback",
            public_origin="http://127.0.0.1:8877", deployment_mode="local", instance_id="dev",
            host_browser_enabled=False, public_default_disabled=True,
            shared_voice_enabled=False, shared_voice_ice_servers=[],
        )
        self.assertTrue(config["features"]["devHmr"]["enabled"])


if __name__ == "__main__":
    unittest.main()
