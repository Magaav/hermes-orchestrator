#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import socket
import sqlite3
import struct
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PLUGIN_ROOT / "server" / "static_server.py"
CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_json(url: str, *, method: str = "GET") -> dict:
    request = Request(url, method=method)
    with urlopen(request, timeout=5) as response:  # noqa: S310 - local test endpoint
        return json.loads(response.read().decode("utf-8"))


class CdpSocket:
    def __init__(self, ws_url: str) -> None:
        parsed = urlparse(ws_url)
        self.sock = socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or 80), timeout=5)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{parsed.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"CDP websocket handshake failed: {response[:200]!r}")
        self.next_id = 0

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def send_json(self, payload: dict) -> None:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        header = bytearray([0x81])
        length = len(raw)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = secrets.token_bytes(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(raw))
        self.sock.sendall(bytes(header) + mask + masked)

    def recv_json(self) -> dict:
        while True:
            first = self.sock.recv(2)
            if len(first) < 2:
                raise RuntimeError("CDP websocket closed")
            opcode = first[0] & 0x0F
            length = first[1] & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            masked = bool(first[1] & 0x80)
            mask = self._recv_exact(4) if masked else b""
            data = self._recv_exact(length)
            if masked:
                data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
            if opcode == 0x8:
                raise RuntimeError("CDP websocket closed")
            if opcode == 0x9:
                continue
            if opcode != 0x1:
                continue
            return json.loads(data.decode("utf-8"))

    def _recv_exact(self, length: int) -> bytes:
        chunks = []
        remaining = length
        while remaining:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise RuntimeError("CDP websocket closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def call(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        message_id = self.next_id
        self.send_json({"id": message_id, "method": method, "params": params or {}})
        while True:
            message = self.recv_json()
            if message.get("id") == message_id:
                if "error" in message:
                    raise RuntimeError(f"CDP {method} failed: {message['error']}")
                return message.get("result") or {}

    def evaluate(self, expression: str) -> object:
        result = self.call("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
        })
        remote = result.get("result") or {}
        if "exceptionDetails" in result:
            raise RuntimeError(json.dumps(result["exceptionDetails"]))
        return remote.get("value")


