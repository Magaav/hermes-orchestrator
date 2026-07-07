"use strict";

const fs = require("fs");
const http = require("http");
const net = require("net");
const path = require("path");
const { request } = http;
const { request: secureRequest } = require("https");
const { spawn, spawnSync } = require("child_process");
const { SimulationContext, redactString, redactValue } = require("./core");

const DEFAULT_WEB_URL = "http://127.0.0.1:8877/home";
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const WASM_AGENT_SERVER_PATH = path.join(REPO_ROOT, "plugins", "wasm-agent", "server", "static_server.py");
const ANDROID_SHELL_QUERY = {
  native: "android",
  shell: "android-webview",
  buildId: "playwright-sim",
};
const BANNED_VISIBLE_TERMS = [
  "Custom Tabs",
  "opened in browser",
  "127.0.0.1",
  "localhost",
  "Install app",
  "Download Windows",
  "Download Android APK",
];
const ANDROID_SHELL_PROOF_KINDS = [
  "android_native_shell_detected",
  "app_ready",
  "authenticated_ui_visible",
  "first_screen_readiness",
];

function loadPlaywright() {
  try {
    return { source: "playwright", module: require("playwright") };
  } catch {
    return { source: "playwright-core", module: require("playwright-core") };
  }
}

function commandPath(commandName) {
  const result = spawnSync("bash", ["-lc", `command -v ${commandName}`], {
    encoding: "utf8",
  });
  if (result.status !== 0) return "";
  return String(result.stdout || "").trim().split("\n")[0] || "";
}

function chromiumExecutablePath() {
  const envPath = process.env.WASM_AGENT_SIM_CHROMIUM
    || process.env.HERMES_WASM_AGENT_CHROMIUM
    || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
  if (envPath) return envPath;
  for (const commandName of ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "microsoft-edge"]) {
    const found = commandPath(commandName);
    if (found) return found;
  }
  return "";
}

function playwrightCacheRoot() {
  const packageRoot = path.dirname(require.resolve("playwright-core/package.json"));
  const envPath = process.env.PLAYWRIGHT_BROWSERS_PATH;
  if (envPath === "0") return path.join(packageRoot, ".local-browsers");
  if (envPath) return path.isAbsolute(envPath) ? envPath : path.resolve(process.env.INIT_CWD || process.cwd(), envPath);
  if (process.platform === "linux") return path.join(process.env.XDG_CACHE_HOME || path.join(process.env.HOME || "", ".cache"), "ms-playwright");
  if (process.platform === "darwin") return path.join(process.env.HOME || "", "Library", "Caches", "ms-playwright");
  if (process.platform === "win32") return path.join(process.env.LOCALAPPDATA || path.join(process.env.USERPROFILE || "", "AppData", "Local"), "ms-playwright");
  return "";
}

function playwrightFfmpegExecutablePath() {
  try {
    const packageRoot = path.dirname(require.resolve("playwright-core/package.json"));
    const browsers = JSON.parse(fs.readFileSync(path.join(packageRoot, "browsers.json"), "utf8"));
    const ffmpeg = (browsers.browsers || []).find((item) => item.name === "ffmpeg");
    if (!ffmpeg?.revision) return "";
    const executable = process.platform === "win32"
      ? "ffmpeg-win64.exe"
      : process.platform === "darwin"
        ? "ffmpeg-mac"
        : "ffmpeg-linux";
    const filePath = path.join(playwrightCacheRoot(), `ffmpeg-${ffmpeg.revision}`, executable);
    return fs.existsSync(filePath) ? filePath : "";
  } catch {
    return "";
  }
}

function withAndroidShellQuery(inputUrl) {
  const url = new URL(inputUrl);
  for (const [key, value] of Object.entries(ANDROID_SHELL_QUERY)) {
    url.searchParams.set(key, value);
  }
  return url.toString();
}

function envDisabled(value) {
  return ["0", "false", "no", "off"].includes(String(value || "").trim().toLowerCase());
}

function simulatorAuthEvidence(auth) {
  if (!auth) return { enabled: false, reason: "not_run" };
  const { cookie, ...safeAuth } = auth;
  return safeAuth;
}

function ensureSimulatorAuthUser() {
  if (envDisabled(process.env.WASM_AGENT_SIM_AUTH)) {
    return { enabled: false, ok: true, reason: "disabled" };
  }
  if (!fs.existsSync(WASM_AGENT_SERVER_PATH)) {
    return { enabled: true, ok: false, reason: "server_missing", server_path: WASM_AGENT_SERVER_PATH };
  }

  const script = String.raw`
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

def emit(payload):
    print(json.dumps(payload, sort_keys=True))

try:
    server_path = Path(os.environ["WASM_AGENT_SIM_SERVER_PATH"]).resolve()
    spec = importlib.util.spec_from_file_location("wasm_agent_static_server_sim_auth", server_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    admins = sorted(module.allowed_admin_emails())
    users = sorted(module.allowed_user_emails())
    requested_email = os.environ.get("WASM_AGENT_SIM_USER_EMAIL", "").strip().lower()
    email = requested_email or (admins[0] if admins else "") or (users[0] if users else "")
    if not email:
        emit({
            "enabled": True,
            "ok": False,
            "reason": "no_allowed_email",
            "admin_count": len(admins),
            "user_count": len(users),
            "db_path": str(module.auth_db_path()),
        })
        sys.exit(0)
    if not module.is_allowed_account_email(email):
        emit({
            "enabled": True,
            "ok": False,
            "reason": "email_not_allowed",
            "requested": bool(requested_email),
            "email_hash": hashlib.sha256(email.encode("utf-8")).hexdigest()[:16],
            "admin_count": len(admins),
            "user_count": len(users),
            "db_path": str(module.auth_db_path()),
        })
        sys.exit(0)

    user_id_raw = os.environ.get("WASM_AGENT_SIM_USER_ID", "").strip()
    if user_id_raw.isdigit():
        user_id = int(user_id_raw)
    else:
        digest = hashlib.blake2s(email.encode("utf-8"), digest_size=6).digest()
        user_id = 810000000000000000 + (int.from_bytes(digest, "big") % 90000000000000)
    name = os.environ.get("WASM_AGENT_SIM_USER_NAME", "").strip() or "WASM Agent Simulator"
    provider_sub = "sim-" + hashlib.sha256(email.encode("utf-8")).hexdigest()[:24]
    now = int(time.time())
    with module.auth_connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO user_tb
              (id, provider, provider_sub, email, email_verified, name, picture_url, created_at, updated_at, last_login_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, "google", provider_sub, email, 1, name, "", now, now, now),
        )
        conn.commit()
    emit({
        "enabled": True,
        "ok": True,
        "user_id": str(user_id),
        "email_hash": hashlib.sha256(email.encode("utf-8")).hexdigest()[:16],
        "role": "admin" if module.is_admin_email(email) else "user",
        "admin_count": len(admins),
        "user_count": len(users),
        "db_path": str(module.auth_db_path()),
        "cookie": module.signed_auth_value(str(user_id)),
    })
except Exception as exc:
    emit({"enabled": True, "ok": False, "reason": "exception", "error": str(exc)})
`;

  const result = spawnSync("python3", ["-c", script], {
    cwd: REPO_ROOT,
    env: {
      ...process.env,
      WASM_AGENT_SIM_SERVER_PATH: WASM_AGENT_SERVER_PATH,
    },
    encoding: "utf8",
    timeout: Number(process.env.WASM_AGENT_SIM_AUTH_TIMEOUT_MS || 5000),
  });
  if (result.error) {
    return { enabled: true, ok: false, reason: "spawn_error", error: result.error.message };
  }
  const stdout = String(result.stdout || "").trim().split("\n").filter(Boolean).pop() || "";
  try {
    const payload = JSON.parse(stdout);
    if (result.status !== 0 && payload.ok !== true) {
      payload.status = result.status;
    }
    return payload;
  } catch {
    return {
      enabled: true,
      ok: false,
      reason: "invalid_output",
      status: result.status,
      stdout: redactString(stdout).slice(0, 500),
      stderr: redactString(String(result.stderr || "")).slice(0, 500),
    };
  }
}

