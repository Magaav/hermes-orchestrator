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


def user(user_id: str, email: str) -> dict[str, object]:
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


def insert_account(conn, user_id: int, email: str, name: str | None = None) -> None:
    now = int(static_server.time.time())
    conn.execute(
        """
        INSERT INTO user_tb (
          id, provider, provider_sub, email, email_verified, name,
          picture_url, created_at, updated_at, last_login_at
        ) VALUES (?, 'test', ?, ?, 1, ?, '', ?, ?, ?)
        """,
        (user_id, str(user_id), email, name or email.split("@", 1)[0].title(), now, now, now),
    )


class ClientFirstCloudTest(unittest.TestCase):
    def test_cloud_mode_resolves_private_state_and_rejects_plugin_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cloud_root = Path(tmp) / "private-instance"
            env = {
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "cloud",
                "HERMES_WASM_AGENT_CLOUD_STATE_ROOT": str(cloud_root),
            }
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(static_server.resolve_wasm_agent_state_dir(PLUGIN_ROOT), cloud_root / "state")
                self.assertEqual(static_server.auth_db_path(), cloud_root / "state" / "db" / "sqlite" / "wa_db.sqlite3")
                self.assertEqual(static_server.auth_secret_path(), cloud_root / "state" / "db" / "sqlite" / "wa_auth_secret")

            unsafe_env = {
                **env,
                "HERMES_WASM_AGENT_STATE_DIR": str(PLUGIN_ROOT / "state"),
            }
            with patch.dict(os.environ, unsafe_env, clear=True):
                with self.assertRaises(RuntimeError):
                    static_server.resolve_wasm_agent_state_dir(PLUGIN_ROOT)

    def test_friend_sync_and_fleet_metadata_stay_lightweight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            db_path = state_dir / "db" / "wa.sqlite3"
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(db_path),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            with patch.dict(os.environ, env, clear=True):
                with static_server.auth_connect() as conn:
                    insert_account(conn, 101, "owner@example.test", "Owner")
                    insert_account(conn, 202, "member@example.test", "Member")

                owner = user("101", "owner@example.test")
                member = user("202", "member@example.test")
                lookup = static_server.account_user_lookup("member@example.test", owner)
                self.assertEqual(lookup["user"]["id"], "202")

                request = static_server.request_friendship(owner, {"email": "member@example.test"})
                self.assertEqual(request["friendship"]["status"], "pending")
                accepted = static_server.respond_friendship(
                    member,
                    {
                        "friendship_id": request["friendship"]["id"],
                        "response": "accepted",
                    },
                )
                self.assertEqual(accepted["friendship"]["status"], "accepted")

                server = SimpleNamespace(plugin_root=PLUGIN_ROOT, public_root=PLUGIN_ROOT / "public", state_dir=state_dir)
                event = static_server.append_sync_event(
                    server,
                    owner,
                    {
                        "conversation_id": "dm-101-202",
                        "peer_user_id": "202",
                        "client_event_id": "client-one",
                        "kind": "chat-message",
                        "payload": {"text": "hello from local-first chat"},
                    },
                )["event"]
                self.assertEqual(event["payload"]["text"], "hello from local-first chat")
                events = static_server.list_sync_events(server, member, {"conversation_id": ["dm-101-202"]})
                self.assertEqual(len(events["events"]), 1)
                self.assertEqual(events["cursor"], event["id"])

                fleet = static_server.ensure_main_fleet_node(owner, {})
                self.assertFalse(fleet["provisioned"])
                self.assertTrue(fleet["node"]["node_id"].startswith("u"))
                self.assertFalse(fleet["node"]["node_id"].endswith("-main"))
                listed = static_server.list_user_fleet(owner)
                self.assertEqual(listed["nodes"], [])
                self.assertEqual(listed["system_nodes"][0]["node_id"], fleet["node"]["node_id"])

                with self.assertRaises(static_server.BrowserError) as provider_node:
                    static_server.ensure_main_fleet_node(owner, {"node_id": "agent:opencode-go:kimi-k2.6"})
                self.assertEqual(provider_node.exception.code, "fleet_node_denied")
                listed_after = static_server.list_user_fleet(owner)
                self.assertEqual(listed_after["nodes"], [])
                self.assertEqual(len(listed_after["system_nodes"]), 1)

    def test_friend_lifecycle_is_realtime_poll_safe_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state" / "db" / "wa.sqlite3"
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(db_path),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            with patch.dict(os.environ, env, clear=True):
                with static_server.auth_connect() as conn:
                    insert_account(conn, 101, "alice@example.test", "Alice")
                    insert_account(conn, 202, "bob@example.test", "Bob")
                    insert_account(conn, 303, "casey@example.test", "Casey")

                alice = user("101", "alice@example.test")
                bob = user("202", "bob@example.test")
                casey = user("303", "casey@example.test")

                request = static_server.request_friendship(alice, {"email": "bob@example.test"})["friendship"]
                self.assertEqual(request["status"], "pending")
                alice_list = static_server.list_friendships(alice)["friendships"]
                bob_list = static_server.list_friendships(bob)["friendships"]
                self.assertEqual(alice_list[0]["direction"], "outgoing")
                self.assertEqual(bob_list[0]["direction"], "incoming")

                canceled = static_server.respond_friendship(alice, {"friendship_id": request["id"], "response": "canceled"})
                self.assertEqual(canceled["friendship"]["status"], "canceled")
                self.assertEqual(static_server.list_friendships(alice)["friendships"], [])
                unchanged = static_server.respond_friendship(bob, {"friendship_id": request["id"], "response": "accepted"})
                self.assertTrue(unchanged["unchanged"])
                self.assertEqual(unchanged["status"], "canceled")

                request = static_server.request_friendship(alice, {"email": "bob@example.test"})["friendship"]
                declined = static_server.respond_friendship(bob, {"friendship_id": request["id"], "response": "declined"})
                self.assertEqual(declined["friendship"]["status"], "declined")
                self.assertEqual(static_server.list_friendships(bob)["friendships"], [])

                request = static_server.request_friendship(alice, {"user_id": "202"})["friendship"]
                with self.assertRaises(static_server.BrowserError) as denied:
                    static_server.respond_friendship(casey, {"friendship_id": request["id"], "response": "accepted"})
                self.assertEqual(denied.exception.status, static_server.HTTPStatus.FORBIDDEN)

                accepted = static_server.respond_friendship(bob, {"friendship_id": request["id"], "response": "accepted"})
                self.assertEqual(accepted["friendship"]["status"], "accepted")
                self.assertEqual(static_server.respond_friendship(bob, {"friendship_id": request["id"], "response": "accepted"})["friendship"]["status"], "accepted")
                self.assertEqual(static_server.list_friendships(alice)["friendships"][0]["status"], "accepted")
                self.assertEqual(static_server.list_friendships(bob)["friendships"][0]["status"], "accepted")

                removed = static_server.respond_friendship(alice, {"friendship_id": request["id"], "response": "removed"})
                self.assertEqual(removed["friendship"]["status"], "removed")
                self.assertEqual(static_server.respond_friendship(bob, {"friendship_id": request["id"], "response": "removed"})["friendship"]["status"], "removed")
                self.assertEqual(static_server.list_friendships(alice)["friendships"], [])
                self.assertEqual(static_server.list_friendships(bob)["friendships"], [])

    def test_direct_chat_events_are_friend_gated_ordered_and_deduped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            db_path = state_dir / "db" / "wa.sqlite3"
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(db_path),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            with patch.dict(os.environ, env, clear=True):
                with static_server.auth_connect() as conn:
                    insert_account(conn, 101, "alice@example.test", "Alice")
                    insert_account(conn, 202, "bob@example.test", "Bob")
                    insert_account(conn, 303, "casey@example.test", "Casey")

                server = SimpleNamespace(plugin_root=PLUGIN_ROOT, public_root=PLUGIN_ROOT / "public", state_dir=state_dir)
                alice = user("101", "alice@example.test")
                bob = user("202", "bob@example.test")
                casey = user("303", "casey@example.test")

                with self.assertRaises(static_server.BrowserError) as non_friend:
                    static_server.append_sync_event(
                        server,
                        alice,
                        {
                            "conversation_id": "dm-101-202",
                            "peer_user_id": "202",
                            "client_event_id": "before-friendship",
                            "kind": "chat-message",
                            "payload": {"text": "blocked"},
                        },
                    )
                self.assertEqual(non_friend.exception.status, static_server.HTTPStatus.FORBIDDEN)

                request = static_server.request_friendship(alice, {"email": "bob@example.test"})["friendship"]
                static_server.respond_friendship(bob, {"friendship_id": request["id"], "response": "accepted"})
                first = static_server.append_sync_event(
                    server,
                    alice,
                    {
                        "conversation_id": "dm-101-202",
                        "peer_user_id": "202",
                        "client_event_id": "hello-once",
                        "kind": "chat-message",
                        "payload": {"text": "hello 👋", "local_message_id": "local-1"},
                    },
                )["event"]
                duplicate = static_server.append_sync_event(
                    server,
                    alice,
                    {
                        "conversation_id": "dm-101-202",
                        "peer_user_id": "202",
                        "client_event_id": "hello-once",
                        "kind": "chat-message",
                        "payload": {"text": "hello 👋", "local_message_id": "local-1"},
                    },
                )["event"]
                self.assertEqual(duplicate["id"], first["id"])

                sticker = static_server.append_sync_event(
                    server,
                    bob,
                    {
                        "conversation_id": "dm-101-202",
                        "peer_user_id": "101",
                        "client_event_id": "sticker-one",
                        "kind": "sticker",
                        "payload": {"sticker": {"id": "ship-it", "emoji": "🚀", "label": "ship it"}},
                    },
                )["event"]
                reaction = static_server.append_sync_event(
                    server,
                    bob,
                    {
                        "conversation_id": "dm-101-202",
                        "peer_user_id": "101",
                        "client_event_id": "reaction-one",
                        "kind": "reaction",
                        "payload": {"message_event_id": first["id"], "emoji": "🔥"},
                    },
                )["event"]

                synced = static_server.list_sync_events(server, bob, {"conversation_id": ["dm-101-202"]})
                self.assertEqual([event["id"] for event in synced["events"]], [first["id"], sticker["id"], reaction["id"]])
                after_first = static_server.list_sync_events(server, alice, {"conversation_id": ["dm-101-202"], "after_id": [first["id"]]})
                self.assertEqual([event["id"] for event in after_first["events"]], [sticker["id"], reaction["id"]])
                global_feed = static_server.list_sync_events(server, bob, {"after_id": ["0"]})
                self.assertEqual(len(global_feed["events"]), 3)

                with self.assertRaises(static_server.BrowserError):
                    static_server.list_sync_events(server, casey, {"conversation_id": ["dm-101-202"]})

                static_server.respond_friendship(alice, {"friendship_id": request["id"], "response": "removed"})
                with self.assertRaises(static_server.BrowserError) as removed_friend:
                    static_server.append_sync_event(
                        server,
                        bob,
                        {
                            "conversation_id": "dm-101-202",
                            "peer_user_id": "101",
                            "client_event_id": "after-remove",
                            "kind": "chat-message",
                            "payload": {"text": "blocked after remove"},
                        },
                    )
                self.assertEqual(removed_friend.exception.status, static_server.HTTPStatus.FORBIDDEN)

    def test_shared_space_chat_events_are_member_gated_ordered_and_deduped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            db_path = state_dir / "db" / "wa.sqlite3"
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(db_path),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
            }
            with patch.dict(os.environ, env, clear=True):
                with static_server.auth_connect() as conn:
                    insert_account(conn, 101, "alice@example.test", "Alice")
                    insert_account(conn, 202, "bob@example.test", "Bob")
                    insert_account(conn, 303, "casey@example.test", "Casey")

                server = SimpleNamespace(plugin_root=PLUGIN_ROOT, public_root=PLUGIN_ROOT / "public", state_dir=state_dir)
                alice = user("101", "alice@example.test")
                bob = user("202", "bob@example.test")
                casey = user("303", "casey@example.test")
                shared_space_id = "share-chat"
                static_server.write_json_file(
                    static_server.shared_space_record_path(server, shared_space_id),
                    {
                        "schema": static_server.SHARED_SPACE_SCHEMA,
                        "id": shared_space_id,
                        "title": "Shared Chat",
                        "owner_user_id": "101",
                        "members": [{"user_id": "202"}],
                        "created_at": static_server.iso_timestamp(),
                        "updated_at": static_server.iso_timestamp(),
                    },
                )

                first = static_server.append_sync_event(
                    server,
                    alice,
                    {
                        "shared_space_id": shared_space_id,
                        "client_event_id": "space-hello",
                        "kind": "space-message",
                        "payload": {"text": "hello shared space", "local_message_id": "space-local-1"},
                    },
                )["event"]
                duplicate = static_server.append_sync_event(
                    server,
                    alice,
                    {
                        "shared_space_id": shared_space_id,
                        "client_event_id": "space-hello",
                        "kind": "space-message",
                        "payload": {"text": "hello shared space", "local_message_id": "space-local-1"},
                    },
                )["event"]
                self.assertEqual(duplicate["id"], first["id"])
                reply = static_server.append_sync_event(
                    server,
                    bob,
                    {
                        "shared_space_id": shared_space_id,
                        "client_event_id": "space-reply",
                        "kind": "space-message",
                        "payload": {"text": "reply from member"},
                    },
                )["event"]

                listed = static_server.list_sync_events(server, bob, {"shared_space_id": [shared_space_id]})
                self.assertEqual([event["id"] for event in listed["events"]], [first["id"], reply["id"]])
                self.assertEqual(listed["events"][0]["conversation_id"], f"space-{shared_space_id}")
                after_first = static_server.list_sync_events(server, alice, {"shared_space_id": [shared_space_id], "after_id": [first["id"]]})
                self.assertEqual([event["id"] for event in after_first["events"]], [reply["id"]])

                with self.assertRaises(static_server.BrowserError) as denied_list:
                    static_server.list_sync_events(server, casey, {"shared_space_id": [shared_space_id]})
                self.assertEqual(denied_list.exception.status, static_server.HTTPStatus.FORBIDDEN)
                with self.assertRaises(static_server.BrowserError) as denied_send:
                    static_server.append_sync_event(
                        server,
                        casey,
                        {
                            "shared_space_id": shared_space_id,
                            "client_event_id": "space-outsider",
                            "kind": "space-message",
                            "payload": {"text": "blocked"},
                        },
                    )
                self.assertEqual(denied_send.exception.status, static_server.HTTPStatus.FORBIDDEN)


if __name__ == "__main__":
    unittest.main()
