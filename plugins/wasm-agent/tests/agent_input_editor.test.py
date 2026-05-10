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
DELETE = "\ue017"


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
        payload = {
            "capabilities": {
                "alwaysMatch": {
                    "browserName": "chrome",
                    "goog:chromeOptions": chrome_options,
                }
            }
        }
        data = self._request("POST", "/session", payload)
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
                "return document.readyState !== 'loading' && Boolean(document.querySelector('#agentInput'));"
            )
            if ready:
                return
            time.sleep(0.05)
        raise AssertionError("agent input did not load")

    @classmethod
    def expose_editor(cls):
        cls.driver.execute(
            """
            document.querySelector("#app").dataset.auth = "ready";
            const overlay = document.querySelector("#agentOverlay");
            overlay.dataset.open = "true";
            overlay.style.display = "block";
            const input = document.querySelector("#agentInput");
            Object.assign(input.style, {
              position: "fixed",
              left: "20px",
              top: "20px",
              width: "460px",
              minHeight: "96px",
              display: "block",
              opacity: "1",
              pointerEvents: "auto",
              zIndex: "2147483647",
            });
            input.hidden = false;
            return true;
            """
        )

    def set_editor_text(self, text):
        self.driver.execute(
            """
            const input = document.querySelector("#agentInput");
            input.replaceChildren(document.createTextNode(arguments[0]));
            delete input.dataset.renderedMarkdown;
            input.focus();
            input.dispatchEvent(new InputEvent("input", {
              bubbles: true,
              inputType: "insertText",
              data: String(arguments[0]).includes("`") ? "`" : String(arguments[0]).slice(-1),
            }));
            return true;
            """,
            text,
        )
        return self.editor_state()

    def editor_state(self):
        return self.driver.execute_async(
            """
            const done = arguments[arguments.length - 1];
            const input = document.querySelector("#agentInput");
            requestAnimationFrame(() => requestAnimationFrame(() => {
              done({
                text: input.textContent,
                html: input.innerHTML,
                rendered: input.dataset.renderedMarkdown || "",
                codeCount: input.querySelectorAll("code").length,
                codeText: input.querySelector("code")?.textContent || "",
              });
            }));
            """
        )

    def focus_editor_at_text_edge(self, collapse_to_end):
        self.driver.execute(
            """
            const input = document.querySelector("#agentInput");
            input.focus();
            const range = document.createRange();
            range.selectNodeContents(input);
            range.collapse(!Boolean(arguments[0]));
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            return input.textContent;
            """,
            collapse_to_end,
        )

    def make_empty_rendered_code(self, caret_at_end):
        self.driver.execute(
            """
            const input = document.querySelector("#agentInput");
            const code = document.createElement("code");
            code.textContent = "\\u200B";
            input.replaceChildren(code, document.createTextNode("\\u200B"));
            input.dataset.renderedMarkdown = "true";
            input.focus();
            const range = document.createRange();
            range.setStart(input, arguments[0] ? input.childNodes.length : 0);
            range.collapse(true);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            return input.innerHTML;
            """,
            caret_at_end,
        )

    def make_empty_rendered_code_with_inner_caret(self, caret_offset):
        self.driver.execute(
            """
            const input = document.querySelector("#agentInput");
            const paragraph = document.createElement("p");
            const code = document.createElement("code");
            code.textContent = "\\u200B";
            paragraph.append(code, document.createTextNode("\\u200B"));
            input.replaceChildren(paragraph);
            input.dataset.renderedMarkdown = "true";
            input.focus();
            const range = document.createRange();
            range.setStart(code.firstChild, arguments[0]);
            range.collapse(true);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            return input.innerHTML;
            """,
            caret_offset,
        )

    def test_empty_backtick_pair_stays_literal_when_input_starts_with_it(self):
        state = self.set_editor_text("``")
        self.assertEqual(state["text"], "``")
        self.assertEqual(state["rendered"], "")
        self.assertEqual(state["codeCount"], 0)
        self.assertNotIn("<code", state["html"])

    def test_typing_empty_backtick_pair_then_deleting_keeps_one_backtick(self):
        self.set_editor_text("")
        self.driver.send_keys(self.driver.element("#agentInput"), "``")
        state = self.editor_state()
        self.assertEqual(state["text"], "``")
        self.assertEqual(state["rendered"], "")
        self.assertEqual(state["codeCount"], 0)

        self.driver.send_keys(self.driver.element("#agentInput"), BACKSPACE)
        state = self.editor_state()
        self.assertEqual(state["text"], "`")
        self.assertEqual(state["rendered"], "")
        self.assertEqual(state["codeCount"], 0)

    def test_emptying_rendered_inline_code_returns_editable_backticks(self):
        state = self.set_editor_text("`test`")
        self.assertEqual(state["rendered"], "true")
        self.assertEqual(state["codeCount"], 1)
        self.assertEqual(state["codeText"], "test")

        state = self.driver.execute_async(
            """
            const done = arguments[arguments.length - 1];
            const input = document.querySelector("#agentInput");
            input.querySelector("code").textContent = "";
            input.focus();
            input.dispatchEvent(new InputEvent("input", {
              bubbles: true,
              inputType: "deleteContentBackward",
            }));
            requestAnimationFrame(() => requestAnimationFrame(() => {
              done({
                text: input.textContent,
                rendered: input.dataset.renderedMarkdown || "",
                codeCount: input.querySelectorAll("code").length,
              });
            }));
            """
        )
        self.assertEqual(state["text"], "``")
        self.assertEqual(state["rendered"], "")
        self.assertEqual(state["codeCount"], 0)

    def test_backspace_and_delete_on_empty_pair_keep_one_backtick(self):
        self.set_editor_text("``")
        self.focus_editor_at_text_edge(True)
        self.driver.send_keys(self.driver.element("#agentInput"), BACKSPACE)
        state = self.editor_state()
        self.assertEqual(state["text"], "`")
        self.assertEqual(state["codeCount"], 0)

        self.set_editor_text("``")
        self.focus_editor_at_text_edge(False)
        self.driver.send_keys(self.driver.element("#agentInput"), DELETE)
        state = self.editor_state()
        self.assertEqual(state["text"], "`")
        self.assertEqual(state["codeCount"], 0)

    def test_legacy_empty_code_span_unwraps_to_one_backtick(self):
        self.make_empty_rendered_code(True)
        self.driver.send_keys(self.driver.element("#agentInput"), BACKSPACE)
        state = self.editor_state()
        self.assertEqual(state["text"], "`")
        self.assertEqual(state["codeCount"], 0)

        self.make_empty_rendered_code(False)
        self.driver.send_keys(self.driver.element("#agentInput"), DELETE)
        state = self.editor_state()
        self.assertEqual(state["text"], "`")
        self.assertEqual(state["codeCount"], 0)

    def test_deleting_inside_empty_rendered_code_unwraps_to_one_backtick(self):
        self.make_empty_rendered_code_with_inner_caret(1)
        self.driver.send_keys(self.driver.element("#agentInput"), BACKSPACE)
        state = self.editor_state()
        self.assertEqual(state["text"], "`")
        self.assertEqual(state["rendered"], "")
        self.assertEqual(state["codeCount"], 0)

        self.make_empty_rendered_code_with_inner_caret(0)
        self.driver.send_keys(self.driver.element("#agentInput"), DELETE)
        state = self.editor_state()
        self.assertEqual(state["text"], "`")
        self.assertEqual(state["rendered"], "")
        self.assertEqual(state["codeCount"], 0)

    def test_copying_rendered_inline_code_preserves_markdown_backticks(self):
        state = self.set_editor_text("test `test` test test")
        self.assertEqual(state["rendered"], "true")
        self.assertEqual(state["codeCount"], 1)
        result = self.driver.execute(
            """
            const input = document.querySelector("#agentInput");
            const range = document.createRange();
            range.selectNodeContents(input);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            const copied = {};
            const event = new Event("copy", { bubbles: true, cancelable: true });
            Object.defineProperty(event, "clipboardData", {
              value: { setData: (type, value) => { copied[type] = value; } },
            });
            input.dispatchEvent(event);
            return { prevented: event.defaultPrevented, text: copied["text/plain"] || "" };
            """
        )
        self.assertTrue(result["prevented"])
        self.assertEqual(result["text"], "test `test` test test")


if __name__ == "__main__":
    unittest.main()