function checkReachable(urlString, redirects = 0) {
  return new Promise((resolve) => {
    let settled = false;
    const url = new URL(urlString);
    const client = url.protocol === "https:" ? secureRequest : request;
    const req = client(url, {
      method: "GET",
      timeout: Number(process.env.WASM_AGENT_SIM_REACHABLE_TIMEOUT_MS || 4000),
      headers: {
        Accept: "text/html,application/json;q=0.9,*/*;q=0.8",
        "User-Agent": "horc-app-simulator/0.1",
      },
    }, (res) => {
      const status = Number(res.statusCode || 0);
      const location = res.headers.location || "";
      res.resume();
      if ([301, 302, 303, 307, 308].includes(status) && location && redirects < 3) {
        const next = new URL(location, url).toString();
        checkReachable(next, redirects + 1).then(resolve);
        return;
      }
      settled = true;
      resolve({
        ok: status > 0 && status < 500,
        status,
        url: urlString,
      });
    });
    req.on("timeout", () => {
      req.destroy(new Error("request timeout"));
    });
    req.on("error", (error) => {
      if (settled) return;
      settled = true;
      resolve({
        ok: false,
        status: 0,
        url: urlString,
        error: error.message,
      });
    });
    req.end();
  });
}

function consoleEntry(message) {
  return {
    type: message.type(),
    text: redactString(message.text()),
    location: redactValue(message.location()),
  };
}

function requestFailureEntry(requestItem) {
  return {
    method: requestItem.method(),
    url: redactString(requestItem.url()),
    resourceType: requestItem.resourceType(),
    failure: redactValue(requestItem.failure()),
  };
}

function responseFailureEntry(response) {
  return {
    status: response.status(),
    statusText: response.statusText(),
    url: redactString(response.url()),
    request: {
      method: response.request().method(),
      resourceType: response.request().resourceType(),
    },
  };
}

function androidBridgeInitScript() {
  return `(() => {
    const diagnostics = [];
    const shellInfo = {
      shell: "android-webview",
      nativeShell: "android-webview",
      platform: "android",
      buildPlatform: "android",
      buildId: "playwright-sim",
      diagnosticsPath: "playwright-sim",
    };
    function parsePayload(payload) {
      if (!payload) return {};
      if (typeof payload === "object") return payload;
      try { return JSON.parse(payload); } catch { return { raw: String(payload) }; }
    }
    function record(kind, payload) {
      const entry = {
        kind,
        payload: parsePayload(payload),
        timestamp: new Date().toISOString(),
      };
      diagnostics.push(entry);
      window.__wasmAgentSimDiagnostics = diagnostics;
      try {
        console.info("wasm-agent-sim:" + kind, JSON.stringify(entry));
      } catch {}
      return JSON.stringify({ ok: true });
    }
    window.__wasmAgentSimDiagnostics = diagnostics;
    window.wasmAgentAndroid = {
      shellInfo: () => JSON.stringify(shellInfo),
      logDiagnostic: record,
      appReady: (payload) => record("app_ready", payload),
      authSessionId: () => "playwright-sim",
      startGoogleLogin: () => record("google_login_start_requested", {}),
    };
    window.wasmAgentNative = {
      platform: "android",
      buildPlatform: "android",
      nativeShell: "android-webview",
      buildId: "playwright-sim",
      shellInfo: () => JSON.stringify(shellInfo),
      logDiagnostic: record,
      logAuthDiagnostic: (kind, payload) => record("auth_" + kind, payload),
      reload: () => record("reload_requested", {}),
    };
    window.WasmAgentNative = window.wasmAgentNative;
    window.WasmAgentAndroidDiagnostics = { record };
  })();`;
}

async function evaluateVisibleState(page) {
  return page.evaluate((bannedTerms) => {
    function elementVisible(element) {
      if (!element) return false;
      let current = element.nodeType === Node.ELEMENT_NODE ? element : element.parentElement;
      while (current && current.nodeType === Node.ELEMENT_NODE) {
        if (current.hidden || current.getAttribute("aria-hidden") === "true") return false;
        const style = window.getComputedStyle(current);
        if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
        current = current.parentElement;
      }
      const owner = element.nodeType === Node.ELEMENT_NODE ? element : element.parentElement;
      if (!owner) return false;
      return Boolean(owner.getClientRects().length);
    }
    function elementState(selector) {
      const element = document.querySelector(selector);
      return {
        exists: Boolean(element),
        hiddenAttr: Boolean(element?.hidden),
        visible: elementVisible(element),
        text: element?.innerText || element?.textContent || "",
      };
    }
    function visibleText() {
      const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
      const parts = [];
      while (walker.nextNode()) {
        const node = walker.currentNode;
        const text = String(node.nodeValue || "").replace(/\s+/g, " ").trim();
        if (!text) continue;
        if (elementVisible(node)) parts.push(text);
      }
      return parts.join(" ").replace(/\s+/g, " ").trim();
    }
    let frontierState = null;
    try {
      frontierState = typeof window.__wasmAgentFrontierState === "function"
        ? window.__wasmAgentFrontierState()
        : null;
    } catch (error) {
      frontierState = { error: String(error?.message || error) };
    }
    let shellInfo = null;
    try {
      shellInfo = window.wasmAgentAndroid?.shellInfo ? JSON.parse(window.wasmAgentAndroid.shellInfo()) : null;
    } catch {
      shellInfo = null;
    }
    const text = visibleText();
    const lower = text.toLowerCase();
    return {
      href: window.location.href,
      title: document.title,
      readyState: document.readyState,
      hasApp: Boolean(document.querySelector("#app")),
      htmlNativeShell: document.documentElement.dataset.nativeShell || "",
      appNativeShell: document.querySelector("#app")?.dataset.nativeShell || "",
      appAuth: document.querySelector("#app")?.dataset.auth || "",
      appPanel: document.querySelector("#app")?.dataset.panel || "",
      visibleTextLength: text.length,
      visibleTextSample: text.slice(0, 4000),
      bannedVisibleTerms: bannedTerms.filter((term) => lower.includes(String(term).toLowerCase())),
      homeGoNativeButton: elementState("#homeGoNativeButton"),
      nativeModal: elementState("#nativeModal"),
      nativeDownloadButton: elementState("#nativeDownloadButton"),
      diagnosticsHookExists: typeof window.__wasmAgentFrontierState === "function",
      simBridgeInstalled: Boolean(window.wasmAgentAndroid?.shellInfo),
      diagnostics: Array.isArray(window.__wasmAgentSimDiagnostics) ? window.__wasmAgentSimDiagnostics.slice(-50) : [],
      frontierState,
      shellInfo,
    };
  }, BANNED_VISIBLE_TERMS);
}

