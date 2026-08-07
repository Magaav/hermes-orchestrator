const manifest = require("./capability-manifest.json");
const { chromeLikeUserAgent } = require("../../native-shell-policy");

const IPC_CHANNEL = "wasm-agent:web-surface";
const EVENT_CHANNEL = "wasm-agent:web-surface-event";
const MAX_ID_LENGTH = 80;

function normalizedId(value) {
  const id = String(value || "").trim();
  if (!id || id.length > MAX_ID_LENGTH || !/^[a-zA-Z0-9._-]+$/.test(id)) {
    throw new Error("invalid_surface_id");
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

function compactState(record) {
  const contents = record.view.webContents;
  return {
    schema: manifest.schema,
    id: record.id,
    status: record.status,
    visible: record.visible,
    url: contents.getURL(),
    title: contents.getTitle(),
    loading: contents.isLoading(),
    canGoBack: contents.navigationHistory.canGoBack(),
    canGoForward: contents.navigationHistory.canGoForward(),
    error: record.error,
  };
}

function createWebSurfaceManager({ WebContentsView, session, shell }) {
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

  function send(record, type) {
    if (record.owner.isDestroyed()) return;
    record.owner.webContents.send(EVENT_CHANNEL, { type, surface: compactState(record) });
  }

  function configurePartition(partition) {
    const webSession = session.fromPartition(partition);
    if (webSession.__wasmAgentWebSurfaceConfigured) return;
    webSession.__wasmAgentWebSurfaceConfigured = true;
    webSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    webSession.on("will-download", (event) => event.preventDefault());
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
    if (owned.has(id)) return compactState(owned.get(id));
    if (owned.size >= manifest.limits.maxSurfacesPerWindow) throw new Error("surface_limit_reached");
    const partition = `persist:wasm-agent:web:${id}`;
    configurePartition(partition);
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
    const record = { id, owner, view, visible: false, status: "idle", error: null, bounds: null };
    const userAgent = chromeLikeUserAgent(view.webContents.getUserAgent());
    if (userAgent) view.webContents.setUserAgent(userAgent);
    owned.set(id, record);
    records.add(record);
    owner.contentView.addChildView(view);
    view.setVisible(false);
    attachEvents(record);
    if (args.bounds) setBounds(owner, { id, bounds: args.bounds });
    if (args.url) await navigate(owner, { id, url: args.url });
    return compactState(record);
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

  function action(owner, args = {}) {
    const record = requireRecord(owner, args.id);
    const contents = record.view.webContents;
    switch (String(args.action || "")) {
      case "back": if (contents.navigationHistory.canGoBack()) contents.navigationHistory.goBack(); break;
      case "forward": if (contents.navigationHistory.canGoForward()) contents.navigationHistory.goForward(); break;
      case "reload": contents.reload(); break;
      case "stop": contents.stop(); break;
      default: throw new Error("unsupported_surface_action");
    }
    return compactState(record);
  }

  function close(owner, args = {}) {
    const owned = windowRecords(owner);
    const record = requireRecord(owner, args.id);
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
        case "visibility": return setVisible(owner, args);
        case "action": return action(owner, args);
        case "status": return compactState(requireRecord(owner, args.id));
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

function installWebSurfaces({ ipcMain, BrowserWindow, WebContentsView, session, shell }) {
  const manager = createWebSurfaceManager({ WebContentsView, session, shell });
  registerWebSurfaceIpc({ ipcMain, BrowserWindow, manager });
  return manager;
}

module.exports = { createWebSurfaceManager, installWebSurfaces, registerWebSurfaceIpc, normalizedBounds, normalizedUrl };
