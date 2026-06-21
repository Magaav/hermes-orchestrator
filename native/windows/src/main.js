const { app, BrowserWindow, Menu, ipcMain, protocol, session, shell } = require("electron");
const fs = require("fs");
const crypto = require("crypto");
const os = require("os");
const path = require("path");
const { execFile, spawn } = require("child_process");
const { once } = require("events");
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
const {
  feedUrlFor,
  stagedInstallerPath,
  validateDownloadedInstaller,
  validateReleaseArtifact,
  windowsArtifactFromFeed,
} = require("./windows-self-update");

const HEARTBEAT_INTERVAL_MS = 30_000;
const NATIVE_CONTROL_POLL_INTERVAL_MS = 15_000;
const NATIVE_OBS_HEARTBEAT_INTERVAL_MS = 1000;
const NATIVE_OBS_RECONNECT_MS = 2500;
const WAO_HEADER_BYTES = 40;
const WAO_TLV_HEADER_BYTES = 8;
const WAO_VERSION = 1;
const WAO_TLV_NULL = 0;
const WAO_TLV_BOOL = 1;
const WAO_TLV_I64 = 2;
const WAO_TLV_F64 = 3;
const WAO_TLV_UTF8 = 4;
const WAO_TLV_BYTES = 5;
const WAO_TLV_JSON = 6;
const WAO_FRAME_TYPES = {
  HELLO: 1,
  DICT: 2,
  EVENT: 3,
  STATE_PATCH: 4,
  COMMAND: 5,
  COMMAND_ACK: 6,
  SNAPSHOT_REQ: 7,
  SNAPSHOT: 8,
  BLOB_CHUNK: 9,
  HEARTBEAT: 10,
  ERROR: 11,
};
const WAO_FRAME_TYPE_NAMES = Object.fromEntries(Object.entries(WAO_FRAME_TYPES).map(([key, value]) => [value, key]));
const WAO_FIELD_IDS = {
  device_id: 1,
  stream: 2,
  type: 3,
  key: 4,
  ts_ms: 5,
  command_id: 6,
  op: 7,
  status: 8,
  priority: 9,
  deadline_ms: 10,
  result_json: 11,
  payload_json: 12,
  reason: 13,
  route: 14,
  build_id: 15,
  app_version: 16,
  runtime: 17,
  seq_start: 18,
  seq_end: 19,
  latency_ms: 20,
  evidence_refs: 21,
  topics: 22,
  cursor: 23,
  token_budget: 24,
  snapshot_json: 25,
  kind: 26,
  schema: 27,
  role: 28,
};
const WAO_FIELD_NAMES = Object.fromEntries(Object.entries(WAO_FIELD_IDS).map(([key, value]) => [value, key]));
const AUTH_COOKIE_WAIT_TIMEOUT_MS = 5000;
const AUTH_COOKIE_WAIT_INTERVAL_MS = 200;
const NATIVE_APP_ORIGIN = "wasm-agent://app";
const NATIVE_APP_HOME_URL = `${NATIVE_APP_ORIGIN}/home`;
const WINDOWS_ANDROID_OAUTH_OPERATIONS = new Set([
  "run_hot_operation",
  "get_native_kernel_status",
  "list_hot_operations",
  "refresh_downloaded_runtime",
  "sync_downloaded_runtime",
  "rollback_downloaded_runtime",
  "refresh_downloaded_hot_ops",
  "sync_downloaded_hot_ops",
  "run_shell_self_test",
  "check_android_connection",
  "adb_version",
  "adb_devices",
  "debug_android_voice_tuning_runtime",
  "export_hermes_wake_dataset",
  "run_android_hermes_wake_proof",
  "play_wake_phrase_probe",
  "play_audio_stimulus",
  "prove_android_voice_tuning",
  "run_android_voice_tuning_goal_loop",
  "verify_android_oauth",
  "read_latest_android_report",
  "open_latest_android_report",
  "request_windows_client_update",
]);
const HOT_OPERATION_PROTOCOL_VERSION = 1;
const SHELL_PROTOCOL_VERSION = 2;
const DOWNLOADED_RUNTIME_PROTOCOL_VERSION = 1;
const NATIVE_KERNEL_CONTRACT_VERSION = "2026.06.14";
const MINIMUM_RUNNER_VERSION = "20260612";
const HOT_OPERATION_DEFAULT_TIMEOUT_MS = 45_000;
const HOT_OPERATION_MANIFEST_SUFFIX = ".manifest.json";
const BRIDGE_LOG_TAIL_LIMIT = 120;
const ALL_NATIVE_KERNEL_CAPABILITIES = [
  "native.capabilities.runtimeLoader.v1",
  "native.capabilities.hotOps.v1",
  "native.capabilities.statusBus.v1",
  "native.capabilities.diagnostics.v1",
  "native.capabilities.fileStore.v1",
  "native.capabilities.downloadedRuntime.v1",
  "native.capabilities.downloadedOperations.v1",
  "native.capabilities.deviceControl.v1",
  "native.capabilities.audioCapture.v1",
  "native.capabilities.modelRuntime.v1",
  "native.capabilities.foregroundSession.v1",
  "native.capabilities.webViewBridge.v1",
  "native.capabilities.boundedCommand.v1",
  "native.capabilities.auditLog.v1",
  "native.capabilities.releaseFeedValidation.v1",
  "native.capabilities.nativeControlPolling.v1",
  "native.capabilities.speaker.v1",
  "native.capabilities.crashSafeStatus.v1",
  "native.capabilities.capabilityManifest.v1",
];
const WINDOWS_NATIVE_KERNEL_CAPABILITIES = [
  "native.capabilities.runtimeLoader.v1",
  "native.capabilities.hotOps.v1",
  "native.capabilities.statusBus.v1",
  "native.capabilities.diagnostics.v1",
  "native.capabilities.fileStore.v1",
  "native.capabilities.downloadedRuntime.v1",
  "native.capabilities.downloadedOperations.v1",
  "native.capabilities.deviceControl.v1",
  "native.capabilities.webViewBridge.v1",
  "native.capabilities.boundedCommand.v1",
  "native.capabilities.auditLog.v1",
  "native.capabilities.releaseFeedValidation.v1",
  "native.capabilities.nativeControlPolling.v1",
  "native.capabilities.crashSafeStatus.v1",
  "native.capabilities.capabilityManifest.v1",
];
const BRIDGE_PROTOCOL_CAPABILITIES = [
  "get_bridge_status",
  "get_native_kernel_status",
  "list_hot_operations",
  "refresh_downloaded_runtime",
  "sync_downloaded_runtime",
  "rollback_downloaded_runtime",
  "refresh_downloaded_hot_ops",
  "sync_downloaded_hot_ops",
  "run_shell_self_test",
  "run_hot_operation",
];
const bridgeLogsTail = [];
const NATIVE_CONTROL_DEFAULT_TIMEOUT_MS = 60_000;
const NATIVE_CONTROL_MAX_TIMEOUT_MS = 240_000;
let selectedBackendOrigin = "";
let nativeControlPollBusy = false;
let nativeObsSocket = null;
let nativeObsConnected = false;
let nativeObsHeartbeatTimer = null;
let nativeObsReconnectTimer = null;
let nativeObsSeq = 1;
let activeNativeCommandCount = 0;
let activeWindowsSelfUpdate = null;
let lastDownloadedRuntimeSync = { ok: false, changed: false, attemptedAt: "", syncedAt: "", feedUrl: "", error: "", status: "not_attempted", feedBundleId: "", cachedBundleId: "", activeRuntimeId: "", activeRuntimeSha: "", activeRuntimePath: "", staleReason: "", fallbackReason: "", files: [] };
let downloadedRuntimeSyncPromise = null;
let lastHotOperationBundleSync = { ok: false, changed: false, attemptedAt: "", syncedAt: "", feedUrl: "", error: "", feedBundleId: "", cachedBundleId: "", moduleSha: "", manifestSha: "", cachePath: "", bundles: [] };
let hotOperationBundleSyncPromise = null;
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

