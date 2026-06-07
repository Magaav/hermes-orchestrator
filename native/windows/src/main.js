const { app, BrowserWindow, Menu, ipcMain, protocol, session, shell } = require("electron");
const fs = require("fs");
const crypto = require("crypto");
const os = require("os");
const path = require("path");
const { execFile, spawn } = require("child_process");
const {
  APP_ID,
  DEFAULT_SERVER_URL,
  PWA_HOME_PATH,
  chromeLikeUserAgent,
  isGoogleAuthUrl,
  normalizeServerUrl,
  payloadIdentifiesWasmAgent,
  payloadIdentifiesWrongApp,
  sameOrigin,
} = require("./native-shell-policy");
const {
  selectPreferredBackendResult,
  validateWasmAgentOrigin,
} = require("./native-backend-resolver");

const HEARTBEAT_INTERVAL_MS = 30_000;
const NATIVE_CONTROL_POLL_INTERVAL_MS = 15_000;
const AUTH_COOKIE_WAIT_TIMEOUT_MS = 5000;
const AUTH_COOKIE_WAIT_INTERVAL_MS = 200;
const NATIVE_APP_ORIGIN = "wasm-agent://app";
const NATIVE_APP_HOME_URL = `${NATIVE_APP_ORIGIN}/home`;
const WINDOWS_ANDROID_OAUTH_OPERATIONS = new Set([
  "adb_version",
  "adb_devices",
  "verify_android_oauth",
  "read_latest_android_report",
  "open_latest_android_report",
]);
let selectedBackendOrigin = "";
let nativeControlPollBusy = false;
let lastReloadCommand = null;
let activeAndroidOAuthVerification = null;
const startupDiagnostics = {
  appRoot: "",
  resourcesPath: "",
  startUrl: NATIVE_APP_HOME_URL,
  uiSource: "bundled-assets",
  bundledPublicRoot: "",
  resolvedBackendOrigin: "",
  candidateOrigins: [],
  originChecks: [],
  candidateEntries: [],
  discardedCandidateOrigins: [],
  savedConfigRawJson: "",
  savedConfigUserExplicit: undefined,
  finalSelectedOrigin: "",
  currentRoute: "",
  configSource: "bundled-native-config",
  lastTestedUrl: "",
  lastFailureReason: null,
};

protocol.registerSchemesAsPrivileged([
  {
    scheme: "wasm-agent",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
      stream: true,
    },
  },
]);

function configPath() {
  return path.join(app.getPath("userData"), "config.json");
}

