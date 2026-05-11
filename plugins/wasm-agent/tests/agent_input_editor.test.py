import http.client
import http.server
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
import unittest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = PLUGIN_ROOT / "public"
BACKSPACE = "\ue003"
ARROW_LEFT = "\ue012"
ARROW_RIGHT = "\ue014"
ENTER = "\ue007"


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class PublicHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_ROOT), **kwargs)

    def log_message(self, _format, *args):
        return


class StaticSite:
    def __init__(self):
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), PublicHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class WebDriver:
    def __init__(self):
        chromedriver = shutil.which("chromedriver")
        if not chromedriver:
            raise unittest.SkipTest("chromedriver is required for browser editor tests")
        self.port = free_port()
        self.proc = subprocess.Popen(
            [chromedriver, f"--port={self.port}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.session_id = ""
        try:
            self._wait_until_ready()
            self._create_session()
        except Exception:
            self.close()
            raise

    def _request(self, method, path, payload=None, timeout=30):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read().decode("utf-8")
        finally:
            conn.close()
        data = json.loads(raw) if raw else {}
        if response.status >= 400:
            raise AssertionError(f"WebDriver {method} {path} failed: {response.status} {raw}")
        value = data.get("value")
        if isinstance(value, dict) and value.get("error"):
            raise AssertionError(f"WebDriver {method} {path} error: {value}")
        return data

    def _wait_until_ready(self):
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                self._request("GET", "/status", timeout=1)
                return
            except Exception:
                time.sleep(0.05)
        raise AssertionError("chromedriver did not become ready")

    def _create_session(self):
        chrome_binary = os.environ.get("HERMES_WASM_AGENT_CHROMIUM")
        chrome_options = {
            "args": [
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1280,900",
            ]
        }
        if chrome_binary:
            chrome_options["binary"] = chrome_binary
        data = self._request("POST", "/session", {
            "capabilities": {
                "alwaysMatch": {
                    "browserName": "chrome",
                    "goog:chromeOptions": chrome_options,
                }
            }
        })
        self.session_id = data.get("value", {}).get("sessionId") or data.get("sessionId", "")
        if not self.session_id:
            raise AssertionError(f"WebDriver session id missing: {data}")

    def close(self):
        if self.session_id:
            try:
                self._request("DELETE", f"/session/{self.session_id}")
            finally:
                self.session_id = ""
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)

    def url(self, url):
        self._request("POST", f"/session/{self.session_id}/url", {"url": url})

    def execute(self, script, *args):
        payload = {"script": script, "args": list(args)}
        return self._request("POST", f"/session/{self.session_id}/execute/sync", payload).get("value")

    def execute_async(self, script, *args):
        payload = {"script": script, "args": list(args)}
        return self._request("POST", f"/session/{self.session_id}/execute/async", payload).get("value")

    def element(self, selector):
        value = self._request(
            "POST",
            f"/session/{self.session_id}/element",
            {"using": "css selector", "value": selector},
        ).get("value", {})
        return value.get("element-6066-11e4-a52e-4f735466cecf") or value.get("ELEMENT")

    def send_keys(self, element_id, text):
        self._request(
            "POST",
            f"/session/{self.session_id}/element/{element_id}/value",
            {"text": text},
        )


class AgentInputEditorBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = StaticSite()
        cls.site.start()
        try:
            cls.driver = WebDriver()
            cls.driver.url(f"{cls.site.url}/index.html?agent-input-editor-test=1")
            cls.wait_for_editor()
            cls.expose_editor()
        except Exception:
            if getattr(cls, "driver", None):
                cls.driver.close()
            cls.site.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.driver.close()
        cls.site.stop()

    @classmethod
    def wait_for_editor(cls):
        deadline = time.time() + 10
        while time.time() < deadline:
            ready = cls.driver.execute(
                "return document.readyState !== 'loading' && Boolean(document.querySelector('#agentInput')?.tagName === 'TEXTAREA');"
            )
            if ready:
                return
            time.sleep(0.05)
        raise AssertionError("agent textarea did not load")

    @classmethod
    def expose_editor(cls):
        cls.driver.execute(
            """
            document.querySelector("#app").dataset.auth = "ready";
            const overlay = document.querySelector("#agentOverlay");
            overlay.dataset.open = "true";
            overlay.style.display = "block";
            const composer = document.querySelector("#agentComposer");
            const input = document.querySelector("#agentInput");
            Object.assign(composer.style, {
              position: "fixed",
              left: "20px",
              top: "20px",
              width: "520px",
              display: "block",
              opacity: "1",
              pointerEvents: "auto",
              zIndex: "2147483647",
            });
            Object.assign(input.style, {
              minHeight: "96px",
              display: "block",
              opacity: "1",
              pointerEvents: "auto",
            });
            input.hidden = false;
            return true;
            """
        )

    def set_editor_text(self, text, caret=None):
        self.driver.execute(
            """
            const input = document.querySelector("#agentInput");
            input.value = arguments[0];
            const caret = arguments[1] == null ? input.value.length : arguments[1];
            input.focus();
            input.setSelectionRange(caret, caret);
            input.dispatchEvent(new InputEvent("input", {
              bubbles: true,
              inputType: "insertText",
              data: String(arguments[0]).slice(-1),
            }));
            return true;
            """,
            text,
            caret,
        )
        return self.editor_state()

    def editor_state(self):
        return self.driver.execute_async(
            """
            const done = arguments[arguments.length - 1];
            const input = document.querySelector("#agentInput");
            requestAnimationFrame(() => requestAnimationFrame(() => {
              done({
                value: input.value,
                selectionStart: input.selectionStart,
                selectionEnd: input.selectionEnd,
                overlayText: document.querySelector("#agentInputOverlay")?.textContent || "",
                overlayHtml: document.querySelector("#agentInputOverlay")?.innerHTML || "",
                paletteHidden: document.querySelector("#agentCommandPalette")?.hidden,
                firstCommand: document.querySelector("#agentCommandPalette .chat-command-option strong")?.textContent || "",
              });
            }));
            """
        )

    def test_textarea_is_raw_source_of_truth(self):
        state = self.set_editor_text("`test`")
        self.assertEqual(state["value"], "`test`")
        self.assertIn("test", state["overlayText"])
        self.assertNotIn("<code", self.driver.execute("return document.querySelector('#agentInput').innerHTML || ''"))

    def test_closing_backtick_never_requires_trailing_space(self):
        self.set_editor_text("")
        input_id = self.driver.element("#agentInput")
        for char in "`test`":
            self.driver.send_keys(input_id, char)
        state = self.editor_state()
        self.assertEqual(state["value"], "`test`")
        self.assertIn("chat-md-inline-code", state["overlayHtml"])

    def test_arrow_keys_do_not_mutate_raw_value(self):
        self.set_editor_text("plain `code` plain")
        input_id = self.driver.element("#agentInput")
        before = self.editor_state()["value"]
        self.driver.send_keys(input_id, ARROW_LEFT)
        self.driver.send_keys(input_id, ARROW_RIGHT)
        state = self.editor_state()
        self.assertEqual(state["value"], before)

    def test_backspace_deletes_one_raw_character(self):
        self.set_editor_text("`test`")
        self.driver.send_keys(self.driver.element("#agentInput"), BACKSPACE)
        state = self.editor_state()
        self.assertEqual(state["value"], "`test")

    def test_slash_palette_filters_and_inserts_command(self):
        self.set_editor_text("/g")
        state = self.editor_state()
        self.assertFalse(state["paletteHidden"])
        self.assertEqual(state["firstCommand"], "/goal")
        self.driver.send_keys(self.driver.element("#agentInput"), ENTER)
        state = self.editor_state()
        self.assertEqual(state["value"], "/goal ")
        self.assertEqual(state["selectionStart"], len("/goal "))

    def test_slash_inside_sentence_does_not_open_palette(self):
        state = self.set_editor_text("look at /tmp/file")
        self.assertTrue(state["paletteHidden"])

    def test_native_newline_and_overlay_stay_in_sync(self):
        self.set_editor_text("hello")
        input_id = self.driver.element("#agentInput")
        self.driver.send_keys(input_id, "\ue008" + ENTER)
        self.driver.send_keys(input_id, "world")
        state = self.editor_state()
        self.assertEqual(state["value"], "hello\nworld")
        self.assertIn("hello\nworld", state["overlayText"])


if __name__ == "__main__":
    unittest.main()
