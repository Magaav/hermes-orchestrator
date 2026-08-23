const manifest = require("./capability-manifest.json");
const { randomUUID } = require("crypto");

const IPC_CHANNEL = "wasm-agent:web-surface";
const EVENT_CHANNEL = "wasm-agent:web-surface-event";
const MAX_ID_LENGTH = 80;
const INPUT_RECEIPT_SCHEMA = "hermes.wasm_agent.native_web_surface_input_receipt.v1";
const POINTER_DISPATCH_SCHEMA = "hermes.wasm_agent.native_web_surface_pointer_dispatch.v1";
const JAVASCRIPT_EXECUTION_SCHEMA = "hermes.wasm_agent.native_web_surface_javascript_execution.v1";
const INPUT_RECEIPT_TTL_MS = manifest.limits.inputReceiptTtlMs;
const POINTER_DISPATCH_CORRELATION_MS = manifest.limits.pointerDispatchCorrelationMs;

function normalizedId(value) {
  const id = String(value || "").trim();
  if (!id || id.length > MAX_ID_LENGTH || !/^[a-zA-Z0-9._-]+$/.test(id)) {
    throw new Error("invalid_surface_id");
  }
  return id;
}

function normalizedCommandId(value) {
  const id = String(value || "").trim();
  if (!id || id.length > MAX_ID_LENGTH || !/^[a-zA-Z0-9._-]+$/.test(id)) {
    throw new Error("invalid_pointer_dispatch_command_id");
  }
  return id;
}

function normalizedUrl(value) {
  const url = new URL(String(value || ""));
  if (!manifest.limits.protocols.includes(url.protocol)) throw new Error("navigation_protocol_denied");
  url.username = "";
  url.password = "";
  return url.href;
}

function normalizedBounds(value = {}) {
  const number = (item) => Math.max(0, Math.round(Number(item) || 0));
  const bounds = {
    x: number(value.x),
    y: number(value.y),
    width: number(value.width),
    height: number(value.height),
  };
  if (!bounds.width || !bounds.height) throw new Error("invalid_surface_bounds");
  return bounds;
}

function chromeMajor(userAgent) {
  return String(userAgent || "").match(/\bChrome\/(\d+)/i)?.[1] || "";
}

function chromeClientHint(userAgent) {
  const major = chromeMajor(userAgent);
  return major ? `"Google Chrome";v="${major}", "Chromium";v="${major}", "Not_A Brand";v="99"` : "";
}

function canonicalChromeUserAgent(version) {
  const normalized = String(version || "").match(/^\d+(?:\.\d+){0,3}/)?.[0] || "";
  return normalized
    ? `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${normalized} Safari/537.36`
    : "";
}

function setHeader(headers, name, value) {
  const existing = Object.keys(headers).find((key) => key.toLowerCase() === name.toLowerCase());
  headers[existing || name] = value;
}

function currentSurfaceStatus(record, loading = record.view.webContents.isLoading()) {
  if (record.error) return "error";
  if (loading) return "loading";
  if (record.view.webContents.getURL()) return "ready";
  return record.status;
}

function compactState(record) {
  const contents = record.view.webContents;
  const loading = contents.isLoading();
  return {
    schema: manifest.schema,
    id: record.id,
    status: currentSurfaceStatus(record, loading),
    visible: record.visible,
    url: contents.getURL(),
    title: contents.getTitle(),
    loading,
    canGoBack: contents.navigationHistory.canGoBack(),
    canGoForward: contents.navigationHistory.canGoForward(),
    browserIdentity: {
      userAgent: contents.getUserAgent(),
      chromeMajor: chromeMajor(contents.getUserAgent()),
    },
    error: record.error,
  };
}

function receiptPosition(mouse, bounds) {
  const x = Math.round(Number(mouse?.x));
  const y = Math.round(Number(mouse?.y));
  if (
    !Number.isFinite(x) || !Number.isFinite(y)
    || !Number.isSafeInteger(bounds?.width) || !Number.isSafeInteger(bounds?.height)
    || bounds.width <= 0 || bounds.height <= 0
    || x < 0 || y < 0 || x >= bounds.width || y >= bounds.height
  ) return null;
  return { x, y, viewport: { width: bounds.width, height: bounds.height } };
}

