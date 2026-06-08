"use strict";

const fs = require("fs");
const path = require("path");
const { request } = require("http");
const { request: secureRequest } = require("https");
const { spawnSync } = require("child_process");
const { SimulationContext, redactString, redactValue } = require("./core");

const DEFAULT_WEB_URL = "http://127.0.0.1:8877/home";
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
    const shell = entry?.payload?.shell || entry?.payload?.native_shell || {};
    return entry.kind === "android_native_shell_detected"
      && (shell.isAndroidNativeShell === true || shell.shell === "android-webview" || shell.platform === "android");
  });
}

function appReadyDiagnosticExists(observed) {
  return (observed.diagnostics || []).some((entry) => entry.kind === "app_ready");
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
    await page.waitForFunction(() => (window.__wasmAgentSimDiagnostics || []).some((entry) => entry.kind === "android_native_shell_detected"), null, { timeout: 10000 });
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
        && consoleLogs.some((entry) => /wasm-agent-sim:android_native_shell_detected/.test(entry.text)),
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
  playwrightFfmpegExecutablePath,
  runWebSimulation,
  withAndroidShellQuery,
};