class VoiceLabBrowserSmokeTest(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        if not CHROMIUM:
            self.skipTest("Chromium is not installed")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state_dir = self.root / "state"
        self.db_path = self.root / "wa.sqlite3"
        self.env_path = self.root / "wa.env"
        self.auth_secret = "voice-lab-browser-test-secret"
        self.user_id = 101
        self.user_email = "voice-browser@example.test"
        self.server_port = free_port()
        self.chrome_port = free_port()
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.room_id = f"browser-smoke-{int(time.time())}"
        self.env_path.write_text(f"USER_EMAILS={self.user_email}\n", encoding="utf-8")
        self._create_user()
        env = os.environ.copy()
        env.update({
            "HERMES_WASM_AGENT_STATE_DIR": str(self.state_dir),
            "HERMES_WASM_AGENT_DB_PATH": str(self.db_path),
            "HERMES_WASM_AGENT_AUTH_SECRET": self.auth_secret,
            "HERMES_WASM_AGENT_ENV_PATH": str(self.env_path),
        })
        self.server = subprocess.Popen(
            ["python3", str(SERVER_PATH), "--host", "127.0.0.1", "--port", str(self.server_port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        self._wait_http(f"{self.origin}/voice-lab")
        self.chrome_dir = self.root / "chrome"
        self.chrome = subprocess.Popen(
            [
                CHROMIUM or "chromium",
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--autoplay-policy=no-user-gesture-required",
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
                "--remote-debugging-address=127.0.0.1",
                f"--remote-debugging-port={self.chrome_port}",
                f"--user-data-dir={self.chrome_dir}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._wait_http(f"http://127.0.0.1:{self.chrome_port}/json/version")
        self.pages: list[tuple[str, CdpSocket]] = []

    def tearDown(self) -> None:
        for _, page in getattr(self, "pages", []):
            page.close()
        for proc_name in ("chrome", "server"):
            proc = getattr(self, proc_name, None)
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self.tmp.cleanup()

    def _create_user(self) -> None:
        now = int(time.time())
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_tb (
                  id INTEGER PRIMARY KEY,
                  provider TEXT NOT NULL,
                  provider_sub TEXT NOT NULL,
                  email TEXT NOT NULL DEFAULT '',
                  email_verified INTEGER NOT NULL DEFAULT 0,
                  name TEXT NOT NULL DEFAULT '',
                  picture_url TEXT NOT NULL DEFAULT '',
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL,
                  last_login_at INTEGER NOT NULL,
                  UNIQUE(provider, provider_sub)
                )
                """
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO user_tb (
                  id, provider, provider_sub, email, email_verified, name,
                  picture_url, created_at, updated_at, last_login_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (self.user_id, "test", "voice-browser", self.user_email, 1, "Voice Browser", "", now, now, now),
            )

    def _auth_cookie_value(self) -> str:
        issued = int(time.time())
        message = f"{self.user_id}.{issued}"
        signature = hmac.new(self.auth_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{message}.{signature}"

    def _wait_http(self, url: str, timeout: float = 10) -> None:
        deadline = time.time() + timeout
        last_error = None
        while time.time() < deadline:
            try:
                with urlopen(url, timeout=2):  # noqa: S310 - local test endpoint
                    return
            except Exception as exc:  # noqa: BLE001 - retry startup races
                last_error = exc
                time.sleep(0.1)
        raise RuntimeError(f"timed out waiting for {url}: {last_error}")

    def _new_page(self, name: str) -> CdpSocket:
        target = http_json(f"http://127.0.0.1:{self.chrome_port}/json/new?about:blank", method="PUT")
        page = CdpSocket(target["webSocketDebuggerUrl"])
        page.call("Page.enable")
        page.call("Runtime.enable")
        page.call("Network.enable")
        page.call("Network.setCookie", {
            "name": "wa_uid",
            "value": self._auth_cookie_value(),
            "url": self.origin,
            "path": "/",
            "httpOnly": True,
            "sameSite": "Lax",
        })
        self.pages.append((target["id"], page))
        page.call("Page.navigate", {"url": f"{self.origin}/voice-lab?room={self.room_id}"})
        self._wait_eval(page, "document.readyState === 'complete'")
        self._wait_eval(page, "document.querySelector('#joinButton') && !document.querySelector('#joinButton').disabled")
        return page

    def _wait_eval(self, page: CdpSocket, expression: str, timeout: float = 12) -> object:
        deadline = time.time() + timeout
        last_value = None
        while time.time() < deadline:
            try:
                last_value = page.evaluate(f"Boolean({expression})")
                if last_value:
                    return last_value
            except Exception:
                pass
            time.sleep(0.2)
        raise AssertionError(f"condition did not become true: {expression}; last={last_value!r}")

    def _snapshot(self, page: CdpSocket) -> dict:
        value = page.evaluate("JSON.parse(document.querySelector('#statePanel').textContent || '{}')")
        assert isinstance(value, dict)
        return value

    def _logs(self, page: CdpSocket) -> list[str]:
        value = page.evaluate("Array.from(document.querySelectorAll('#eventLog li strong')).map((item) => item.textContent)")
        assert isinstance(value, list)
        return [str(item) for item in value]

    def _post_room_signal(self, *, device_id: str, client_id: str, payload: dict) -> None:
        body = json.dumps({
            "action": "signal",
            "kind": "voice-signal",
            "room_id": self.room_id,
            "payload": payload,
        }).encode("utf-8")
        request = Request(
            f"{self.origin}/voice-lab/room",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Cookie": f"wa_uid={self._auth_cookie_value()}",
                "X-Wasm-Agent-Device-Id": "browser-profile",
                "X-Wasm-Agent-Voice-Lab-Client-Id": client_id,
                "X-Wasm-Agent-Voice-Lab-Device-Id": device_id,
            },
        )
        with urlopen(request, timeout=5):  # noqa: S310 - local test endpoint
            pass

    def _click(self, page: CdpSocket, selector: str) -> None:
        page.evaluate(f"document.querySelector({json.dumps(selector)}).click()")

    def _wait_state(self, page: CdpSocket, expression: str, timeout: float = 15) -> dict:
        self._wait_eval(page, f"(() => {{ const s = JSON.parse(document.querySelector('#statePanel').textContent || '{{}}'); return {expression}; }})()", timeout=timeout)
        return self._snapshot(page)

    def _join_and_wait(self, page: CdpSocket, peer_count: int) -> dict:
        self._click(page, "#joinButton")
        return self._wait_state(page, f"s.status === 'joined' && s.hasLocalStream === true && s.peerCount === {peer_count}", timeout=25)

    def _wait_remote_audio_count(self, page: CdpSocket, count: int, timeout: float = 30) -> None:
        try:
            self._wait_eval(page, f"document.querySelectorAll('#remoteAudioList audio').length >= {count}", timeout=timeout)
        except AssertionError as exc:
            raise AssertionError(
                f"{exc}; state={json.dumps(self._snapshot(page), sort_keys=True)}; logs={self._logs(page)[:12]!r}"
            ) from exc

    def test_01_two_tab_voice_lifecycle_with_fake_media(self) -> None:
        page_a = self._new_page("a")
        page_b = self._new_page("b")
        id_a = self._snapshot(page_a)["localDeviceId"]
        id_b = self._snapshot(page_b)["localDeviceId"]
        self.assertNotEqual(id_a, id_b)
        self.assertEqual(self._snapshot(page_a)["status"], "idle")
        self.assertEqual(self._snapshot(page_b)["status"], "idle")
        self.assertNotIn("getUserMedia accepted", " ".join(self._logs(page_a) + self._logs(page_b)))

        self._click(page_a, "#joinButton")
        self._wait_state(page_a, "s.status === 'joined' && s.hasLocalStream === true")
        self.assertEqual(self._snapshot(page_b)["status"], "idle")
        self.assertFalse(self._snapshot(page_b)["hasLocalStream"])
        self.assertNotIn("getUserMedia accepted", " ".join(self._logs(page_b)))

        self._click(page_b, "#joinButton")
        self._wait_state(page_a, "s.status === 'joined' && s.peerCount === 1")
        self._wait_state(page_b, "s.status === 'joined' && s.peerCount === 1")
        self._wait_remote_audio_count(page_a, 1, timeout=30)
        self._wait_remote_audio_count(page_b, 1, timeout=30)
        old_a_epoch = self._snapshot(page_a)["joinEpoch"]
        b_snapshot = self._snapshot(page_b)

        self._click(page_a, "#leaveButton")
        self._wait_state(page_a, "s.status === 'idle' && s.hasLocalStream === false")
        self._wait_state(page_b, "s.status === 'joined' && s.hasLocalStream === true && s.peerCount === 0")
        self._post_room_signal(
            device_id=id_b,
            client_id=b_snapshot["localClientId"],
            payload={
                "voice_schema": "hermes.wasm_agent.shared_space.voice_signal.v1",
                "type": "offer",
                "room_id": self.room_id,
                "call_id": "retained-old-offer",
                "to_device_id": id_a,
                "join_epoch": b_snapshot["joinEpoch"],
                "target_join_epoch": old_a_epoch,
                "sdp": "v=0\r\n",
            },
        )

        self._click(page_a, "#joinButton")
        self._wait_state(page_a, "s.status === 'joined' && s.peerCount === 1")
        self._wait_state(page_b, "s.status === 'joined' && s.peerCount === 1")
        self._wait_eval(
            page_a,
            "Array.from(document.querySelectorAll('#eventLog li strong')).some((item) => item.textContent.includes('event-ignored-epoch-mismatch ignored') || item.textContent.includes('stale-event-ignored ignored'))",
            timeout=10,
        )

        self._click(page_b, "#leaveButton")
        self._wait_state(page_b, "s.status === 'idle' && s.hasLocalStream === false")
        self._wait_state(page_a, "s.status === 'joined' && s.hasLocalStream === true && s.peerCount === 0")

        self._click(page_b, "#joinButton")
        self._wait_state(page_a, "s.status === 'joined' && s.peerCount === 1")
        self._wait_state(page_b, "s.status === 'joined' && s.peerCount === 1")

        page_a.call("Page.reload", {"ignoreCache": True})
        self._wait_eval(page_a, "document.readyState === 'complete'")
        self._wait_eval(page_a, "document.querySelector('#joinButton') && !document.querySelector('#joinButton').disabled")
        self._wait_state(page_a, "s.status === 'idle' && s.hasLocalStream === false")
        self._wait_state(page_b, "s.status === 'joined' && s.hasLocalStream === true")

        self._click(page_a, "#joinButton")
        self._wait_state(page_a, "s.status === 'joined' && s.peerCount === 1")
        self._wait_state(page_b, "s.status === 'joined' && s.peerCount === 1")

        page_b.call("Page.reload", {"ignoreCache": True})
        self._wait_eval(page_b, "document.readyState === 'complete'")
        self._wait_eval(page_b, "document.querySelector('#joinButton') && !document.querySelector('#joinButton').disabled")
        self._wait_state(page_b, "s.status === 'idle' && s.hasLocalStream === false")
        self._wait_state(page_a, "s.status === 'joined' && s.hasLocalStream === true")

        target_id, page_b_socket = self.pages[-1]
        with urlopen(Request(f"http://127.0.0.1:{self.chrome_port}/json/close/{target_id}", method="PUT"), timeout=5):  # noqa: S310 - local test endpoint
            pass
        page_b_socket.close()
        self._wait_state(page_a, "s.status === 'joined' && s.hasLocalStream === true", timeout=5)

    def test_02_three_tab_mesh_voice_lifecycle_with_fake_media(self) -> None:
        page_a = self._new_page("a")
        page_b = self._new_page("b")
        page_c = self._new_page("c")
        ids = {
            self._snapshot(page_a)["localDeviceId"],
            self._snapshot(page_b)["localDeviceId"],
            self._snapshot(page_c)["localDeviceId"],
        }
        self.assertEqual(len(ids), 3)
        self.assertNotIn("getUserMedia accepted", " ".join(self._logs(page_a) + self._logs(page_b) + self._logs(page_c)))

        self._join_and_wait(page_a, 0)
        self.assertEqual(self._snapshot(page_b)["status"], "idle")
        self.assertEqual(self._snapshot(page_c)["status"], "idle")

        self._join_and_wait(page_b, 1)
        self._wait_state(page_a, "s.status === 'joined' && s.peerCount === 1", timeout=25)
        self.assertEqual(self._snapshot(page_c)["status"], "idle")

        self._join_and_wait(page_c, 2)
        for page in (page_a, page_b, page_c):
            self._wait_state(page, "s.status === 'joined' && s.peerCount === 2", timeout=30)
            self._wait_remote_audio_count(page, 2, timeout=60)

        self._click(page_b, "#leaveButton")
        self._wait_state(page_b, "s.status === 'idle' && s.hasLocalStream === false", timeout=20)
        self._wait_state(page_a, "s.status === 'joined' && s.hasLocalStream === true && s.peerCount === 1", timeout=25)
        self._wait_state(page_c, "s.status === 'joined' && s.hasLocalStream === true && s.peerCount === 1", timeout=25)

        self._join_and_wait(page_b, 2)
        for page in (page_a, page_b, page_c):
            self._wait_state(page, "s.status === 'joined' && s.peerCount === 2", timeout=30)

        page_c.call("Page.reload", {"ignoreCache": True})
        self._wait_eval(page_c, "document.readyState === 'complete'")
        self._wait_eval(page_c, "document.querySelector('#joinButton') && !document.querySelector('#joinButton').disabled")
        self._wait_state(page_c, "s.status === 'idle' && s.hasLocalStream === false", timeout=15)
        self._wait_state(page_a, "s.status === 'joined' && s.hasLocalStream === true", timeout=10)
        self._wait_state(page_b, "s.status === 'joined' && s.hasLocalStream === true", timeout=10)

        self._join_and_wait(page_c, 2)
        for page in (page_a, page_b, page_c):
            self._wait_state(page, "s.status === 'joined' && s.peerCount === 2", timeout=30)


if __name__ == "__main__":
    unittest.main()
