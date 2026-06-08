"use strict";

const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const https = require("https");
const os = require("os");
const path = require("path");
const { spawn, spawnSync } = require("child_process");
const { SimulationContext, redactString, redactValue, repoRootFromCore } = require("./core");

const DEFAULT_ANDROID_APK = path.join(repoRootFromCore(), "native", "android", "release", "WASM-Agent-arm64.apk");
const DEFAULT_PACKAGE = "com.colmeio.wasmagent";
const DEFAULT_ACTIVITY = ".MainActivity";
const DEFAULT_WAIT_BOOT_MS = 60000;
const DEFAULT_WAIT_AFTER_TAP_MS = 18000;
const DEFAULT_WAIT_RETRY_MS = 18000;
const DEFAULT_OAUTH_WAIT_MS = 0;
const DEFAULT_ADB_TIMEOUT_MS = 15000;
const DEFAULT_EMULATOR_BOOT_MS = 120000;
const LOGIN_BUTTON_TEXT = "Sign in with Google";
const FORBIDDEN_EXTERNAL_AUTH_START = "wa.colmeio.com/native/android/auth/start";
const FORBIDDEN_EXTERNAL_HOME = "wa.colmeio.com/home";
const GOOGLE_ACCOUNTS_HOST = "accounts.google.com";
const STALE_OPENING_GOOGLE_SIGN_IN = "Opening Google sign-in...";
const FIXTURE_DIR = path.join(__dirname, "fixtures", "android");
const REQUIRED_ANDROID_PROOF_ASSERTIONS = [
  "first tap: no Android resolver chooser",
  "first tap: no external wasm-agent URL first",
  "first tap: opens Google OAuth/account screen",
  "OAuth completion redirects to native return",
  "package-targeted Android return intent fired",
  "MainActivity received native return intent",
  "post-auth returns to native app",
  "WebView becomes authenticated",
  "authenticated UI visible",
  "native diagnostics latest.json attached",
  "server correlation logs attached",
  "logcat excerpt attached",
  "cancel/return makes Google sign-in retryable",
  "retry tap does not stay stuck",
];
const REQUIRED_ANDROID_VOICE_ASSERTIONS = [
  "foreground service started",
  "microphone permission state known",
  "wake detected",
  "transcription produced",
  "voice_command event reached wasm-agent",
  "UI timeline shows event",
  "logs are redacted",
];

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function commandPath(commandName) {
  const result = spawnSync("bash", ["-lc", `command -v ${commandName}`], {
    encoding: "utf8",
  });
  if (result.status !== 0) return "";
  return String(result.stdout || "").trim().split("\n")[0] || "";
}

function unique(values) {
  return Array.from(new Set(values.filter(Boolean)));
}

function runCommand(command, args = [], options = {}) {
  const timeoutMs = Number(options.timeoutMs || DEFAULT_ADB_TIMEOUT_MS);
  const encoding = options.encoding === "buffer" ? "buffer" : "utf8";
  return new Promise((resolve) => {
    const startedAt = Date.now();
    const child = spawn(command, args, {
      cwd: options.cwd || repoRootFromCore(),
      env: options.env || process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const stdout = [];
    const stderr = [];
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
      setTimeout(() => child.kill("SIGKILL"), 1500).unref();
    }, timeoutMs);
    child.stdout.on("data", (chunk) => stdout.push(chunk));
    child.stderr.on("data", (chunk) => stderr.push(chunk));
    child.on("error", (error) => {
      clearTimeout(timer);
      resolve({
        command,
        args,
        status: -1,
        signal: "",
        timedOut,
        durationMs: Date.now() - startedAt,
        stdout: encoding === "buffer" ? Buffer.concat(stdout) : Buffer.concat(stdout).toString("utf8"),
        stderr: encoding === "buffer" ? Buffer.concat(stderr) : Buffer.concat(stderr).toString("utf8"),
        error: error.message,
      });
    });
    child.on("close", (status, signal) => {
      clearTimeout(timer);
      resolve({
        command,
        args,
        status: status == null ? -1 : status,
        signal: signal || "",
        timedOut,
        durationMs: Date.now() - startedAt,
        stdout: encoding === "buffer" ? Buffer.concat(stdout) : Buffer.concat(stdout).toString("utf8"),
        stderr: encoding === "buffer" ? Buffer.concat(stderr) : Buffer.concat(stderr).toString("utf8"),
      });
    });
  });
}

function fetchJsonUrl(url, options = {}) {
  const timeoutMs = Number(options.timeoutMs || 8000);
  return new Promise((resolve) => {
    let settled = false;
    const startedAt = Date.now();
    const client = String(url || "").startsWith("https:") ? https : http;
    const request = client.get(url, { timeout: timeoutMs, headers: { Accept: "application/json" } }, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("end", () => {
        if (settled) return;
        settled = true;
        const raw = Buffer.concat(chunks).toString("utf8");
        let payload = null;
        try {
          payload = raw ? JSON.parse(raw) : null;
        } catch (error) {
          resolve({
            ok: false,
            statusCode: response.statusCode || 0,
            durationMs: Date.now() - startedAt,
            raw: redactString(raw).slice(0, 2000),
            error: `invalid_json:${error.message}`,
          });
          return;
        }
        resolve({
          ok: response.statusCode >= 200 && response.statusCode < 300,
          statusCode: response.statusCode || 0,
          durationMs: Date.now() - startedAt,
          payload: redactValue(payload),
        });
      });
    });
    request.on("timeout", () => {
      request.destroy(new Error("timeout"));
    });
    request.on("error", (error) => {
      if (settled) return;
      settled = true;
      resolve({
        ok: false,
        statusCode: 0,
        durationMs: Date.now() - startedAt,
        error: redactString(error.message || String(error)),
      });
    });
  });
}

function resultText(result) {
  const stdout = Buffer.isBuffer(result.stdout) ? result.stdout.toString("utf8") : String(result.stdout || "");
  const stderr = Buffer.isBuffer(result.stderr) ? result.stderr.toString("utf8") : String(result.stderr || "");
  return `${stdout}\n${stderr}`.trim();
}

function compactCommandResult(result) {
  return redactValue({
    command: result.command,
    args: result.args,
    status: result.status,
    signal: result.signal,
    timedOut: result.timedOut,
    durationMs: result.durationMs,
    stdout: String(result.stdout || "").slice(0, 8000),
    stderr: String(result.stderr || "").slice(0, 8000),
    error: result.error || "",
  });
}

function candidateAdbPaths(rootDir = repoRootFromCore()) {
  const sdkRoots = unique([
    process.env.ANDROID_HOME,
    process.env.ANDROID_SDK_ROOT,
    path.join(rootDir, "native", "android", ".android-sdk"),
  ]);
  return unique([
    process.env.WASM_AGENT_SIM_ADB,
    process.env.ADB,
    commandPath("adb"),
    ...sdkRoots.map((root) => root && path.join(root, "platform-tools", process.platform === "win32" ? "adb.exe" : "adb")),
  ]);
}

async function testAdbInvocation(command, prefixArgs, displayPath, timeoutMs = 6000) {
  const result = await runCommand(command, [...prefixArgs, "version"], { timeoutMs });
  if (result.status === 0) {
    return {
      ok: true,
      adb: {
        command,
        prefixArgs,
        displayPath,
        version: redactString(resultText(result)),
      },
      result,
    };
  }
  return { ok: false, result };
}

async function resolveAdb(rootDir = repoRootFromCore()) {
  const attempts = [];
  for (const candidate of candidateAdbPaths(rootDir)) {
    if (candidate !== "adb" && !fs.existsSync(candidate)) continue;
    const direct = await testAdbInvocation(candidate, [], candidate);
    attempts.push({
      displayPath: candidate,
      status: direct.result.status,
      stderr: redactString(resultText(direct.result)).slice(0, 800),
    });
    if (direct.ok) return { available: true, ...direct.adb, attempts };

    const output = resultText(direct.result);
    const mayNeedQemu = /Exec format error|qemu-x86_64|ld-linux-x86-64|No such file or directory/i.test(output);
    if (mayNeedQemu) {
      const qemu = commandPath("qemu-x86_64");
      const sysroot = path.join(rootDir, "native", "android", ".android-sdk-qemu-root");
      if (qemu && fs.existsSync(sysroot)) {
        const wrapped = await testAdbInvocation(qemu, ["-L", sysroot, candidate], `${qemu} -L ${sysroot} ${candidate}`);
        attempts.push({
          displayPath: `${qemu} -L ${sysroot} ${candidate}`,
          status: wrapped.result.status,
          stderr: redactString(resultText(wrapped.result)).slice(0, 800),
        });
        if (wrapped.ok) return { available: true, ...wrapped.adb, wrapper: "qemu-x86_64", sysroot, attempts };
      } else {
        attempts.push({
          displayPath: `${candidate} via qemu-x86_64`,
          status: -1,
          stderr: "ADB appears to need qemu-x86_64, but qemu-x86_64 or the SDK sysroot is unavailable.",
        });
      }
    }
  }
  return {
    available: false,
    reason: "adb was not found or could not run",
    attempts,
  };
}

function adbArgs(adbInfo, args, serial = "") {
  const scoped = serial ? ["-s", serial, ...args] : args;
  return [...(adbInfo.prefixArgs || []), ...scoped];
}

function runAdb(adbInfo, args, options = {}) {
  return runCommand(adbInfo.command, adbArgs(adbInfo, args, options.serial || ""), {
    timeoutMs: options.timeoutMs || DEFAULT_ADB_TIMEOUT_MS,
    encoding: options.encoding,
  });
}

async function adbText(adbInfo, serial, args, options = {}) {
  const result = await runAdb(adbInfo, args, { ...options, serial });
  return {
    ...result,
    stdout: String(result.stdout || ""),
    stderr: String(result.stderr || ""),
  };
}

function parseDevices(output) {
  const lines = String(output || "").split(/\r?\n/).slice(1);
  return lines
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !line.startsWith("* "))
    .map((line) => {
      const [serial, state, ...detailParts] = line.split(/\s+/);
      return { serial, state, detail: detailParts.join(" ") };
    })
    .filter((device) => device.serial);
}

function androidDeviceKind(device) {
  const text = `${device.serial || ""} ${device.detail || ""}`.toLowerCase();
  if (/^emulator-\d+/.test(String(device.serial || "")) || /model:sdk_|model:.*emulator|device:generic/i.test(text)) {
    return "emulator";
  }
  return "device";
}

async function detectAdbDevice(rootDir = repoRootFromCore(), options = {}) {
  const adbInfo = await resolveAdb(rootDir);
  if (!adbInfo.available) {
    return { available: false, adb: adbInfo, reason: adbInfo.reason };
  }
  const devicesResult = await runAdb(adbInfo, ["devices", "-l"], { timeoutMs: 8000 });
  const requestedKind = options.kind || "any";
  const devices = parseDevices(resultText(devicesResult)).map((device) => ({
    ...device,
    kind: androidDeviceKind(device),
  }));
  const usable = devices
    .filter((device) => device.state === "device")
    .filter((device) => requestedKind === "any" || device.kind === requestedKind);
  const kindLabel = requestedKind === "any" ? "device/emulator" : requestedKind;
  return {
    available: usable.length > 0,
    adb: adbInfo,
    devices,
    selected: usable[0] || null,
    reason: usable.length ? "" : `no connected adb ${kindLabel} in device state`,
    devicesResult: compactCommandResult(devicesResult),
  };
}

function sha256File(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function loadJsonIfExists(filePath) {
  try {
    if (!fs.existsSync(filePath)) return null;
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return null;
  }
}

function loadApkMetadata(apkPath, rootDir = repoRootFromCore()) {
  const sidecar = loadJsonIfExists(apkPath.replace(/\.apk$/i, ".native-defaults.json"));
  const manifest = loadJsonIfExists(path.join(rootDir, "native", "android", "release", "release-manifest.json"));
  const basename = path.basename(apkPath);
  const manifestArtifact = (manifest?.artifacts || []).find((artifact) => path.basename(artifact.path || "") === basename) || null;
  const actualSha256 = fs.existsSync(apkPath) ? sha256File(apkPath) : "";
  return redactValue({
    path: apkPath,
    exists: fs.existsSync(apkPath),
    size: fs.existsSync(apkPath) ? fs.statSync(apkPath).size : 0,
    sha256: actualSha256,
    buildId: sidecar?.buildId || manifest?.buildId || "",
    version: sidecar?.installableVersion || manifest?.version || "",
    serverUrl: sidecar?.serverUrl || manifest?.serverUrl || "",
    allowLocalDev: sidecar?.allowLocalDev ?? manifest?.allowLocalDev ?? null,
    signingLevel: sidecar?.signingLevel || manifest?.signingLevel || "",
    expectedSha256: sidecar?.artifactSha256 || manifestArtifact?.sha256 || "",
    sha256MatchesMetadata: Boolean(actualSha256 && (sidecar?.artifactSha256 || manifestArtifact?.sha256))
      ? actualSha256 === (sidecar?.artifactSha256 || manifestArtifact?.sha256)
      : null,
  });
}

function decodeXmlEntities(value) {
  return String(value || "")
    .replace(/&quot;/g, "\"")
    .replace(/&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}

function parseBounds(value) {
  const match = String(value || "").match(/\[(\d+),(\d+)]\[(\d+),(\d+)]/);
  if (!match) return null;
  const [, left, top, right, bottom] = match.map(Number);
  return {
    left,
    top,
    right,
    bottom,
    centerX: Math.round((left + right) / 2),
    centerY: Math.round((top + bottom) / 2),
  };
}

function parseUiXml(xml) {
  const nodes = [];
  const nodeRegex = /<node\b([^>]*)>/g;
  let match;
  while ((match = nodeRegex.exec(String(xml || "")))) {
    const attrs = {};
    const attrRegex = /([A-Za-z0-9_:-]+)="([^"]*)"/g;
    let attrMatch;
    while ((attrMatch = attrRegex.exec(match[1]))) {
      attrs[attrMatch[1]] = decodeXmlEntities(attrMatch[2]);
    }
    const text = [attrs.text, attrs["content-desc"]].filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
    nodes.push({
      text,
      rawText: attrs.text || "",
      contentDescription: attrs["content-desc"] || "",
      className: attrs.class || "",
      packageName: attrs.package || "",
      resourceId: attrs["resource-id"] || "",
      clickable: attrs.clickable === "true",
      enabled: attrs.enabled !== "false",
      bounds: parseBounds(attrs.bounds),
    });
  }
  const visibleText = nodes
    .map((node) => node.text)
    .filter(Boolean)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
  return {
    nodes,
    visibleText,
    visibleTextSample: visibleText.slice(0, 4000),
  };
}

function findLoginButton(parsedUi) {
  const lowerNeedle = LOGIN_BUTTON_TEXT.toLowerCase();
  return (parsedUi.nodes || []).find((node) => {
    const text = String(node.text || "").toLowerCase();
    const resource = String(node.resourceId || "").toLowerCase();
    return node.enabled && node.bounds && (
      text.includes(lowerNeedle) ||
      resource.includes("google-signin") ||
      resource.includes("google_signin")
    );
  }) || null;
}

