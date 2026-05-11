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


class FakeHeaders(dict):
    def get(self, key, default=None):  # noqa: ANN001 - mirrors http header mapping
        return super().get(key, default)


class FakeHandler:
    def __init__(self, *, client_id: str, device_id: str, account_device_id: str = "browser-profile") -> None:
        self.headers = FakeHeaders({
            "User-Agent": "Mozilla/5.0 Test Browser",
            "X-Wasm-Agent-Device-Id": account_device_id,
            "X-Wasm-Agent-Voice-Lab-Client-Id": client_id,
            "X-Wasm-Agent-Voice-Lab-Device-Id": device_id,
        })
        self.client_address = ("127.0.0.1", 49152)


def make_user(user_id: str, email: str) -> dict[str, object]:
    return {
        "id": user_id,
        "provider": "test",
        "email": email,
        "email_verified": True,
        "role": "user",
        "name": email.split("@", 1)[0],
        "picture_url": "",
        "created_at": 0,
        "last_login_at": 0,
    }


class VoiceLabRoomTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        state_dir = Path(self.tempdir.name) / "state"
        self.server = SimpleNamespace(
            plugin_root=PLUGIN_ROOT,
            public_root=PLUGIN_ROOT / "public",
            state_dir=state_dir,
            bridge_url="http://127.0.0.1:8790",
            browser_timeout_sec=1.0,
        )
        self.user = make_user("101", "voice@example.test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_duplicate_tabs_keep_separate_lab_presence(self) -> None:
        tab_one = FakeHandler(client_id="tab-one", device_id="vl-dev-tab-one")
        tab_two = FakeHandler(client_id="tab-two", device_id="vl-dev-tab-two")

        static_server.voice_lab_room(
            self.server,
            self.user,
            {"action": "presence", "room_id": "debug-room"},
            tab_one,
        )
        room = static_server.voice_lab_room(
            self.server,
            self.user,
            {"action": "presence", "room_id": "debug-room"},
            tab_two,
        )["room"]

        self.assertEqual(room["schema"], static_server.VOICE_LAB_ROOM_SCHEMA)
        self.assertEqual(room["current_device_id"], "vl-dev-tab-two")
        self.assertEqual(
            {entry["device_id"] for entry in room["presence"]},
            {"vl-dev-tab-one", "vl-dev-tab-two"},
        )
        self.assertEqual(
            {entry["client_id"] for entry in room["presence"]},
            {"tab-one", "tab-two"},
        )

    def test_voice_lab_signal_overrides_sender_and_preserves_sdp(self) -> None:
        handler = FakeHandler(client_id="tab-one", device_id="vl-dev-tab-one")
        long_sdp = "v=0\r\n" + ("a=rtpmap:111 opus/48000/2\r\n" * 240)

        room = static_server.voice_lab_room(
            self.server,
            self.user,
            {
                "action": "signal",
                "kind": "voice-signal",
                "room_id": "debug-room",
                "payload": {
                    "voice_schema": "hermes.wasm_agent.shared_space.voice_signal.v1",
                    "type": "offer",
                    "room_id": "spoofed-room",
                    "call_id": "voice-call",
                    "from_device_id": "spoofed-device",
                    "from_client_id": "spoofed-client",
                    "to_device_id": "vl-dev-tab-two",
                    "join_epoch": "join-a",
                    "target_join_epoch": "join-b",
                    "sdp": long_sdp,
                    "api_token": "placeholder-value",
                },
            },
            handler,
        )["room"]

        event = room["events"][-1]
        self.assertEqual(event["kind"], "voice-signal")
        self.assertEqual(event["payload"]["room_id"], "debug-room")
        self.assertEqual(event["payload"]["from_device_id"], "vl-dev-tab-one")
        self.assertEqual(event["payload"]["from_client_id"], "tab-one")
        self.assertEqual(event["payload"]["to_device_id"], "vl-dev-tab-two")
        self.assertEqual(event["payload"]["sdp"], long_sdp)
        self.assertEqual(event["payload"]["api_token"], "[redacted]")


if __name__ == "__main__":
    unittest.main()
