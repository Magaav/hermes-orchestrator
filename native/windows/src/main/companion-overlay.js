"use strict";

const fs = require("fs");
const path = require("path");

const OVERLAY_QUERY = "native=electron&companion=overlay";
const TOPMOST_MIN_INTERVAL_MS = 250;
const TOPMOST_MAX_INTERVAL_MS = 10000;
const DEFAULT_SHORTCUT = "CommandOrControl+Space";
const IPC_CHANNEL = "wasm-agent:companion-window";
const IPC_MOVE_CHANNEL = "wasm-agent:companion-window-move";
const COMPACT_SIZE = 86;
const DEFAULT_PANEL_WIDTH = 430;
const DEFAULT_PANEL_HEIGHT = 620;

function overlayUrl(origin) {
  const url = new URL("/home", String(origin || "https://wa.colmeio.com"));
  url.search = OVERLAY_QUERY;
  return url.toString();
}

function boundedPanelSize(payload = {}) {
  return {
    width: Math.max(320, Math.min(860, Math.round(Number(payload.panel_width || payload.panelWidth) || DEFAULT_PANEL_WIDTH))),
    height: Math.max(420, Math.min(1200, Math.round(Number(payload.panel_height || payload.panelHeight) || DEFAULT_PANEL_HEIGHT))),
  };
}

function windowSize(mode, payload = {}) {
  if (mode !== "expanded") return { width: COMPACT_SIZE, height: COMPACT_SIZE };
  const panel = boundedPanelSize(payload);
  return { width: panel.width + COMPACT_SIZE, height: panel.height };
}

function clampBounds(bounds, screen) {
  if (!screen?.getDisplayMatching) return bounds;
  const display = screen.getDisplayMatching(bounds);
  const area = display?.workArea || display?.bounds;
  if (!area) return bounds;
  const width = Math.min(bounds.width, area.width);
  const height = Math.min(bounds.height, area.height);
  return {
    x: Math.max(area.x, Math.min(area.x + area.width - width, bounds.x)),
    y: Math.max(area.y, Math.min(area.y + area.height - height, bounds.y)),
    width,
    height,
  };
}

function clampPosition(bounds, screen) {
  if (!screen?.getDisplayMatching) return bounds;
  const display = screen.getDisplayMatching(bounds);
  const area = display?.workArea || display?.bounds;
  if (!area) return bounds;
  return {
    ...bounds,
    x: Math.max(area.x, Math.min(area.x + Math.max(0, area.width - bounds.width), bounds.x)),
    y: Math.max(area.y, Math.min(area.y + Math.max(0, area.height - bounds.height), bounds.y)),
  };
}

function anchorBounds(current, size, screen) {
  return clampBounds({
    x: current.x + current.width - size.width,
    y: current.y + current.height - size.height,
    ...size,
  }, screen);
}