function statFile(filePath) {
  try {
    return fs.statSync(filePath);
  } catch {
    return null;
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

function nativeUpdateAuditPath() {
  return path.join(nativeAppDataDir(), "windows-self-update-audit.log");
}

function windowsSelfUpdateStagingRoot() {
  return path.join(nativeAppDataDir(), "staged", "windows-updates");
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
  bridgeLogsTail.push(JSON.stringify(entry));
  while (bridgeLogsTail.length > BRIDGE_LOG_TAIL_LIMIT) bridgeLogsTail.shift();
  appendJsonLine(nativeControlAuditPath(), entry);
  return entry;
}

function recentBridgeLogsTail(limit = 80) {
  return bridgeLogsTail.slice(-Math.max(1, Math.min(Number(limit) || 80, BRIDGE_LOG_TAIL_LIMIT)));
}

function writeNativeUpdateAudit(event = {}) {
  const entry = {
    schema: "hermes.wasm_agent.windows_self_update_audit.v1",
    timestamp: new Date().toISOString(),
    ...sanitizeRendererDiagnosticValue(event),
  };
  appendJsonLine(nativeUpdateAuditPath(), entry);
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

function execFileBufferBounded(command, args = [], options = {}) {
  return new Promise((resolve) => {
    const startedAt = Date.now();
    execFile(command, args, {
      timeout: Number(options.timeoutMs || 8000),
      maxBuffer: Number(options.maxBuffer || 512 * 1024),
      cwd: options.cwd || undefined,
      env: options.env || process.env,
      windowsHide: true,
      encoding: "buffer",
    }, (error, stdout, stderr) => {
      resolve({
        ok: !error,
        command: [command, ...args].join(" "),
        exitCode: typeof error?.code === "number" ? error.code : error ? 1 : 0,
        signal: error?.signal || "",
        timedOut: Boolean(error?.killed),
        elapsedMs: Date.now() - startedAt,
        stdout: Buffer.isBuffer(stdout) ? stdout : Buffer.from(stdout || ""),
        stderr: Buffer.isBuffer(stderr) ? clipDiagnosticText(stderr.toString("utf8")) : clipDiagnosticText(stderr || ""),
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
    commandResults.logcat = await runAdbDiagnosticCommand(adbPath, ["logcat", "-d", "-t", "2500", "-v", "time"], { timeoutMs: 12000, maxBuffer: 2 * 1024 * 1024 });
    commandResults.logcatCrash = await runAdbDiagnosticCommand(adbPath, ["logcat", "-b", "crash", "-d", "-t", "800", "-v", "time"], { timeoutMs: 12000, maxBuffer: 2 * 1024 * 1024 });
  }
  const interestingLogPattern = /com\.colmeio\.wasmagent|wasmagent|WASM Agent|wa\.colmeio\.com|android-auth-return|native\/android\/auth|accounts\.google\.com|ActivityTaskManager|START u0|ChromeTabbedActivity|webapk|MIUILOG|Permission Denied|AndroidRuntime|FATAL EXCEPTION|SpeechRecognizer|RecognitionService|HermesVoiceWakeService/i;
  const crashLogPattern = /AndroidRuntime|FATAL EXCEPTION|Process:\s*com\.colmeio\.wasmagent|Process\s+com\.colmeio\.wasmagent.*has died|Force finishing activity.*com\.colmeio\.wasmagent|SpeechRecognizer.*(?:Exception|Error|crash|died)|RecognitionService.*(?:Exception|Error|crash|died)|HermesVoiceWakeService.*(?:Exception|Error|crash|died)/i;
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
      crashLogcat: filterDiagnosticLines(`${commandResults.logcatCrash?.stdout || ""}\n${commandResults.logcat?.stdout || ""}`, crashLogPattern, 260),
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

function emitWindowsUpdateEvent(sender, opId, step, detail = {}) {
  const payload = {
    type: "progress",
    operation: "request_windows_client_update",
    opId,
    step,
    status: detail.ok === false ? "failed" : "ok",
    ...detail,
  };
  writeNativeUpdateAudit({ action: step, opId, detail: payload });
  return emitWindowsDiagnosticEvent(sender, payload);
}

async function fetchJsonWithTimeout(url, timeoutMs = 10000) {
  const response = await fetchWithTimeout(url, { method: "GET", headers: { "Cache-Control": "no-cache" } }, timeoutMs);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function currentWindowsBuildInfo() {
  const config = ensureConfig();
  const defaults = readNativeDefaults();
  return {
    buildId: String(config.buildId || defaults.buildId || ""),
    version: String(config.installableVersion || defaults.installableVersion || config.nativeShellVersion || defaults.nativeShellVersion || app.getVersion()),
    appVersion: app.getVersion(),
    productionTarget: normalizeServerUrl(selectedBackendOrigin || config.serverUrl || DEFAULT_SERVER_URL),
  };
}

async function downloadWindowsInstallerArtifact(sender, opId, artifact, payload = {}) {
  const timeoutMs = Math.max(1000, Math.min(Number(payload.downloadTimeoutMs || payload.download_timeout_ms || 300_000), 900_000));
  fs.mkdirSync(windowsSelfUpdateStagingRoot(), { recursive: true });
  const target = stagedInstallerPath(windowsSelfUpdateStagingRoot(), artifact);
  emitWindowsUpdateEvent(sender, opId, "update_download_started", { url: artifact.url, target, timeoutMs });
  let response;
  try {
    response = await fetchWithTimeout(artifact.url, { method: "GET" }, timeoutMs);
  } catch (error) {
    return { ok: false, error: "download_failed", message: String(error && error.message ? error.message : error), url: artifact.url };
  }
  if (!response.ok || !response.body) {
    return { ok: false, error: "download_failed", status: response.status, statusText: response.statusText || "", url: artifact.url };
  }
  const writer = fs.createWriteStream(target);
  let sizeBytes = 0;
  try {
    for await (const chunk of response.body) {
      const buffer = Buffer.from(chunk);
      sizeBytes += buffer.length;
      if (!writer.write(buffer)) await once(writer, "drain");
    }
    writer.end();
    await once(writer, "finish");
  } catch (error) {
    writer.destroy();
    return { ok: false, error: "download_failed", message: String(error && error.message ? error.message : error), target };
  }
  emitWindowsUpdateEvent(sender, opId, "update_download_finished", { target, sizeBytes });
  const validation = validateDownloadedInstaller(target, artifact);
  emitWindowsUpdateEvent(sender, opId, validation.ok ? "update_hash_verified" : validation.error || "hash_mismatch", validation);
  if (!validation.ok) return validation;
  return { ok: true, path: target, sizeBytes: validation.sizeBytes, sha256: validation.sha256 };
}

async function checkAndStageWindowsSelfUpdate(sender, opId, payload = {}) {
  if (process.platform !== "win32" && !payload.allowNonWindowsTest) {
    return { ok: false, error: "windows_native_shell_required" };
  }
  const current = currentWindowsBuildInfo();
  const serverUrl = current.productionTarget;
  const feedUrl = feedUrlFor(serverUrl);
  const cacheBypass = payload.cacheBypass !== false && payload.bypassCache !== false;
  const fetchUrl = cacheBypass ? `${feedUrl}${feedUrl.includes("?") ? "&" : "?"}_=${Date.now()}` : feedUrl;
  emitWindowsUpdateEvent(sender, opId, "update_check_started", {
    feedUrl,
    fetchUrl,
    cacheBypass,
    currentBuild: current.buildId,
    comparisonMode: "buildId",
  });
  let feed;
  try {
    feed = await fetchJsonWithTimeout(fetchUrl, Number(payload.feedTimeoutMs || payload.feed_timeout_ms || 10000));
  } catch (error) {
    return { ok: false, error: "download_failed", phase: "feed", feedUrl, fetchUrl, cacheBypass, message: String(error && error.message ? error.message : error), current };
  }
  const fetched = windowsArtifactFromFeed(feed);
  const validation = validateReleaseArtifact(feed, {
    serverUrl,
    currentBuildId: current.buildId,
    productionTarget: serverUrl,
  });
  if (!validation.ok) {
    emitWindowsUpdateEvent(sender, opId, validation.error || "update_metadata_rejected", { ok: false, feedUrl, fetchUrl, cacheBypass, comparisonMode: "buildId", currentBuild: current.buildId, fetchedBuildId: fetched.buildId || "", fetchedSha256: fetched.sha256 || "", ...validation });
    return { ok: false, phase: "metadata", feedUrl, fetchUrl, cacheBypass, comparisonMode: "buildId", current, ...validation };
  }
  const latest = validation.artifact;
  if (!validation.updateAvailable) {
    emitWindowsUpdateEvent(sender, opId, validation.reason === "older_build_ignored" ? "older_build_ignored" : "same_build_noop", { feedUrl, fetchUrl, cacheBypass, comparisonMode: "buildId", currentBuild: current.buildId, latestBuild: latest.buildId, fetchedSha256: latest.sha256 });
    return { ok: true, updateAvailable: false, reason: validation.reason, feedUrl, fetchUrl, cacheBypass, comparisonMode: "buildId", current, latest };
  }
  emitWindowsUpdateEvent(sender, opId, "update_available", {
    feedUrl,
    fetchUrl,
    cacheBypass,
    comparisonMode: "buildId",
    currentBuild: current.buildId,
    latestBuild: latest.buildId,
    version: latest.version || "",
    sha256: latest.sha256,
    sizeBytes: latest.sizeBytes,
  });
  const downloaded = await downloadWindowsInstallerArtifact(sender, opId, latest, payload);
  if (!downloaded.ok) return { ok: false, phase: "download", current, latest, ...downloaded, manualInstallerUrl: latest.url };
  const staged = { ...downloaded, artifact: latest, stagedAt: new Date().toISOString() };
  activeWindowsSelfUpdate = { opId, current, latest, staged };
  emitWindowsUpdateEvent(sender, opId, "update_ready_for_install", {
    currentBuild: current.buildId,
    latestBuild: latest.buildId,
    installerPath: staged.path,
    sha256: staged.sha256,
  });
  return { ok: true, updateAvailable: true, approvalRequired: true, feedUrl, fetchUrl, cacheBypass, comparisonMode: "buildId", current, latest, staged };
}

async function promptAndLaunchWindowsInstaller(sender, opId, stagedUpdate) {
  if (process.platform !== "win32") return { ok: false, error: "windows_native_shell_required" };
  if (activeNativeCommandCount > 0) return { ok: false, error: "native_command_in_progress" };
  const win = currentNativeWindow();
  const staged = stagedUpdate?.staged || stagedUpdate;
  const latest = stagedUpdate?.latest || staged?.artifact || {};
  const current = stagedUpdate?.current || currentWindowsBuildInfo();
  if (!staged?.path) return { ok: false, error: "update_not_staged" };
  const validation = validateDownloadedInstaller(staged.path, latest);
  if (!validation.ok) return { ok: false, ...validation, manualInstallerPath: staged.path || "" };
  const { dialog } = require("electron");
  const message = [
    "WASM Agent update available",
    `Current build: ${current.buildId || "unknown"}`,
    `New build: ${latest.buildId || "unknown"}`,
    `SHA-256: ${latest.sha256 || validation.sha256}`,
  ].join("\n");
  const response = await dialog.showMessageBox(win || undefined, {
    type: "info",
    title: "WASM Agent Update",
    message: "WASM Agent update available",
    detail: message,
    buttons: ["Install Update", "Later", "View Details"],
    defaultId: 0,
    cancelId: 1,
    noLink: true,
  });
  if (response.response === 2) {
    await shell.showItemInFolder(staged.path);
    return { ok: true, approvalRequired: true, userDeferred: true, detailsOpened: true, manualInstallerPath: staged.path };
  }
  if (response.response !== 0) return { ok: true, approvalRequired: true, userDeferred: true, manualInstallerPath: staged.path };
  emitWindowsUpdateEvent(sender, opId, "user_approved_install", { installerPath: staged.path });
  emitWindowsUpdateEvent(sender, opId, "install_started", { installerPath: staged.path, mode: "guided-installer" });
  try {
    spawn(staged.path, [], { detached: true, stdio: "ignore", windowsHide: false }).unref();
  } catch (error) {
    return { ok: false, error: "installer_failed", message: String(error && error.message ? error.message : error), manualInstallerPath: staged.path };
  }
  emitWindowsUpdateEvent(sender, opId, "app_restarting", { installerPath: staged.path });
  setTimeout(() => app.quit(), 500).unref();
  return { ok: true, installStarted: true, restarting: true, expectedNewBuildId: latest.buildId, manualInstallerPath: staged.path };
}

async function runWindowsSelfUpdate(sender, opId, payload = {}) {
  if (process.platform !== "win32" && !payload.allowNonWindowsTest) {
    return { ok: false, error: "windows_native_shell_required" };
  }
  const staged = await checkAndStageWindowsSelfUpdate(sender, opId, payload);
  if (!staged.ok || !staged.updateAvailable) return staged;
  if (!payload.applyApproved) return staged;
  return promptAndLaunchWindowsInstaller(sender, opId, staged);
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

function userHotOperationsRoot() {
  const appData = process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming");
  return path.join(appData, "WASM-Agent", "bridge-ops");
}

function localHotOperationOverrideRoot() {
  const explicit = String(process.env.WASM_AGENT_HOT_OPS_OVERRIDE_DIR || "").trim();
  if (explicit) return path.resolve(explicit);
  return path.join(os.homedir(), ".wasm-agent", "hot-ops");
}

function localHotOperationOverrideEnabled() {
  const value = String(
    process.env.WASM_AGENT_ENABLE_HOT_OP_OVERRIDES
    || process.env.WASM_AGENT_ENABLE_LOCAL_HOT_OPS
    || "",
  ).trim().toLowerCase();
  return ["1", "true", "yes", "on", "dev"].includes(value);
}

function bundledHotOperationsRoot() {
  const candidates = [
    resourcePath("bridge-ops"),
    path.resolve(__dirname, "..", "ops"),
    path.resolve(__dirname, "..", "..", "ops"),
  ];
  return candidates.find((candidate) => candidate && fs.existsSync(candidate)) || candidates[0];
}

function userDownloadedRuntimeRoot() {
  const appData = process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming");
  return path.join(appData, "WASM-Agent", "runtime");
}

function downloadedRuntimeActiveRoot() {
  return path.join(userDownloadedRuntimeRoot(), "active");
}

function downloadedRuntimeLastKnownGoodRoot() {
  return path.join(userDownloadedRuntimeRoot(), "last-known-good");
}

function downloadedRuntimeStagingRoot(bundleId = "") {
  const safeBundleId = String(bundleId || "runtime").replace(/[^A-Za-z0-9_.-]+/g, "_").slice(0, 100) || "runtime";
  return path.join(userDownloadedRuntimeRoot(), "staging", safeBundleId);
}

function downloadedRuntimeMetadataPath(root = downloadedRuntimeActiveRoot()) {
  return path.join(root, ".runtime-cache.json");
}

function removeDirSafe(dir) {
  try {
    fs.rmSync(dir, { recursive: true, force: true });
  } catch {
    // A stale cache directory must not crash the native shell.
  }
}

function normalizeDownloadedRuntimeTargetPath(value = "") {
  const text = String(value || "").replace(/\\/g, "/").trim();
  if (!text || path.isAbsolute(text) || text.includes("\0")) return "";
  const parts = text.split("/").filter(Boolean);
  if (!parts.length || parts.some((part) => part === "." || part === "..")) return "";
  const ext = path.extname(parts[parts.length - 1] || "").toLowerCase();
  if (![".html", ".css", ".js", ".json", ".webmanifest", ".txt", ".md"].includes(ext)) return "";
  return parts.join("/");
}

function releaseUrlAllowedForDownloadedRuntime(value = "", serverUrl = selectedBackendOrigin || DEFAULT_SERVER_URL) {
  const text = String(value || "").trim();
  if (!text) return { ok: false, error: "missing_url" };
  try {
    const base = new URL(serverUrl || DEFAULT_SERVER_URL);
    const url = new URL(text, base);
    if (url.origin !== base.origin) return { ok: false, error: "unallowlisted_origin", url: url.toString() };
    if (!url.pathname.startsWith("/native/releases/runtime/")) return { ok: false, error: "unallowlisted_url_path", url: url.toString() };
    return { ok: true, url: url.toString(), pathname: url.pathname };
  } catch (error) {
    return { ok: false, error: "invalid_url", message: String(error && error.message ? error.message : error) };
  }
}

function downloadedRuntimeBundlesFromFeed(feed = {}) {
  const runtime = feed?.artifacts?.runtime || feed?.artifacts?.downloadedRuntime || feed?.downloadedRuntime || {};
  const bundles = [];
  const visit = (value) => {
    if (!value || typeof value !== "object") return;
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }
    if (Array.isArray(value.files) && (value.bundleId || value.runtimeId || value.id || value.kind === "native-runtime-bundle")) {
      bundles.push(value);
      return;
    }
    for (const child of Object.values(value)) visit(child);
  };
  visit(runtime);
  return bundles;
}

function downloadedRuntimeBundleFeedMetadata(bundle = {}) {
  const files = Array.isArray(bundle.files) ? bundle.files : [];
  const fileShaList = files.map((file) => `${file.targetPath || file.target_path || ""}:${String(file.sha256 || "").toLowerCase()}`).sort().join("|");
  const bundleSha = String(bundle.bundleSha || bundle.bundle_sha || bundle.sha256 || crypto.createHash("sha256").update(fileShaList).digest("hex")).trim().toLowerCase();
  const feedBundleId = String(bundle.bundleId || bundle.runtimeId || bundle.id || (bundleSha ? `runtime-${bundleSha.slice(0, 16)}` : "")).trim();
  const manifest = files.find((file) => String(file.role || "").toLowerCase() === "manifest" || String(file.targetPath || file.target_path || "").endsWith(".json")) || {};
  return {
    feedBundleId,
    bundleSha,
    manifestSha: String(manifest.sha256 || "").trim().toLowerCase(),
    cachePath: downloadedRuntimeActiveRoot(),
    files,
  };
}

function downloadedRuntimeCachedMetadata(root = downloadedRuntimeActiveRoot()) {
  const meta = readJsonFile(downloadedRuntimeMetadataPath(root), {});
  return {
    bundleId: String(meta.bundleId || meta.runtimeId || "").trim(),
    runtimeId: String(meta.runtimeId || meta.bundleId || "").trim(),
    bundleSha: String(meta.bundleSha || meta.sha256 || "").trim().toLowerCase(),
    manifestSha: String(meta.manifestSha || "").trim().toLowerCase(),
    activatedAt: String(meta.activatedAt || ""),
    cachePath: root,
    files: Array.isArray(meta.files) ? meta.files : [],
  };
}

function downloadedRuntimeFileMismatch(files = [], root = downloadedRuntimeActiveRoot()) {
  for (const file of files) {
    const relPath = normalizeDownloadedRuntimeTargetPath(file.targetPath || file.target_path || file.installPath || file.install_path || file.target || "");
    if (!relPath) return { ok: false, reason: "runtime_invalid_target_path", path: String(file.targetPath || file.target_path || "") };
    const target = path.resolve(path.join(root, relPath));
    const expectedSha = String(file.sha256 || "").trim().toLowerCase();
    if (!target.startsWith(`${path.resolve(root)}${path.sep}`)) return { ok: false, reason: "runtime_invalid_target_path", path: relPath };
    if (!fileExists(target)) return { ok: false, reason: "runtime_file_missing", path: relPath };
    const actualSha = sha256File(target).toLowerCase();
    if (expectedSha && actualSha !== expectedSha) {
      return { ok: false, reason: "runtime_sha_mismatch", path: relPath, expectedSha256: expectedSha, sha256: actualSha };
    }
  }
  return { ok: true, reason: "" };
}

function downloadedRuntimeMetadataDiffers(feedMeta, cachedMeta) {
  return Boolean(
    (feedMeta.feedBundleId || "") !== (cachedMeta.bundleId || "")
    || (feedMeta.bundleSha || "") !== (cachedMeta.bundleSha || "")
  );
}

async function fetchDownloadedRuntimeBundleFile(file, serverUrl, stageRoot) {
  const relPath = normalizeDownloadedRuntimeTargetPath(file.targetPath || file.target_path || file.installPath || file.install_path || file.target || "");
  const urlCheck = releaseUrlAllowedForDownloadedRuntime(file.url || "", serverUrl);
  if (!relPath) return { ok: false, error: "invalid_runtime_path", file };
  if (!urlCheck.ok) return urlCheck;
  const expectedSha = String(file.sha256 || "").trim().toLowerCase();
  if (!expectedSha) return { ok: false, error: "missing_sha256", path: relPath };
  const res = await fetchWithTimeout(urlCheck.url, {}, 15000);
  if (!res.ok) return { ok: false, error: "download_failed", status: res.status, url: urlCheck.url };
  const buffer = Buffer.from(await res.arrayBuffer());
  if (buffer.length > 8 * 1024 * 1024) return { ok: false, error: "runtime_file_too_large", path: relPath, sizeBytes: buffer.length };
  const actualSha = crypto.createHash("sha256").update(buffer).digest("hex");
  if (actualSha !== expectedSha) return { ok: false, error: "sha256_mismatch", path: relPath, expectedSha256: expectedSha, sha256: actualSha };
  const root = path.resolve(stageRoot);
  const target = path.resolve(path.join(root, relPath));
  if (!target.startsWith(`${root}${path.sep}`)) return { ok: false, error: "invalid_runtime_target", path: relPath };
  return { ok: true, role: String(file.role || ""), path: relPath, target, sha256: actualSha, sizeBytes: buffer.length, buffer };
}

function writeDownloadedRuntimeMetadata(root, bundle, feedMeta, fileResults = []) {
  const metadata = {
    schema: "hermes.wasm_agent.downloaded_runtime_cache.v1",
    runtimeId: feedMeta.feedBundleId,
    bundleId: feedMeta.feedBundleId,
    bundleSha: feedMeta.bundleSha,
    sha256: feedMeta.bundleSha,
    manifestSha: feedMeta.manifestSha,
    updateMode: String(bundle.updateMode || "downloaded-runtime-atomic"),
    activatedAt: new Date().toISOString(),
    source: "release-feed",
    files: fileResults.map((file) => ({
      role: file.role || "",
      path: file.path || "",
      sha256: file.sha256 || "",
      sizeBytes: file.sizeBytes || 0,
    })),
  };
  fs.mkdirSync(root, { recursive: true });
  fs.writeFileSync(downloadedRuntimeMetadataPath(root), `${JSON.stringify(metadata, null, 2)}\n`);
  return metadata;
}

function activateDownloadedRuntimeBundle(bundle, stageRoot, feedMeta, fileResults = []) {
  const activeRoot = downloadedRuntimeActiveRoot();
  const lkgRoot = downloadedRuntimeLastKnownGoodRoot();
  const failedRoot = path.join(userDownloadedRuntimeRoot(), "failed-active");
  fs.mkdirSync(userDownloadedRuntimeRoot(), { recursive: true });
  removeDirSafe(lkgRoot);
  removeDirSafe(failedRoot);
  try {
    if (fs.existsSync(activeRoot)) fs.renameSync(activeRoot, lkgRoot);
    fs.renameSync(stageRoot, activeRoot);
    const metadata = writeDownloadedRuntimeMetadata(activeRoot, bundle, feedMeta, fileResults);
    return { ok: true, activeRoot, lastKnownGoodRoot: fs.existsSync(lkgRoot) ? lkgRoot : "", metadata };
  } catch (error) {
    try {
      if (fs.existsSync(activeRoot)) fs.renameSync(activeRoot, failedRoot);
      if (fs.existsSync(lkgRoot)) fs.renameSync(lkgRoot, activeRoot);
    } catch {
      // Preserve the original activation error below.
    }
    return { ok: false, error: "runtime_activation_failed", message: String(error && error.message ? error.message : error), activeRoot, lastKnownGoodRoot: fs.existsSync(activeRoot) ? activeRoot : "" };
  }
}

async function syncDownloadedRuntimeFromFeed(options = {}) {
  const now = new Date().toISOString();
  const serverUrl = selectedBackendOrigin || DEFAULT_SERVER_URL;
  const feedUrl = new URL("/native/releases/latest.json", serverUrl).toString();
  lastDownloadedRuntimeSync = { ...lastDownloadedRuntimeSync, attemptedAt: now, feedUrl, status: "syncing" };
  let feed;
  try {
    feed = await fetchJsonWithTimeout(`${feedUrl}${feedUrl.includes("?") ? "&" : "?"}_=${Date.now()}`, Number(options.feedTimeoutMs || 10000));
  } catch (error) {
    const cached = downloadedRuntimeCachedMetadata();
    lastDownloadedRuntimeSync = { ok: false, changed: false, attemptedAt: now, feedUrl, syncedAt: "", error: String(error && error.message ? error.message : error), status: "runtime_feed_fetch_failed", feedBundleId: "", cachedBundleId: cached.bundleId, activeRuntimeId: cached.bundleId, activeRuntimeSha: cached.bundleSha, activeRuntimePath: cached.cachePath, staleReason: "runtime_feed_fetch_failed", fallbackReason: cached.bundleId ? "using_cached_active_runtime" : "", files: [] };
    return lastDownloadedRuntimeSync;
  }
  const bundles = downloadedRuntimeBundlesFromFeed(feed);
  const bundle = bundles.find((item) => String(item.kind || "").includes("runtime")) || bundles[0];
  if (!bundle) {
    const cached = downloadedRuntimeCachedMetadata();
    lastDownloadedRuntimeSync = { ok: false, changed: false, attemptedAt: now, feedUrl, syncedAt: "", error: "runtime_bundle_missing", status: "runtime_bundle_missing", feedBundleId: "", cachedBundleId: cached.bundleId, activeRuntimeId: cached.bundleId, activeRuntimeSha: cached.bundleSha, activeRuntimePath: cached.cachePath, staleReason: "runtime_bundle_missing", fallbackReason: cached.bundleId ? "using_cached_active_runtime" : "", files: [] };
    return lastDownloadedRuntimeSync;
  }
  const feedMeta = downloadedRuntimeBundleFeedMetadata(bundle);
  const cached = downloadedRuntimeCachedMetadata();
  const mismatch = downloadedRuntimeFileMismatch(feedMeta.files, downloadedRuntimeActiveRoot());
  const changed = options.force === true || options.forceSync === true || downloadedRuntimeMetadataDiffers(feedMeta, cached) || !mismatch.ok;
  if (!changed) {
    lastDownloadedRuntimeSync = { ok: true, changed: false, attemptedAt: now, feedUrl, syncedAt: new Date().toISOString(), error: "", status: "current", feedBundleId: feedMeta.feedBundleId, cachedBundleId: cached.bundleId, activeRuntimeId: cached.bundleId, activeRuntimeSha: cached.bundleSha, activeRuntimePath: cached.cachePath, staleReason: "", fallbackReason: "", files: feedMeta.files.map((file) => ({ path: normalizeDownloadedRuntimeTargetPath(file.targetPath || file.target_path || ""), sha256: String(file.sha256 || "").trim().toLowerCase(), skipped: true })) };
    return lastDownloadedRuntimeSync;
  }
  const stageRoot = downloadedRuntimeStagingRoot(feedMeta.feedBundleId);
  removeDirSafe(stageRoot);
  const staged = [];
  const fileResults = [];
  for (const file of feedMeta.files) {
    const fileResult = await fetchDownloadedRuntimeBundleFile(file, serverUrl, stageRoot);
    fileResults.push({ ...fileResult, buffer: undefined });
    if (!fileResult.ok) {
      removeDirSafe(stageRoot);
      lastDownloadedRuntimeSync = { ok: false, changed: false, attemptedAt: now, feedUrl, syncedAt: "", error: fileResult.error || "runtime_download_failed", status: fileResult.error || "runtime_download_failed", feedBundleId: feedMeta.feedBundleId, cachedBundleId: cached.bundleId, activeRuntimeId: cached.bundleId, activeRuntimeSha: cached.bundleSha, activeRuntimePath: cached.cachePath, staleReason: fileResult.error || "runtime_download_failed", fallbackReason: cached.bundleId ? "last-known-good-preserved" : "", files: fileResults };
      return lastDownloadedRuntimeSync;
    }
    staged.push(fileResult);
  }
  for (const fileResult of staged) {
    fs.mkdirSync(path.dirname(fileResult.target), { recursive: true });
    fs.writeFileSync(fileResult.target, fileResult.buffer);
  }
  const activation = activateDownloadedRuntimeBundle(bundle, stageRoot, feedMeta, staged);
  if (!activation.ok) {
    removeDirSafe(stageRoot);
    const active = downloadedRuntimeCachedMetadata();
    lastDownloadedRuntimeSync = { ok: false, changed: false, attemptedAt: now, feedUrl, syncedAt: "", error: activation.error, status: activation.error, feedBundleId: feedMeta.feedBundleId, cachedBundleId: cached.bundleId, activeRuntimeId: active.bundleId, activeRuntimeSha: active.bundleSha, activeRuntimePath: active.cachePath, staleReason: activation.error, fallbackReason: active.bundleId ? "last-known-good-restored" : "", files: fileResults };
    return lastDownloadedRuntimeSync;
  }
  lastDownloadedRuntimeSync = { ok: true, changed: true, attemptedAt: now, feedUrl, syncedAt: new Date().toISOString(), error: "", status: "activated", feedBundleId: feedMeta.feedBundleId, cachedBundleId: activation.metadata.bundleId, activeRuntimeId: activation.metadata.bundleId, activeRuntimeSha: activation.metadata.bundleSha, activeRuntimePath: activation.activeRoot, staleReason: "", fallbackReason: activation.lastKnownGoodRoot ? "previous-active-preserved-as-last-known-good" : "", files: fileResults };
  return lastDownloadedRuntimeSync;
}

async function ensureDownloadedRuntimeFromFeed(options = {}) {
  const active = downloadedRuntimeCachedMetadata();
  const force = options.force === true || options.forceSync === true;
  if (active.bundleId && !force) return lastDownloadedRuntimeSync;
  if (!downloadedRuntimeSyncPromise) {
    downloadedRuntimeSyncPromise = syncDownloadedRuntimeFromFeed(options).finally(() => {
      downloadedRuntimeSyncPromise = null;
    });
  }
  return downloadedRuntimeSyncPromise;
}

function rollbackDownloadedRuntimeToLastKnownGood() {
  const activeRoot = downloadedRuntimeActiveRoot();
  const lkgRoot = downloadedRuntimeLastKnownGoodRoot();
  if (!fs.existsSync(lkgRoot)) {
    return { ok: false, operation: "rollback_downloaded_runtime", error: "last_known_good_missing", downloadedRuntime: downloadedRuntimeSummary() };
  }
  const failedRoot = path.join(userDownloadedRuntimeRoot(), `rolled-back-${timestampForFilename()}`);
  try {
    if (fs.existsSync(activeRoot)) fs.renameSync(activeRoot, failedRoot);
    fs.renameSync(lkgRoot, activeRoot);
    const active = downloadedRuntimeCachedMetadata();
    lastDownloadedRuntimeSync = { ...lastDownloadedRuntimeSync, ok: true, changed: true, status: "rolled_back_to_last_known_good", activeRuntimeId: active.bundleId, activeRuntimeSha: active.bundleSha, activeRuntimePath: active.cachePath, staleReason: "", fallbackReason: `previous_active_moved:${failedRoot}` };
    return { ok: true, operation: "rollback_downloaded_runtime", rolledBack: true, failedRoot, downloadedRuntime: downloadedRuntimeSummary() };
  } catch (error) {
    return { ok: false, operation: "rollback_downloaded_runtime", error: "runtime_rollback_failed", message: String(error && error.message ? error.message : error), downloadedRuntime: downloadedRuntimeSummary() };
  }
}

function downloadedRuntimeSummary() {
  const active = downloadedRuntimeCachedMetadata();
  const lkg = downloadedRuntimeCachedMetadata(downloadedRuntimeLastKnownGoodRoot());
  const staleReason = lastDownloadedRuntimeSync.staleReason
    || (lastDownloadedRuntimeSync.feedBundleId && active.bundleId && lastDownloadedRuntimeSync.feedBundleId !== active.bundleId ? "runtime_bundle_stale" : "");
  return {
    supported: true,
    protocol: DOWNLOADED_RUNTIME_PROTOCOL_VERSION,
    runtimeLoaderProtocolVersion: DOWNLOADED_RUNTIME_PROTOCOL_VERSION,
    root: userDownloadedRuntimeRoot(),
    activeRoot: downloadedRuntimeActiveRoot(),
    lastKnownGoodRoot: downloadedRuntimeLastKnownGoodRoot(),
    activeRuntimeId: active.bundleId,
    activeRuntimeSha: active.bundleSha,
    activeDownloadedRuntimeId: active.bundleId,
    activeDownloadedRuntimeSha: active.bundleSha,
    activeRuntimePath: active.cachePath,
    activeManifestSha: active.manifestSha,
    activeRuntimeActivatedAt: active.activatedAt,
    lastKnownGoodRuntimeId: lkg.bundleId,
    lastKnownGoodRuntimeSha: lkg.bundleSha,
    syncStatus: lastDownloadedRuntimeSync.status || (active.bundleId ? "cached" : "not_synced"),
    lastSync: lastDownloadedRuntimeSync,
    stale: Boolean(staleReason),
    staleReason,
    mismatchReason: staleReason,
  };
}

function hotOperationRoots() {
  const roots = [];
  const devOverride = String(process.env.WASM_AGENT_BRIDGE_OPS_DIR || "").trim();
  const devReload = String(process.env.WASM_AGENT_HOT_OPS_DEV_RELOAD || "").trim() === "1";
  if (localHotOperationOverrideEnabled()) {
    const overrideRoot = devOverride ? path.resolve(devOverride) : path.resolve(localHotOperationOverrideRoot());
    roots.push({ kind: "local_override", root: overrideRoot, reload: true, active: true });
  }
  roots.push({ kind: "downloaded", root: path.resolve(userHotOperationsRoot()), reload: true });
  roots.push({ kind: "bundled", root: path.resolve(bundledHotOperationsRoot()), reload: devReload });
  return roots.map((item, index) => ({
    ...item,
    active: item.active === true || (!localHotOperationOverrideEnabled() && index === 0),
    exists: fs.existsSync(item.root),
  }));
}

function hotOperationsDevReloadEnabled() {
  return String(process.env.WASM_AGENT_HOT_OPS_DEV_RELOAD || "").trim() === "1";
}

function hotOperationsDisabled() {
  return String(process.env.WASM_AGENT_DISABLE_HOT_OPS || "").trim() === "1";
}

function hotOperationsRequireSha() {
  return String(process.env.WASM_AGENT_HOT_OPS_REQUIRE_SHA || "").trim() === "1";
}

function downloadedHotOperationManifestTrusted(manifest, entrySha256) {
  const trusted = manifest && manifest.trusted === true;
  const bundleId = String(manifest?.bundleId || manifest?.bundle_id || "").trim();
  const trustedSha256 = String(manifest?.trustedSha256 || manifest?.trusted_sha256 || manifest?.sha256 || "").trim().toLowerCase();
  return trusted || (Boolean(bundleId) && Boolean(trustedSha256) && trustedSha256 === String(entrySha256 || "").toLowerCase());
}

function releaseUrlAllowedForHotOperationBundle(value = "", serverUrl = selectedBackendOrigin || DEFAULT_SERVER_URL) {
  const text = String(value || "").trim();
  if (!text) return { ok: false, error: "missing_url" };
  try {
    const base = new URL(serverUrl || DEFAULT_SERVER_URL);
    const url = new URL(text, base);
    if (url.origin !== base.origin) return { ok: false, error: "unallowlisted_origin", url: url.toString() };
    if (!url.pathname.startsWith("/native/releases/hot-ops/")) return { ok: false, error: "unallowlisted_url_path", url: url.toString() };
    return { ok: true, url: url.toString(), pathname: url.pathname };
  } catch (error) {
    return { ok: false, error: "invalid_url", message: String(error && error.message ? error.message : error) };
  }
}

function normalizeHotOperationBundleTargetPath(value = "") {
  const text = String(value || "").replace(/\\/g, "/").trim();
  if (!text || path.isAbsolute(text) || text.includes("\0")) return "";
  const parts = text.split("/").filter(Boolean);
  if (!parts.length || parts.some((part) => part === "." || part === "..")) return "";
  const filename = parts[parts.length - 1] || "";
  if (path.extname(filename).toLowerCase() === ".js" || filename.endsWith(HOT_OPERATION_MANIFEST_SUFFIX)) {
    return parts.join("/");
  }
  return "";
}

function hotOperationBundlesFromFeed(feed = {}) {
  const hotOps = feed?.artifacts?.hotOps || feed?.artifacts?.hot_ops || feed?.hotOps || {};
  const bundles = [];
  const visit = (value) => {
    if (!value || typeof value !== "object") return;
    if (Array.isArray(value)) {
      value.forEach(visit);
      return;
    }
    if (Array.isArray(value.files) && (value.bundleId || value.id || value.operationName)) {
      bundles.push(value);
      return;
    }
    for (const child of Object.values(value)) visit(child);
  };
  visit(hotOps);
  return bundles;
}

async function fetchHotOperationBundleFile(file, serverUrl) {
  const relPath = normalizeHotOperationBundleTargetPath(file.targetPath || file.target_path || file.installPath || file.install_path || file.target || "");
  const urlCheck = releaseUrlAllowedForHotOperationBundle(file.url || "", serverUrl);
  if (!relPath) return { ok: false, error: "invalid_hot_op_path", file };
  if (!urlCheck.ok) return urlCheck;
  const expectedSha = String(file.sha256 || "").trim().toLowerCase();
  if (!expectedSha) return { ok: false, error: "missing_sha256", path: relPath };
  const res = await fetchWithTimeout(urlCheck.url, {}, 15000);
  if (!res.ok) return { ok: false, error: "download_failed", status: res.status, url: urlCheck.url };
  const buffer = Buffer.from(await res.arrayBuffer());
  const actualSha = crypto.createHash("sha256").update(buffer).digest("hex");
  if (actualSha !== expectedSha) return { ok: false, error: "sha256_mismatch", path: relPath, expectedSha256: expectedSha, sha256: actualSha };
  const root = path.resolve(userHotOperationsRoot());
  const target = path.resolve(path.join(root, relPath));
  if (!target.startsWith(`${root}${path.sep}`)) return { ok: false, error: "invalid_hot_op_target", path: relPath };
  return { ok: true, role: String(file.role || ""), path: relPath, target, sha256: actualSha, sizeBytes: buffer.length, buffer };
}

function hotOperationBundleCachedMetadata(files = []) {
  const root = path.resolve(userHotOperationsRoot());
  const result = { bundleId: "", moduleSha: "", manifestSha: "", cachePath: "" };
  for (const file of files) {
    const relPath = normalizeHotOperationBundleTargetPath(file.targetPath || file.target_path || file.installPath || file.install_path || file.target || "");
    if (!relPath) continue;
    const target = path.resolve(path.join(root, relPath));
    if (!target.startsWith(`${root}${path.sep}`) || !fileExists(target)) continue;
    const sha = sha256File(target).toLowerCase();
    const role = String(file.role || "").trim().toLowerCase();
    if (role === "module" || target.endsWith(".js")) {
      result.moduleSha = sha;
      result.cachePath = target;
    }
    if (role === "manifest" || target.endsWith(HOT_OPERATION_MANIFEST_SUFFIX)) {
      result.manifestSha = sha;
      const manifest = readJsonFile(target, {});
      result.bundleId = String(manifest.bundleId || manifest.bundle_id || "").trim();
    }
  }
  return result;
}

function hotOperationBundleFeedMetadata(bundle = {}) {
  const result = {
    feedBundleId: String(bundle.bundleId || bundle.id || "").trim(),
    moduleSha: "",
    manifestSha: "",
    cachePath: "",
  };
  const root = path.resolve(userHotOperationsRoot());
  const files = Array.isArray(bundle.files) ? bundle.files : [];
  for (const file of files) {
    const relPath = normalizeHotOperationBundleTargetPath(file.targetPath || file.target_path || file.installPath || file.install_path || file.target || "");
    if (!relPath) continue;
    const sha = String(file.sha256 || "").trim().toLowerCase();
    const role = String(file.role || "").trim().toLowerCase();
    if (role === "module" || relPath.endsWith(".js")) {
      result.moduleSha = sha;
      result.cachePath = path.resolve(path.join(root, relPath));
    }
    if (role === "manifest" || relPath.endsWith(HOT_OPERATION_MANIFEST_SUFFIX)) {
      result.manifestSha = sha;
    }
  }
  return result;
}

function hotOperationBundleMetadataDiffers(feedMeta, cachedMeta) {
  return Boolean(
    (feedMeta.feedBundleId || "") !== (cachedMeta.bundleId || "")
    || (feedMeta.moduleSha || "") !== (cachedMeta.moduleSha || "")
    || (feedMeta.manifestSha || "") !== (cachedMeta.manifestSha || "")
  );
}

async function syncDownloadedHotOperationsFromFeed(options = {}) {
  const now = new Date().toISOString();
  const serverUrl = selectedBackendOrigin || DEFAULT_SERVER_URL;
  const feedUrl = new URL("/native/releases/latest.json", serverUrl).toString();
  lastHotOperationBundleSync = { ...lastHotOperationBundleSync, attemptedAt: now, feedUrl };
  let feed;
  try {
    feed = await fetchJsonWithTimeout(`${feedUrl}${feedUrl.includes("?") ? "&" : "?"}_=${Date.now()}`, Number(options.feedTimeoutMs || 10000));
  } catch (error) {
    lastHotOperationBundleSync = { ok: false, changed: false, attemptedAt: now, feedUrl, syncedAt: "", error: String(error && error.message ? error.message : error), feedBundleId: "", cachedBundleId: "", moduleSha: "", manifestSha: "", cachePath: "", bundles: [] };
    return lastHotOperationBundleSync;
  }
  const bundles = hotOperationBundlesFromFeed(feed);
  const synced = [];
  let anyChanged = false;
  let primarySync = { feedBundleId: "", cachedBundleId: "", moduleSha: "", manifestSha: "", cachePath: "" };
  for (const bundle of bundles) {
    const files = Array.isArray(bundle.files) ? bundle.files : [];
    const feedMeta = hotOperationBundleFeedMetadata(bundle);
    const beforeMeta = hotOperationBundleCachedMetadata(files);
    const changed = hotOperationBundleMetadataDiffers(feedMeta, beforeMeta);
    const result = {
      bundleId: feedMeta.feedBundleId,
      cachedBundleId: beforeMeta.bundleId,
      operationName: String(bundle.operationName || ""),
      changed,
      moduleSha: feedMeta.moduleSha,
      manifestSha: feedMeta.manifestSha,
      cachePath: feedMeta.cachePath,
      files: [],
    };
    if (changed) {
      const staged = [];
      for (const file of files) {
        const fileResult = await fetchHotOperationBundleFile(file, serverUrl);
        result.files.push({ ...fileResult, buffer: undefined });
        if (!fileResult.ok) {
          lastHotOperationBundleSync = { ok: false, changed: anyChanged, attemptedAt: now, feedUrl, syncedAt: "", error: fileResult.error || "hot_op_download_failed", feedBundleId: feedMeta.feedBundleId, cachedBundleId: beforeMeta.bundleId, moduleSha: feedMeta.moduleSha, manifestSha: feedMeta.manifestSha, cachePath: feedMeta.cachePath, bundles: [result] };
          return lastHotOperationBundleSync;
        }
        staged.push(fileResult);
      }
      for (const fileResult of staged) {
        fs.mkdirSync(path.dirname(fileResult.target), { recursive: true });
        fs.writeFileSync(fileResult.target, fileResult.buffer);
      }
      anyChanged = true;
    } else {
      for (const file of files) {
        const relPath = normalizeHotOperationBundleTargetPath(file.targetPath || file.target_path || file.installPath || file.install_path || file.target || "");
        if (relPath) result.files.push({ ok: true, path: relPath, target: path.resolve(path.join(userHotOperationsRoot(), relPath)), sha256: String(file.sha256 || "").trim().toLowerCase(), skipped: true });
      }
    }
    const afterMeta = hotOperationBundleCachedMetadata(files);
    result.cachedBundleId = afterMeta.bundleId || beforeMeta.bundleId;
    result.cachedModuleSha = afterMeta.moduleSha || beforeMeta.moduleSha;
    result.cachedManifestSha = afterMeta.manifestSha || beforeMeta.manifestSha;
    if (!primarySync.feedBundleId || result.operationName === "run_android_hermes_wake_proof") {
      primarySync = {
        feedBundleId: feedMeta.feedBundleId,
        cachedBundleId: result.cachedBundleId,
        moduleSha: feedMeta.moduleSha,
        manifestSha: feedMeta.manifestSha,
        cachePath: feedMeta.cachePath,
      };
    }
    synced.push(result);
  }
  lastHotOperationBundleSync = { ok: true, changed: anyChanged, attemptedAt: now, feedUrl, syncedAt: new Date().toISOString(), error: "", ...primarySync, bundles: synced };
  return lastHotOperationBundleSync;
}

async function ensureDownloadedHotOperationsFromFeed(options = {}) {
  if (localHotOperationOverrideEnabled()) return lastHotOperationBundleSync;
  const downloadedRoot = userHotOperationsRoot();
  const hasDownloadedOps = fs.existsSync(downloadedRoot) && walkHotOperationManifestFiles(downloadedRoot).length > 0;
  const force = options.force === true || options.forceSync === true;
  if (hasDownloadedOps && !force) return lastHotOperationBundleSync;
  if (!hotOperationBundleSyncPromise) {
    hotOperationBundleSyncPromise = syncDownloadedHotOperationsFromFeed(options).finally(() => {
      hotOperationBundleSyncPromise = null;
    });
  }
  return hotOperationBundleSyncPromise;
}

function verboseBridgeLogsEnabled() {
  return String(process.env.WASM_AGENT_ENABLE_VERBOSE_BRIDGE_LOGS || "").trim() === "1";
}

function activeHotOperationsRoot() {
  const roots = hotOperationRoots();
  return roots.find((item) => item.active && item.exists)
    || roots.find((item) => item.kind === "downloaded" && item.exists)
    || roots.find((item) => item.kind === "bundled")
    || roots[0]
    || { kind: "bundled", root: bundledHotOperationsRoot(), exists: false };
}

function hotOperationsSummary() {
  const active = activeHotOperationsRoot();
  const availableHotOps = scanHotOperationManifests().map((op) => ({
    name: op.name,
    version: op.version,
    entry: op.entry,
    manifest: op.manifest,
    loadedFrom: op.loadedFrom,
    sha256: op.sha256,
    capabilities: op.capabilities,
    requiredNativeCapabilities: op.requiredNativeCapabilities,
    operationId: op.operationId,
    inputsSchema: op.inputsSchema,
    outputsSchema: op.outputsSchema,
    safetyLimits: op.safetyLimits,
    rollback: op.rollback,
    timeoutMs: op.timeoutMs,
  }));
  return {
    shellProtocolVersion: SHELL_PROTOCOL_VERSION,
    supportedHotOpsProtocol: HOT_OPERATION_PROTOCOL_VERSION,
    hotOpsProtocolVersion: HOT_OPERATION_PROTOCOL_VERSION,
    minimumRunnerVersion: MINIMUM_RUNNER_VERSION,
    capabilities: BRIDGE_PROTOCOL_CAPABILITIES.slice(),
    hotOpsMode: active.kind || "bundled",
    hotOpsRoot: active.root || "",
    devReload: active.kind === "local_override" || hotOperationsDevReloadEnabled(),
    overrideEnabled: localHotOperationOverrideEnabled(),
    localOverrideRoot: localHotOperationOverrideRoot(),
    hotOpsDisabled: hotOperationsDisabled(),
    hotOpsRequireSha: hotOperationsRequireSha(),
    downloadedHotOpsSync: lastHotOperationBundleSync,
    downloadedRuntime: downloadedRuntimeSummary(),
    hotOpsRoots: hotOperationRoots().map((item) => ({
      kind: item.kind,
      path: item.root,
      active: item.root === active.root,
      exists: item.exists,
    })),
    availableHotOps,
  };
}

function activeHotOperationBundleStatus() {
  const operations = scanHotOperationManifests();
  const preferred = operations.find((item) => item.loadedFrom === "downloaded" && item.name === "run_android_hermes_wake_proof")
    || operations.find((item) => item.loadedFrom === "downloaded")
    || operations.find((item) => item.name === "run_android_hermes_wake_proof")
    || operations[0]
    || {};
  return {
    activeHotOpBundleId: String(preferred.bundleId || ""),
    activeHotOpSha: String(preferred.sha256 || ""),
    activeHotOpSource: String(preferred.hotOpSource || preferred.loadedFrom || ""),
    activeHotOpOperation: String(preferred.name || ""),
    activeHotOpManifestSha: String(preferred.manifestSha256 || ""),
  };
}

function nativeKernelStatus() {
  const build = currentWindowsBuildInfo();
  const downloadedRuntime = downloadedRuntimeSummary();
  const hotOp = activeHotOperationBundleStatus();
  const unsupportedCapabilities = ALL_NATIVE_KERNEL_CAPABILITIES.filter((capability) => !WINDOWS_NATIVE_KERNEL_CAPABILITIES.includes(capability));
  const staleReason = downloadedRuntime.staleReason || lastHotOperationBundleSync.error || "";
  return {
    schema: "hermes.wasm_agent.native_kernel_status.v1",
    "native.kernel.version": NATIVE_KERNEL_CONTRACT_VERSION,
    nativeKernelVersion: NATIVE_KERNEL_CONTRACT_VERSION,
    kernelContractVersion: NATIVE_KERNEL_CONTRACT_VERSION,
    platform: "windows",
    runtime: "electron",
    installedNativeBuildId: build.buildId,
    nativeBuildId: build.buildId,
    installedNativeVersion: build.version,
    appVersion: app.getVersion(),
    productionTarget: build.productionTarget,
    supportedCapabilities: WINDOWS_NATIVE_KERNEL_CAPABILITIES.slice(),
    missingCapabilities: [],
    unsupportedCapabilities,
    bridgeProtocolCapabilities: BRIDGE_PROTOCOL_CAPABILITIES.slice(),
    downloadedRuntime,
    activeDownloadedRuntimeId: downloadedRuntime.activeRuntimeId,
    activeDownloadedRuntimeSha: downloadedRuntime.activeRuntimeSha,
    activeHotOpBundleId: hotOp.activeHotOpBundleId,
    activeHotOpSha: hotOp.activeHotOpSha,
    activeHotOpSource: hotOp.activeHotOpSource,
    activeHotOpOperation: hotOp.activeHotOpOperation,
    syncStatus: {
      runtime: downloadedRuntime.syncStatus,
      hotOps: lastHotOperationBundleSync.ok ? "current_or_synced" : (lastHotOperationBundleSync.error || "not_attempted"),
    },
    stale: Boolean(staleReason),
    staleReason,
  };
}

function walkHotOperationManifestFiles(root) {
  const files = [];
  const visit = (dir) => {
    let entries = [];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        visit(fullPath);
      } else if (entry.isFile() && entry.name.endsWith(HOT_OPERATION_MANIFEST_SUFFIX)) {
        files.push(fullPath);
      }
    }
  };
  visit(root);
  return files;
}

function normalizeHotOperationManifest(rootInfo, manifestPath) {
  const manifest = readJsonFile(manifestPath, {});
  const name = String(manifest.name || "").trim();
  const entry = normalizeHotOperationModulePath(manifest.entry || "");
  if (!name || !entry) return null;
  const root = path.resolve(rootInfo.root);
  const manifestRelative = path.relative(root, manifestPath).replace(/\\/g, "/");
  const entryRelative = normalizeHotOperationModulePath(path.posix.join(path.posix.dirname(manifestRelative), entry));
  if (!entryRelative) return null;
  const entryPath = path.resolve(root, entryRelative);
  const entryRootRelative = path.relative(root, entryPath);
  if (!entryRootRelative || entryRootRelative.startsWith("..") || path.isAbsolute(entryRootRelative)) return null;
  if (!fs.existsSync(entryPath) || !fs.statSync(entryPath).isFile()) return null;
  const sha256 = sha256File(entryPath).toLowerCase();
  const manifestSha256 = String(manifest.sha256 || manifest.expectedSha256 || manifest.expected_sha256 || "").trim().toLowerCase();
  if (rootInfo.kind === "downloaded" && !downloadedHotOperationManifestTrusted(manifest, sha256)) return null;
  return {
    name,
    version: String(manifest.version || ""),
    entry: entryRelative,
    manifest: manifestRelative,
    loadedFrom: rootInfo.kind,
    hotOpSource: rootInfo.kind,
    root,
    path: entryPath,
    hotOpPath: entryPath,
    bundleId: String(manifest.bundleId || manifest.bundle_id || ""),
    modulePath: entryRelative,
    manifestPath,
    sha256,
    manifestSha256,
    capabilities: Array.isArray(manifest.capabilities) ? manifest.capabilities.map(String) : [],
    requiredNativeCapabilities: Array.isArray(manifest.requiredNativeCapabilities || manifest.required_native_capabilities)
      ? (manifest.requiredNativeCapabilities || manifest.required_native_capabilities).map(String)
      : [],
    operationId: String(manifest.operationId || manifest.operation_id || name),
    inputsSchema: manifest.inputsSchema || manifest.inputs_schema || {},
    outputsSchema: manifest.outputsSchema || manifest.outputs_schema || {},
    safetyLimits: manifest.safetyLimits || manifest.safety_limits || {},
    rollback: manifest.rollback || {},
    timeoutMs: Number(manifest.timeoutMs || manifest.timeout_ms || 0) || HOT_OPERATION_DEFAULT_TIMEOUT_MS,
    reload: rootInfo.reload || hotOperationsDevReloadEnabled(),
  };
}

function scanHotOperationManifests() {
  const seen = new Set();
  const operations = [];
  for (const rootInfo of hotOperationRoots()) {
    if (!rootInfo.exists) continue;
    for (const manifestPath of walkHotOperationManifestFiles(rootInfo.root)) {
      const op = normalizeHotOperationManifest(rootInfo, manifestPath);
      if (!op || seen.has(op.name)) continue;
      seen.add(op.name);
      operations.push(op);
    }
  }
  return operations;
}

function bundledHotOperationSha(operationName = "") {
  const name = String(operationName || "").trim();
  if (!name) return "";
  const bundledRoot = hotOperationRoots().find((item) => item.kind === "bundled");
  if (!bundledRoot || !bundledRoot.exists) return "";
  for (const manifestPath of walkHotOperationManifestFiles(bundledRoot.root)) {
    const op = normalizeHotOperationManifest(bundledRoot, manifestPath);
    if (op && op.name === name) return op.sha256 || "";
  }
  return "";
}

function listHotOperations() {
  const summary = hotOperationsSummary();
  return {
    ok: true,
    ...summary,
    logsTail: recentBridgeLogsTail(),
  };
}

function getBridgeStatus() {
  const hotOps = hotOperationsSummary();
  const kernel = nativeKernelStatus();
  return {
    ok: true,
    stable: true,
    operation: "get_bridge_status",
    source: "shell",
    shellProtocolVersion: SHELL_PROTOCOL_VERSION,
    hotOpsProtocolVersion: HOT_OPERATION_PROTOCOL_VERSION,
    minimumRunnerVersion: MINIMUM_RUNNER_VERSION,
    capabilities: BRIDGE_PROTOCOL_CAPABILITIES.slice(),
    buildId: currentWindowsBuildInfo().buildId,
    buildSha: currentWindowsBuildInfo().sha256 || "",
    appVersion: app.getVersion(),
    arch: os.arch(),
    platform: process.platform,
    kernel,
    nativeKernel: kernel,
    downloadedRuntime: kernel.downloadedRuntime,
    activeDownloadedRuntimeId: kernel.activeDownloadedRuntimeId,
    activeDownloadedRuntimeSha: kernel.activeDownloadedRuntimeSha,
    activeHotOpBundleId: kernel.activeHotOpBundleId,
    activeHotOpSha: kernel.activeHotOpSha,
    syncStatus: kernel.syncStatus,
    staleReason: kernel.staleReason,
    hotOperations: hotOps,
    logsTail: recentBridgeLogsTail(),
    failureClassification: null,
    nextAction: "Run list_hot_operations, run_shell_self_test, then canary_echo.",
  };
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

function adbDeviceFields(detail = "") {
  const fields = {};
  String(detail || "").split(/\s+/).forEach((part) => {
    const match = part.match(/^([^:]+):(.+)$/);
    if (!match) return;
    const key = match[1];
    if (["model", "product", "device"].includes(key)) fields[key] = match[2];
  });
  return fields;
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

function androidConnectionInstructions(status = "") {
  if (status === "adb_missing") return adbMissingInstructions();
  if (status === "unauthorized") {
    return "Unlock the phone and accept the USB debugging authorization prompt.";
  }
  if (status === "offline") {
    return "Reconnect USB, toggle USB debugging, then retry.";
  }
  if (status === "no_device") {
    return "Phone not visible to Windows ADB. Check cable, USB mode, driver, and debugging.";
  }
  if (status === "multiple_devices") return "Disconnect extra Android devices or emulators, then retry with exactly one authorized phone.";
  if (status === "one_authorized_device") return "One authorized Android device is visible to Windows ADB.";
  if (status === "adb_timeout") return "ADB device discovery timed out while starting or contacting the daemon. Retry after platform-tools finishes starting, or restart WASM Agent.";
  if (status === "adb_server_start_failed") return "ADB server failed to start. Close other ADB processes, reconnect USB, and retry.";
  return "ADB returned an unexpected error. Check platform-tools and reconnect the phone.";
}

function isAdbServerStartupOutput(resultOrText = {}) {
  const text = typeof resultOrText === "string"
    ? resultOrText
    : `${resultOrText.stdout || ""}\n${resultOrText.stderr || ""}\n${resultOrText.error || ""}`;
  return /\bdaemon not running\b|\bstarting now\b|\bstarted successfully\b|tcp:5037/i.test(text);
}

function isBlankAdbDevicesOutput(stdout = "") {
  return parseAdbDevices(stdout).length === 0;
}

function parseAndroidConnectionState(stdout = "", commandOk = true, commandResult = {}) {
  if (!commandOk) {
    const status = isAdbMissingResult(commandResult)
      ? "adb_missing"
      : commandResult.timedOut
        ? "adb_timeout"
        : "adb_timeout";
    return {
      status,
      ok: false,
      devices: [],
      authorizedDevices: [],
      instructions: androidConnectionInstructions(status),
    };
  }
  const devices = parseAdbDevices(stdout).map((device) => ({ ...device, ...adbDeviceFields(device.detail) }));
  const authorizedDevices = devices.filter((device) => device.state === "device");
  const unauthorizedDevices = devices.filter((device) => device.state === "unauthorized");
  const offlineDevices = devices.filter((device) => device.state === "offline");
  let status = "no_device";
  if (authorizedDevices.length === 1 && devices.length === 1) status = "one_authorized_device";
  else if (authorizedDevices.length > 1 || (authorizedDevices.length === 1 && devices.length > 1)) status = "multiple_devices";
  else if (unauthorizedDevices.length > 0) status = "unauthorized";
  else if (offlineDevices.length > 0 && devices.length === 1) status = "offline";
  else if (devices.length > 1) status = "multiple_devices";
  const device = status === "one_authorized_device" ? authorizedDevices[0] : null;
  return {
    status,
    ok: status === "one_authorized_device",
    devices,
    authorizedDevices,
    hasAuthorizedDevice: status === "one_authorized_device",
    serial: device?.serial || "",
    model: device?.model || "",
    product: device?.product || "",
    device: device?.device || "",
    instructions: androidConnectionInstructions(status),
  };
}

function adbMissingInstructions() {
  return "Install Android SDK Platform Tools, add platform-tools to PATH, then restart WASM Agent.";
}

function isAdbMissingResult(result = {}) {
  return !result.ok && /ENOENT|not recognized|cannot find|not found|where\.exe.*adb/i.test(`${result.stderr || ""}\n${result.error || ""}`);
}

function shouldRecoverAdbDevicesResult(result = {}) {
  if (isAdbMissingResult(result)) return false;
  if (result.timedOut) return true;
  if (isAdbServerStartupOutput(result)) return true;
  if (result.ok && isBlankAdbDevicesOutput(result.stdout || "")) return true;
  return false;
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

async function runAdbDeviceDiscoveryWithRecovery(sender, opId, adbPath, operationPrefix = "adb", options = {}) {
  const resolvedAdbPath = adbPath || await findWindowsAdbExecutable();
  const commands = {};
  const deadline = Date.now() + Number(options.recoveryMs || 30_000);
  const devicesTimeoutMs = Number(options.devicesTimeoutMs || 5000);
  const maxBuffer = Number(options.maxBuffer || 128 * 1024);
  const runDevices = async (suffix) => runWindowsDiagnosticExec(sender, opId, `${operationPrefix}_${suffix}`, resolvedAdbPath, ["devices", "-l"], { timeoutMs: devicesTimeoutMs, maxBuffer });

  commands.devicesInitial = await runDevices("adb_devices");
  if (isAdbMissingResult(commands.devicesInitial)) {
    const parsed = parseAndroidConnectionState(commands.devicesInitial.stdout || "", false, commands.devicesInitial);
    return { ok: false, status: parsed.status, adbPath: resolvedAdbPath, commands, ...parsed };
  }

  if (!shouldRecoverAdbDevicesResult(commands.devicesInitial)) {
    const parsed = parseAndroidConnectionState(commands.devicesInitial.stdout || "", commands.devicesInitial.ok, commands.devicesInitial);
    return { adbPath: resolvedAdbPath, commands, ...parsed };
  }

  commands.killServer = await runWindowsDiagnosticExec(sender, opId, `${operationPrefix}_adb_kill_server`, resolvedAdbPath, ["kill-server"], { timeoutMs: 5000, maxBuffer });
  if (isAdbMissingResult(commands.killServer)) {
    const parsed = parseAndroidConnectionState(commands.killServer.stdout || "", false, commands.killServer);
    return { ok: false, status: parsed.status, adbPath: resolvedAdbPath, commands, ...parsed };
  }
  commands.startServer = await runWindowsDiagnosticExec(sender, opId, `${operationPrefix}_adb_start_server`, resolvedAdbPath, ["start-server"], { timeoutMs: 10000, maxBuffer });
  if (!commands.startServer.ok) {
    const status = commands.startServer.timedOut || isAdbServerStartupOutput(commands.startServer) ? "adb_server_start_failed" : "adb_server_start_failed";
    return { ok: false, status, adbPath: resolvedAdbPath, commands, devices: [], authorizedDevices: [], instructions: androidConnectionInstructions(status) };
  }

  let latest = null;
  let attempt = 0;
  while (Date.now() < deadline) {
    attempt += 1;
    latest = await runDevices(`adb_devices_retry_${attempt}`);
    commands[`devicesRetry${attempt}`] = latest;
    if (isAdbMissingResult(latest)) {
      const parsed = parseAndroidConnectionState(latest.stdout || "", false, latest);
      return { ok: false, status: parsed.status, adbPath: resolvedAdbPath, commands, ...parsed };
    }
    const parsed = parseAndroidConnectionState(latest.stdout || "", latest.ok, latest);
    if (parsed.status === "one_authorized_device" || parsed.status === "unauthorized" || parsed.status === "offline" || parsed.status === "multiple_devices") {
      return { adbPath: resolvedAdbPath, commands, ...parsed };
    }
    await sleep(Math.max(500, Math.min(Number(options.retryDelayMs || 1500), 5000)));
  }
  const parsed = latest
    ? parseAndroidConnectionState(latest.stdout || "", latest.ok, latest)
    : parseAndroidConnectionState("", false, { timedOut: true });
  return { adbPath: resolvedAdbPath, commands, ...parsed, status: parsed.status === "adb_timeout" ? "adb_timeout" : parsed.status };
}

async function runWindowsDiagnosticExecBinary(sender, opId, operation, command, args = [], options = {}) {
  const startedAt = new Date().toISOString();
  const displayCommand = commandLineDisplay(path.basename(command), args);
  writeNativeControlAudit({ action: "local_diagnostics_command_started", operation, opId, command: displayCommand, startedAt });
  emitWindowsDiagnosticEvent(sender, { type: "command_started", operation, opId, command: displayCommand, startedAt });
  const result = await execFileBufferBounded(command, args, options);
  const summary = sanitizeRendererDiagnosticValue({
    ...result,
    stdout: undefined,
    stdoutBytes: Buffer.isBuffer(result.stdout) ? result.stdout.length : 0,
  });
  writeNativeControlAudit({ action: "local_diagnostics_command_finished", operation, opId, result: summary });
  emitWindowsDiagnosticEvent(sender, { type: "command_finished", operation, opId, result: summary });
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
  const discovery = await runAdbDeviceDiscoveryWithRecovery(sender, opId, resolvedAdbPath, "adb_devices", { recoveryMs: 30_000 });
  const devices = {
    status: discovery.status,
    devices: discovery.devices || [],
    authorizedCount: (discovery.authorizedDevices || []).length,
    unauthorizedCount: (discovery.devices || []).filter((device) => device.state === "unauthorized").length,
    offlineCount: (discovery.devices || []).filter((device) => device.state === "offline").length,
    hasAuthorizedDevice: discovery.status === "one_authorized_device",
  };
  const label = devices.status === "one_authorized_device"
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
    message: androidConnectionInstructions(devices.status),
    devices,
  });
  return { ...discovery, adbPath: resolvedAdbPath, devices };
}

async function runAndroidConnectionCheck(sender, opId) {
  if (process.platform !== "win32") return { ok: false, status: "adb_error", error: "windows_native_shell_required" };
  const adbPath = await findWindowsAdbExecutable();
  emitWindowsDiagnosticEvent(sender, {
    type: "status",
    operation: "check_android_connection",
    opId,
    status: "checking_adb",
    label: "checking Android connection",
  });
  const result = await runAdbDeviceDiscoveryWithRecovery(sender, opId, adbPath, "android_connection", { recoveryMs: 30_000 });
  emitWindowsDiagnosticEvent(sender, {
    type: "status",
    operation: "check_android_connection",
    opId,
    status: result.status,
    label: result.status,
    message: result.instructions,
    device: result.ok ? { serial: result.serial, model: result.model, product: result.product, device: result.device } : null,
  });
  writeNativeControlAudit({ action: "android_connection_check_finished", opId, result });
  return result;
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

function androidVoiceTuningProofRoot() {
  try {
    return path.join(app.getPath("userData"), "native-diagnostics", "android-voice-tuning");
  } catch {
    return path.join(os.tmpdir(), "wasm-agent-android-voice-tuning");
  }
}

function androidVoiceTuningInstructions(status) {
  if (status === "unauthorized") return "Device visible but unauthorized. Accept the USB debugging prompt on the phone, then rerun adb devices.";
  return "No Android device visible to Windows ADB. Unlock phone, enable USB debugging, set USB mode to File Transfer, accept RSA prompt.";
}

function androidVoiceTuningStagingRoot() {
  const localAppData = process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
  return path.join(localAppData, "WASM Agent", "staged", "android");
}

function emitAndroidVoiceTuningStep(sender, opId, step, detail = {}, operation = "prove_android_voice_tuning") {
  return emitWindowsDiagnosticEvent(sender, {
    type: "progress",
    operation,
    opId,
    step,
    status: detail.ok === false ? "failed" : "ok",
    ...detail,
  });
}

function bundledAndroidApkMetadata() {
  return readJsonFile(bundledAndroidApkDefaultsPath(), {});
}

function latestAndroidReleaseFeedPath() {
  return path.resolve(__dirname, "..", "..", "..", "plugins", "wasm-agent", "public", "native", "releases", "latest.json");
}

async function latestAndroidReleaseFeed(payload = {}) {
  const timeoutMs = Math.max(1000, Math.min(Number(payload.feedTimeoutMs || payload.feed_timeout_ms || 10000), 60000));
  const feedUrl = new URL("/native/releases/latest.json", selectedBackendOrigin || DEFAULT_SERVER_URL).toString();
  try {
    return {
      source: "live",
      feedUrl,
      feed: await fetchJsonWithTimeout(feedUrl, timeoutMs),
    };
  } catch (error) {
    return {
      source: "bundled_fallback",
      feedUrl,
      error: String(error && error.message ? error.message : error),
      feed: readJsonFile(latestAndroidReleaseFeedPath(), {}),
    };
  }
}

function androidReleaseArtifactFromFeed(feed = {}) {
  const android = feed?.artifacts?.android || {};
  return android.arm64 || android.universal || {};
}

function defaultAndroidReleaseArtifact() {
  return {
    platform: "android",
    arch: "arm64",
    kind: "android-apk",
    filename: "WASM-Agent-arm64.apk",
    url: "/native/releases/android/WASM-Agent-arm64.apk",
    packageName: "com.colmeio.wasmagent",
  };
}

function expectedAndroidApkMetadata(payload = {}, source = {}) {
  const sha256 = String(payload.apkSha256 || payload.apk_sha256 || source.sha256 || "").trim().toLowerCase();
  const sizeBytes = Number(payload.apkSizeBytes || payload.apk_size_bytes || source.sizeBytes || source.size || 0);
  return {
    sha256,
    sizeBytes: Number.isFinite(sizeBytes) ? sizeBytes : 0,
    buildId: String(payload.buildId || payload.build_id || source.buildId || "").trim(),
    url: String(source.url || "").trim(),
    packageName: String(source.packageName || payload.packageName || payload.package_name || "com.colmeio.wasmagent").trim(),
  };
}

function isAllowlistedAndroidApkUrl(value) {
  let url;
  try {
    url = new URL(value, selectedBackendOrigin || DEFAULT_SERVER_URL);
  } catch {
    return { ok: false, error: "invalid_apk_url" };
  }
  if (!/^https?:$/.test(url.protocol)) return { ok: false, error: "invalid_apk_url" };
  if (!/\/native\/releases\/android\/WASM-Agent-(arm64|universal)\.apk$/i.test(url.pathname)) {
    return { ok: false, error: "apk_url_not_allowlisted", url: url.toString() };
  }
  const origin = url.origin.toLowerCase();
  const allowedOrigins = new Set([
    normalizeServerUrl(selectedBackendOrigin || DEFAULT_SERVER_URL).toLowerCase(),
    normalizeServerUrl(DEFAULT_SERVER_URL).toLowerCase(),
  ]);
  if (allowLocalDevCandidates()) {
    allowedOrigins.add(loopbackDevServerUrl().toLowerCase());
    allowedOrigins.add(localhostDevServerUrl().toLowerCase());
  }
  if (!allowedOrigins.has(origin)) return { ok: false, error: "apk_url_origin_not_allowlisted", url: url.toString() };
  return { ok: true, url: url.toString() };
}

function validateAndroidVoiceTuningApk(filePath, expected = {}) {
  const stat = statFile(filePath);
  if (!stat || !stat.isFile()) return { ok: false, error: "apk_missing", path: filePath };
  const sizeBytes = stat.size;
  const expectedSize = Number(expected.sizeBytes || 0);
  if (expectedSize > 0 && sizeBytes !== expectedSize) {
    return { ok: false, error: "apk_size_mismatch", path: filePath, sizeBytes, expectedSize };
  }
  if (!expectedSize && sizeBytes <= 50 * 1024 * 1024) {
    return { ok: false, error: "stale_or_stub_apk", path: filePath, sizeBytes, minSizeBytes: 50 * 1024 * 1024 };
  }
  if (expectedSize > 0 && expectedSize <= 50 * 1024 * 1024) {
    return { ok: false, error: "stale_or_stub_apk", path: filePath, sizeBytes, expectedSize };
  }
  const sha256 = sha256File(filePath).toLowerCase();
  if (expected.sha256 && sha256 !== expected.sha256) {
    return { ok: false, error: "apk_sha256_mismatch", path: filePath, sizeBytes, sha256, expectedSha256: expected.sha256 };
  }
  return { ok: true, path: filePath, sizeBytes, sha256, expectedSize, expectedSha256: expected.sha256 || "", buildId: expected.buildId || "" };
}

async function downloadAndroidVoiceTuningApk(sender, opId, url, expected = {}, payload = {}) {
  const timeoutMs = Math.max(1000, Math.min(Number(payload.downloadTimeoutMs || payload.download_timeout_ms || 120_000), 300_000));
  fs.mkdirSync(androidVoiceTuningStagingRoot(), { recursive: true });
  const target = path.join(androidVoiceTuningStagingRoot(), "WASM-Agent-arm64.apk");
  emitAndroidVoiceTuningStep(sender, opId, "apk_download_started", { url, target, timeoutMs }, payload.progressOperation || "prove_android_voice_tuning");
  let response;
  try {
    response = await fetchWithTimeout(url, { method: "GET" }, timeoutMs);
  } catch (error) {
    return {
      ok: false,
      error: "fresh_apk_download_failed",
      url,
      timeoutMs,
      message: error?.message || String(error),
      suggestedManualInstall: `Download ${url} and run: adb install -r <downloaded_fresh_apk_path>`,
    };
  }
  if (!response.ok || !response.body) {
    return {
      ok: false,
      error: "fresh_apk_download_failed",
      url,
      status: response.status,
      statusText: response.statusText || "",
      timeoutMs,
      suggestedManualInstall: `Download ${url} and run: adb install -r <downloaded_fresh_apk_path>`,
    };
  }
  const writer = fs.createWriteStream(target);
  let sizeBytes = 0;
  const hash = crypto.createHash("sha256");
  try {
    for await (const chunk of response.body) {
      const buffer = Buffer.from(chunk);
      sizeBytes += buffer.length;
      hash.update(buffer);
      if (!writer.write(buffer)) await once(writer, "drain");
    }
    writer.end();
    await once(writer, "finish");
  } catch (error) {
    writer.destroy();
    return { ok: false, error: "fresh_apk_download_failed", url, timeoutMs, message: error?.message || String(error), target };
  }
  const sha256 = hash.digest("hex");
  emitAndroidVoiceTuningStep(sender, opId, "apk_download_finished", { url, target, sizeBytes }, payload.progressOperation || "prove_android_voice_tuning");
  emitAndroidVoiceTuningStep(sender, opId, "apk_hash_computed", { path: target, sizeBytes, sha256, expectedSha256: expected.sha256 || "" }, payload.progressOperation || "prove_android_voice_tuning");
  return { ok: true, source: "download", path: target, url, sizeBytes, sha256 };
}

async function resolveAndroidVoiceTuningApk(sender, opId, payload = {}) {
  const explicitUrl = String(payload.apkUrl || payload.apk_url || "").trim();
  const explicitPath = String(payload.apkPath || payload.apk_path || process.env.WASM_AGENT_ANDROID_APK || "").trim();
  const releaseFeed = await latestAndroidReleaseFeed(payload);
  const releaseArtifact = androidReleaseArtifactFromFeed(releaseFeed.feed);
  const freshArtifact = releaseArtifact.url || releaseArtifact.path ? releaseArtifact : defaultAndroidReleaseArtifact();
  const releaseMeta = expectedAndroidApkMetadata(payload, releaseArtifact);
  let selected = null;

  if (explicitUrl) {
    const allowed = isAllowlistedAndroidApkUrl(explicitUrl);
    if (!allowed.ok) return allowed;
    selected = { source: "explicit_url", url: allowed.url, expected: expectedAndroidApkMetadata(payload, {}) };
  } else if (freshArtifact.url) {
    const allowed = isAllowlistedAndroidApkUrl(freshArtifact.url);
    selected = allowed.ok
      ? { source: "release_feed", url: allowed.url, expected: releaseMeta }
      : { source: "release_feed_path", path: freshArtifact.path, expected: releaseMeta };
  } else if (explicitPath) {
    selected = { source: "explicit_path", path: explicitPath, expected: expectedAndroidApkMetadata(payload, {}) };
  } else {
    selected = { source: "bundled", path: bundledAndroidApkPath(), expected: expectedAndroidApkMetadata(payload, bundledAndroidApkMetadata()) };
  }

  emitAndroidVoiceTuningStep(sender, opId, "apk_source_selected", {
    source: selected.source,
    releaseFeedSource: releaseFeed.source,
    releaseFeedUrl: releaseFeed.feedUrl,
    releaseFeedError: releaseFeed.error || "",
    url: selected.url || "",
    path: selected.path || "",
    expectedSizeBytes: selected.expected.sizeBytes || 0,
    expectedSha256: selected.expected.sha256 || "",
    buildId: selected.expected.buildId || "",
  }, payload.progressOperation || "prove_android_voice_tuning");

  let apk = selected;
  if (selected.url) {
    apk = await downloadAndroidVoiceTuningApk(sender, opId, selected.url, selected.expected, payload);
    if (!apk.ok) return apk;
    apk = { ...selected, ...apk };
  }
  const validation = validateAndroidVoiceTuningApk(apk.path, selected.expected);
  emitAndroidVoiceTuningStep(sender, opId, validation.ok ? "apk_validation_passed" : "apk_validation_failed", validation, payload.progressOperation || "prove_android_voice_tuning");
  if (!validation.ok) return { ok: false, ...validation, source: selected.source, url: selected.url || "" };
  return { ok: true, source: selected.source, path: apk.path, url: selected.url || "", ...validation };
}

function parseJsonObjectSafe(value, fallback = {}) {
  if (value && typeof value === "object" && !Buffer.isBuffer(value)) return value;
  try {
    return JSON.parse(String(value || ""));
  } catch {
    return fallback;
  }
}

function powershellSingleQuoted(value) {
  return `'${String(value || "").replace(/'/g, "''")}'`;
}

function latestAndroidEvent(nativeDiagnostics = {}, kind = "") {
  const events = Array.isArray(nativeDiagnostics.events) ? nativeDiagnostics.events : [];
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (String(events[index]?.kind || "") === kind) return events[index];
  }
  return null;
}

function firstAndroidEventAt(nativeDiagnostics = {}, kind = "") {
  const events = Array.isArray(nativeDiagnostics.events) ? nativeDiagnostics.events : [];
  const event = events.find((item) => String(item?.kind || "") === kind);
  return Number(event?.timestamp || 0) || 0;
}

function androidVoiceTuningRuntimeProbe(nativeDiagnostics = {}) {
  const event = latestAndroidEvent(nativeDiagnostics, "train_hermes_wake_runtime_probe");
  return event?.payload && typeof event.payload === "object" ? event.payload : {};
}

function permissionStateFromRuntime(nativeDiagnostics = {}, probe = {}) {
  const voiceTuning = nativeDiagnostics.voice_tuning || {};
  const bridgeDetails = probe?.payload?.bridge_details || probe?.bridge_details || {};
  const permissionState = voiceTuning.permission_state || bridgeDetails.permission_state || {};
  const recordAudio = typeof permissionState.record_audio === "string"
    ? permissionState.record_audio
    : voiceTuning.permission_record_audio === true || bridgeDetails.recording_supported === true
      ? "granted"
      : "missing";
  return {
    record_audio: recordAudio,
    permission_record_audio: recordAudio === "granted",
    raw: permissionState,
  };
}

function androidPermissionPromptInfo(uiXml = "") {
  const text = String(uiXml || "");
  const microphonePrompt = /android\.permissioncontroller|permission/i.test(text)
    && /microphone|record audio|record_audio|audio/i.test(text)
    && /while using|allow|deny/i.test(text);
  const unrelatedPrompt = /android\.permissioncontroller|permission/i.test(text)
    && !/microphone|record audio|record_audio|audio/i.test(text)
    && /while using|allow|deny|permission/i.test(text);
  return {
    visible: microphonePrompt || unrelatedPrompt,
    microphone: microphonePrompt,
    unrelated: unrelatedPrompt,
  };
}

function androidVoiceTuningTiming(nativeDiagnostics = {}, launchStartedAtMs = 0, resultFinishedAtMs = Date.now()) {
  const pageStartedAt = Number(nativeDiagnostics.webview?.page_started_at || firstAndroidEventAt(nativeDiagnostics, "webview_page_started") || 0);
  const pageCommitVisibleAt = Number(nativeDiagnostics.webview?.page_commit_visible_at || firstAndroidEventAt(nativeDiagnostics, "webview_page_commit_visible") || 0);
  const pageFinishedAt = Number(nativeDiagnostics.webview?.page_finished_at || firstAndroidEventAt(nativeDiagnostics, "webview_page_finished") || 0);
  const probeAt = firstAndroidEventAt(nativeDiagnostics, "train_hermes_wake_runtime_probe");
  return {
    activity_launch_to_visible_ms: launchStartedAtMs && pageCommitVisibleAt ? Math.max(0, pageCommitVisibleAt - launchStartedAtMs) : 0,
    activity_launch_to_probe_ms: launchStartedAtMs && probeAt ? Math.max(0, probeAt - launchStartedAtMs) : 0,
    modal_open_to_bridge_ready_ms: pageCommitVisibleAt && probeAt ? Math.max(0, probeAt - pageCommitVisibleAt) : 0,
    page_started_to_commit_visible_ms: pageStartedAt && pageCommitVisibleAt ? Math.max(0, pageCommitVisibleAt - pageStartedAt) : 0,
    page_started_to_finished_ms: pageStartedAt && pageFinishedAt ? Math.max(0, pageFinishedAt - pageStartedAt) : 0,
    wall_wait_ms: launchStartedAtMs ? Math.max(0, resultFinishedAtMs - launchStartedAtMs) : 0,
  };
}

function classifyAndroidVoiceTuningRuntime(capture = {}, expectedApk = {}) {
  const nativeDiagnostics = capture.nativeDiagnostics || {};
  const probe = capture.runtimeProbe || {};
  const bridgePayload = probe.payload || probe || {};
  const bridgeDetails = bridgePayload.bridge_details || {};
  const permission = capture.permissionState || permissionStateFromRuntime(nativeDiagnostics, probe);
  const timing = capture.timing || {};
  const logcat = String(capture.relevantLogcat || "");
  const uiXml = String(capture.uiXml || "");
  const prompt = capture.permissionPrompt || androidPermissionPromptInfo(uiXml);
  const apkBuildId = String(nativeDiagnostics.build?.build_id || bridgeDetails.apk_build_id || capture.apkBuildId || "");
  const webBuildId = String(bridgePayload.web_build_id || bridgeDetails.web_build_id || capture.webBuildId || "");
  const expectedBuildId = String(expectedApk.buildId || expectedApk.build_id || "");
  const failures = [];
  if (expectedBuildId && apkBuildId && apkBuildId !== expectedBuildId) failures.push("stale_apk");
  if (capture.blankWebView) failures.push("blank_webview");
  if (!bridgePayload.bridge_object_present && !capture.bridgeObjectPresent) failures.push("missing_bridge");
  if (permission.record_audio === "missing") failures.push("missing_permission");
  if (prompt.microphone) failures.push("permission_prompt_visible");
  if (prompt.unrelated) failures.push("unrelated_permission_prompt_visible");
  if (/ANR|Application Not Responding|Input dispatching timed out/i.test(logcat)) failures.push("ui_thread_lag_anr_risk");
  if (/Choreographer.*Skipped\s+([3-9]\d|[1-9]\d{2,})\s+frames/i.test(logcat) || Number(timing.activity_launch_to_visible_ms || 0) > 8000 || Number(timing.modal_open_to_bridge_ready_ms || 0) > 3000) {
    failures.push("ui_thread_lag");
  }
  if (/clear_webview_data|cache|ServiceWorker|ERR_CACHE|stale/i.test(logcat) && !bridgePayload.native_flags_present) failures.push("webview_cache_issue");
  if (permission.record_audio === "granted" && /recorder_unavailable|audio_record_initialization_failed/i.test(logcat)) failures.push("recorder_not_ready");
  if (/onnx|OrtEnvironment|OpenWakeWordOnnxEngine|createSession|wake_model/i.test(logcat) && Number(timing.modal_open_to_bridge_ready_ms || 0) > 1000) failures.push("onnx_model_initialization_lag");
  if (capture.recordingStartedAutomatically) failures.push("recording_started_automatically");
  if (capture.crashDetected) failures.push("app_crash");
  const stable = !failures.some((item) => !["missing_permission", "permission_prompt_visible"].includes(item))
    && Boolean(bridgePayload.android_shell_detected || capture.androidShellDetected)
    && Boolean(bridgePayload.native_flags_present || capture.nativeFlagsPresent)
    && Boolean(bridgePayload.bridge_object_present || capture.bridgeObjectPresent)
    && Boolean(bridgePayload.tune_voice_modal_open || /Train Hermes Wake/i.test(uiXml));
  return {
    stable,
    failure_classification: failures[0] || "stable",
    failures,
    apk_build_id: apkBuildId,
    web_build_id: webBuildId,
    bridge_status: bridgeDetails.bridge_status || nativeDiagnostics.voice_tuning?.bridge_status || (capture.bridgeObjectPresent ? "connected" : "missing"),
    permission_state: permission.record_audio,
    next_run_safe: !failures.includes("recording_started_automatically")
      && !failures.includes("unrelated_permission_prompt_visible")
      && !failures.includes("app_crash")
      && !failures.includes("ui_thread_lag_anr_risk"),
  };
}

async function captureAndroidVoiceTuningRuntime(sender, opId, adbPath, payload = {}, operation = "debug_android_voice_tuning_runtime") {
  const packageName = String(payload.packageName || payload.package_name || "com.colmeio.wasmagent");
  const componentName = String(payload.componentName || payload.component_name || `${packageName}/.MainActivity`);
  const debugScreen = String(payload.debugScreen || payload.debug_screen || "train-hermes-wake");
  const commands = {};
  const run = async (name, args, options = {}) => {
    commands[name] = await runWindowsDiagnosticExec(sender, opId, `android_voice_runtime_${name}`, adbPath, args, {
      timeoutMs: options.timeoutMs || 15000,
      maxBuffer: options.maxBuffer || 2 * 1024 * 1024,
    });
    return commands[name];
  };
  commands.devices = await run("devices", ["devices", "-l"], { timeoutMs: 5000, maxBuffer: 128 * 1024 });
  const devices = parseAndroidConnectionState(commands.devices.stdout || "", commands.devices.ok);
  if (devices.status !== "one_authorized_device") {
    return { ok: false, status: devices.status, devices, commands, message: devices.instructions };
  }
  commands.packageInfo = await run("package_info", ["shell", "dumpsys", "package", packageName], { timeoutMs: 12000, maxBuffer: 4 * 1024 * 1024 });
  commands.apkPath = await run("apk_path", ["shell", "pm", "path", packageName], { timeoutMs: 8000, maxBuffer: 256 * 1024 });
  commands.appOps = await run("appops_record_audio", ["shell", "appops", "get", packageName, "RECORD_AUDIO"], { timeoutMs: 8000, maxBuffer: 256 * 1024 });
  const clearData = Boolean(payload.clearData || payload.clear_data);
  const clearWebViewData = Boolean(payload.clearWebViewData || payload.clear_webview_data || payload.debugProofRun || payload.debug_proof_run);
  if (clearData) {
    commands.clearData = await run("clear_data", ["shell", "pm", "clear", packageName], { timeoutMs: 20000, maxBuffer: 256 * 1024 });
  } else if (payload.clearCache === true || payload.clear_cache === true) {
    commands.clearCache = await run("clear_cache", ["shell", "pm", "trim-caches", "64G"], { timeoutMs: 15000, maxBuffer: 256 * 1024 });
  }
  commands.forceStop = await run("force_stop", ["shell", "am", "force-stop", packageName], { timeoutMs: 10000, maxBuffer: 128 * 1024 });
  commands.logcatClear = await run("logcat_clear", ["logcat", "-c"], { timeoutMs: 10000, maxBuffer: 128 * 1024 });
  const launchStartedAtMs = Date.now();
  commands.launch = await run("launch", [
    "shell", "am", "start",
    "-n", componentName,
    "-a", "android.intent.action.MAIN",
    "-c", "android.intent.category.LAUNCHER",
    "--es", "debug_screen", debugScreen,
    "--es", "native_screen", debugScreen,
    "--ez", "clear_webview_data", clearWebViewData ? "true" : "false",
    "--es", "debug_requested_by", operation,
  ], { timeoutMs: 15000, maxBuffer: 512 * 1024 });
  const waitMs = Math.max(1000, Math.min(Number(payload.waitMs || payload.wait_ms || 12000), 60000));
  await sleep(waitMs);
  commands.activity = await run("activity", ["shell", "dumpsys", "activity", "activities"], { timeoutMs: 12000, maxBuffer: 4 * 1024 * 1024 });
  commands.window = await run("window", ["shell", "dumpsys", "window"], { timeoutMs: 12000, maxBuffer: 2 * 1024 * 1024 });
  commands.gfxinfo = await run("gfxinfo", ["shell", "dumpsys", "gfxinfo", packageName, "framestats"], { timeoutMs: 12000, maxBuffer: 4 * 1024 * 1024 });
  commands.uiautomatorDump = await run("uiautomator_dump", ["shell", "uiautomator", "dump", "/sdcard/wasm-agent-hermes-wake.xml"], { timeoutMs: 15000, maxBuffer: 256 * 1024 });
  commands.uiautomatorXml = await run("uiautomator_xml", ["exec-out", "cat", "/sdcard/wasm-agent-hermes-wake.xml"], { timeoutMs: 10000, maxBuffer: 2 * 1024 * 1024 });
  commands.nativeDiagnostics = await run("native_diagnostics", ["exec-out", "run-as", packageName, "cat", "files/native-diagnostics/latest.json"], { timeoutMs: 12000, maxBuffer: 4 * 1024 * 1024 });
  if (!commands.nativeDiagnostics.ok || !String(commands.nativeDiagnostics.stdout || "").trim()) {
    commands.nativeDiagnosticsFallback = await run("native_diagnostics_fallback", ["shell", "run-as", packageName, "cat", "files/native-diagnostics/latest.json"], { timeoutMs: 12000, maxBuffer: 4 * 1024 * 1024 });
  }
  commands.logcat = await run("logcat", ["logcat", "-d", "-v", "time"], { timeoutMs: 20000, maxBuffer: 16 * 1024 * 1024 });

  const proofRoot = androidVoiceTuningProofRoot();
  fs.mkdirSync(proofRoot, { recursive: true });
  const timestamp = timestampForFilename();
  const screenshotPath = path.join(proofRoot, `hermes-wake-${timestamp}.png`);
  const screenshot = await runWindowsDiagnosticExecBinary(sender, opId, `android_voice_runtime_screenshot`, adbPath, ["exec-out", "screencap", "-p"], { timeoutMs: 12000, maxBuffer: 16 * 1024 * 1024 });
  if (screenshot.ok && Buffer.isBuffer(screenshot.stdout) && screenshot.stdout.length > 0) {
    fs.writeFileSync(screenshotPath, screenshot.stdout);
  }

  const packageInfo = String(commands.packageInfo.stdout || "");
  const activity = String(commands.activity.stdout || "");
  const windowDump = String(commands.window.stdout || "");
  const logcat = String(commands.logcat.stdout || "");
  const uiXml = String(commands.uiautomatorXml.stdout || "");
  const nativeDiagnosticsText = String(commands.nativeDiagnostics.stdout || commands.nativeDiagnosticsFallback?.stdout || "");
  const nativeDiagnostics = parseJsonObjectSafe(nativeDiagnosticsText, {});
  const runtimeProbe = androidVoiceTuningRuntimeProbe(nativeDiagnostics);
  const permissionState = permissionStateFromRuntime(nativeDiagnostics, runtimeProbe);
  const permissionPrompt = androidPermissionPromptInfo(uiXml);
  const interestingLogPattern = /MainActivity|addJavascriptInterface|WasmAgentNativeVoiceTuning|voice_tuning_bridge_registered|native=android|native=electron|shell=android-webview|WebView URL|webview_load_url|webview_page_started|webview_page_finished|webview_page_commit_visible|Train Hermes Wake|bridge unavailable|getNativeVoiceTuningBridge|voice_tuning_bridge_available|frontend_bridge_detection|renderer_|train_hermes_wake_runtime_probe|activity_debug_screen_requested|activity_clear_webview_requested|wa\.colmeio\.com|com\.colmeio\.wasmagent|ANR|Application Not Responding|Choreographer|onnx|OrtEnvironment|OpenWakeWordOnnxEngine|native_record_started|voice_tuning_started/i;
  const activityPattern = /mResumedActivity|mFocusedRootTask|Hist #|Intent|dat=|cmp=com\.colmeio|cmp=com\.android\.chrome|webapk|wa\.colmeio/i;
  const versionLines = packageInfo.split(/\r?\n/).filter((line) => /version|versionCode|firstInstall|lastUpdate|Package \[|codePath|resourcePath/i.test(line)).join("\n");
  const activityLines = activity.split(/\r?\n/).filter((line) => activityPattern.test(line)).slice(0, 240).join("\n");
  const windowLines = windowDump.split(/\r?\n/).filter((line) => /mCurrentFocus|mFocusedApp|com\.colmeio|ChromeTabbedActivity|webapk|permissioncontroller/i.test(line)).slice(0, 160).join("\n");
  const relevantLogcat = logcat.split(/\r?\n/).filter((line) => interestingLogPattern.test(line)).slice(-800).join("\n");
  const launchUrl = String(nativeDiagnostics.current_webview_url || nativeDiagnostics.webview?.current_url || "");
  const bridgePayload = runtimeProbe.payload || runtimeProbe || {};
  const bridgeObjectPresent = Boolean(bridgePayload.bridge_object_present || /"bridge_object_present":true|voice_tuning_bridge_available[^\n]*(true|1)/i.test(relevantLogcat));
  const nativeFlagsPresent = Boolean(bridgePayload.native_flags_present || /"native_flags_present":true/i.test(relevantLogcat));
  const androidShellDetected = Boolean(bridgePayload.android_shell_detected || /"android_shell_detected":true/i.test(relevantLogcat));
  const recordingStartedAutomatically = /native_record_started|voice_tuning_started/i.test(relevantLogcat);
  const crashDetected = /FATAL EXCEPTION|AndroidRuntime|Process com\.colmeio\.wasmagent.*has died|Force finishing activity/i.test(logcat);
  const blankWebView = !/Train Hermes Wake|tuneVoice|tune-voice|Hermes/i.test(uiXml) && !bridgePayload.tune_voice_modal_open;
  const timing = androidVoiceTuningTiming(nativeDiagnostics, launchStartedAtMs, Date.now());
  const artifactPaths = {
    screenshotPath: screenshot.ok ? screenshotPath : "",
    uiXmlPath: path.join(proofRoot, `hermes-wake-${timestamp}.xml`),
    nativeDiagnosticsPath: path.join(proofRoot, `hermes-wake-native-${timestamp}.json`),
    logcatPath: path.join(proofRoot, `hermes-wake-${timestamp}.log`),
    resultPath: path.join(proofRoot, `runtime-bridge-${timestamp}.json`),
  };
  fs.writeFileSync(artifactPaths.uiXmlPath, uiXml);
  fs.writeFileSync(artifactPaths.nativeDiagnosticsPath, nativeDiagnosticsText || "{}");
  fs.writeFileSync(artifactPaths.logcatPath, relevantLogcat || logcat);
  const result = {
    ok: commands.devices.ok && commands.packageInfo.ok && commands.apkPath.ok && commands.launch.ok,
    status: "runtime_debug_captured",
    adbPath,
    packageName,
    componentName,
    debugScreen,
    waitMs,
    clearData,
    clearWebViewData,
    devices,
    launchUrl,
    webViewUrl: launchUrl,
    bridgeObject: bridgePayload.detected_bridge_object || bridgePayload.bridge_details?.detected_voice_tuning_bridge_name || "",
    bridgeObjectPresent,
    nativeFlagsPresent,
    androidShellDetected,
    permissionState,
    permissionPrompt,
    timing,
    apkBuildId: nativeDiagnostics.build?.build_id || bridgePayload.apk_build_id || "",
    webBuildId: bridgePayload.web_build_id || bridgePayload.bridge_details?.web_build_id || "",
    previousGuardFailureReason: bridgePayload.failure_reason || "",
    recordingStartedAutomatically,
    crashDetected,
    blankWebView,
    runtimeProbe,
    nativeDiagnostics,
    versionLines: clipDiagnosticText(versionLines, 32 * 1024),
    apkPath: clipDiagnosticText(commands.apkPath.stdout || "", 32 * 1024),
    activityLines: clipDiagnosticText(activityLines, 64 * 1024),
    windowLines: clipDiagnosticText(windowLines, 32 * 1024),
    uiXml: clipDiagnosticText(uiXml, 128 * 1024),
    relevantLogcat: clipDiagnosticText(relevantLogcat, 160 * 1024),
    fullLogLineCount: logcat.split(/\r?\n/).length,
    artifactPaths,
    commands: sanitizeRendererDiagnosticValue(commands),
  };
  result.classification = classifyAndroidVoiceTuningRuntime(result, payload.expectedApk || {});
  fs.writeFileSync(artifactPaths.resultPath, `${JSON.stringify(result, null, 2)}\n`);
  result.proofPath = artifactPaths.resultPath;
  writeNativeControlAudit({ action: "android_voice_tuning_runtime_debug_finished", opId, result });
  return result;
}

async function runAndroidVoiceTuningProof(sender, opId, payload = {}) {
  if (process.platform !== "win32") return { ok: false, status: "FAIL", error: "windows_native_shell_required" };
  const adbPath = await findWindowsAdbExecutable();
  const commands = {};
  const connection = await runAndroidConnectionCheck(sender, opId);
  if (connection.status !== "one_authorized_device") {
    return { ok: false, status: connection.status, adbPath, connection, message: connection.instructions };
  }
  commands.killServer = await runWindowsDiagnosticExec(sender, opId, "android_voice_tuning_adb_kill_server", adbPath, ["kill-server"], { timeoutMs: 5000, maxBuffer: 128 * 1024 });
  commands.startServer = await runWindowsDiagnosticExec(sender, opId, "android_voice_tuning_adb_start_server", adbPath, ["start-server"], { timeoutMs: 10000, maxBuffer: 128 * 1024 });
  commands.devices = await runWindowsDiagnosticExec(sender, opId, "android_voice_tuning_adb_devices", adbPath, ["devices"], { timeoutMs: 5000, maxBuffer: 128 * 1024 });
  const devices = classifyAdbDevices(commands.devices.stdout || "");
  emitAndroidVoiceTuningStep(sender, opId, "adb_devices_result", { devices, command: sanitizeRendererDiagnosticValue(commands.devices) });
  if (!devices.hasAuthorizedDevice) {
    const status = devices.status === "unauthorized" ? "unauthorized" : "no_device";
    const result = { ok: false, status, adbPath, devices, commands, message: androidVoiceTuningInstructions(status) };
    emitWindowsDiagnosticEvent(sender, { type: "status", operation: "prove_android_voice_tuning", opId, status, label: result.message, devices });
    return result;
  }

  const apk = await resolveAndroidVoiceTuningApk(sender, opId, payload);
  if (!apk.ok) return { ok: false, status: "FAIL", adbPath, devices, apk };
  const packageName = String(payload.packageName || payload.package_name || "com.colmeio.wasmagent");
  emitAndroidVoiceTuningStep(sender, opId, "adb_install_started", { apkPath: apk.path, sizeBytes: apk.sizeBytes, sha256: apk.sha256, source: apk.source });
  commands.install = await runWindowsDiagnosticExec(sender, opId, "android_voice_tuning_install", adbPath, ["install", "-r", apk.path], { timeoutMs: 180_000, maxBuffer: 2 * 1024 * 1024 });
  emitAndroidVoiceTuningStep(sender, opId, "adb_install_finished", { ok: commands.install.ok, command: sanitizeRendererDiagnosticValue(commands.install) });
  if (!commands.install.ok) return { ok: false, status: "install_failed", adbPath, devices, apk, commands };
  commands.forceStop = await runWindowsDiagnosticExec(sender, opId, "android_voice_tuning_force_stop", adbPath, ["shell", "am", "force-stop", packageName], { timeoutMs: 10000, maxBuffer: 128 * 1024 });
  emitAndroidVoiceTuningStep(sender, opId, "app_force_stopped", { ok: commands.forceStop.ok, command: sanitizeRendererDiagnosticValue(commands.forceStop) });
  commands.logcatClear = await runWindowsDiagnosticExec(sender, opId, "android_voice_tuning_logcat_clear", adbPath, ["logcat", "-c"], { timeoutMs: 10000, maxBuffer: 128 * 1024 });
  commands.launch = await runWindowsDiagnosticExec(sender, opId, "android_voice_tuning_launch", adbPath, ["shell", "monkey", "-p", packageName, "1"], { timeoutMs: 15000, maxBuffer: 512 * 1024 });
  emitAndroidVoiceTuningStep(sender, opId, "app_launched", { ok: commands.launch.ok, command: sanitizeRendererDiagnosticValue(commands.launch) });
  const waitMs = Math.max(1000, Math.min(Number(payload.proofWaitMs || payload.proof_wait_ms || 12000), 60000));
  if (waitMs) await sleep(waitMs);
  const tags = "voice_tuning_bridge_registered|WasmAgentNativeVoiceTuning|native=android|shell=android-webview|native=electron|getNativeVoiceTuningBridge|voice_tuning_bridge_available|Train Hermes Wake|bridge unavailable";
  emitAndroidVoiceTuningStep(sender, opId, "logcat_capture_started", { waitMs, tags });
  commands.logcat = await runWindowsDiagnosticExec(sender, opId, "android_voice_tuning_logcat", adbPath, ["logcat", "-d", "-v", "time"], { timeoutMs: 20000, maxBuffer: 8 * 1024 * 1024 });
  emitAndroidVoiceTuningStep(sender, opId, "logcat_capture_finished", { ok: commands.logcat.ok, command: sanitizeRendererDiagnosticValue(commands.logcat) });
  const logcat = String(commands.logcat.stdout || "");
  const relevantLogcat = logcat.split(/\r?\n/).filter((line) => new RegExp(tags, "i").test(line)).join("\n");
  const proofRoot = androidVoiceTuningProofRoot();
  fs.mkdirSync(proofRoot, { recursive: true });
  const logcatPath = path.join(proofRoot, `voice-tuning-${timestampForFilename()}.log`);
  fs.writeFileSync(logcatPath, relevantLogcat || logcat);
  const bridgeRegistered = /voice_tuning_bridge_registered[^\n]*(true|1)|voice_tuning_bridge_registered=true/i.test(relevantLogcat);
  const bridgeObjectSeen = /WasmAgentNativeVoiceTuning/i.test(relevantLogcat);
  const androidShellSeen = /native=android|shell=android-webview/i.test(relevantLogcat);
  const electronShellSeen = /native=electron/i.test(relevantLogcat);
  const developerPanelAvailable = /voice_tuning_bridge_available[^\n]*(true|1)|voice_tuning_bridge_available=true/i.test(relevantLogcat);
  const result = {
    ok: commands.install.ok && commands.launch.ok && bridgeRegistered && bridgeObjectSeen && androidShellSeen && !electronShellSeen,
    status: commands.install.ok && commands.launch.ok ? "runtime_bridge_checked" : "runtime_bridge_check_failed",
    adbPath,
    devices,
    apk,
    packageName,
    logcatPath,
    relevantLogcat: clipDiagnosticText(relevantLogcat, 64 * 1024),
    proof: {
      bridgeRegistered,
      bridgeObjectSeen,
      androidShellSeen,
      electronShellSeen,
      developerPanelAvailable,
    },
    commands: sanitizeRendererDiagnosticValue(commands),
  };
  writeNativeControlAudit({ action: "android_voice_tuning_proof_finished", opId, result });
  return result;
}

async function exportHermesWakeDataset(sender, opId, payload = {}) {
  if (process.platform !== "win32") return { ok: false, status: "FAIL", error: "windows_native_shell_required" };
  const packageName = String(payload.packageName || payload.package_name || "com.colmeio.wasmagent");
  const sourcePath = String(payload.sourcePath || payload.source_path || "files/voice/exports/hermes-dataset.zip");
  if (packageName !== "com.colmeio.wasmagent") {
    return { ok: false, status: "invalid_package", error: "Only com.colmeio.wasmagent dataset export is supported." };
  }
  if (sourcePath !== "files/voice/exports/hermes-dataset.zip") {
    return { ok: false, status: "invalid_source_path", error: "Only files/voice/exports/hermes-dataset.zip may be exported." };
  }
  const adbPath = await findWindowsAdbExecutable();
  const commands = {};
  commands.devices = await runWindowsDiagnosticExec(sender, opId, "export_hermes_wake_dataset_devices", adbPath, ["devices", "-l"], { timeoutMs: 5000, maxBuffer: 128 * 1024 });
  const devices = parseAndroidConnectionState(commands.devices.stdout || "", commands.devices.ok);
  if (devices.status !== "one_authorized_device") {
    return { ok: false, status: devices.status, adbPath, devices, commands, message: devices.instructions };
  }
  commands.stat = await runWindowsDiagnosticExec(sender, opId, "export_hermes_wake_dataset_stat", adbPath, ["exec-out", "run-as", packageName, "stat", "-c", "%s", sourcePath], { timeoutMs: 10000, maxBuffer: 64 * 1024 });
  const sizeBytes = Number.parseInt(String(commands.stat.stdout || "").trim(), 10);
  if (!commands.stat.ok || !Number.isFinite(sizeBytes) || sizeBytes <= 0) {
    return { ok: false, status: "dataset_export_missing", adbPath, devices, commands, message: "Click Export in Train Hermes Wake, then retry." };
  }
  const maxBytes = 256 * 1024 * 1024;
  if (sizeBytes > maxBytes) {
    return { ok: false, status: "dataset_export_too_large", adbPath, devices, commands, sizeBytes, maxBytes };
  }
  const pulled = await runWindowsDiagnosticExecBinary(sender, opId, "export_hermes_wake_dataset_pull", adbPath, ["exec-out", "run-as", packageName, "cat", sourcePath], {
    timeoutMs: 120000,
    maxBuffer: maxBytes + 1024,
  });
  if (!pulled.ok || !Buffer.isBuffer(pulled.stdout) || pulled.stdout.length <= 0) {
    return { ok: false, status: "dataset_export_pull_failed", adbPath, devices, commands, pull: sanitizeRendererDiagnosticValue(pulled) };
  }
  const timestamp = timestampForFilename();
  const exportDir = path.join(nativeDiagnosticsBundleRoot(), "android-hermes-wake-dataset");
  fs.mkdirSync(exportDir, { recursive: true });
  const exportPath = path.join(exportDir, `hermes-dataset-${timestamp}.zip`);
  fs.writeFileSync(exportPath, pulled.stdout);
  const sha256 = crypto.createHash("sha256").update(pulled.stdout).digest("hex");
  let upload = { ok: false, skipped: true, reason: "backend_origin_unavailable" };
  const backendOrigin = normalizeServerUrl(selectedBackendOrigin || DEFAULT_SERVER_URL);
  if (backendOrigin) {
    try {
      const response = await fetchWithTimeout(`${backendOrigin}/native/android/hermes-wake-dataset`, {
        method: "POST",
        headers: {
          "Content-Type": "application/zip",
          "X-Wasm-Agent-Dataset-Source": "windows-adb-run-as",
          "X-Wasm-Agent-Native-Device-Id": devices.serial || "android-hermes-wake",
          "X-Wasm-Agent-Dataset-Sha256": sha256,
        },
        body: pulled.stdout,
      }, Number(payload.uploadTimeoutMs || payload.upload_timeout_ms || 120000));
      const responseText = await response.text();
      let responseJson = {};
      try {
        responseJson = JSON.parse(responseText || "{}");
      } catch {
        responseJson = { raw: clipDiagnosticText(responseText, 2000) };
      }
      upload = { ok: response.ok, status: response.status, backendOrigin, response: responseJson };
    } catch (error) {
      upload = { ok: false, backendOrigin, error: String(error && error.message ? error.message : error) };
    }
  }
  const result = {
    ok: true,
    status: "dataset_exported",
    adbPath,
    packageName,
    sourcePath,
    exportPath,
    sizeBytes: pulled.stdout.length,
    expectedSizeBytes: sizeBytes,
    sha256,
    upload,
    devices,
    commands,
  };
  fs.writeFileSync(path.join(exportDir, "latest.json"), `${JSON.stringify(result, null, 2)}\n`);
  fs.writeFileSync(path.join(exportDir, "latest.path.txt"), `${exportPath}\n`);
  return result;
}

function parseJsonDiagnosticText(text = "") {
  const raw = String(text || "").trim();
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return { raw: clipDiagnosticText(raw, 16 * 1024) };
  }
}

function voiceWakeModelSource(status = {}) {
  return String(status.model_source || status.modelSource || status.wake_model_source || status.wakeProvider || status.wake_provider || "").toLowerCase();
}

function voiceWakeOpenWakeWordReady(status = {}) {
  const source = voiceWakeModelSource(status);
  return Boolean(
    (source === "openwakeword_bundle" || source.includes("openwakeword"))
      && status.onnx_runtime_available !== false
      && (status.wake_engine_ready === true || status.onnx_model_ready === true)
      && status.openwakeword_bundle_exists !== false
  );
}

function voiceWakeModelReady(status = {}) {
  return Boolean(
    status.onnx_model_ready === true
      || voiceWakeOpenWakeWordReady(status)
      || (status.onnx_runtime_available && status.wake_engine_ready && status.personalized_model_exists && status.model_sha_match)
  );
}

function classifyHermesWakeProof(status = {}) {
  const metrics = status.confidence_metrics || {};
  const latestWindow = status.latest_inference_window || {};
  const lastConfidence = Number(status.last_wake_confidence ?? status.last_confidence ?? metrics.last_confidence ?? latestWindow.confidence ?? 0);
  const maxConfidence = Number(status.max_observed_confidence ?? status.max_confidence_since_start ?? status.max_confidence ?? metrics.max_confidence ?? latestWindow.max_confidence ?? lastConfidence);
  const threshold = Number(status.wake_threshold ?? status.threshold ?? metrics.threshold ?? latestWindow.threshold ?? 0.58);
  const inferenceCount = Number(status.inference_count || 0);
  const wakeDetectionCount = Number(status.wake_detection_count || status.wake_hit_count || latestWindow.detection_count || (status.last_wake_at ? 1 : 0));
  const serviceAlive = Boolean((status.status_source === "live_service" || status.status_source === "lightweight_no_model_load" || !status.status_source) && status.proof_session_active !== false && (status.foreground_service_started || status.foreground_service_running || status.foreground_service_active || status.service_running || status.voice_service_running));
  const audioCaptureAlive = Boolean(status.permission_record_audio !== false && status.audio_capture_alive !== false && (status.audio_record_started || Number(status.audio_read_calls || 0) > 0 || inferenceCount > 0));
  const onnxModelReady = voiceWakeModelReady(status);
  const inferenceRunning = inferenceCount > 0;
  const confidenceObserved = Boolean(status.wake_confidence_observed || inferenceRunning || maxConfidence > 0);
  const thresholdCrossed = Boolean(status.threshold_crossed || status.last_inference_threshold_crossed || metrics.threshold_crossed || latestWindow.threshold_crossed || maxConfidence >= threshold);
  const wakeEventEmitted = Boolean(status.wake_detected_event_emitted || wakeDetectionCount > 0);
  const commandCaptureStarted = Boolean(status.command_capture_started || Number(status.command_capture_started_at || 0) > 0 || ["capturing", "transcribing", "sent"].includes(String(status.state || "").toLowerCase()));
  return {
    ok: serviceAlive && audioCaptureAlive && onnxModelReady && inferenceRunning && confidenceObserved && thresholdCrossed && wakeEventEmitted && commandCaptureStarted,
    stages: {
      "1_service_alive": serviceAlive,
      "2_audio_capture_alive": audioCaptureAlive,
      "3_onnx_model_ready": onnxModelReady,
      "4_inference_running": inferenceRunning,
      "5_wake_confidence_observed": confidenceObserved,
      "6_wake_threshold_crossed": thresholdCrossed,
      "7_wake_event_emitted": wakeEventEmitted,
      "8_command_capture_ui_action_started": commandCaptureStarted,
    },
    confidence: {
      last: lastConfidence,
      max: maxConfidence,
      threshold,
      rejection_reason: status.rejection_reason || status.last_inference_rejection_reason || latestWindow.rejection_reason || "",
      inference_count: inferenceCount,
      wake_detection_count: wakeDetectionCount,
      last_detection_timestamp: Number(status.last_detection_timestamp || status.last_wake_detection_at || status.last_wake_at || 0),
    },
  };
}

async function fetchAndroidHermesWakeStatusFromBackend() {
  const backendOrigin = normalizeServerUrl(selectedBackendOrigin || DEFAULT_SERVER_URL);
  if (!backendOrigin) return { ok: false, error: "backend_origin_unavailable" };
  try {
    const response = await fetchWithTimeout(`${backendOrigin}/native/android/wake-word-state`, {
      method: "GET",
      headers: { Accept: "application/json", "Cache-Control": "no-cache" },
    }, 12000);
    const text = await response.text();
    let payload = {};
    try {
      payload = JSON.parse(text || "{}");
    } catch {
      payload = { raw: clipDiagnosticText(text, 16000) };
    }
    const state = payload.state && typeof payload.state === "object" ? payload.state : {};
    if (response.ok && payload.available !== false && Object.keys(state).length) {
      return {
        ok: true,
        status: response.status,
        backendOrigin,
        payload: state,
        diagnostics: sanitizeRendererDiagnosticValue({ schema: payload.schema, available: payload.available, state }),
      };
    }
  } catch {
    // Fall through to the legacy diagnostics snapshot.
  }
  try {
    const response = await fetchWithTimeout(`${backendOrigin}/native/diagnostics/latest`, {
      method: "GET",
      headers: { Accept: "application/json", "Cache-Control": "no-cache" },
    }, 12000);
    const text = await response.text();
    let payload = {};
    try {
      payload = JSON.parse(text || "{}");
    } catch {
      payload = { raw: clipDiagnosticText(text, 16000) };
    }
    const voiceWake = payload.voice_wake || payload.voiceWake || payload.payload?.voice_wake || payload.payload?.voiceWake || {};
    return {
      ok: response.ok && Boolean(voiceWake && Object.keys(voiceWake).length),
      status: response.status,
      backendOrigin,
      payload: voiceWake,
      diagnostics: sanitizeRendererDiagnosticValue(payload),
    };
  } catch (error) {
    return { ok: false, backendOrigin, error: String(error && error.message ? error.message : error) };
  }
}

async function resolveBestVoiceWakeDiagnostics(sender, opId, payload = {}) {
  const packageName = String(payload.packageName || payload.package_name || "com.colmeio.wasmagent");
  const result = { source: "missing", path: "", data: {}, error: null };
  try {
    const adbPath = await findWindowsAdbExecutable();
    const device = await runWindowsDiagnosticExec(sender, opId, "hot_voice_wake_devices", adbPath, ["devices", "-l"], { timeoutMs: 5000, maxBuffer: 128 * 1024 });
    const connection = parseAndroidConnectionState(device.stdout || "", device.ok);
    const serialArgs = connection.serial ? ["-s", connection.serial] : [];
    const remotePath = "/sdcard/wasm-agent-voice-wake.json";
    const pullPath = path.join(hotOperationDataRoot("voice-wake-diagnostics"), `voice-wake-${timestampForFilename()}.json`);
    const pull = await runWindowsDiagnosticExec(sender, opId, "hot_voice_wake_pull", adbPath, [
      ...serialArgs,
      "pull",
      `/sdcard/Android/data/${packageName}/files/native-diagnostics/voice-wake.json`,
      pullPath,
    ], { timeoutMs: 12000, maxBuffer: 1024 * 1024 });
    if (pull.ok && fileExists(pullPath)) {
      return { source: "adb_pull", path: pullPath, data: readJsonFile(pullPath, {}), error: null };
    }
    const runAs = await runWindowsDiagnosticExec(sender, opId, "hot_voice_wake_run_as", adbPath, [
      ...serialArgs,
      "exec-out",
      "run-as",
      packageName,
      "cat",
      "files/native-diagnostics/voice-wake.json",
    ], { timeoutMs: 12000, maxBuffer: 4 * 1024 * 1024 });
    const parsed = parseJsonDiagnosticText(runAs.stdout || "");
    if (runAs.ok && Object.keys(parsed).length && !parsed.raw) {
      return { source: "run_as", path: "files/native-diagnostics/voice-wake.json", data: parsed, error: null };
    }
    const backend = await fetchAndroidHermesWakeStatusFromBackend();
    if (backend.ok) return { source: "server_upload", path: backend.backendOrigin || "", data: backend.payload || {}, error: null };
    result.error = backend.error || pull.stderr || runAs.stderr || "voice_wake_diagnostics_missing";
    return result;
  } catch (error) {
    result.error = String(error && error.message ? error.message : error);
    return result;
  }
}

async function playWindowsWakePhraseProbe(payload = {}) {
  const phrase = String(payload.phrase || payload.wakePhrase || payload.wake_phrase || "alexa")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80) || "alexa";
  const rate = Math.max(-5, Math.min(Math.round(Number(payload.rate ?? -1)), 5));
  const volume = Math.max(0, Math.min(Math.round(Number(payload.volume ?? 100)), 100));
  const timeoutMs = Math.max(1000, Math.min(Math.round(Number(payload.timeoutMs || payload.timeout_ms || 8000)), 15000));
  if (process.platform !== "win32") {
    return {
      ok: false,
      operation: "play_wake_phrase_probe",
      error: "windows_native_shell_required",
      phrase,
    };
  }
  const script = [
    "Add-Type -AssemblyName System.Speech;",
    `$phrase = ${powershellSingleQuoted(phrase)};`,
    "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer;",
    `$synth.Rate = ${rate};`,
    `$synth.Volume = ${volume};`,
    "try { $synth.Speak($phrase) } finally { $synth.Dispose() }",
  ].join(" ");
  const startedAt = Date.now();
  const result = await execFileBounded("powershell.exe", [
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
    script,
  ], { timeoutMs, maxBuffer: 64 * 1024 });
  return {
    ok: result.ok,
    operation: "play_wake_phrase_probe",
    source: "windows_speech_synthesizer",
    phrase,
    rate,
    volume,
    timeoutMs,
    elapsedMs: Date.now() - startedAt,
    exitCode: result.exitCode,
    timedOut: result.timedOut,
    error: result.error || result.stderr || "",
  };
}

async function playWindowsAudioStimulus(payload = {}) {
  const rawKind = String(payload.kind || payload.stimulus || payload.type || "speech").toLowerCase();
  const kind = ["speech", "system_sound", "beep", "silence"].includes(rawKind) ? rawKind : "speech";
  const label = String(payload.label || payload.stimulusId || payload.stimulus_id || kind)
    .replace(/[^A-Za-z0-9_.:-]+/g, "_")
    .slice(0, 80) || kind;
  const durationMs = Math.max(100, Math.min(Math.round(Number(payload.durationMs || payload.duration_ms || 700)), 5000));
  const timeoutMs = Math.max(1000, Math.min(Math.round(Number(payload.timeoutMs || payload.timeout_ms || durationMs + 5000)), 15000));
  if (kind === "speech") {
    const speech = await playWindowsWakePhraseProbe({
      phrase: payload.phrase || payload.text || payload.wakePhrase || payload.wake_phrase || "alexa",
      rate: payload.rate,
      volume: payload.volume,
      timeoutMs,
    });
    return {
      ...speech,
      operation: "play_audio_stimulus",
      stimulusKind: kind,
      stimulusLabel: label,
      nestedOperation: "play_wake_phrase_probe",
    };
  }
  if (process.platform !== "win32") {
    return {
      ok: false,
      operation: "play_audio_stimulus",
      error: "windows_native_shell_required",
      stimulusKind: kind,
      stimulusLabel: label,
    };
  }
  const startedAt = Date.now();
  let script = "";
  if (kind === "silence") {
    script = `Start-Sleep -Milliseconds ${durationMs};`;
  } else if (kind === "system_sound") {
    const sound = String(payload.sound || payload.systemSound || payload.system_sound || "Exclamation").replace(/[^A-Za-z]/g, "");
    const safeSound = ["Asterisk", "Beep", "Exclamation", "Hand", "Question"].includes(sound) ? sound : "Exclamation";
    script = [
      "Add-Type -AssemblyName System.Windows.Forms;",
      `[System.Media.SystemSounds]::${safeSound}.Play();`,
      `Start-Sleep -Milliseconds ${durationMs};`,
    ].join(" ");
  } else {
    const frequencyHz = Math.max(120, Math.min(Math.round(Number(payload.frequencyHz || payload.frequency_hz || payload.frequency || 880)), 4000));
    script = `[Console]::Beep(${frequencyHz}, ${durationMs});`;
  }
  const result = await execFileBounded("powershell.exe", [
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
    script,
  ], { timeoutMs, maxBuffer: 64 * 1024 });
  return {
    ok: result.ok,
    operation: "play_audio_stimulus",
    source: "windows_fixed_audio_stimulus",
    stimulusKind: kind,
    stimulusLabel: label,
    durationMs,
    timeoutMs,
    elapsedMs: Date.now() - startedAt,
    exitCode: result.exitCode,
    timedOut: result.timedOut,
    error: result.error || result.stderr || "",
  };
}

async function runAndroidHermesWakeProof(sender, opId, payload = {}) {
  if (process.platform !== "win32") return { ok: false, status: "FAIL", error: "windows_native_shell_required" };
  const packageName = String(payload.packageName || payload.package_name || "com.colmeio.wasmagent");
  if (packageName !== "com.colmeio.wasmagent") {
    return { ok: false, status: "invalid_package", error: "Only com.colmeio.wasmagent Hermes wake proof is supported." };
  }
  const adbPath = await findWindowsAdbExecutable();
  const commands = {};
  commands.devices = await runWindowsDiagnosticExec(sender, opId, "android_hermes_wake_proof_devices", adbPath, ["devices", "-l"], { timeoutMs: 5000, maxBuffer: 128 * 1024 });
  const devices = parseAndroidConnectionState(commands.devices.stdout || "", commands.devices.ok);
  if (devices.status !== "one_authorized_device") {
    return { ok: false, status: devices.status, adbPath, devices, commands, message: devices.instructions };
  }
  const waitMs = Math.max(5000, Math.min(Number(payload.waitMs || payload.wait_ms || 30000), 120000));
  emitAndroidVoiceTuningStep(sender, opId, "hermes_wake_proof_launching", { packageName, waitMs }, "run_android_hermes_wake_proof");
  commands.wakeup = await runWindowsDiagnosticExec(sender, opId, "android_hermes_wake_wakeup", adbPath, ["shell", "input", "keyevent", "KEYCODE_WAKEUP"], { timeoutMs: 5000, maxBuffer: 64 * 1024 });
  commands.launch = await runWindowsDiagnosticExec(sender, opId, "android_hermes_wake_launch", adbPath, [
    "shell",
    "am",
    "start",
    "-W",
    "-n",
    `${packageName}/.MainActivity`,
    "--es",
    "native_screen",
    "hermes-wake-proof",
  ], { timeoutMs: 15000, maxBuffer: 512 * 1024 });
  emitAndroidVoiceTuningStep(sender, opId, "hermes_wake_proof_listening", {
    waitMs,
    prompt: "Speak Hermes near the connected phone now.",
  }, "run_android_hermes_wake_proof");
  await new Promise((resolve) => setTimeout(resolve, waitMs));
  commands.statusRequest = await runWindowsDiagnosticExec(sender, opId, "android_hermes_wake_status_request", adbPath, [
    "shell",
    "am",
    "startservice",
    "-n",
    `${packageName}/.HermesVoiceWakeService`,
    "-a",
    "com.colmeio.wasmagent.voice.STATUS",
    "--ez",
    "proof_session",
    "true",
  ], { timeoutMs: 10000, maxBuffer: 256 * 1024 });
  await new Promise((resolve) => setTimeout(resolve, 1000));
  commands.voiceWakeStatus = await runWindowsDiagnosticExec(sender, opId, "android_hermes_wake_status_pull", adbPath, [
    "exec-out",
    "run-as",
    packageName,
    "cat",
    "files/native-diagnostics/voice-wake.json",
  ], { timeoutMs: 12000, maxBuffer: 4 * 1024 * 1024 });
  let statusPayload = parseJsonDiagnosticText(commands.voiceWakeStatus.stdout || "");
  let statusSource = "run-as";
  let backendStatus = { ok: false };
  if (!statusPayload.schema || /run-as:\s*package not debuggable/i.test(String(commands.voiceWakeStatus.stdout || ""))) {
    backendStatus = await fetchAndroidHermesWakeStatusFromBackend();
    if (backendStatus.ok) {
      statusPayload = backendStatus.payload || {};
      statusSource = "backend-upload";
    }
  }
  const classification = classifyHermesWakeProof(statusPayload);
  const result = {
    ok: classification.ok,
    status: classification.ok ? "hermes_wake_proof_passed" : "hermes_wake_proof_incomplete",
    adbPath,
    devices,
    packageName,
    waitMs,
    statusSource,
    classification,
    backendStatus,
    voiceWakeStatus: sanitizeRendererDiagnosticValue(statusPayload),
    commands: sanitizeRendererDiagnosticValue(commands),
  };
  emitAndroidVoiceTuningStep(sender, opId, "hermes_wake_proof_finished", result, "run_android_hermes_wake_proof");
  writeNativeControlAudit({ action: "android_hermes_wake_proof_finished", opId, result });
  return result;
}

async function runAndroidVoiceTuningRuntimeDebug(sender, opId, payload = {}) {
  if (process.platform !== "win32") return { ok: false, status: "FAIL", error: "windows_native_shell_required" };
  const adbPath = await findWindowsAdbExecutable();
  const connection = await runAndroidConnectionCheck(sender, opId);
  if (connection.status !== "one_authorized_device") {
    return { ok: false, status: connection.status, adbPath, connection, message: connection.instructions };
  }
  return captureAndroidVoiceTuningRuntime(sender, opId, adbPath, {
    clearWebViewData: false,
    clearCache: false,
    ...payload,
  }, "debug_android_voice_tuning_runtime");
}

function normalizeHotOperationModulePath(value = "") {
  const modulePath = String(value || "").replace(/\\/g, "/").trim();
  if (!modulePath || path.isAbsolute(modulePath) || modulePath.includes("\0")) return "";
  const parts = modulePath.split("/").filter(Boolean);
  if (!parts.length || parts.some((part) => part === "." || part === "..")) return "";
  if (path.extname(parts[parts.length - 1]).toLowerCase() !== ".js") return "";
  return parts.join("/");
}

function resolveHotOperationModule(modulePath = "") {
  const safePath = normalizeHotOperationModulePath(modulePath);
  if (!safePath) return { ok: false, error: "hot_operation_missing", message: "Hot operation module path must be a relative .js path." };
  for (const candidate of hotOperationRoots()) {
    const root = path.resolve(candidate.root);
    const resolved = path.resolve(root, safePath);
    const relative = path.relative(root, resolved);
    if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) continue;
    if (fs.existsSync(resolved) && fs.statSync(resolved).isFile()) {
      return { ok: true, modulePath: safePath, path: resolved, root, rootKind: candidate.kind, reload: candidate.reload };
    }
  }
  return { ok: false, error: "hot_operation_missing", modulePath: safePath, roots: hotOperationRoots().map((item) => item.root) };
}

function resolveHotOperation(payload = {}) {
  const operationName = String(payload.operationName || payload.operation || "").trim();
  if (operationName) {
    const manifestOp = scanHotOperationManifests().find((item) => item.name === operationName);
    if (manifestOp) return { ok: true, ...manifestOp, operationName, fromManifest: true };
    if (!payload.modulePath && !payload.moduleId) {
      return { ok: false, error: "hot_operation_missing", operationName, roots: hotOperationRoots().map((item) => item.root) };
    }
  }
  const moduleInfo = resolveHotOperationModule(String(payload.modulePath || payload.moduleId || "").trim());
  if (!moduleInfo.ok) return { ...moduleInfo, operationName };
  return {
    ...moduleInfo,
    operationName,
    loadedFrom: moduleInfo.rootKind,
    hotOpSource: moduleInfo.rootKind,
    hotOpPath: moduleInfo.path,
    bundleId: "",
    capabilities: Array.isArray(payload.capabilities) ? payload.capabilities.map(String) : [],
    timeoutMs: HOT_OPERATION_DEFAULT_TIMEOUT_MS,
    version: String(payload.operationVersion || ""),
    manifestSha256: "",
    sha256: sha256File(moduleInfo.path).toLowerCase(),
    fromManifest: false,
  };
}

function requireHotOperationCapability(granted, capability) {
  if (!granted.has(capability)) {
    const error = new Error(`Hot operation capability denied: ${capability}`);
    error.code = "hot_operation_capability_denied";
    error.capability = capability;
    throw error;
  }
}

function safeFsPathForHotOperation(root, value = "") {
  const target = path.resolve(root, String(value || ""));
  const relative = path.relative(root, target);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    const error = new Error("Hot operation filesystem path outside operation data root.");
    error.code = "hot_operation_capability_denied";
    error.capability = "fs.safe";
    throw error;
  }
  return target;
}

function hotOperationDataRoot(operationName = "") {
  const safeName = String(operationName || "operation").replace(/[^A-Za-z0-9_.-]+/g, "_").slice(0, 80) || "operation";
  const root = path.join(nativeDiagnosticsBundleRoot(), "bridge-ops", safeName);
  fs.mkdirSync(root, { recursive: true });
  return root;
}

function createHotOperationContext(sender, opId, payload = {}, moduleInfo = {}) {
  const capabilities = new Set(Array.isArray(moduleInfo.capabilities) ? moduleInfo.capabilities.map(String) : []);
  const operationName = String(payload.operationName || payload.operation || "");
  const dataRoot = hotOperationDataRoot(operationName);
  const progress = {
    lastPhase: "",
    phases: [],
  };
  const markPhase = (phase, details = {}) => {
    const name = String(phase || "").trim();
    if (!name) return progress.lastPhase;
    const entry = {
      phase: name,
      at: new Date().toISOString(),
      details: sanitizeRendererDiagnosticValue(details || {}),
    };
    progress.lastPhase = name;
    progress.phases.push(entry);
    writeNativeControlAudit({ action: "hot_operation_phase", opId, operation: operationName, ...entry });
    return name;
  };
  const adbDeviceArgs = (deviceId, args = []) => deviceId ? ["-s", String(deviceId), ...args.map(String)] : args.map(String);
  const adbExec = async (capability, step, deviceId, args, options = {}) => {
    requireHotOperationCapability(capabilities, capability);
    const adbPath = await findWindowsAdbExecutable();
    return runWindowsDiagnosticExec(sender, opId, `hot_${step}`, adbPath, adbDeviceArgs(deviceId, args), options);
  };
  return {
    operation: {
      name: operationName,
      version: String(payload.operationVersion || ""),
      modulePath: moduleInfo.modulePath || "",
      moduleFile: moduleInfo.path || "",
      dataRoot,
      capabilities: Array.from(capabilities),
      requiredNativeCapabilities: Array.isArray(moduleInfo.requiredNativeCapabilities) ? moduleInfo.requiredNativeCapabilities.slice() : [],
      bundleId: String(moduleInfo.bundleId || ""),
      bundleSha: String(moduleInfo.sha256 || ""),
      dryRun: Boolean(payload.dryRun || payload.dry_run || (payload.args && (payload.args.dryRun || payload.args.dry_run))),
    },
    progress,
    markPhase,
    dryRun: Boolean(payload.dryRun || payload.dry_run || (payload.args && (payload.args.dryRun || payload.args.dry_run))),
    args: {
      ...Object.fromEntries(Object.entries(payload || {}).filter(([key]) => ![
        "operationName",
        "operation",
        "name",
        "operationVersion",
        "dryRun",
        "dry_run",
        "args",
      ].includes(key))),
      ...(payload.args && typeof payload.args === "object" ? payload.args : {}),
      dryRun: Boolean(payload.dryRun || payload.dry_run || (payload.args && (payload.args.dryRun || payload.args.dry_run))),
    },
    adb: {
      findAuthorizedDevice: async () => {
        requireHotOperationCapability(capabilities, "adb.device");
        const adbPath = await findWindowsAdbExecutable();
        const result = await runAdbDeviceDiscoveryWithRecovery(sender, opId, adbPath, "hot_adb", { recoveryMs: 30_000 });
        return { adbPath, command: result.commands?.devicesInitial || {}, ...result };
      },
      shell: (deviceId, args, options) => adbExec("adb.shell", "adb_shell", deviceId, ["shell", ...args], options),
      install: (deviceId, apkPath, options) => adbExec("adb.install", "adb_install", deviceId, ["install", "-r", String(apkPath || "")], options),
      pull: (deviceId, remotePath, localPath, options) => adbExec("adb.pull", "adb_pull", deviceId, ["pull", String(remotePath || ""), String(localPath || "")], options),
      push: (deviceId, localPath, remotePath, options) => adbExec("adb.push", "adb_push", deviceId, ["push", String(localPath || ""), String(remotePath || "")], options),
      logcat: (deviceId, options = {}) => adbExec("adb.logcat", "adb_logcat", deviceId, ["logcat", "-d", "-v", "time"], { timeoutMs: options.timeoutMs || 20000, maxBuffer: options.maxBuffer || 16 * 1024 * 1024 }),
      launchIntent: (deviceId, intentArgs, options) => adbExec("adb.shell", "adb_launch_intent", deviceId, ["shell", "am", "start", ...intentArgs], options),
    },
    fs: {
      existsSafe: (safePath) => fs.existsSync(safeFsPathForHotOperation(dataRoot, safePath)),
      mkdirSafe: (safePath) => fs.mkdirSync(safeFsPathForHotOperation(dataRoot, safePath), { recursive: true }),
      readJsonSafe: (safePath) => readJsonFile(safeFsPathForHotOperation(dataRoot, safePath), {}),
      readTextSafe: (safePath) => fs.readFileSync(safeFsPathForHotOperation(dataRoot, safePath), "utf8"),
      writeJsonSafe: (safePath, data) => {
        const target = safeFsPathForHotOperation(dataRoot, safePath);
        fs.mkdirSync(path.dirname(target), { recursive: true });
        fs.writeFileSync(target, `${JSON.stringify(data, null, 2)}\n`);
        return target;
      },
      writeTextSafe: (safePath, text) => {
        const target = safeFsPathForHotOperation(dataRoot, safePath);
        fs.mkdirSync(path.dirname(target), { recursive: true });
        fs.writeFileSync(target, String(text || ""));
        return target;
      },
    },
    diagnostics: {
      readLatestNativeDiagnostics: () => {
        requireHotOperationCapability(capabilities, "diagnostics.read");
        return readJsonFile(path.join(nativeDiagnosticsBundleRoot(), "latest.json"), {});
      },
      readLatestServerDiagnostics: () => {
        requireHotOperationCapability(capabilities, "diagnostics.read");
        return fetchAndroidHermesWakeStatusFromBackend();
      },
      uploadResult: async (data) => {
        requireHotOperationCapability(capabilities, "result.upload");
        return uploadNativeDiagnosticsPayload({ source: "hot_operation", operation: operationName, result: data });
      },
      resolveBestVoiceWakeDiagnostics: async () => {
        requireHotOperationCapability(capabilities, "diagnostics.read");
        return resolveBestVoiceWakeDiagnostics(sender, opId, payload.args || {});
      },
    },
    release: {
      readLatestFeed: () => latestAndroidReleaseFeed(payload.args || {}),
      resolveAndroidApk: async () => {
        requireHotOperationCapability(capabilities, "release.android_apk");
        return resolveAndroidVoiceTuningApk(sender, opId, payload.args || {});
      },
    },
    artifacts: {
      writeJson: (name, data) => {
        requireHotOperationCapability(capabilities, "artifact.write");
        const target = safeFsPathForHotOperation(dataRoot, path.join("artifacts", String(name || "artifact.json")));
        fs.mkdirSync(path.dirname(target), { recursive: true });
        fs.writeFileSync(target, `${JSON.stringify(data, null, 2)}\n`);
        return { ok: true, path: target };
      },
      writeText: (name, text) => {
        requireHotOperationCapability(capabilities, "artifact.write");
        const target = safeFsPathForHotOperation(dataRoot, path.join("artifacts", String(name || "artifact.txt")));
        fs.mkdirSync(path.dirname(target), { recursive: true });
        fs.writeFileSync(target, String(text || ""));
        return { ok: true, path: target };
      },
      copyFile: (name, sourcePath) => {
        requireHotOperationCapability(capabilities, "artifact.write");
        const target = safeFsPathForHotOperation(dataRoot, path.join("artifacts", String(name || path.basename(sourcePath || "artifact.bin"))));
        fs.mkdirSync(path.dirname(target), { recursive: true });
        fs.copyFileSync(String(sourcePath || ""), target);
        return { ok: true, path: target };
      },
      attach: (name, metadata) => {
        requireHotOperationCapability(capabilities, "artifact.write");
        return { ok: true, name: String(name || ""), metadata: sanitizeRendererDiagnosticValue(metadata || {}) };
      },
    },
    logger: {
      info: (...items) => writeNativeControlAudit({ action: "hot_operation_log", level: "info", opId, operation: operationName, items: sanitizeRendererDiagnosticValue(items) }),
      warn: (...items) => writeNativeControlAudit({ action: "hot_operation_log", level: "warn", opId, operation: operationName, items: sanitizeRendererDiagnosticValue(items) }),
      error: (...items) => writeNativeControlAudit({ action: "hot_operation_log", level: "error", opId, operation: operationName, items: sanitizeRendererDiagnosticValue(items) }),
    },
  };
}

async function runWithHotOperationTimeout(promise, timeoutMs, progress = {}) {
  let timeout = null;
  const started = Date.now();
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timeout = setTimeout(() => {
          const error = new Error(`Hot operation timed out after ${timeoutMs}ms`);
          error.code = "hot_operation_timeout";
          error.timeoutMs = timeoutMs;
          error.elapsedMs = Date.now() - started;
          error.lastPhase = progress.lastPhase || "";
          error.phases = Array.isArray(progress.phases) ? progress.phases.slice() : [];
          reject(error);
        }, timeoutMs);
        timeout.unref?.();
      }),
    ]);
  } finally {
    if (timeout) clearTimeout(timeout);
  }
}

function hotOperationTimeoutClassification(operationName, lastPhase) {
  if (operationName === "run_android_hermes_wake_proof") {
    const phase = String(lastPhase || "").trim();
    return phase ? `hermes_wake_timeout_after_${phase}` : "hermes_wake_timeout_before_phase";
  }
  return "hot_operation_timeout";
}

async function runHotOperation(sender, opId, payload = {}) {
  const startedAt = new Date();
  const operationName = String(payload.operationName || payload.operation || "").trim();
  let activeModuleInfo = null;
  const finishEnvelope = (fields = {}) => {
    const finishedAt = new Date();
    const kernel = nativeKernelStatus();
    const failureClassification = fields.failureClassification || fields.failure_classification || fields.error || fields.status || null;
    const opName = fields.operation || operationName || activeModuleInfo?.name || "";
    const hotOpSource = fields.hotOpSource || fields.loadedFrom || activeModuleInfo?.hotOpSource || activeModuleInfo?.loadedFrom || activeModuleInfo?.rootKind || "";
    return {
      ok: fields.ok === true,
      stable: fields.stable === true,
      operation: opName,
      source: "hot_operation",
      loadedFrom: fields.loadedFrom || "",
      operationVersion: String(fields.operationVersion || ""),
      hotOpSource,
      hotOpPath: fields.hotOpPath || activeModuleInfo?.hotOpPath || activeModuleInfo?.path || "",
      bundleId: fields.bundleId || activeModuleInfo?.bundleId || "",
      activeDownloadedRuntimeId: kernel.activeDownloadedRuntimeId,
      activeDownloadedRuntimeSha: kernel.activeDownloadedRuntimeSha,
      activeHotOpBundleId: fields.bundleId || activeModuleInfo?.bundleId || kernel.activeHotOpBundleId,
      activeHotOpSha: fields.hotOpSha || fields.sha256 || activeModuleInfo?.sha256 || kernel.activeHotOpSha,
      hotOpSha: fields.hotOpSha || fields.sha256 || activeModuleInfo?.sha256 || "",
      bundledHotOpSha: fields.bundledHotOpSha || bundledHotOperationSha(opName),
      overrideEnabled: localHotOperationOverrideEnabled(),
      manifestTimeoutMs: fields.manifestTimeoutMs ?? activeModuleInfo?.timeoutMs,
      kernel,
      nativeKernel: kernel,
      startedAt: startedAt.toISOString(),
      finishedAt: finishedAt.toISOString(),
      durationMs: finishedAt.getTime() - startedAt.getTime(),
      elapsedMs: fields.elapsedMs ?? (finishedAt.getTime() - startedAt.getTime()),
      timeoutMs: fields.timeoutMs,
      lastPhase: fields.lastPhase || "",
      failureClassification: fields.ok === true ? (fields.failureClassification || null) : failureClassification,
      stages: fields.stages && typeof fields.stages === "object" ? fields.stages : {},
      metrics: fields.metrics && typeof fields.metrics === "object" ? fields.metrics : {},
      artifacts: fields.artifacts && typeof fields.artifacts === "object" ? fields.artifacts : {},
      logsTail: Array.isArray(fields.logsTail) ? fields.logsTail.slice(-80) : [],
      runId: fields.runId || payload.runId || payload.run_id || opId,
      ...fields,
    };
  };
  if (hotOperationsDisabled()) {
    return finishEnvelope({ ok: false, stable: false, status: "hot_operations_disabled", error: "hot_operations_disabled", operation: operationName });
  }
  const moduleInfo = resolveHotOperation(payload);
  activeModuleInfo = moduleInfo.ok ? moduleInfo : null;
  if (!moduleInfo.ok) {
    return finishEnvelope({ ok: false, stable: false, status: moduleInfo.error, error: moduleInfo.error, operation: operationName, roots: moduleInfo.roots || [] });
  }
  const missingNativeCapabilities = (moduleInfo.requiredNativeCapabilities || [])
    .filter((capability) => !WINDOWS_NATIVE_KERNEL_CAPABILITIES.includes(capability));
  if (missingNativeCapabilities.length) {
    return finishEnvelope({
      ok: false,
      stable: false,
      status: "hot_operation_capability_denied",
      error: "hot_operation_capability_denied",
      failureClassification: "native_capability_missing",
      operation: operationName,
      missingNativeCapabilities,
      requiredNativeCapabilities: moduleInfo.requiredNativeCapabilities,
    });
  }
  const expectedSha256 = String(payload.expectedSha256 || payload.expected_sha256 || "").trim().toLowerCase();
  const actualSha256 = moduleInfo.sha256 || sha256File(moduleInfo.path).toLowerCase();
  if (expectedSha256 && actualSha256 !== expectedSha256) {
    return finishEnvelope({ ok: false, stable: false, status: "hot_operation_sha_mismatch", error: "hot_operation_sha_mismatch", operation: operationName, loadedFrom: moduleInfo.loadedFrom || moduleInfo.rootKind, operationVersion: moduleInfo.version || "", modulePath: moduleInfo.modulePath, sha256: actualSha256, expectedSha256 });
  }
  const manifestSha = moduleInfo.manifestSha256 || "";
  if (manifestSha && actualSha256 !== manifestSha) {
    return finishEnvelope({ ok: false, stable: false, status: "hot_operation_sha_mismatch", error: "hot_operation_sha_mismatch", operation: operationName, loadedFrom: moduleInfo.loadedFrom || moduleInfo.rootKind, operationVersion: moduleInfo.version || "", modulePath: moduleInfo.modulePath, sha256: actualSha256, expectedSha256: manifestSha });
  }
  if (hotOperationsRequireSha() && moduleInfo.loadedFrom !== "bundled" && !expectedSha256 && !manifestSha) {
    return finishEnvelope({ ok: false, stable: false, status: "hot_operation_sha_mismatch", error: "hot_operation_sha_mismatch", operation: operationName, loadedFrom: moduleInfo.loadedFrom || moduleInfo.rootKind, operationVersion: moduleInfo.version || "", modulePath: moduleInfo.modulePath, sha256: actualSha256, expectedSha256: "" });
  }
  const requestedTimeout = Number(payload.timeoutMs || payload.timeout_ms || 0);
  const manifestTimeout = Number(moduleInfo.timeoutMs || HOT_OPERATION_DEFAULT_TIMEOUT_MS);
  const timeoutMs = Math.max(1000, Math.min(requestedTimeout > 0 ? Math.min(requestedTimeout, manifestTimeout) : manifestTimeout, 10 * 60 * 1000));
  try {
    if (moduleInfo.reload || hotOperationsDevReloadEnabled()) delete require.cache[require.resolve(moduleInfo.path)];
    const loaded = require(moduleInfo.path);
    const runner = typeof loaded === "function" ? loaded : loaded && loaded.run;
    if (typeof runner !== "function") {
      throw Object.assign(new Error("Hot operation module must export run(context)."), { code: "hot_operation_exception" });
    }
    const context = createHotOperationContext(sender, opId, payload, moduleInfo);
    const result = await runWithHotOperationTimeout(Promise.resolve(runner(context)), timeoutMs, context.progress);
    const rawResult = sanitizeRendererDiagnosticValue(result || {});
    return finishEnvelope({
      ok: rawResult.ok !== false,
      stable: rawResult.stable === true || rawResult.ok === true,
      status: result?.status || "hot_operation_finished",
      operation: operationName || moduleInfo.name || "",
      loadedFrom: moduleInfo.loadedFrom || moduleInfo.rootKind,
      hotOpSource: moduleInfo.hotOpSource || moduleInfo.loadedFrom || moduleInfo.rootKind,
      hotOpPath: moduleInfo.hotOpPath || moduleInfo.path,
      bundleId: moduleInfo.bundleId || "",
      operationVersion: String(moduleInfo.version || payload.operationVersion || ""),
      modulePath: moduleInfo.modulePath,
      moduleRoot: moduleInfo.loadedFrom || moduleInfo.rootKind,
      sha256: actualSha256,
      hotOpSha: actualSha256,
      bundledHotOpSha: bundledHotOperationSha(operationName || moduleInfo.name || ""),
      overrideEnabled: localHotOperationOverrideEnabled(),
      manifestTimeoutMs: manifestTimeout,
      timeoutMs,
      elapsedMs: Date.now() - startedAt.getTime(),
      lastPhase: rawResult.lastPhase || context.progress.lastPhase || "",
      phaseHistory: rawResult.phaseHistory || context.progress.phases || [],
      stages: rawResult.stages || {},
      metrics: rawResult.metrics || rawResult.confidence || {},
      artifacts: rawResult.artifacts || {},
      failureClassification: rawResult.failureClassification || rawResult.failure_classification || (rawResult.ok === false ? rawResult.status : null),
      rawResult,
      result: rawResult,
    });
  } catch (error) {
    const code = error && error.code ? String(error.code) : "hot_operation_exception";
    const lastPhase = error?.lastPhase || "";
    const failureClassification = code === "hot_operation_timeout"
      ? hotOperationTimeoutClassification(operationName, lastPhase)
      : code;
    return finishEnvelope({
      ok: false,
      stable: false,
      status: code,
      error: code,
      failureClassification,
      operation: operationName,
      loadedFrom: moduleInfo.loadedFrom || moduleInfo.rootKind,
      hotOpSource: moduleInfo.hotOpSource || moduleInfo.loadedFrom || moduleInfo.rootKind,
      hotOpPath: moduleInfo.hotOpPath || moduleInfo.path,
      bundleId: moduleInfo.bundleId || "",
      operationVersion: String(moduleInfo.version || payload.operationVersion || ""),
      modulePath: moduleInfo.modulePath,
      message: String(error && error.message ? error.message : error),
      timeoutMs: error?.timeoutMs || timeoutMs,
      elapsedMs: error?.elapsedMs || (Date.now() - startedAt.getTime()),
      lastPhase,
      phaseHistory: Array.isArray(error?.phases) ? sanitizeRendererDiagnosticValue(error.phases) : [],
      capability: error?.capability || "",
      logsTail: verboseBridgeLogsEnabled() ? [String(error && error.stack ? error.stack : error), ...recentBridgeLogsTail(20)] : recentBridgeLogsTail(20),
    });
  }
}

async function runShellSelfTest(sender, opId, payload = {}) {
  const startedAt = new Date();
  const checks = {};
  let failureClassification = null;
  const includeDeepProbes = payload.includeDeepProbes === true || payload.include_deep_probes === true;
  const includeAdbDiscovery = payload.includeAdbDiscovery === true
    || payload.include_adb_discovery === true
    || payload.requireAuthorizedAndroid === true
    || payload.require_authorized_android === true;
  const requireAuthorizedAndroid = payload.requireAuthorizedAndroid === true
    || payload.require_authorized_android === true;
  const setCheck = (name, value, failure = name) => {
    checks[name] = Boolean(value);
    if (!checks[name] && !failureClassification) failureClassification = failure;
  };
  const summary = hotOperationsSummary();
  setCheck("local_bridge_alive", true);
  setCheck("native_kernel_contract_advertised", nativeKernelStatus().kernelContractVersion === NATIVE_KERNEL_CONTRACT_VERSION);
  setCheck("downloaded_runtime_status_exposed", downloadedRuntimeSummary().supported === true);
  setCheck("runtime_sync_compares_bundle_sha", typeof downloadedRuntimeMetadataDiffers === "function");
  setCheck("runtime_rollback_available", typeof rollbackDownloadedRuntimeToLastKnownGood === "function");
  setCheck("hot_ops_root_resolved", Boolean(summary.hotOpsRoot));
  setCheck("active_or_bundled_root_readable", summary.hotOpsRoots.some((item) => (item.active || item.kind === "bundled") && item.exists));
  setCheck("bundled_op_root_readable", summary.hotOpsRoots.some((item) => item.kind === "bundled" && item.exists));
  const listed = listHotOperations();
  setCheck("manifest_scan_works", Array.isArray(listed.availableHotOps));
  setCheck("loader_rejects_traversal", !normalizeHotOperationModulePath("../x.js"));
  setCheck("loader_rejects_absolute_path", !normalizeHotOperationModulePath(path.resolve(os.tmpdir(), "x.js")));
  const missing = resolveHotOperation({ operationName: "self_test_missing_hot_operation" });
  setCheck("missing_op_returns_hot_operation_missing", missing.error === "hot_operation_missing");
  checks.deep_hot_operation_probes_skipped = !includeDeepProbes;
  if (includeDeepProbes) {
    const mismatch = await runHotOperation(sender, `${opId}-sha`, {
      operationName: "run_android_hermes_wake_proof",
      expectedSha256: "0".repeat(64),
      timeoutMs: 1000,
    });
    setCheck("sha_mismatch_returns_hot_operation_sha_mismatch", mismatch.error === "hot_operation_sha_mismatch");
    try {
      const context = createHotOperationContext(sender, `${opId}-cap`, {
        operationName: "run_shell_self_test_capability_probe",
        args: {},
      }, { capabilities: [] });
      await context.adb.logcat("", { timeoutMs: 1 });
      setCheck("denied_capability_returns_hot_operation_capability_denied", false, "hot_operation_capability_denied");
    } catch (error) {
      setCheck("denied_capability_returns_hot_operation_capability_denied", error?.code === "hot_operation_capability_denied", "hot_operation_capability_denied");
    }
  } else {
    setCheck("sha_mismatch_probe_available", typeof runHotOperation === "function");
    setCheck("capability_guard_available", typeof createHotOperationContext === "function");
  }
  const adbPath = await findWindowsAdbExecutable();
  setCheck("adb_discoverable", Boolean(adbPath));
  let authorized = false;
  let adbDiscovery = { ok: Boolean(adbPath), status: adbPath ? "skipped" : "adb_missing", skipped: true, adbPath: adbPath || "" };
  if (adbPath && includeAdbDiscovery) {
    const recoveryMs = Math.max(0, Math.min(Number(payload.adbRecoveryMs || payload.adb_recovery_ms || 5000), 30_000));
    adbDiscovery = await runAdbDeviceDiscoveryWithRecovery(sender, opId, adbPath, "shell_self_test", { recoveryMs });
    authorized = adbDiscovery.status === "one_authorized_device";
  }
  setCheck("authorized_android_device_present", includeAdbDiscovery ? authorized : true, requireAuthorizedAndroid ? (adbDiscovery?.status || "no_device") : "authorized_android_device_present");
  checks.authorized_android_device_present_skipped = !includeAdbDiscovery;
  const localMode = !selectedBackendOrigin || isLocalDevCandidateUrl(selectedBackendOrigin);
  checks.result_upload_path_works_or_skipped = localMode ? true : Boolean(selectedBackendOrigin);
  const finishedAt = new Date();
  const ok = Object.entries(checks)
    .every(([, passed]) => passed === true);
  return {
    ok,
    stable: ok,
    operation: "run_shell_self_test",
    source: "shell",
    startedAt: startedAt.toISOString(),
    finishedAt: finishedAt.toISOString(),
    durationMs: finishedAt.getTime() - startedAt.getTime(),
    checks,
    adbDiscovery,
    androidDiscoveryStatus: adbDiscovery?.status || (adbPath ? "adb_timeout" : "adb_missing"),
    failureClassification: ok ? null : failureClassification,
    nextAction: ok ? "Run the canary hot operation, then Hermes wake proof." : "Inspect hot ops root, bridge protocol, ADB, or capability failures before running Hermes.",
    hotOperations: listed,
    logsTail: recentBridgeLogsTail(),
  };
}

function runShellSelfTestSnapshot() {
  const now = new Date().toISOString();
  return {
    ok: true,
    stable: true,
    operation: "run_shell_self_test",
    source: "shell",
    mode: "constant_native_control_roundtrip",
    startedAt: now,
    finishedAt: now,
    durationMs: 0,
    checks: { native_control_roundtrip: true },
    adbDiscovery: { ok: true, status: "skipped", skipped: true },
    androidDiscoveryStatus: "skipped",
    failureClassification: null,
    nextAction: "Run the canary hot operation, then Hermes wake proof.",
    hotOperations: { skipped: true },
    logsTail: [],
  };
}

function androidVoiceTuningIterationReport(iteration = {}) {
  const classification = iteration.classification || {};
  const timing = iteration.timing || {};
  return {
    iteration: iteration.iteration,
    apk_build_id_installed: classification.apk_build_id || iteration.apkBuildId || "",
    web_build_id_loaded: classification.web_build_id || iteration.webBuildId || "",
    bridge_status: classification.bridge_status || "",
    permission_state: classification.permission_state || "",
    lag_timing: timing,
    failure_classification: classification.failure_classification || "",
    patch_applied: iteration.patchApplied || "none",
    next_run_safe: Boolean(classification.next_run_safe),
    artifact_paths: iteration.artifactPaths || {},
  };
}

async function runAndroidVoiceTuningGoalLoop(sender, opId, payload = {}) {
  if (process.platform !== "win32") return { ok: false, status: "FAIL", error: "windows_native_shell_required" };
  const maxIterations = Math.max(1, Math.min(Number(payload.maxIterations || payload.max_iterations || 3), 5));
  const packageName = String(payload.packageName || payload.package_name || "com.colmeio.wasmagent");
  const adbPath = await findWindowsAdbExecutable();
  const iterations = [];
  let stopReason = "";
  let crashOrAnrCount = 0;
  emitAndroidVoiceTuningStep(sender, opId, "goal_loop_started", {
    maxIterations,
    packageName,
    safety: {
      autoRecord: false,
      autoPermissionClick: false,
      collectVoiceSamples: false,
    },
  }, "run_android_voice_tuning_goal_loop");

  for (let index = 1; index <= maxIterations; index += 1) {
    emitAndroidVoiceTuningStep(sender, opId, "goal_iteration_started", { iteration: index }, "run_android_voice_tuning_goal_loop");
    const connection = await runAndroidConnectionCheck(sender, opId);
    if (connection.status !== "one_authorized_device") {
      stopReason = connection.status === "multiple_devices" ? "hard_stop_multiple_android_devices" : connection.status;
      const blocked = {
        iteration: index,
        ok: false,
        status: stopReason,
        connection,
        classification: {
          stable: false,
          failure_classification: stopReason,
          failures: [stopReason],
          next_run_safe: false,
        },
        patchApplied: "none",
      };
      iterations.push(blocked);
      emitAndroidVoiceTuningStep(sender, opId, "goal_iteration_blocked", androidVoiceTuningIterationReport(blocked), "run_android_voice_tuning_goal_loop");
      break;
    }

    const apk = await resolveAndroidVoiceTuningApk(sender, opId, {
      ...payload,
      packageName,
      progressOperation: "run_android_voice_tuning_goal_loop",
    });
    if (!apk.ok) {
      stopReason = apk.error || "apk_resolution_failed";
      const blocked = {
        iteration: index,
        ok: false,
        status: stopReason,
        apk,
        classification: {
          stable: false,
          failure_classification: stopReason,
          failures: [stopReason],
          next_run_safe: false,
        },
        patchApplied: "none",
      };
      iterations.push(blocked);
      emitAndroidVoiceTuningStep(sender, opId, "goal_iteration_blocked", androidVoiceTuningIterationReport(blocked), "run_android_voice_tuning_goal_loop");
      break;
    }

    const install = await runWindowsDiagnosticExec(sender, opId, "android_voice_goal_install", adbPath, ["install", "-r", apk.path], { timeoutMs: 180_000, maxBuffer: 2 * 1024 * 1024 });
    emitAndroidVoiceTuningStep(sender, opId, "goal_apk_installed", {
      iteration: index,
      ok: install.ok,
      apkPath: apk.path,
      buildId: apk.buildId || "",
      sha256: apk.sha256 || "",
      sizeBytes: apk.sizeBytes || 0,
    }, "run_android_voice_tuning_goal_loop");
    if (!install.ok) {
      stopReason = "install_failed";
      const blocked = {
        iteration: index,
        ok: false,
        status: stopReason,
        apk,
        install,
        classification: {
          stable: false,
          failure_classification: stopReason,
          failures: [stopReason],
          next_run_safe: false,
        },
        patchApplied: "none",
      };
      iterations.push(blocked);
      emitAndroidVoiceTuningStep(sender, opId, "goal_iteration_blocked", androidVoiceTuningIterationReport(blocked), "run_android_voice_tuning_goal_loop");
      break;
    }

    const runtime = await captureAndroidVoiceTuningRuntime(sender, opId, adbPath, {
      ...payload,
      packageName,
      clearWebViewData: Boolean(payload.debugProofRun || payload.debug_proof_run || payload.clearWebViewData || payload.clear_webview_data),
      clearCache: false,
      expectedApk: apk,
      waitMs: payload.waitMs || payload.wait_ms || 10000,
    }, "run_android_voice_tuning_goal_loop");
    runtime.iteration = index;
    runtime.apk = apk;
    runtime.install = sanitizeRendererDiagnosticValue(install);
    runtime.patchApplied = "renderer/native lazy status guard in current source; runtime loop applied no on-device patch";
    runtime.classification = classifyAndroidVoiceTuningRuntime(runtime, apk);
    iterations.push(runtime);
    const report = androidVoiceTuningIterationReport(runtime);
    emitAndroidVoiceTuningStep(sender, opId, "goal_iteration_report", report, "run_android_voice_tuning_goal_loop");

    if (runtime.recordingStartedAutomatically) {
      stopReason = "hard_stop_recording_started_automatically";
      break;
    }
    if (runtime.permissionPrompt?.unrelated) {
      stopReason = "hard_stop_unrelated_permission_prompt";
      break;
    }
    if (runtime.classification.failures.includes("app_crash") || runtime.classification.failures.includes("ui_thread_lag_anr_risk")) {
      crashOrAnrCount += 1;
      if (crashOrAnrCount >= 2) {
        stopReason = "hard_stop_repeated_crash_or_anr";
        break;
      }
    }
    if (runtime.classification.stable) {
      stopReason = "stable";
      break;
    }
    if (!runtime.classification.next_run_safe) {
      stopReason = runtime.classification.failure_classification || "unsafe_next_run";
      break;
    }
  }

  const latest = iterations[iterations.length - 1] || {};
  const latestClassification = latest.classification || {};
  const result = {
    ok: stopReason === "stable" || latestClassification.stable === true,
    status: stopReason || latestClassification.failure_classification || "max_iterations_reached",
    opId,
    adbPath,
    packageName,
    iterations: iterations.map((iteration) => ({
      ...androidVoiceTuningIterationReport(iteration),
      failures: iteration.classification?.failures || [],
      proofPath: iteration.proofPath || "",
    })),
    latest: androidVoiceTuningIterationReport(latest),
    latestProofPath: latest.proofPath || "",
    safety: {
      recording_started_automatically: iterations.some((iteration) => iteration.recordingStartedAutomatically),
      permission_prompt_auto_clicked: false,
      voice_samples_collected: false,
    },
  };
  emitAndroidVoiceTuningStep(sender, opId, "goal_loop_finished", result, "run_android_voice_tuning_goal_loop");
  writeNativeControlAudit({ action: "android_voice_tuning_goal_loop_finished", opId, result });
  return result;
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
  const opName = typeof operation === "object" ? String(operation.operation || operation.type || "") : String(operation || "");
  const payload = operation && typeof operation === "object" ? operation.payload || {} : {};
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
  if (opName === "check_android_connection") {
    return runAndroidConnectionCheck(event.sender, opId);
  }
  if (opName === "get_native_kernel_status") {
    await ensureDownloadedRuntimeFromFeed(payload);
    await ensureDownloadedHotOperationsFromFeed(payload);
    return { ok: true, operation: opName, kernel: nativeKernelStatus(), logsTail: recentBridgeLogsTail() };
  }
  if (opName === "refresh_downloaded_runtime" || opName === "sync_downloaded_runtime") {
    const downloadedRuntimeSync = await ensureDownloadedRuntimeFromFeed({ ...payload, forceSync: true });
    return { ok: downloadedRuntimeSync.ok === true, operation: opName, downloadedRuntimeSync, downloadedRuntime: downloadedRuntimeSummary(), logsTail: recentBridgeLogsTail() };
  }
  if (opName === "rollback_downloaded_runtime") {
    const result = rollbackDownloadedRuntimeToLastKnownGood();
    return { ...result, logsTail: recentBridgeLogsTail() };
  }
  if (opName === "run_hot_operation") {
    await ensureDownloadedRuntimeFromFeed(payload);
    await ensureDownloadedHotOperationsFromFeed(payload);
    return runHotOperation(event.sender, opId, payload);
  }
  if (opName === "list_hot_operations") {
    await ensureDownloadedRuntimeFromFeed(payload);
    await ensureDownloadedHotOperationsFromFeed(payload);
    return listHotOperations();
  }
  if (opName === "refresh_downloaded_hot_ops" || opName === "sync_downloaded_hot_ops") {
    const downloadedHotOpsSync = await ensureDownloadedHotOperationsFromFeed({ ...payload, forceSync: true });
    return { ok: downloadedHotOpsSync.ok === true, operation: opName, downloadedHotOpsSync, logsTail: recentBridgeLogsTail() };
  }
  if (opName === "run_shell_self_test") {
    await ensureDownloadedRuntimeFromFeed(payload);
    await ensureDownloadedHotOperationsFromFeed(payload);
    return runShellSelfTest(event.sender, opId, payload);
  }
  if (opName === "debug_android_voice_tuning_runtime") {
    return runAndroidVoiceTuningRuntimeDebug(event.sender, opId, payload);
  }
  if (opName === "export_hermes_wake_dataset") {
    return exportHermesWakeDataset(event.sender, opId, payload);
  }
  if (opName === "run_android_hermes_wake_proof") {
    return runAndroidHermesWakeProof(event.sender, opId, payload);
  }
  if (opName === "play_audio_stimulus") {
    return playWindowsAudioStimulus(payload);
  }
  if (opName === "prove_android_voice_tuning") {
    return runAndroidVoiceTuningProof(event.sender, opId, payload);
  }
  if (opName === "run_android_voice_tuning_goal_loop") {
    return runAndroidVoiceTuningGoalLoop(event.sender, opId, payload);
  }
  if (opName === "verify_android_oauth") {
    return runWindowsAndroidOAuthVerification(event.sender, opId);
  }
  if (opName === "request_windows_client_update") {
    return runWindowsSelfUpdate(event.sender, opId, { ...payload, applyApproved: Boolean(payload.applyApproved) });
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
    nativeKernel: nativeKernelStatus(),
    downloadedRuntime: downloadedRuntimeSummary(),
    hotOperations: {
      supported: true,
      protocol: HOT_OPERATION_PROTOCOL_VERSION,
      roots: hotOperationRoots().map((item) => ({ kind: item.kind, root: item.root, reload: item.reload })),
      bundledRoot: bundledHotOperationsRoot(),
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
      nativeKernel: nativeKernelStatus(),
      downloadedRuntime: downloadedRuntimeSummary(),
      hotOperations: hotOperationsSummary(),
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

function waoEncodeValue(value) {
  if (value === null || typeof value === "undefined") return { type: WAO_TLV_NULL, payload: Buffer.alloc(0) };
  if (typeof value === "boolean") return { type: WAO_TLV_BOOL, payload: Buffer.from([value ? 1 : 0]) };
  if (Number.isInteger(value)) {
    const payload = Buffer.alloc(8);
    payload.writeBigInt64LE(BigInt(value), 0);
    return { type: WAO_TLV_I64, payload };
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    const payload = Buffer.alloc(8);
    payload.writeDoubleLE(value, 0);
    return { type: WAO_TLV_F64, payload };
  }
  if (Buffer.isBuffer(value)) return { type: WAO_TLV_BYTES, payload: value };
  if (value instanceof ArrayBuffer) return { type: WAO_TLV_BYTES, payload: Buffer.from(value) };
  if (ArrayBuffer.isView(value)) return { type: WAO_TLV_BYTES, payload: Buffer.from(value.buffer, value.byteOffset, value.byteLength) };
  if (typeof value === "object") return { type: WAO_TLV_JSON, payload: Buffer.from(JSON.stringify(value), "utf8") };
  return { type: WAO_TLV_UTF8, payload: Buffer.from(String(value), "utf8") };
}

function waoDecodeValue(type, payload) {
  if (type === WAO_TLV_NULL) return null;
  if (type === WAO_TLV_BOOL) return Boolean(payload && payload[0]);
  if (type === WAO_TLV_I64 && payload.length === 8) {
    const value = payload.readBigInt64LE(0);
    return value <= BigInt(Number.MAX_SAFE_INTEGER) && value >= BigInt(Number.MIN_SAFE_INTEGER) ? Number(value) : value.toString();
  }
  if (type === WAO_TLV_F64 && payload.length === 8) return payload.readDoubleLE(0);
  if (type === WAO_TLV_BYTES) return payload;
  if (type === WAO_TLV_JSON) {
    try {
      return JSON.parse(payload.toString("utf8"));
    } catch {
      return {};
    }
  }
  if (type === WAO_TLV_UTF8) return payload.toString("utf8");
  return payload;
}

function waoEncodeTlv(fields = {}) {
  const chunks = [];
  for (const [name, value] of Object.entries(fields || {})) {
    const fieldId = WAO_FIELD_IDS[name];
    if (!fieldId) continue;
    const encoded = waoEncodeValue(value);
    const header = Buffer.alloc(WAO_TLV_HEADER_BYTES);
    header.writeUInt16LE(fieldId, 0);
    header.writeUInt8(encoded.type, 2);
    header.writeUInt8(0, 3);
    header.writeUInt32LE(encoded.payload.length, 4);
    chunks.push(header, encoded.payload);
  }
  return Buffer.concat(chunks);
}

function waoDecodeTlv(payload) {
  const buffer = Buffer.isBuffer(payload) ? payload : Buffer.from(payload || []);
  const fields = {};
  let offset = 0;
  while (offset + WAO_TLV_HEADER_BYTES <= buffer.length) {
    const fieldId = buffer.readUInt16LE(offset);
    const type = buffer.readUInt8(offset + 2);
    const length = buffer.readUInt32LE(offset + 4);
    offset += WAO_TLV_HEADER_BYTES;
    if (offset + length > buffer.length) break;
    fields[WAO_FIELD_NAMES[fieldId] || `field_${fieldId}`] = waoDecodeValue(type, buffer.subarray(offset, offset + length));
    offset += length;
  }
  return fields;
}

function waoEncodeFrame(typeName, fields = {}, options = {}) {
  const body = waoEncodeTlv(fields);
  const header = Buffer.alloc(WAO_HEADER_BYTES);
  header.write("WAO1", 0, 4, "ascii");
  header.writeUInt8(WAO_VERSION, 4);
  header.writeUInt8(WAO_FRAME_TYPES[String(typeName || "EVENT").toUpperCase()] || WAO_FRAME_TYPES.EVENT, 5);
  header.writeUInt16LE(Number(options.schemaId || options.schema_id || 0), 6);
  header.writeUInt32LE(Number(options.flags || 0), 8);
  header.writeUInt32LE(Number(options.session || 0), 12);
  header.writeBigUInt64LE(BigInt(options.seq || nativeObsSeq++), 16);
  header.writeBigUInt64LE(BigInt(options.ack || 0), 24);
  header.writeBigUInt64LE(BigInt(Math.max(0, Math.round(performance.now()))), 32);
  return Buffer.concat([header, body]);
}

function waoDecodeFrame(data) {
  const buffer = Buffer.isBuffer(data) ? data : Buffer.from(data || []);
  if (buffer.length < WAO_HEADER_BYTES) throw new Error("wao_frame_too_short");
  if (buffer.subarray(0, 4).toString("ascii") !== "WAO1") throw new Error("wao_bad_magic");
  const version = buffer.readUInt8(4);
  if (version !== WAO_VERSION) throw new Error("wao_bad_version");
  const typeId = buffer.readUInt8(5);
  const seq = buffer.readBigUInt64LE(16);
  const ack = buffer.readBigUInt64LE(24);
  return {
    version,
    type_id: typeId,
    type: WAO_FRAME_TYPE_NAMES[typeId] || `UNKNOWN_${typeId}`,
    schema_id: buffer.readUInt16LE(6),
    flags: buffer.readUInt32LE(8),
    session: buffer.readUInt32LE(12),
    seq: seq <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(seq) : seq.toString(),
    ack: ack <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(ack) : ack.toString(),
    monotonic_ms: Number(buffer.readBigUInt64LE(32)),
    fields: waoDecodeTlv(buffer.subarray(WAO_HEADER_BYTES)),
  };
}

function nativeObsCanUseSocket() {
  return typeof WebSocket === "function";
}

function nativeObsSocketUrl() {
  const config = ensureConfig();
  const url = new URL("/native/obs/v1", selectedBackendOrigin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("device_id", config.deviceId);
  url.searchParams.set("role", "windows-native");
  url.searchParams.set("topics", "commands,bridge,errors,windows.native");
  return url.toString();
}

function nativeObsSend(typeName, fields = {}, options = {}) {
  if (!nativeObsSocket || nativeObsSocket.readyState !== WebSocket.OPEN) return false;
  try {
    nativeObsSocket.send(waoEncodeFrame(typeName, fields, options));
    return true;
  } catch (error) {
    writeNativeControlAudit({ action: "native_obs_send_failed", type: typeName, error: String(error && error.message ? error.message : error) });
    return false;
  }
}

function nativeObsSendHeartbeat() {
  const config = ensureConfig();
  const kernel = nativeKernelStatus();
  nativeObsSend("HEARTBEAT", {
    device_id: config.deviceId,
    build_id: String(config.buildId || ""),
    app_version: app.getVersion(),
    route: currentRendererUrl(),
    runtime: "electron",
    ts_ms: Date.now(),
    payload_json: {
      platform: "windows",
      activeNativeCommandCount,
      nativeKernelVersion: NATIVE_KERNEL_CONTRACT_VERSION,
      downloadedRuntime: kernel.downloadedRuntime,
      activeDownloadedRuntimeId: kernel.activeDownloadedRuntimeId,
      activeHotOpBundleId: kernel.activeHotOpBundleId,
    },
  });
}

async function executeNativeObsCommand(fields = {}, frame = {}) {
  const config = ensureConfig();
  const command = {
    id: String(fields.command_id || ""),
    type: String(fields.op || fields.type || ""),
    payload: fields.payload_json && typeof fields.payload_json === "object" ? fields.payload_json : {},
    reason: String(fields.reason || "wao"),
  };
  if (!command.id) return;
  nativeObsSend("COMMAND_ACK", {
    device_id: config.deviceId,
    command_id: command.id,
    op: command.type,
    status: "accepted",
    ts_ms: Date.now(),
  }, { ack: frame.seq || 0 });
  const started = performance.now();
  let result = {};
  try {
    result = await executeNativeControlCommandWithWatchdog(command);
  } catch (error) {
    result = { ok: false, error: String(error && error.message ? error.message : error), failureClassification: "handler_threw" };
  }
  nativeObsSend("COMMAND_ACK", {
    device_id: config.deviceId,
    command_id: command.id,
    op: command.type,
    status: "finished",
    latency_ms: Math.max(0, Math.round(performance.now() - started)),
    result_json: {
      ...result,
      reason: "wao",
      executedAt: new Date().toISOString(),
    },
  }, { ack: frame.seq || 0 });
  writeNativeControlAudit({ action: "native_obs_command_result_sent", id: command.id, type: command.type, ok: Boolean(result && result.ok) });
}

function handleNativeObsFrame(frame = {}) {
  const fields = frame.fields && typeof frame.fields === "object" ? frame.fields : {};
  if (frame.type === "COMMAND") {
    void executeNativeObsCommand(fields, frame);
    return;
  }
  if (frame.type === "ERROR") {
    writeNativeControlAudit({ action: "native_obs_error", status: fields.status || "", reason: fields.reason || "" });
  }
}

function scheduleNativeObsReconnect(reason = "closed") {
  if (nativeObsReconnectTimer || !selectedBackendOrigin || !nativeObsCanUseSocket()) return;
  nativeObsReconnectTimer = setTimeout(() => {
    nativeObsReconnectTimer = null;
    startNativeObservabilitySocket(reason);
  }, NATIVE_OBS_RECONNECT_MS);
  nativeObsReconnectTimer.unref();
}

function startNativeObservabilitySocket(reason = "startup") {
  if (!selectedBackendOrigin || !nativeObsCanUseSocket()) return false;
  if (nativeObsSocket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(nativeObsSocket.readyState)) return true;
  const config = ensureConfig();
  try {
    nativeObsSocket = new WebSocket(nativeObsSocketUrl());
    nativeObsSocket.binaryType = "arraybuffer";
  } catch (error) {
    writeNativeControlAudit({ action: "native_obs_connect_failed", reason, error: String(error && error.message ? error.message : error) });
    scheduleNativeObsReconnect("connect_failed");
    return false;
  }
  nativeObsSocket.addEventListener("open", () => {
    nativeObsConnected = true;
    writeNativeControlAudit({ action: "native_obs_socket_open", reason, backend: selectedBackendOrigin });
    nativeObsSend("HELLO", {
      device_id: config.deviceId,
      role: "windows-native",
      topics: ["commands", "bridge", "errors", "windows.native"],
      build_id: String(config.buildId || ""),
      app_version: app.getVersion(),
      route: currentRendererUrl(),
      runtime: "electron",
      payload_json: {
        platform: "windows",
        capabilities: WINDOWS_NATIVE_KERNEL_CAPABILITIES,
        nativeKernelVersion: NATIVE_KERNEL_CONTRACT_VERSION,
      },
    });
    nativeObsSendHeartbeat();
    if (nativeObsHeartbeatTimer) clearInterval(nativeObsHeartbeatTimer);
    nativeObsHeartbeatTimer = setInterval(nativeObsSendHeartbeat, NATIVE_OBS_HEARTBEAT_INTERVAL_MS);
    nativeObsHeartbeatTimer.unref();
  });
  nativeObsSocket.addEventListener("message", (event) => {
    try {
      const frame = typeof event.data === "string" ? { type: "EVENT", fields: JSON.parse(event.data) } : waoDecodeFrame(event.data);
      handleNativeObsFrame(frame);
    } catch (error) {
      writeNativeControlAudit({ action: "native_obs_decode_failed", error: String(error && error.message ? error.message : error) });
    }
  });
  nativeObsSocket.addEventListener("close", () => {
    nativeObsConnected = false;
    if (nativeObsHeartbeatTimer) clearInterval(nativeObsHeartbeatTimer);
    nativeObsHeartbeatTimer = null;
    scheduleNativeObsReconnect("closed");
  });
  nativeObsSocket.addEventListener("error", () => {
    nativeObsConnected = false;
  });
  return true;
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
  nativeObsSend("EVENT", {
    device_id: config.deviceId,
    stream: "windows.native",
    type: kind,
    key: `windows.native.${kind}`,
    ts_ms: Date.now(),
    payload_json: body,
  });
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

function nativeControlCommandTimeoutMs(command = {}) {
  const payload = command && typeof command.payload === "object" ? command.payload : {};
  const requested = Number(payload.nativeControlTimeoutMs || payload.native_control_timeout_ms || payload.commandTimeoutMs || payload.command_timeout_ms || 0);
  if (Number.isFinite(requested) && requested > 0) {
    return Math.max(1000, Math.min(requested, NATIVE_CONTROL_MAX_TIMEOUT_MS));
  }
  const type = String(command.type || "");
  if (type === "run_hot_operation") {
    const hotOpRequested = Number(payload.timeoutMs || payload.timeout_ms || payload.args?.timeoutMs || payload.args?.timeout_ms || 0);
    if (Number.isFinite(hotOpRequested) && hotOpRequested > 0) {
      return Math.max(1000, Math.min(hotOpRequested + 15_000, NATIVE_CONTROL_MAX_TIMEOUT_MS));
    }
    return 75_000;
  }
  if (type === "run_shell_self_test") return 10_000;
  return NATIVE_CONTROL_DEFAULT_TIMEOUT_MS;
}

function nativeControlTimeoutResult(command = {}, timeoutMs = NATIVE_CONTROL_DEFAULT_TIMEOUT_MS, startedAt = new Date().toISOString()) {
  const type = String(command.type || "unknown");
  return {
    ok: false,
    operation: type,
    error: "handler_timeout",
    failureClassification: "handler_timeout",
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    timedOut: true,
    timeoutMs,
    message: `Native-control handler timed out after ${timeoutMs}ms.`,
    logsTail: recentBridgeLogsTail(),
  };
}

function nativeControlConstantSelfTestResult() {
  const config = ensureConfig();
  return {
    ok: true,
    operation: "run_shell_self_test",
    mode: "constant_self_test",
    source: "shell",
    buildId: String(config.buildId || ""),
    clientId: String(config.deviceId || ""),
    ts: Date.now(),
  };
}

function isRunShellSelfTestNativeControlCommand(command = {}) {
  const candidates = [
    command.type,
    command.name,
    command.command,
    command.operation,
    command.operationName,
    command.operation_name,
    command.payload?.type,
    command.payload?.name,
    command.payload?.command,
    command.payload?.operation,
    command.payload?.operationName,
    command.payload?.operation_name,
  ];
  return candidates.some((value) => String(value || "") === "run_shell_self_test");
}

async function executeNativeControlCommandWithWatchdog(command = {}) {
  const timeoutMs = nativeControlCommandTimeoutMs(command);
  const startedAt = new Date().toISOString();
  let timeoutHandle = null;
  let timedOut = false;
  const handlerPromise = executeNativeControlCommand(command);
  handlerPromise.catch((error) => {
    if (timedOut) {
      writeNativeControlAudit({
        action: "command_late_rejection_after_timeout",
        id: command.id || "",
        type: command.type || "",
        error: String(error && error.message ? error.message : error),
      });
    }
  });
  const timeoutPromise = new Promise((resolve) => {
    timeoutHandle = setTimeout(() => {
      timedOut = true;
      const result = nativeControlTimeoutResult(command, timeoutMs, startedAt);
      writeNativeControlAudit({ action: "command_timeout", id: command.id || "", type: command.type || "", timeoutMs, result });
      resolve(result);
    }, timeoutMs);
    timeoutHandle.unref();
  });
  const result = await Promise.race([handlerPromise, timeoutPromise]);
  if (timeoutHandle) clearTimeout(timeoutHandle);
  return result && typeof result === "object" ? result : { ok: false, error: "result_seen_wrong_shape", failureClassification: "result_seen_wrong_shape", rawResult: result };
}

async function executeNativeControlCommand(command = {}) {
  const type = String(command.type || "");
  const payload = command && typeof command.payload === "object" ? command.payload : {};
  const win = currentNativeWindow();
  activeNativeCommandCount += 1;
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
  try {
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
      adbDiagnostics: {
        schema: adbBundle.payload.schema,
        generated_at: adbBundle.payload.generated_at,
        reason: adbBundle.payload.reason,
        adbPath: adbBundle.payload.adbPath,
        hasDevice: Boolean(adbBundle.payload.hasDevice),
        commandStatus: Object.fromEntries(Object.entries(adbBundle.payload.commands || {}).map(([name, value]) => [name, {
          ok: value?.ok === true,
          exitCode: value?.exitCode ?? null,
          timedOut: value?.timedOut === true,
          elapsedMs: value?.elapsedMs ?? null,
          error: value?.error || "",
        }])),
        filtered: {
          crashLogcat: clipDiagnosticText(adbBundle.payload.filtered?.crashLogcat || "", 80_000),
          logcat: clipDiagnosticText(adbBundle.payload.filtered?.logcat || "", 80_000),
          activity: clipDiagnosticText(adbBundle.payload.filtered?.activity || "", 40_000),
          packageWasmAgent: clipDiagnosticText(adbBundle.payload.filtered?.packageWasmAgent || "", 40_000),
          webApkPackages: clipDiagnosticText(adbBundle.payload.filtered?.webApkPackages || "", 20_000),
        },
      },
      uploaded: upload,
    };
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "check_android_connection") {
    const sender = win?.webContents || { send: () => {} };
    const opId = `control-android-connection-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    const result = await runAndroidConnectionCheck(sender, opId);
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "run_hot_operation") {
    const sender = win?.webContents || { send: () => {} };
    const opId = `control-hot-operation-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    await ensureDownloadedRuntimeFromFeed(payload);
    await ensureDownloadedHotOperationsFromFeed(payload);
    const result = await runHotOperation(sender, opId, payload);
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "get_native_kernel_status") {
    await ensureDownloadedRuntimeFromFeed(payload);
    await ensureDownloadedHotOperationsFromFeed(payload);
    const result = { ok: true, operation: type, kernel: nativeKernelStatus(), logsTail: recentBridgeLogsTail() };
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "get_bridge_status" || type === "status") {
    await ensureDownloadedRuntimeFromFeed(payload);
    await ensureDownloadedHotOperationsFromFeed(payload);
    const result = getBridgeStatus();
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "list_hot_operations") {
    await ensureDownloadedRuntimeFromFeed(payload);
    await ensureDownloadedHotOperationsFromFeed(payload);
    const result = listHotOperations();
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "refresh_downloaded_runtime" || type === "sync_downloaded_runtime") {
    const downloadedRuntimeSync = await ensureDownloadedRuntimeFromFeed({ ...payload, forceSync: true });
    const result = { ok: downloadedRuntimeSync.ok === true, operation: type, downloadedRuntimeSync, downloadedRuntime: downloadedRuntimeSummary(), logsTail: recentBridgeLogsTail() };
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "rollback_downloaded_runtime") {
    const result = { ...rollbackDownloadedRuntimeToLastKnownGood(), logsTail: recentBridgeLogsTail() };
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "refresh_downloaded_hot_ops" || type === "sync_downloaded_hot_ops") {
    const downloadedHotOpsSync = await ensureDownloadedHotOperationsFromFeed({ ...payload, forceSync: true });
    const result = { ok: downloadedHotOpsSync.ok === true, operation: type, downloadedHotOpsSync, logsTail: recentBridgeLogsTail() };
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "run_shell_self_test") {
    const sender = win?.webContents || { send: () => {} };
    const opId = `control-shell-self-test-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    const defaultLightweight = payload.includeDeepProbes !== true
      && payload.include_deep_probes !== true
      && payload.includeAdbDiscovery !== true
      && payload.include_adb_discovery !== true
      && payload.requireAuthorizedAndroid !== true
      && payload.require_authorized_android !== true;
    const result = defaultLightweight
      ? runShellSelfTestSnapshot()
      : await runShellSelfTest(sender, opId, payload);
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "debug_android_voice_tuning_runtime") {
    const sender = win?.webContents || { send: () => {} };
    const opId = `control-android-runtime-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    const result = await runAndroidVoiceTuningRuntimeDebug(sender, opId, payload);
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "export_hermes_wake_dataset") {
    const sender = win?.webContents || { send: () => {} };
    const opId = `control-hermes-wake-export-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    const result = await exportHermesWakeDataset(sender, opId, payload);
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "run_android_hermes_wake_proof") {
    const sender = win?.webContents || { send: () => {} };
    const opId = `control-hermes-wake-proof-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    const result = await runAndroidHermesWakeProof(sender, opId, payload);
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "play_wake_phrase_probe") {
    const result = await playWindowsWakePhraseProbe(payload);
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "play_audio_stimulus") {
    const result = await playWindowsAudioStimulus(payload);
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
  if (type === "prove_android_voice_tuning") {
    const sender = win?.webContents || { send: () => {} };
    const opId = `control-android-voice-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    const result = await runAndroidVoiceTuningProof(sender, opId, payload);
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "run_android_voice_tuning_goal_loop") {
    const sender = win?.webContents || { send: () => {} };
    const opId = `control-android-voice-goal-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    const result = await runAndroidVoiceTuningGoalLoop(sender, opId, payload);
    writeNativeControlAudit({ action: "command_finished", id: command.id || "", type, result });
    return result;
  }
  if (type === "request_windows_client_update") {
    const sender = win?.webContents || { send: () => {} };
    const opId = `control-windows-update-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    const result = await runWindowsSelfUpdate(sender, opId, {
      reason: command.reason || payload.reason || `control:${command.id || type}`,
      applyApproved: payload.applyApproved === true || payload.apply_approved === true,
    });
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
  } finally {
    activeNativeCommandCount = Math.max(0, activeNativeCommandCount - 1);
  }
}

async function pollNativeControl(reason = "interval") {
  if (nativeControlPollBusy || !selectedBackendOrigin) return { ok: false, error: "not_ready" };
  if (nativeObsConnected && reason !== "startup") return { ok: true, skipped: "native_obs_connected" };
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
      let upload = {};
      writeNativeControlAudit({
        action: "command_received",
        id: command?.id || "",
        type: command?.type || "",
        name: command?.name || command?.operationName || command?.operation_name || "",
        payloadType: command?.payload?.type || "",
        payloadName: command?.payload?.name || command?.payload?.operationName || command?.payload?.operation_name || "",
      });
      if (isRunShellSelfTestNativeControlCommand(command)) {
        writeNativeControlAudit({ action: "self_test_branch_entered", id: command?.id || "", type: command?.type || "", name: command?.name || "" });
        result = nativeControlConstantSelfTestResult();
        writeNativeControlAudit({ action: "self_test_result_built", id: command?.id || "", type: command?.type || "", result });
        try {
          writeNativeControlAudit({ action: "self_test_upload_start", id: command?.id || "", type: command?.type || "" });
          upload = await postNativeControlResult(command, result);
          writeNativeControlAudit({ action: "self_test_upload_done", id: command?.id || "", type: command?.type || "", upload });
          writeNativeControlAudit({ action: "command_result_upload_finished", id: command?.id || "", type: command?.type || "", upload });
        } catch (error) {
          upload = { ok: false, error: String(error && error.message ? error.message : error) };
          writeNativeControlAudit({ action: "self_test_upload_error", id: command?.id || "", type: command?.type || "", upload });
          writeNativeControlAudit({ action: "command_result_upload_finished", id: command?.id || "", type: command?.type || "", upload });
        }
        continue;
      }
      try {
        result = await executeNativeControlCommandWithWatchdog(command);
      } catch (error) {
        result = { ok: false, error: String(error && error.message ? error.message : error), failureClassification: "handler_threw" };
      } finally {
        upload = await postNativeControlResult(command, result);
        writeNativeControlAudit({ action: "command_result_upload_finished", id: command.id || "", type: command.type || "", upload });
      }
    }
    return { ok: true, commandCount: commands.length };
  } catch (error) {
    return { ok: false, error: String(error && error.message ? error.message : error) };
  } finally {
    nativeControlPollBusy = false;
  }
}

function startNativeControlPolling() {
  startNativeObservabilitySocket("startup");
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
    if (serverUrl) {
      void ensureDownloadedRuntimeFromFeed({ launch: true, forceSync: true })
        .then((downloadedRuntimeSync) => postNativeEvent("native.runtime_sync", { downloadedRuntimeSync, downloadedRuntime: downloadedRuntimeSummary(), kernel: nativeKernelStatus() }))
        .catch((error) => logNativeDiagnostic("downloaded-runtime-sync-failed", { reason: String(error && error.message ? error.message : error) }));
      void ensureDownloadedHotOperationsFromFeed({ launch: true, forceSync: true })
        .then((downloadedHotOpsSync) => postNativeEvent("native.hot_ops_sync", { downloadedHotOpsSync, hotOperations: hotOperationsSummary(), kernel: nativeKernelStatus() }))
        .catch((error) => logNativeDiagnostic("downloaded-hot-ops-sync-failed", { reason: String(error && error.message ? error.message : error) }));
    }
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
  setTimeout(() => {
    void checkAndStageWindowsSelfUpdate(win.webContents, `startup-update-${Date.now().toString(36)}`, { startup: true })
      .then((result) => {
        if (result?.ok && result.updateAvailable) {
          writeNativeUpdateAudit({ action: "startup_update_ready", result });
        }
      })
      .catch((error) => writeNativeUpdateAudit({ action: "startup_update_check_failed", error: String(error && error.message ? error.message : error) }));
  }, 8000).unref();
  return win;
}

app.setName("WASM Agent");
Menu.setApplicationMenu(Menu.buildFromTemplate([
  {
    label: "WASM Agent",
    submenu: [
      {
        label: "Check for Updates",
        click: () => {
          const win = currentNativeWindow();
          const sender = win?.webContents || { send: () => {} };
          const opId = `manual-update-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
          void runWindowsSelfUpdate(sender, opId, { applyApproved: true }).then((result) => {
            if (!result?.ok && result?.manualInstallerPath) shell.showItemInFolder(result.manualInstallerPath);
          });
        },
      },
      { type: "separator" },
      { role: "quit" },
    ],
  },
]));

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
  nativeKernel: nativeKernelStatus(),
  downloadedRuntime: downloadedRuntimeSummary(),
  hotOperations: hotOperationsSummary(),
}));

