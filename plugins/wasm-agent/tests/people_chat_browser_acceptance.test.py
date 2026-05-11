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


def http_json(url: str, *, method: str = "GET", body: dict | None = None, cookie: str = "") -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    request = Request(url, data=data, method=method, headers=headers)
    with urlopen(request, timeout=8) as response:  # noqa: S310 - local test endpoint
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
        if "exceptionDetails" in result:
            raise RuntimeError(json.dumps(result["exceptionDetails"], sort_keys=True))
        remote = result.get("result") or {}
        return remote.get("value")


class BrowserPage:
    def __init__(
        self,
        *,
        name: str,
        origin: str,
        chrome_port: int,
        user_id: int,
        auth_secret: str,
        path: str,
    ) -> None:
        self.name = name
        self.origin = origin
        self.chrome_port = chrome_port
        self.user_id = user_id
        self.auth_secret = auth_secret
        target = http_json(f"http://127.0.0.1:{chrome_port}/json/new?about:blank", method="PUT")
        self.target_id = str(target["id"])
        self.page = CdpSocket(target["webSocketDebuggerUrl"])
        self.page.call("Page.enable")
        self.page.call("Runtime.enable")
        self.page.call("Network.enable")
        self.page.call("Network.setCookie", {
            "name": "wa_uid",
            "value": self.auth_cookie_value(),
            "url": origin,
            "path": "/",
            "httpOnly": True,
            "sameSite": "Lax",
        })
        self.page.call("Page.navigate", {"url": f"{origin}{path}"})
        self.wait("document.readyState === 'complete'", timeout=15)
        self.wait("document.querySelector('#app')?.dataset.auth === 'ready'", timeout=30)
        self.wait("document.querySelector('#agentAvatarButton') && document.querySelector('#agentPeopleButton')", timeout=15)

    def close(self) -> None:
        self.page.close()

    def auth_cookie_value(self) -> str:
        issued = int(time.time())
        message = f"{self.user_id}.{issued}"
        signature = hmac.new(self.auth_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{message}.{signature}"

    def evaluate(self, expression: str) -> object:
        return self.page.evaluate(expression)

    def wait(self, expression: str, *, timeout: float = 12, interval: float = 0.2) -> object:
        deadline = time.time() + timeout
        last_error = None
        last_value = None
        while time.time() < deadline:
            try:
                last_value = self.evaluate(f"Boolean({expression})")
                if last_value:
                    return last_value
            except Exception as exc:  # noqa: BLE001 - CDP can race page reloads
                last_error = exc
            time.sleep(interval)
        details = self.debug_snapshot()
        raise AssertionError(
            f"{self.name}: condition did not become true: {expression}; "
            f"last={last_value!r}; error={last_error!r}; snapshot={details}"
        )

    def debug_snapshot(self) -> dict:
        try:
            value = self.evaluate(
                """(() => ({
                  auth: document.querySelector('#app')?.dataset.auth || '',
                  panel: document.querySelector('#app')?.dataset.panel || '',
                  activeSpace: document.querySelector('#app')?.dataset.activeSpace || '',
                  agentOpen: document.querySelector('#agentOverlay')?.dataset.open || '',
                  title: document.querySelector('#agentPanelTitle')?.textContent || '',
                  people: document.querySelector('#agentPeopleList')?.textContent || '',
                  messages: document.querySelector('#agentMessages')?.textContent || '',
                  peopleButton: document.querySelector('#agentPeopleButton')?.className || '',
                  toasts: document.querySelector('#agentToastStack')?.textContent || ''
                }))()"""
            )
            return value if isinstance(value, dict) else {}
        except Exception as exc:  # noqa: BLE001 - diagnostic only
            return {"error": str(exc)}

    def reload(self) -> None:
        self.page.call("Page.reload", {"ignoreCache": True})
        self.wait("document.readyState === 'complete'", timeout=15)
        self.wait("document.querySelector('#app')?.dataset.auth === 'ready'", timeout=30)
        self.wait("document.querySelector('#agentAvatarButton') && document.querySelector('#agentPeopleButton')", timeout=15)


class PeopleChatBrowserAcceptanceTest(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        if not CHROMIUM:
            self.skipTest("Chromium is not installed")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cloud_root = self.root / "private-cloud"
        self.cloud_root.mkdir(parents=True)
        (self.cloud_root / "conf").mkdir(parents=True)
        self.auth_secret = "people-chat-browser-acceptance-secret"
        self.server_port = free_port()
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.alice = {"id": 101, "email": "alice@example.test", "name": "Alice"}
        self.bob = {"id": 202, "email": "bob@example.test", "name": "Bob"}
        self.shared_space_id = "acceptance-shared"
        self.alice_space_id = "acceptance-alice"
        self.bob_space_id = "acceptance-bob"
        (self.cloud_root / "conf" / "wa.env").write_text(
            "ADMIN_EMAIL=alice@example.test\nUSER_EMAILS=alice@example.test,bob@example.test\n",
            encoding="utf-8",
        )
        self.db_path = self.cloud_root / "state" / "db" / "sqlite" / "wa_db.sqlite3"
        self._create_users()
        env = os.environ.copy()
        env.update({
            "HERMES_WASM_AGENT_DEPLOYMENT_MODE": "cloud",
            "HERMES_WASM_AGENT_CLOUD_STATE_ROOT": str(self.cloud_root),
            "HERMES_WASM_AGENT_AUTH_SECRET": self.auth_secret,
            "HERMES_WASM_AGENT_ACCESS_LOG": "0",
        })
        self.server = subprocess.Popen(
            ["python3", str(SERVER_PATH), "--host", "127.0.0.1", "--port", str(self.server_port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        self._wait_http(f"{self.origin}/boot.js")
        self._seed_shared_space()
        self.chrome_processes: list[subprocess.Popen] = []
        self.pages: list[BrowserPage] = []

    def tearDown(self) -> None:
        for page in getattr(self, "pages", []):
            page.close()
        for proc in getattr(self, "chrome_processes", []):
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        proc = getattr(self, "server", None)
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            if proc.stdout:
                proc.stdout.close()
        self.tmp.cleanup()

    def _create_users(self) -> None:
        now = int(time.time())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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
            for user in (self.alice, self.bob):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO user_tb (
                      id, provider, provider_sub, email, email_verified, name,
                      picture_url, created_at, updated_at, last_login_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user["id"],
                        "test",
                        f"browser-acceptance-{user['id']}",
                        user["email"],
                        1,
                        user["name"],
                        "",
                        now,
                        now,
                        now,
                    ),
                )

    def _auth_cookie_value(self, user_id: int) -> str:
        issued = int(time.time())
        message = f"{user_id}.{issued}"
        signature = hmac.new(self.auth_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{message}.{signature}"

    def _cookie_header(self, user_id: int) -> str:
        return f"wa_uid={self._auth_cookie_value(user_id)}"

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

    def _api(self, user_id: int, path: str, body: dict | None = None, method: str | None = None) -> dict:
        return http_json(
            f"{self.origin}{path}",
            method=method or ("POST" if body is not None else "GET"),
            body=body,
            cookie=self._cookie_header(user_id),
        )

    def _seed_shared_space(self) -> None:
        area = {"width_px": 2000, "height_px": 1500}
        self._api(self.alice["id"], "/spaces", {
            "action": "replace",
            "spaces": [{"id": self.alice_space_id, "title": "Acceptance Shared", "space_area": area}],
        })
        shared = self._api(self.alice["id"], "/spaces/share", {
            "space_id": self.alice_space_id,
            "shared_space_id": self.shared_space_id,
            "title": "Acceptance Shared",
            "space_area": area,
        })
        self.assertTrue(shared.get("ok"))
        joined = self._api(self.bob["id"], "/spaces/join", {
            "join_code": self.shared_space_id,
            "local_space_id": self.bob_space_id,
        })
        self.assertTrue(joined.get("ok"))

    def _start_chrome(self, name: str) -> int:
        port = free_port()
        user_dir = self.root / f"chrome-{name}"
        proc = subprocess.Popen(
            [
                CHROMIUM or "chromium",
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--remote-debugging-address=127.0.0.1",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={user_dir}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.chrome_processes.append(proc)
        self._wait_http(f"http://127.0.0.1:{port}/json/version")
        return port

    def _new_browser_page(self, name: str, user: dict, path: str) -> BrowserPage:
        page = BrowserPage(
            name=name,
            origin=self.origin,
            chrome_port=self._start_chrome(name),
            user_id=int(user["id"]),
            auth_secret=self.auth_secret,
            path=path,
        )
        self.pages.append(page)
        return page

    def _open_people(self, page: BrowserPage) -> None:
        page.evaluate(
            """(() => {
              const overlay = document.querySelector('#agentOverlay');
              if (overlay?.dataset.open !== 'true') document.querySelector('#agentAvatarButton')?.click();
              if (document.querySelector('#agentPanelTitle')?.textContent !== 'People') {
                document.querySelector('#agentPeopleButton')?.click();
              }
            })()"""
        )
        page.wait("document.querySelector('#agentPanelTitle')?.textContent === 'People'", timeout=8)

    def _open_agent(self, page: BrowserPage) -> None:
        page.evaluate(
            """(() => {
              if (document.querySelector('#agentOverlay')?.dataset.open !== 'true') {
                document.querySelector('#agentAvatarButton')?.click();
              }
            })()"""
        )
        page.wait("document.querySelector('#agentOverlay')?.dataset.open === 'true'", timeout=8)

    def _submit_friend_search(self, page: BrowserPage, query: str) -> None:
        self._open_people(page)
        page.evaluate(
            f"""(() => {{
              const input = document.querySelector('#agentPeopleSearchInput');
              input.value = {json.dumps(query)};
              input.dispatchEvent(new Event('input', {{ bubbles: true }}));
              document.querySelector('#agentPeopleSearchForm')
                .dispatchEvent(new Event('submit', {{ bubbles: true, cancelable: true }}));
            }})()"""
        )

    def _click_people_action(self, page: BrowserPage, title_prefix: str) -> None:
        self._open_people(page)
        clicked = page.evaluate(
            f"""(() => {{
              const button = Array.from(document.querySelectorAll('#agentPeopleList button'))
                .find((item) => (item.title || '').startsWith({json.dumps(title_prefix)}));
              if (!button) return false;
              button.click();
              return true;
            }})()"""
        )
        self.assertTrue(clicked, f"{page.name}: missing People action {title_prefix!r}; {page.debug_snapshot()}")

    def _open_friend_chat(self, page: BrowserPage, name: str) -> None:
        self._open_people(page)
        page.wait(
            f"Array.from(document.querySelectorAll('.agent-person-row.friend')).some((item) => item.textContent.includes({json.dumps(name)}))",
            timeout=12,
        )
        clicked = page.evaluate(
            f"""(() => {{
              const row = Array.from(document.querySelectorAll('.agent-person-row.friend'))
                .find((item) => item.textContent.includes({json.dumps(name)}));
              if (!row) return false;
              row.click();
              return true;
            }})()"""
        )
        self.assertTrue(clicked, f"{page.name}: missing friend row for {name}; {page.debug_snapshot()}")
        page.wait(f"document.querySelector('#agentPanelTitle')?.textContent.includes({json.dumps(name)})", timeout=8)

    def _open_shared_chat(self, page: BrowserPage) -> None:
        self._open_people(page)
        page.wait("document.querySelector('.agent-person-row.shared-chat')", timeout=12)
        clicked = page.evaluate(
            """(() => {
              const row = document.querySelector('.agent-person-row.shared-chat');
              if (!row) return false;
              row.click();
              return true;
            })()"""
        )
        self.assertTrue(clicked, f"{page.name}: missing shared chat row; {page.debug_snapshot()}")
        page.wait("document.querySelector('#agentPanelTitle')?.textContent.includes('Acceptance Shared')", timeout=10)

    def _send_agent_text(self, page: BrowserPage, text: str) -> None:
        page.evaluate(
            f"""(() => {{
              const input = document.querySelector('#agentInput');
              input.value = {json.dumps(text)};
              input.dispatchEvent(new Event('input', {{ bubbles: true }}));
              document.querySelector('#agentForm')
                .dispatchEvent(new Event('submit', {{ bubbles: true, cancelable: true }}));
            }})()"""
        )

    def _people_has_no_pending(self, page: BrowserPage) -> str:
        self._open_people(page)
        value = page.evaluate("document.querySelector('#agentPeopleList')?.textContent || ''")
        return str(value or "")

    def _check_client_state_snapshot_restore(self, page: BrowserPage) -> None:
        result = page.evaluate(
            """(async () => {
              const { createClientFirstStore } = await import('/modules/client-state/client-store.js');
              const store = createClientFirstStore();
              const snapshot = {
                schema: 'hermes.wasm_agent.client_first_snapshot.v1',
                dbName: 'wasmAgent.clientFirst.v1',
                created_at: new Date().toISOString(),
                stores: {
                  conversations: [],
                  messages: [],
                  people: [{ id: 'encrypted-acceptance', friendships: [], syncCursor: '42' }],
                  brains: [],
                  syncCursors: [],
                  artifacts: []
                }
              };
              const encrypted = await store.encryptSnapshot('acceptance passphrase', snapshot);
              let wrongFailed = false;
              try {
                await store.decryptSnapshot('wrong passphrase', encrypted);
              } catch {
                wrongFailed = true;
              }
              await store.importEncrypted('acceptance passphrase', encrypted, { clear: false });
              const restored = await store.get('people', 'encrypted-acceptance');
              return {
                schema: encrypted.schema,
                cipher: encrypted.cipher,
                kdf: encrypted.kdf?.name,
                wrongFailed,
                syncCursor: restored?.syncCursor || ''
              };
            })()"""
        )
        self.assertEqual(result.get("schema"), "hermes.wasm_agent.client_first_snapshot.encrypted.v1")
        self.assertEqual(result.get("cipher"), "AES-256-GCM")
        self.assertEqual(result.get("kdf"), "PBKDF2")
        self.assertTrue(result.get("wrongFailed"))
        self.assertEqual(result.get("syncCursor"), "42")

    def test_people_dm_shared_chat_private_cloud_acceptance(self) -> None:
        alice = self._new_browser_page("alice", self.alice, f"/spaces/{self.alice_space_id}")
        bob = self._new_browser_page("bob", self.bob, f"/spaces/{self.bob_space_id}")
        alice.wait(f"document.querySelector('#app')?.dataset.activeSpace === {json.dumps(self.alice_space_id)}", timeout=15)
        bob.wait(f"document.querySelector('#app')?.dataset.activeSpace === {json.dumps(self.bob_space_id)}", timeout=15)
        self._check_client_state_snapshot_restore(alice)

        self._submit_friend_search(alice, self.bob["email"])
        alice.wait("document.querySelector('#agentPeopleList')?.textContent.includes('request sent')", timeout=8)
        self._open_people(bob)
        bob.wait("document.querySelector('#agentPeopleList')?.textContent.includes('wants to connect')", timeout=10)
        bob.wait("document.querySelector('#agentPeopleButton')?.classList.contains('has-social-alerts')", timeout=5)

        self._click_people_action(alice, "Cancel request")
        alice.wait("!(document.querySelector('#agentPeopleList')?.textContent || '').includes('request sent')", timeout=10)
        bob.wait("!(document.querySelector('#agentPeopleList')?.textContent || '').includes('wants to connect')", timeout=10)

        self._submit_friend_search(alice, self.bob["email"])
        bob.wait("document.querySelector('#agentPeopleList')?.textContent.includes('wants to connect')", timeout=10)
        self._click_people_action(bob, "Decline")
        alice.wait("!(document.querySelector('#agentPeopleList')?.textContent || '').includes('request sent')", timeout=10)
        bob.wait("!(document.querySelector('#agentPeopleList')?.textContent || '').includes('wants to connect')", timeout=10)

        self._submit_friend_search(alice, self.bob["email"])
        bob.wait("document.querySelector('#agentPeopleList')?.textContent.includes('wants to connect')", timeout=10)
        self._click_people_action(bob, "Accept")
        alice.wait("Array.from(document.querySelectorAll('.agent-person-row.friend')).some((row) => row.textContent.includes('Bob'))", timeout=12)
        bob.wait("Array.from(document.querySelectorAll('.agent-person-row.friend')).some((row) => row.textContent.includes('Alice'))", timeout=12)

        self._open_friend_chat(alice, "Bob")
        self._send_agent_text(alice, "hello 👋")
        alice.wait("document.querySelector('#agentMessages')?.textContent.includes('hello 👋')", timeout=8)
        bob.wait("document.querySelector('#agentPeopleButton')?.classList.contains('has-social-alerts')", timeout=10)
        bob.wait("document.querySelector('.agent-toast.message')?.textContent.includes('hello')", timeout=8)
        self._open_people(bob)
        bob.wait("Array.from(document.querySelectorAll('.agent-person-row.friend.has-unread')).some((row) => row.textContent.includes('Alice'))", timeout=8)
        self._open_friend_chat(bob, "Alice")
        bob.wait("document.querySelector('#agentMessages')?.textContent.includes('hello 👋')", timeout=8)

        self._send_agent_text(bob, "reply 😄")
        bob.wait("document.querySelector('#agentMessages')?.textContent.includes('reply 😄')", timeout=8)
        bob.wait("!document.querySelector('#agentSendButton')?.classList.contains('is-busy')", timeout=8)
        bob.evaluate("document.querySelector('#agentStickerButton')?.click()")
        bob.wait("!document.querySelector('#agentStickerPicker')?.hidden", timeout=5)
        bob.evaluate(
            """(() => {
              const button = Array.from(document.querySelectorAll('.agent-sticker-option'))
                .find((item) => item.textContent.includes('ship it'));
              button?.click();
            })()"""
        )
        bob.wait("document.querySelector('#agentMessages')?.textContent.includes('ship it')", timeout=8)
        alice.wait("document.querySelector('#agentMessages')?.textContent.includes('reply 😄')", timeout=12)
        alice.wait("document.querySelector('#agentMessages')?.textContent.includes('ship it')", timeout=12)

        alice.evaluate(
            """(() => {
              const message = Array.from(document.querySelectorAll('.agent-message.assistant.direct-message'))
                .find((item) => item.textContent.includes('reply'));
              const button = message?.querySelector('.agent-reaction-quick button:not([disabled])');
              button?.click();
              return Boolean(button);
            })()"""
        )
        bob.wait("document.querySelector('.agent-reaction-chip')?.textContent.includes('1')", timeout=12)

        alice.reload()
        self._open_friend_chat(alice, "Bob")
        alice.wait("document.querySelector('#agentMessages')?.textContent.includes('reply 😄')", timeout=12)

        alice.evaluate("document.querySelector('#agentPeopleButton')?.click()")
        alice.wait("document.querySelector('#agentPanelTitle')?.textContent === 'People'", timeout=8)
        alice.evaluate("document.querySelector('#agentPeopleButton')?.click()")
        alice.wait("document.querySelector('#agentPanelTitle')?.textContent === 'Chat'", timeout=8)

        self._open_shared_chat(alice)
        self._send_agent_text(alice, "shared hello")
        alice.wait("document.querySelector('#agentMessages')?.textContent.includes('shared hello')", timeout=8)
        bob.wait("document.querySelector('#agentPeopleButton')?.classList.contains('has-social-alerts')", timeout=12)
        self._open_people(bob)
        bob.wait("document.querySelector('.agent-person-row.shared-chat.has-unread')", timeout=8)
        self._open_shared_chat(bob)
        bob.wait("document.querySelector('#agentMessages')?.textContent.includes('shared hello')", timeout=8)
        self._send_agent_text(bob, "shared reply")
        alice.wait("document.querySelector('#agentMessages')?.textContent.includes('shared reply')", timeout=12)

        self._click_people_action(alice, "Remove")
        alice.wait("!Array.from(document.querySelectorAll('.agent-person-row.friend')).some((row) => row.textContent.includes('Bob'))", timeout=12)
        self._open_people(bob)
        bob.wait("!Array.from(document.querySelectorAll('.agent-person-row.friend')).some((row) => row.textContent.includes('Alice'))", timeout=12)
        self.assertNotIn("request sent", self._people_has_no_pending(alice))
        self.assertNotIn("wants to connect", self._people_has_no_pending(bob))


if __name__ == "__main__":
    unittest.main()