function latestNativeDiagnosticPayload(nativeDiagnostics = {}) {
  const payload = nativeDiagnostics?.payload || nativeDiagnostics || {};
  const nestedPayload = payload.payload && typeof payload.payload === "object" ? payload.payload : {};
  const hasNestedPayload = Object.keys(nestedPayload).length > 0;
  const snapshot = payload.snapshot
    || payload.diagnostics
    || payload.native_state
    || nestedPayload.snapshot
    || nestedPayload.diagnostics
    || nestedPayload.native_state
    || (hasNestedPayload ? nestedPayload : null)
    || payload;
  const webview = snapshot.webview || payload.webview || nestedPayload.webview || {};
  const renderer = webview.renderer_readiness?.payload
    || snapshot.renderer_readiness?.payload
    || payload.renderer_readiness?.payload
    || nestedPayload.renderer_readiness?.payload
    || payload.payload
    || {};
  const text = JSON.stringify(payload).slice(0, 250000);
  return { payload, snapshot, webview, renderer, text };
}

function finiteNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function boundsAroundPoint(x, y, width = 48, height = 48) {
  const centerX = Math.round(x);
  const centerY = Math.round(y);
  const halfWidth = Math.max(12, Math.round(width / 2));
  const halfHeight = Math.max(12, Math.round(height / 2));
  return {
    left: centerX - halfWidth,
    top: centerY - halfHeight,
    right: centerX + halfWidth,
    bottom: centerY + halfHeight,
    centerX,
    centerY,
  };
}

function rendererReadinessTapTarget(snapshot = {}) {
  const native = latestNativeDiagnosticPayload(snapshot.nativeDiagnostics || {});
  const target = native.renderer.google_signin_tap_target || {};
  const adbTarget = target.adb_tap_target || {};
  const adbX = finiteNumber(adbTarget.x);
  const adbY = finiteNumber(adbTarget.y);
  if (adbX !== null && adbY !== null) {
    return {
      source: "native_adb_tap_target",
      target,
      bounds: boundsAroundPoint(adbX, adbY, 56, 56),
    };
  }

  const rect = target.rect || {};
  const viewport = target.viewport || {};
  const metrics = target.native_webview_metrics || native.webview.metrics || {};
  const centerX = finiteNumber(rect.center_x);
  const centerY = finiteNumber(rect.center_y);
  const innerWidth = finiteNumber(viewport.inner_width);
  const innerHeight = finiteNumber(viewport.inner_height);
  const webViewWidth = finiteNumber(metrics.width_px);
  const webViewHeight = finiteNumber(metrics.height_px);
  if (
    centerX === null ||
    centerY === null ||
    !innerWidth ||
    !innerHeight ||
    !webViewWidth ||
    !webViewHeight
  ) {
    return null;
  }
  const screenX = finiteNumber(metrics.screen_x_px) || 0;
  const screenY = finiteNumber(metrics.screen_y_px) || 0;
  const physicalX = screenX + (centerX / innerWidth) * webViewWidth;
  const physicalY = screenY + (centerY / innerHeight) * webViewHeight;
  return {
    source: "computed_from_renderer_readiness",
    target,
    bounds: boundsAroundPoint(physicalX, physicalY, Number(rect.width || 56), Number(rect.height || 56)),
  };
}

function loginButtonFromRendererReadiness(snapshot = {}) {
  const native = latestNativeDiagnosticPayload(snapshot.nativeDiagnostics || {});
  const readinessVisible = native.renderer.login_screen_visible === true
    && native.renderer.google_signin_button_visible === true;
  if (!readinessVisible && !/"google_signin_button_visible"\s*:\s*true/i.test(native.text)) return null;
  const tapTarget = rendererReadinessTapTarget(snapshot);
  if (!tapTarget?.bounds) return null;
  return {
    text: LOGIN_BUTTON_TEXT,
    bounds: tapTarget.bounds,
    source: tapTarget.source,
    rendererTapTarget: tapTarget.target,
  };
}

function classifyFirstScreenState(snapshot = {}) {
  const native = latestNativeDiagnosticPayload(snapshot.nativeDiagnostics || {});
  const uiText = String(snapshot.uiText || "");
  const logcatText = String(snapshot.logcatText || "");
  const allText = `${uiText}\n${logcatText}\n${native.text}`;
  const loginVisible = Boolean(snapshot.loginButton)
    || native.renderer.login_screen_visible === true
    || /"login_screen_visible"\s*:\s*true/i.test(native.text);
  const googleButtonVisible = Boolean(snapshot.loginButton)
    || native.renderer.google_signin_button_visible === true
    || /"google_signin_button_visible"\s*:\s*true/i.test(native.text);
  const pageFinished = native.webview.page_finished === true || /webview_page_finished/i.test(native.text);
  const pageCommitVisible = native.webview.page_commit_visible === true || /webview_page_commit_visible/i.test(native.text);
  const currentUrl = String(native.webview.current_url || native.snapshot.current_webview_url || snapshot.latestUrl || "");
  const nativeSplash = native.webview.splash_visible === true || (/Connecting to wa\.colmeio\.com|WASM Agent/i.test(uiText) && !pageCommitVisible);
  const errorVisible = native.webview.error_visible === true
    || Boolean(native.webview.main_frame_error && native.webview.main_frame_error !== null)
    || /WASM Agent did not load|WASM Agent is offline|Secure connection blocked|Google login is not configured/i.test(allText);
  const authenticated = /"auth_state"\s*:\s*"authenticated"|authenticated_ui_visible|has_wa_uid"\s*:\s*true/i.test(native.text);
  const oauthRedirect = /accounts\.google\.com|\/native\/android\/auth\/start|wasm-agent:\/\/android-auth-return|\/native\/android\/auth\/return/i.test(allText);
  const androidDiagnosticsPage = /WasmAgentAndroidDiagnostics|native-diagnostics|Android diagnostics/i.test(allText);
  let state = "webview_blank";
  let reason = "WebView has no exposed login state yet";
  if (oauthRedirect) {
    state = "browser_oauth_redirect_page";
    reason = "OAuth redirect/browser evidence is visible before first-screen tap";
  } else if (authenticated) {
    state = "authenticated_page";
    reason = "Renderer/native diagnostics indicate an authenticated session";
  } else if (googleButtonVisible || loginVisible) {
    state = "login_page";
    reason = googleButtonVisible ? "Google sign-in button reported visible" : "login screen reported visible";
  } else if (androidDiagnosticsPage) {
    state = "android_debug_diagnostics_page";
    reason = "Android diagnostics/debug surface is visible";
  } else if (errorVisible) {
    state = "network_config_error";
    reason = "Native/WebView diagnostics show a load or config error";
  } else if (nativeSplash) {
    state = "native_splash_loading";
    reason = "Native splash/loading screen is still visible";
  } else if (pageFinished || pageCommitVisible) {
    state = "webview_blank";
    reason = "WebView loaded or committed, but no login/auth state is exposed";
  }
  return redactValue({
    state,
    reason,
    currentUrl,
    pageFinished,
    pageCommitVisible,
    loginScreenVisible: loginVisible,
    googleSigninButtonVisible: googleButtonVisible,
    nativeDiagnosticsOk: Boolean(snapshot.nativeDiagnostics?.ok),
    evidence: {
      uiXml: snapshot.artifacts?.ui || "",
      screenshot: snapshot.artifacts?.screenshot || "",
      nativeDiagnostics: snapshot.nativeDiagnostics?.artifact || "",
      logcat: snapshot.artifacts?.logcat || "",
      visibleTextSample: uiText.slice(0, 1000),
    },
  });
}

function firstMatchingEvidence(patterns, parts) {
  for (const [label, text] of parts) {
    const value = String(text || "");
    for (const pattern of patterns) {
      const match = value.match(pattern);
      if (match) {
        return {
          label,
          match: redactString(match[0]).slice(0, 500),
        };
      }
    }
  }
  return null;
}

function extractAndroidAuthSessionFromText(text) {
  const value = String(text || "");
  const patterns = [
    /[?&]state=([A-Za-z0-9._:-]{24,128})/i,
    /[?&]session=([A-Za-z0-9._:-]{24,128})/i,
    /android_auth_session=([A-Za-z0-9._:-]{24,128})/i,
    /wasm-agent:\/\/android-auth-return\?session=([A-Za-z0-9._:-]{24,128})/i,
  ];
  for (const pattern of patterns) {
    const match = value.match(pattern);
    if (match?.[1]) return match[1];
  }
  return "";
}

