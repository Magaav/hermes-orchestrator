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
    def __init__(self, *, device_id: str = "device-a") -> None:
        self.headers = FakeHeaders({
            "User-Agent": "Mozilla/5.0 Test Browser",
            "X-Wasm-Agent-Device-Id": device_id,
        })
        self.client_address = ("127.0.0.1", 49152)


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


class WisSharedSpaceTest(unittest.TestCase):
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
        self.owner = make_user("101", "owner@example.test")
        self.member = make_user("202", "member@example.test")
        self.outsider = make_user("303", "outsider@example.test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def create_owner_space(self) -> None:
        static_server.save_user_spaces(self.server, self.owner, {
            "action": "replace",
            "spaces": [
                {
                    "id": "playground",
                    "title": "Playground",
                    "space_area": {"width_px": 1600, "height_px": 900},
                }
            ],
        })

    def test_share_join_room_presence_and_redaction(self) -> None:
        self.create_owner_space()
        shared = static_server.share_user_space(self.server, self.owner, {
            "space_id": "playground",
            "title": "Playground",
        })["shared_space"]

        shared_id = shared["id"]
        join_code = shared["join_code"]
        self.assertEqual(shared["space_area"], {"width_px": 1600, "height_px": 900})

        joined = static_server.join_shared_space(
            self.server,
            self.member,
            {"join_code": f"http://127.0.0.1:8877/home?join_space={join_code}"},
            FakeHandler(device_id="member-device"),
        )
        joined_space = joined["spaces"]["spaces"][0]
        self.assertEqual(joined_space["shared_space_id"], shared_id)
        self.assertEqual(joined_space["space_area"], {"width_px": 1600, "height_px": 900})

        room = static_server.shared_space_room(
            self.server,
            self.member,
            {
                "action": "message",
                "shared_space_id": shared_id,
                "space_id": joined_space["id"],
                "kind": "chat",
                "payload": {
                    "text": "hello from the joined space",
                    "api_token": "placeholder-value",
                },
            },
            FakeHandler(device_id="member-device"),
        )["room"]

        self.assertEqual(room["schema"], static_server.SHARED_SPACE_ROOM_SCHEMA)
        self.assertEqual(room["member_count"], 2)
        self.assertEqual(room["online_count"], 1)
        self.assertEqual(room["events"][-1]["payload"]["api_token"], "[redacted]")

        with self.assertRaises(static_server.BrowserError) as denied:
            static_server.shared_space_room(
                self.server,
                self.outsider,
                {"action": "read", "shared_space_id": shared_id},
                FakeHandler(device_id="outsider-device"),
            )
        self.assertEqual(denied.exception.status, static_server.HTTPStatus.FORBIDDEN)

    def test_wis_patch_applies_to_shared_artifact_scope(self) -> None:
        self.create_owner_space()
        shared = static_server.share_user_space(self.server, self.owner, {"space_id": "playground"})["shared_space"]
        static_server.join_shared_space(
            self.server,
            self.member,
            {"join_code": shared["join_code"]},
            FakeHandler(device_id="member-device"),
        )

        result = static_server.patch_wis_artifact(self.server, self.member, {
            "schema": static_server.WIS_PATCH_SCHEMA,
            "space_id": "playground",
            "shared_space_id": shared["id"],
            "artifact_id": "main",
            "operations": [
                {"op": "set_title", "title": "Shared Checklist"},
                {"op": "set_state", "key": "status", "value": "draft"},
                {
                    "op": "append_child",
                    "parent_id": "doc",
                    "node": {
                        "id": "step-one",
                        "type": "text",
                        "text": "Confirm the shared WIS artifact writes to shared state.",
                    },
                },
            ],
        })

        self.assertTrue(result["applied"])
        self.assertEqual(result["scope"], f"shared:{shared['id']}")
        self.assertEqual(result["operations"], 3)

        root = static_server.shared_space_dir(self.server, shared["id"]) / "wis"
        artifact = static_server.read_json_file(root / "main.json", {})
        self.assertEqual(artifact["title"], "Shared Checklist")
        document = artifact["documents"][0]
        self.assertEqual(document["state"]["status"], "draft")
        self.assertTrue(
            any(child.get("id") == "step-one" for child in document["tree"]["children"]),
            "patched WIS node was not persisted",
        )

    def test_agent_reply_wis_patch_block_is_applied_and_summarized(self) -> None:
        reply = """
Here is the userland patch.

```json
{
  "schema": "hermes.wasm_agent.wis.patch.v1",
  "artifact_id": "brief",
  "operations": [
    {"op": "set_title", "title": "Brief"},
    {"op": "append_child", "parent_id": "doc", "node": {"id": "summary", "type": "text", "text": "Done"}}
  ]
}
```
""".strip()

        summary, result = static_server.apply_agent_wis_patches_from_reply(
            self.server,
            reply,
            user=self.member,
            space_id="playground",
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["applied"])
        self.assertEqual(result["operations"], 2)
        self.assertIn("Applied WIS/userland patch", summary)
        self.assertNotIn("hermes.wasm_agent.wis.patch.v1", summary)


if __name__ == "__main__":
    unittest.main()
