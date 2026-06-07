from __future__ import annotations

import sys
import http.client
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = PLUGIN_ROOT / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import static_server


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


class AuthCookiePersistenceTest(unittest.TestCase):
    def test_auth_cookie_is_durable_and_secure_on_https_origin(self) -> None:
        original_public_origin = static_server.public_origin
        try:
            static_server.public_origin = lambda: "https://wa.colmeio.com"
            cookie = static_server.auth_cookie("123")
        finally:
            static_server.public_origin = original_public_origin

        self.assertIn("wa_uid=", cookie)
        self.assertIn(f"Max-Age={60 * 60 * 24 * 30}", cookie)
        self.assertIn("Path=/", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)

    def test_google_auth_routes_set_durable_auth_cookie(self) -> None:
        source = Path(static_server.__file__).read_text(encoding="utf-8")
        self.assertIn('if path == "/auth/google":', source)
        self.assertIn('if path == "/auth/google/callback":', source)
        self.assertIn('headers={"Set-Cookie": auth_cookie(payload["user"]["id"], handler=self)}', source)
        self.assertIn("AUTH_COOKIE_MAX_AGE_SEC = 60 * 60 * 24 * 30", source)
        self.assertIn("Max-Age={max_age}", source)

    def test_android_google_callback_redirects_to_native_return_not_home(self) -> None:
        session_id = "fixture-session-android-return-0001"
        user_payload = {
            "ok": True,
            "authenticated": True,
            "user": {
                "id": "123",
                "email": "android@example.test",
                "role": "user",
                "name": "Android",
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            httpd, thread = start_static_test_server(Path(tmp) / "state")
            host, port = httpd.server_address
            try:
                with patch.object(static_server, "google_auth_login", return_value=user_payload), patch.object(static_server, "create_auth_redirect_code", return_value="fixed-auth-code"):
                    body = f"id_token=fake-token&state={session_id}"
                    conn = http.client.HTTPConnection(host, port, timeout=5)
                    conn.request(
                        "POST",
                        "/auth/google/callback",
                        body=body,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    response = conn.getresponse()
                    response.read()
                    self.assertEqual(response.status, 303)
                    location = response.getheader("Location", "")
                    self.assertTrue(
                        location.startswith("/native/android/auth/return?"),
                        f"Android callback must return to native handoff, got {location!r}",
                    )
                    self.assertNotIn("/home", location)

                    conn = http.client.HTTPConnection(host, port, timeout=5)
                    conn.request("GET", location)
                    return_response = conn.getresponse()
                    return_response.read()
                    self.assertEqual(return_response.status, 303)
                    return_location = return_response.getheader("Location", "")
                    self.assertIn("intent://android-auth-return", return_location)
                    self.assertIn("package=com.colmeio.wasmagent", return_location)
                    self.assertIn("component=com.colmeio.wasmagent/.MainActivity", return_location)
                    self.assertNotIn("browser_fallback_url=", return_location)

                    conn = http.client.HTTPConnection(host, port, timeout=5)
                    manual_path = location + "&page=1"
                    conn.request("GET", manual_path)
                    manual_response = conn.getresponse()
                    return_body = manual_response.read().decode("utf-8", errors="replace")
                    self.assertEqual(manual_response.status, 200)
                    self.assertIn("intent://android-auth-return", return_body)
                    self.assertIn("intent://wa.colmeio.com/native/android/auth/return", return_body)
                    self.assertIn("package=com.colmeio.wasmagent", return_body)
                    self.assertIn("wasm-agent://android-auth-return", return_body)
                    self.assertNotIn("https://wa.colmeio.com/home", return_body)

                    conn = http.client.HTTPConnection(host, port, timeout=5)
                    conn.request("GET", "/.well-known/assetlinks.json")
                    assetlinks_response = conn.getresponse()
                    assetlinks_body = assetlinks_response.read().decode("utf-8", errors="replace")
                    self.assertEqual(assetlinks_response.status, 200)
                    self.assertIn("delegate_permission/common.handle_all_urls", assetlinks_body)
                    self.assertIn("com.colmeio.wasmagent", assetlinks_body)
                    self.assertIn(static_server.ANDROID_SIGNING_CERT_SHA256, assetlinks_body)

                    with self.assertRaises(static_server.BrowserError) as rejected:
                        static_server.complete_native_android_auth(httpd, user_payload["user"], {"session": session_id})
                    self.assertEqual(rejected.exception.status, 410)
                    self.assertEqual(rejected.exception.code, "native_return_required")
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