function extractNativeCorrelationFromText(text) {
  const value = String(text || "");
  const patterns = [
    /[?&]native_correlation_id=([A-Za-z0-9._:-]{12,220})/i,
    /native_correlation_id["']?\s*[:=]\s*["']?([A-Za-z0-9._:-]{12,220})/i,
    /nativeCorrelationId["']?\s*[:=]\s*["']?([A-Za-z0-9._:-]{12,220})/i,
  ];
  for (const pattern of patterns) {
    const match = value.match(pattern);
    if (match?.[1]) return match[1];
  }
  return "";
}

function detectChooserFromText(text) {
  const value = String(text || "");
  const chooserDetected = /Open with|Complete action using|Choose an app|Just once|Always/i.test(value)
    || /ResolverActivity|ChooserActivity|IntentResolver/i.test(value);
  return {
    detected: chooserDetected,
    openWithText: /Open with|Complete action using/i.test(value),
    chromeOption: chooserDetected && /\bChrome\b|com\.android\.chrome|com\.google\.android\.apps\.chrome/i.test(value),
    wasmAgentOption: chooserDetected && /\bWASM Agent\b|com\.colmeio\.wasmagent/i.test(value),
  };
}

function classifyTapEvidence(snapshot) {
  const parts = [
    ["ui", snapshot.uiText],
    ["activity", snapshot.activityText],
    ["window", snapshot.windowText],
    ["logcat", snapshot.logcatText],
  ];
  const chooser = detectChooserFromText(parts.map(([, text]) => text).join("\n"));
  const externalAuthStart = firstMatchingEvidence([
    /(?:START[^\n]*|dat=|data=|uri=|Intent[^\n]*)https?:\/\/wa\.colmeio\.com\/native\/android\/auth\/start[^\s"'<>)]*/i,
    /https?:\/\/wa\.colmeio\.com\/native\/android\/auth\/start[^\s"'<>)]*/i,
  ], [
    ["ui", snapshot.uiText],
    ["activity", snapshot.activityText],
    ["window", snapshot.windowText],
    ["logcat-start", String(snapshot.logcatText || "").split(/\r?\n/).filter((line) => /START|ActivityTaskManager|Intent/i.test(line)).join("\n")],
  ]);
  const externalHome = firstMatchingEvidence([
    /(?:START[^\n]*|dat=|data=|uri=|Intent[^\n]*)https?:\/\/wa\.colmeio\.com\/home[^\s"'<>)]*/i,
  ], [
    ["activity", snapshot.activityText],
    ["window", snapshot.windowText],
    ["logcat-start", String(snapshot.logcatText || "").split(/\r?\n/).filter((line) => /START|ActivityTaskManager|Intent/i.test(line)).join("\n")],
  ]);
  const googleHost = firstMatchingEvidence([
    /https?:\/\/accounts\.google\.com[^\s"'<>)]*/i,
    /\baccounts\.google\.com\b/i,
  ], parts);
  const androidAuthSession = extractAndroidAuthSessionFromText(parts.map(([, text]) => text).join("\n"));
  const nativeCorrelationId = extractNativeCorrelationFromText(parts.map(([, text]) => text).join("\n"));
  const googleAccountScreen = /Choose an account|Use your Google Account|Sign in\s*[- ]\s*Google|Google Accounts|to continue to/i.test(String(snapshot.uiText || ""));
  return {
    chooser,
    forbiddenExternal: {
      authStart: Boolean(externalAuthStart),
      authStartEvidence: externalAuthStart,
      home: Boolean(externalHome),
      homeEvidence: externalHome,
    },
    google: {
      hostDetected: Boolean(googleHost),
      hostEvidence: googleHost,
      accountScreenDetected: googleAccountScreen,
      androidAuthSession,
      nativeCorrelationId,
    },
    passed: !chooser.detected
      && !chooser.wasmAgentOption
      && !externalAuthStart
      && !externalHome
      && (Boolean(googleHost) || googleAccountScreen),
  };
}

function summarizeSnapshot(snapshot) {
  const firstScreenClassification = snapshot.firstScreenClassification || classifyFirstScreenState(snapshot);
  return redactValue({
    label: snapshot.label,
    at: snapshot.at,
    artifacts: snapshot.artifacts || {},
    topActivity: snapshot.topActivity || "",
    currentFocus: snapshot.currentFocus || "",
    latestUrl: firstScreenClassification.currentUrl || "",
    firstScreenClassification,
    webViewPageFinished: Boolean(firstScreenClassification.pageFinished),
    visibleTextSample: String(snapshot.uiText || "").slice(0, 1000),
    loginButton: snapshot.loginButton ? {
      text: snapshot.loginButton.text,
      bounds: snapshot.loginButton.bounds,
      source: snapshot.loginButton.source || "uiautomator",
    } : null,
    nativeDiagnostics: snapshot.nativeDiagnostics ? {
      ok: Boolean(snapshot.nativeDiagnostics.ok),
      source: snapshot.nativeDiagnostics.source || "",
      artifact: snapshot.nativeDiagnostics.artifact || "",
    } : null,
    staleOpeningMessage: /Opening Google sign-in\.\.\./i.test(String(snapshot.uiText || "")),
  });
}

function extractTopActivity(activityText) {
  const text = String(activityText || "");
  const match = text.match(/mResumedActivity:.*? ([A-Za-z0-9_.]+\/[A-Za-z0-9_.$]+)|topResumedActivity=.*? ([A-Za-z0-9_.]+\/[A-Za-z0-9_.$]+)|ResumedActivity:.*? ([A-Za-z0-9_.]+\/[A-Za-z0-9_.$]+)/i);
  return (match && (match[1] || match[2] || match[3])) || "";
}

function extractCurrentFocus(windowText) {
  const text = String(windowText || "");
  const match = text.match(/mCurrentFocus=([^\n]+)|mFocusedApp=([^\n]+)/i);
  return (match && (match[1] || match[2] || "").trim()) || "";
}

async function writeScreenshot(ctx, adbInfo, serial, label) {
  const result = await runAdb(adbInfo, ["exec-out", "screencap", "-p"], {
    serial,
    encoding: "buffer",
    timeoutMs: 10000,
  });
  if (result.status !== 0 || !Buffer.isBuffer(result.stdout) || result.stdout.length < 100) {
    return { ok: false, result: compactCommandResult(result) };
  }
  const filePath = ctx.artifactPath("screenshots", `${label}.png`);
  fs.writeFileSync(filePath, result.stdout);
  ctx.addArtifact("screenshot", filePath);
  return { ok: true, ref: ctx.artifactRef(filePath) };
}

async function dumpUiXml(adbInfo, serial) {
  const remotePath = `/sdcard/wasm-agent-sim-${Date.now()}.xml`;
  await adbText(adbInfo, serial, ["shell", "uiautomator", "dump", remotePath], { timeoutMs: 10000 });
  const cat = await adbText(adbInfo, serial, ["exec-out", "cat", remotePath], { timeoutMs: 10000 });
  await adbText(adbInfo, serial, ["shell", "rm", "-f", remotePath], { timeoutMs: 5000 }).catch(() => {});
  return cat.status === 0 ? cat.stdout : resultText(cat);
}

async function captureSnapshot(ctx, adbInfo, serial, label, options = {}) {
  const [uiXml, activity, windowDump, topDump, logcat] = await Promise.all([
    dumpUiXml(adbInfo, serial),
    adbText(adbInfo, serial, ["shell", "dumpsys", "activity", "activities"], { timeoutMs: 12000 }),
    adbText(adbInfo, serial, ["shell", "dumpsys", "window"], { timeoutMs: 12000 }),
    adbText(adbInfo, serial, ["shell", "dumpsys", "activity", "top"], { timeoutMs: 12000 }),
    options.includeLogcat
      ? adbText(adbInfo, serial, ["logcat", "-d", "-v", "threadtime", "-t", String(Number(process.env.WASM_AGENT_SIM_ANDROID_LOGCAT_LINES || 1200))], { timeoutMs: 12000 })
      : Promise.resolve({ stdout: "", stderr: "", status: 0 }),
  ]);
  const parsedUi = parseUiXml(uiXml);
  const artifacts = {};
  const uiPath = ctx.writeTextArtifact("ui", `ui/${label}.xml`, uiXml);
  artifacts.ui = ctx.artifactRef(uiPath);
  const activityPath = ctx.writeTextArtifact("activityDump", `activity/${label}-activity.txt`, resultText(activity));
  artifacts.activity = ctx.artifactRef(activityPath);
  const windowPath = ctx.writeTextArtifact("windowDump", `activity/${label}-window.txt`, resultText(windowDump));
  artifacts.window = ctx.artifactRef(windowPath);
  const topPath = ctx.writeTextArtifact("activityTop", `activity/${label}-top.txt`, resultText(topDump));
  artifacts.top = ctx.artifactRef(topPath);
  if (options.includeLogcat) {
    const logPath = ctx.writeTextArtifact("logcat", `logs/${label}-logcat.txt`, resultText(logcat));
    artifacts.logcat = ctx.artifactRef(logPath);
  }
  const screenshot = await writeScreenshot(ctx, adbInfo, serial, label);
  if (screenshot.ok) artifacts.screenshot = screenshot.ref;
  const nativeDiagnostics = options.packageName
    ? await collectNativeDiagnosticsLatest(ctx, adbInfo, serial, options.packageName, options.origin || "").catch((error) => ({
      ok: false,
      source: "error",
      error: String(error?.message || error).slice(0, 1000),
    }))
    : null;
  const snapshot = {
    label,
    at: new Date().toISOString(),
    uiXml,
    uiText: parsedUi.visibleText,
    parsedUi,
    loginButton: findLoginButton(parsedUi),
    activityText: resultText(activity),
    windowText: resultText(windowDump),
    topText: resultText(topDump),
    logcatText: resultText(logcat),
    topActivity: extractTopActivity(resultText(activity)),
    currentFocus: extractCurrentFocus(resultText(windowDump)),
    artifacts,
    nativeDiagnostics,
  };
  snapshot.loginButton = snapshot.loginButton || loginButtonFromRendererReadiness(snapshot);
  return snapshot;
}

async function collectLogcatExcerpt(ctx, adbInfo, serial, label = "final") {
  const result = await adbText(adbInfo, serial, [
    "logcat",
    "-d",
    "-v",
    "threadtime",
    "-t",
    String(Number(process.env.WASM_AGENT_SIM_ANDROID_LOGCAT_LINES || 1800)),
  ], { timeoutMs: 15000 });
  const raw = resultText(result);
  const lines = raw
    .split(/\r?\n/)
    .filter((line) => /WasmAgentNative|com\.colmeio\.wasmagent|wasm-agent:\/\/android-auth-return|\/native\/android\/auth|accounts\.google\.com|ActivityTaskManager|START u0/i.test(line))
    .slice(-500)
    .join("\n");
  const artifact = ctx.writeTextArtifact("logcat", `logs/${label}-native-logcat-excerpt.txt`, lines || raw.slice(-16000));
  return redactValue({
    ok: result.status === 0,
    artifact: ctx.artifactRef(artifact),
    lineCount: (lines || raw).split(/\r?\n/).filter(Boolean).length,
    status: result.status,
    stderr: String(result.stderr || "").slice(0, 1000),
  });
}

async function collectNativeDiagnosticsLatest(ctx, adbInfo, serial, packageName, origin = "") {
  const attempts = [];
  const runAsExec = await adbText(adbInfo, serial, ["exec-out", "run-as", packageName, "cat", "files/native-diagnostics/latest.json"], { timeoutMs: 12000 });
  attempts.push({ mode: "exec-out run-as", status: runAsExec.status, stderr: String(runAsExec.stderr || "").slice(0, 1000) });
  let raw = runAsExec.status === 0 ? String(runAsExec.stdout || "").trim() : "";
  if (!raw) {
    const runAsShell = await adbText(adbInfo, serial, ["shell", "run-as", packageName, "cat", "files/native-diagnostics/latest.json"], { timeoutMs: 12000 });
    attempts.push({ mode: "shell run-as", status: runAsShell.status, stderr: String(runAsShell.stderr || "").slice(0, 1000) });
    raw = runAsShell.status === 0 ? String(runAsShell.stdout || "").trim() : "";
  }

  if (raw) {
    let payload = null;
    try {
      payload = JSON.parse(raw);
    } catch {
      payload = { raw: raw.slice(0, 120000) };
    }
    const artifact = ctx.writeJsonArtifact("nativeDiagnostics", "logs/native-diagnostics-latest.json", payload);
    return redactValue({ ok: true, source: "apk-files", artifact: ctx.artifactRef(artifact), attempts, payload });
  }

  if (origin) {
    const serverLatest = await fetchJsonUrl(`${origin.replace(/\/+$/, "")}/native/diagnostics/latest`, { timeoutMs: 8000 });
    attempts.push({ mode: "server /native/diagnostics/latest", ok: serverLatest.ok, statusCode: serverLatest.statusCode, error: serverLatest.error || "" });
    if (serverLatest.ok && serverLatest.payload) {
      const artifact = ctx.writeJsonArtifact("nativeDiagnostics", "logs/native-diagnostics-latest.json", serverLatest.payload);
      return redactValue({ ok: true, source: "server-upload", artifact: ctx.artifactRef(artifact), attempts, payload: serverLatest.payload });
    }
  }

  const artifact = ctx.writeJsonArtifact("nativeDiagnostics", "logs/native-diagnostics-latest-missing.json", {
    ok: false,
    reason: "native diagnostics latest.json was not accessible via run-as and no server upload was available",
    attempts,
  });
  return redactValue({ ok: false, source: "missing", artifact: ctx.artifactRef(artifact), attempts });
}

async function collectServerCorrelationLogs(ctx, origin, sessionId, nativeCorrelationId = "") {
  const debug = await fetchNativeAndroidAuthDebug(origin, sessionId);
  const payload = debug.payload || {};
  const correlationMatches = !nativeCorrelationId || !payload.native_correlation_id || payload.native_correlation_id === nativeCorrelationId;
  const artifact = ctx.writeJsonArtifact("serverCorrelationLogs", "logs/server-correlation-auth-debug.json", debug);
  return redactValue({
    ok: Boolean(debug.ok && debug.payload) && correlationMatches,
    artifact: ctx.artifactRef(artifact),
    debug,
    correlationMatches,
  });
}

async function waitForLoginButton(ctx, adbInfo, serial, label, timeoutMs = DEFAULT_WAIT_BOOT_MS, options = {}) {
  const started = Date.now();
  let lastSnapshot = null;
  while (Date.now() - started < timeoutMs) {
    const snapshot = await captureSnapshot(ctx, adbInfo, serial, `${label}-poll-${String(Math.floor((Date.now() - started) / 1000)).padStart(2, "0")}`, {
      includeLogcat: true,
      packageName: options.packageName,
      origin: options.origin,
    });
    snapshot.firstScreenClassification = classifyFirstScreenState(snapshot);
    lastSnapshot = snapshot;
    if (snapshot.loginButton) break;
    if (snapshot.firstScreenClassification.googleSigninButtonVisible && snapshot.firstScreenClassification.loginScreenVisible) break;
    if (/WASM Agent did not load|WASM Agent is offline|Secure connection blocked/i.test(snapshot.uiText)) break;
    await sleep(1500);
  }
  const full = await captureSnapshot(ctx, adbInfo, serial, label, {
    includeLogcat: true,
    packageName: options.packageName,
    origin: options.origin,
  });
  if (lastSnapshot?.loginButton && !full.loginButton) {
    full.loginButton = lastSnapshot.loginButton;
  }
  full.firstScreenClassification = classifyFirstScreenState(full);
  if (!full.firstScreenClassification.googleSigninButtonVisible && lastSnapshot?.firstScreenClassification?.googleSigninButtonVisible) {
    full.firstScreenClassification = lastSnapshot.firstScreenClassification;
  }
  return full;
}

async function observeAfterTap(ctx, adbInfo, serial, label, timeoutMs = DEFAULT_WAIT_AFTER_TAP_MS) {
  const started = Date.now();
  const polls = [];
  let decisive = null;
  while (Date.now() - started < timeoutMs) {
    const snapshot = await captureSnapshot(ctx, adbInfo, serial, `${label}-poll-${String(polls.length + 1).padStart(2, "0")}`, {
      includeLogcat: true,
    });
    const classification = classifyTapEvidence(snapshot);
    const summary = {
      snapshot: summarizeSnapshot(snapshot),
      classification,
    };
    polls.push(summary);
    if (classification.chooser.detected || classification.forbiddenExternal.authStart || classification.forbiddenExternal.home || classification.google.hostDetected || classification.google.accountScreenDetected) {
      decisive = { snapshot, classification };
      break;
    }
    await sleep(1500);
  }
  if (!decisive && polls.length) {
    decisive = {
      snapshot: null,
      classification: polls[polls.length - 1].classification,
    };
  }
  const pollsPath = ctx.writeJsonArtifact("tapPolls", `logs/${label}-polls.json`, polls);
  return {
    label,
    polls,
    pollsArtifact: ctx.artifactRef(pollsPath),
    classification: decisive?.classification || classifyTapEvidence({}),
    decisiveSnapshot: decisive?.snapshot ? summarizeSnapshot(decisive.snapshot) : null,
  };
}

async function tapLoginButton(adbInfo, serial, button) {
  if (!button?.bounds) {
    return {
      status: -1,
      stdout: "",
      stderr: "missing Sign in with Google button bounds",
    };
  }
  return adbText(adbInfo, serial, ["shell", "input", "tap", String(button.bounds.centerX), String(button.bounds.centerY)], {
    timeoutMs: 8000,
  });
}

async function getDeviceInfo(adbInfo, serial) {
  const props = {};
  for (const [key, prop] of Object.entries({
    model: "ro.product.model",
    manufacturer: "ro.product.manufacturer",
    brand: "ro.product.brand",
    device: "ro.product.device",
    androidVersion: "ro.build.version.release",
    sdk: "ro.build.version.sdk",
    fingerprint: "ro.build.fingerprint",
    abi: "ro.product.cpu.abi",
  })) {
    const result = await adbText(adbInfo, serial, ["shell", "getprop", prop], { timeoutMs: 5000 });
    props[key] = result.stdout.trim();
  }
  const [wmSize, wmDensity] = await Promise.all([
    adbText(adbInfo, serial, ["shell", "wm", "size"], { timeoutMs: 5000 }),
    adbText(adbInfo, serial, ["shell", "wm", "density"], { timeoutMs: 5000 }),
  ]);
  return redactValue({
    serial,
    ...props,
    wmSize: wmSize.stdout.trim(),
    wmDensity: wmDensity.stdout.trim(),
  });
}

async function installApk(adbInfo, serial, apkPath, packageName) {
  const attempts = [];
  let install = await adbText(adbInfo, serial, ["install", "-r", "-d", apkPath], { timeoutMs: 180000 });
  attempts.push(compactCommandResult(install));
  if (install.status !== 0 && /INSTALL_FAILED_VERSION_DOWNGRADE|INSTALL_FAILED_UPDATE_INCOMPATIBLE|INSTALL_FAILED_INVALID_APK/i.test(resultText(install))) {
    const uninstall = await adbText(adbInfo, serial, ["uninstall", packageName], { timeoutMs: 60000 });
    attempts.push(compactCommandResult(uninstall));
    install = await adbText(adbInfo, serial, ["install", "-r", apkPath], { timeoutMs: 180000 });
    attempts.push(compactCommandResult(install));
  }
  return {
    ok: install.status === 0 && /Success/i.test(resultText(install)),
    attempts,
  };
}

async function launchApp(adbInfo, serial, packageName, activityName) {
  await adbText(adbInfo, serial, ["shell", "input", "keyevent", "KEYCODE_WAKEUP"], { timeoutMs: 5000 }).catch(() => {});
  await adbText(adbInfo, serial, ["shell", "wm", "dismiss-keyguard"], { timeoutMs: 5000 }).catch(() => {});
  await adbText(adbInfo, serial, ["shell", "am", "force-stop", packageName], { timeoutMs: 10000 });
  const component = `${packageName}/${activityName}`;
  return adbText(adbInfo, serial, ["shell", "am", "start", "-W", "-n", component], { timeoutMs: 20000 });
}

function detectHostVirtualization(rootDir = repoRootFromCore()) {
  const cpuinfoPath = "/proc/cpuinfo";
  const cpuinfo = fs.existsSync(cpuinfoPath) ? fs.readFileSync(cpuinfoPath, "utf8") : "";
  const kvmExists = fs.existsSync("/dev/kvm");
  let kvmAccessible = false;
  try {
    if (kvmExists) {
      fs.accessSync("/dev/kvm", fs.constants.R_OK | fs.constants.W_OK);
      kvmAccessible = true;
    }
  } catch {
    kvmAccessible = false;
  }
  const virtualizationFlags = /\b(vmx|svm)\b/i.test(cpuinfo);
  const nestedIntel = fs.existsSync("/sys/module/kvm_intel/parameters/nested")
    ? fs.readFileSync("/sys/module/kvm_intel/parameters/nested", "utf8").trim()
    : "";
  const nestedAmd = fs.existsSync("/sys/module/kvm_amd/parameters/nested")
    ? fs.readFileSync("/sys/module/kvm_amd/parameters/nested", "utf8").trim()
    : "";
  return redactValue({
    platform: os.platform(),
    arch: os.arch(),
    machine: os.machine ? os.machine() : "",
    release: os.release(),
    rootDir,
    kvmExists,
    kvmAccessible,
    virtualizationFlags,
    nestedVirtualization: nestedIntel || nestedAmd || "",
    viableForX86Emulator: os.platform() === "linux" && os.arch() === "x64" && kvmExists && kvmAccessible && virtualizationFlags,
  });
}

function candidateAndroidSdkRoots(rootDir = repoRootFromCore()) {
  return unique([
    process.env.ANDROID_HOME,
    process.env.ANDROID_SDK_ROOT,
    path.join(rootDir, "native", "android", ".android-sdk"),
  ]);
}

async function detectAndroidSdk(rootDir = repoRootFromCore()) {
  const roots = candidateAndroidSdkRoots(rootDir);
  const candidates = [];
  for (const root of roots) {
    const platformToolsAdb = path.join(root, "platform-tools", process.platform === "win32" ? "adb.exe" : "adb");
    const emulator = path.join(root, "emulator", process.platform === "win32" ? "emulator.exe" : "emulator");
    const sdkmanagerCandidates = [
      path.join(root, "cmdline-tools", "latest", "bin", process.platform === "win32" ? "sdkmanager.bat" : "sdkmanager"),
      path.join(root, "tools", "bin", process.platform === "win32" ? "sdkmanager.bat" : "sdkmanager"),
    ];
    const avdmanagerCandidates = [
      path.join(root, "cmdline-tools", "latest", "bin", process.platform === "win32" ? "avdmanager.bat" : "avdmanager"),
      path.join(root, "tools", "bin", process.platform === "win32" ? "avdmanager.bat" : "avdmanager"),
    ];
    candidates.push({
      root,
      exists: fs.existsSync(root),
      adb: fs.existsSync(platformToolsAdb) ? platformToolsAdb : "",
      emulator: fs.existsSync(emulator) ? emulator : "",
      sdkmanager: sdkmanagerCandidates.find((candidate) => fs.existsSync(candidate)) || "",
      avdmanager: avdmanagerCandidates.find((candidate) => fs.existsSync(candidate)) || "",
      avdHome: process.env.ANDROID_AVD_HOME || path.join(os.homedir(), ".android", "avd"),
    });
  }
  const selected = candidates.find((candidate) => candidate.exists && candidate.emulator && candidate.sdkmanager && candidate.avdmanager)
    || candidates.find((candidate) => candidate.exists)
    || candidates[0];
  let avds = [];
  let avdResult = null;
  if (selected?.emulator) {
    avdResult = await runCommand(selected.emulator, ["-list-avds"], { timeoutMs: 12000 });
    avds = resultText(avdResult).split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  }
  return redactValue({
    roots: candidates,
    selected,
    avds,
    avdResult: avdResult ? compactCommandResult(avdResult) : null,
  });
}

async function detectDockerRuntime() {
  const docker = commandPath("docker");
  if (!docker) return { available: false, reason: "Docker unavailable" };
  const info = await runCommand(docker, ["info", "--format", "{{json .}}"], { timeoutMs: 12000 });
  return redactValue({
    available: info.status === 0,
    command: docker,
    reason: info.status === 0 ? "" : "Docker daemon unavailable or not accessible",
    info: compactCommandResult(info),
    kvmDeviceAvailable: fs.existsSync("/dev/kvm"),
  });
}

async function attemptDockerEmulator(host) {
  const docker = await detectDockerRuntime();
  if (!docker.available) {
    return { attempted: false, available: false, reason: docker.reason, docker };
  }
  if (!host.kvmExists || !host.kvmAccessible) {
    return {
      attempted: false,
      available: false,
      reason: "Docker emulator skipped because /dev/kvm is unavailable to the host; Docker cannot replace missing KVM/nested virtualization.",
      docker,
    };
  }
  return {
    attempted: false,
    available: false,
    reason: "Docker is available and /dev/kvm exists, but no pinned Android emulator container is configured for this simulator yet.",
    docker,
  };
}

async function waitForAnyEmulator(rootDir, timeoutMs = DEFAULT_EMULATOR_BOOT_MS) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const detection = await detectAdbDevice(rootDir, { kind: "emulator" });
    if (detection.available) return detection;
    await sleep(3000);
  }
  return detectAdbDevice(rootDir, { kind: "emulator" });
}

async function attemptHostEmulatorBootstrap(rootDir, host, sdk) {
  const result = {
    attempted: false,
    available: false,
    reason: "",
    commands: [],
  };
  if (!host.viableForX86Emulator) {
    result.reason = host.kvmExists
      ? "host emulator skipped because KVM is not accessible or CPU virtualization flags are missing"
      : "host emulator skipped because /dev/kvm is unavailable";
    return result;
  }
  const selected = sdk.selected || {};
  if (!selected.emulator || !selected.sdkmanager || !selected.avdmanager) {
    result.reason = "Android SDK emulator/cmdline-tools are not installed; automatic SDK download is not enabled in this repository runner";
    return result;
  }
  result.attempted = true;
  const systemImage = process.env.WASM_AGENT_SIM_ANDROID_SYSTEM_IMAGE || "system-images;android-35;google_apis;x86_64";
  const avdName = process.env.WASM_AGENT_SIM_ANDROID_AVD || "wasm_agent_api35";
  const install = await runCommand(selected.sdkmanager, ["platform-tools", "emulator", "platforms;android-35", systemImage], {
    timeoutMs: 300000,
    env: {
      ...process.env,
      ANDROID_HOME: selected.root,
      ANDROID_SDK_ROOT: selected.root,
    },
  });
  result.commands.push(compactCommandResult(install));
  if (install.status !== 0) {
    result.reason = "sdkmanager could not install emulator packages/system image";
    return result;
  }
  if (!sdk.avds.includes(avdName)) {
    const create = await runCommand("bash", ["-lc", `printf 'no\n' | "${selected.avdmanager}" create avd -f -n "${avdName}" -k "${systemImage}" --device pixel_6`], {
      timeoutMs: 120000,
      env: {
        ...process.env,
        ANDROID_HOME: selected.root,
        ANDROID_SDK_ROOT: selected.root,
      },
    });
    result.commands.push(compactCommandResult(create));
    if (create.status !== 0) {
      result.reason = "avdmanager could not create a viable AVD";
      return result;
    }
  }
  const emulator = spawn(selected.emulator, ["-avd", avdName, "-no-window", "-no-audio", "-no-snapshot", "-no-boot-anim", "-gpu", "swiftshader_indirect"], {
    cwd: rootDir,
    env: {
      ...process.env,
      ANDROID_HOME: selected.root,
      ANDROID_SDK_ROOT: selected.root,
    },
    stdio: ["ignore", "pipe", "pipe"],
    detached: true,
  });
  const logPath = path.join(rootDir, "reports", "sim", "android", "emulator-bootstrap.log");
  fs.mkdirSync(path.dirname(logPath), { recursive: true });
  const logStream = fs.createWriteStream(logPath, { flags: "a" });
  emulator.stdout.pipe(logStream);
  emulator.stderr.pipe(logStream);
  emulator.unref();
  result.commands.push({ command: selected.emulator, args: ["-avd", avdName, "-no-window", "-no-audio", "-no-snapshot", "-no-boot-anim"], status: "spawned", logPath });
  const detection = await waitForAnyEmulator(rootDir, DEFAULT_EMULATOR_BOOT_MS);
  result.available = detection.available;
  result.detection = redactValue({
    devices: detection.devices || [],
    selected: detection.selected || null,
    reason: detection.reason || "",
  });
  result.reason = detection.available ? "" : (detection.reason || "emulator did not reach adb device state before timeout");
  return redactValue(result);
}

async function runEmulatorAndroidSimulation(ctx, options = {}) {
  const rootDir = ctx.rootDir;
  const observations = {
    backend: "emulator",
    runtimeVerified: false,
    guardrail: "Emulator proof is useful for CI/regression only; real-device OAuth/app-link/chooser claims still require --device or --local-report evidence.",
  };
  ctx.result.target = { backend: "emulator" };
  ctx.startPhase("boot", "detect emulator, KVM/nested virtualization, SDK, and Docker");
  const existing = await detectAdbDevice(rootDir, { kind: "emulator" });
  observations.adb = redactValue({
    available: existing.adb?.available,
    displayPath: existing.adb?.displayPath,
    devices: existing.devices || [],
    devicesResult: existing.devicesResult || null,
  });
  if (existing.available) {
    ctx.completePhase("boot", "passed", "existing adb emulator found");
    return runLiveAndroidSimulation(ctx, { ...options, backend: "emulator", deviceKind: "emulator" });
  }
  observations.host = detectHostVirtualization(rootDir);
  observations.sdk = await detectAndroidSdk(rootDir);
  observations.hostBootstrap = await attemptHostEmulatorBootstrap(rootDir, observations.host, observations.sdk);
  if (observations.hostBootstrap.available) {
    ctx.completePhase("boot", "passed", "host emulator bootstrapped");
    return runLiveAndroidSimulation(ctx, { ...options, backend: "emulator", deviceKind: "emulator" });
  }
  observations.dockerBootstrap = await attemptDockerEmulator(observations.host);
  const reasons = [
    existing.reason,
    observations.hostBootstrap.reason,
    observations.dockerBootstrap.reason,
  ].filter(Boolean);
  return completePending(ctx, reasons.join("; ") || "no viable Android emulator backend", observations);
}

function completePending(ctx, reason, observations = {}) {
  for (const step of ctx.result.lifecycle) {
    if (step.status === "running" || step.status === "pending") {
      ctx.completePhase(step.phase, "pending", reason);
    }
  }
  ctx.result.status = "pending";
  ctx.result.pendingReason = reason;
  ctx.result.assertions.push({
    name: "Android runtime prerequisites",
    status: "pending",
    detail: reason,
  });
  ctx.result.evidence.observations = redactValue({
    runtimeVerified: false,
    pendingReason: reason,
    ...observations,
  });
  ctx.startPhase("score", "pending prerequisite");
  ctx.score();
  ctx.completePhase("score", "pending", "runtime verification not executed");
  const withSummary = {
    ...ctx.result.evidence.observations,
    finalScore: ctx.result.score,
  };
  withSummary.failureClassification = classifyAndroidOAuthFailure(withSummary);
  withSummary.reportSummary = finalReportSummary(ctx, withSummary);
  ctx.result.evidence.observations = redactValue(withSummary);
  ctx.writeJsonArtifact("observations", "logs/observations.json", ctx.result.evidence.observations);
  ctx.startPhase("report", "write result.json and summary.md");
  ctx.report();
  ctx.completePhase("report", "passed", "reports written");
  ctx.report();
  console.log(`horc simulate android: pending`);
  console.log(`  ${reason}`);
  console.log(`  report: ${ctx.reportDir}/summary.md`);
  return ctx.result;
}

function assertionDetailForTap(result) {
  const pieces = [];
  if (result.chooser.detected) pieces.push("chooser detected");
  if (result.chooser.chromeOption) pieces.push("Chrome option present");
  if (result.chooser.wasmAgentOption) pieces.push("WASM Agent option present");
  if (result.forbiddenExternal.authStart) pieces.push("external auth-start URL detected");
  if (result.forbiddenExternal.home) pieces.push("external home URL detected");
  if (result.google.hostDetected) pieces.push("accounts.google.com host evidence");
  if (result.google.accountScreenDetected) pieces.push("Google account UI evidence");
  return pieces.length ? pieces.join("; ") : "no decisive post-tap evidence";
}

function classifyPostAuthRedirect({
  serverCompleted,
  browserHome,
  browserActive,
  nativeReturn,
  nativeReturnIntent,
  nativeReturnReceived,
  authenticatedWebView,
}) {
  if (nativeReturnReceived && authenticatedWebView) return "native_return_received_and_authenticated";
  if (nativeReturnReceived && !authenticatedWebView) return "native_return_received_but_session_missing";
  if (serverCompleted && browserHome) return "auth_completed_but_landed_on_pwa_home";
  if (serverCompleted && browserActive) return "auth_completed_but_returned_to_browser";
  if (serverCompleted && (!nativeReturn || !nativeReturnIntent || !nativeReturnReceived)) return "native_return_intent_missing";
  return "pending_or_unobserved";
}

function classifyOAuthCompletionEvidence(snapshot, serverDebug = {}, packageName = DEFAULT_PACKAGE) {
  const parts = [
    ["ui", snapshot?.uiText],
    ["activity", snapshot?.activityText],
    ["window", snapshot?.windowText],
    ["top", snapshot?.topText],
    ["logcat", snapshot?.logcatText],
    ["serverDebug", JSON.stringify(serverDebug || {})],
  ];
  const combined = parts.map(([, text]) => String(text || "")).join("\n");
  const chooser = detectChooserFromText(combined);
  const browserHome = firstMatchingEvidence([
    /(?:com\.android\.chrome|ChromeTabbedActivity|START[^\n]*)[^\n]*https?:\/\/wa\.colmeio\.com\/home[^\s"'<>)]*/i,
    /https?:\/\/wa\.colmeio\.com\/home[^\s"'<>)]*/i,
  ], parts);
  const nativeReturn = firstMatchingEvidence([
    /wasm-agent:\/\/android-auth-return\?session=[A-Za-z0-9._:-]+/i,
    /intent:\/\/android-auth-return\?session=[A-Za-z0-9._:-]+/i,
    /\/native\/android\/auth\/return\?session=[A-Za-z0-9._:-]+/i,
  ], parts);
  const nativeReturnIntent = firstMatchingEvidence([
    /wasm-agent:\/\/android-auth-return\?session=[A-Za-z0-9._:-]+[^\n]*(?:pkg=|cmp=)com\.colmeio\.wasmagent/i,
    /intent:\/\/android-auth-return\?session=[A-Za-z0-9._:-]+/i,
    /android_auth_return_intent_received/i,
  ], parts);
  const nativePackage = packageName.replace(/\./g, "\\.");
  const nativeAppReturn = new RegExp(`${nativePackage}|WASM Agent`, "i").test(`${snapshot?.activityText || ""}\n${snapshot?.windowText || ""}\n${snapshot?.topActivity || ""}\n${snapshot?.currentFocus || ""}`)
    && !/com\.android\.chrome\/|ChromeTabbedActivity/i.test(String(snapshot?.topActivity || snapshot?.currentFocus || ""));
  const nativeReturnReceived = Boolean(nativeReturnIntent)
    && new RegExp(`${nativePackage}\\/\\.MainActivity|${nativePackage}\\.MainActivity|android_auth_return_intent_received`, "i").test(combined);
  const browserActive = /com\.android\.chrome\/|ChromeTabbedActivity|org\.mozilla|com\.brave\.browser|com\.microsoft\.emmx/i.test(String(snapshot?.activityText || snapshot?.windowText || snapshot?.topActivity || snapshot?.currentFocus || ""));
  const serverState = String(serverDebug?.state || serverDebug?.payload?.state || "").toLowerCase();
  const serverCompleted = ["completed", "delivered", "redeemed"].includes(serverState)
    || Boolean(serverDebug?.completed_at || serverDebug?.payload?.completed_at || serverDebug?.has_auth_code || serverDebug?.payload?.has_auth_code);
  const authenticatedWebView = serverState === "redeemed"
    || Boolean(serverDebug?.redeemed_at || serverDebug?.payload?.redeemed_at)
    || /auth_session_load_finished[^\n]*(authenticated["']?\s*:\s*true|authenticated=true)|has_wa_uid["']?\s*:\s*true/i.test(combined);
  const authenticatedUiVisible = /AUTHENTICATED_UI_SEEN|authenticated_ui_visible|authenticated-app-ready|renderer_app_ready[^\n]*(authenticated["']?\s*:\s*true|authenticated=true)/i.test(combined)
    || (authenticatedWebView && /WASM Agent Home|space-home|New Space|Fleet|Devices|Artifacts|agent/i.test(String(snapshot?.uiText || "")));
  const delivered = serverState === "delivered" || serverState === "completed" || Boolean(serverDebug?.delivered_at || serverDebug?.completed_at);
  const postAuthRedirectClassification = classifyPostAuthRedirect({
    serverCompleted,
    browserHome: Boolean(browserHome),
    browserActive,
    nativeReturn: Boolean(nativeReturn),
    nativeReturnIntent: Boolean(nativeReturnIntent),
    nativeReturnReceived,
    authenticatedWebView,
  });
  return {
    chooser,
    browserHome: {
      detected: Boolean(browserHome),
      evidence: browserHome,
    },
    nativeReturn: {
      detected: Boolean(nativeReturn),
      evidence: nativeReturn,
    },
    nativeReturnIntent: {
      detected: Boolean(nativeReturnIntent),
      evidence: nativeReturnIntent,
    },
    nativeReturnReceived,
    nativeAppReturn,
    browserActive,
    serverCompleted,
    authenticatedWebView,
    authenticatedUiVisible,
    serverState,
    delivered,
    postAuthRedirectClassification,
    authRedirectTarget: browserHome ? "browser-home" : nativeReturn ? "native-return" : "unknown",
    passed: !chooser.detected
      && !browserHome
      && Boolean(nativeReturn)
      && Boolean(nativeReturnIntent)
      && nativeReturnReceived
      && nativeAppReturn
      && authenticatedWebView
      && authenticatedUiVisible,
  };
}

function firstScreenLoginVisible(firstScreen = {}) {
  const classification = firstScreen.firstScreenClassification || {};
  return Boolean(
    firstScreen.loginButton ||
    (classification.loginScreenVisible === true && classification.googleSigninButtonVisible === true)
  );
}

function classifyAndroidOAuthFailure(observations = {}) {
  const firstScreen = observations.firstScreen || {};
  const firstScreenClassification = firstScreen.firstScreenClassification || {};
  const oauth = observations.oauthCompletionResult || {};
  const oauthClassification = oauth.classification || {};
  if (observations.fullOAuthRuntimeVerified || oauth.status === "passed" || oauthClassification.passed) {
    return "authenticated page";
  }
  if (!firstScreen || !Object.keys(firstScreen).length) {
    return "network/config/WebView boot failure";
  }
  if (["network_config_error", "webview_blank", "native_splash_loading", "android_debug_diagnostics_page"].includes(firstScreenClassification.state)) {
    return "network/config/WebView boot failure";
  }
  if (firstScreenClassification.loginScreenVisible !== true) {
    return "login page not visible";
  }
  if (firstScreenClassification.googleSigninButtonVisible !== true && !firstScreen.loginButton) {
    return "Google button not visible";
  }
  if (observations.tap && observations.tap.status !== 0) {
    return "Google button visible but tap failed";
  }
  const firstTap = observations.firstTap?.classification || {};
  if (!observations.tap && !observations.firstTap) {
    return "Google button visible but tap failed";
  }
  if (
    !firstTap.passed ||
    firstTap.chooser?.detected ||
    firstTap.forbiddenExternal?.authStart ||
    firstTap.forbiddenExternal?.home ||
    !(firstTap.google?.hostDetected || firstTap.google?.accountScreenDetected)
  ) {
    return firstTap.google?.hostDetected || firstTap.google?.accountScreenDetected
      ? "OAuth started but external/browser handoff failed"
      : "Google button visible but tap failed";
  }
  const postAuthClass = oauthClassification.postAuthRedirectClassification || "";
  if ([
    "auth_completed_but_returned_to_browser",
    "auth_completed_but_landed_on_pwa_home",
    "native_return_intent_missing",
    "native_return_received_but_session_missing",
  ].includes(postAuthClass)) {
    return postAuthClass;
  }
  if (oauthClassification.browserHome?.detected || (oauthClassification.serverCompleted && !oauthClassification.nativeReturnReceived)) {
    return "native_return_intent_missing";
  }
  if (oauthClassification.nativeReturnReceived && !oauthClassification.authenticatedWebView) {
    return "native_return_received_but_session_missing";
  }
  if (oauthClassification.authenticatedWebView && !oauthClassification.authenticatedUiVisible) {
    return "session persisted but WebView did not show authenticated UI";
  }
  return "OAuth started but external/browser handoff failed";
}

function oauthCompletionDetail(result) {
  if (!result) return "no OAuth completion evidence";
  const pieces = [];
  if (result.reason) pieces.push(result.reason);
  if (result.classification?.postAuthRedirectClassification) pieces.push(`post-auth=${result.classification.postAuthRedirectClassification}`);
  if (result.classification?.chooser?.detected) pieces.push("chooser detected after auth");
  if (result.classification?.browserHome?.detected) pieces.push("browser/PWA home redirect detected");
  if (result.classification?.nativeReturn?.detected) pieces.push("native return URL/deep link detected");
  if (result.classification?.nativeReturnIntent?.detected) pieces.push("package-targeted/custom-scheme return intent evidence");
  if (result.classification?.nativeReturnReceived) pieces.push("MainActivity received native return");
  if (result.classification?.nativeAppReturn) pieces.push("native app resumed");
  if (result.classification?.authenticatedWebView) pieces.push("WebView/session redemption evidence");
  if (result.classification?.authenticatedUiVisible) pieces.push("authenticated UI visible");
  if (result.classification?.serverState) pieces.push(`native auth state=${result.classification.serverState}`);
  return pieces.length ? pieces.join("; ") : "no decisive OAuth completion evidence";
}

function addOAuthCompletionAssertions(ctx, result) {
  const classification = result?.classification || {};
  const pending = result?.status === "pending";
  const add = (name, passed, detail, evidence) => {
    if (pending) return ctx.addPendingAssertion(name, detail, evidence);
    return ctx.addAssertion(name, passed, detail, evidence);
  };
  add(
    "OAuth completion redirects to native return",
    !classification.browserHome?.detected && classification.nativeReturn?.detected,
    oauthCompletionDetail(result),
    classification,
  );
  add(
    "package-targeted Android return intent fired",
    Boolean(classification.nativeReturnIntent?.detected),
    oauthCompletionDetail(result),
    classification,
  );
  add(
    "MainActivity received native return intent",
    Boolean(classification.nativeReturnReceived),
    oauthCompletionDetail(result),
    classification,
  );
  add(
    "post-auth returns to native app",
    Boolean(classification.nativeAppReturn) && Boolean(classification.nativeReturnReceived) && !classification.browserHome?.detected,
    oauthCompletionDetail(result),
    classification,
  );
  add(
    "WebView becomes authenticated",
    Boolean(classification.authenticatedWebView),
    oauthCompletionDetail(result),
    classification,
  );
  add(
    "authenticated UI visible",
    Boolean(classification.authenticatedUiVisible),
    oauthCompletionDetail(result),
    classification,
  );
}

function addTapAssertions(ctx, prefix, tapResult) {
  const result = tapResult.classification || tapResult;
  ctx.addAssertion(
    `${prefix}: no Android resolver chooser`,
    !result.chooser.detected && !result.chooser.chromeOption && !result.chooser.wasmAgentOption,
    result.chooser.detected
      ? assertionDetailForTap(result)
      : "no Open with / Complete action using chooser evidence",
    result.chooser,
  );
  ctx.addAssertion(
    `${prefix}: no external wasm-agent URL first`,
    !result.forbiddenExternal.authStart && !result.forbiddenExternal.home,
    result.forbiddenExternal.authStart || result.forbiddenExternal.home
      ? assertionDetailForTap(result)
      : "no external wa.colmeio.com auth-start/home intent evidence",
    result.forbiddenExternal,
  );
  ctx.addAssertion(
    `${prefix}: opens Google OAuth/account screen`,
    result.google.hostDetected || result.google.accountScreenDetected,
    assertionDetailForTap(result),
    result.google,
  );
}

async function runCancelRetry(ctx, adbInfo, serial, packageName, activityName, firstTapPassed, origin = "") {
  const result = {
    attempted: firstTapPassed,
    backResult: null,
    relaunchResult: null,
    returnedToApp: false,
    buttonRetryable: false,
    staleOpeningMessage: false,
    retryTap: null,
    passed: false,
  };
  if (!firstTapPassed) {
    result.reason = "first tap did not reach Google, so cancel/retry cannot prove recovery";
    return result;
  }
  result.backResult = compactCommandResult(await adbText(adbInfo, serial, ["shell", "input", "keyevent", "KEYCODE_BACK"], { timeoutMs: 8000 }));
  await sleep(2000);
  const launch = await launchApp(adbInfo, serial, packageName, activityName);
  result.relaunchResult = compactCommandResult(launch);
  await sleep(3000);
  const returned = await waitForLoginButton(ctx, adbInfo, serial, "after-cancel-return", Number(process.env.WASM_AGENT_SIM_ANDROID_CANCEL_WAIT_MS || 20000), {
    packageName,
    origin,
  });
  result.returnedToApp = /com\.colmeio\.wasmagent|WASM Agent|Sign in with Google/i.test(`${returned.topActivity}\n${returned.currentFocus}\n${returned.uiText}`);
  result.buttonRetryable = Boolean(returned.loginButton);
  result.staleOpeningMessage = /Opening Google sign-in\.\.\./i.test(String(returned.uiText || ""));
  result.returnSnapshot = summarizeSnapshot(returned);
  if (returned.loginButton) {
    const tap = await tapLoginButton(adbInfo, serial, returned.loginButton);
    result.retryTapCommand = compactCommandResult(tap);
    await sleep(2000);
    result.retryTap = await observeAfterTap(ctx, adbInfo, serial, "retry-tap", DEFAULT_WAIT_RETRY_MS);
  }
  const retryClass = result.retryTap?.classification || {};
  result.passed = result.returnedToApp
    && result.buttonRetryable
    && !result.staleOpeningMessage
    && Boolean(retryClass.passed);
  return redactValue(result);
}

async function fetchNativeAndroidAuthDebug(origin, sessionId) {
  if (!origin || !sessionId) return { ok: false, error: "missing origin or Android auth session" };
  const url = `${origin.replace(/\/+$/, "")}/native/android/auth/debug?session=${encodeURIComponent(sessionId)}`;
  return fetchJsonUrl(url, { timeoutMs: 8000 });
}

async function runOAuthCompletionProof(ctx, adbInfo, serial, options = {}) {
  const waitMs = Number(
    options.oauthWaitMs != null
      ? options.oauthWaitMs
      : process.env.WASM_AGENT_SIM_ANDROID_OAUTH_WAIT_MS || DEFAULT_OAUTH_WAIT_MS,
  );
  const result = {
    attempted: waitMs > 0,
    waitMs,
    session: options.sessionId || "",
    origin: options.origin || "",
    status: "pending",
    reason: "",
    polls: [],
    pollsArtifact: "",
    classification: classifyOAuthCompletionEvidence({}, {}, options.packageName || DEFAULT_PACKAGE),
  };
  if (!result.session) {
    result.reason = "no Android OAuth state/session was captured from the Google handoff";
    return result;
  }
  if (!result.origin) {
    result.reason = "APK/server origin is unknown, so native auth debug state cannot be checked";
    return result;
  }
  if (waitMs <= 0) {
    result.reason = "manual Google authorization proof was not requested; set WASM_AGENT_SIM_ANDROID_OAUTH_WAIT_MS or pass --interactive-oauth";
    result.debug = await fetchNativeAndroidAuthDebug(result.origin, result.session);
    if (result.debug?.payload) {
      result.classification = classifyOAuthCompletionEvidence({}, result.debug.payload, options.packageName || DEFAULT_PACKAGE);
    }
    return redactValue(result);
  }

  const started = Date.now();
  let decisive = null;
  while (Date.now() - started < waitMs) {
    const label = `oauth-completion-poll-${String(result.polls.length + 1).padStart(2, "0")}`;
    const [snapshot, debug] = await Promise.all([
      captureSnapshot(ctx, adbInfo, serial, label, { includeLogcat: true }),
      fetchNativeAndroidAuthDebug(result.origin, result.session),
    ]);
    const classification = classifyOAuthCompletionEvidence(snapshot, debug.payload || {}, options.packageName || DEFAULT_PACKAGE);
    const summary = {
      snapshot: summarizeSnapshot(snapshot),
      debug,
      classification,
    };
    result.polls.push(summary);
    if (classification.browserHome.detected || classification.passed) {
      decisive = summary;
      break;
    }
    await sleep(2000);
  }
  if (!decisive && result.polls.length) decisive = result.polls[result.polls.length - 1];
  result.pollsArtifact = ctx.artifactRef(ctx.writeJsonArtifact("oauthCompletionPolls", "logs/oauth-completion-polls.json", result.polls));
  result.classification = decisive?.classification || result.classification;
  result.decisiveSnapshot = decisive?.snapshot || null;
  result.debug = decisive?.debug || null;
  if (result.classification.passed) {
    result.status = "passed";
    result.reason = "native return and WebView/session redemption evidence captured";
  } else if (result.classification.browserHome?.detected) {
    result.status = "failed";
    result.reason = result.classification.postAuthRedirectClassification || "OAuth completion opened wa.colmeio.com/home in the browser/PWA";
  } else if ([
    "auth_completed_but_returned_to_browser",
    "auth_completed_but_landed_on_pwa_home",
    "native_return_intent_missing",
    "native_return_received_but_session_missing",
  ].includes(result.classification.postAuthRedirectClassification || "")) {
    result.status = "failed";
    result.reason = result.classification.postAuthRedirectClassification;
  } else {
    result.status = "pending";
    result.reason = "OAuth completion was not observed before the wait timeout";
  }
  return redactValue(result);
}

function finalReportSummary(ctx, observations) {
  return redactValue({
    classification: observations.failureClassification || classifyAndroidOAuthFailure(observations),
    device: observations.device
      ? `${observations.device.manufacturer || ""} ${observations.device.model || ""}`.trim() || observations.device.serial
      : "none",
    androidVersion: observations.device?.androidVersion || "",
    apk: observations.apk
      ? `${observations.apk.path} build=${observations.apk.buildId || "unknown"} sha256=${observations.apk.sha256 || ""}`
      : "",
    install: observations.install ? (observations.install.ok ? "passed" : "failed") : "not run",
    launch: observations.launch ? (observations.launch.ok ? "passed" : "failed") : "not run",
    firstScreen: observations.firstScreen
      ? (firstScreenLoginVisible(observations.firstScreen)
        ? (observations.firstScreen.loginButton && observations.firstScreen.loginButton.source !== "renderer_readiness" && observations.firstScreen.loginButton.source !== "native_adb_tap_target" && observations.firstScreen.loginButton.source !== "computed_from_renderer_readiness"
          ? "Sign in with Google visible"
          : "Sign in with Google visible by renderer readiness")
        : `${observations.firstScreen.firstScreenClassification?.state || "login entrypoint missing"}: ${observations.firstScreen.firstScreenClassification?.reason || "Sign in with Google not found"}`)
      : "not run",
    firstTap: observations.firstTap ? (observations.firstTap.classification?.passed ? "passed" : "failed") : "not run",
    chooser: observations.chooserResult ? (observations.chooserResult.detected ? "chooser detected" : "no chooser detected") : "not run",
    googleHost: observations.googleHostResult ? (observations.googleHostResult.hostDetected || observations.googleHostResult.accountScreenDetected ? "detected" : "not detected") : "not run",
    oauthCompletion: observations.oauthCompletionResult
      ? `${observations.oauthCompletionResult.status || "unknown"}: ${observations.oauthCompletionResult.reason || oauthCompletionDetail(observations.oauthCompletionResult)}`
      : "not run",
    postAuthRedirectClassification: observations.oauthCompletionResult
      ? observations.oauthCompletionResult.classification?.postAuthRedirectClassification || "unknown"
      : "not run",
    androidAuthSession: observations.androidAuthSession || observations.oauthCompletionResult?.session || "",
    nativeCorrelationId: observations.nativeCorrelationId
      || observations.oauthCompletionResult?.debug?.payload?.native_correlation_id
      || observations.nativeDiagnostics?.payload?.native_correlation_id
      || "",
    nativeReturn: observations.oauthCompletionResult
      ? (observations.oauthCompletionResult.classification?.nativeReturnReceived ? "received by MainActivity" : observations.oauthCompletionResult.classification?.nativeReturn?.detected ? "return URL only" : "not detected")
      : "not run",
    authenticatedWebView: observations.oauthCompletionResult
      ? (observations.oauthCompletionResult.classification?.authenticatedWebView ? "detected" : "not detected")
      : "not run",
    authenticatedUiVisible: observations.oauthCompletionResult
      ? (observations.oauthCompletionResult.classification?.authenticatedUiVisible ? "detected" : "not detected")
      : "not run",
    nativeDiagnostics: observations.nativeDiagnostics?.artifact || (observations.proof?.hasNativeDiagnostics ? "attached" : "not attached"),
    serverCorrelationLogs: observations.serverCorrelationLogs?.artifact || (observations.proof?.hasServerCorrelationLogs ? "attached" : "not attached"),
    logcatExcerpt: observations.logcatExcerpt?.artifact || (observations.proof?.hasLogcatExcerpt ? "attached" : "not attached"),
    cancelRetry: observations.cancelRetryResult ? (observations.cancelRetryResult.passed ? "passed" : "failed") : "not run",
    score: ctx.result.score == null ? "n/a" : `${ctx.result.score}/100`,
  });
}

function resolveLocalReportPath(inputPath) {
  const resolved = path.resolve(inputPath || "");
  if (!inputPath) throw new Error("--local-report requires a report file or directory path");
  if (!fs.existsSync(resolved)) throw new Error(`local report path does not exist: ${resolved}`);
  const stat = fs.statSync(resolved);
  if (stat.isDirectory()) {
    const resultPath = path.join(resolved, "result.json");
    if (!fs.existsSync(resultPath)) throw new Error(`local report directory does not contain result.json: ${resolved}`);
    return resultPath;
  }
  return resolved;
}

function assertionStatusMap(report) {
  const map = new Map();
  for (const assertion of Array.isArray(report?.assertions) ? report.assertions : []) {
    map.set(String(assertion.name || ""), String(assertion.status || ""));
  }
  return map;
}

function reportArtifactList(report) {
  const artifacts = report?.evidence?.artifacts || {};
  const values = [];
  for (const value of Object.values(artifacts)) {
    if (Array.isArray(value)) values.push(...value.map(String));
    else if (value) values.push(String(value));
  }
  return values;
}

function localReportRequiredProof(report) {
  const observations = report?.evidence?.observations || {};
  const assertions = assertionStatusMap(report);
  const artifacts = reportArtifactList(report);
  const missingAssertions = REQUIRED_ANDROID_PROOF_ASSERTIONS.filter((name) => !assertions.has(name));
  const failedAssertions = REQUIRED_ANDROID_PROOF_ASSERTIONS.filter((name) => assertions.get(name) === "failed");
  const pendingAssertions = REQUIRED_ANDROID_PROOF_ASSERTIONS.filter((name) => assertions.get(name) === "pending");
  const hasScreenshots = artifacts.some((item) => /screenshot|\.png$/i.test(item));
  const hasLogs = artifacts.some((item) => /logcat|logs\//i.test(item));
  const hasActivity = artifacts.some((item) => /activity|window/i.test(item));
  const hasNativeDiagnostics = artifacts.some((item) => /native-diagnostics-latest|nativeDiagnostics/i.test(item));
  const hasServerCorrelationLogs = artifacts.some((item) => /server-correlation-auth-debug|serverCorrelationLogs/i.test(item));
  const hasLogcatExcerpt = artifacts.some((item) => /native-logcat-excerpt|logcat/i.test(item));
  const oauth = observations.oauthCompletionResult || {};
  return redactValue({
    missingAssertions,
    failedAssertions,
    pendingAssertions,
    hasScreenshots,
    hasLogs,
    hasActivity,
    hasNativeDiagnostics,
    hasServerCorrelationLogs,
    hasLogcatExcerpt,
    oauthStatus: oauth.status || "",
    oauthNativeReturn: Boolean(oauth.classification?.nativeAppReturn),
    oauthAuthenticatedWebView: Boolean(oauth.classification?.authenticatedWebView),
    oauthAuthenticatedUiVisible: Boolean(oauth.classification?.authenticatedUiVisible),
    oauthBrowserHomeDetected: Boolean(oauth.classification?.browserHome?.detected),
  });
}

async function runLocalReportAndroidSimulation(ctx, reportPathInput) {
  const observations = {
    backend: "local-report",
    runtimeVerified: false,
    localReportPath: "",
  };
  try {
    ctx.startPhase("boot", "load local Android simulator report");
    const reportPath = resolveLocalReportPath(reportPathInput);
    observations.localReportPath = reportPath;
    const report = JSON.parse(fs.readFileSync(reportPath, "utf8"));
    const sourceCopy = ctx.writeJsonArtifact("localReport", "logs/local-report-source.json", report);
    observations.localReportArtifact = ctx.artifactRef(sourceCopy);
    observations.source = {
      schema: report.schema || "",
      platform: report.platform || "",
      status: report.status || "",
      score: report.score,
      runId: report.runId || "",
      command: report.command || "",
    };
    const sourceObservations = report.evidence?.observations || {};
    observations.device = sourceObservations.device || {};
    observations.apk = sourceObservations.apk || report.target?.apk || {};
    observations.proof = localReportRequiredProof(report);
    ctx.result.target = {
      backend: "local-report",
      sourceReport: reportPath,
      apk: observations.apk,
      device: observations.device,
    };
    ctx.addAssertion("local report schema", report.schema === "hermes.app_simulator.result.v1", report.schema || "missing schema");
    ctx.addAssertion("local report platform is android", report.platform === "android", report.platform || "missing platform");
    ctx.addAssertion("local report has device info", Boolean(observations.device.model || observations.device.serial), JSON.stringify(observations.device));
    ctx.addAssertion("local report has APK build id", Boolean(observations.apk.buildId), observations.apk.buildId || "missing build id", observations.apk);
    ctx.addAssertion("local report has APK sha256", /^[a-f0-9]{64}$/i.test(String(observations.apk.sha256 || "")) || observations.apk.sha256 === "fixture", observations.apk.sha256 || "missing sha256", observations.apk);
    const currentApk = loadApkMetadata(path.resolve(process.env.WASM_AGENT_ANDROID_APK || process.env.WASM_AGENT_SIM_ANDROID_APK || DEFAULT_ANDROID_APK), ctx.rootDir);
    if (currentApk.exists && currentApk.sha256 && observations.apk.sha256 && observations.apk.sha256 !== "fixture") {
      ctx.addAssertion(
        "local report APK sha256 matches current APK",
        currentApk.sha256 === observations.apk.sha256,
        currentApk.sha256 === observations.apk.sha256 ? currentApk.sha256 : `current ${currentApk.sha256}, report ${observations.apk.sha256}`,
        { currentApk, reportApk: observations.apk },
      );
    }
    ctx.addAssertion("local report has screenshots", observations.proof.hasScreenshots, observations.proof.hasScreenshots ? "screenshot artifacts referenced" : "missing screenshot artifacts", observations.proof);
    ctx.addAssertion("local report has logcat/log evidence", observations.proof.hasLogs, observations.proof.hasLogs ? "log artifacts referenced" : "missing log artifacts", observations.proof);
    ctx.addAssertion("local report has activity/window evidence", observations.proof.hasActivity, observations.proof.hasActivity ? "activity/window artifacts referenced" : "missing activity/window artifacts", observations.proof);
    ctx.addAssertion("native diagnostics latest.json attached", observations.proof.hasNativeDiagnostics, observations.proof.hasNativeDiagnostics ? "native diagnostics artifact referenced" : "missing native diagnostics latest.json artifact", observations.proof);
    ctx.addAssertion("server correlation logs attached", observations.proof.hasServerCorrelationLogs, observations.proof.hasServerCorrelationLogs ? "server correlation artifact referenced" : "missing server correlation logs artifact", observations.proof);
    ctx.addAssertion("logcat excerpt attached", observations.proof.hasLogcatExcerpt, observations.proof.hasLogcatExcerpt ? "logcat excerpt artifact referenced" : "missing logcat excerpt artifact", observations.proof);
    ctx.addAssertion(
      "local report includes required Android OAuth assertions",
      observations.proof.missingAssertions.length === 0,
      observations.proof.missingAssertions.length ? `missing ${observations.proof.missingAssertions.join(", ")}` : "all required assertions present",
      observations.proof,
    );
    ctx.addAssertion(
      "local report proves post-auth native return",
      observations.proof.oauthNativeReturn && !observations.proof.oauthBrowserHomeDetected,
      observations.proof.oauthBrowserHomeDetected ? "browser/PWA home redirect detected" : `nativeReturn=${observations.proof.oauthNativeReturn}`,
      observations.proof,
    );
    ctx.addAssertion(
      "local report proves authenticated WebView",
      observations.proof.oauthAuthenticatedWebView,
      `authenticatedWebView=${observations.proof.oauthAuthenticatedWebView} oauthStatus=${observations.proof.oauthStatus || "unknown"}`,
      observations.proof,
    );
    ctx.addAssertion(
      "local report proves authenticated UI visible",
      observations.proof.oauthAuthenticatedUiVisible,
      `authenticatedUiVisible=${observations.proof.oauthAuthenticatedUiVisible} oauthStatus=${observations.proof.oauthStatus || "unknown"}`,
      observations.proof,
    );
    ctx.addAssertion(
      "local report source status passed",
      report.status === "passed",
      `source status=${report.status || "unknown"} score=${report.score == null ? "n/a" : report.score}`,
      observations.source,
    );
    observations.runtimeVerified = report.status === "passed"
      && observations.proof.missingAssertions.length === 0
      && observations.proof.failedAssertions.length === 0
      && observations.proof.pendingAssertions.length === 0
      && observations.proof.oauthNativeReturn
      && observations.proof.oauthAuthenticatedWebView
      && observations.proof.oauthAuthenticatedUiVisible
      && !observations.proof.oauthBrowserHomeDetected;
    ctx.completePhase("boot", "passed", "local report loaded");
    ctx.startPhase("observe", "validate copied device/APK/artifact evidence");
    ctx.completePhase("observe", "passed", "local report evidence inspected");
    ctx.startPhase("act", "read recorded Android OAuth handoff assertions");
    ctx.completePhase("act", observations.proof.failedAssertions.length ? "failed" : "passed", "recorded assertions inspected");
    ctx.startPhase("assert", "validate source proves full Android OAuth return");
    ctx.completePhase(
      "assert",
      ctx.result.assertions.some((assertion) => assertion.status === "failed") ? "failed" : "passed",
      observations.runtimeVerified ? "local report proves required Android OAuth behavior" : "local report does not prove full Android OAuth behavior",
    );
  } catch (error) {
    ctx.addError(error, "local-report");
    ctx.addAssertion("local report validation completed", false, error.message || String(error));
  } finally {
    ctx.startPhase("collect evidence", "write local report validation observations");
    ctx.result.evidence.observations = redactValue(observations);
    ctx.completePhase("collect evidence", "passed", "local report validation artifacts collected");

    ctx.startPhase("score", "score local report validation");
    ctx.score();
    observations.finalScore = ctx.result.score;
    observations.reportSummary = finalReportSummary(ctx, observations);
    ctx.result.evidence.observations = redactValue(observations);
    ctx.writeJsonArtifact("observations", "logs/observations.json", observations);
    ctx.completePhase("score", "passed", `status=${ctx.result.status} score=${ctx.result.score == null ? "n/a" : ctx.result.score}`);

    ctx.startPhase("report", "write result.json and summary.md");
    ctx.report();
    ctx.completePhase("report", "passed", "reports written");
    ctx.report();
  }
  console.log(`horc simulate android local-report: ${ctx.result.status}${ctx.result.score == null ? "" : ` (${ctx.result.score}/100)`}`);
  console.log(`  report: ${ctx.reportDir}/summary.md`);
  return ctx.result;
}

async function runLiveAndroidSimulation(ctx, options = {}) {
  const rootDir = ctx.rootDir;
  const backend = options.backend || "auto";
  const deviceKind = options.deviceKind || (backend === "device" ? "device" : backend === "emulator" ? "emulator" : "any");
  const packageName = process.env.WASM_AGENT_SIM_ANDROID_PACKAGE || DEFAULT_PACKAGE;
  const activityName = process.env.WASM_AGENT_SIM_ANDROID_ACTIVITY || DEFAULT_ACTIVITY;
  const apkPath = path.resolve(process.env.WASM_AGENT_ANDROID_APK || process.env.WASM_AGENT_SIM_ANDROID_APK || DEFAULT_ANDROID_APK);
  let currentPhase = "boot";
  let pendingResult = null;
  const observations = {
    packageName,
    activityName,
    apk: loadApkMetadata(apkPath, rootDir),
    runtimeVerified: false,
    fullOAuthRuntimeVerified: false,
    buildSuccessIsRuntimeVerification: false,
    backend,
    requestedDeviceKind: deviceKind,
    guardrail: "This Android result is based on adb-installed APK runtime evidence, not Playwright web simulation.",
  };
  ctx.result.target = {
    apk: observations.apk,
    packageName,
    activityName,
  };

  try {
    ctx.startPhase("boot", "resolve adb, device, and APK");
    const adbDetection = await detectAdbDevice(rootDir, { kind: deviceKind });
    observations.adb = redactValue({
      available: adbDetection.adb?.available,
      displayPath: adbDetection.adb?.displayPath,
      version: adbDetection.adb?.version,
      wrapper: adbDetection.adb?.wrapper || "",
      attempts: adbDetection.adb?.attempts || [],
      devices: adbDetection.devices || [],
      devicesResult: adbDetection.devicesResult || null,
    });
    if (!adbDetection.adb?.available) {
      pendingResult = completePending(ctx, adbDetection.reason || "adb is unavailable", observations);
      return pendingResult;
    }
    if (!adbDetection.available || !adbDetection.selected) {
      pendingResult = completePending(ctx, adbDetection.reason || "no connected adb device/emulator", observations);
      return pendingResult;
    }
    const adbInfo = adbDetection.adb;
    const serial = adbDetection.selected.serial;
    observations.device = await getDeviceInfo(adbInfo, serial);
    ctx.result.target = {
      apk: observations.apk,
      packageName,
      activityName,
      deviceSerial: serial,
    };
    ctx.result.engine.adb = {
      displayPath: adbInfo.displayPath,
      wrapper: adbInfo.wrapper || "",
      version: adbInfo.version,
    };

    ctx.addAssertion("adb available", true, adbInfo.displayPath);
    ctx.addAssertion(
      `connected adb ${deviceKind === "any" ? "device/emulator" : deviceKind}`,
      true,
      `${observations.device.model || serial} Android ${observations.device.androidVersion || "unknown"}`,
    );
    ctx.addAssertion("APK exists", observations.apk.exists, apkPath, observations.apk);
    if (!observations.apk.exists) throw new Error(`APK does not exist: ${apkPath}`);
    if (observations.apk.expectedSha256) {
      ctx.addAssertion(
        "APK sha256 matches release metadata",
        observations.apk.sha256MatchesMetadata === true,
        observations.apk.sha256MatchesMetadata ? observations.apk.sha256 : `expected ${observations.apk.expectedSha256}, got ${observations.apk.sha256}`,
        observations.apk,
      );
    }
    ctx.completePhase("boot", "passed", "adb/device/APK ready");

    currentPhase = "observe";
    ctx.startPhase("observe", "install and launch APK");
    await runAdb(adbInfo, ["logcat", "-c"], { serial, timeoutMs: 10000 }).catch(() => {});
    observations.install = await installApk(adbInfo, serial, apkPath, packageName);
    ctx.addAssertion("install APK", observations.install.ok, observations.install.ok ? "adb install succeeded" : "adb install failed", observations.install);
    if (!observations.install.ok) throw new Error("adb install failed");
    if (process.env.WASM_AGENT_SIM_ANDROID_PRESERVE_DATA !== "1") {
      const clear = await adbText(adbInfo, serial, ["shell", "pm", "clear", packageName], { timeoutMs: 20000 });
      observations.clearData = compactCommandResult(clear);
    }
    const launch = await launchApp(adbInfo, serial, packageName, activityName);
    observations.launch = {
      ok: launch.status === 0 && !/Error:/i.test(resultText(launch)),
      result: compactCommandResult(launch),
    };
    ctx.addAssertion("launch APK", observations.launch.ok, observations.launch.ok ? "activity started" : "activity launch failed", observations.launch);
    if (!observations.launch.ok) throw new Error("APK launch failed");
    const proofOrigin = observations.apk.serverUrl || process.env.WASM_AGENT_SIM_URL || "https://wa.colmeio.com";
    const firstScreen = await waitForLoginButton(ctx, adbInfo, serial, "first-screen", Number(process.env.WASM_AGENT_SIM_ANDROID_BOOT_WAIT_MS || DEFAULT_WAIT_BOOT_MS), {
      packageName,
      origin: proofOrigin,
    });
    observations.firstScreen = summarizeSnapshot(firstScreen);
    observations.firstScreen.loginButton = firstScreen.loginButton ? {
      text: firstScreen.loginButton.text,
      bounds: firstScreen.loginButton.bounds,
      source: firstScreen.loginButton.source || "uiautomator",
    } : null;
    const firstScreenReady = firstScreenLoginVisible(observations.firstScreen);
    ctx.addAssertion(
      "first screen has Sign in with Google",
      firstScreenReady,
      firstScreen.loginButton
        ? `button visible and tappable via ${firstScreen.loginButton.source || "uiautomator"}`
        : firstScreenReady
          ? "button visible by renderer readiness, but no tap target was available"
          : (observations.firstScreen.firstScreenClassification?.reason || "button was not found in UIAutomator dump"),
      observations.firstScreen,
    );
    ctx.completePhase("observe", firstScreenReady ? "passed" : "failed", "first screen captured");
    if (!firstScreenReady) throw new Error(`Sign in with Google button was not found: ${observations.firstScreen.firstScreenClassification?.state || "unknown"} - ${observations.firstScreen.firstScreenClassification?.reason || "no readiness evidence"}`);

    currentPhase = "act";
    ctx.startPhase("act", "tap Sign in with Google and observe external handoff");
    const tap = await tapLoginButton(adbInfo, serial, firstScreen.loginButton);
    observations.tap = compactCommandResult(tap);
    ctx.addAssertion("tap Sign in with Google", tap.status === 0, tap.status === 0 ? "tap sent" : "tap command failed", observations.tap);
    if (tap.status !== 0) throw new Error("tap command failed");
    await sleep(2000);
    observations.firstTap = await observeAfterTap(ctx, adbInfo, serial, "first-tap", Number(process.env.WASM_AGENT_SIM_ANDROID_AFTER_TAP_WAIT_MS || DEFAULT_WAIT_AFTER_TAP_MS));
    observations.chooserResult = observations.firstTap.classification.chooser;
    observations.googleHostResult = observations.firstTap.classification.google;
    observations.androidAuthSession = observations.firstTap.classification.google?.androidAuthSession || "";
    observations.nativeCorrelationId = observations.firstTap.classification.google?.nativeCorrelationId || "";
    addTapAssertions(ctx, "first tap", observations.firstTap);
    ctx.completePhase("act", observations.firstTap.classification.passed ? "passed" : "failed", assertionDetailForTap(observations.firstTap.classification));

    currentPhase = "assert";
    ctx.startPhase("assert", "cancel browser handoff, verify retry, and collect post-auth proof when requested");
    observations.cancelRetryResult = await runCancelRetry(
      ctx,
      adbInfo,
      serial,
      packageName,
      activityName,
      observations.firstTap.classification.passed,
      proofOrigin,
    );
    ctx.addAssertion(
      "cancel/return makes Google sign-in retryable",
      observations.cancelRetryResult.returnedToApp && observations.cancelRetryResult.buttonRetryable && !observations.cancelRetryResult.staleOpeningMessage,
      observations.cancelRetryResult.reason || `returned=${observations.cancelRetryResult.returnedToApp} retryable=${observations.cancelRetryResult.buttonRetryable} stale=${observations.cancelRetryResult.staleOpeningMessage}`,
      observations.cancelRetryResult,
    );
    if (observations.cancelRetryResult.retryTap) addTapAssertions(ctx, "retry tap", observations.cancelRetryResult.retryTap);
    if (!observations.androidAuthSession) {
      observations.androidAuthSession = observations.cancelRetryResult.retryTap?.classification?.google?.androidAuthSession || "";
    }
    if (!observations.nativeCorrelationId) {
      observations.nativeCorrelationId = observations.cancelRetryResult.retryTap?.classification?.google?.nativeCorrelationId || "";
    }
    ctx.addAssertion(
      "retry tap does not stay stuck",
      Boolean(observations.cancelRetryResult.passed),
      observations.cancelRetryResult.passed ? "retry opened Google evidence again" : (observations.cancelRetryResult.reason || "retry did not produce Google evidence"),
      observations.cancelRetryResult,
    );
    observations.oauthCompletionResult = await runOAuthCompletionProof(ctx, adbInfo, serial, {
      packageName,
      origin: proofOrigin,
      sessionId: observations.androidAuthSession,
      oauthWaitMs: options.oauthWaitMs,
    });
    addOAuthCompletionAssertions(ctx, observations.oauthCompletionResult);
    observations.nativeCorrelationId = observations.nativeCorrelationId
      || observations.oauthCompletionResult.debug?.payload?.native_correlation_id
      || observations.oauthCompletionResult.debug?.payload?.payload?.native_correlation_id
      || "";
    observations.nativeDiagnostics = await collectNativeDiagnosticsLatest(ctx, adbInfo, serial, packageName, proofOrigin);
    ctx.addAssertion(
      "native diagnostics latest.json attached",
      Boolean(observations.nativeDiagnostics?.ok && observations.nativeDiagnostics?.artifact),
      observations.nativeDiagnostics?.ok ? observations.nativeDiagnostics.artifact : "latest.json was not available",
      observations.nativeDiagnostics,
    );
    observations.serverCorrelationLogs = observations.androidAuthSession
      ? await collectServerCorrelationLogs(ctx, proofOrigin, observations.androidAuthSession, observations.nativeCorrelationId)
      : { ok: false, reason: "missing Android auth session" };
    ctx.addAssertion(
      "server correlation logs attached",
      Boolean(observations.serverCorrelationLogs?.ok && observations.serverCorrelationLogs?.artifact),
      observations.serverCorrelationLogs?.ok ? observations.serverCorrelationLogs.artifact : (observations.serverCorrelationLogs?.reason || "server debug record unavailable"),
      observations.serverCorrelationLogs,
    );
    observations.logcatExcerpt = await collectLogcatExcerpt(ctx, adbInfo, serial, "final");
    ctx.addAssertion(
      "logcat excerpt attached",
      Boolean(observations.logcatExcerpt?.ok && observations.logcatExcerpt?.artifact),
      observations.logcatExcerpt?.ok ? observations.logcatExcerpt.artifact : "logcat excerpt unavailable",
      observations.logcatExcerpt,
    );
    observations.runtimeVerified = true;
    observations.fullOAuthRuntimeVerified = observations.oauthCompletionResult.status === "passed";
    const hasFailed = ctx.result.assertions.some((assertion) => assertion.status === "failed");
    const hasPending = ctx.result.assertions.some((assertion) => assertion.status === "pending");
    ctx.completePhase("assert", hasFailed ? "failed" : hasPending ? "pending" : "passed", "Android runtime assertions evaluated");
  } catch (error) {
    ctx.addError(error, currentPhase);
    const phase = ctx.phase(currentPhase);
    if (phase && phase.status === "running") ctx.completePhase(currentPhase, "failed", error.message || String(error));
    if (!ctx.result.assertions.some((assertion) => assertion.status === "failed")) {
      ctx.addAssertion("Android simulation completed", false, error.message || String(error));
    }
  } finally {
    if (!pendingResult) {
      currentPhase = "collect evidence";
      ctx.startPhase("collect evidence", "write final logs and observations");
      try {
        ctx.result.evidence.observations = redactValue(observations);
      } catch (error) {
        ctx.addError(error, "collect evidence");
      }
      ctx.completePhase("collect evidence", ctx.result.errors.some((error) => error.phase === "collect evidence") ? "failed" : "passed", "artifacts collected");

      currentPhase = "score";
      ctx.startPhase("score", "score assertions");
      ctx.score();
      observations.finalScore = ctx.result.score;
      observations.failureClassification = classifyAndroidOAuthFailure(observations);
      observations.reportSummary = finalReportSummary(ctx, observations);
      ctx.result.evidence.observations = redactValue(observations);
      ctx.writeJsonArtifact("observations", "logs/observations.json", observations);
      ctx.completePhase("score", "passed", `status=${ctx.result.status} score=${ctx.result.score == null ? "n/a" : ctx.result.score}`);

      currentPhase = "report";
      ctx.startPhase("report", "write result.json and summary.md");
      ctx.report();
      ctx.completePhase("report", "passed", "reports written");
      ctx.report();
    }
  }

  console.log(`horc simulate android: ${ctx.result.status}${ctx.result.score == null ? "" : ` (${ctx.result.score}/100)`}`);
  console.log(`  report: ${ctx.reportDir}/summary.md`);
  return ctx.result;
}

function fixtureSnapshot(fixture, key) {
  const item = fixture[key] || {};
  const uiText = item.uiText || "";
  const activityText = item.activityText || "";
  const windowText = item.windowText || "";
  const logcatText = item.logcatText || "";
  const snapshot = {
    label: key,
    at: new Date().toISOString(),
    uiText,
    activityText,
    windowText,
    logcatText,
    topActivity: extractTopActivity(activityText),
    currentFocus: extractCurrentFocus(windowText),
    loginButton: item.loginButton || (uiText.includes(LOGIN_BUTTON_TEXT) ? { text: LOGIN_BUTTON_TEXT, bounds: parseBounds("[90,600][990,690]") } : null),
    nativeDiagnostics: item.nativeDiagnostics || null,
    artifacts: item.artifacts || {},
  };
  snapshot.firstScreenClassification = classifyFirstScreenState(snapshot);
  snapshot.loginButton = snapshot.loginButton || loginButtonFromRendererReadiness(snapshot);
  return snapshot;
}

function fixtureOAuthCompletionResult(fixture, packageName = DEFAULT_PACKAGE) {
  const item = fixture.postAuth || fixture.oauthCompletion || {};
  const snapshot = {
    label: "postAuth",
    at: new Date().toISOString(),
    uiText: item.uiText || "",
    activityText: item.activityText || "",
    windowText: item.windowText || "",
    topText: item.topText || "",
    logcatText: item.logcatText || "",
    topActivity: extractTopActivity(item.activityText || ""),
    currentFocus: extractCurrentFocus(item.windowText || ""),
  };
  const debug = item.serverDebug || item.debug || {};
  const classification = classifyOAuthCompletionEvidence(snapshot, debug, packageName);
  const explicitStatus = String(item.status || "").trim().toLowerCase();
  const status = explicitStatus || (classification.passed ? "passed" : classification.browserHome.detected ? "failed" : "pending");
  return {
    attempted: Boolean(Object.keys(item).length),
    waitMs: 0,
    session: item.session || "",
    origin: item.origin || "https://wa.colmeio.com",
    status,
    reason: item.reason || (classification.passed ? "fixture post-auth native return passed" : oauthCompletionDetail({ classification })),
    classification,
    decisiveSnapshot: summarizeSnapshot(snapshot),
    debug: { ok: true, payload: debug },
  };
}

async function runFixtureAndroidSimulation(ctx, fixtureName) {
  const fixturePath = path.join(FIXTURE_DIR, `${fixtureName}.json`);
  const observations = {
    fixture: fixtureName,
    fixturePath,
    runtimeVerified: false,
    buildSuccessIsRuntimeVerification: false,
  };
  try {
    ctx.startPhase("boot", "load Android simulator fixture");
    if (!fs.existsSync(fixturePath)) throw new Error(`Android simulator fixture not found: ${fixtureName}`);
    const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
    observations.device = fixture.device || { model: "fixture", androidVersion: "fixture" };
    observations.apk = fixture.apk || { path: DEFAULT_ANDROID_APK, buildId: "fixture", sha256: "fixture" };
    observations.install = { ok: true, fixture: true };
    observations.launch = { ok: true, fixture: true };
    ctx.result.target = { fixture: fixtureName, apk: observations.apk };
    ctx.writeJsonArtifact("fixture", "logs/fixture.json", fixture);
    ctx.completePhase("boot", "passed", `fixture ${fixtureName} loaded`);

    ctx.startPhase("observe", "fixture first screen");
    const firstScreen = fixtureSnapshot(fixture, "firstScreen");
    observations.firstScreen = summarizeSnapshot(firstScreen);
    observations.firstScreen.loginButton = firstScreen.loginButton;
    ctx.writeTextArtifact("ui", "ui/fixture-first-screen.txt", firstScreen.uiText);
    const firstScreenReady = firstScreenLoginVisible(observations.firstScreen);
    ctx.addAssertion("fixture first screen has Sign in with Google", firstScreenReady, firstScreenReady ? "button visible" : "button missing", observations.firstScreen);
    ctx.completePhase("observe", firstScreenReady ? "passed" : "failed", "fixture first screen evaluated");

    ctx.startPhase("act", "fixture first tap evidence");
    const firstTapSnapshot = fixtureSnapshot(fixture, "firstTap");
    const firstTapClassification = classifyTapEvidence(firstTapSnapshot);
    observations.firstTap = {
      classification: firstTapClassification,
      decisiveSnapshot: summarizeSnapshot(firstTapSnapshot),
    };
    observations.chooserResult = firstTapClassification.chooser;
    observations.googleHostResult = firstTapClassification.google;
    ctx.writeTextArtifact("activityDump", "activity/fixture-first-tap-activity.txt", firstTapSnapshot.activityText);
    ctx.writeTextArtifact("windowDump", "activity/fixture-first-tap-window.txt", firstTapSnapshot.windowText);
    ctx.writeTextArtifact("ui", "ui/fixture-first-tap.txt", firstTapSnapshot.uiText);
    addTapAssertions(ctx, "first tap", observations.firstTap);
    ctx.completePhase("act", firstTapClassification.passed ? "passed" : "failed", assertionDetailForTap(firstTapClassification));

    ctx.startPhase("assert", "fixture cancel/retry evidence");
    const cancelRetry = fixture.cancelRetry || {};
    observations.cancelRetryResult = {
      attempted: Boolean(cancelRetry.attempted),
      returnedToApp: Boolean(cancelRetry.returnedToApp),
      buttonRetryable: Boolean(cancelRetry.buttonRetryable),
      staleOpeningMessage: Boolean(cancelRetry.staleOpeningMessage),
      passed: Boolean(cancelRetry.passed),
      reason: cancelRetry.reason || "",
    };
    ctx.addAssertion(
      "cancel/return makes Google sign-in retryable",
      observations.cancelRetryResult.returnedToApp && observations.cancelRetryResult.buttonRetryable && !observations.cancelRetryResult.staleOpeningMessage,
      observations.cancelRetryResult.reason || `returned=${observations.cancelRetryResult.returnedToApp} retryable=${observations.cancelRetryResult.buttonRetryable} stale=${observations.cancelRetryResult.staleOpeningMessage}`,
      observations.cancelRetryResult,
    );
    ctx.addAssertion(
      "retry tap does not stay stuck",
      observations.cancelRetryResult.passed,
      observations.cancelRetryResult.passed ? "fixture retry passed" : (observations.cancelRetryResult.reason || "fixture retry failed"),
      observations.cancelRetryResult,
    );
    observations.oauthCompletionResult = fixtureOAuthCompletionResult(fixture);
    if (fixture.expectedPostAuthRedirectClassification) {
      const actualPostAuthClass = observations.oauthCompletionResult.classification?.postAuthRedirectClassification || "";
      ctx.addAssertion(
        "fixture post-auth redirect classification matches expected",
        actualPostAuthClass === fixture.expectedPostAuthRedirectClassification,
        `expected=${fixture.expectedPostAuthRedirectClassification} actual=${actualPostAuthClass || "missing"}`,
        observations.oauthCompletionResult.classification,
      );
    }
    ctx.writeTextArtifact("activityDump", "activity/fixture-post-auth-activity.txt", fixture.postAuth?.activityText || "");
    ctx.writeTextArtifact("windowDump", "activity/fixture-post-auth-window.txt", fixture.postAuth?.windowText || "");
    ctx.writeTextArtifact("ui", "ui/fixture-post-auth.txt", fixture.postAuth?.uiText || "");
    addOAuthCompletionAssertions(ctx, observations.oauthCompletionResult);
    const fixtureNativeDiagnostics = fixture.nativeDiagnostics || {
      schema: "hermes.wasm_agent.android_native_diagnostics.v1",
      current_webview_url: fixture.postAuth?.webViewUrl || "https://wa.colmeio.com/home?native=android",
      android_auth_session: observations.oauthCompletionResult.session || observations.firstTap.classification.google.androidAuthSession || "fixture-session",
      native_correlation_id: fixture.postAuth?.nativeCorrelationId || "fixture-correlation",
      oauth: {
        stage: observations.oauthCompletionResult.classification?.authenticatedWebView ? "AUTHENTICATED_UI_SEEN" : "AUTH_ERROR",
        result: observations.oauthCompletionResult.reason || "",
      },
      safe_cookie_session_summary: {
        cookie_count: observations.oauthCompletionResult.classification?.authenticatedWebView ? 1 : 0,
        has_wa_uid: Boolean(observations.oauthCompletionResult.classification?.authenticatedWebView),
      },
    };
    const nativeDiagnosticsArtifact = ctx.writeJsonArtifact("nativeDiagnostics", "logs/native-diagnostics-latest.json", fixtureNativeDiagnostics);
    observations.nativeDiagnostics = {
      ok: true,
      source: "fixture",
      artifact: ctx.artifactRef(nativeDiagnosticsArtifact),
      payload: fixtureNativeDiagnostics,
    };
    ctx.addAssertion("native diagnostics latest.json attached", true, observations.nativeDiagnostics.artifact, observations.nativeDiagnostics);
    const serverCorrelationArtifact = ctx.writeJsonArtifact("serverCorrelationLogs", "logs/server-correlation-auth-debug.json", observations.oauthCompletionResult.debug || {});
    observations.serverCorrelationLogs = { ok: true, source: "fixture", artifact: ctx.artifactRef(serverCorrelationArtifact) };
    ctx.addAssertion("server correlation logs attached", true, observations.serverCorrelationLogs.artifact, observations.serverCorrelationLogs);
    const logcatArtifact = ctx.writeTextArtifact("logcat", "logs/fixture-native-logcat-excerpt.txt", [
      fixture.firstTap?.logcatText || "",
      fixture.postAuth?.logcatText || "",
    ].filter(Boolean).join("\n"));
    observations.logcatExcerpt = { ok: true, source: "fixture", artifact: ctx.artifactRef(logcatArtifact) };
    ctx.addAssertion("logcat excerpt attached", true, observations.logcatExcerpt.artifact, observations.logcatExcerpt);
    const hasFailed = ctx.result.assertions.some((assertion) => assertion.status === "failed");
    const hasPending = ctx.result.assertions.some((assertion) => assertion.status === "pending");
    ctx.completePhase("assert", hasFailed ? "failed" : hasPending ? "pending" : "passed", "fixture assertions evaluated");
  } catch (error) {
    ctx.addError(error, "fixture");
    ctx.addAssertion("Android fixture simulation completed", false, error.message || String(error));
  } finally {
    ctx.startPhase("collect evidence", "write fixture observations");
    ctx.result.evidence.observations = redactValue(observations);
    ctx.completePhase("collect evidence", "passed", "fixture artifacts collected");

    ctx.startPhase("score", "score fixture assertions");
    ctx.score();
    observations.finalScore = ctx.result.score;
    observations.failureClassification = classifyAndroidOAuthFailure(observations);
    observations.reportSummary = finalReportSummary(ctx, observations);
    ctx.result.evidence.observations = redactValue(observations);
    ctx.writeJsonArtifact("observations", "logs/observations.json", observations);
    ctx.completePhase("score", "passed", `status=${ctx.result.status} score=${ctx.result.score == null ? "n/a" : ctx.result.score}`);

    ctx.startPhase("report", "write result.json and summary.md");
    ctx.report();
    ctx.completePhase("report", "passed", "reports written");
    ctx.report();
  }
  console.log(`horc simulate android fixture ${fixtureName}: ${ctx.result.status}${ctx.result.score == null ? "" : ` (${ctx.result.score}/100)`}`);
  console.log(`  report: ${ctx.reportDir}/summary.md`);
  return ctx.result;
}

async function runVoiceWakeFixtureSimulation(ctx, fixtureName) {
  const fixturePath = path.join(FIXTURE_DIR, "voice", `${fixtureName}.json`);
  const observations = {
    fixture: fixtureName,
    fixturePath,
    runtimeVerified: false,
    buildSuccessIsRuntimeVerification: false,
    voiceWake: true,
  };
  try {
    ctx.startPhase("boot", "load Android voice wake fixture");
    if (!fs.existsSync(fixturePath)) throw new Error(`Android voice wake fixture not found: ${fixtureName}`);
    const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
    observations.device = fixture.device || { model: "fixture", androidVersion: "fixture" };
    observations.apk = fixture.apk || { path: DEFAULT_ANDROID_APK, buildId: "fixture", sha256: "fixture" };
    observations.voice = fixture.voice || {};
    observations.nativeDiagnostics = fixture.nativeDiagnostics || {};
    observations.nativeEvent = fixture.nativeEvent || {};
    observations.timeline = fixture.timeline || {};
    observations.logs = fixture.logs || {};
    ctx.result.target = { fixture: fixtureName, apk: observations.apk, voiceWake: true };
    ctx.writeJsonArtifact("fixture", "logs/voice-fixture.json", fixture);
    ctx.writeJsonArtifact("nativeDiagnostics", "logs/native-voice-diagnostics.json", observations.nativeDiagnostics);
    ctx.writeJsonArtifact("nativeEvent", "logs/native-voice-event.json", observations.nativeEvent);
    ctx.writeTextArtifact("logcat", "logs/voice-logcat-redacted.txt", observations.logs.logcatText || "");
    ctx.completePhase("boot", "passed", `voice fixture ${fixtureName} loaded`);

    ctx.startPhase("assert", "evaluate Android voice wake evidence");
    const voice = observations.voice || {};
    const diagnostics = observations.nativeDiagnostics?.voice_wake || observations.nativeDiagnostics || {};
    const payload = observations.nativeEvent?.payload || observations.nativeEvent || {};
    const transcript = String(payload.transcript || voice.transcript || "");
    const logText = String(observations.logs?.logcatText || "");
    const hasSecretLeak = /(access_token|auth_code|refresh_token|Authorization: Bearer|Cookie:|wa_uid=|audio_pcm|continuous background audio)/i.test(logText);
    const expected = fixture.expected || { voiceCommandEvent: true, wakeDetected: true, transcriptionProduced: true, timelineShowsVoiceCommand: true };
    ctx.addAssertion("foreground service started", Boolean(voice.foregroundServiceStarted || diagnostics.foreground_service_running), "foreground microphone service evidence", { voice, diagnostics });
    ctx.addAssertion("microphone permission state known", typeof voice.permissionGranted === "boolean" || typeof diagnostics.permission_record_audio === "boolean", "permission state captured", { voice, diagnostics });
    const didWake = Boolean(voice.wakeDetected || diagnostics.last_wake_at);
    const producedTranscript = transcript.length > 0;
    const emittedVoiceCommand = payload.type === "voice_command" && payload.source === "android_native_hermes_voice_wake" && payload.audio_retained === false;
    const timelineShowsVoiceCommand = Boolean(observations.timeline?.showsVoiceCommand);
    ctx.addAssertion("wake detected", expected.wakeDetected === false ? !didWake : didWake, expected.wakeDetected === false ? "no wake expected" : "Hermes wake detection evidence", { voice, diagnostics });
    ctx.addAssertion("transcription produced", expected.transcriptionProduced === false ? !producedTranscript : producedTranscript, transcript || "missing transcript", { transcript });
    ctx.addAssertion("voice_command event reached wasm-agent", expected.voiceCommandEvent === false ? !emittedVoiceCommand : emittedVoiceCommand, "structured native voice event stored", payload);
    ctx.addAssertion("UI timeline shows event", expected.timelineShowsVoiceCommand === false ? !timelineShowsVoiceCommand : timelineShowsVoiceCommand, "timeline evidence captured", observations.timeline);
    if (expected.diagnosticState) {
      ctx.addAssertion("diagnostic state matches expected", diagnostics.state === expected.diagnosticState, `expected=${expected.diagnosticState} actual=${diagnostics.state || "missing"}`, diagnostics);
    }
    if (expected.lastError) {
      ctx.addAssertion("diagnostic error matches expected", String(diagnostics.last_error || "").includes(expected.lastError), `expected error includes ${expected.lastError}`, diagnostics);
    }
    ctx.addAssertion("logs are redacted", !hasSecretLeak, hasSecretLeak ? "sensitive data found in logs" : "no secret/audio payload leak markers", { logText: logText.slice(0, 2000) });
    ctx.completePhase("assert", ctx.result.assertions.some((assertion) => assertion.status === "failed") ? "failed" : "passed", "voice wake assertions evaluated");
  } catch (error) {
    ctx.addError(error, "voice-wake-fixture");
    ctx.addAssertion("Android voice wake fixture simulation completed", false, error.message || String(error));
  } finally {
    ctx.startPhase("collect evidence", "write voice wake observations");
    ctx.result.evidence.observations = redactValue(observations);
    ctx.completePhase("collect evidence", "passed", "voice wake artifacts collected");
    ctx.startPhase("score", "score voice wake assertions");
    ctx.score();
    observations.finalScore = ctx.result.score;
    observations.missingAssertions = REQUIRED_ANDROID_VOICE_ASSERTIONS.filter((name) => !ctx.result.assertions.some((assertion) => assertion.name === name));
    ctx.result.evidence.observations = redactValue(observations);
    ctx.writeJsonArtifact("observations", "logs/voice-observations.json", observations);
    ctx.completePhase("score", "passed", `status=${ctx.result.status} score=${ctx.result.score == null ? "n/a" : ctx.result.score}`);
    ctx.startPhase("report", "write result.json and summary.md");
    ctx.report();
    ctx.completePhase("report", "passed", "reports written");
    ctx.report();
  }
  console.log(`horc simulate android --voice-wake ${fixtureName}: ${ctx.result.status}${ctx.result.score == null ? "" : ` (${ctx.result.score}/100)`}`);
  console.log(`  report: ${ctx.reportDir}/summary.md`);
  return ctx.result;
}

async function runAndroidSimulation(options = {}) {
  const fixtureName = process.env.WASM_AGENT_SIM_ANDROID_FIXTURE || "";
  const voiceWakeFixture = options.voiceWakeFixture || process.env.WASM_AGENT_SIM_ANDROID_VOICE_WAKE || "";
  const backend = options.backend || "auto";
  const ctx = new SimulationContext({
    platform: "android",
    command: options.command || "horc simulate android",
    engine: voiceWakeFixture
      ? {
          name: "android-voice-wake-fixture",
          fixture: voiceWakeFixture,
          description: "Fixture evidence for Android Hermes Voice Wake.",
        }
      : fixtureName
      ? {
          name: "android-fixture",
          fixture: fixtureName,
          description: "Classifier fixture for Android simulator evidence.",
        }
      : backend === "local-report"
        ? {
            name: "android-local-report",
            description: "Validates a copied Android device/emulator report from another machine.",
          }
      : backend === "emulator"
        ? {
            name: "android-emulator",
            description: "Attempts host/Docker Android emulator bootstrap, then runs ADB/UIAutomator evidence.",
          }
      : backend === "device"
        ? {
            name: "adb-uiautomator-device",
            description: "ADB install/launch against a physical connected device.",
          }
      : {
          name: "adb-uiautomator",
          description: "ADB install/launch with UIAutomator, logcat, screencap, dumpsys activity/window evidence.",
        },
  });
  if (voiceWakeFixture) return runVoiceWakeFixtureSimulation(ctx, voiceWakeFixture);
  if (fixtureName) return runFixtureAndroidSimulation(ctx, fixtureName);
  if (backend === "local-report") return runLocalReportAndroidSimulation(ctx, options.localReportPath || "");
  if (backend === "emulator") return runEmulatorAndroidSimulation(ctx, options);
  return runLiveAndroidSimulation(ctx, options);
}

module.exports = {
  DEFAULT_ACTIVITY,
  DEFAULT_ANDROID_APK,
  DEFAULT_PACKAGE,
  androidDeviceKind,
  classifyAndroidOAuthFailure,
  classifyTapEvidence,
  classifyOAuthCompletionEvidence,
  detectAdbDevice,
  parseDevices,
  parseUiXml,
  runAndroidSimulation,
  resolveAdb,
};