function createCompanionOverlay({ BrowserWindow, globalShortcut, ipcMain, screen, session, shell, preload, icon, origin, statePath = "", onStatus = () => {} } = {}) {
  let window = null;
  let mode = "compact";
  let shortcutRegistered = false;
  let registeredAccelerator = "";
  let ipcInstalled = false;
  let activeMove = null;
  let topmostTimer = null;
  let topmostPolicy = { enabled: true, interval_ms: 1000 };
  let topmostEnforcements = 0;
  let lastTopmostEnforcedAt = "";

  const enforceTopmost = () => {
    if (!topmostPolicy.enabled || !window || window.isDestroyed() || !window.isVisible()) return false;
    window.setAlwaysOnTop(true, "floating");
    window.moveTop?.();
    topmostEnforcements += 1;
    lastTopmostEnforcedAt = new Date().toISOString();
    return true;
  };

  const scheduleTopmost = () => {
    if (topmostTimer) clearInterval(topmostTimer);
    topmostTimer = null;
    if (!topmostPolicy.enabled) return;
    topmostTimer = setInterval(enforceTopmost, topmostPolicy.interval_ms);
    topmostTimer.unref?.();
  };

  const configureTopmost = (payload = {}) => {
    const requested = Math.round(Number(payload.interval_ms || payload.intervalMs) || 1000);
    topmostPolicy = {
      enabled: payload.enabled !== false,
      interval_ms: Math.max(TOPMOST_MIN_INTERVAL_MS, Math.min(TOPMOST_MAX_INTERVAL_MS, requested)),
    };
    scheduleTopmost();
    enforceTopmost();
    return status("topmost_configured", { reason: "cloud_policy" });
  };

  const readAnchor = () => {
    try {
      const value = JSON.parse(fs.readFileSync(statePath, "utf8"));
      return Number.isFinite(value.right) && Number.isFinite(value.bottom) ? value : null;
    } catch {
      return null;
    }
  };

  const persistAnchor = () => {
    if (!statePath || !window || window.isDestroyed()) return;
    const bounds = window.getBounds();
    try {
      fs.mkdirSync(path.dirname(statePath), { recursive: true });
      fs.writeFileSync(statePath, `${JSON.stringify({ right: bounds.x + bounds.width, bottom: bounds.y + bounds.height })}\n`);
    } catch {
      // Position persistence must not interfere with companion control.
    }
  };

  const currentBounds = () => (window && !window.isDestroyed() ? window.getBounds() : null);
  const status = (state, extra = {}) => {
    const value = {
      schema: "hermes.wasm_agent.companion_overlay.v2",
      ok: state !== "shortcut_unavailable",
      state,
      mode,
      visible: Boolean(window && !window.isDestroyed() && window.isVisible()),
      bounds: currentBounds(),
      visual_owner: "pwa.agent-avatar-token",
      topmost: {
        ...topmostPolicy,
        active: Boolean(window && !window.isDestroyed() && window.isAlwaysOnTop?.()),
        enforcements: topmostEnforcements,
        last_enforced_at: lastTopmostEnforcedAt || null,
      },
      ...extra,
    };
    onStatus(value);
    return value;
  };

  const initialBounds = () => {
    const size = windowSize("compact");
    const saved = readAnchor();
    if (saved) return clampBounds({ x: saved.right - size.width, y: saved.bottom - size.height, ...size }, screen);
    const area = screen?.getPrimaryDisplay?.()?.workArea;
    if (!area) return size;
    return { x: area.x + area.width - size.width - 12, y: area.y + area.height - size.height - 12, ...size };
  };

  const setMode = (nextMode, payload = {}) => {
    const target = create();
    activeMove = null;
    mode = nextMode === "expanded" ? "expanded" : "compact";
    target.setBounds(anchorBounds(target.getBounds(), windowSize(mode, payload), screen), false);
    persistAnchor();
    if (mode === "expanded") {
      target.show();
      target.focus();
    } else if (!target.isVisible()) {
      target.showInactive?.();
    }
    return status("visible", { reason: "mode", requested_mode: nextMode });
  };

  const moveBy = (delta = {}) => {
    if (!window || window.isDestroyed()) return { ok: false, error: "companion_overlay_unavailable" };
    const x = Math.max(-4000, Math.min(4000, Math.round(Number(delta.x) || 0)));
    const y = Math.max(-4000, Math.min(4000, Math.round(Number(delta.y) || 0)));
    if (!x && !y) return { ok: true, moved: false };
    const bounds = window.getBounds();
    window.setBounds(clampPosition({ ...bounds, x: bounds.x + x, y: bounds.y + y }, screen), false);
    return { ok: true, moved: true, bounds: currentBounds() };
  };

  const cursorPoint = (request = {}) => {
    const supplied = { x: Number(request.pointer_x), y: Number(request.pointer_y) };
    if (Number.isFinite(supplied.x) && Number.isFinite(supplied.y)) return supplied;
    const point = screen?.getCursorScreenPoint?.();
    return Number.isFinite(point?.x) && Number.isFinite(point?.y) ? point : null;
  };

  const beginMove = (request = {}) => {
    if (!window || window.isDestroyed()) return { ok: false, error: "companion_overlay_unavailable" };
    const cursor = cursorPoint(request);
    if (!cursor) return { ok: false, error: "companion_cursor_unavailable" };
    activeMove = { bounds: window.getBounds(), cursor, sessionId: String(request.session_id || "") };
    return { ok: true, moving: true };
  };

  const updateMove = (request = {}) => {
    if (!activeMove || !window || window.isDestroyed()) return { ok: false, moved: false, error: "companion_move_inactive" };
    const sessionId = String(request.session_id || "");
    if (sessionId && activeMove.sessionId && sessionId !== activeMove.sessionId) return { ok: false, moved: false, error: "companion_move_stale" };
    const cursor = cursorPoint(request);
    if (!cursor) return { ok: false, moved: false, error: "companion_cursor_unavailable" };
    const bounds = clampPosition({
      ...activeMove.bounds,
      x: activeMove.bounds.x + cursor.x - activeMove.cursor.x,
      y: activeMove.bounds.y + cursor.y - activeMove.cursor.y,
    }, screen);
    const current = window.getBounds();
    const moved = bounds.x !== current.x || bounds.y !== current.y;
    if (moved) window.setBounds(bounds, false);
    return { ok: true, moved, bounds: currentBounds() };
  };

  const endMove = (request = {}) => {
    if (!activeMove) return { ok: true, moved: false };
    const sessionId = String(request.session_id || "");
    if (sessionId && activeMove.sessionId && sessionId !== activeMove.sessionId) return { ok: false, moved: false, error: "companion_move_stale" };
    const moved = request.moved !== false;
    if (moved) updateMove(request);
    activeMove = null;
    if (!moved) return { ok: true, moved: false, bounds: currentBounds() };
    persistAnchor();
    return status("visible", { reason: "move_finished" });
  };

  const handleIpc = (event, request = {}) => {
    if (!window || window.isDestroyed() || event.sender !== window.webContents) {
      return { ok: false, error: "companion_sender_denied" };
    }
    const operation = String(request.operation || "status");
    if (operation === "set_mode") return setMode(request.mode, request);
    if (operation === "configure_topmost") return configureTopmost(request);
    if (operation === "end_move") {
      if (activeMove) return endMove(request);
      persistAnchor();
      return status("visible", { reason: "move_finished", protocol: "legacy_delta" });
    }
    if (operation === "status") return status("status");
    return { ok: false, error: "companion_operation_unsupported", operation };
  };

  const installIpc = () => {
    if (ipcInstalled || !ipcMain) return;
    ipcInstalled = true;
    ipcMain.handle(IPC_CHANNEL, handleIpc);
    ipcMain.on(IPC_MOVE_CHANNEL, handleMoveIpc);
  };

  function handleMoveIpc(event, request = {}) {
    if (!window || window.isDestroyed() || event.sender !== window.webContents) return;
    if (request.operation === "begin") beginMove(request);
    else if (request.operation === "update") updateMove(request);
    else if (request.operation === "end") endMove(request);
    else moveBy(request);
  }

  const create = () => {
    if (window && !window.isDestroyed()) return window;
    window = new BrowserWindow({
      ...initialBounds(),
      minWidth: COMPACT_SIZE,
      minHeight: COMPACT_SIZE,
      show: false,
      frame: false,
      transparent: true,
      hasShadow: false,
      alwaysOnTop: true,
      skipTaskbar: true,
      resizable: false,
      movable: true,
      title: "WASM Agent Companion",
      backgroundColor: "#00000000",
      icon,
      webPreferences: {
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        preload,
        session: session?.defaultSession,
        additionalArguments: ["--wasm-agent-companion-overlay=1"],
      },
    });
    window.__wasmAgentCompanionOverlay = true;
    window.setAlwaysOnTop(true, "floating");
    window.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    scheduleTopmost();
    window.webContents.setWindowOpenHandler(({ url }) => {
      shell?.openExternal?.(url);
      return { action: "deny" };
    });
    window.on("close", (event) => {
      if (window && !window.isDestroyed()) {
        event.preventDefault();
        window.hide();
        status("hidden", { reason: "close" });
      }
    });
    installIpc();
    void window.loadURL(overlayUrl(typeof origin === "function" ? origin() : origin));
    return window;
  };

  const show = () => {
    const target = create();
    if (mode === "compact" && target.showInactive) target.showInactive();
    else {
      target.show();
      target.focus();
    }
    enforceTopmost();
    return status("visible");
  };

  const hide = () => {
    if (window && !window.isDestroyed()) window.hide();
    return status("hidden");
  };

  const toggle = () => (window && !window.isDestroyed() && window.isVisible() ? hide() : show());
  const register = (accelerator = DEFAULT_SHORTCUT) => {
    shortcutRegistered = Boolean(globalShortcut?.register?.(accelerator, toggle));
    registeredAccelerator = shortcutRegistered ? accelerator : "";
    return status(shortcutRegistered ? "ready" : "shortcut_unavailable", { accelerator, shortcutRegistered });
  };

  const dispose = () => {
    persistAnchor();
    if (shortcutRegistered && registeredAccelerator) globalShortcut?.unregister?.(registeredAccelerator);
    shortcutRegistered = false;
    registeredAccelerator = "";
    if (ipcInstalled) {
      ipcMain?.removeHandler?.(IPC_CHANNEL);
      ipcMain?.removeListener?.(IPC_MOVE_CHANNEL, handleMoveIpc);
    }
    ipcInstalled = false;
    activeMove = null;
    if (topmostTimer) clearInterval(topmostTimer);
    topmostTimer = null;
    if (window && !window.isDestroyed()) {
      window.removeAllListeners("close");
      window.destroy();
    }
    window = null;
  };

  return { beginMove, configureTopmost, create, dispose, endMove, enforceTopmost, hide, moveBy, register, setMode, show, status: () => status("status"), toggle, updateMove };
}

module.exports = {
  COMPACT_SIZE,
  DEFAULT_SHORTCUT,
  IPC_CHANNEL,
  IPC_MOVE_CHANNEL,
  TOPMOST_MAX_INTERVAL_MS,
  TOPMOST_MIN_INTERVAL_MS,
  anchorBounds,
  boundedPanelSize,
  clampBounds,
  clampPosition,
  createCompanionOverlay,
  overlayUrl,
  windowSize,
};