function createWebSurfaceManager({
  WebContentsView,
  session,
  shell,
  chromeVersion = process.versions.chrome,
  now = () => Date.now(),
  receiptId = () => randomUUID(),
  scheduleExpiry = (callback, delay) => setTimeout(callback, delay),
  cancelExpiry = (timer) => clearTimeout(timer),
}) {
  const windows = new Map();
  const records = new Set();

  function ownerKey(owner) {
    const id = Number(owner?.id);
    if (!Number.isSafeInteger(id) || id <= 0) throw new Error("invalid_native_window_id");
    return id;
  }

  function windowRecords(owner) {
    const key = ownerKey(owner);
    let owned = windows.get(key);
    if (!owned) {
      owned = new Map();
      windows.set(key, owned);
    }
    return owned;
  }

  function send(record, type, surface = compactState(record)) {
    if (record.owner.isDestroyed()) return;
    record.owner.webContents.send(EVENT_CHANNEL, { type, surface });
  }

  function clearStoredInputReceipt(record) {
    if (record.inputReceiptTimer) cancelExpiry(record.inputReceiptTimer);
    record.inputReceiptTimer = null;
    record.inputReceipt = null;
    record.inputReceiptAtMs = 0;
  }

  function clearInputState(record) {
    record.pendingPrimaryInput = null;
    record.pendingSyntheticDispatch = null;
    clearStoredInputReceipt(record);
  }

  function storeInputReceipt(record, receipt, atMs) {
    clearStoredInputReceipt(record);
    record.inputReceipt = receipt;
    record.inputReceiptAtMs = atMs;
    const expected = receipt;
    record.inputReceiptTimer = scheduleExpiry(() => {
      if (record.inputReceipt !== expected) return;
      record.inputReceiptTimer = null;
      record.inputReceipt = null;
      record.inputReceiptAtMs = 0;
    }, INPUT_RECEIPT_TTL_MS);
    record.inputReceiptTimer?.unref?.();
  }

  function currentInputReceipt(record) {
    if (!record.inputReceiptEnabled || !record.inputReceipt) return null;
    const ageMs = Math.max(0, Math.round(now() - record.inputReceiptAtMs));
    if (ageMs >= INPUT_RECEIPT_TTL_MS) {
      clearStoredInputReceipt(record);
      return null;
    }
    return { ...record.inputReceipt, age_ms: ageMs };
  }

  function statusState(record, options = {}) {
    const state = compactState(record);
    if (options.includeInputReceipt === true) {
      state.inputReceiptEnabled = record.inputReceiptEnabled;
      state.inputReceipt = currentInputReceipt(record);
    }
    return state;
  }

  function creationState(record) {
    return { ...compactState(record), inputReceiptEnabled: record.inputReceiptEnabled };
  }

  async function configurePartition(partition) {
    const webSession = session.fromPartition(partition);
    if (webSession.__wasmAgentWebSurfaceConfigured) return webSession;
    webSession.__wasmAgentWebSurfaceConfigured = true;
    const userAgent = canonicalChromeUserAgent(chromeVersion) || webSession.getUserAgent();
    if (userAgent) webSession.setUserAgent(userAgent);
    const clientHint = chromeClientHint(userAgent);
    webSession.webRequest.onBeforeSendHeaders((details, callback) => {
      const requestHeaders = { ...details.requestHeaders };
      if (userAgent) setHeader(requestHeaders, "User-Agent", userAgent);
      if (clientHint) setHeader(requestHeaders, "Sec-CH-UA", clientHint);
      callback({ requestHeaders });
    });
    await Promise.all([
      webSession.clearCache(),
      webSession.clearStorageData({ storages: ["serviceworkers", "cachestorage"] }),
    ]);
    webSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    webSession.on("will-download", (event) => event.preventDefault());
    return webSession;
  }

  function attachEvents(record) {
    const contents = record.view.webContents;
    contents.setWindowOpenHandler(({ url }) => {
      try {
        void contents.loadURL(normalizedUrl(url));
      } catch {
        if (/^https:/i.test(String(url || ""))) void shell.openExternal(url);
      }
      return { action: "deny" };
    });
    contents.on("will-navigate", (event, url) => {
      try {
        normalizedUrl(url);
      } catch {
        event.preventDefault();
        record.error = "navigation_protocol_denied";
        send(record, "navigation-denied");
      }
    });
    contents.on("before-mouse-event", (_event, mouse = {}) => {
      if (!record.inputReceiptEnabled) return;
      if (mouse.type === "mouseDown") {
        const position = mouse.button === "left" ? receiptPosition(mouse, record.bounds) : null;
        const synthetic = record.pendingSyntheticDispatch;
        const syntheticMatch = Boolean(
          position && synthetic
          && synthetic.documentRevision === record.documentRevision
          && synthetic.expiresAtMs >= now()
          && synthetic.x === position.x
          && synthetic.y === position.y
        );
        record.pendingSyntheticDispatch = null;
        record.pendingPrimaryInput = position
          ? {
            documentRevision: record.documentRevision,
            inputSource: syntheticMatch ? "electron_synthetic" : "unattributed_native_input",
            commandId: syntheticMatch ? synthetic.commandId : "",
          }
          : null;
        return;
      }
      if (mouse.type === "mouseLeave") {
        record.pendingPrimaryInput = null;
        record.pendingSyntheticDispatch = null;
        return;
      }
      if (mouse.type !== "mouseUp" || mouse.button !== "left") return;
      const pending = record.pendingPrimaryInput;
      record.pendingPrimaryInput = null;
      if (!pending || pending.documentRevision !== record.documentRevision) return;
      const position = receiptPosition(mouse, record.bounds);
      if (!position) return;
      const atMs = now();
      const receipt = {
        schema: INPUT_RECEIPT_SCHEMA,
        id: String(receiptId()).slice(0, 80),
        surface_id: record.id,
        at: new Date(atMs).toISOString(),
        action: "pointer.primary_gesture",
        outcome: "observed_pre_dispatch",
        button: "left",
        ...position,
        current_document: true,
        input_source: pending.inputSource,
        redacted: true,
      };
      if (pending.commandId) receipt.command_id = pending.commandId;
      storeInputReceipt(record, receipt, atMs);
    });
    contents.on("blur", () => {
      record.pendingPrimaryInput = null;
      record.pendingSyntheticDispatch = null;
    });
    contents.on("render-process-gone", () => clearInputState(record));
    contents.on("did-start-navigation", (details, _url, _isInPlace, isMainFrame) => {
      if ((details?.isMainFrame ?? isMainFrame) !== true) return;
      record.documentRevision += 1;
      clearInputState(record);
    });
    contents.on("did-start-loading", () => {
      record.status = "loading";
      record.error = null;
      send(record, "loading");
    });
    contents.on("did-finish-load", () => {
      record.status = "ready";
      record.error = null;
      send(record, "ready");
    });
    contents.on("did-fail-load", (_event, code, description, url, isMainFrame) => {
      if (!isMainFrame || code === -3) return;
      record.status = "error";
      record.error = `${code}:${String(description || "load_failed").slice(0, 120)}`;
      send(record, "error");
    });
    contents.on("page-title-updated", () => send(record, "title"));
    contents.on("did-navigate", () => send(record, "navigate"));
  }

  async function create(owner, args = {}) {
    const id = normalizedId(args.id);
    const owned = windowRecords(owner);
    if (owned.has(id)) return creationState(owned.get(id));
    if (owned.size >= manifest.limits.maxSurfacesPerWindow) throw new Error("surface_limit_reached");
    const partition = `persist:wasm-agent:web:${id}`;
    await configurePartition(partition);
    const view = new WebContentsView({
      webPreferences: {
        partition,
        sandbox: true,
        contextIsolation: true,
        nodeIntegration: false,
        webSecurity: true,
        allowRunningInsecureContent: false,
        navigateOnDragDrop: false,
      },
    });
    const record = {
      id,
      owner,
      view,
      visible: false,
      status: "idle",
      error: null,
      bounds: null,
      documentRevision: 0,
      pendingPrimaryInput: null,
      pendingSyntheticDispatch: null,
      inputReceiptEnabled: false,
      inputReceipt: null,
      inputReceiptAtMs: 0,
      inputReceiptTimer: null,
    };
    owned.set(id, record);
    records.add(record);
    owner.contentView.addChildView(view);
    view.setVisible(false);
    attachEvents(record);
    if (args.bounds) setBounds(owner, { id, bounds: args.bounds });
    if (args.url) await navigate(owner, { id, url: args.url });
    return creationState(record);
  }

  function requireRecord(owner, idValue) {
    const record = windowRecords(owner).get(normalizedId(idValue));
    if (!record) throw new Error("surface_not_found");
    return record;
  }

  async function navigate(owner, args = {}) {
    const record = requireRecord(owner, args.id);
    try {
      await record.view.webContents.loadURL(normalizedUrl(args.url));
    } catch (error) {
      if (Number(error?.errno ?? error?.code) !== -3) throw error;
    }
    return compactState(record);
  }

  function setBounds(owner, args = {}) {
    const record = requireRecord(owner, args.id);
    const bounds = normalizedBounds(args.bounds);
    if (!record.bounds || Object.keys(bounds).some((key) => bounds[key] !== record.bounds[key])) {
      record.bounds = bounds;
      record.view.setBounds(bounds);
    }
    return compactState(record);
  }

  function setVisible(owner, args = {}) {
    const record = requireRecord(owner, args.id);
    record.visible = Boolean(args.visible);
    record.view.setVisible(record.visible);
    return compactState(record);
  }

  function setInputReceiptEnabled(owner, args = {}) {
    if (typeof args.enabled !== "boolean") throw new Error("invalid_input_receipt_state");
    const record = requireRecord(owner, args.id);
    const changed = record.inputReceiptEnabled !== args.enabled;
    if (changed) clearInputState(record);
    record.inputReceiptEnabled = args.enabled;
    const state = creationState(record);
    if (changed) send(record, "input-receipt", state);
    return state;
  }

  function dispatchPrimaryPointer(owner, args = {}) {
    const record = requireRecord(owner, args.id);
    if (!record.inputReceiptEnabled) throw new Error("input_receipt_not_enabled");
    if (!record.visible || currentSurfaceStatus(record) !== "ready") throw new Error("surface_not_ready_for_pointer_dispatch");
    const position = receiptPosition(args, record.bounds);
    if (!position) throw new Error("invalid_pointer_dispatch_position");
    const commandId = normalizedCommandId(args.commandId);
    clearStoredInputReceipt(record);
    record.pendingPrimaryInput = null;
    record.pendingSyntheticDispatch = {
      commandId,
      documentRevision: record.documentRevision,
      x: position.x,
      y: position.y,
      expiresAtMs: now() + POINTER_DISPATCH_CORRELATION_MS,
    };
    try {
      owner.focus();
      record.view.webContents.focus();
      record.view.webContents.sendInputEvent({ type: "mouseDown", button: "left", clickCount: 1, x: position.x, y: position.y });
      record.view.webContents.sendInputEvent({ type: "mouseUp", button: "left", clickCount: 1, x: position.x, y: position.y });
    } catch (error) {
      record.pendingSyntheticDispatch = null;
      throw error;
    }
    const observed = currentInputReceipt(record);
    const receiptObserved = observed?.input_source === "electron_synthetic" && observed?.command_id === commandId;
    return {
      schema: POINTER_DISPATCH_SCHEMA,
      ok: true,
      surface_id: record.id,
      command_id: commandId,
      input_source: "electron_synthetic",
      dispatch_accepted: true,
      receipt_observed: receiptObserved,
      receipt_id: receiptObserved ? observed.id : null,
      current_document: true,
      redacted: true,
    };
  }

  async function executeJavascript(owner, args = {}) {
    const record = requireRecord(owner, args.id);
    const source = String(args.source ?? args.javascript ?? "");
    if (!source.trim()) throw new Error("javascript_source_missing");
    if (Buffer.byteLength(source, "utf8") > manifest.limits.javascriptSourceMaxBytes) throw new Error("javascript_source_too_large");
    const commandId = normalizedCommandId(args.commandId);
    const maxBytes = manifest.limits.javascriptResultMaxBytes;
    let value;
    let executionError = null;
    try {
      value = await record.view.webContents.executeJavaScript(source, true);
    } catch (error) {
      executionError = error;
    }
    let rawJson = "null";
    if (!executionError) {
      try {
        rawJson = JSON.stringify(value, (_key, item) => typeof item === "bigint" ? String(item) : item) ?? "null";
      } catch (_error) {
        rawJson = JSON.stringify(String(value));
      }
    }
    const resultBytes = Buffer.byteLength(rawJson, "utf8");
    const clipped = resultBytes > maxBytes ? Buffer.from(rawJson).subarray(0, maxBytes).toString("utf8") : rawJson;
    return {
      schema: JAVASCRIPT_EXECUTION_SCHEMA,
      ok: !executionError,
      surface_id: record.id,
      command_id: commandId,
      url: record.view.webContents.getURL(),
      result_json: clipped,
      result_bytes: resultBytes,
      result_truncated: resultBytes > maxBytes,
      error: String(executionError?.message || executionError || ""),
      stack: String(executionError?.stack || "").slice(0, 8192),
      execution_scope: "web_contents_main_world",
    };
  }

  async function snapshot(owner, args = {}) {
    const record = requireRecord(owner, args.id);
    const image = await record.view.webContents.capturePage();
    const size = image.getSize();
    return {
      schema: manifest.schema,
      id: record.id,
      status: "captured",
      mime: "image/png",
      dataUrl: image.toDataURL(),
      width: size.width,
      height: size.height,
      capturedAt: new Date().toISOString(),
    };
  }

  function action(owner, args = {}) {
    const record = requireRecord(owner, args.id);
    const contents = record.view.webContents;
    switch (String(args.action || "")) {
      case "back": if (contents.navigationHistory.canGoBack()) contents.navigationHistory.goBack(); break;
      case "forward": if (contents.navigationHistory.canGoForward()) contents.navigationHistory.goForward(); break;
      case "reload": contents.reloadIgnoringCache(); break;
      case "stop": contents.stop(); break;
      default: throw new Error("unsupported_surface_action");
    }
    return compactState(record);
  }

  function close(owner, args = {}) {
    const owned = windowRecords(owner);
    const record = requireRecord(owner, args.id);
    clearInputState(record);
    owner.contentView.removeChildView(record.view);
    record.view.webContents.close();
    owned.delete(record.id);
    records.delete(record);
    return { schema: manifest.schema, id: record.id, status: "closed" };
  }

  function disposeWindow(owner) {
    for (const id of [...windowRecords(owner).keys()]) close(owner, { id });
    windows.delete(ownerKey(owner));
  }

  function disposeAll() {
    for (const record of [...records]) close(record.owner, { id: record.id });
  }

  return {
    manifest,
    handle(owner, request = {}) {
      const args = request.args || {};
      switch (request.operation) {
        case "capabilities": return manifest;
        case "create": return create(owner, args);
        case "navigate": return navigate(owner, args);
        case "bounds": return setBounds(owner, args);
        case "snapshot": return snapshot(owner, args);
        case "visibility": return setVisible(owner, args);
        case "input-receipt": return setInputReceiptEnabled(owner, args);
        case "pointer-dispatch": return dispatchPrimaryPointer(owner, args);
        case "javascript-execute-unrestricted": return executeJavascript(owner, args);
        case "action": return action(owner, args);
        case "status": return statusState(requireRecord(owner, args.id), args);
        case "close": return close(owner, args);
        default: throw new Error("unsupported_web_surface_operation");
      }
    },
    disposeWindow,
    disposeAll,
  };
}

function registerWebSurfaceIpc({ ipcMain, BrowserWindow, manager }) {
  ipcMain.handle(IPC_CHANNEL, (event, request = {}) => {
    const owner = BrowserWindow.fromWebContents(event.sender);
    if (!owner) throw new Error("native_window_not_found");
    return manager.handle(owner, request);
  });
}

function installWebSurfaces({ ipcMain, BrowserWindow, WebContentsView, session, shell, chromeVersion }) {
  const manager = createWebSurfaceManager({ WebContentsView, session, shell, chromeVersion });
  registerWebSurfaceIpc({ ipcMain, BrowserWindow, manager });
  return manager;
}

module.exports = { canonicalChromeUserAgent, chromeClientHint, chromeMajor, createWebSurfaceManager, installWebSurfaces, registerWebSurfaceIpc, normalizedBounds, normalizedUrl };
