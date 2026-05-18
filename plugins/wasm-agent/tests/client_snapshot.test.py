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
assert spec and spec.loader
static_server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(static_server)


def make_user(user_id: str) -> dict[str, object]:
    return {
        "id": user_id,
        "provider": "test",
        "email": f"{user_id}@example.test",
        "email_verified": True,
        "role": "user",
        "name": user_id,
        "picture_url": "",
        "created_at": 0,
        "last_login_at": 0,
    }


class ClientSnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.server = SimpleNamespace(
            plugin_root=PLUGIN_ROOT,
            public_root=PLUGIN_ROOT / "public",
            state_dir=Path(self.tempdir.name) / "state",
            bridge_url="http://127.0.0.1:8790",
            browser_timeout_sec=1.0,
        )
        self.user = make_user("202")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_client_snapshot_persists_latest_and_redacts_secrets(self) -> None:
        result = static_server.save_client_snapshot(
            self.server,
            {
                "schema": static_server.CLIENT_SNAPSHOT_SCHEMA,
                "snapshot_id": "manual-debug",
                "active_session_id": "session-a",
                "agent": {
                    "direct_provider": {
                        "provider": "openrouter",
                        "model": "test-model",
                        "apiKey": "secret-key",
                        "token": "secret-token",
                    }
                },
                "sessions": [
                    {
                        "id": "session-a",
                        "messages": [
                            {"role": "user", "content": "why did the artifact not apply?"},
                            {"role": "assistant", "content": "No valid WIS patch was emitted."},
                        ],
                    }
                ],
            },
            user=self.user,
        )

        self.assertTrue(result["stored"])
        self.assertEqual(result["active_session_id"], "session-a")

        latest = static_server.latest_client_snapshot(self.server, self.user)
        snapshot = latest["snapshot"]
        self.assertEqual(snapshot["snapshot_id"], "manual-debug")
        self.assertEqual(snapshot["sessions"][0]["messages"][0]["content"], "why did the artifact not apply?")
        provider = snapshot["agent"]["direct_provider"]
        self.assertEqual(provider["provider"], "openrouter")
        self.assertEqual(provider["apiKey"], "[redacted]")
        self.assertEqual(provider["token"], "[redacted]")

    def test_client_snapshot_request_response_persists_payload(self) -> None:
        created = static_server.create_client_snapshot_request(
            self.server,
            {"request_id": "ask-context", "scope": "context", "source": "test"},
            self.user,
        )
        self.assertEqual(created["request"]["type"], "client.snapshot.request")
        self.assertEqual(created["request"]["scope"], "context")

        pending = static_server.list_client_snapshot_requests(self.server, self.user)
        self.assertEqual([item["request_id"] for item in pending["requests"]], ["ask-context"])

        response = static_server.save_client_snapshot_response(
            self.server,
            {
                "schema": static_server.CLIENT_SNAPSHOT_RESPONSE_SCHEMA,
                "type": "client.snapshot.response",
                "request_id": "ask-context",
                "ok": True,
                "payload": {
                    "schema": static_server.CLIENT_SNAPSHOT_SCHEMA,
                    "snapshot_id": "client-context",
                    "scope": "context",
                    "active_session_id": "session-b",
                    "sessions": [],
                },
            },
            self.user,
        )
        self.assertTrue(response["stored"])

        pending_after = static_server.list_client_snapshot_requests(self.server, self.user)
        self.assertEqual(pending_after["requests"], [])
        latest = static_server.latest_client_snapshot(self.server, self.user)["snapshot"]
        self.assertEqual(latest["snapshot_id"], "client-context")
        self.assertEqual(latest["request_id"], "ask-context")
        self.assertEqual(latest["request_scope"], "context")


if __name__ == "__main__":
    unittest.main()
