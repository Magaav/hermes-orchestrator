#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from urllib.request import urlopen

PEOPLE_BROWSER_TEST_PATH = Path(__file__).with_name("people_chat_browser_acceptance.test.py")
PEOPLE_BROWSER_SPEC = importlib.util.spec_from_file_location("people_chat_browser_acceptance", PEOPLE_BROWSER_TEST_PATH)
if PEOPLE_BROWSER_SPEC is None or PEOPLE_BROWSER_SPEC.loader is None:
    raise RuntimeError(f"could not load {PEOPLE_BROWSER_TEST_PATH}")
people_browser = importlib.util.module_from_spec(PEOPLE_BROWSER_SPEC)
PEOPLE_BROWSER_SPEC.loader.exec_module(people_browser)

BrowserPage = people_browser.BrowserPage
CHROMIUM = people_browser.CHROMIUM
SERVER_PATH = people_browser.SERVER_PATH
free_port = people_browser.free_port
http_json = people_browser.http_json


class SharedPointerBrowserSmokeTest(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        if not CHROMIUM:
            self.skipTest("Chromium is not installed")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cloud_root = self.root / "private-cloud"
        self.cloud_root.mkdir(parents=True)
        (self.cloud_root / "conf").mkdir(parents=True)
        self.auth_secret = "shared-pointer-browser-smoke-secret"
        self.server_port = free_port()
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.alice = {"id": 5000000101, "email": "alice.pointer@example.test", "name": "Alice Pointer"}
        self.bob = {"id": 5000000202, "email": "bob.pointer@example.test", "name": "Bob Pointer"}
        self.shared_space_id = "pointer-smoke-shared"
        self.alice_space_id = "pointer-smoke-alice"
        self.bob_space_id = "pointer-smoke-bob"
        (self.cloud_root / "conf" / "wa.env").write_text(
            "ADMIN_EMAIL=alice.pointer@example.test\n"
            "USER_EMAILS=alice.pointer@example.test,bob.pointer@example.test\n",
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
                        f"shared-pointer-smoke-{user['id']}",
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
            "spaces": [{"id": self.alice_space_id, "title": "Pointer Smoke", "space_area": area}],
        })
        shared = self._api(self.alice["id"], "/spaces/share", {
            "space_id": self.alice_space_id,
            "shared_space_id": self.shared_space_id,
            "title": "Pointer Smoke",
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

    def test_shared_pointer_replays_dense_path_without_unbounded_visual_growth(self) -> None:
        alice = self._new_browser_page("alice-pointer", self.alice, f"/spaces/{self.alice_space_id}?shared-pointer-diagnostics=1")
        bob = self._new_browser_page("bob-pointer", self.bob, f"/spaces/{self.bob_space_id}?shared-pointer-diagnostics=1")
        alice.wait(f"document.querySelector('#app')?.dataset.activeSpace === {json.dumps(self.alice_space_id)}", timeout=15)
        bob.wait(f"document.querySelector('#app')?.dataset.activeSpace === {json.dumps(self.bob_space_id)}", timeout=15)
        bob.wait("document.querySelector('.space-viewport') && document.querySelector('#spaceBoard')", timeout=10)

        watch_script = """(() => {
              const startedAt = performance.now();
              const samples = [];
              window.__sharedPointerWatch = { startedAt, samples };
              const tick = (now) => {
                const debug = window.wasmAgentSharedPointerDebug?.() || {};
                const visual = Array.isArray(debug.visuals) ? debug.visuals[0] : null;
                const point = visual ? { x: Number(visual.x || 0), y: Number(visual.y || 0) } : null;
                const diag = {};
                const diagnostics = document.querySelector('[data-shared-space-pointer-diagnostics]');
                if (diagnostics) {
                  const children = Array.from(diagnostics.children);
                  for (let index = 0; index + 1 < children.length; index += 2) {
                    diag[children[index].textContent || ''] = children[index + 1].textContent || '';
                  }
                }
                samples.push({
                  t: now,
                  point,
                  transform: point ? `canvas:${point.x.toFixed(1)},${point.y.toFixed(1)}` : '',
                  label: visual?.label || '',
                  pointerCount: Array.isArray(debug.visuals) ? debug.visuals.length : document.querySelectorAll('[data-shared-space-pointer]').length,
                  trailDots: Math.max(Number(visual?.historyLength || 0), document.querySelectorAll('.shared-space-pointer-trail span').length),
                  canvasCount: document.querySelectorAll('[data-shared-space-pointer-canvas]').length,
                  layer: debug.layer || '',
                  leadMs: Number(visual?.predictionLeadMs || 0),
                  predictionPx: Number(visual?.predictionPx || 0),
                  netAgeMs: Number(visual?.netAgeMs || 0),
                  renderBufferMs: Number(visual?.renderBufferMs || 0),
                  realtimeSamples: Number(visual?.realtimeSamples || 0),
                  realtimeMode: visual?.realtimeMode || '',
                  replayMode: visual?.replayMode || '',
                  diag,
                });
                if (now - startedAt < 1800) requestAnimationFrame(tick);
              };
              requestAnimationFrame(tick);
            })()"""
        alice.evaluate(watch_script)
        bob.evaluate(watch_script)

        alice.evaluate(
            """(() => new Promise((resolve) => {
              const viewport = document.querySelector('.space-viewport');
              const rect = viewport.getBoundingClientRect();
              const width = Math.max(260, rect.width || viewport.clientWidth || 800);
              const height = Math.max(220, rect.height || viewport.clientHeight || 600);
              const centerX = rect.left + Math.min(width - 130, Math.max(130, width * 0.48));
              const centerY = rect.top + Math.min(height - 120, Math.max(120, height * 0.48));
              const radiusX = Math.min(150, Math.max(70, width * 0.2));
              const radiusY = Math.min(110, Math.max(55, height * 0.18));
              let step = 0;
              const total = 120;
              const dispatch = (type, x, y, buttons = 0) => {
                document.dispatchEvent(new PointerEvent(type, {
                  bubbles: true,
                  composed: true,
                  clientX: x,
                  clientY: y,
                  pointerId: 7,
                  pointerType: 'mouse',
                  isPrimary: true,
                  button: 0,
                  buttons,
                }));
              };
              dispatch('pointerdown', centerX + radiusX, centerY, 1);
              const tick = () => {
                const theta = (step / total) * Math.PI * 4;
                const wobble = Math.sin(theta * 2.5) * 18;
                const x = centerX + Math.cos(theta) * (radiusX + wobble);
                const y = centerY + Math.sin(theta) * radiusY;
                dispatch('pointermove', x, y, step < total ? 1 : 0);
                step += 1;
                if (step <= total) {
                  setTimeout(tick, 8);
                  return;
                }
                dispatch('pointerup', x, y, 0);
                setTimeout(resolve, 350);
              };
              tick();
            }))()"""
        )
        bob.wait("window.wasmAgentSharedPointerDebug?.().visuals?.length > 0", timeout=10)
        alice.evaluate(
            """(() => new Promise((resolve) => {
              const viewport = document.querySelector('.space-viewport');
              const rect = viewport.getBoundingClientRect();
              const x = rect.left + Math.min(Math.max(rect.width * 0.52, 140), rect.width - 140);
              const y = rect.top + Math.min(Math.max(rect.height * 0.52, 120), rect.height - 120);
              const dispatch = (type, buttons = 0) => {
                document.dispatchEvent(new PointerEvent(type, {
                  bubbles: true,
                  composed: true,
                  clientX: x,
                  clientY: y,
                  pointerId: 9,
                  pointerType: 'mouse',
                  isPrimary: true,
                  button: 0,
                  buttons,
                }));
              };
              dispatch('pointerdown', 1);
              setTimeout(() => {
                dispatch('pointerup', 0);
                resolve();
              }, 40);
            }))()"""
        )
        bob.wait(
            "window.wasmAgentSharedPointerDebug?.().visuals?.some((visual) => visual.label === 'Alice Pointer' && visual.pulseActive)",
            timeout=10,
            interval=0.05,
        )
        time.sleep(1.0)
        collect_script = """(() => {
              const samples = window.__sharedPointerWatch?.samples || [];
              const withPoints = samples.filter((sample) => sample.point);
              const unique = new Set(withPoints.map((sample) => `${sample.point.x.toFixed(1)},${sample.point.y.toFixed(1)}`));
              let maxJump = 0;
              let distance = 0;
              for (let index = 1; index < withPoints.length; index += 1) {
                const previous = withPoints[index - 1].point;
                const next = withPoints[index].point;
                const jump = Math.hypot(next.x - previous.x, next.y - previous.y);
                maxJump = Math.max(maxJump, jump);
                distance += jump;
              }
              const latest = samples[samples.length - 1] || {};
              const maxTrailDots = samples.reduce((value, sample) => Math.max(value, Number(sample.trailDots || 0)), 0);
              const maxPointers = samples.reduce((value, sample) => Math.max(value, Number(sample.pointerCount || 0)), 0);
              const maxCanvases = samples.reduce((value, sample) => Math.max(value, Number(sample.canvasCount || 0)), 0);
              const layers = Array.from(new Set(samples.map((sample) => sample.layer || '').filter(Boolean)));
              const modes = Array.from(new Set(samples.map((sample) => sample.diag?.Mode || '').filter(Boolean)));
              const transports = Array.from(new Set(samples.map((sample) => sample.diag?.Transport || '').filter(Boolean)));
              const realtimeModes = Array.from(new Set(samples.map((sample) => sample.realtimeMode || '').filter(Boolean)));
              const replayModes = Array.from(new Set(samples.map((sample) => sample.replayMode || '').filter(Boolean)));
              const sampleCounts = samples.map((sample) => {
                const value = String(sample.diag?.Samples || '').split('/')[0];
                return Number(value || 0);
              }).filter(Number.isFinite);
              const maxLeadMs = samples.reduce((value, sample) => Math.max(value, Number(sample.leadMs || 0)), 0);
              const maxPredictionPx = samples.reduce((value, sample) => Math.max(value, Number(sample.predictionPx || 0)), 0);
              const maxRealtimeSamples = samples.reduce((value, sample) => Math.max(value, Number(sample.realtimeSamples || 0)), 0);
              const maxNetAgeMs = samples.reduce((value, sample) => Math.max(value, Number(sample.netAgeMs || 0)), 0);
              const maxRenderBufferMs = samples.reduce((value, sample) => Math.max(value, Number(sample.renderBufferMs || 0)), 0);
              const maxBinaryReceived = samples.reduce((value, sample) => {
                const valueText = String(sample.diag?.Binary || '0/0').split('/')[0];
                return Math.max(value, Number(valueText || 0));
              }, 0);
              const maxRtcOpen = samples.reduce((value, sample) => {
                const valueText = String(sample.diag?.RTC || '0/0').split('/')[0];
                return Math.max(value, Number(valueText || 0));
              }, 0);
              const maxRtcKb = samples.reduce((value, sample) => Math.max(value, Number(sample.diag?.RtcKB || 0)), 0);
              return {
                totalSamples: samples.length,
                pointSamples: withPoints.length,
                uniqueTransforms: unique.size,
                maxJump,
                distance,
                maxTrailDots,
                maxPointers,
                maxCanvases,
                layers,
                modes,
                transports,
                realtimeModes,
                replayModes,
                maxSampleCount: sampleCounts.length ? Math.max(...sampleCounts) : 0,
                maxLeadMs,
                maxPredictionPx,
                maxRealtimeSamples,
                maxNetAgeMs,
                maxRenderBufferMs,
                maxBinaryReceived,
                maxRtcOpen,
                maxRtcKb,
                latest,
              };
            })()"""
        result = bob.evaluate(collect_script)
        local_result = alice.evaluate(collect_script)

        self.assertGreater(result["pointSamples"], 30, result)
        self.assertGreater(result["uniqueTransforms"], 20, result)
        self.assertGreater(result["distance"], 120, result)
        self.assertLess(result["maxJump"], 180, result)
        self.assertEqual(result["maxPointers"], 1, result)
        self.assertEqual(result["maxCanvases"], 1, result)
        self.assertIn("canvas", result["layers"], result)
        self.assertLessEqual(result["maxTrailDots"], 28, result)
        self.assertLessEqual(result["maxSampleCount"], 28, result)
        self.assertLessEqual(result["maxLeadMs"], 0.5, result)
        self.assertLessEqual(result["maxPredictionPx"], 0.5, result)
        self.assertLessEqual(result["maxRealtimeSamples"], 64, result)
        self.assertLessEqual(result["maxRenderBufferMs"], 12.5, result)
        self.assertLess(result["maxNetAgeMs"], 1400, result)
        self.assertIn("binary", result["transports"], result)
        self.assertGreater(result["maxBinaryReceived"], 0, result)
        if result["maxRtcOpen"] > 0:
            self.assertGreater(result["maxRtcKb"], 0, result)
        self.assertNotIn("net-predict", set(result["realtimeModes"]), result)
        self.assertNotIn("lead", set(result["modes"]), result)
        self.assertTrue(set(result["realtimeModes"]) & {"net-buffer", "net-latest", "net-single", "net-wait"}, result)
        self.assertTrue(set(result["replayModes"]) & {"low-latency", "stable", "idle", "snap"}, result)
        self.assertTrue(set(result["modes"]) & {"net-buffer", "net-latest", "path", "smooth", "fast", "settled"}, result)
        self.assertGreater(local_result["pointSamples"], 30, local_result)
        self.assertGreater(local_result["uniqueTransforms"], 20, local_result)
        self.assertGreater(local_result["distance"], 120, local_result)
        self.assertLess(local_result["maxJump"], 180, local_result)
        self.assertEqual(local_result["maxPointers"], 1, local_result)
        self.assertEqual(local_result["maxCanvases"], 1, local_result)
        self.assertIn("canvas", local_result["layers"], local_result)
        self.assertLessEqual(local_result["maxTrailDots"], 28, local_result)
        self.assertLessEqual(local_result["maxSampleCount"], 28, local_result)
        self.assertLessEqual(local_result["maxLeadMs"], 0.5, local_result)
        self.assertLessEqual(local_result["maxPredictionPx"], 0.5, local_result)
        self.assertLessEqual(local_result["maxRenderBufferMs"], 0.5, local_result)
        self.assertNotIn("local-predict", set(local_result["realtimeModes"]), local_result)
        self.assertNotIn("lead", set(local_result["modes"]), local_result)
        self.assertTrue(set(local_result["realtimeModes"]) & {"local-buffer", "local-latest", "local-single", "local-wait"}, local_result)
        self.assertTrue(set(local_result["modes"]) & {"local-buffer", "local-latest", "path", "smooth", "fast", "settled"}, local_result)


if __name__ == "__main__":
    unittest.main()
