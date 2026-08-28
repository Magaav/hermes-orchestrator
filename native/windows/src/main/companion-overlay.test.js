"use strict";

const assert = require("assert");
const { COMPACT_SIZE, anchorBounds, clampPosition, createCompanionOverlay, overlayUrl, windowSize } = require("./companion-overlay");

assert.strictEqual(overlayUrl("https://wa.colmeio.com"), "https://wa.colmeio.com/home?native=electron&companion=overlay");

class FakeWindow {
  constructor(options) {
    this.options = options; this.visible = false; this.destroyed = false; this.handlers = {};
    this.bounds = { x: options.x || 0, y: options.y || 0, width: options.width, height: options.height };
    this.alwaysOnTop = false; this.moveTopCalls = 0;
    this.webContents = { insertCSS: async () => {}, executeJavaScript: async () => true, on: (name, fn) => { this.handlers[name] = fn; }, setWindowOpenHandler: () => {} };
  }
  isDestroyed() { return this.destroyed; }
  isVisible() { return this.visible; }
  show() { this.visible = true; }
  hide() { this.visible = false; }
  focus() {}
  getBounds() { return { ...this.bounds }; }
  setBounds(bounds) { this.bounds = { ...bounds }; }
  setAlwaysOnTop(value) { this.alwaysOnTop = value; }
  isAlwaysOnTop() { return this.alwaysOnTop; }
  moveTop() { this.moveTopCalls += 1; }
  setVisibleOnAllWorkspaces() {}
  on(name, fn) { this.handlers[name] = fn; }
  removeAllListeners() {}
  destroy() { this.destroyed = true; }
  async loadURL(url) { this.url = url; }
}

let shortcut;
const statuses = [];
const overlay = createCompanionOverlay({
  BrowserWindow: FakeWindow,
  globalShortcut: { register: (_key, fn) => { shortcut = fn; return true; }, unregister: () => {} },
  origin: "https://wa.colmeio.com",
  onStatus: (value) => statuses.push(value),
});
assert.strictEqual(overlay.register().shortcutRegistered, true);
assert.strictEqual(overlay.show().visible, true);
assert.strictEqual(overlay.create().__wasmAgentCompanionOverlay, true);
assert.strictEqual(overlay.create().options.width, COMPACT_SIZE);
assert.strictEqual(overlay.create().options.hasShadow, false);
assert.strictEqual(overlay.status().topmost.active, true);
assert.strictEqual(overlay.configureTopmost({ enabled: true, interval_ms: 10 }).topmost.interval_ms, 250);
assert(overlay.create().moveTopCalls >= 1, "topmost configuration must promote without focusing");
assert.strictEqual(overlay.setMode("expanded", { panel_width: 430, panel_height: 620 }).mode, "expanded");
assert.deepStrictEqual(windowSize("expanded"), { width: 516, height: 620 });
assert.deepStrictEqual(anchorBounds({ x: 100, y: 100, width: 86, height: 86 }, { width: 516, height: 620 }), { x: -330, y: -434, width: 516, height: 620 });
assert.deepStrictEqual(
  clampPosition(
    { x: 200, y: 200, width: 516, height: 620 },
    { getDisplayMatching: () => ({ workArea: { x: 0, y: 0, width: 400, height: 500 } }) },
  ),
  { x: 0, y: 0, width: 516, height: 620 },
  "drag clamping must never resize the chat window",
);
const statusCountBeforeMove = statuses.length;
assert.strictEqual(overlay.moveBy({ x: 12, y: -8 }).moved, true);
assert.strictEqual(statuses.length, statusCountBeforeMove, "drag frames must not emit audit/status events");
shortcut();
assert.strictEqual(overlay.status().visible, false);
overlay.dispose();

let cursor = { x: 200, y: 200 };
const sessionOverlay = createCompanionOverlay({
  BrowserWindow: FakeWindow,
  origin: "https://wa.colmeio.com",
  screen: {
    getCursorScreenPoint: () => ({ ...cursor }),
    getDisplayMatching: () => ({ workArea: { x: 0, y: 0, width: 1920, height: 1080 } }),
  },
});
const sessionWindow = sessionOverlay.create();
sessionOverlay.setMode("expanded");
const dragStart = sessionWindow.getBounds();
assert.strictEqual(sessionOverlay.beginMove({ session_id: "drag-1", pointer_x: 200, pointer_y: 200 }).moving, true);
cursor = { x: 245, y: 218 };
assert.strictEqual(sessionOverlay.updateMove({ session_id: "drag-1", pointer_x: 245, pointer_y: 218 }).moved, true);
assert.deepStrictEqual(sessionWindow.getBounds(), { ...dragStart, x: dragStart.x + 45, y: dragStart.y + 18 });
assert.strictEqual(sessionOverlay.updateMove({ session_id: "old-drag", pointer_x: 900, pointer_y: 900 }).error, "companion_move_stale");
assert.strictEqual(sessionOverlay.endMove({ moved: true, session_id: "drag-1", pointer_x: 245, pointer_y: 218 }).mode, "expanded");
const dragEnd = sessionWindow.getBounds();
cursor = { x: 400, y: 400 };
assert.strictEqual(sessionOverlay.updateMove().error, "companion_move_inactive");
assert.deepStrictEqual(sessionWindow.getBounds(), dragEnd, "stale updates after release must not move the window");
sessionOverlay.dispose();
console.log("companion overlay tests passed");
