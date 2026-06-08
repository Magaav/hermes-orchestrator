#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import base64
import io
import json
import os
import socket
import struct
import tempfile
import threading
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


class RemoteControlLiveSocket:
    def __init__(self, *, origin: str, cookie: str) -> None:
        host, port = origin.removeprefix("http://").split(":", 1)
        self.sock = socket.create_connection((host, int(port)), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            "GET /remote-control/live HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Origin: {origin}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Cookie: {cookie}\r\n"
            "\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.sock.recv(4096)
        headers, _, remainder = response.partition(b"\r\n\r\n")
        self.buffer = bytearray(remainder)
        if b" 101 " not in headers.split(b"\r\n", 1)[0]:
            raise AssertionError(f"remote-control live websocket handshake failed: {response[:200]!r}")

    def close(self) -> None:
        try:
            self.send_frame(0x8)
        except Exception:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def send_json(self, payload: dict[str, object]) -> None:
        self.send_frame(0x1, json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    def send_frame(self, opcode: int, payload: bytes = b"") -> None:
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def recv_json(self, *, timeout: float = 2.0) -> dict[str, object]:
        self.sock.settimeout(timeout)
        while True:
            opcode, payload = self.recv_frame()
            if opcode == 0x8:
                raise AssertionError("remote-control live websocket closed")
            if opcode == 0x9:
                self.send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                value = json.loads(payload.decode("utf-8"))
                if isinstance(value, dict):
                    return value

    def recv_type(self, message_type: str, *, timeout: float = 2.0) -> dict[str, object]:
        deadline = static_server.time.monotonic() + timeout
        while static_server.time.monotonic() < deadline:
            remaining = max(0.1, deadline - static_server.time.monotonic())
            message = self.recv_json(timeout=remaining)
            if message.get("type") == message_type:
                return message
        raise AssertionError(f"remote-control live websocket did not receive type={message_type!r}")

    def recv_frame(self) -> tuple[int, bytes]:
        first = self._recv_exact(2)
        opcode = first[0] & 0x0F
        masked = bool(first[1] & 0x80)
        length = first[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length) if length else b""
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def _recv_exact(self, length: int) -> bytes:
        chunks = bytearray()
        if self.buffer:
            take = min(length, len(self.buffer))
            chunks.extend(self.buffer[:take])
            del self.buffer[:take]
        while len(chunks) < length:
            chunk = self.sock.recv(length - len(chunks))
            if not chunk:
                raise AssertionError("remote-control live websocket closed")
            chunks.extend(chunk)
        return bytes(chunks)


def start_static_test_server(state_dir: Path) -> tuple[static_server.WasmAgentServer, threading.Thread]:
    def handler(*handler_args, **handler_kwargs):
        return static_server.WasmAgentHandler(
            *handler_args,
            directory=str(PLUGIN_ROOT / "public"),
            **handler_kwargs,
        )

    httpd = static_server.WasmAgentServer(
        ("127.0.0.1", 0),
        handler,
        plugin_root=PLUGIN_ROOT,
        public_root=PLUGIN_ROOT / "public",
        state_dir=state_dir,
        bridge_url="http://127.0.0.1:8790",
        browser_timeout_sec=1.0,
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


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

    def test_native_voice_command_event_writes_timeline_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = SimpleNamespace(state_dir=Path(tmp))
            handler = SimpleNamespace(
                headers={"X-Wasm-Agent-Native-Device-Id": "android-test-device"},
                client_address=("127.0.0.1", 45678),
            )

            result = static_server.save_native_event(
                server,
                {
                    "kind": "voice_command",
                    "device_id": "android-test-device",
                    "type": "voice_command",
                    "wake_word": "hermes",
                    "transcript": "open my current run logs",
                    "confidence": 0.82,
                    "source": "android_native_hermes_voice_wake",
                    "build_id": "android-test",
                    "session_id": "voice-session-test",
                    "privacy_mode": "wake-word-local-transcript-only",
                    "audio_retained": False,
                },
                handler,
            )

            self.assertTrue(result["stored"])
            latest = static_server.latest_native_voice_command(server)
            self.assertTrue(latest["available"])
            event = latest["event"]
            self.assertEqual(event["type"], "voice_command")
            self.assertEqual(event["wake_word"], "hermes")
            self.assertEqual(event["transcript"], "open my current run logs")
            self.assertEqual(event["source"], "android_native_hermes_voice_wake")
            self.assertFalse(event["audio_retained"])
            timeline = Path(tmp) / "native-events" / "voice-command-timeline.jsonl"
            self.assertIn("voice-session-test", timeline.read_text(encoding="utf-8"))

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

    def test_native_companion_package_targets_current_device_and_standby(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins" / "wasm-agent"
            plugin_root.mkdir(parents=True)
            state_dir = root / "state"
            server = SimpleNamespace(plugin_root=plugin_root, public_root=plugin_root / "public", state_dir=state_dir)
            owner = user("101", "owner@example.test")
            handler = SimpleNamespace(
                headers={
                    "User-Agent": "Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 Chrome/136.0 Safari/537.36",
                    "X-Wasm-Agent-Device-Id": "pixel-eight",
                },
                client_address=("127.0.0.1", 44770),
            )

            devices = static_server.list_account_devices(server, owner, handler)
            current_device_id = devices["current_device_id"]
            package = static_server.create_native_companion_package(
                server,
                owner,
                {
                    "device_id": current_device_id,
                    "standby_module_enabled": True,
                    "device_profile": {
                        "schema": "hermes.wasm_agent.native_device_profile.v1",
                        "os": "Android",
                        "browser": "Chrome",
                        "device_type": "phone",
                        "install_channel": "android-foreground-service",
                        "pwa_capabilities": {
                            "microphone": True,
                            "service_worker": True,
                            "wake_lock": True,
                            "screen_off_standby": False,
                        },
                    },
                },
                handler,
            )["package"]

            self.assertEqual(package["schema"], "hermes.wasm_agent.native_companion_package.v1")
            self.assertEqual(package["target_device_id"], current_device_id)
            self.assertEqual(package["target_os"], "Android")
            self.assertEqual(package["install_channel"], "android-foreground-service")
            self.assertEqual(package["standby"]["module_id"], "native-standby")
            self.assertEqual(package["standby"]["wake_phrase"], "hi wasm")
            self.assertTrue(package["standby"]["enabled_from_pwa"])
            self.assertFalse(package["standby"]["pwa_screen_off_standby"])
            self.assertTrue(package["standby"]["native_screen_off_standby"])
            request_path = state_dir / "users" / "101" / "native-companion" / f"{package['token_id']}.json"
            self.assertTrue(request_path.exists())

            missing = static_server.resolve_native_installer(
                server,
                owner,
                {
                    "platform": "android",
                    "arch": "arm64",
                    "deviceType": "phone",
                    "browser": "chrome",
                    "userAgent": handler.headers["User-Agent"],
                    "accountId": "101",
                    "deviceId": current_device_id,
                },
            )
            self.assertFalse(missing["available"])
            self.assertEqual(missing["platform"], "android")
            self.assertEqual(missing["kind"], "android-apk")
            self.assertEqual(missing["message"], "Native installer not built yet")
            self.assertEqual(missing["buildStatus"], "missing")
            self.assertEqual(missing["fallbacks"][0]["kind"], "pwa")

    def test_native_installer_resolver_and_download_stream_real_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins" / "wasm-agent"
            artifact = root / "native" / "windows" / "release" / "WASM-Agent-Setup-x64.exe"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"MZ wasm-agent setup")
            defaults = artifact.parent / "win-unpacked" / "resources" / "native-defaults.json"
            defaults.parent.mkdir(parents=True)
            defaults.write_text(
                json.dumps(
                    {
                        "schema": "hermes.wasm_agent.native_defaults.v1",
                        "wasmAgentVersion": "0.1.0",
                        "installableVersion": "0.1.0+win-x64-20260603T132803Z",
                        "buildId": "win-x64-20260603T132803Z",
                    }
                ),
                encoding="utf-8",
            )
            server = SimpleNamespace(plugin_root=plugin_root, public_root=plugin_root / "public", state_dir=root / "state")
            owner = user("101", "owner@example.test")

            resolved = static_server.resolve_native_installer(
                server,
                owner,
                {
                    "platform": "windows",
                    "arch": "x64",
                    "deviceType": "desktop",
                    "browser": "edge",
                    "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edg/136.0",
                    "accountId": "101",
                    "deviceId": "windows-device",
                },
            )
            self.assertTrue(resolved["available"])
            self.assertEqual(resolved["kind"], "windows-installer")
            self.assertEqual(resolved["filename"], "WASM-Agent-Setup-x64-0.1.0-20260603T132803Z.exe")
            self.assertEqual(resolved["artifactFilename"], "WASM-Agent-Setup-x64.exe")
            self.assertEqual(resolved["buildId"], "win-x64-20260603T132803Z")
            self.assertEqual(resolved["installableVersion"], "0.1.0+win-x64-20260603T132803Z")
            self.assertEqual(resolved["downloadUrl"], "/native/download?platform=windows&arch=x64&buildId=win-x64-20260603T132803Z")

            class DownloadHandler:
                def __init__(self) -> None:
                    self.server = server
                    self.path = "/native/download?platform=windows&arch=x64&buildId=win-x64-20260603T132803Z"
                    self.wfile = io.BytesIO()
                    self.status = None
                    self.headers = {}

                def send_response(self, status) -> None:
                    self.status = status

                def send_header(self, key, value) -> None:
                    self.headers[key] = value

                def end_headers(self) -> None:
                    pass

            download = DownloadHandler()
            static_server.serve_native_installer_download(download, owner)
            self.assertEqual(download.status, static_server.HTTPStatus.OK)
            self.assertEqual(download.headers["Content-Disposition"], 'attachment; filename="WASM-Agent-Setup-x64-0.1.0-20260603T132803Z.exe"')
            self.assertEqual(download.headers["X-Wasm-Agent-Native-Kind"], "windows-installer")
            self.assertEqual(download.headers["X-Wasm-Agent-Native-Build-Id"], "win-x64-20260603T132803Z")
            self.assertEqual(download.headers["X-Wasm-Agent-Native-Version"], "0.1.0+win-x64-20260603T132803Z")
            self.assertEqual(download.wfile.getvalue(), b"MZ wasm-agent setup")

    def test_native_installer_resolver_prefers_versioned_windows_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_root = root / "plugins" / "wasm-agent"
            release = root / "native" / "windows" / "release"
            release.mkdir(parents=True)
            static_artifact = release / "WASM-Agent-Setup-x64.exe"
            versioned_artifact = release / "WASM-Agent-Setup-x64-0.1.0-20260603T160102Z.exe"
            static_artifact.write_bytes(b"old setup")
            versioned_artifact.write_bytes(b"new setup")
            (release / "WASM-Agent-Setup-x64-0.1.0-20260603T160102Z.native-defaults.json").write_text(
                json.dumps(
                    {
                        "schema": "hermes.wasm_agent.native_defaults.v1",
                        "wasmAgentVersion": "0.1.0",
                        "installableVersion": "0.1.0+win-x64-20260603T160102Z",
                        "buildId": "win-x64-20260603T160102Z",
                    }
                ),
                encoding="utf-8",
            )
            server = SimpleNamespace(plugin_root=plugin_root, public_root=plugin_root / "public", state_dir=root / "state")
            owner = user("101", "owner@example.test")

            resolved = static_server.resolve_native_installer(
                server,
                owner,
                {"platform": "windows", "arch": "x64", "deviceType": "desktop", "browser": "edge"},
            )
            self.assertEqual(resolved["artifactFilename"], versioned_artifact.name)
            self.assertEqual(resolved["filename"], versioned_artifact.name)
            self.assertEqual(resolved["downloadUrl"], "/native/download?platform=windows&arch=x64&buildId=win-x64-20260603T160102Z")

            class DownloadHandler:
                def __init__(self) -> None:
                    self.server = server
                    self.path = "/native/download?platform=windows&arch=x64&buildId=win-x64-20260603T160102Z"
                    self.wfile = io.BytesIO()
                    self.status = None
                    self.headers = {}

                def send_response(self, status) -> None:
                    self.status = status

                def send_header(self, key, value) -> None:
                    self.headers[key] = value

                def end_headers(self) -> None:
                    pass

            download = DownloadHandler()
            static_server.serve_native_installer_download(download, owner)
            self.assertEqual(download.status, static_server.HTTPStatus.OK)
            self.assertEqual(download.headers["Content-Disposition"], f'attachment; filename="{versioned_artifact.name}"')
            self.assertEqual(download.wfile.getvalue(), b"new setup")

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

    def test_remote_control_live_recipients_follow_conversation_members(self) -> None:
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

                server = SimpleNamespace(plugin_root=PLUGIN_ROOT, public_root=PLUGIN_ROOT / "public", state_dir=state_dir)
                alice = user("101", "alice@example.test")
                bob = user("202", "bob@example.test")
                request = static_server.request_friendship(alice, {"email": "bob@example.test"})["friendship"]
                static_server.respond_friendship(bob, {"friendship_id": request["id"], "response": "accepted"})

                remote_event = static_server.append_sync_event(
                    server,
                    alice,
                    {
                        "conversation_id": "dm-101-202",
                        "peer_user_id": "202",
                        "client_event_id": "remote-live-request",
                        "kind": "remote-control-request",
                        "payload": {"request_id": "rc_req_test", "expires_at": int(static_server.time.time() * 1000) + 60_000},
                    },
                )["event"]

                self.assertEqual(remote_event["kind"], "remote-control-request")
                self.assertEqual(
                    static_server.remote_control_live_conversation_user_ids(remote_event["conversation_id"]),
                    ["101", "202"],
                )

    def test_remote_control_live_async_broadcast_does_not_block_sync_append(self) -> None:
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

                server = SimpleNamespace(
                    plugin_root=PLUGIN_ROOT,
                    public_root=PLUGIN_ROOT / "public",
                    state_dir=state_dir,
                    remote_control_live_clients={},
                    remote_control_live_clients_lock=static_server.threading.Lock(),
                )
                alice = user("101", "alice@example.test")
                bob = user("202", "bob@example.test")
                request = static_server.request_friendship(alice, {"email": "bob@example.test"})["friendship"]
                static_server.respond_friendship(bob, {"friendship_id": request["id"], "response": "accepted"})

                class SlowClient:
                    def send_json(self, payload):
                        static_server.time.sleep(0.25)
                        raise TimeoutError("stale live socket")

                server.remote_control_live_clients["202"] = {SlowClient()}
                event = static_server.append_sync_event(
                    server,
                    alice,
                    {
                        "conversation_id": "dm-101-202",
                        "peer_user_id": "202",
                        "client_event_id": "remote-live-nonblocking",
                        "kind": "remote-control-request",
                        "payload": {"request_id": "rc_req_nonblocking", "expires_at": int(static_server.time.time() * 1000) + 60_000},
                    },
                )["event"]

                started = static_server.time.monotonic()
                static_server.remote_control_live_broadcast_async(server, event)
                elapsed = static_server.time.monotonic() - started
                self.assertEqual(event["kind"], "remote-control-request")
                self.assertLess(elapsed, 0.1)
                static_server.time.sleep(0.35)

    def test_rc_live_ephemeral_pixels_skip_sync_rows(self) -> None:
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

                server = SimpleNamespace(
                    plugin_root=PLUGIN_ROOT,
                    public_root=PLUGIN_ROOT / "public",
                    state_dir=state_dir,
                    remote_control_live_clients={},
                    remote_control_live_clients_lock=static_server.threading.Lock(),
                )
                alice = user("101", "alice@example.test")
                bob = user("202", "bob@example.test")
                request = static_server.request_friendship(alice, {"email": "bob@example.test"})["friendship"]
                static_server.respond_friendship(bob, {"friendship_id": request["id"], "response": "accepted"})

                class Client:
                    def __init__(self) -> None:
                        self.messages = []

                    def send_json(self, payload):
                        self.messages.append(payload)

                client = Client()
                server.remote_control_live_clients["202"] = {client}
                event = static_server.remote_control_live_ephemeral_event(
                    server,
                    alice,
                    {
                        "conversation_id": "dm-101-202",
                        "peer_user_id": "202",
                        "client_event_id": "remote-live-frame",
                        "kind": "remote-control-frame",
                        "payload": {
                            "grant_id": "grant",
                            "token": "token",
                            "seq": 1,
                            "image": "data:image/webp;base64,AA==",
                        },
                    },
                )
                static_server.remote_control_live_broadcast(server, event)
                persisted = static_server.list_sync_events(server, bob, {"conversation_id": ["dm-101-202"]})

                self.assertTrue(event["ephemeral"])
                self.assertEqual(event["kind"], "remote-control-frame")
                self.assertEqual(persisted["events"], [])
                self.assertEqual(client.messages[0]["event"]["payload"]["seq"], 1)
                self.assertTrue(client.messages[0]["event"]["ephemeral"])

    def test_remote_control_live_websocket_broadcasts_signed_clients(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            db_path = state_dir / "db" / "wa.sqlite3"
            env_path = Path(tmp) / "wa.env"
            env_path.write_text("USER_EMAILS=alice@example.test,bob@example.test\n", encoding="utf-8")
            env = {
                "HERMES_WASM_AGENT_DB_PATH": str(db_path),
                "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "local",
                "HERMES_WASM_AGENT_AUTH_SECRET": "remote-control-live-test-secret",
                "HERMES_WASM_AGENT_ENV_PATH": str(env_path),
            }
            with patch.dict(os.environ, env, clear=True):
                with static_server.auth_connect() as conn:
                    insert_account(conn, 101, "alice@example.test", "Alice")
                    insert_account(conn, 202, "bob@example.test", "Bob")

                alice = user("101", "alice@example.test")
                bob = user("202", "bob@example.test")
                request = static_server.request_friendship(alice, {"email": "bob@example.test"})["friendship"]
                static_server.respond_friendship(bob, {"friendship_id": request["id"], "response": "accepted"})

                httpd, thread = start_static_test_server(state_dir)
                origin = f"http://127.0.0.1:{httpd.server_address[1]}"
                alice_ws = bob_ws = None
                try:
                    alice_ws = RemoteControlLiveSocket(origin=origin, cookie=f"wa_uid={static_server.signed_auth_value('101')}")
                    bob_ws = RemoteControlLiveSocket(origin=origin, cookie=f"wa_uid={static_server.signed_auth_value('202')}")
                    self.assertEqual(alice_ws.recv_type("ready")["user_id"], "101")
                    self.assertEqual(bob_ws.recv_type("ready")["user_id"], "202")

                    alice_ws.send_json({
                        "type": "append",
                        "request_id": "append-request",
                        "body": {
                            "conversation_id": "dm-101-202",
                            "peer_user_id": "202",
                            "client_event_id": "live-ws-request",
                            "kind": "remote-control-request",
                            "payload": {
                                "request_id": "rc_req_live_ws",
                                "expires_at": int(static_server.time.time() * 1000) + 60_000,
                            },
                        },
                    })
                    alice_ack = alice_ws.recv_type("ack")
                    bob_event = bob_ws.recv_type("event")
                    self.assertTrue(alice_ack["ok"])
                    self.assertEqual(bob_event["event"]["kind"], "remote-control-request")
                    self.assertEqual(bob_event["event"]["payload"]["request_id"], "rc_req_live_ws")

                    bob_ws.send_json({
                        "type": "frame",
                        "request_id": "frame-request",
                        "body": {
                            "conversation_id": "dm-101-202",
                            "peer_user_id": "101",
                            "client_event_id": "live-ws-frame",
                            "kind": "remote-control-frame",
                            "payload": {
                                "grant_id": "grant",
                                "token": "token",
                                "seq": 7,
                                "image": "data:image/webp;base64,AA==",
                            },
                        },
                    })
                    bob_ack = bob_ws.recv_type("ack")
                    alice_frame = alice_ws.recv_type("event")
                    persisted = static_server.list_sync_events(
                        SimpleNamespace(plugin_root=PLUGIN_ROOT, public_root=PLUGIN_ROOT / "public", state_dir=state_dir),
                        alice,
                        {"conversation_id": ["dm-101-202"], "kind": ["remote-control-frame"]},
                    )
                    self.assertTrue(bob_ack["ok"])
                    self.assertTrue(bob_ack["event"]["ephemeral"])
                    self.assertEqual(alice_frame["event"]["kind"], "remote-control-frame")
                    self.assertTrue(alice_frame["event"]["ephemeral"])
                    self.assertEqual(alice_frame["event"]["payload"]["seq"], 7)
                    self.assertEqual(persisted["events"], [])
                finally:
                    if alice_ws:
                        alice_ws.close()
                    if bob_ws:
                        bob_ws.close()
                    httpd.shutdown()
                    thread.join(timeout=2)
                    httpd.server_close()

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