ipcMain.handle("wasm-agent:native-diagnostics-operation", (event, operation) => handleWindowsNativeDiagnosticsOperation(event, operation));

ipcMain.handle("wasm-agent:check-for-updates", (event) => {
  const opId = `manual-update-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  return checkAndStageWindowsSelfUpdate(event.sender, opId, { manual: true });
});

ipcMain.handle("wasm-agent:install-staged-update", (event) => {
  const opId = activeWindowsSelfUpdate?.opId || `manual-install-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  return promptAndLaunchWindowsInstaller(event.sender, opId, activeWindowsSelfUpdate);
});

app.whenReady().then(async () => {
  registerNativeAppProtocol();
  await clearNativeWebShellCache();
  createWindow();
  void postNativeEvent("native.install_status", { status: "launched", app_version: app.getVersion() });
  const hotOpsStatus = hotOperationsSummary();
  const runtimeStatus = downloadedRuntimeSummary();
  const kernelStatus = nativeKernelStatus();
  void postNativeEvent("native.capabilities", {
    native_kernel_version: NATIVE_KERNEL_CONTRACT_VERSION,
    kernelContractVersion: NATIVE_KERNEL_CONTRACT_VERSION,
    supportedCapabilities: WINDOWS_NATIVE_KERNEL_CAPABILITIES,
    missingCapabilities: [],
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
	    windows_self_update_ready: process.platform === "win32",
	    run_hot_operation_ready: true,
	    list_hot_operations_ready: true,
	    run_shell_self_test_ready: true,
	    shell_protocol_version: SHELL_PROTOCOL_VERSION,
	    supported_hot_ops_protocol: HOT_OPERATION_PROTOCOL_VERSION,
	    hot_ops_protocol_version: HOT_OPERATION_PROTOCOL_VERSION,
	    minimum_runner_version: MINIMUM_RUNNER_VERSION,
	    bridge_protocol_capabilities: BRIDGE_PROTOCOL_CAPABILITIES,
	    downloadedRuntime: runtimeStatus,
	    nativeKernel: kernelStatus,
	    hotOperations: hotOpsStatus,
	  });
  void postNativeEvent("device.status", { status: "online", app_version: app.getVersion(), arch: os.arch(), build_id: currentWindowsBuildInfo().buildId, shellProtocolVersion: SHELL_PROTOCOL_VERSION, hotOpsProtocolVersion: HOT_OPERATION_PROTOCOL_VERSION, downloadedRuntimeProtocolVersion: DOWNLOADED_RUNTIME_PROTOCOL_VERSION, nativeKernelVersion: NATIVE_KERNEL_CONTRACT_VERSION, minimumRunnerVersion: MINIMUM_RUNNER_VERSION, capabilities: BRIDGE_PROTOCOL_CAPABILITIES, supportedCapabilities: WINDOWS_NATIVE_KERNEL_CAPABILITIES, downloadedRuntime: runtimeStatus, nativeKernel: kernelStatus, activeDownloadedRuntimeId: kernelStatus.activeDownloadedRuntimeId, activeDownloadedRuntimeSha: kernelStatus.activeDownloadedRuntimeSha, activeHotOpBundleId: kernelStatus.activeHotOpBundleId, activeHotOpSha: kernelStatus.activeHotOpSha, syncStatus: kernelStatus.syncStatus, staleReason: kernelStatus.staleReason, hotOperations: { supported: true, protocol: HOT_OPERATION_PROTOCOL_VERSION, ...hotOpsStatus }, logsTail: recentBridgeLogsTail() });
  startNativeControlPolling();
  setInterval(() => {
    void ensureDownloadedRuntimeFromFeed({ heartbeat: true });
    const heartbeatHotOps = hotOperationsSummary();
    const heartbeatKernel = nativeKernelStatus();
    void postNativeEvent("device.heartbeat", { status: "online", app_version: app.getVersion(), arch: os.arch(), build_id: currentWindowsBuildInfo().buildId, shellProtocolVersion: SHELL_PROTOCOL_VERSION, hotOpsProtocolVersion: HOT_OPERATION_PROTOCOL_VERSION, downloadedRuntimeProtocolVersion: DOWNLOADED_RUNTIME_PROTOCOL_VERSION, nativeKernelVersion: NATIVE_KERNEL_CONTRACT_VERSION, minimumRunnerVersion: MINIMUM_RUNNER_VERSION, capabilities: BRIDGE_PROTOCOL_CAPABILITIES, supportedCapabilities: WINDOWS_NATIVE_KERNEL_CAPABILITIES, downloadedRuntime: heartbeatKernel.downloadedRuntime, nativeKernel: heartbeatKernel, activeDownloadedRuntimeId: heartbeatKernel.activeDownloadedRuntimeId, activeDownloadedRuntimeSha: heartbeatKernel.activeDownloadedRuntimeSha, activeHotOpBundleId: heartbeatKernel.activeHotOpBundleId, activeHotOpSha: heartbeatKernel.activeHotOpSha, syncStatus: heartbeatKernel.syncStatus, staleReason: heartbeatKernel.staleReason, hotOperations: { supported: true, protocol: HOT_OPERATION_PROTOCOL_VERSION, ...heartbeatHotOps }, hotOpsMode: heartbeatHotOps.hotOpsMode, hotOpsRoot: heartbeatHotOps.hotOpsRoot, devReload: heartbeatHotOps.devReload, logsTail: recentBridgeLogsTail() });
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
