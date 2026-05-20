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


def make_user(user_id: str, email: str = "user@example.test") -> dict[str, object]:
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


class SpaceRegressionTest(unittest.TestCase):
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
        self.user = make_user("202", "zangao.colmeio@example.test")
        self.user_spaces = state_dir / "users" / "202" / "spaces"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_reserved_display_labels_do_not_round_trip_as_user_spaces(self) -> None:
        (self.user_spaces / "space-home" / "wis").mkdir(parents=True)
        (self.user_spaces / "space-admin" / "wis").mkdir(parents=True)

        listed = static_server.list_user_spaces(self.server, self.user)
        self.assertEqual(listed["spaces"], [])

        saved = static_server.save_user_spaces(self.server, self.user, {
            "action": "replace",
            "spaces": [
                {"id": "space-home", "title": "space-home"},
                {"id": "space-admin", "title": "space-admin"},
                {"id": "project-room", "title": "Project Room"},
            ],
        })

        self.assertEqual([space["id"] for space in saved["spaces"]], ["project-room"])
        self.assertFalse((self.user_spaces / "space-home").exists())
        self.assertFalse((self.user_spaces / "space-admin").exists())

    def test_wis_patch_display_label_space_ids_target_builtin_storage(self) -> None:
        home_result = static_server.patch_wis_artifact(self.server, self.user, {
            "schema": static_server.WIS_PATCH_SCHEMA,
            "space_id": "space-home",
            "artifact_id": "brief",
            "operations": [{"op": "set_title", "title": "Home Brief"}],
        })
        admin_result = static_server.patch_wis_artifact(self.server, self.user, {
            "schema": static_server.WIS_PATCH_SCHEMA,
            "space_id": "space-admin",
            "artifact_id": "brief",
            "operations": [{"op": "set_title", "title": "Admin Brief"}],
        })

        self.assertEqual(home_result["space_id"], "home")
        self.assertEqual(home_result["scope"], "user:202:home")
        self.assertEqual(admin_result["space_id"], "admin")
        self.assertEqual(admin_result["scope"], "user:202:admin")
        self.assertTrue((self.user_spaces / "home" / "wis" / "brief.json").exists())
        self.assertTrue((self.user_spaces / "admin" / "wis" / "brief.json").exists())
        self.assertFalse((self.user_spaces / "space-home").exists())
        self.assertFalse((self.user_spaces / "space-admin").exists())


if __name__ == "__main__":
    unittest.main()
