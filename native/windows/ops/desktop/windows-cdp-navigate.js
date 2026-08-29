"use strict";

const { execFile } = require("node:child_process");
const http = require("node:http");

const OPERATION = "navigate_windows_cdp_persistent";
const SCHEMA = "hermes.wasm_agent.windows_cdp_navigation.v1";

function clean(value, limit = 1000) { return String(value || "").replace(/\s+/g, " ").trim().slice(0, limit); }

function normalizeUrl(value) {
  const text = String(value || "").trim();
  if (text.length < 8 || text.length > 2048) return "";
  try { const parsed = new URL(text); return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : ""; } catch { return ""; }
}

function portScript() {
  return [
    "$ErrorActionPreference = 'Stop';",
    "$profile = Join-Path $env:APPDATA 'WASM-Agent\\browser\\cdp-persistent';",
    "$activePort = Join-Path $profile 'DevToolsActivePort'; if (-not (Test-Path -LiteralPath $activePort)) { throw 'persistent_cdp_active_port_not_found' };",
    "$lines = @(Get-Content -LiteralPath $activePort -ErrorAction Stop); if ($lines.Count -lt 1) { throw 'persistent_cdp_active_port_invalid' };",
    "$port = [int]$lines[0]; if ($port -lt 1024 -or $port -gt 65535) { throw 'persistent_cdp_port_invalid' };",
    "$process = Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe'\" | Where-Object { $_.CommandLine -like ('*--user-data-dir=' + $profile + '*') -and $_.CommandLine -like '*--remote-debugging-port=*' } | Select-Object -First 1;",
    "[ordered]@{ port=$port; processId=[int]($process.ProcessId); browserWebSocketPath=[string]($lines | Select-Object -Skip 1 -First 1) } | ConvertTo-Json -Compress;",
  ].join("\n");
}

function discover(timeoutMs = 5000) {
  return new Promise((resolve) => execFile("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", portScript()], { timeout: timeoutMs, maxBuffer: 8192, windowsHide: true, encoding: "utf8" }, (error, stdout, stderr) => resolve({ ok: !error, stdout: String(stdout || ""), stderr: clean(stderr || error?.message), timedOut: Boolean(error?.killed) })));
}

function requestJson({ port, method = "GET", path, timeoutMs = 8000 }) {
  return new Promise((resolve) => {
    const request = http.request({ host: "127.0.0.1", port, method, path, timeout: timeoutMs }, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => { if (body.length < 64 * 1024) body += chunk; });
      response.on("end", () => { try { resolve({ ok: response.statusCode >= 200 && response.statusCode < 300, status: response.statusCode, value: JSON.parse(body) }); } catch { resolve({ ok: false, status: response.statusCode, error: "cdp_json_invalid" }); } });
    });
    request.on("timeout", () => request.destroy(new Error("cdp_request_timeout")));
    request.on("error", (error) => resolve({ ok: false, error: clean(error.message) }));
    request.end();
  });
}

async function run(context = {}, dependencies = {}) {
  const url = normalizeUrl(context.args?.url);
  if (!url) return { schema: SCHEMA, operation: OPERATION, ok: false, failureClassification: "windows_cdp_url_invalid" };
  if ((dependencies.platform || process.platform) !== "win32") return { schema: SCHEMA, operation: OPERATION, ok: false, failureClassification: "windows_native_shell_required" };
  context.markPhase?.("persistent_cdp_navigation_started");
  const found = await (dependencies.discover || discover)();
  if (!found.ok) return { schema: SCHEMA, operation: OPERATION, ok: false, failureClassification: found.timedOut ? "windows_cdp_discovery_timeout" : "windows_cdp_persistent_unavailable", error: clean(found.stderr) };
  let session; try { session = JSON.parse(found.stdout); } catch { return { schema: SCHEMA, operation: OPERATION, ok: false, failureClassification: "windows_cdp_discovery_invalid" }; }
  const port = Number(session.port);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) return { schema: SCHEMA, operation: OPERATION, ok: false, failureClassification: "windows_cdp_port_invalid" };
  const request = dependencies.requestJson || requestJson;
  const before = await request({ port, path: "/json/list" });
  const existing = Array.isArray(before.value) ? before.value.find((item) => normalizeUrl(item?.url) === url && item?.id) : null;
  if (before.ok && existing) {
    const result = { schema: SCHEMA, operation: OPERATION, ok: true, realm: "browser_cdp_persistent", requestedUrl: url, observedUrl: normalizeUrl(existing.url), targetId: clean(existing.id, 160), processId: Number(session.processId) || 0, port, reusedTarget: true, proof: ["windows.browser.cdp.navigation.observed"], answer: `The persistent CDP browser is already at ${normalizeUrl(existing.url)}` };
    context.markPhase?.("persistent_cdp_navigation_observed", { targetId: result.targetId, observedUrl: result.observedUrl, reusedTarget: true });
    return result;
  }
  const created = await request({ port, method: "PUT", path: `/json/new?${encodeURIComponent(url)}` });
  if (!created.ok || !created.value?.id) return { schema: SCHEMA, operation: OPERATION, ok: false, failureClassification: "windows_cdp_navigation_failed", status: created.status || 0, error: clean(created.error) };
  const observed = await request({ port, path: "/json/list" });
  const target = Array.isArray(observed.value) ? observed.value.find((item) => item?.id === created.value.id) : null;
  const observedUrl = normalizeUrl(target?.url || created.value.url);
  if (!observed.ok || !target || !observedUrl) return { schema: SCHEMA, operation: OPERATION, ok: false, failureClassification: "windows_cdp_navigation_unverified" };
  const result = { schema: SCHEMA, operation: OPERATION, ok: true, realm: "browser_cdp_persistent", requestedUrl: url, observedUrl, targetId: clean(target.id, 160), processId: Number(session.processId) || 0, port, reusedTarget: false, proof: ["windows.browser.cdp.navigation.observed"], answer: `Navigated the persistent CDP browser to ${observedUrl}` };
  context.markPhase?.("persistent_cdp_navigation_observed", { targetId: result.targetId, observedUrl });
  return result;
}

module.exports = { OPERATION, SCHEMA, normalizeUrl, portScript, requestJson, run };