function readConfig() {
  try {
    const parsed = JSON.parse(fs.readFileSync(configPath(), "utf8"));
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function readConfigRaw() {
  try {
    return fs.readFileSync(configPath(), "utf8");
  } catch {
    return "";
  }
}

function nativeDefaultsPath() {
  const candidates = [
    path.join(process.resourcesPath || "", "native-defaults.json"),
    path.join(__dirname, "native-defaults.json"),
    path.join(__dirname, "build", "native-defaults.json"),
  ];
  return candidates.find((candidate) => candidate && fs.existsSync(candidate)) || candidates[0];
}

function readNativeDefaults() {
  try {
    const parsed = JSON.parse(fs.readFileSync(nativeDefaultsPath(), "utf8"));
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function appAsarPath() {
  const candidates = [
    path.join(process.resourcesPath || "", "app.asar"),
    __filename,
  ];
  return candidates.find((candidate) => candidate && fs.existsSync(candidate)) || "";
}

function sha256File(filePath) {
  try {
    return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
  } catch {
    return "";
  }
}

function readJsonFile(filePath, fallback = {}) {
  try {
    const parsed = JSON.parse(fs.readFileSync(filePath, "utf8"));
    return parsed && typeof parsed === "object" ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function nativeDefaultsDiagnostics(defaults = readNativeDefaults()) {
  return {
    path: nativeDefaultsPath(),
    serverUrl: normalizeServerUrl(defaults.serverUrl || DEFAULT_SERVER_URL),
    serverUrlCandidates: Array.isArray(defaults.serverUrlCandidates) ? defaults.serverUrlCandidates : [],
  };
}

function uniqueServerUrlList(values) {
  const urls = [];
  values.forEach((value) => {
    const url = normalizeServerUrl(value);
    if (!url) return;
    if (!urls.some((existing) => existing.toLowerCase() === url.toLowerCase())) urls.push(url);
  });
  return urls;
}

function isLegacyLocalDefaultUrl(value) {
  const normalized = normalizeServerUrl(value, "");
  return normalized === loopbackDevServerUrl() || normalized === localhostDevServerUrl();
}

function loopbackDevServerUrl() {
  return ["http://127.0.0.1:", "8877"].join("");
}

function localhostDevServerUrl() {
  return ["http://localhost:", "8877"].join("");
}

function hasExplicitCustomServer(existing = {}) {
  return existing.userExplicit === true;
}

function allowLocalDevCandidates() {
  return String(process.env.WASM_AGENT_ALLOW_LOCAL_DEV || "").trim() === "1";
}

function isProductionBackendMode() {
  return !allowLocalDevCandidates();
}

function isLocalDevCandidateUrl(value) {
  const normalized = normalizeServerUrl(value, "");
  if (!normalized) return false;
  try {
    const hostname = new URL(normalized).hostname.toLowerCase();
    if (hostname === "localhost" || hostname === "0.0.0.0" || hostname === "::1" || hostname === "[::1]") return true;
    if (hostname === "host.docker.internal" || hostname.endsWith(".local")) return true;
    if (hostname.startsWith("127.")) return true;
    if (hostname.startsWith("10.")) return true;
    if (hostname.startsWith("192.168.")) return true;
    const match = hostname.match(/^172\.(\d+)\./);
    return Boolean(match && Number(match[1]) >= 16 && Number(match[1]) <= 31);
  } catch {
    return false;
  }
}

function candidateSourceEntries(existing = readConfig(), options = {}) {
  const defaults = readNativeDefaults();
  const defaultDiagnostics = nativeDefaultsDiagnostics(defaults);
  const allowLocal = allowLocalDevCandidates();
  const entries = [];
  const addEntry = (value, source) => {
    const url = normalizeServerUrl(value, "");
    if (!url) return;
    if (!allowLocal && isLocalDevCandidateUrl(url)) {
      const discarded = { serverUrl: url, source, reason: "discarded local dev backend in production" };
      startupDiagnostics.discardedCandidateOrigins.push(discarded);
      if (options.logDiscards) logNativeDiagnostic("discarded-local-dev-backend", discarded);
      return;
    }
    if (!entries.some((entry) => entry.serverUrl.toLowerCase() === url.toLowerCase())) entries.push({ serverUrl: url, source });
  };
  if (existing.serverUrl) addEntry(existing.serverUrl, hasExplicitCustomServer(existing) ? "saved-config" : "saved-auto");
  addEntry(defaultDiagnostics.serverUrl, "native-defaults.serverUrl");
  addEntry(DEFAULT_SERVER_URL, "packaged-default");
  [
    ["WASM_AGENT_DEFAULT_SERVER_URL", process.env.WASM_AGENT_DEFAULT_SERVER_URL],
    ["WASM_AGENT_URL", process.env.WASM_AGENT_URL],
    ["WASM_AGENT_SERVER_URL", process.env.WASM_AGENT_SERVER_URL],
    ["HERMES_WASM_AGENT_NATIVE_SERVER_URL", process.env.HERMES_WASM_AGENT_NATIVE_SERVER_URL],
    ["HERMES_WASM_AGENT_PUBLIC_URL", process.env.HERMES_WASM_AGENT_PUBLIC_URL],
    ["WASM_AGENT_PUBLIC_URL", process.env.WASM_AGENT_PUBLIC_URL],
  ].forEach(([name, value]) => addEntry(value, `env:${name}`));
  process.argv.forEach((arg) => {
    const match = String(arg || "").match(/^--wasm-agent-server-url=(.+)$/);
    if (match) addEntry(match[1], "command-line:--wasm-agent-server-url");
  });
  defaultDiagnostics.serverUrlCandidates.forEach((value, index) => addEntry(value, `native-defaults.serverUrlCandidates[${index}]`));
  if (allowLocal) {
    addEntry(localhostDevServerUrl(), "dev-fallback");
    addEntry(loopbackDevServerUrl(), "dev-fallback");
  }
  return entries;
}

function configuredServerUrlCandidates(existing = readConfig(), options = {}) {
  const entries = candidateSourceEntries(existing, options);
  startupDiagnostics.candidateEntries = entries;
  return entries.map((entry) => entry.serverUrl);
}

function candidateSourceFor(serverUrl, existing = readConfig()) {
  const normalized = normalizeServerUrl(serverUrl, "");
  return candidateSourceEntries(existing).find((entry) => entry.serverUrl === normalized)?.source || "";
}

function productionSafeServerUrl(value, fallback = DEFAULT_SERVER_URL, source = "unknown") {
  const normalized = normalizeServerUrl(value || fallback, fallback);
  if (isProductionBackendMode() && isLocalDevCandidateUrl(normalized)) {
    logNativeDiagnostic("discarded-local-dev-backend", {
      serverUrl: normalized,
      source,
      reason: "discarded local dev backend in production",
    });
    return DEFAULT_SERVER_URL;
  }
  return normalized;
}

function logNativeDiagnostic(kind, payload = {}) {
  const entry = { timestamp: new Date().toISOString(), kind, ...sanitizeRendererDiagnosticValue(payload) };
  appendJsonLine(nativeMainLogPath(), entry);
  console.log(`[wasm-agent:native] ${kind} ${JSON.stringify(entry)}`);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function writeConfig(next) {
  fs.mkdirSync(app.getPath("userData"), { recursive: true });
  fs.writeFileSync(configPath(), JSON.stringify(next, null, 2));
}

function migrateLegacyNativeConfig(existing = readConfig()) {
  const serverUrl = normalizeServerUrl(existing.serverUrl, "");
  if (!serverUrl || !isLegacyLocalDefaultUrl(serverUrl)) return existing;
  if (!isProductionBackendMode() && hasExplicitCustomServer(existing)) return existing;
  const migrated = {
    ...existing,
    serverUrl: "",
    serverUrlCandidates: [],
    legacyServerUrl: serverUrl,
    legacyServerUrlMigratedAt: new Date().toISOString(),
    userExplicit: false,
    savedCustomServerUrl: false,
  };
  try {
    writeConfig(migrated);
  } catch {
    // ensureConfig writes a fresh cloud-first config immediately after this migration.
  }
  logNativeDiagnostic("legacy-local-config-migrated", {
    legacyServerUrl: serverUrl,
    defaultServerUrl: DEFAULT_SERVER_URL,
  });
  return migrated;
}

function appAsarFingerprint() {
  const target = appAsarPath();
  try {
    const hash = sha256File(target).slice(0, 16);
    return `${path.basename(target)}:${hash}`;
  } catch {
    return "";
  }
}

function nativeAppDataDir() {
  const localAppData = process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
  return path.join(localAppData, "WASM Agent Native");
}

function nativeMainLogPath() {
  return path.join(nativeAppDataDir(), "main.log");
}

function rendererConsoleDiagnosticsPath() {
  return path.join(nativeAppDataDir(), "renderer-console.log");
}

function nativeControlAuditPath() {
  return path.join(nativeAppDataDir(), "native-control-audit.log");
}

function nativeFatalDiagnosticsPath() {
  return path.join(nativeAppDataDir(), "fatal-diagnostics.log");
}

function nativeDiagnosticsBundleRoot() {
  return path.join(nativeAppDataDir(), "native-diagnostics");
}

function appendJsonLine(filePath, payload = {}) {
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.appendFileSync(filePath, `${JSON.stringify(payload)}\n`);
  } catch {
    // Diagnostics must not interfere with app startup or command execution.
  }
}

function timestampForFilename() {
  return new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
}

function writeNativeControlAudit(event = {}) {
  const entry = {
    schema: "hermes.wasm_agent.native_control_local_audit.v1",
    timestamp: new Date().toISOString(),
    ...sanitizeRendererDiagnosticValue(event),
  };
  appendJsonLine(nativeControlAuditPath(), entry);
  return entry;
}

function execFileBounded(command, args = [], options = {}) {
  return new Promise((resolve) => {
    const startedAt = Date.now();
    execFile(command, args, {
      timeout: Number(options.timeoutMs || 8000),
      maxBuffer: Number(options.maxBuffer || 512 * 1024),
      cwd: options.cwd || undefined,
      env: options.env || process.env,
      windowsHide: true,
    }, (error, stdout, stderr) => {
      resolve({
        ok: !error,
        command: [command, ...args].join(" "),
        exitCode: typeof error?.code === "number" ? error.code : error ? 1 : 0,
        signal: error?.signal || "",
        timedOut: Boolean(error?.killed),
        elapsedMs: Date.now() - startedAt,
        stdout: clipDiagnosticText(stdout),
        stderr: clipDiagnosticText(stderr),
        error: error ? redactSensitiveText(String(error.message || error)) : "",
      });
    });
  });
}

function redactSensitiveText(value) {
  return String(value || "")
    .replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, "[redacted-email]")
    .replace(/\b(Bearer\s+)[A-Za-z0-9._~+/=-]+/gi, "$1[redacted]")
    .replace(/\b(ya29\.[A-Za-z0-9._-]+)/g, "[redacted-token]")
    .replace(/\b(eyJ[A-Za-z0-9._-]+\.[A-Za-z0-9._-]+\.[A-Za-z0-9._-]+)\b/g, "[redacted-token]")
    .replace(/((?:^|[?&#\s"'])(?:id_token|access_token|refresh_token|credential|auth_code|code|state|nonce|session|android_auth_session|native_correlation_id)=)[^&#\s"'<>)]*/gi, "$1[redacted]")
    .replace(/\b((?:Cookie|Set-Cookie|Authorization):\s*)[^\r\n]+/gi, "$1[redacted]");
}

function clipDiagnosticText(value, maxLength = 120_000) {
  const text = redactSensitiveText(value);
  if (text.length <= maxLength) return text;
  return `${text.slice(0, 2000)}\n...[clipped ${text.length - maxLength} chars]...\n${text.slice(-maxLength)}`;
}

function filterDiagnosticLines(text, pattern, maxLines = 300) {
  const regex = pattern instanceof RegExp ? pattern : /./;
  return String(text || "")
    .split(/\r?\n/)
    .filter((line) => regex.test(line))
    .slice(-maxLines)
    .join("\n");
}

async function findAdbExecutable() {
  const explicit = String(process.env.WASM_AGENT_ADB_PATH || "").trim();
  const candidates = [];
  if (explicit) candidates.push(explicit);
  try {
    const where = await execFileBounded(process.platform === "win32" ? "where.exe" : "which", ["adb"], { timeoutMs: 3000, maxBuffer: 64 * 1024 });
    if (where.ok) {
      String(where.stdout || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean).forEach((line) => candidates.push(line));
    }
  } catch {
    // Fall through to common paths.
  }
  candidates.push(
    path.join(os.homedir(), "Downloads", "platform-tools-latest-windows", "platform-tools", "adb.exe"),
    path.join(os.homedir(), "AppData", "Local", "Android", "Sdk", "platform-tools", "adb.exe"),
    "adb",
  );
  for (const candidate of candidates) {
    if (!candidate) continue;
    if (candidate === "adb") return candidate;
    try {
      if (fs.existsSync(candidate)) return candidate;
    } catch {
      // Ignore inaccessible paths.
    }
  }
  return "adb";
}

async function runAdbDiagnosticCommand(adbPath, args, options = {}) {
  const result = await execFileBounded(adbPath, args, {
    timeoutMs: options.timeoutMs || 8000,
    maxBuffer: options.maxBuffer || 1024 * 1024,
  });
  return sanitizeRendererDiagnosticValue(result);
}

async function collectAdbDiagnostics(options = {}) {
  const generatedAt = new Date().toISOString();
  const adbPath = await findAdbExecutable();
  const commandResults = {};
  commandResults.version = await runAdbDiagnosticCommand(adbPath, ["version"], { timeoutMs: 4000, maxBuffer: 128 * 1024 });
  commandResults.devices = await runAdbDiagnosticCommand(adbPath, ["devices", "-l"], { timeoutMs: 5000, maxBuffer: 128 * 1024 });
  const hasDevice = /\bdevice\b/.test(commandResults.devices?.stdout || "");
  if (hasDevice) {
    commandResults.packageWasmAgent = await runAdbDiagnosticCommand(adbPath, ["shell", "dumpsys", "package", "com.colmeio.wasmagent"], { timeoutMs: 8000 });
    commandResults.activity = await runAdbDiagnosticCommand(adbPath, ["shell", "dumpsys", "activity", "activities"], { timeoutMs: 8000, maxBuffer: 2 * 1024 * 1024 });
    commandResults.window = await runAdbDiagnosticCommand(adbPath, ["shell", "dumpsys", "window"], { timeoutMs: 8000, maxBuffer: 1024 * 1024 });
    commandResults.packages = await runAdbDiagnosticCommand(adbPath, ["shell", "pm", "list", "packages"], { timeoutMs: 8000, maxBuffer: 512 * 1024 });
    commandResults.logcat = await runAdbDiagnosticCommand(adbPath, ["logcat", "-d", "-v", "time"], { timeoutMs: 12000, maxBuffer: 4 * 1024 * 1024 });
  }
  const interestingLogPattern = /com\.colmeio\.wasmagent|wasmagent|WASM Agent|wa\.colmeio\.com|android-auth-return|native\/android\/auth|accounts\.google\.com|ActivityTaskManager|START u0|ChromeTabbedActivity|webapk|MIUILOG|Permission Denied/i;
  const activityPattern = /mResumedActivity|mFocusedRootTask|Hist #|Intent|dat=|cmp=com\.colmeio|cmp=com\.android\.chrome|webapk|wa\.colmeio|android-auth-return/i;
  const packagePattern = /android-auth-return|wasm-agent|intent|VIEW|BROWSABLE|com\.colmeio\.wasmagent/i;
  const payload = {
    schema: "hermes.wasm_agent.windows_adb_diagnostics.v1",
    generated_at: generatedAt,
    reason: String(options.reason || "collect_adb_diagnostics").slice(0, 160),
    platform: "windows",
    device_bridge: "adb",
    adbPath,
    hasDevice,
    commands: commandResults,
    filtered: {
      logcat: filterDiagnosticLines(commandResults.logcat?.stdout || "", interestingLogPattern, 300),
      activity: filterDiagnosticLines(commandResults.activity?.stdout || "", activityPattern, 180),
      packageWasmAgent: filterDiagnosticLines(commandResults.packageWasmAgent?.stdout || "", packagePattern, 220),
      webApkPackages: filterDiagnosticLines(commandResults.packages?.stdout || "", /webapk|colmeio|wasm/i, 120),
    },
  };
  const bundleDir = path.join(nativeDiagnosticsBundleRoot(), `adb-${timestampForFilename()}`);
  fs.mkdirSync(bundleDir, { recursive: true });
  const bundlePath = path.join(bundleDir, "adb-diagnostics.json");
  const summaryPath = path.join(bundleDir, "SUMMARY.md");
  fs.writeFileSync(bundlePath, `${JSON.stringify(payload, null, 2)}\n`);
  fs.writeFileSync(summaryPath, [
    "# WASM Agent ADB Diagnostics",
    "",
    `- Generated: ${generatedAt}`,
    `- ADB path: ${adbPath}`,
    `- Device detected: ${hasDevice}`,
    `- Reason: ${payload.reason}`,
    "",
    "## Filtered Logcat",
    "",
    "```text",
    payload.filtered.logcat || "",
    "```",
    "",
  ].join("\n"));
  return { ok: true, bundlePath, summaryPath, payload };
}

function windowsAndroidOAuthStatePath() {
  return path.join(nativeAppDataDir(), "android-oauth-verification-state.json");
}

function readWindowsAndroidOAuthState() {
  return readJsonFile(windowsAndroidOAuthStatePath(), {});
}

function writeWindowsAndroidOAuthState(update = {}) {
  const current = readWindowsAndroidOAuthState();
  const next = {
    schema: "hermes.wasm_agent.windows_android_oauth_verification.v1",
    ...current,
    ...sanitizeRendererDiagnosticValue(update),
    updatedAt: new Date().toISOString(),
  };
  try {
    fs.mkdirSync(path.dirname(windowsAndroidOAuthStatePath()), { recursive: true });
    fs.writeFileSync(windowsAndroidOAuthStatePath(), `${JSON.stringify(next, null, 2)}\n`);
  } catch {
    // The UI still receives live status events if persistence fails.
  }
  return next;
}

function emitWindowsDiagnosticEvent(sender, event = {}) {
  const payload = sanitizeRendererDiagnosticValue({
    schema: "hermes.wasm_agent.windows_native_diagnostics_event.v1",
    timestamp: new Date().toISOString(),
    ...event,
  });
  try {
    sender.send("wasm-agent:native-diagnostics-event", payload);
  } catch {
    // Renderer may have navigated while an operation was running.
  }
  return payload;
}

function commandLineDisplay(command, args = []) {
  return [command, ...args].join(" ");
}

function windowsCommandArg(value) {
  const text = String(value || "");
  if (/^[A-Za-z0-9_./:=+-]+$/.test(text)) return text;
  return `"${text.replace(/"/g, '""')}"`;
}

function spawnInvocation(command, args = []) {
  if (process.platform === "win32" && /\.(cmd|bat)$/i.test(command)) {
    return {
      command: "cmd.exe",
      args: ["/d", "/s", "/c", [windowsCommandArg(command), ...args.map(windowsCommandArg)].join(" ")],
    };
  }
  return { command, args };
}

function spawnStreamingCommand(sender, opId, operation, command, args = [], options = {}) {
  return new Promise((resolve) => {
    const startedAt = new Date().toISOString();
    const startedMs = Date.now();
    const displayCommand = options.displayCommand || commandLineDisplay(path.basename(command), args);
    const invocation = spawnInvocation(command, args);
    let stdout = "";
    let stderr = "";
    let finished = false;
    let timeout = 0;
    const finish = (result) => {
      if (finished) return;
      finished = true;
      if (timeout) clearTimeout(timeout);
      const payload = {
        ok: result.exitCode === 0 && !result.error,
        operation,
        opId,
        command: displayCommand,
        exitCode: Number.isFinite(result.exitCode) ? result.exitCode : 1,
        signal: result.signal || "",
        timedOut: Boolean(result.timedOut),
        startedAt,
        finishedAt: new Date().toISOString(),
        elapsedMs: Date.now() - startedMs,
        stdout: clipDiagnosticText(stdout, 256 * 1024),
        stderr: clipDiagnosticText(stderr, 256 * 1024),
        error: result.error || "",
      };
      writeNativeControlAudit({ action: "local_diagnostics_command_finished", operation, opId, result: sanitizeRendererDiagnosticValue(payload) });
      emitWindowsDiagnosticEvent(sender, { type: "command_finished", operation, opId, result: sanitizeRendererDiagnosticValue(payload) });
      resolve(payload);
    };
    writeNativeControlAudit({ action: "local_diagnostics_command_started", operation, opId, command: displayCommand, startedAt });
    emitWindowsDiagnosticEvent(sender, { type: "command_started", operation, opId, command: displayCommand, startedAt });
    let child = null;
    try {
      child = spawn(invocation.command, invocation.args, {
        cwd: options.cwd || undefined,
        env: options.env || process.env,
        windowsHide: true,
        shell: false,
      });
    } catch (error) {
      finish({ exitCode: 1, error: redactSensitiveText(String(error && error.message ? error.message : error)) });
      return;
    }
    child.stdout?.on("data", (chunk) => {
      const text = clipDiagnosticText(chunk.toString("utf8"), 64 * 1024);
      stdout = clipDiagnosticText(`${stdout}${text}`, 256 * 1024);
      emitWindowsDiagnosticEvent(sender, { type: "stdout", operation, opId, text });
    });
    child.stderr?.on("data", (chunk) => {
      const text = clipDiagnosticText(chunk.toString("utf8"), 64 * 1024);
      stderr = clipDiagnosticText(`${stderr}${text}`, 256 * 1024);
      emitWindowsDiagnosticEvent(sender, { type: "stderr", operation, opId, text });
    });
    child.on("error", (error) => {
      finish({ exitCode: 1, error: redactSensitiveText(String(error && error.message ? error.message : error)) });
    });
    child.on("close", (exitCode, signal) => {
      finish({ exitCode: Number(exitCode || 0), signal: signal || "" });
    });
    const timeoutMs = Number(options.timeoutMs || 15 * 60 * 1000);
    if (timeoutMs > 0) {
      timeout = setTimeout(() => {
        try {
          child.kill();
        } catch {
          // Process may have already exited.
        }
        finish({ exitCode: 1, timedOut: true, error: `timed out after ${timeoutMs}ms` });
      }, timeoutMs);
      timeout.unref?.();
    }
  });
}

async function findCommandExecutable(commandName, envName, commonPaths = []) {
  const explicit = String(process.env[envName] || "").trim();
  const candidates = [];
  if (explicit) candidates.push(explicit);
  const lookup = process.platform === "win32"
    ? await execFileBounded("where.exe", [commandName], { timeoutMs: 3000, maxBuffer: 64 * 1024 })
    : await execFileBounded("which", [commandName], { timeoutMs: 3000, maxBuffer: 64 * 1024 });
  if (lookup.ok) {
    String(lookup.stdout || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean).forEach((line) => candidates.push(line));
  }
  candidates.push(...commonPaths, commandName);
  for (const candidate of candidates) {
    if (!candidate) continue;
    if (candidate === commandName) return candidate;
    try {
      if (fs.existsSync(candidate)) return candidate;
    } catch {
      // Ignore inaccessible candidates.
    }
  }
  return commandName;
}

async function findWindowsAdbExecutable() {
  return findCommandExecutable("adb", "WASM_AGENT_ADB_PATH", [
    path.join(os.homedir(), "AppData", "Local", "Android", "Sdk", "platform-tools", "adb.exe"),
    path.join(os.homedir(), "Downloads", "platform-tools", "adb.exe"),
    path.join(os.homedir(), "Downloads", "platform-tools-latest-windows", "platform-tools", "adb.exe"),
  ]);
}

async function findHorcExecutable() {
  const explicit = String(process.env.WASM_AGENT_HORC_PATH || "").trim();
  const resolved = await findCommandExecutable("horc", "WASM_AGENT_HORC_PATH", []);
  if (resolved === "horc" && !explicit) return "";
  return resolved;
}

function fileExists(filePath = "") {
  try {
    return Boolean(filePath && fs.existsSync(filePath) && fs.statSync(filePath).isFile());
  } catch {
    return false;
  }
}

function resourcePath(...segments) {
  return path.join(process.resourcesPath || "", ...segments);
}

function bundledHorcRunnerPath() {
  return resourcePath("horc", "horc-local.js");
}

function bundledAndroidApkPath() {
  return resourcePath("android", "WASM-Agent-arm64.apk");
}

function bundledAndroidApkDefaultsPath() {
  return resourcePath("android", "WASM-Agent-arm64.native-defaults.json");
}

function androidSimulatorStateRoot() {
  try {
    return path.join(app.getPath("userData"), "native-diagnostics", "android-oauth-verifier");
  } catch {
    return path.join(os.tmpdir(), "wasm-agent-android-oauth-verifier");
  }
}

function ensureAndroidSimulatorStateRoot() {
  const root = androidSimulatorStateRoot();
  fs.mkdirSync(root, { recursive: true });
  return root;
}

async function resolveLocalHorcRunner() {
  const bundledRunner = bundledHorcRunnerPath();
  if (fileExists(bundledRunner)) {
    return {
      ok: true,
      source: "bundled",
      command: process.execPath,
      argsPrefix: [bundledRunner],
      cwd: path.dirname(bundledRunner),
      usesElectronRunAsNode: true,
      runnerPath: bundledRunner,
      displayName: "bundled-horc",
    };
  }

  const horcRoot = resolveHorcWorkingDirectory();
  const devRunner = path.join(horcRoot, "tools", "horc-local", "horc-local.js");
  if (allowLocalDevCandidates() && fileExists(devRunner)) {
    return {
      ok: true,
      source: "dev-local",
      command: process.execPath,
      argsPrefix: [devRunner],
      cwd: path.dirname(devRunner),
      usesElectronRunAsNode: true,
      runnerPath: devRunner,
      displayName: "dev-horc-local",
    };
  }

  if (allowLocalDevCandidates()) {
    const pathHorc = await findHorcExecutable();
    if (pathHorc) {
      return {
        ok: true,
        source: "path",
        command: pathHorc,
        argsPrefix: [],
        cwd: horcRoot,
        usesElectronRunAsNode: false,
        runnerPath: pathHorc,
        displayName: "path-horc",
      };
    }
  }

  return {
    ok: false,
    source: "missing",
    error: "bundled_horc_runner_missing",
    runnerPath: bundledRunner,
    message: allowLocalDevCandidates()
      ? "Bundled/dev horc runner was not found, and no PATH horc fallback is available."
      : "The installed Windows app is missing its bundled Android verifier. Update WASM Agent and try again.",
  };
}

function androidSimulatorEnvironment(adbPath = "", runner = {}) {
  const rootDir = ensureAndroidSimulatorStateRoot();
  const apkPath = fileExists(bundledAndroidApkPath())
    ? bundledAndroidApkPath()
    : String(process.env.WASM_AGENT_ANDROID_APK || process.env.WASM_AGENT_SIM_ANDROID_APK || "");
  const env = {
    ...process.env,
    WASM_AGENT_SIM_ROOT_DIR: rootDir,
    WASM_AGENT_SIM_URL: selectedBackendOrigin || DEFAULT_SERVER_URL,
  };
  if (adbPath) env.WASM_AGENT_SIM_ADB = adbPath;
  if (apkPath) env.WASM_AGENT_ANDROID_APK = apkPath;
  if (runner.usesElectronRunAsNode) env.ELECTRON_RUN_AS_NODE = "1";
  return {
    env,
    rootDir,
    apkPath,
    apkDefaultsPath: fileExists(bundledAndroidApkDefaultsPath()) ? bundledAndroidApkDefaultsPath() : "",
  };
}

function looksLikeHorcRoot(candidate) {
  try {
    return Boolean(candidate && fs.existsSync(path.join(candidate, "tools", "app-simulator", "simulate.js")));
  } catch {
    return false;
  }
}

function resolveHorcWorkingDirectory() {
  const candidates = [
    process.env.WASM_AGENT_HORC_ROOT,
    process.env.HERMES_ORCHESTRATOR_ROOT,
    process.env.HORC_ROOT,
    process.cwd(),
    path.resolve(__dirname, "..", "..", ".."),
    path.join(os.homedir(), "hermes-orchestrator"),
    path.join(os.homedir(), "local"),
    "/local",
  ].filter(Boolean);
  return candidates.find(looksLikeHorcRoot) || process.cwd();
}

function parseAdbDevices(stdout = "") {
  return String(stdout || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !/^List of devices attached/i.test(line))
    .map((line) => {
      const match = line.match(/^(\S+)\s+(\S+)(?:\s+(.*))?$/);
      if (!match) return null;
      return { serial: match[1], state: match[2], detail: match[3] || "" };
    })
    .filter(Boolean);
}

function classifyAdbDevices(stdout = "") {
  const devices = parseAdbDevices(stdout);
  const authorized = devices.filter((device) => device.state === "device");
  const unauthorized = devices.filter((device) => device.state === "unauthorized");
  const offline = devices.filter((device) => device.state === "offline");
  const status = authorized.length
    ? "device_authorized"
    : unauthorized.length
      ? "unauthorized"
      : offline.length
        ? "offline"
        : "waiting_for_phone";
  return {
    status,
    devices,
    authorizedCount: authorized.length,
    unauthorizedCount: unauthorized.length,
    offlineCount: offline.length,
    hasAuthorizedDevice: authorized.length > 0,
  };
}

function adbMissingInstructions() {
  return "Install Android SDK Platform Tools, add platform-tools to PATH, then restart WASM Agent.";
}

function isAdbMissingResult(result = {}) {
  return !result.ok && /ENOENT|not recognized|cannot find|not found|where\.exe.*adb/i.test(`${result.stderr || ""}\n${result.error || ""}`);
}

async function runWindowsDiagnosticExec(sender, opId, operation, command, args = [], options = {}) {
  const startedAt = new Date().toISOString();
  const displayCommand = commandLineDisplay(path.basename(command), args);
  writeNativeControlAudit({ action: "local_diagnostics_command_started", operation, opId, command: displayCommand, startedAt });
  emitWindowsDiagnosticEvent(sender, { type: "command_started", operation, opId, command: displayCommand, startedAt });
  const result = sanitizeRendererDiagnosticValue(await execFileBounded(command, args, options));
  writeNativeControlAudit({ action: "local_diagnostics_command_finished", operation, opId, result });
  emitWindowsDiagnosticEvent(sender, { type: "command_finished", operation, opId, result });
  return result;
}

async function runAdbVersionDiagnostics(sender, opId) {
  emitWindowsDiagnosticEvent(sender, { type: "status", operation: "adb_version", opId, status: "checking_adb", label: "checking adb" });
  const adbPath = await findWindowsAdbExecutable();
  const result = await runWindowsDiagnosticExec(sender, opId, "adb_version", adbPath, ["version"], { timeoutMs: 5000, maxBuffer: 128 * 1024 });
  if (isAdbMissingResult(result)) {
    emitWindowsDiagnosticEvent(sender, {
      type: "status",
      operation: "adb_version",
      opId,
      status: "adb_missing",
      label: "adb missing",
      message: adbMissingInstructions(),
    });
  }
  return { ...result, adbPath, adbMissing: isAdbMissingResult(result), instructions: isAdbMissingResult(result) ? adbMissingInstructions() : "" };
}

async function runAdbDevicesDiagnostics(sender, opId, adbPath = "") {
  const resolvedAdbPath = adbPath || await findWindowsAdbExecutable();
  emitWindowsDiagnosticEvent(sender, { type: "status", operation: "adb_devices", opId, status: "waiting_for_phone", label: "waiting for phone" });
  const result = await runWindowsDiagnosticExec(sender, opId, "adb_devices", resolvedAdbPath, ["devices", "-l"], { timeoutMs: 5000, maxBuffer: 128 * 1024 });
  const devices = classifyAdbDevices(result.stdout || "");
  const label = devices.status === "device_authorized"
    ? "device authorized"
    : devices.status === "unauthorized"
      ? "unauthorized: unlock phone and tap Allow"
      : devices.status === "offline"
        ? "phone offline"
        : "waiting for phone";
  emitWindowsDiagnosticEvent(sender, {
    type: "status",
    operation: "adb_devices",
    opId,
    status: devices.status,
    label,
    message: devices.status === "unauthorized" ? "Unlock your phone and tap Allow USB debugging." : "",
    devices,
  });
  return { ...result, adbPath: resolvedAdbPath, devices };
}

function reportDirFromPath(value = "") {
  const input = String(value || "").trim().replace(/^file:\/+/i, "");
  if (!input) return "";
  try {
    const stat = fs.statSync(input);
    if (stat.isDirectory()) return input;
    return path.dirname(input);
  } catch {
    if (/[\\/]result\.json$|[\\/]summary\.md$/i.test(input)) return path.dirname(input);
    return input;
  }
}

function parseReportPathFromOutput(output = "") {
  const match = String(output || "").match(/^\s*report:\s*(.+?)\s*$/im);
  return match ? reportDirFromPath(match[1]) : "";
}

function latestAndroidReportCandidateDirs(preferredPath = "") {
  const state = readWindowsAndroidOAuthState();
  const horcRoot = resolveHorcWorkingDirectory();
  const simulatorRoot = androidSimulatorStateRoot();
  return [
    reportDirFromPath(preferredPath),
    reportDirFromPath(state.latestReportDir || state.latestReportPath || ""),
    reportDirFromPath(process.env.WASM_AGENT_ANDROID_SIM_REPORT_DIR || ""),
    path.join(simulatorRoot, "reports", "sim", "android", "latest"),
    path.join(horcRoot, "reports", "sim", "android", "latest"),
    path.join(process.cwd(), "reports", "sim", "android", "latest"),
    "/local/reports/sim/android/latest",
  ].filter(Boolean);
}

function reportStatusFrom(summary = "", result = {}) {
  const resultStatus = String(result.status || "").trim().toLowerCase();
  if (resultStatus) return resultStatus;
  const match = String(summary || "").match(/-\s*Status:\s*([A-Z]+)/i);
  return match ? match[1].toLowerCase() : "";
}

function readLatestAndroidSimulatorReport(options = {}) {
  for (const reportDir of latestAndroidReportCandidateDirs(options.preferredPath || "")) {
    const summaryPath = path.join(reportDir, "summary.md");
    const resultPath = path.join(reportDir, "result.json");
    const hasSummary = fs.existsSync(summaryPath);
    const hasResult = fs.existsSync(resultPath);
    if (!hasSummary && !hasResult) continue;
    const summary = hasSummary ? clipDiagnosticText(fs.readFileSync(summaryPath, "utf8"), 160 * 1024) : "";
    const result = hasResult ? sanitizeRendererDiagnosticValue(readJsonFile(resultPath, {})) : {};
    const status = reportStatusFrom(summary, result);
    return {
      ok: true,
      reportDir,
      summaryPath: hasSummary ? summaryPath : "",
      resultPath: hasResult ? resultPath : "",
      status,
      passed: status === "passed",
      pending: status === "pending",
      failed: status === "failed" || status === "fail",
      summary,
      result,
    };
  }
  return {
    ok: false,
    status: "missing",
    reportDir: "",
    summaryPath: "",
    resultPath: "",
    summary: "",
    result: {},
  };
}

async function waitForAuthorizedAndroidDevice(sender, opId, adbPath) {
  const deadline = Date.now() + Number(process.env.WASM_AGENT_ANDROID_OAUTH_DEVICE_WAIT_MS || 180_000);
  let latest = null;
  while (Date.now() < deadline) {
    latest = await runAdbDevicesDiagnostics(sender, opId, adbPath);
    if (latest.devices?.hasAuthorizedDevice) return latest;
    await sleep(2000);
  }
  return latest || { ok: false, devices: { status: "waiting_for_phone", hasAuthorizedDevice: false } };
}

async function runWindowsAndroidOAuthVerification(sender, opId) {
  if (activeAndroidOAuthVerification) {
    return { ok: false, status: "busy", error: "verification_already_running", opId: activeAndroidOAuthVerification };
  }
  activeAndroidOAuthVerification = opId;
  try {
    writeWindowsAndroidOAuthState({ opId, status: "checking_adb", startedAt: new Date().toISOString() });
    const adbVersion = await runAdbVersionDiagnostics(sender, opId);
    if (adbVersion.adbMissing || !adbVersion.ok) {
      const result = {
        ok: false,
        opId,
        status: "adb_missing",
        label: "adb missing",
        instructions: adbVersion.instructions || adbMissingInstructions(),
        adbVersion,
      };
      writeWindowsAndroidOAuthState(result);
      return result;
    }
    const devices = await waitForAuthorizedAndroidDevice(sender, opId, adbVersion.adbPath);
    if (!devices.devices?.hasAuthorizedDevice) {
      const pendingStatus = devices.devices?.status || "waiting_for_phone";
      const result = {
        ok: false,
        opId,
        status: "pending",
        label: pendingStatus === "unauthorized" ? "unauthorized: unlock phone and tap Allow" : "waiting for phone",
        message: pendingStatus === "unauthorized"
          ? "Unlock your phone and tap Allow USB debugging."
          : "Plug Android phone by USB and enable USB debugging.",
        devices,
      };
      emitWindowsDiagnosticEvent(sender, { type: "status", operation: "verify_android_oauth", opId, status: pendingStatus, label: result.label, message: result.message });
      writeWindowsAndroidOAuthState(result);
      return result;
    }
    const runner = await resolveLocalHorcRunner();
    if (!runner.ok) {
      const result = {
        ok: false,
        opId,
        status: "FAIL",
        label: "FAIL",
        message: runner.message || "Bundled Android verifier is missing.",
        error: runner.error || "horc_runner_missing",
        runner,
        adbVersion,
        devices,
        report: readLatestAndroidSimulatorReport(),
      };
      writeWindowsAndroidOAuthState({
        status: "FAIL",
        latestReportDir: result.report.reportDir || "",
        latestReportPath: result.report.summaryPath || result.report.resultPath || "",
        lastExitCode: 1,
        finishedAt: new Date().toISOString(),
        error: result.error,
      });
      emitWindowsDiagnosticEvent(sender, { type: "status", operation: "verify_android_oauth", opId, status: "FAIL", label: "FAIL", message: result.message });
      return result;
    }
    const simulator = androidSimulatorEnvironment(adbVersion.adbPath, runner);
    emitWindowsDiagnosticEvent(sender, {
      type: "status",
      operation: "verify_android_oauth",
      opId,
      status: "running_horc",
      label: "running horc simulate android --device --interactive-oauth",
      runner: { source: runner.source, runnerPath: runner.runnerPath, apkPath: simulator.apkPath, reportRoot: simulator.rootDir },
    });
    const horcArgs = ["simulate", "android", "--device", "--interactive-oauth"];
    const horcResult = await spawnStreamingCommand(sender, opId, "verify_android_oauth", runner.command, [...runner.argsPrefix, ...horcArgs], {
      cwd: runner.cwd || simulator.rootDir,
      env: simulator.env,
      displayCommand: "horc simulate android --device --interactive-oauth",
      timeoutMs: Number(process.env.WASM_AGENT_ANDROID_OAUTH_VERIFY_TIMEOUT_MS || 15 * 60 * 1000),
    });
    const reportDir = parseReportPathFromOutput(`${horcResult.stdout || ""}\n${horcResult.stderr || ""}`);
    const report = readLatestAndroidSimulatorReport({ preferredPath: reportDir });
    const proofPassed = horcResult.exitCode === 0 && report.passed;
    const finalStatus = proofPassed
      ? "PASS"
      : report.pending
        ? "PENDING"
        : "FAIL";
    const result = {
      ok: proofPassed,
      opId,
      status: finalStatus,
      label: finalStatus,
      message: proofPassed
        ? "Android OAuth real-device proof passed."
        : report.pending
          ? "Real-device proof is still pending."
          : "Android OAuth real-device proof failed.",
      horcResult: sanitizeRendererDiagnosticValue({
        ...horcResult,
        runner: { source: runner.source, runnerPath: runner.runnerPath, apkPath: simulator.apkPath, reportRoot: simulator.rootDir },
        stdout: clipDiagnosticText(horcResult.stdout || "", 8000),
        stderr: clipDiagnosticText(horcResult.stderr || "", 8000),
      }),
      report,
    };
    writeWindowsAndroidOAuthState({
      status: finalStatus,
      latestReportDir: report.reportDir || reportDir || "",
      latestReportPath: report.summaryPath || report.resultPath || "",
      lastExitCode: horcResult.exitCode,
      finishedAt: new Date().toISOString(),
    });
    emitWindowsDiagnosticEvent(sender, { type: "status", operation: "verify_android_oauth", opId, status: finalStatus, label: finalStatus, message: result.message, report });
    return result;
  } finally {
    activeAndroidOAuthVerification = null;
  }
}

function isWindowsNativeDiagnosticsAllowed(event) {
  if (process.platform !== "win32") return { ok: false, error: "windows_native_shell_required" };
  const win = BrowserWindow.fromWebContents(event.sender);
  if (!win || win.isDestroyed() || win !== currentNativeWindow()) return { ok: false, error: "native_window_required" };
  const currentUrl = event.sender.getURL();
  if (currentUrl.startsWith(NATIVE_APP_ORIGIN)) return { ok: true };
  try {
    const parsed = new URL(currentUrl);
    if (selectedBackendOrigin && sameOrigin(selectedBackendOrigin, currentUrl) && parsed.searchParams.get("native") === "electron") return { ok: true };
  } catch {
    // Fall through to denial.
  }
  return { ok: false, error: "native_electron_route_required" };
}

async function handleWindowsNativeDiagnosticsOperation(event, operation) {
  const opName = String(operation || "");
  const opId = `win-android-oauth-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  if (!WINDOWS_ANDROID_OAUTH_OPERATIONS.has(opName)) {
    writeNativeControlAudit({ action: "local_diagnostics_command_refused", operation: opName, opId, reason: "operation_not_allowlisted" });
    return { ok: false, opId, error: "operation_not_allowlisted" };
  }
  const allowed = isWindowsNativeDiagnosticsAllowed(event);
  if (!allowed.ok) {
    writeNativeControlAudit({ action: "local_diagnostics_command_refused", operation: opName, opId, reason: allowed.error });
    return { ok: false, opId, error: allowed.error, windowsNativeShellRequired: true };
  }
  if (opName === "read_latest_android_report") {
    const report = readLatestAndroidSimulatorReport();
    writeNativeControlAudit({ action: "local_diagnostics_report_read", operation: opName, opId, reportPath: report.summaryPath || report.resultPath || "" });
    return { ok: report.ok, opId, report };
  }
  if (opName === "open_latest_android_report") {
    const report = readLatestAndroidSimulatorReport();
    const target = report.summaryPath || report.resultPath || "";
    if (!target) return { ok: false, opId, error: "latest_report_missing", report };
    const openError = await shell.openPath(target);
    const result = { ok: !openError, opId, path: target, error: openError || "", report };
    writeNativeControlAudit({ action: "local_diagnostics_report_opened", operation: opName, opId, result });
    return result;
  }
  if (opName === "adb_version") {
    return runAdbVersionDiagnostics(event.sender, opId);
  }
  if (opName === "adb_devices") {
    return runAdbDevicesDiagnostics(event.sender, opId);
  }
  if (opName === "verify_android_oauth") {
    return runWindowsAndroidOAuthVerification(event.sender, opId);
  }
  return { ok: false, opId, error: "operation_not_implemented" };
}

function runtimeDiagnosticsPayload(overrides = {}) {
  const config = readConfig();
  const defaults = readNativeDefaults();
  const nativeDefaults = nativeDefaultsDiagnostics(defaults);
  const candidateList = configuredServerUrlCandidates(config);
  const candidateSources = {};
  startupDiagnostics.candidateEntries.forEach((entry) => {
    candidateSources[entry.serverUrl] = entry.source;
  });
  const asarPath = appAsarPath();
  return {
    execPath: process.execPath || "",
    resourcesPath: process.resourcesPath || "",
    userData: app.getPath("userData"),
    appAsarPath: asarPath,
    appAsarSha256: sha256File(asarPath),
    androidOAuthVerifier: {
      bundledHorcRunnerPath: bundledHorcRunnerPath(),
      bundledHorcRunnerPresent: fileExists(bundledHorcRunnerPath()),
      bundledAndroidApkPath: bundledAndroidApkPath(),
      bundledAndroidApkPresent: fileExists(bundledAndroidApkPath()),
      reportRoot: androidSimulatorStateRoot(),
    },
    packageVersion: app.getVersion(),
    buildId: String(config.buildId || defaults.buildId || ""),
    mode: allowLocalDevCandidates() ? "development" : "production",
    allowLocalDev: allowLocalDevCandidates(),
    packagedDefaultServerUrl: DEFAULT_SERVER_URL,
    nativeDefaultsRaw: defaults,
    savedConfigPath: configPath(),
    savedConfigRaw: startupDiagnostics.savedConfigRawJson || readConfigRaw() || null,
    envDefaultServerUrl: process.env.WASM_AGENT_DEFAULT_SERVER_URL || null,
    envAllowLocalDev: process.env.WASM_AGENT_ALLOW_LOCAL_DEV || null,
    candidateList,
    candidateSources,
    discardedCandidateOrigins: startupDiagnostics.discardedCandidateOrigins,
    lastTestedUrl: startupDiagnostics.lastTestedUrl || (candidateList[0] ? new URL("/config.json", candidateList[0]).toString() : ""),
    lastFailureReason: startupDiagnostics.lastFailureReason,
    nativeDefaultsPath: nativeDefaults.path,
    nativeDefaultsServerUrl: nativeDefaults.serverUrl,
    nativeDefaultsServerUrlCandidates: nativeDefaults.serverUrlCandidates,
    finalSelectedOrigin: startupDiagnostics.finalSelectedOrigin,
    currentRoute: startupDiagnostics.currentRoute,
    lastReload: lastReloadCommand,
    ...overrides,
  };
}

function runtimeDiagnosticsPath() {
  return path.join(nativeAppDataDir(), "runtime-diagnostics.json");
}

function rendererAuthDiagnosticsPath() {
  return path.join(nativeAppDataDir(), "renderer-auth-diagnostics.log");
}

function sanitizeRendererDiagnosticValue(value, depth = 0) {
  if (depth > 4) return "[depth-limit]";
  if (typeof value === "string") {
    const text = redactSensitiveText(value);
    return text.length > 600 ? `${text.slice(0, 600)}...` : text;
  }
  if (value === null || ["number", "boolean"].includes(typeof value)) {
    return value;
  }
  if (Array.isArray(value)) return value.slice(0, 20).map((item) => sanitizeRendererDiagnosticValue(item, depth + 1));
  if (!value || typeof value !== "object") return "";
  const redacted = {};
  Object.entries(value).slice(0, 80).forEach(([key, item]) => {
    if (/credential|token|cookie|secret|authorization|password|saved.*config.*raw|raw.*config/i.test(key)) {
      redacted[key] = "[redacted]";
      return;
    }
    redacted[key] = sanitizeRendererDiagnosticValue(item, depth + 1);
  });
  return redacted;
}

function writeRendererAuthDiagnostic(kind, payload = {}) {
  const entry = {
    timestamp: new Date().toISOString(),
    kind: String(kind || "unknown").slice(0, 120),
    payload: sanitizeRendererDiagnosticValue(payload),
  };
  try {
    const target = rendererAuthDiagnosticsPath();
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.appendFileSync(target, `${JSON.stringify(entry)}\n`);
  } catch (error) {
    logNativeDiagnostic("renderer-auth-diagnostic-write-failed", {
      reason: String(error && error.message ? error.message : error),
    });
  }
  console.log(`[wasm-agent:renderer-auth] ${entry.kind} ${JSON.stringify(entry.payload)}`);
  void uploadRendererAuthDiagnostics({ reason: entry.kind });
  return { ok: true, path: rendererAuthDiagnosticsPath() };
}

function readTextTail(filePath, maxBytes = 128 * 1024) {
  try {
    const stats = fs.statSync(filePath);
    const start = Math.max(0, stats.size - maxBytes);
    const fd = fs.openSync(filePath, "r");
    try {
      const buffer = Buffer.alloc(stats.size - start);
      fs.readSync(fd, buffer, 0, buffer.length, start);
      return buffer.toString("utf8");
    } finally {
      fs.closeSync(fd);
    }
  } catch {
    return "";
  }
}

async function nativeAuthCookieStatus() {
  const config = ensureConfig();
  const serverUrl = selectedBackendOrigin || config.serverUrl || DEFAULT_SERVER_URL;
  const normalized = normalizeServerUrl(serverUrl, DEFAULT_SERVER_URL);
  try {
    const cookies = await session.defaultSession.cookies.get({ url: normalized, name: "wa_uid" });
    return {
      ok: true,
      serverUrl: normalized,
      hasWaUid: cookies.length > 0,
      cookieCount: cookies.length,
      cookieMeta: cookies.map((cookie) => ({
        domain: cookie.domain,
        path: cookie.path,
        secure: Boolean(cookie.secure),
        httpOnly: Boolean(cookie.httpOnly),
        session: Boolean(cookie.session),
        expirationDate: cookie.expirationDate || 0,
      })),
    };
  } catch (error) {
    return {
      ok: false,
      serverUrl: normalized,
      error: String(error && error.message ? error.message : error),
      hasWaUid: false,
      cookieCount: 0,
      cookieMeta: [],
    };
  }
}

async function waitForNativeAuthCookie(timeoutMs = AUTH_COOKIE_WAIT_TIMEOUT_MS) {
  const started = Date.now();
  let status = await nativeAuthCookieStatus();
  while (!status.hasWaUid && Date.now() - started < timeoutMs) {
    await sleep(AUTH_COOKIE_WAIT_INTERVAL_MS);
    status = await nativeAuthCookieStatus();
  }
  return {
    ...status,
    waitMs: Date.now() - started,
  };
}

async function flushNativeAuthCookies(options = {}) {
  let flushed = false;
  const timeoutMs = Number.isFinite(Number(options.timeoutMs)) ? Number(options.timeoutMs) : AUTH_COOKIE_WAIT_TIMEOUT_MS;
  const preFlushStatus = await waitForNativeAuthCookie(timeoutMs);
  try {
    await session.defaultSession.cookies.flushStore();
    flushed = true;
  } catch (error) {
    const status = await nativeAuthCookieStatus();
    return {
      ...status,
      ok: false,
      flushed: false,
      reason: String(options.reason || ""),
      error: String(error && error.message ? error.message : error),
    };
  }
  const status = await nativeAuthCookieStatus();
  logNativeDiagnostic("native-auth-cookie-flushed", {
    reason: String(options.reason || ""),
    ok: status.ok,
    hasWaUid: status.hasWaUid,
    cookieCount: status.cookieCount,
    waitMs: preFlushStatus.waitMs,
    cookieMeta: status.cookieMeta,
  });
  return {
    ...status,
    flushed,
    reason: String(options.reason || ""),
    waitMs: preFlushStatus.waitMs,
    preFlushHasWaUid: preFlushStatus.hasWaUid,
  };
}

async function nativeAuthSessionStatus() {
  const config = ensureConfig();
  const serverUrl = selectedBackendOrigin || config.serverUrl || DEFAULT_SERVER_URL;
  const normalized = normalizeServerUrl(serverUrl, DEFAULT_SERVER_URL);
  const endpoint = new URL("/auth/session", normalized).toString();
  try {
    const fetchFromSession = typeof session.defaultSession.fetch === "function"
      ? session.defaultSession.fetch.bind(session.defaultSession)
      : fetchWithTimeout;
    const response = await fetchFromSession(endpoint, {
      method: "GET",
      credentials: "include",
      headers: { "X-Wasm-Agent-Native-Device-Id": config.deviceId },
    });
    let authenticated = false;
    try {
      const payload = await response.clone().json();
      authenticated = Boolean(payload && payload.authenticated);
    } catch {
      authenticated = false;
    }
    return {
      ok: true,
      url: endpoint,
      status: response.status,
      authenticated,
    };
  } catch (error) {
    return {
      ok: false,
      url: endpoint,
      status: 0,
      authenticated: false,
      error: String(error && error.message ? error.message : error),
    };
  }
}

async function writeAuthPersistenceDiagnostics(reason = "auth-persistence") {
  const authCookie = await nativeAuthCookieStatus();
  const authSession = await nativeAuthSessionStatus();
  const payload = {
    authCookie,
    authSession,
    currentRoute: currentRendererUrl(),
    authPersistenceReason: reason,
  };
  writeRuntimeDiagnostics(payload);
  logNativeDiagnostic("auth-persistence-status", {
    reason,
    currentRoute: payload.currentRoute,
    authCookie,
    authSession,
  });
  return payload;
}

function recordNativeAuthUploadAttempt(entry = {}) {
  const attempts = Array.isArray(startupDiagnostics.nativeAuthUploadAttempts)
    ? startupDiagnostics.nativeAuthUploadAttempts
    : [];
  attempts.push({
    timestamp: new Date().toISOString(),
    ...entry,
  });
  startupDiagnostics.nativeAuthUploadAttempts = attempts.slice(-12);
  writeRuntimeDiagnostics();
}

async function uploadRendererAuthDiagnostics(options = {}) {
  const config = ensureConfig();
  const serverUrl = selectedBackendOrigin || await recoverReachableServerUrl(config);
  const reason = String(options.reason || "manual").slice(0, 120);
  if (!serverUrl) {
    const result = { ok: false, error: "backend_identity_unresolved", reason };
    recordNativeAuthUploadAttempt(result);
    return result;
  }
  const authDiagnosticsPath = rendererAuthDiagnosticsPath();
  const runtimeDiagnostics = readJsonFile(runtimeDiagnosticsPath(), {});
  const payload = {
    schema: "hermes.wasm_agent.native_auth_diagnostics.v1",
    uploaded_at: new Date().toISOString(),
    reason,
    platform: "windows",
    runtime: "electron",
    device_id: config.deviceId,
    account_id: config.accountId,
    app_version: app.getVersion(),
    build_id: String(config.buildId || ""),
    app_asar_fingerprint: config.appAsarFingerprint || appAsarFingerprint(),
    selected_backend_origin: selectedBackendOrigin,
    runtime_diagnostics: runtimeDiagnostics,
    renderer_auth_diagnostics_path: authDiagnosticsPath,
    renderer_auth_diagnostics_tail: readTextTail(authDiagnosticsPath),
  };
  recordNativeAuthUploadAttempt({
    ok: null,
    reason,
    serverUrl,
    rendererAuthDiagnosticsBytes: payload.renderer_auth_diagnostics_tail.length,
  });
  try {
    const response = await fetchWithTimeout(new URL("/native/diagnostics", serverUrl).toString(), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Wasm-Agent-Native-Device-Id": config.deviceId,
        "X-Wasm-Agent-Native-Runtime": "electron",
      },
      body: JSON.stringify(payload),
    }, 5000);
    if (!response.ok) {
      const result = { ok: false, error: `HTTP ${response.status}`, reason, serverUrl };
      recordNativeAuthUploadAttempt(result);
      return result;
    }
    const result = await response.json();
    recordNativeAuthUploadAttempt({
      ok: Boolean(result && result.ok),
      stored: Boolean(result && result.stored),
      reason,
      serverUrl,
      receivedAt: result && result.receivedAt,
    });
    return result;
  } catch (error) {
    const result = { ok: false, error: String(error && error.message ? error.message : error), reason, serverUrl };
    recordNativeAuthUploadAttempt(result);
    return result;
  }
}

function writeRuntimeDiagnostics(overrides = {}) {
  try {
    const target = runtimeDiagnosticsPath();
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, `${JSON.stringify(runtimeDiagnosticsPayload(overrides), null, 2)}\n`);
    return target;
  } catch (error) {
    logNativeDiagnostic("runtime-diagnostics-write-failed", {
      reason: String(error && error.message ? error.message : error),
    });
    return "";
  }
}

function ensureConfig() {
  const rawConfigBeforeMigration = readConfigRaw();
  const parsedConfigBeforeMigration = readConfig();
  if (rawConfigBeforeMigration) startupDiagnostics.savedConfigRawJson = rawConfigBeforeMigration;
  startupDiagnostics.savedConfigUserExplicit = parsedConfigBeforeMigration.userExplicit;
  const existing = migrateLegacyNativeConfig(parsedConfigBeforeMigration);
  const defaults = readNativeDefaults();
  const candidates = configuredServerUrlCandidates(existing, { logDiscards: true });
  const serverUrl = productionSafeServerUrl(candidates[0] || DEFAULT_SERVER_URL, DEFAULT_SERVER_URL, candidateSourceFor(candidates[0], existing) || "packaged-default");
  const savedConfigSource = hasExplicitCustomServer(existing)
    ? "user-explicit"
    : existing.legacyServerUrlMigratedAt
      ? "legacy-local-migrated"
      : existing.serverUrl
        ? "saved-auto-ignored"
        : "packaged-default";
  const deviceId = String(existing.deviceId || `win-${os.hostname()}-${Math.random().toString(16).slice(2)}`).replace(/[^a-zA-Z0-9_.-]/g, "-");
  const next = {
    schema: "hermes.wasm_agent.native_config.v1",
    appId: APP_ID,
    service: APP_ID,
    wasmAgentVersion: String(defaults.wasmAgentVersion || app.getVersion()),
    nativeShellVersion: String(defaults.nativeShellVersion || app.getVersion()),
    installableVersion: String(defaults.installableVersion || app.getVersion()),
    buildId: String(defaults.buildId || ""),
    buildGeneratedAt: String(defaults.generatedAt || ""),
    buildPlatform: String(defaults.buildPlatform || "windows"),
    buildArch: String(defaults.buildArch || "x64"),
    buildChannel: String(defaults.buildChannel || "nsis"),
    packagedDefaultServerUrl: DEFAULT_SERVER_URL,
    appAsarFingerprint: appAsarFingerprint(),
    savedConfigSource,
    googleClientId: String(defaults.googleClientId || existing.googleClientId || ""),
    serverUrl,
    serverUrlCandidates: configuredServerUrlCandidates({ ...existing, serverUrl }),
    deviceId,
    accountId: String(existing.accountId || ""),
    deviceToken: String(existing.deviceToken || ""),
    userExplicit: hasExplicitCustomServer(existing),
    savedCustomServerUrl: hasExplicitCustomServer(existing),
    createdAt: existing.createdAt || new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
  writeConfig(next);
  return next;
}

function nativeIconPath() {
  const candidates = [
    path.join(process.resourcesPath || "", "icon.ico"),
    path.join(__dirname, "build", "icon.ico"),
  ];
  return candidates.find((candidate) => candidate && fs.existsSync(candidate));
}

function fallbackPagePath() {
  return path.join(__dirname, "fallback.html");
}

function publicRootPath() {
  const candidates = [
    path.join(process.resourcesPath || "", "public"),
    path.resolve(__dirname, "..", "..", "..", "plugins", "wasm-agent", "public"),
  ];
  return candidates.find((candidate) => candidate && fs.existsSync(path.join(candidate, "index.html"))) || candidates[0];
}

function describeUiSource() {
  const root = publicRootPath();
  return root.startsWith(process.resourcesPath || "\0") ? "bundled-assets" : "source-tree-assets";
}

function contentTypeFor(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  return {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml; charset=utf-8",
    ".wasm": "application/wasm",
    ".webmanifest": "application/manifest+json; charset=utf-8",
  }[ext] || "application/octet-stream";
}

function responseJson(status, payload) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

function staticFileResponse(filePath) {
  return new Response(fs.readFileSync(filePath), {
    status: 200,
    headers: {
      "Content-Type": contentTypeFor(filePath),
      "Cache-Control": "no-store",
    },
  });
}

function resolvePublicFile(urlPath, method) {
  const publicRoot = path.resolve(publicRootPath());
  const rawPath = String(urlPath || "/").replace(/^\/+/, "");
  let decodedPath = "";
  try {
    decodedPath = decodeURIComponent(rawPath);
  } catch {
    return null;
  }
  const requested = decodedPath || "index.html";
  const candidate = path.resolve(publicRoot, requested);
  if (candidate !== publicRoot && !candidate.startsWith(`${publicRoot}${path.sep}`)) return null;
  try {
    if (fs.statSync(candidate).isFile()) return candidate;
  } catch {
    // Not a static asset; app routes fall through to index.html below.
  }
  if ((method || "GET").toUpperCase() === "GET" && !path.extname(requested)) {
    return path.join(publicRoot, "index.html");
  }
  return null;
}

function isPackagedFallbackUrl(rawUrl) {
  const url = String(rawUrl || "").split("?")[0].replace(/\\/g, "/");
  return url.startsWith("file:") && url.endsWith("/fallback.html");
}

function isNavigationAbort(error) {
  const message = String(error && error.message ? error.message : error || "");
  return /ERR_ABORTED|\(-3\)/i.test(message);
}

function compactLoadReason(reason, targetUrl) {
  let message = String(reason && reason.message ? reason.message : reason || "").trim();
  if (!message || isNavigationAbort(message)) {
    message = `Could not reach ${targetUrl || ensureConfig().serverUrl}.`;
  }
  message = message.replace(/\s+loading\s+'[^']*'\.?$/i, "").trim();
  if (message.length > 180) message = `${message.slice(0, 177)}...`;
  return message || `Could not reach ${targetUrl || ensureConfig().serverUrl}.`;
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 1600) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

function acceptValidatedBackend(current, serverUrl) {
  const safeServerUrl = productionSafeServerUrl(serverUrl, DEFAULT_SERVER_URL, candidateSourceFor(serverUrl, current) || "validated-backend");
  if (safeServerUrl !== normalizeServerUrl(serverUrl, "")) return "";
  const next = { ...current, serverUrl: safeServerUrl, serverUrlCandidates: configuredServerUrlCandidates({ ...current, serverUrl: safeServerUrl }), updatedAt: new Date().toISOString() };
  writeConfig(next);
  selectedBackendOrigin = safeServerUrl;
  startupDiagnostics.finalSelectedOrigin = safeServerUrl;
  return safeServerUrl;
}

async function selectReachableServerUrl() {
  const current = ensureConfig();
  const candidates = configuredServerUrlCandidates(current, { logDiscards: true });
  startupDiagnostics.candidateOrigins = candidates;
  startupDiagnostics.resolvedBackendOrigin = current.serverUrl;
  writeRuntimeDiagnostics();
  candidates.forEach((serverUrl) => {
    startupDiagnostics.lastTestedUrl = new URL("/config.json", serverUrl).toString();
    console.log(`[native] testing backend candidate: ${serverUrl}`);
  });
  const results = await Promise.all(candidates.map((serverUrl) => validateWasmAgentOrigin(serverUrl, current)));
  results.forEach((result) => {
    startupDiagnostics.originChecks.push(result);
    logNativeDiagnostic("origin-candidate", {
      serverUrl: result.serverUrl,
      accepted: result.ok,
      reason: result.reason || "wasm_agent_identity_confirmed",
      checks: result.checks,
    });
    console.log(`[native] result: ${result.ok ? "success" : "failure"} ${result.serverUrl} ${result.reason || "HTTP 200 valid JSON"}`);
  });
  startupDiagnostics.lastFailureReason = results.find((result) => !result.ok)?.reason || null;
  const accepted = selectPreferredBackendResult(results);
  if (accepted) {
    console.log(`[native] selected backend: ${accepted.serverUrl}`);
    const acceptedUrl = acceptValidatedBackend(current, accepted.serverUrl);
    writeRuntimeDiagnostics({ lastFailureReason: null, finalSelectedOrigin: acceptedUrl });
    return acceptedUrl;
  }
  selectedBackendOrigin = "";
  startupDiagnostics.finalSelectedOrigin = "";
  console.log("[native] selected backend: ");
  writeRuntimeDiagnostics();
  return "";
}

async function recoverReachableServerUrl(current = ensureConfig()) {
  if (selectedBackendOrigin) return selectedBackendOrigin;
  const candidates = configuredServerUrlCandidates(current, { logDiscards: true });
  for (const serverUrl of candidates) {
    console.log(`[native] testing backend candidate: ${serverUrl}`);
    startupDiagnostics.lastTestedUrl = new URL("/config.json", serverUrl).toString();
    const result = await validateWasmAgentOrigin(serverUrl, current, 5000);
    startupDiagnostics.originChecks.push({ ...result, recovery: true });
    logNativeDiagnostic("origin-recovery-candidate", {
      serverUrl,
      accepted: result.ok,
      reason: result.reason || "wasm_agent_identity_confirmed",
      checks: result.checks,
    });
    console.log(`[native] result: ${result.ok ? "success" : "failure"} ${serverUrl} ${result.reason || "HTTP 200 valid JSON"}`);
    startupDiagnostics.lastFailureReason = result.ok ? null : result.reason || "backend_probe_failed";
    if (result.ok) {
      const acceptedUrl = acceptValidatedBackend(current, serverUrl);
      writeRuntimeDiagnostics({ lastFailureReason: null, finalSelectedOrigin: acceptedUrl });
      return acceptedUrl;
    }
  }
  writeRuntimeDiagnostics();
  return "";
}

async function nativeConfigPayload() {
  const config = ensureConfig();
  const nativeDefaults = nativeDefaultsDiagnostics();
  let backendConfig = {};
  const serverUrl = selectedBackendOrigin || await recoverReachableServerUrl(config);
  if (serverUrl) {
    try {
      const response = await fetchWithTimeout(new URL("/config.json", serverUrl).toString(), {
        method: "GET",
        headers: { "X-Wasm-Agent-Native-Device-Id": config.deviceId },
      }, 5000);
      if (response.ok) {
        const parsed = await response.json();
        if (payloadIdentifiesWasmAgent(parsed) && !payloadIdentifiesWrongApp(parsed)) {
          backendConfig = parsed;
          startupDiagnostics.configSource = "validated-remote-server";
        }
      }
    } catch {
      backendConfig = {};
    }
  }
  return {
    ...(backendConfig && typeof backendConfig === "object" ? backendConfig : {}),
    appId: APP_ID,
    service: APP_ID,
    name: "wasm-agent",
    version: config.wasmAgentVersion || app.getVersion(),
    auth: {
      ...(backendConfig.auth || {}),
      googleClientId: String(backendConfig.auth?.googleClientId || config.googleClientId || ""),
      googleClientIdConfigured: Boolean(backendConfig.auth?.googleClientId || config.googleClientId),
      googleLoginUri: backendConfig.auth?.googleLoginUri || (serverUrl ? new URL("/auth/google/callback", serverUrl).toString() : ""),
      required: true,
    },
    native: {
      platform: "windows",
      runtime: "electron",
      desktopApp: true,
      appVersion: app.getVersion(),
      wasmAgentVersion: config.wasmAgentVersion || app.getVersion(),
      nativeShellVersion: config.nativeShellVersion || app.getVersion(),
      installableVersion: config.installableVersion || app.getVersion(),
      buildId: config.buildId || "",
      buildGeneratedAt: config.buildGeneratedAt || "",
      packagedDefaultServerUrl: config.packagedDefaultServerUrl || DEFAULT_SERVER_URL,
      appAsarFingerprint: config.appAsarFingerprint || appAsarFingerprint(),
      buildPlatform: config.buildPlatform || "windows",
      buildArch: config.buildArch || "x64",
      buildChannel: config.buildChannel || "nsis",
      serverUrl,
      serverUrlCandidates: config.serverUrlCandidates || configuredServerUrlCandidates(config),
      nativeDefaultsPath: nativeDefaults.path,
      nativeDefaultsServerUrl: nativeDefaults.serverUrl,
      nativeDefaultsServerUrlCandidates: nativeDefaults.serverUrlCandidates,
      savedConfigPath: configPath(),
      savedConfigRawJson: startupDiagnostics.savedConfigRawJson || readConfigRaw(),
      savedConfigUserExplicit: startupDiagnostics.savedConfigUserExplicit,
      envWasmAgentDefaultServerUrl: process.env.WASM_AGENT_DEFAULT_SERVER_URL || "",
      envWasmAgentAllowLocalDev: process.env.WASM_AGENT_ALLOW_LOCAL_DEV || "",
      runtimeDiagnosticsPath: runtimeDiagnosticsPath(),
      candidateEntries: startupDiagnostics.candidateEntries,
      discardedCandidateOrigins: startupDiagnostics.discardedCandidateOrigins,
      selectedTestedCandidateSource: candidateSourceFor(serverUrl || config.serverUrl, config),
      deviceId: config.deviceId,
    registered: Boolean(config.deviceToken),
      packagedAssets: true,
      savedConfigSource: config.savedConfigSource || "packaged-default",
      configSource: startupDiagnostics.configSource,
    },
  };
}

async function proxyNativeRequest(request, appUrl) {
  const config = ensureConfig();
  const serverUrl = selectedBackendOrigin || await recoverReachableServerUrl(config);
  if (!serverUrl) {
    return responseJson(503, {
      ok: false,
      error: {
        code: "native_backend_identity_unresolved",
        message: "No backend origin has identified itself as wasm-agent.",
      },
      native: {
        serverUrl: "",
        candidateOrigins: configuredServerUrlCandidates(config),
        packagedAssets: true,
      },
    });
  }
  const target = new URL(`${appUrl.pathname}${appUrl.search}`, serverUrl);
  const method = String(request.method || "GET").toUpperCase();
  const headers = new Headers(request.headers);
  headers.set("X-Wasm-Agent-Native-Device-Id", config.deviceId);
  headers.set("X-Wasm-Agent-Native-Runtime", "electron");
  if (config.deviceToken) headers.set("Authorization", `Bearer ${config.deviceToken}`);
  const init = {
    method,
    headers,
    redirect: "manual",
  };
  if (!["GET", "HEAD"].includes(method)) {
    const body = await request.arrayBuffer();
    if (body.byteLength) init.body = Buffer.from(body);
  }
  try {
    return await fetchWithTimeout(target.toString(), init, 30000);
  } catch (error) {
    return responseJson(503, {
      ok: false,
      error: {
        code: "native_backend_unavailable",
        message: `Native backend unavailable at ${serverUrl}.`,
        detail: String(error && error.message ? error.message : error),
      },
      native: {
        serverUrl,
        packagedAssets: true,
      },
    });
  }
}

function registerNativeAppProtocol() {
  protocol.handle("wasm-agent", async (request) => {
    const url = new URL(request.url);
    const method = String(request.method || "GET").toUpperCase();
    startupDiagnostics.currentRoute = url.pathname;
    if (url.hostname !== "app") return responseJson(404, { ok: false, error: { code: "native_route_not_found", message: "Unknown native app host." } });
    if (url.pathname === "/config.json") return responseJson(200, await nativeConfigPayload());
    if (url.pathname === "/auth/session") {
      const proxied = await proxyNativeRequest(request, url);
      return proxied.status === 503 ? responseJson(200, { ok: true, authenticated: false, user: null, native: { backend: "unavailable" } }) : proxied;
    }
    const staticFile = resolvePublicFile(url.pathname, method);
    if (staticFile && ["GET", "HEAD"].includes(method)) return staticFileResponse(staticFile);
    return proxyNativeRequest(request, url);
  });
}

async function postNativeEvent(kind, payload = {}) {
  const config = ensureConfig();
  if (!selectedBackendOrigin) return { ok: false, error: "backend_identity_unresolved" };
  const endpoint = new URL("/native/events", selectedBackendOrigin).toString();
  const body = {
    schema: "hermes.wasm_agent.native_event.v1",
    kind,
    emitted_at: new Date().toISOString(),
    platform: "windows",
    runtime: "electron",
    device_id: config.deviceId,
    account_id: config.accountId,
    payload,
  };
  try {
    const headers = { "Content-Type": "application/json", "X-Wasm-Agent-Native-Device-Id": config.deviceId };
    if (config.deviceToken) headers.Authorization = `Bearer ${config.deviceToken}`;
    await fetch(endpoint, { method: "POST", headers, body: JSON.stringify(body) });
    return { ok: true };
  } catch (error) {
    return { ok: false, error: String(error && error.message ? error.message : error) };
  }
}

function currentNativeWindow() {
  return BrowserWindow.getAllWindows().find((win) => win && !win.isDestroyed()) || null;
}

function currentRendererUrl() {
  const win = currentNativeWindow();
  if (!win) return startupDiagnostics.currentRoute || "";
  try {
    return win.webContents.getURL() || startupDiagnostics.currentRoute || "";
  } catch {
    return startupDiagnostics.currentRoute || "";
  }
}

async function rendererVisualState() {
  const win = currentNativeWindow();
  const config = ensureConfig();
  const base = {
    ok: Boolean(win && !win.isDestroyed()),
    currentUrl: currentRendererUrl(),
    title: win && !win.isDestroyed() ? win.getTitle() : "",
    readyState: "",
    loading: win && !win.isDestroyed() ? win.webContents.isLoading() : false,
    loadingMainFrame: win && !win.isDestroyed() ? win.webContents.isLoadingMainFrame() : false,
    authSessionStateSummary: {},
    native: {
      runtime: "electron",
      electronVersion: process.versions.electron,
      chromeVersion: process.versions.chrome,
      nodeVersion: process.versions.node,
      appVersion: app.getVersion(),
      buildId: String(config.buildId || ""),
      appAsarFingerprint: config.appAsarFingerprint || appAsarFingerprint(),
    },
    appBuildId: String(config.buildId || ""),
    cloudAssetBuildId: "",
    visibleErrorBannerText: "",
    lastFrontendFatalError: null,
  };
  if (!win || win.isDestroyed()) return base;
  try {
    const renderer = await win.webContents.executeJavaScript(`(() => {
      const clean = (value, limit = 800) => String(value || "").replace(/\\s+/g, " ").trim().slice(0, limit);
      const visible = (node) => {
        if (!node) return false;
        const style = window.getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity || 1) > 0 && rect.width > 0 && rect.height > 0;
      };
      const selectors = [
        "[role='alert']",
        ".login-message",
        ".modal-message",
        ".agent-toast.is-error",
        ".error",
        "[data-error]",
        "#nodeFormStatus"
      ];
      const visibleErrorBannerText = selectors
        .flatMap((selector) => Array.from(document.querySelectorAll(selector)))
        .filter(visible)
        .map((node) => clean(node.textContent, 300))
        .filter(Boolean)
        .slice(0, 4)
        .join(" | ");
      const app = document.querySelector("#app");
      const script = Array.from(document.scripts)
        .map((item) => item.src || "")
        .find((src) => src.includes("/app.js"));
      let cloudAssetBuildId = "";
      try {
        const url = new URL(script || "", window.location.href);
        cloudAssetBuildId = url.searchParams.get("v") || "";
      } catch {}
      const frontierState = typeof window.__wasmAgentFrontierState === "function"
        ? window.__wasmAgentFrontierState()
        : {};
      const lastFrontendFatalError = window.__wasmAgentLastFatalError || frontierState.lastFatalError || null;
      return {
        href: window.location.href,
        title: document.title,
        readyState: document.readyState,
        appDataset: app ? { ...app.dataset } : {},
        authSessionStateSummary: {
          appAuth: app?.dataset?.auth || "",
          configChecked: Boolean(frontierState.configChecked),
          authChecked: Boolean(frontierState.authChecked),
          authenticated: Boolean(frontierState.authenticated),
          authSessionLoadPhase: frontierState.authSessionLoadPhase || "",
          loadAuthSessionReached: Boolean(frontierState.loadAuthSessionReached),
        },
        cloudAssetBuildId,
        visibleErrorBannerText,
        lastFrontendFatalError,
        frontierState,
      };
    })()`, true);
    return {
      ...base,
      currentUrl: renderer.href || base.currentUrl,
      title: renderer.title || base.title,
      readyState: renderer.readyState || "",
      authSessionStateSummary: renderer.authSessionStateSummary || {},
      cloudAssetBuildId: renderer.cloudAssetBuildId || "",
      visibleErrorBannerText: renderer.visibleErrorBannerText || "",
      lastFrontendFatalError: renderer.lastFrontendFatalError || null,
      frontendState: renderer.frontierState || {},
      appDataset: renderer.appDataset || {},
    };
  } catch (error) {
    return {
      ...base,
      ok: false,
      error: String(error && error.message ? error.message : error),
    };
  }
}

async function withScreenshotRedaction(win, callback) {
  if (!win || win.isDestroyed()) return callback();
  const styleId = `frontier-redaction-${Date.now()}`;
  try {
    await win.webContents.executeJavaScript(`(() => {
      const style = document.createElement("style");
      style.id = ${JSON.stringify(styleId)};
      style.textContent = [
        "input, textarea, [contenteditable='true'], [data-sensitive], [data-secret], .login-popover { filter: blur(12px) !important; }",
        "[data-sensitive], [data-secret] { color: transparent !important; text-shadow: 0 0 12px rgba(0,0,0,.7) !important; }"
      ].join("\\n");
      document.documentElement.appendChild(style);
    })()`, true);
    await sleep(75);
  } catch {
    // Redaction is best-effort; capture metadata still records the redaction attempt.
  }
  try {
    return await callback();
  } finally {
    try {
      await win.webContents.executeJavaScript(`document.getElementById(${JSON.stringify(styleId)})?.remove()`, true);
    } catch {
      // Ignore cleanup failure.
    }
  }
}

async function captureNativeScreenshot(options = {}) {
  const win = currentNativeWindow();
  if (!win || win.isDestroyed()) return { ok: false, error: "window_unavailable" };
  const redacted = options.redacted !== false;
  try {
    const image = redacted
      ? await withScreenshotRedaction(win, () => win.webContents.capturePage())
      : await win.webContents.capturePage();
    const timestamp = timestampForFilename();
    const target = path.join(nativeDiagnosticsBundleRoot(), `screenshot-${timestamp}.png`);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, image.toPNG());
    const size = image.getSize();
    return {
      ok: true,
      path: target,
      sha256: sha256File(target),
      width: size.width,
      height: size.height,
      redacted,
    };
  } catch (error) {
    return { ok: false, error: String(error && error.message ? error.message : error), redacted };
  }
}

async function fetchNativeBackendJson(pathname) {
  const config = ensureConfig();
  const serverUrl = selectedBackendOrigin || config.serverUrl || DEFAULT_SERVER_URL;
  const normalized = normalizeServerUrl(serverUrl, DEFAULT_SERVER_URL);
  const endpoint = new URL(pathname, normalized).toString();
  try {
    const fetchFromSession = typeof session.defaultSession.fetch === "function"
      ? session.defaultSession.fetch.bind(session.defaultSession)
      : fetchWithTimeout;
    const response = await fetchFromSession(endpoint, {
      method: "GET",
      credentials: "include",
      headers: { "X-Wasm-Agent-Native-Device-Id": config.deviceId },
    });
    let body = null;
    try {
      body = await response.clone().json();
    } catch {
      body = null;
    }
    return {
      ok: response.ok,
      url: endpoint,
      status: response.status,
      body: sanitizeRendererDiagnosticValue(body),
    };
  } catch (error) {
    return {
      ok: false,
      url: endpoint,
      status: 0,
      error: String(error && error.message ? error.message : error),
    };
  }
}

function diagnosticSummaryMarkdown(payload = {}) {
  const visual = payload.visualState || {};
  const authCookie = payload.authCookie || {};
  const authSession = payload.authSession || {};
  const lines = [
    "# WASM Agent Native Diagnostics",
    "",
    `- Generated: ${payload.generated_at || new Date().toISOString()}`,
    `- Route: ${visual.currentUrl || ""}`,
    `- Title: ${visual.title || ""}`,
    `- Ready: ${visual.readyState || ""}`,
    `- Loading: ${Boolean(visual.loading)}`,
    `- Native build: ${payload.build_id || ""}`,
    `- Cloud asset build: ${payload.cloud_asset_build_id || ""}`,
    `- authCookie.hasWaUid: ${Boolean(authCookie.hasWaUid)}`,
    `- /auth/session authenticated: ${Boolean(authSession.authenticated)}`,
    `- Last fatal error: ${visual.lastFrontendFatalError ? JSON.stringify(visual.lastFrontendFatalError).slice(0, 300) : ""}`,
    `- Visible error banner: ${visual.visibleErrorBannerText || ""}`,
  ];
  return `${lines.join("\n")}\n`;
}

async function uploadNativeDiagnosticsPayload(payload = {}) {
  const config = ensureConfig();
  const serverUrl = selectedBackendOrigin || await recoverReachableServerUrl(config);
  if (!serverUrl) return { ok: false, error: "backend_identity_unresolved" };
  try {
    const response = await fetchWithTimeout(new URL("/native/diagnostics", serverUrl).toString(), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Wasm-Agent-Native-Device-Id": config.deviceId,
        "X-Wasm-Agent-Native-Runtime": "electron",
      },
      body: JSON.stringify(payload),
    }, 8000);
    if (!response.ok) return { ok: false, error: `HTTP ${response.status}` };
    return await response.json();
  } catch (error) {
    return { ok: false, error: String(error && error.message ? error.message : error) };
  }
}

async function collectNativeDiagnosticsBundle(options = {}) {
  const config = ensureConfig();
  const generatedAt = new Date().toISOString();
  const visualState = await rendererVisualState();
  const authCookie = await nativeAuthCookieStatus();
  const authSession = await nativeAuthSessionStatus();
  const configJson = await fetchNativeBackendJson("/config.json");
  const sessionJson = await fetchNativeBackendJson("/auth/session");
  const runtimeDiagnostics = sanitizeRendererDiagnosticValue(runtimeDiagnosticsPayload({
    currentRoute: currentRendererUrl(),
    authCookie,
    authSession,
    last_frontend_fatal_error: visualState.lastFrontendFatalError || null,
  }));
  const screenshot = options.includeScreenshot ? await captureNativeScreenshot({ redacted: options.redacted !== false }) : null;
  const payload = {
    schema: "hermes.wasm_agent.native_full_diagnostic_bundle.v1",
    generated_at: generatedAt,
    reason: String(options.reason || "frontier").slice(0, 120),
    platform: "windows",
    runtime: "electron",
    device_id: config.deviceId,
    account_id: config.accountId,
    app_version: app.getVersion(),
    build_id: String(config.buildId || ""),
    cloud_asset_build_id: visualState.cloudAssetBuildId || "",
    app_asar_fingerprint: config.appAsarFingerprint || appAsarFingerprint(),
    selected_backend_origin: selectedBackendOrigin,
    visualState,
    authCookie,
    authSession,
    configJson,
    sessionJson,
    nativeBackendResolver: {
      candidateOrigins: startupDiagnostics.candidateOrigins,
      originChecks: startupDiagnostics.originChecks,
      finalSelectedOrigin: startupDiagnostics.finalSelectedOrigin,
      lastFailureReason: startupDiagnostics.lastFailureReason,
    },
    packageMetadata: {
      execPath: process.execPath || "",
      resourcesPath: process.resourcesPath || "",
      appAsarPath: appAsarPath(),
      appAsarSha256: sha256File(appAsarPath()),
      packageJson: readJsonFile(path.join(__dirname, "package.json"), {}),
      nativeDefaults: readNativeDefaults(),
      nativeDefaultsPath: nativeDefaultsPath(),
    },
    runtime_diagnostics: runtimeDiagnostics,
    logs: {
      mainLogPath: nativeMainLogPath(),
      mainLogTail: readTextTail(nativeMainLogPath(), 32 * 1024),
      preloadLogPath: rendererAuthDiagnosticsPath(),
      preloadLogTail: readTextTail(rendererAuthDiagnosticsPath(), 32 * 1024),
      rendererConsoleLogPath: rendererConsoleDiagnosticsPath(),
      rendererConsoleLogTail: readTextTail(rendererConsoleDiagnosticsPath(), 32 * 1024),
      fatalLogPath: nativeFatalDiagnosticsPath(),
      fatalLogTail: readTextTail(nativeFatalDiagnosticsPath(), 16 * 1024),
      nativeControlAuditPath: nativeControlAuditPath(),
      nativeControlAuditTail: readTextTail(nativeControlAuditPath(), 16 * 1024),
    },
    screenshot,
  };
  payload.summary_markdown = diagnosticSummaryMarkdown(payload);
  const bundleDir = path.join(nativeDiagnosticsBundleRoot(), `bundle-${timestampForFilename()}`);
  fs.mkdirSync(bundleDir, { recursive: true });
  const bundlePath = path.join(bundleDir, "bundle.json");
  const summaryPath = path.join(bundleDir, "SUMMARY.md");
  fs.writeFileSync(bundlePath, `${JSON.stringify(payload, null, 2)}\n`);
  fs.writeFileSync(summaryPath, payload.summary_markdown);
  writeRuntimeDiagnostics({
    authCookie,
    authSession,
    last_frontend_fatal_error: visualState.lastFrontendFatalError || null,
    latestDiagnosticBundlePath: bundlePath,
    latestDiagnosticSummaryPath: summaryPath,
    cloud_asset_build_id: visualState.cloudAssetBuildId || "",
  });
  return {
    ok: true,
    bundlePath,
    summaryPath,
    payload,
  };
}

async function postNativeControlResult(command, result = {}) {
  const config = ensureConfig();
  if (!selectedBackendOrigin) return { ok: false, error: "backend_identity_unresolved" };
  try {
    const response = await fetchWithTimeout(new URL("/native/control/result", selectedBackendOrigin).toString(), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Wasm-Agent-Native-Device-Id": config.deviceId,
      },
      body: JSON.stringify({
        schema: "hermes.wasm_agent.native_control_result.v1",
        device_id: config.deviceId,
        build_id: String(config.buildId || ""),
        command_id: String(command && command.id ? command.id : "unknown"),
        command_type: String(command && command.type ? command.type : "unknown"),
        result,
      }),
    }, 5000);
    if (!response.ok) return { ok: false, error: `HTTP ${response.status}` };
    return await response.json();
  } catch (error) {
    return { ok: false, error: String(error && error.message ? error.message : error) };
  }
}

async function executeNativeControlCommand(command = {}) {
  const type = String(command.type || "");
  const payload = command && typeof command.payload === "object" ? command.payload : {};
  const win = currentNativeWindow();
  logNativeDiagnostic("native-control-command", {
    id: command.id || "",
    type,
    reason: command.reason || payload.reason || "",
  });
  writeNativeControlAudit({
    action: "command_started",
    id: command.id || "",
    type,
    actor: command.created_by || payload.requested_by || "",
    reason: command.reason || payload.reason || "",
  });
  if (type === "upload_diagnostics") {
    const result = await uploadRendererAuthDiagnostics({ reason: `control:${command.id || type}` });
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "collect_logs" || type === "export_diagnostics") {
    const bundle = await collectNativeDiagnosticsBundle({
      reason: command.reason || payload.reason || `control:${command.id || type}`,
      includeScreenshot: Boolean(payload.includeScreenshot || payload.include_screenshot),
      redacted: payload.redacted !== false,
    });
    const upload = await uploadNativeDiagnosticsPayload(bundle.payload);
    const result = {
      ok: true,
      bundlePath: bundle.bundlePath,
      summaryPath: bundle.summaryPath,
      uploaded: upload,
    };
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "collect_adb_diagnostics") {
    const adbBundle = await collectAdbDiagnostics({
      reason: command.reason || payload.reason || `control:${command.id || type}`,
    });
    const nativeBundle = await collectNativeDiagnosticsBundle({
      reason: command.reason || payload.reason || `control:${command.id || type}`,
      includeScreenshot: Boolean(payload.includeScreenshot || payload.include_screenshot),
      redacted: payload.redacted !== false,
    });
    nativeBundle.payload.adbDiagnostics = adbBundle.payload;
    const upload = await uploadNativeDiagnosticsPayload(nativeBundle.payload);
    const result = {
      ok: true,
      adbBundlePath: adbBundle.bundlePath,
      adbSummaryPath: adbBundle.summaryPath,
      nativeBundlePath: nativeBundle.bundlePath,
      nativeSummaryPath: nativeBundle.summaryPath,
      deviceDetected: Boolean(adbBundle.payload.hasDevice),
      uploaded: upload,
    };
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "read_latest_android_report") {
    const report = readLatestAndroidSimulatorReport();
    const result = {
      ok: report.ok,
      report,
    };
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "verify_android_oauth") {
    if (process.platform !== "win32") {
      const result = { ok: false, status: "FAIL", error: "windows_native_shell_required" };
      writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
      return result;
    }
    const sender = win?.webContents || { send: () => {} };
    const opId = `control-android-oauth-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    const result = await runWindowsAndroidOAuthVerification(sender, opId);
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "screenshot") {
    const result = await captureNativeScreenshot({ redacted: payload.redacted !== false });
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "write_runtime_diagnostics") {
    const pathWritten = writeRuntimeDiagnostics({
      nativeControlCommandId: command.id || "",
      nativeControlCommandType: type,
      currentRoute: currentRendererUrl(),
    });
    const result = { ok: Boolean(pathWritten), path: pathWritten };
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "clear_web_cache" || type === "clear_cache") {
    const clearResult = await clearNativeWebShellCache();
    const reloadResult = await controlledNativeReload(win, {
      mode: "clear_cache",
      reason: command.reason || payload.reason || "",
      cacheBust: true,
    });
    const result = { ok: clearResult.ok && reloadResult.ok, clearCache: clearResult, reload: reloadResult };
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "reload") {
    const result = await controlledNativeReload(win, { mode: "reload", reason: command.reason || payload.reason || "" });
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "hard_reload" || type === "reload_ignore_cache") {
    const result = await controlledNativeReload(win, {
      mode: "reload_ignore_cache",
      reason: command.reason || payload.reason || "",
      hard: true,
      cacheBust: true,
    });
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "restart_app") {
    const result = {
      ok: true,
      restarting: true,
      route: currentRendererUrl(),
      scheduledInMs: 2000,
    };
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    setTimeout(() => {
      app.relaunch();
      app.exit(0);
    }, 2000).unref();
    return result;
  }
  if (type === "open_devtools") {
    if (win && !win.isDestroyed()) win.webContents.openDevTools({ mode: "detach" });
    const result = { ok: Boolean(win && !win.isDestroyed()), opened: Boolean(win && !win.isDestroyed()) };
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "verify_session") {
    const authCookie = await nativeAuthCookieStatus();
    const authSession = await nativeAuthSessionStatus();
    const visualState = await rendererVisualState();
    const result = {
      ok: Boolean(authCookie.hasWaUid && authSession.authenticated),
      authCookie,
      authSession,
      visualState,
      failureClassification: classifyNativeSessionFailure(authCookie, authSession, visualState),
    };
    writeRuntimeDiagnostics({ authCookie, authSession, last_frontend_fatal_error: visualState.lastFrontendFatalError || null });
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "verify_installed_app") {
    const bundle = await collectNativeDiagnosticsBundle({
      reason: command.reason || payload.reason || "verify_installed_app",
      includeScreenshot: Boolean(payload.includeScreenshot || payload.include_screenshot),
    });
    const result = {
      ok: Boolean(bundle.payload.authCookie?.hasWaUid && bundle.payload.authSession?.authenticated),
      currentSessionVerified: Boolean(bundle.payload.authCookie?.hasWaUid && bundle.payload.authSession?.authenticated),
      requiresExternalCloseReopenVerifier: true,
      verifierScript: "native/windows/scripts/verify-installed-app.ps1",
      bundlePath: bundle.bundlePath,
      summaryPath: bundle.summaryPath,
      failureClassification: classifyNativeSessionFailure(bundle.payload.authCookie, bundle.payload.authSession, bundle.payload.visualState),
    };
    await uploadNativeDiagnosticsPayload(bundle.payload);
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "status") {
    const authDiagnostics = await writeAuthPersistenceDiagnostics("native-control-status");
    const visualState = await rendererVisualState();
    const result = {
      ok: true,
      status: "online",
      appVersion: app.getVersion(),
      arch: os.arch(),
      route: currentRendererUrl(),
      authCookie: authDiagnostics.authCookie,
      authSession: authDiagnostics.authSession,
      visualState,
      lastReload: lastReloadCommand,
      diagnosticsPath: runtimeDiagnosticsPath(),
      rendererAuthDiagnosticsPath: rendererAuthDiagnosticsPath(),
      rendererConsoleDiagnosticsPath: rendererConsoleDiagnosticsPath(),
      nativeControlAuditPath: nativeControlAuditPath(),
    };
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  const result = { ok: false, error: `unsupported_command:${type}` };
  writeNativeControlAudit({ action: "command_refused", id: command.id || "", type, result });
  return result;
}

async function pollNativeControl(reason = "interval") {
  if (nativeControlPollBusy || !selectedBackendOrigin) return { ok: false, error: "not_ready" };
  nativeControlPollBusy = true;
  const config = ensureConfig();
  try {
    const url = new URL("/native/control/poll", selectedBackendOrigin);
    url.searchParams.set("device_id", config.deviceId);
    url.searchParams.set("build_id", String(config.buildId || ""));
    url.searchParams.set("app_version", app.getVersion());
    url.searchParams.set("route", currentRendererUrl());
    url.searchParams.set("reason", reason);
    const response = await fetchWithTimeout(url.toString(), {
      headers: {
        "Accept": "application/json",
        "X-Wasm-Agent-Native-Device-Id": config.deviceId,
        "X-Wasm-Agent-Native-Runtime": "electron",
      },
    }, 5000);
    if (!response.ok) return { ok: false, error: `HTTP ${response.status}` };
    const payload = await response.json();
    const commands = Array.isArray(payload.commands) ? payload.commands : [];
    for (const command of commands) {
      let result = {};
      try {
        result = await executeNativeControlCommand(command);
      } catch (error) {
        result = { ok: false, error: String(error && error.message ? error.message : error) };
      }
      await postNativeControlResult(command, result);
    }
    return { ok: true, commandCount: commands.length };
  } catch (error) {
    return { ok: false, error: String(error && error.message ? error.message : error) };
  } finally {
    nativeControlPollBusy = false;
  }
}

function startNativeControlPolling() {
  setTimeout(() => {
    void pollNativeControl("startup");
  }, 5000).unref();
  setInterval(() => {
    void pollNativeControl("interval");
  }, NATIVE_CONTROL_POLL_INTERVAL_MS).unref();
}

function showFallback(win, reason) {
  if (!win || win.isDestroyed()) return;
  const config = ensureConfig();
  const savedConfigRaw = startupDiagnostics.savedConfigRawJson || readConfigRaw();
  const savedConfig = readConfig();
  const nativeDefaults = nativeDefaultsDiagnostics();
  const finalCandidates = configuredServerUrlCandidates(config, { logDiscards: true });
  const displayServerUrl = productionSafeServerUrl(config.serverUrl, DEFAULT_SERVER_URL, config.savedConfigSource || "saved-config");
  const testedCandidateSource = startupDiagnostics.candidateEntries.find((entry) => entry.serverUrl === displayServerUrl)?.source
    || candidateSourceFor(displayServerUrl, config)
    || "fallback-html-default";
  const diagnostics = {
    ...runtimeDiagnosticsPayload({
      lastTestedUrl: new URL("/config.json", displayServerUrl).toString(),
      lastFailureReason: compactLoadReason(reason, displayServerUrl),
    }),
    buildGeneratedAt: config.buildGeneratedAt,
    buildId: config.buildId,
    installableVersion: config.installableVersion,
    packagedDefaultServerUrl: config.packagedDefaultServerUrl || DEFAULT_SERVER_URL,
    nativeDefaultsPath: nativeDefaults.path,
    nativeDefaultsServerUrl: nativeDefaults.serverUrl,
    nativeDefaultsServerUrlCandidates: nativeDefaults.serverUrlCandidates,
    savedConfigPath: configPath(),
    savedConfigRawJson: savedConfigRaw,
    savedConfigUserExplicit: startupDiagnostics.savedConfigUserExplicit ?? savedConfig.userExplicit,
    envWasmAgentDefaultServerUrl: process.env.WASM_AGENT_DEFAULT_SERVER_URL || "",
    envWasmAgentAllowLocalDev: process.env.WASM_AGENT_ALLOW_LOCAL_DEV || "",
    serverUrlCandidates: finalCandidates,
    candidateEntries: startupDiagnostics.candidateEntries,
    discardedCandidateOrigins: startupDiagnostics.discardedCandidateOrigins,
    selectedTestedCandidateSource: testedCandidateSource,
    appAsarFingerprint: config.appAsarFingerprint || appAsarFingerprint(),
    savedConfigSource: config.savedConfigSource || "packaged-default",
    finalSelectedOrigin: startupDiagnostics.finalSelectedOrigin,
  };
  startupDiagnostics.lastTestedUrl = diagnostics.lastTestedUrl;
  startupDiagnostics.lastFailureReason = diagnostics.lastFailureReason;
  writeRuntimeDiagnostics(diagnostics);
  win.loadFile(fallbackPagePath(), {
    query: {
      serverUrl: displayServerUrl,
      testedUrl: new URL("/config.json", displayServerUrl).toString(),
      reason: diagnostics.lastFailureReason,
      diagnostics: JSON.stringify(diagnostics),
    },
  }).catch((error) => {
    if (!isNavigationAbort(error)) console.warn(`Could not load fallback page: ${error.message || error}`);
  });
}

function backendHomeElectronUrl(serverUrl) {
  const url = new URL(PWA_HOME_PATH, serverUrl);
  url.searchParams.set("native", "electron");
  return url.toString();
}

function loadConfiguredServer(win) {
  selectReachableServerUrl().then((serverUrl) => {
    const startUrl = serverUrl ? backendHomeElectronUrl(serverUrl) : "";
    startupDiagnostics.startUrl = startUrl || fallbackPagePath();
    startupDiagnostics.uiSource = serverUrl ? "remote-pwa" : describeUiSource();
    logNativeDiagnostic("startup", startupDiagnostics);
    console.log(`[native] resolved backend: ${serverUrl || ""}`);
    console.log(`[native] config googleClientIdConfigured: ${Boolean(startupDiagnostics.originChecks.find((result) => result.serverUrl === serverUrl)?.googleClientIdConfigured)}`);
    console.log(`[native] final loaded URL: ${startUrl || fallbackPagePath()}`);
    if (!startUrl) {
      showFallback(win, "No validated cloud wasm-agent backend was found.");
      return;
    }
    win.loadURL(startUrl).catch((error) => {
      if (serverUrl && !isNavigationAbort(error)) {
        logNativeDiagnostic("remote-pwa-fallback", {
          failedUrl: startUrl,
          fallbackUrl: fallbackPagePath(),
          reason: compactLoadReason(error, serverUrl),
        });
        showFallback(win, error.message || String(error));
        return;
      }
      if (!isNavigationAbort(error)) showFallback(win, error.message || String(error));
    });
  });
}

function reloadWindow(win, options = {}) {
  if (!win || win.isDestroyed()) return;
  if (options.hard) {
    win.webContents.reloadIgnoringCache();
    return;
  }
  win.webContents.reload();
}

function classifyNativeSessionFailure(authCookie = {}, authSession = {}, visualState = {}) {
  if (visualState.lastFrontendFatalError) return "frontend bootstrap crash";
  if (!authCookie.hasWaUid) return "cookie missing";
  const cookieMeta = Array.isArray(authCookie.cookieMeta) ? authCookie.cookieMeta : [];
  const firstCookie = cookieMeta[0] || {};
  if (firstCookie.domain && !String(firstCookie.domain).includes("wa.colmeio.com")) return "cookie wrong domain";
  if (authSession.status && !authSession.authenticated) return "cookie wrong partition";
  const route = String(visualState.currentUrl || currentRendererUrl() || "");
  if (/auth_error|auth_code/.test(route)) return "Google redirect/code redemption failure";
  if (route.startsWith("file:") || route.startsWith("wasm-agent:")) return "native shell issue";
  return "unknown";
}

async function controlledNativeReload(win, options = {}) {
  if (!win || win.isDestroyed()) return { ok: false, error: "window_unavailable" };
  const config = ensureConfig();
  const reason = String(options.reason || "").slice(0, 240);
  const mode = String(options.mode || (options.hard ? "reload_ignore_cache" : "reload"));
  const beforeRoute = currentRendererUrl();
  const startedAt = new Date().toISOString();
  if (options.clearCache) await clearNativeWebShellCache();
  let targetUrl = "";
  try {
    if (options.cacheBust) {
      const base = beforeRoute && beforeRoute.startsWith("http")
        ? beforeRoute
        : selectedBackendOrigin
          ? backendHomeElectronUrl(selectedBackendOrigin)
          : "";
      if (base) {
        const url = new URL(base);
        if (selectedBackendOrigin && sameOrigin(selectedBackendOrigin, url.toString())) {
          url.searchParams.set("native", "electron");
          url.searchParams.set("frontierReload", String(config.buildId || Date.now()));
          targetUrl = url.toString();
          await win.loadURL(targetUrl);
        }
      }
    }
    if (!targetUrl) reloadWindow(win, { hard: Boolean(options.hard) });
    lastReloadCommand = {
      schema: "hermes.wasm_agent.native_reload.v1",
      startedAt,
      finishedAt: new Date().toISOString(),
      mode,
      reason,
      beforeRoute,
      targetUrl,
      reloadIgnoringCache: Boolean(options.hard),
      cacheBust: Boolean(options.cacheBust),
      buildId: String(config.buildId || ""),
    };
    writeRuntimeDiagnostics({ lastReload: lastReloadCommand, currentRoute: currentRendererUrl() });
    logNativeDiagnostic("native-reload", lastReloadCommand);
    return { ok: true, reloaded: true, mode, hard: Boolean(options.hard), cacheBust: Boolean(options.cacheBust), beforeRoute, targetUrl, route: currentRendererUrl() };
  } catch (error) {
    lastReloadCommand = {
      schema: "hermes.wasm_agent.native_reload.v1",
      startedAt,
      finishedAt: new Date().toISOString(),
      mode,
      reason,
      beforeRoute,
      targetUrl,
      ok: false,
      error: String(error && error.message ? error.message : error),
    };
    writeRuntimeDiagnostics({ lastReload: lastReloadCommand, currentRoute: currentRendererUrl() });
    return { ok: false, error: lastReloadCommand.error, beforeRoute, targetUrl };
  }
}

async function clearNativeWebShellCache() {
  try {
    await session.defaultSession.clearCache();
    await session.defaultSession.clearStorageData({
      storages: ["serviceworkers", "cachestorage", "localstorage"],
    });
    logNativeDiagnostic("web-cache-cleared", {
      storages: ["http", "serviceworkers", "cachestorage", "localstorage"],
    });
    return { ok: true, storages: ["http", "serviceworkers", "cachestorage", "localstorage"] };
  } catch (error) {
    const reason = String(error && error.message ? error.message : error);
    logNativeDiagnostic("web-cache-clear-failed", { reason });
    return { ok: false, error: reason };
  }
}

function createWindow() {
  const config = ensureConfig();
  const icon = nativeIconPath();
  startupDiagnostics.appRoot = __dirname;
  startupDiagnostics.resourcesPath = process.resourcesPath || "";
  startupDiagnostics.bundledPublicRoot = publicRootPath();
  startupDiagnostics.uiSource = describeUiSource();
  startupDiagnostics.candidateOrigins = configuredServerUrlCandidates(config);
  startupDiagnostics.resolvedBackendOrigin = config.serverUrl;
  logNativeDiagnostic("app-root", {
    appRoot: startupDiagnostics.appRoot,
    resourcesPath: startupDiagnostics.resourcesPath,
    publicRoot: startupDiagnostics.bundledPublicRoot,
    uiSource: startupDiagnostics.uiSource,
    startUrl: startupDiagnostics.startUrl,
  });
  const win = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 960,
    minHeight: 640,
    title: "WASM Agent",
    backgroundColor: "#090d12",
    autoHideMenuBar: true,
    icon,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, "preload.js"),
      additionalArguments: [`--wasm-agent-server-url=${config.serverUrl}`, `--wasm-agent-device-id=${config.deviceId}`],
    },
  });
  const userAgent = chromeLikeUserAgent(win.webContents.getUserAgent());
  if (userAgent) win.webContents.setUserAgent(userAgent);

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (isPackagedFallbackUrl(url)) return { action: "allow" };
    if (isGoogleAuthUrl(url)) return { action: "allow" };
    if ((selectedBackendOrigin && sameOrigin(selectedBackendOrigin, url)) || sameOrigin(NATIVE_APP_HOME_URL, url)) {
      win.loadURL(url).catch((error) => {
        if (!isNavigationAbort(error)) console.warn(`Could not route auth popup in main window: ${error.message || error}`);
      });
      return { action: "deny" };
    }
    shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (event, url) => {
    if (isPackagedFallbackUrl(url)) return;
    if (url.startsWith("file:")) {
      event.preventDefault();
      return;
    }
    if (selectedBackendOrigin && sameOrigin(selectedBackendOrigin, url)) return;
    if (sameOrigin(NATIVE_APP_HOME_URL, url)) return;
    if (isGoogleAuthUrl(url)) return;
    if (url.startsWith("http://") || url.startsWith("https://")) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });
  win.webContents.on("did-fail-load", (event, errorCode, errorDescription, validatedURL, isMainFrame) => {
    const failedUrl = String(validatedURL || "");
    appendJsonLine(nativeFatalDiagnosticsPath(), {
      timestamp: new Date().toISOString(),
      kind: "did-fail-load",
      errorCode,
      errorDescription,
      validatedURL: failedUrl,
      isMainFrame: Boolean(isMainFrame),
    });
    if (isMainFrame && !failedUrl.startsWith("file:") && errorCode !== -3) {
      if (selectedBackendOrigin && sameOrigin(selectedBackendOrigin, failedUrl)) {
        logNativeDiagnostic("remote-pwa-fallback", {
          failedUrl,
          fallbackUrl: fallbackPagePath(),
          reason: errorDescription || `Connection failed (${errorCode})`,
        });
        showFallback(win, errorDescription || `Connection failed (${errorCode})`);
        return;
      }
      showFallback(win, errorDescription || `Connection failed (${errorCode})`);
    }
  });
  win.webContents.on("console-message", (_event, level, message, line, sourceId) => {
    appendJsonLine(rendererConsoleDiagnosticsPath(), {
      timestamp: new Date().toISOString(),
      level,
      message: String(message || "").slice(0, 2000),
      line,
      sourceId: String(sourceId || "").slice(0, 600),
      route: currentRendererUrl(),
    });
  });
  win.webContents.on("render-process-gone", (_event, details) => {
    appendJsonLine(nativeFatalDiagnosticsPath(), {
      timestamp: new Date().toISOString(),
      kind: "render-process-gone",
      details: sanitizeRendererDiagnosticValue(details || {}),
      route: currentRendererUrl(),
    });
    writeRuntimeDiagnostics({ last_frontend_fatal_error: { kind: "render-process-gone", details: sanitizeRendererDiagnosticValue(details || {}) } });
  });
  win.webContents.on("preload-error", (_event, preloadPath, error) => {
    appendJsonLine(nativeFatalDiagnosticsPath(), {
      timestamp: new Date().toISOString(),
      kind: "preload-error",
      preloadPath: String(preloadPath || ""),
      error: String(error && error.message ? error.message : error),
      stack: String(error && error.stack ? error.stack : "").slice(0, 1800),
      route: currentRendererUrl(),
    });
  });
  win.on("unresponsive", () => {
    appendJsonLine(nativeFatalDiagnosticsPath(), {
      timestamp: new Date().toISOString(),
      kind: "window-unresponsive",
      route: currentRendererUrl(),
    });
  });
  win.webContents.on("did-navigate", (_event, url) => {
    startupDiagnostics.currentRoute = url;
    logNativeDiagnostic("route", {
      currentRoute: url,
      uiSource: startupDiagnostics.uiSource,
      selectedBackendOrigin,
    });
  });
  win.webContents.on("did-finish-load", () => {
    startupDiagnostics.currentRoute = win.webContents.getURL();
    void uploadRendererAuthDiagnostics({ reason: "native-did-finish-load" });
    void writeAuthPersistenceDiagnostics("native-did-finish-load");
  });
  win.webContents.on("before-input-event", (event, input) => {
    const key = String(input.key || "").toLowerCase();
    if ((input.control || input.meta) && key === "r") {
      event.preventDefault();
      reloadWindow(win, { hard: Boolean(input.shift) });
      setTimeout(() => {
        void uploadRendererAuthDiagnostics({ reason: input.shift ? "native-hard-refresh" : "native-refresh" });
      }, 1500).unref();
    }
  });
  loadConfiguredServer(win);
  setTimeout(() => {
    void uploadRendererAuthDiagnostics({ reason: "native-window-created" });
  }, 2500).unref();
  return win;
}

app.setName("WASM Agent");
Menu.setApplicationMenu(null);

ipcMain.handle("wasm-agent:native-config", async () => nativeConfigPayload());

ipcMain.handle("wasm-agent:native-configure", (_event, update = {}) => {
  const current = ensureConfig();
  const serverUrl = normalizeServerUrl(update.serverUrl || current.serverUrl || DEFAULT_SERVER_URL);
  if (isProductionBackendMode() && isLocalDevCandidateUrl(serverUrl)) {
    const reason = "discarded local dev backend in production";
    logNativeDiagnostic("discarded-local-dev-backend", { serverUrl, source: "manual-configure", reason });
    return { ok: false, reason, config: { serverUrl: current.serverUrl, deviceId: current.deviceId, registered: Boolean(current.deviceToken) } };
  }
  const next = {
    ...current,
    serverUrl,
    serverUrlCandidates: configuredServerUrlCandidates({ ...current, serverUrl }),
    userExplicit: update.serverUrl ? true : hasExplicitCustomServer(current),
    savedCustomServerUrl: update.serverUrl ? true : hasExplicitCustomServer(current),
    accountId: String(update.accountId || current.accountId || ""),
    deviceToken: String(update.deviceToken || current.deviceToken || ""),
    updatedAt: new Date().toISOString(),
  };
  writeConfig(next);
  selectedBackendOrigin = "";
  startupDiagnostics.finalSelectedOrigin = "";
  return { ok: true, config: { serverUrl: next.serverUrl, deviceId: next.deviceId, registered: Boolean(next.deviceToken) } };
});

ipcMain.handle("wasm-agent:native-test-backend", async (_event, serverUrl) => {
  const current = ensureConfig();
  const normalized = normalizeServerUrl(serverUrl || current.serverUrl || DEFAULT_SERVER_URL);
  if (isProductionBackendMode() && isLocalDevCandidateUrl(normalized)) {
    const reason = "discarded local dev backend in production";
    logNativeDiagnostic("discarded-local-dev-backend", { serverUrl: normalized, source: "manual-test", reason });
    return { ok: false, serverUrl: normalized, reason, checks: [], googleClientIdConfigured: false };
  }
  console.log(`[native] testing backend candidate: ${normalized}`);
  const result = await validateWasmAgentOrigin(normalized, current, 5000);
  console.log(`[native] result: ${result.ok ? "success" : "failure"} ${normalized} ${result.reason || "HTTP 200 valid JSON"}`);
  if (result.ok) {
    acceptValidatedBackend(current, normalized);
    console.log(`[native] selected backend: ${normalized}`);
  }
  return result;
});

ipcMain.handle("wasm-agent:native-auth-diagnostic", (_event, kind, payload = {}) => writeRendererAuthDiagnostic(kind, payload));

ipcMain.handle("wasm-agent:native-upload-auth-diagnostics", () => uploadRendererAuthDiagnostics({ reason: "manual" }));

ipcMain.handle("wasm-agent:native-flush-auth-cookies", (_event, options = {}) => flushNativeAuthCookies(options || {}));

ipcMain.handle("wasm-agent:native-reload", (event) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  if (win) loadConfiguredServer(win);
  return { ok: true };
});

ipcMain.handle("wasm-agent:native-dev-hmr-reload", (event, paths = []) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  reloadWindow(win, { hard: Array.isArray(paths) && paths.some((item) => String(item || "").includes("boot.js")) });
  return { ok: true };
});

ipcMain.handle("wasm-agent:native-status", () => postNativeEvent("device.status", {
  status: "online",
  app_version: app.getVersion(),
  hostname: os.hostname(),
  arch: os.arch(),
}));

ipcMain.handle("wasm-agent:native-diagnostics-operation", (event, operation) => handleWindowsNativeDiagnosticsOperation(event, operation));

app.whenReady().then(async () => {
  registerNativeAppProtocol();
  await clearNativeWebShellCache();
  createWindow();
  void postNativeEvent("native.install_status", { status: "launched", app_version: app.getVersion() });
  void postNativeEvent("native.capabilities", {
    desktop_app: true,
    persistent_config: true,
    device_registration_ready: true,
    heartbeat_ready: true,
    native_control_poll_ready: true,
    native_diagnostics_upload_ready: true,
	    frontier_operator_commands_ready: true,
	    frontier_visual_state_ready: true,
	    frontier_diagnostic_bundle_ready: true,
	    windows_android_oauth_verification_ready: process.platform === "win32",
	  });
  void postNativeEvent("device.status", { status: "online", app_version: app.getVersion(), arch: os.arch() });
  startNativeControlPolling();
  setInterval(() => {
    void postNativeEvent("device.heartbeat", { status: "online", app_version: app.getVersion(), arch: os.arch() });
  }, HEARTBEAT_INTERVAL_MS).unref();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("before-quit", () => {
  void flushNativeAuthCookies({ reason: "before_quit" });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