function diagnosticConfirmsAndroid(observed) {
  return (observed.diagnostics || []).some((entry) => {
    const payload = entry?.payload || {};
    const shell = payload.shell || payload.native_shell || {};
    return ANDROID_SHELL_PROOF_KINDS.includes(entry?.kind)
      && (shell.isAndroidNativeShell === true || shell.shell === "android-webview" || shell.platform === "android");
  });
}

function appReadyDiagnosticExists(observed) {
  return (observed.diagnostics || []).some((entry) => entry.kind === "app_ready");
}

function freeTcpPort(host = "127.0.0.1") {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.on("error", reject);
    server.listen(0, host, () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close((error) => {
        if (error) reject(error);
        else resolve(port);
      });
    });
  });
}

function createResponsesStubServer(options = {}) {
  const requests = [];
  const usages = Array.isArray(options.usages) && options.usages.length
    ? options.usages
    : [options.usage || { input_tokens: 123, output_tokens: 45, total_tokens: 168 }];
  const answers = Array.isArray(options.answers) && options.answers.length
    ? options.answers
    : [options.answer || "Avatar quest simulator reply."];
  const server = http.createServer((req, res) => {
    if (req.method !== "POST" || !String(req.url || "").startsWith("/responses")) {
      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "not_found" }));
      return;
    }
    let body = "";
    req.setEncoding("utf8");
    req.on("data", (chunk) => {
      body += chunk;
    });
    req.on("end", () => {
      let payload = {};
      try {
        payload = body ? JSON.parse(body) : {};
      } catch {
        payload = {};
      }
      const requestIndex = requests.length;
      const usage = usages[Math.min(requestIndex, usages.length - 1)];
      const answer = answers[Math.min(requestIndex, answers.length - 1)];
      const reply = JSON.stringify({
        answer,
        decision: "answer",
        actions: [],
        state_delta: {},
        needs: [],
        proof_requests: ["route-used:/agent/provider/envelope/stream"],
        confidence: 0.99,
      });
      requests.push({
        path: req.url,
        authorization: req.headers.authorization || "",
        content_type: req.headers["content-type"] || "",
        payload,
      });
      const events = [
        { type: "response.output_text.delta", delta: reply },
        {
          type: "response.completed",
          response: {
            id: "resp_avatar_quest_sim",
            status: "completed",
            usage,
            output: [],
          },
        },
      ];
      const data = `${events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("")}data: [DONE]\n\n`;
      res.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Content-Length": Buffer.byteLength(data),
      });
      res.end(data);
    });
  });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      resolve({
        server,
        requests,
        usage: usages[0],
        usages,
        answer: answers[0],
        answers,
        baseUrl: `http://127.0.0.1:${port}`,
        close: () => new Promise((done) => server.close(() => done())),
      });
    });
  });
}

function writeAvatarQuestEnv(envPath, stubBaseUrl) {
  fs.mkdirSync(path.dirname(envPath), { recursive: true });
  const lines = [
    "ADMIN_EMAIL=simulator@wasm-agent.local",
    "USER_EMAILS=simulator@wasm-agent.local",
    "GOOGLE_LOGIN_CLIENT_ID=simulator-client-id",
    "WASM_AGENT_MASTER_FRONTIER_RECEIVER=openai-responses",
    `WASM_AGENT_OPENAI_BASE_URL=${stubBaseUrl}`,
    "WASM_AGENT_OPENAI_API_KEY=simulator-key",
    "WASM_AGENT_OPENAI_MODEL=gpt-5.5-sim",
  ];
  fs.writeFileSync(envPath, `${lines.join("\n")}\n`, "utf8");
}

function withTemporaryProcessEnv(env, fn) {
  const previous = {};
  for (const key of Object.keys(env)) {
    previous[key] = Object.prototype.hasOwnProperty.call(process.env, key) ? process.env[key] : undefined;
    process.env[key] = env[key];
  }
  const restore = () => {
    for (const key of Object.keys(env)) {
      if (previous[key] === undefined) delete process.env[key];
      else process.env[key] = previous[key];
    }
  };
  try {
    const result = fn();
    if (result && typeof result.then === "function") return result.finally(restore);
    restore();
    return result;
  } catch (error) {
    restore();
    throw error;
  }
}

