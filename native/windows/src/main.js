const { app, BrowserWindow, Menu, ipcMain, protocol, session, shell } = require("electron");
const fs = require("fs");
const crypto = require("crypto");
const os = require("os");
const path = require("path");
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
const NATIVE_APP_ORIGIN = "wasm-agent://app";
const NATIVE_APP_HOME_URL = `${NATIVE_APP_ORIGIN}/home`;
let selectedBackendOrigin = "";
let nativeControlPollBusy = false;
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
  const entry = { kind, ...payload };
  console.log(`[wasm-agent:native] ${kind} ${JSON.stringify(entry)}`);
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
    ...overrides,
  };
}

function runtimeDiagnosticsPath() {
  const localAppData = process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
  return path.join(localAppData, "WASM Agent Native", "runtime-diagnostics.json");
}

function rendererAuthDiagnosticsPath() {
  const localAppData = process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
  return path.join(localAppData, "WASM Agent Native", "renderer-auth-diagnostics.log");
}

function sanitizeRendererDiagnosticValue(value, depth = 0) {
  if (depth > 4) return "[depth-limit]";
  if (value === null || ["string", "number", "boolean"].includes(typeof value)) {
    const text = String(value);
    return text.length > 600 ? `${text.slice(0, 600)}...` : value;
  }
  if (Array.isArray(value)) return value.slice(0, 20).map((item) => sanitizeRendererDiagnosticValue(item, depth + 1));
  if (!value || typeof value !== "object") return "";
  const redacted = {};
  Object.entries(value).slice(0, 80).forEach(([key, item]) => {
    if (/credential|token|cookie|secret|authorization|password/i.test(key)) {
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

async function flushNativeAuthCookies(options = {}) {
  let flushed = false;
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
  });
  return {
    ...status,
    flushed,
    reason: String(options.reason || ""),
  };
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
  const win = currentNativeWindow();
  logNativeDiagnostic("native-control-command", {
    id: command.id || "",
    type,
  });
  if (type === "upload_diagnostics") {
    return uploadRendererAuthDiagnostics({ reason: `control:${command.id || type}` });
  }
  if (type === "write_runtime_diagnostics") {
    const pathWritten = writeRuntimeDiagnostics({
      nativeControlCommandId: command.id || "",
      nativeControlCommandType: type,
      currentRoute: currentRendererUrl(),
    });
    return { ok: Boolean(pathWritten), path: pathWritten };
  }
  if (type === "clear_web_cache") {
    return clearNativeWebShellCache();
  }
  if (type === "reload") {
    reloadWindow(win);
    return { ok: true, reloaded: true, hard: false, route: currentRendererUrl() };
  }
  if (type === "hard_reload") {
    reloadWindow(win, { hard: true });
    return { ok: true, reloaded: true, hard: true, route: currentRendererUrl() };
  }
  if (type === "status") {
    const authCookie = await nativeAuthCookieStatus();
    return {
      ok: true,
      status: "online",
      appVersion: app.getVersion(),
      arch: os.arch(),
      route: currentRendererUrl(),
      authCookie,
      diagnosticsPath: runtimeDiagnosticsPath(),
      rendererAuthDiagnosticsPath: rendererAuthDiagnosticsPath(),
    };
  }
  return { ok: false, error: `unsupported_command:${type}` };
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

async function clearNativeWebShellCache() {
  try {
    await session.defaultSession.clearCache();
    await session.defaultSession.clearStorageData({
      storages: ["serviceworkers", "cachestorage"],
    });
    logNativeDiagnostic("web-cache-cleared", {
      storages: ["serviceworkers", "cachestorage"],
    });
    return { ok: true, storages: ["serviceworkers", "cachestorage"] };
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
