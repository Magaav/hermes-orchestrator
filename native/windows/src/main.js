const { app, BrowserWindow, Menu, ipcMain, protocol, session, shell } = require("electron");
const fs = require("fs");
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
const NATIVE_APP_ORIGIN = "wasm-agent://app";
const NATIVE_APP_HOME_URL = `${NATIVE_APP_ORIGIN}/home`;
let selectedBackendOrigin = "";
const startupDiagnostics = {
  appRoot: "",
  resourcesPath: "",
  startUrl: NATIVE_APP_HOME_URL,
  uiSource: "bundled-assets",
  bundledPublicRoot: "",
  resolvedBackendOrigin: "",
  candidateOrigins: [],
  originChecks: [],
  finalSelectedOrigin: "",
  currentRoute: "",
  configSource: "bundled-native-config",
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

function nativeDefaultsPath() {
  const candidates = [
    path.join(process.resourcesPath || "", "native-defaults.json"),
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

function uniqueServerUrlList(values) {
  const urls = [];
  values.forEach((value) => {
    const url = normalizeServerUrl(value);
    if (!url) return;
    if (!urls.some((existing) => existing.toLowerCase() === url.toLowerCase())) urls.push(url);
  });
  return urls;
}

function configuredServerUrlCandidates(existing = readConfig()) {
  const defaults = readNativeDefaults();
  const defaultCandidates = Array.isArray(defaults.serverUrlCandidates) ? defaults.serverUrlCandidates : [];
  return uniqueServerUrlList([
    existing.serverUrl,
    process.env.WASM_AGENT_URL,
    process.env.WASM_AGENT_SERVER_URL,
    process.env.HERMES_WASM_AGENT_NATIVE_SERVER_URL,
    process.env.HERMES_WASM_AGENT_PUBLIC_URL,
    process.env.WASM_AGENT_PUBLIC_URL,
    defaults.serverUrl,
    DEFAULT_SERVER_URL,
    "http://localhost:8877",
    ...defaultCandidates,
  ]);
}

function logNativeDiagnostic(kind, payload = {}) {
  const entry = { kind, ...payload };
  console.log(`[wasm-agent:native] ${kind} ${JSON.stringify(entry)}`);
}

function writeConfig(next) {
  fs.mkdirSync(app.getPath("userData"), { recursive: true });
  fs.writeFileSync(configPath(), JSON.stringify(next, null, 2));
}

function ensureConfig() {
  const existing = readConfig();
  const defaults = readNativeDefaults();
  const serverUrl = configuredServerUrlCandidates(existing)[0] || DEFAULT_SERVER_URL;
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
    googleClientId: String(defaults.googleClientId || existing.googleClientId || ""),
    serverUrl,
    serverUrlCandidates: configuredServerUrlCandidates({ ...existing, serverUrl }),
    deviceId,
    accountId: String(existing.accountId || ""),
    deviceToken: String(existing.deviceToken || ""),
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
  const next = { ...current, serverUrl, serverUrlCandidates: configuredServerUrlCandidates({ ...current, serverUrl }), updatedAt: new Date().toISOString() };
  writeConfig(next);
  selectedBackendOrigin = serverUrl;
  startupDiagnostics.finalSelectedOrigin = serverUrl;
  return serverUrl;
}

async function selectReachableServerUrl() {
  const current = ensureConfig();
  const candidates = configuredServerUrlCandidates(current);
  startupDiagnostics.candidateOrigins = candidates;
  startupDiagnostics.resolvedBackendOrigin = current.serverUrl;
  candidates.forEach((serverUrl) => console.log(`[native] testing backend candidate: ${serverUrl}`));
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
  const accepted = selectPreferredBackendResult(results);
  if (accepted) {
    console.log(`[native] selected backend: ${accepted.serverUrl}`);
    return acceptValidatedBackend(current, accepted.serverUrl);
  }
  selectedBackendOrigin = "";
  startupDiagnostics.finalSelectedOrigin = "";
  console.log("[native] selected backend: ");
  return "";
}

async function recoverReachableServerUrl(current = ensureConfig()) {
  if (selectedBackendOrigin) return selectedBackendOrigin;
  const candidates = configuredServerUrlCandidates(current);
  for (const serverUrl of candidates) {
    console.log(`[native] testing backend candidate: ${serverUrl}`);
    const result = await validateWasmAgentOrigin(serverUrl, current, 5000);
    startupDiagnostics.originChecks.push({ ...result, recovery: true });
    logNativeDiagnostic("origin-recovery-candidate", {
      serverUrl,
      accepted: result.ok,
      reason: result.reason || "wasm_agent_identity_confirmed",
      checks: result.checks,
    });
    console.log(`[native] result: ${result.ok ? "success" : "failure"} ${serverUrl} ${result.reason || "HTTP 200 valid JSON"}`);
    if (result.ok) return acceptValidatedBackend(current, serverUrl);
  }
  return "";
}

async function nativeConfigPayload() {
  const config = ensureConfig();
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
      buildPlatform: config.buildPlatform || "windows",
      buildArch: config.buildArch || "x64",
      buildChannel: config.buildChannel || "nsis",
      serverUrl,
      serverUrlCandidates: config.serverUrlCandidates || configuredServerUrlCandidates(config),
      deviceId: config.deviceId,
      registered: Boolean(config.deviceToken),
      packagedAssets: true,
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

function showFallback(win, reason) {
  if (!win || win.isDestroyed()) return;
  const config = ensureConfig();
  win.loadFile(fallbackPagePath(), {
    query: {
      serverUrl: config.serverUrl,
      testedUrl: new URL("/config.json", config.serverUrl).toString(),
      reason: compactLoadReason(reason, config.serverUrl),
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
      showFallback(win, "No backend with an available /config.json was found.");
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
  } catch (error) {
    logNativeDiagnostic("web-cache-clear-failed", {
      reason: String(error && error.message ? error.message : error),
    });
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
    if (selectedBackendOrigin && sameOrigin(selectedBackendOrigin, url)) return { action: "allow" };
    if (sameOrigin(NATIVE_APP_HOME_URL, url)) return { action: "allow" };
    if (isGoogleAuthUrl(url)) return { action: "allow" };
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
  win.webContents.on("before-input-event", (event, input) => {
    const key = String(input.key || "").toLowerCase();
    if ((input.control || input.meta) && key === "r") {
      event.preventDefault();
      reloadWindow(win, { hard: Boolean(input.shift) });
    }
  });
  loadConfiguredServer(win);
  return win;
}

app.setName("WASM Agent");
Menu.setApplicationMenu(null);

ipcMain.handle("wasm-agent:native-config", async () => nativeConfigPayload());

ipcMain.handle("wasm-agent:native-configure", (_event, update = {}) => {
  const current = ensureConfig();
  const serverUrl = normalizeServerUrl(update.serverUrl || current.serverUrl || DEFAULT_SERVER_URL);
  const next = {
    ...current,
    serverUrl,
    serverUrlCandidates: configuredServerUrlCandidates({ ...current, serverUrl }),
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
  console.log(`[native] testing backend candidate: ${normalized}`);
  const result = await validateWasmAgentOrigin(normalized, current, 5000);
  console.log(`[native] result: ${result.ok ? "success" : "failure"} ${normalized} ${result.reason || "HTTP 200 valid JSON"}`);
  if (result.ok) {
    acceptValidatedBackend(current, normalized);
    console.log(`[native] selected backend: ${normalized}`);
  }
  return result;
});

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
  });
  void postNativeEvent("device.status", { status: "online", app_version: app.getVersion(), arch: os.arch() });
  setInterval(() => {
    void postNativeEvent("device.heartbeat", { status: "online", app_version: app.getVersion(), arch: os.arch() });
  }, HEARTBEAT_INTERVAL_MS).unref();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