async function waitForReachable(url, timeoutMs = 15000) {
  const started = Date.now();
  let latest = null;
  while (Date.now() - started < timeoutMs) {
    latest = await checkReachable(url);
    if (latest.ok) return latest;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  return latest || { ok: false, status: 0, error: "timeout", url };
}

function startIsolatedWasmAgentServer({ port, env, ctx }) {
  const child = spawn("python3", [
    path.join(REPO_ROOT, "plugins", "wasm-agent", "server", "static_server.py"),
    "--host",
    "127.0.0.1",
    "--port",
    String(port),
    "--bridge-url",
    "http://127.0.0.1:8790",
  ], {
    cwd: REPO_ROOT,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const stdout = [];
  const stderr = [];
  child.stdout.on("data", (chunk) => {
    stdout.push(String(chunk));
  });
  child.stderr.on("data", (chunk) => {
    stderr.push(String(chunk));
  });
  const close = () => new Promise((resolve) => {
    if (child.exitCode !== null || child.signalCode) {
      resolve();
      return;
    }
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      resolve();
    }, 3000);
    child.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
    child.kill("SIGTERM");
  });
  return {
    child,
    stdout,
    stderr,
    close,
    writeLogs() {
      ctx.writeTextArtifact("serverStdout", "logs/static-server-stdout.log", stdout.join(""));
      ctx.writeTextArtifact("serverStderr", "logs/static-server-stderr.log", stderr.join(""));
    },
  };
}

async function prepareAvatarQuestRuntime(ctx, stub) {
  const runtimeRoot = ctx.artifactPath("runtime");
  fs.mkdirSync(runtimeRoot, { recursive: true });
  const envPath = path.join(runtimeRoot, "wa.env");
  const stateDir = path.join(runtimeRoot, "state");
  const dbPath = path.join(runtimeRoot, "wa.sqlite3");
  const secretPath = path.join(runtimeRoot, "wa_auth_secret");
  writeAvatarQuestEnv(envPath, stub.baseUrl);
  const port = await freeTcpPort();
  const env = {
    ...process.env,
    HERMES_WASM_AGENT_DEPLOYMENT_MODE: "local",
    HERMES_WASM_AGENT_ENV_PATH: envPath,
    HERMES_WASM_AGENT_STATE_DIR: stateDir,
    HERMES_WASM_AGENT_DB_PATH: dbPath,
    HERMES_WASM_AGENT_AUTH_SECRET_PATH: secretPath,
    HERMES_WASM_AGENT_HOST: "127.0.0.1",
    HERMES_WASM_AGENT_PORT: String(port),
    WASM_AGENT_MASTER_FRONTIER_RECEIVER: "openai-responses",
    WASM_AGENT_OPENAI_BASE_URL: stub.baseUrl,
    WASM_AGENT_OPENAI_API_KEY: "simulator-key",
    WASM_AGENT_OPENAI_MODEL: "gpt-5.5-sim",
    WASM_AGENT_SIM_USER_EMAIL: "simulator@wasm-agent.local",
  };
  const server = startIsolatedWasmAgentServer({ port, env, ctx });
  const targetUrl = withAndroidShellQuery(`http://127.0.0.1:${port}/home?chat=wasm-agent-chat`);
  const reachable = await waitForReachable(targetUrl, Number(process.env.WASM_AGENT_SIM_SERVER_TIMEOUT_MS || 15000));
  if (!reachable.ok) {
    server.writeLogs();
    await server.close();
    throw new Error(`isolated wasm-agent server did not become reachable: ${reachable.error || `HTTP ${reachable.status}`}`);
  }
  return {
    env,
    server,
    targetUrl,
    inputUrl: `http://127.0.0.1:${port}/home?chat=wasm-agent-chat`,
    port,
    runtimeRoot,
    reachable,
  };
}

async function addSimulatorAuthCookie(context, targetUrl, env, ctx) {
  const simulatorAuth = await withTemporaryProcessEnv(env, () => ensureSimulatorAuthUser());
  ctx.result.evidence.simulatorUser = redactValue(simulatorAuthEvidence(simulatorAuth));
  ctx.addAssertion(
    "simulator auth user",
    simulatorAuth.enabled === false || simulatorAuth.ok === true,
    simulatorAuth.ok ? `ready${simulatorAuth.role ? ` role=${simulatorAuth.role}` : ""}` : `${simulatorAuth.reason || "unavailable"}`,
    simulatorAuthEvidence(simulatorAuth),
  );
  if (simulatorAuth?.ok && simulatorAuth.cookie) {
    const cookieUrl = new URL(targetUrl);
    await context.addCookies([{
      name: "wa_uid",
      value: simulatorAuth.cookie,
      url: cookieUrl.origin,
      httpOnly: true,
      sameSite: "Lax",
      secure: cookieUrl.protocol === "https:",
    }]);
  }
  return simulatorAuth;
}

async function collectAvatarQuestProof(page, expectedUsages) {
  return page.evaluate(async ({ expectedUsages }) => {
    function clean(value) {
      return String(value || "").trim();
    }
    function callSummary(call = {}) {
      return {
        provider_call_id: clean(call.provider_call_id),
        quest_id: clean(call.quest_id),
        run_id: clean(call.run_id),
        turn_id: clean(call.turn_id),
        route_id: clean(call.route_id),
        input_tokens: Number(call.input_tokens || 0),
        output_tokens: Number(call.output_tokens || 0),
        total_tokens: Number(call.total_tokens || 0),
        estimated_input_tokens: Number(call.estimated_input_tokens || 0),
        estimated_output_tokens: Number(call.estimated_output_tokens || 0),
        estimated_total_tokens: Number(call.estimated_total_tokens || 0),
        exact: call.exact !== false,
      };
    }
    function ledgerSummary(ledger = {}) {
      const calls = Array.isArray(ledger.calls) ? ledger.calls : [];
      const turns = Array.isArray(ledger.turns) ? ledger.turns : [];
      return {
        exact: ledger.exact !== false,
        provider_call_count: Number(ledger.provider_call_count || calls.length || 0),
        exact_provider_call_count: Number(ledger.exact_provider_call_count || 0),
        turn_count: Number(ledger.turn_count || turns.length || 0),
        total_tokens: Number(ledger.total_tokens || 0),
        input_tokens: Number(ledger.input_tokens || 0),
        output_tokens: Number(ledger.output_tokens || 0),
        estimated_total_tokens: Number(ledger.estimated_total_tokens || 0),
        estimated_input_tokens: Number(ledger.estimated_input_tokens || 0),
        estimated_output_tokens: Number(ledger.estimated_output_tokens || 0),
        quest_id: clean(ledger.quest_id),
        run_id: clean(ledger.run_id),
        turn_id: clean(ledger.turn_id),
        calls: calls.map(callSummary),
        turns: turns.map((turn) => {
          const providerCalls = Array.isArray(turn.provider_calls)
            ? turn.provider_calls
            : Array.isArray(turn.calls) ? turn.calls : [];
          return {
            exact: turn.exact !== false,
            provider_call_count: Number(turn.provider_call_count || providerCalls.length || 0),
            exact_provider_call_count: Number(turn.exact_provider_call_count || 0),
            total_tokens: Number(turn.total_tokens || 0),
            input_tokens: Number(turn.input_tokens || 0),
            output_tokens: Number(turn.output_tokens || 0),
            estimated_total_tokens: Number(turn.estimated_total_tokens || 0),
            estimated_input_tokens: Number(turn.estimated_input_tokens || 0),
            estimated_output_tokens: Number(turn.estimated_output_tokens || 0),
            quest_id: clean(turn.quest_id),
            run_id: clean(turn.run_id),
            turn_id: clean(turn.turn_id),
            run_ids: Array.isArray(turn.run_ids) ? turn.run_ids.map(clean).filter(Boolean) : [],
            provider_calls: providerCalls.map(callSummary),
          };
        }),
      };
    }
    function elementVisible(element) {
      if (!element) return false;
      let current = element.nodeType === Node.ELEMENT_NODE ? element : element.parentElement;
      while (current && current.nodeType === Node.ELEMENT_NODE) {
        if (current.hidden || current.getAttribute("aria-hidden") === "true") return false;
        const style = window.getComputedStyle(current);
        if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
        current = current.parentElement;
      }
      const owner = element.nodeType === Node.ELEMENT_NODE ? element : element.parentElement;
      return Boolean(owner?.getClientRects?.().length);
    }
    function readSessions() {
      try {
        return JSON.parse(localStorage.getItem("wasmAgent.agentSessions.v1") || "[]");
      } catch {
        return [];
      }
    }
    async function fetchJson(path, options = {}) {
      const response = await fetch(path, {
        method: options.method || "GET",
        credentials: "include",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: options.body ? JSON.stringify(options.body) : undefined,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload.ok === false) {
        throw new Error(payload?.error?.message || `HTTP ${response.status}`);
      }
      return payload;
    }
    function containment(selector) {
      const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
      const items = Array.from(document.querySelectorAll(selector)).map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          selector,
          visible: elementVisible(element),
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          width: Math.round(rect.width),
          within: rect.left >= -1 && rect.right <= viewportWidth + 1,
          text: clean(element.textContent).slice(0, 160),
        };
      });
      return {
        selector,
        count: items.length,
        overflow: items.filter((item) => item.visible && !item.within),
        items: items.slice(-4),
      };
    }

    const sessions = readSessions();
    const session = sessions.find((item) => Array.isArray(item.messages) && item.messages.some((message) => message.role === "assistant" && message.run_id)) || sessions[0] || {};
    const messages = (Array.isArray(session.messages) ? session.messages : [])
      .filter((message) => message.role === "assistant" && message.run_id)
      .map((message) => ({ ...message, session_id: session.id || "" }));
    if (!messages.length) throw new Error("no completed assistant messages with run_id");
    const runs = [];
    for (const message of messages) {
      const runPayload = await fetchJson(`/agent/runs/${encodeURIComponent(message.run_id)}`);
      const eventPayload = await fetchJson(`/agent/runs/${encodeURIComponent(message.run_id)}/events?limit=120`);
      const runCostPayload = await fetchJson("/agent/tools/cost.status", {
        method: "POST",
        body: {
          run_id: message.run_id,
          exact_only: true,
        },
      });
      const events = Array.isArray(eventPayload.events) ? eventPayload.events : [];
      const eventTypes = events.map((event) => clean(event.type));
      const routeIndex = eventTypes.indexOf("route.resolved");
      const headIndex = eventTypes.indexOf("head.started");
      const hermesIndex = eventTypes.indexOf("hermes.dispatch");
      runs.push({
        run_id: message.run_id,
        turn_id: clean(message.turn_id),
        session_id: clean(message.session_id),
        status: clean(runPayload.run?.status),
        route_id: clean(runPayload.run?.route_id || runPayload.run?.final?.route_id || ""),
        token_ledger_total: Number(runPayload.run?.token_ledger?.total_tokens || 0),
        eventTypes,
        routeBeforeProvider: routeIndex >= 0 && (headIndex < 0 || routeIndex < headIndex) && (hermesIndex < 0 || routeIndex < hermesIndex),
        hermesDispatchSeen: hermesIndex >= 0,
        ledger: ledgerSummary(runCostPayload.ledger || {}),
      });
    }
    const questId = clean(messages[0]?.session_id || session.id || "");
    const questCostPayload = await fetchJson("/agent/tools/cost.status", {
      method: "POST",
      body: {
        quest_id: questId,
      },
    });
    const exactQuestCostPayload = await fetchJson("/agent/tools/cost.status", {
      method: "POST",
      body: {
        quest_id: questId,
        exact_only: true,
      },
    });
    const turnLedgers = [];
    for (const message of messages) {
      const turnCostPayload = await fetchJson("/agent/tools/cost.status", {
        method: "POST",
        body: {
          quest_id: questId,
          turn_id: message.turn_id || "",
          exact_only: true,
        },
      });
      turnLedgers.push(ledgerSummary(turnCostPayload.ledger || {}));
    }
    return {
      href: window.location.href,
      appAuth: document.querySelector("#app")?.dataset.auth || "",
      selectedTarget: document.querySelector("#agentNodeSelect")?.value || "",
      run_id: runs[runs.length - 1]?.run_id || "",
      turn_id: runs[runs.length - 1]?.turn_id || "",
      session_id: questId,
      messages: messages.map((message) => ({
        run_id: clean(message.run_id),
        turn_id: clean(message.turn_id),
        pending: Boolean(message.pending),
        status: clean(message.agent_run_status),
        content: clean(message.content).slice(0, 400),
        timeline_count: Array.isArray(message.timeline) ? message.timeline.length : 0,
        has_token_ledger: Boolean(message.token_ledger || message.diagnostics?.token_ledger),
      })),
      runs,
      questLedger: ledgerSummary(questCostPayload.ledger || {}),
      exactQuestLedger: ledgerSummary(exactQuestCostPayload.ledger || {}),
      turnLedgers,
      expectedUsages,
      dom: {
        timeline: containment(".agent-message.assistant:last-of-type .agent-timeline, .agent-timeline"),
        tokenLedger: containment(".agent-message.assistant:last-of-type .agent-token-ledger, .agent-token-ledger"),
        documentScrollWidth: document.documentElement.scrollWidth,
        viewportWidth: document.documentElement.clientWidth || window.innerWidth,
      },
    };
  }, { expectedUsages });
}

async function runAvatarQuestSimulation(options = {}) {
  const ctx = new SimulationContext({
    platform: "avatar-quest",
    command: options.command || "horc simulate web --avatar-quest",
    engine: {
      name: "playwright",
      package: "",
      browser: "chromium",
    },
  });

  let stub = null;
  let runtime = null;
  let browser = null;
  let context = null;
  let page = null;
  let traceStarted = false;
  let currentPhase = "boot";
  const consoleLogs = [];
  const networkFailures = [];
  const prompts = [
    process.env.WASM_AGENT_SIM_AVATAR_QUEST_PROMPT || "avatar-chat quest proof turn one: answer directly with route and token proof only.",
    process.env.WASM_AGENT_SIM_AVATAR_QUEST_PROMPT_2 || "avatar-chat quest proof turn two: answer directly and keep the ledger exact.",
  ];
  const expectedUsages = [
    { input_tokens: 123, output_tokens: 45, total_tokens: 168 },
    { input_tokens: 200, output_tokens: 60, total_tokens: 260 },
  ];
  const expectedTotals = expectedUsages.reduce((total, usage) => ({
    input_tokens: total.input_tokens + usage.input_tokens,
    output_tokens: total.output_tokens + usage.output_tokens,
    total_tokens: total.total_tokens + usage.total_tokens,
  }), { input_tokens: 0, output_tokens: 0, total_tokens: 0 });

  try {
    ctx.startPhase("boot", "start isolated server and provider stub");
    stub = await createResponsesStubServer({
      answers: [
        "Avatar quest simulator completed turn one through the real avatar-chat UI.",
        "Avatar quest simulator completed turn two through the real avatar-chat UI.",
      ],
      usages: expectedUsages,
    });
    runtime = await prepareAvatarQuestRuntime(ctx, stub);
    ctx.result.target = {
      inputUrl: runtime.inputUrl,
      url: runtime.targetUrl,
      mode: "isolated-avatar-quest",
      port: runtime.port,
      providerStub: { baseUrl: stub.baseUrl },
    };
    ctx.addAssertion("isolated target reachable", runtime.reachable.ok, `HTTP ${runtime.reachable.status}`, runtime.reachable);

    const { source, module: playwright } = loadPlaywright();
    const executablePath = chromiumExecutablePath();
    ctx.result.engine.package = source;
    ctx.result.engine.executablePath = executablePath || "playwright-managed";
    const launchOptions = {
      headless: process.env.WASM_AGENT_SIM_HEADED === "1" ? false : true,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    };
    if (executablePath) launchOptions.executablePath = executablePath;
    browser = await playwright.chromium.launch(launchOptions);
    context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
      userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP2A.240805.005; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/126.0.0.0 Mobile Safari/537.36 wasm-agent-playwright-sim",
    });
    await addSimulatorAuthCookie(context, runtime.targetUrl, runtime.env, ctx);
    await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
    traceStarted = true;
    await context.addInitScript(androidBridgeInitScript());
    await context.addInitScript(() => {
      try {
        window.sessionStorage.setItem("wasmAgent.agentTargetNode.session.v1", "__target:master_frontier__");
      } catch {}
    });
    page = await context.newPage();
    page.on("console", (message) => consoleLogs.push(consoleEntry(message)));
    page.on("pageerror", (error) => {
      consoleLogs.push({
        type: "pageerror",
        text: redactString(error.message || String(error)),
        stack: redactString(error.stack || ""),
      });
    });
    page.on("requestfailed", (requestItem) => networkFailures.push(requestFailureEntry(requestItem)));
    page.on("response", (response) => {
      if (response.status() >= 500) networkFailures.push(responseFailureEntry(response));
    });
    ctx.completePhase("boot", "passed", "isolated runtime ready");

    currentPhase = "observe";
    ctx.startPhase("observe", "load authenticated avatar-chat shell");
    await page.goto(runtime.targetUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForSelector("#app", { state: "attached", timeout: 15000 });
    await page.waitForFunction(() => document.querySelector("#app")?.dataset.auth === "ready", null, { timeout: 15000 });
    await page.waitForSelector("#agentInput", { state: "visible", timeout: 15000 });
    await page.waitForFunction(() => Boolean(document.querySelector('#agentNodeSelect option[value="__target:master_frontier__"]')), null, { timeout: 10000 });
    await page.evaluate(() => {
      const select = document.querySelector("#agentNodeSelect");
      select.value = "__target:master_frontier__";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await page.waitForFunction(() => window.__wasmAgentFrontierState?.().agentNodeSelect?.master_frontier_selected === true, null, { timeout: 10000 });
    const observed = await evaluateVisibleState(page);
    ctx.result.evidence.observations = redactValue(observed);
    ctx.addAssertion("authenticated avatar-chat loaded", observed.appAuth === "ready" && observed.frontierState?.authenticated === true, `appAuth=${observed.appAuth}`);
    ctx.addAssertion("Master:frontier selected", observed.frontierState?.agentNodeSelect?.master_frontier_selected === true, "selected direct head", observed.frontierState?.agentNodeSelect);
    ctx.completePhase("observe", "passed", "authenticated avatar-chat ready");

    currentPhase = "act";
    ctx.startPhase("act", "submit two real avatar-chat quest turns");
    for (let index = 0; index < prompts.length; index += 1) {
      await page.fill("#agentInput", prompts[index]);
      await page.press("#agentInput", "Enter");
      await page.waitForFunction((expectedCount) => {
        let sessions = [];
        try {
          sessions = JSON.parse(localStorage.getItem("wasmAgent.agentSessions.v1") || "[]");
        } catch {
          sessions = [];
        }
        const messages = sessions.flatMap((session) => Array.isArray(session.messages) ? session.messages : []);
        const completed = messages.filter((message) => (
          message.role === "assistant"
          && message.run_id
          && !message.pending
          && message.agent_run_status === "completed"
          && (message.token_ledger || message.diagnostics?.token_ledger)
        ));
        return completed.length >= expectedCount;
      }, index + 1, { timeout: Number(process.env.WASM_AGENT_SIM_AVATAR_QUEST_TIMEOUT_MS || 30000) });
    }
    ctx.completePhase("act", "passed", "two avatar-chat quest turns completed");

    currentPhase = "assert";
    ctx.startPhase("assert", "verify kernel proof gate and quest ledger history");
    const proof = await collectAvatarQuestProof(page, expectedUsages);
    ctx.result.evidence.quest = redactValue(proof);
    ctx.result.evidence.providerStub = redactValue({
      requestCount: stub.requests.length,
      paths: stub.requests.map((requestItem) => requestItem.path),
      payloadKeys: stub.requests.map((requestItem) => Object.keys(requestItem.payload || {}).sort()),
    });
    const questTurns = Array.isArray(proof.questLedger?.turns) ? proof.questLedger.turns : [];
    const allProviderCalls = questTurns.flatMap((turn) => Array.isArray(turn.provider_calls) ? turn.provider_calls : []);
    ctx.addAssertion("real UI submitted exactly two provider calls", stub.requests.length === 2, `${stub.requests.length} calls`, ctx.result.evidence.providerStub);
    ctx.addAssertion(
      "route.resolved before provider dispatch on every turn",
      proof.runs.length === 2 && proof.runs.every((run) => run.routeBeforeProvider),
      proof.runs.map((run) => `${run.turn_id}: ${run.eventTypes.join(" > ")}`).join(" | "),
    );
    ctx.addAssertion(
      "no Hermes broad fallback",
      proof.runs.every((run) => run.hermesDispatchSeen === false),
      proof.runs.some((run) => run.hermesDispatchSeen) ? "hermes.dispatch appeared" : "no hermes.dispatch event",
    );
    ctx.addAssertion(
      "exact quest token ledger persisted",
      proof.questLedger.exact
        && proof.questLedger.provider_call_count === 2
        && proof.questLedger.turn_count === 2
        && proof.questLedger.input_tokens === expectedTotals.input_tokens
        && proof.questLedger.output_tokens === expectedTotals.output_tokens
        && proof.questLedger.total_tokens === expectedTotals.total_tokens,
      `in=${proof.questLedger.input_tokens} out=${proof.questLedger.output_tokens} total=${proof.questLedger.total_tokens}`,
    );
    ctx.addAssertion(
      "each turn has exact input output total",
      questTurns.length === 2 && questTurns.every((turn, index) => (
        turn.exact
        && turn.input_tokens === expectedUsages[index].input_tokens
        && turn.output_tokens === expectedUsages[index].output_tokens
        && turn.total_tokens === expectedUsages[index].total_tokens
      )),
      JSON.stringify(questTurns.map((turn) => ({ turn_id: turn.turn_id, input_tokens: turn.input_tokens, output_tokens: turn.output_tokens, total_tokens: turn.total_tokens }))),
    );
    ctx.addAssertion(
      "quest aggregate equals sum of turns",
      proof.questLedger.input_tokens === questTurns.reduce((total, turn) => total + turn.input_tokens, 0)
        && proof.questLedger.output_tokens === questTurns.reduce((total, turn) => total + turn.output_tokens, 0)
        && proof.questLedger.total_tokens === questTurns.reduce((total, turn) => total + turn.total_tokens, 0),
      `quest=${proof.questLedger.input_tokens}/${proof.questLedger.output_tokens}/${proof.questLedger.total_tokens}`,
    );
    ctx.addAssertion(
      "provider calls have ids and avatar-chat route",
      allProviderCalls.length === 2 && allProviderCalls.every((call) => call.provider_call_id && call.route_id === "wasm-agent.avatar-chat.ui"),
      JSON.stringify(allProviderCalls.map((call) => ({ provider_call_id: call.provider_call_id, route_id: call.route_id }))),
    );
    ctx.addAssertion(
      "turn and exact filters return one exact turn each",
      proof.turnLedgers.length === 2
        && proof.turnLedgers.every((ledger, index) => (
          ledger.exact
          && ledger.turn_count === 1
          && ledger.provider_call_count === 1
          && ledger.total_tokens === expectedUsages[index].total_tokens
        ))
        && proof.exactQuestLedger.provider_call_count === 2,
      JSON.stringify(proof.turnLedgers.map((ledger) => ({ turn_id: ledger.turn_id, total_tokens: ledger.total_tokens, provider_call_count: ledger.provider_call_count }))),
    );
    ctx.addAssertion("timeline UI is contained", proof.dom.timeline.count > 0 && proof.dom.timeline.overflow.length === 0 && proof.dom.documentScrollWidth <= proof.dom.viewportWidth + 1, `scroll=${proof.dom.documentScrollWidth}/${proof.dom.viewportWidth}`, proof.dom.timeline);
    ctx.addAssertion(
      "token ledger UI is contained and shows turn history",
      proof.dom.tokenLedger.count > 0
        && proof.dom.tokenLedger.overflow.length === 0
        && proof.dom.documentScrollWidth <= proof.dom.viewportWidth + 1
        && proof.dom.tokenLedger.items.some((item) => /2 turns/.test(item.text)),
      `scroll=${proof.dom.documentScrollWidth}/${proof.dom.viewportWidth}`,
      proof.dom.tokenLedger,
    );
    const missingRoute = await page.evaluate(async () => {
      const response = await fetch("/agent/tools/route.resolve", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ objective: "Fix the agent timeline and token report UI." }),
      });
      return response.json();
    });
    ctx.result.evidence.objectiveOnlyRoute = redactValue(missingRoute);
    ctx.addAssertion("objective-only route fails", missingRoute?.ok === false && missingRoute?.error?.code === "route_contract_missing", missingRoute?.error?.code || "unexpected");
    ctx.completePhase("assert", ctx.result.assertions.some((assertion) => assertion.status === "failed") ? "failed" : "passed", "quest assertions evaluated");
  } catch (error) {
    ctx.addError(error, currentPhase);
    const phase = ctx.phase(currentPhase);
    if (phase && phase.status === "running") ctx.completePhase(currentPhase, "failed", error.message || String(error));
    if (!ctx.result.assertions.some((assertion) => assertion.status === "failed")) {
      ctx.addAssertion("simulation completed", false, error.message || String(error));
    }
  } finally {
    const preArtifactStatus = ctx.result.assertions.some((assertion) => assertion.status === "failed") || ctx.result.errors.length
      ? "failed"
      : "passed";
    currentPhase = "collect evidence";
    ctx.startPhase("collect evidence", "write screenshots and logs");
    if (page) {
      try {
        const screenshotPath = ctx.artifactPath("screenshots", "final.png");
        await page.screenshot({ path: screenshotPath, fullPage: true });
        ctx.addArtifact("screenshot", screenshotPath);
      } catch (error) {
        ctx.addError(error, "collect evidence");
      }
    }
    ctx.result.evidence.console = redactValue(consoleLogs);
    ctx.result.evidence.networkFailures = redactValue(networkFailures);
    ctx.writeJsonArtifact("console", "logs/console.json", consoleLogs);
    ctx.writeJsonArtifact("networkFailures", "logs/network-failures.json", networkFailures);
    if (runtime?.server) runtime.server.writeLogs();
    if (context && traceStarted) {
      try {
        if (preArtifactStatus === "failed") {
          const tracePath = ctx.artifactPath("traces", "trace.zip");
          await context.tracing.stop({ path: tracePath });
          ctx.addArtifact("trace", tracePath);
        } else {
          await context.tracing.stop();
        }
      } catch (error) {
        ctx.addError(error, "collect evidence");
      }
    }
    if (context) {
      try {
        await context.close();
      } catch (error) {
        ctx.addError(error, "collect evidence");
      }
    }
    if (browser) {
      try {
        await browser.close();
      } catch (error) {
        ctx.addError(error, "collect evidence");
      }
    }
    if (runtime?.server) await runtime.server.close();
    if (stub) await stub.close();
    ctx.completePhase("collect evidence", ctx.result.errors.some((error) => error.phase === "collect evidence") ? "failed" : "passed", "artifacts collected");

    currentPhase = "score";
    ctx.startPhase("score", "score assertions");
    ctx.score();
    ctx.completePhase("score", "passed", `status=${ctx.result.status} score=${ctx.result.score == null ? "n/a" : ctx.result.score}`);

    currentPhase = "report";
    ctx.startPhase("report", "write result.json and summary.md");
    ctx.report();
    ctx.completePhase("report", "passed", "reports written");
    ctx.report();
  }

  console.log(`horc simulate web --avatar-quest: ${ctx.result.status}${ctx.result.score == null ? "" : ` (${ctx.result.score}/100)`}`);
  console.log(`  report: ${ctx.reportDir}/summary.md`);
  return ctx.result;
}

async function runWebSimulation(options = {}) {
  const ctx = new SimulationContext({
    platform: "web",
    command: options.command || "horc simulate web",
    engine: {
      name: "playwright",
      package: "",
      browser: "chromium",
    },
  });

  let browser = null;
  let context = null;
  let page = null;
  let traceStarted = false;
  let currentPhase = "boot";
  const consoleLogs = [];
  const networkFailures = [];

  try {
    ctx.startPhase("boot", "resolve target and launch browser");
    const inputUrl = process.env.WASM_AGENT_SIM_URL || DEFAULT_WEB_URL;
    const targetUrl = withAndroidShellQuery(inputUrl);
    ctx.result.target = {
      inputUrl,
      url: targetUrl,
      defaulted: !process.env.WASM_AGENT_SIM_URL,
      mode: "android-shell-query",
      query: ANDROID_SHELL_QUERY,
    };

    const reachable = await checkReachable(targetUrl);
    ctx.addAssertion(
      "target reachable",
      reachable.ok,
      reachable.ok
        ? `HTTP ${reachable.status}`
        : `Could not reach ${targetUrl}. Start with horc space start or set WASM_AGENT_SIM_URL.`,
      reachable,
    );
    if (!reachable.ok) {
      throw new Error(`web simulation target is unreachable: ${reachable.error || `HTTP ${reachable.status}`}`);
    }

    const simulatorAuth = ensureSimulatorAuthUser();
    ctx.result.evidence.simulatorUser = redactValue(simulatorAuthEvidence(simulatorAuth));
    ctx.addAssertion(
      "simulator auth user",
      simulatorAuth.enabled === false || simulatorAuth.ok === true,
      simulatorAuth.ok
        ? `ready${simulatorAuth.role ? ` role=${simulatorAuth.role}` : ""}`
        : `${simulatorAuth.reason || "unavailable"}`,
      simulatorAuthEvidence(simulatorAuth),
    );

    const { source, module: playwright } = loadPlaywright();
    const executablePath = chromiumExecutablePath();
    const ffmpegPath = playwrightFfmpegExecutablePath();
    const recordVideoEnabled = Boolean(ffmpegPath);
    ctx.result.engine.package = source;
    ctx.result.engine.executablePath = executablePath || "playwright-managed";
    ctx.result.engine.video = recordVideoEnabled
      ? { enabled: true, ffmpegPath }
      : {
          enabled: false,
          reason: "Playwright ffmpeg is not installed; failure video skipped. Run `cd tools/app-simulator && npx playwright-core install ffmpeg` to enable it.",
        };
    const launchOptions = {
      headless: process.env.WASM_AGENT_SIM_HEADED === "1" ? false : true,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    };
    if (executablePath) launchOptions.executablePath = executablePath;
    browser = await playwright.chromium.launch(launchOptions);
    const contextOptions = {
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
      userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP2A.240805.005; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/126.0.0.0 Mobile Safari/537.36 wasm-agent-playwright-sim",
    };
    if (recordVideoEnabled) {
      contextOptions.recordVideo = {
        dir: ctx.artifactPath("videos"),
        size: { width: 390, height: 844 },
      };
    }
    context = await browser.newContext(contextOptions);
    if (simulatorAuth?.ok && simulatorAuth.cookie) {
      const cookieUrl = new URL(targetUrl);
      await context.addCookies([{
        name: "wa_uid",
        value: simulatorAuth.cookie,
        url: cookieUrl.origin,
        httpOnly: true,
        sameSite: "Lax",
        secure: cookieUrl.protocol === "https:",
      }]);
    }
    await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
    traceStarted = true;
    await context.addInitScript(androidBridgeInitScript());
    page = await context.newPage();
    page.on("console", (message) => consoleLogs.push(consoleEntry(message)));
    page.on("pageerror", (error) => {
      consoleLogs.push({
        type: "pageerror",
        text: redactString(error.message || String(error)),
        stack: redactString(error.stack || ""),
      });
    });
    page.on("requestfailed", (requestItem) => networkFailures.push(requestFailureEntry(requestItem)));
    page.on("response", (response) => {
      if (response.status() >= 500) networkFailures.push(responseFailureEntry(response));
    });
    ctx.completePhase("boot", "passed", "browser ready");

    currentPhase = "observe";
    ctx.startPhase("observe", "load PWA in Android WebView query mode");
    await page.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForSelector("#app", { state: "attached", timeout: 15000 });
    await page.waitForFunction(() => document.readyState === "interactive" || document.readyState === "complete", null, { timeout: 10000 });
    await page.waitForFunction(() => document.documentElement.dataset.nativeShell === "android", null, { timeout: 10000 });
    await page.waitForFunction((proofKinds) => (window.__wasmAgentSimDiagnostics || []).some((entry) => {
      const payload = entry?.payload || {};
      const shell = payload.shell || payload.native_shell || {};
      return proofKinds.includes(entry?.kind)
        && (payload.native_android_shell === true || shell.isAndroidNativeShell === true || shell.shell === "android-webview" || shell.platform === "android");
    }), ANDROID_SHELL_PROOF_KINDS, { timeout: 10000 });
    await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => {});
    ctx.completePhase("observe", "passed", "app loaded and shell signal observed");

    currentPhase = "act";
    ctx.startPhase("act", "exercise native shell event diagnostics");
    await page.evaluate(() => {
      window.dispatchEvent(new CustomEvent("wasm-agent:native-page-finished", {
        detail: { source: "playwright-sim", lifecycle: "act" },
      }));
    });
    await page.waitForFunction(() => (window.__wasmAgentSimDiagnostics || []).some((entry) => entry.kind === "native_page_finished"), null, { timeout: 5000 });
    ctx.completePhase("act", "passed", "native page-finished event captured");

    currentPhase = "assert";
    ctx.startPhase("assert", "check runtime guardrails");
    const observed = await evaluateVisibleState(page);
    ctx.result.evidence.observations = redactValue(observed);
    ctx.result.evidence.diagnostics = redactValue(observed.diagnostics || []);
    ctx.addAssertion(
      "app loads",
      observed.hasApp && ["interactive", "complete"].includes(observed.readyState),
      `readyState=${observed.readyState} hasApp=${observed.hasApp}`,
    );
    ctx.addAssertion(
      "Android native shell mode detected",
      observed.htmlNativeShell === "android" && observed.appNativeShell === "android",
      `html=${observed.htmlNativeShell || "unset"} app=${observed.appNativeShell || "unset"}`,
    );
    ctx.addAssertion(
      "home Native is visible without opening installer prompt",
      observed.homeGoNativeButton.visible && !observed.nativeModal.visible && !observed.nativeDownloadButton.visible,
      `homeGoNative visible=${observed.homeGoNativeButton.visible}; nativeModal visible=${observed.nativeModal.visible}; nativeDownload visible=${observed.nativeDownloadButton.visible}`,
    );
    if (ctx.result.evidence.simulatorUser?.ok) {
      ctx.addAssertion(
        "simulator user reached authenticated app",
        observed.appAuth === "ready",
        `appAuth=${observed.appAuth || "unset"}`,
      );
    }
    ctx.addAssertion(
      "visible UI excludes browser/native install leakage",
      observed.bannedVisibleTerms.length === 0,
      observed.bannedVisibleTerms.length ? `visible terms: ${observed.bannedVisibleTerms.join(", ")}` : "no banned visible terms",
      { visibleTextSample: observed.visibleTextSample },
    );
    ctx.addAssertion(
      "diagnostics hook/event/console confirms shell mode",
      observed.diagnosticsHookExists
        && observed.simBridgeInstalled
        && diagnosticConfirmsAndroid(observed)
        && appReadyDiagnosticExists(observed)
        && consoleLogs.some((entry) => /wasm-agent-sim:(android_native_shell_detected|app_ready|authenticated_ui_visible|first_screen_readiness)/.test(entry.text)),
      `frontierHook=${observed.diagnosticsHookExists} bridge=${observed.simBridgeInstalled} androidDiagnostic=${diagnosticConfirmsAndroid(observed)} appReady=${appReadyDiagnosticExists(observed)}`,
    );
    ctx.completePhase("assert", ctx.result.assertions.some((assertion) => assertion.status === "failed") ? "failed" : "passed", "assertions evaluated");
  } catch (error) {
    ctx.addError(error, currentPhase);
    const phase = ctx.phase(currentPhase);
    if (phase && phase.status === "running") ctx.completePhase(currentPhase, "failed", error.message || String(error));
    if (!ctx.result.assertions.some((assertion) => assertion.status === "failed")) {
      ctx.addAssertion("simulation completed", false, error.message || String(error));
    }
  } finally {
    const preArtifactStatus = ctx.result.assertions.some((assertion) => assertion.status === "failed") || ctx.result.errors.length
      ? "failed"
      : "passed";
    currentPhase = "collect evidence";
    ctx.startPhase("collect evidence", "write screenshots and logs");
    if (page) {
      try {
        const screenshotPath = ctx.artifactPath("screenshots", "final.png");
        await page.screenshot({ path: screenshotPath, fullPage: true });
        ctx.addArtifact("screenshot", screenshotPath);
      } catch (error) {
        ctx.addError(error, "collect evidence");
      }
    }
    ctx.result.evidence.console = redactValue(consoleLogs);
    ctx.result.evidence.networkFailures = redactValue(networkFailures);
    ctx.writeJsonArtifact("console", "logs/console.json", consoleLogs);
    ctx.writeJsonArtifact("networkFailures", "logs/network-failures.json", networkFailures);
    ctx.writeJsonArtifact("observations", "logs/observations.json", ctx.result.evidence.observations || {});

    if (context && traceStarted) {
      try {
        if (preArtifactStatus === "failed") {
          const tracePath = ctx.artifactPath("traces", "trace.zip");
          await context.tracing.stop({ path: tracePath });
          ctx.addArtifact("trace", tracePath);
        } else {
          await context.tracing.stop();
        }
      } catch (error) {
        ctx.addError(error, "collect evidence");
      }
    }

    let videoPath = "";
    try {
      if (page?.video) videoPath = await page.video()?.path();
    } catch {
      videoPath = "";
    }
    if (context) {
      try {
        await context.close();
      } catch (error) {
        ctx.addError(error, "collect evidence");
      }
    }
    if (browser) {
      try {
        await browser.close();
      } catch (error) {
        ctx.addError(error, "collect evidence");
      }
    }
    if (videoPath) {
      try {
        if (preArtifactStatus === "failed" && fs.existsSync(videoPath)) {
          const finalVideoPath = ctx.artifactPath("videos", "failure.webm");
          if (path.resolve(videoPath) !== path.resolve(finalVideoPath)) {
            fs.copyFileSync(videoPath, finalVideoPath);
            fs.rmSync(videoPath, { force: true });
          }
          ctx.addArtifact("video", finalVideoPath);
        } else if (fs.existsSync(videoPath)) {
          fs.rmSync(videoPath, { force: true });
        }
      } catch (error) {
        ctx.addError(error, "collect evidence");
      }
    }
    ctx.completePhase("collect evidence", ctx.result.errors.some((error) => error.phase === "collect evidence") ? "failed" : "passed", "artifacts collected");

    currentPhase = "score";
    ctx.startPhase("score", "score assertions");
    ctx.score();
    ctx.completePhase("score", "passed", `status=${ctx.result.status} score=${ctx.result.score == null ? "n/a" : ctx.result.score}`);

    currentPhase = "report";
    ctx.startPhase("report", "write result.json and summary.md");
    ctx.report();
    ctx.completePhase("report", "passed", "reports written");
    ctx.report();
  }

  console.log(`horc simulate web: ${ctx.result.status}${ctx.result.score == null ? "" : ` (${ctx.result.score}/100)`}`);
  console.log(`  report: ${ctx.reportDir}/summary.md`);
  if (ctx.result.status !== "passed") {
    console.log("  web simulation verifies PWA/browser behavior only; APK and Windows installed-app behavior remain unverified.");
  }
  return ctx.result;
}

module.exports = {
  ANDROID_SHELL_QUERY,
  BANNED_VISIBLE_TERMS,
  DEFAULT_WEB_URL,
  ensureSimulatorAuthUser,
  playwrightFfmpegExecutablePath,
  runAvatarQuestSimulation,
  runWebSimulation,
  simulatorAuthEvidence,
  withAndroidShellQuery,
};
