const assert = require("assert");
const { EventEmitter } = require("events");
const { canonicalChromeUserAgent, chromeClientHint, createWebSurfaceManager, normalizedBounds, normalizedUrl } = require("./manager");

class FakeContents extends EventEmitter {
  constructor() { super(); this.url = ""; this.title = ""; this.loading = false; this.sent = []; this.inputEvents = []; this.emitInputEvents = false; this.userAgent = "Mozilla/5.0 Chrome/144 Safari/537.36 Electron/42.3.2 WASM Agent/0.1.0"; this.navigationHistory = { canGoBack: () => false, canGoForward: () => false }; }
  async loadURL(url) { this.url = url; }
  getURL() { return this.url; }
  getTitle() { return this.title; }
  isLoading() { return this.loading; }
  getUserAgent() { return this.userAgent; }
  setUserAgent(value) { this.userAgent = value; }
  setWindowOpenHandler(handler) { this.openHandler = handler; }
  reloadIgnoringCache() { this.hardReloaded = true; }
  focus() { this.focused = true; }
  sendInputEvent(event) { this.inputEvents.push(event); if (this.emitInputEvents) this.emit("before-mouse-event", {}, event); }
  async capturePage() { return { getSize: () => ({ width: 600, height: 400 }), toDataURL: () => "data:image/png;base64,c25hcHNob3Q=" }; }
  async executeJavaScript(source, userGesture) { this.executedJavaScript = { source, userGesture }; return { answer: 42 }; }
  stop() {}
  close() { this.closed = true; }
}

class FakeView {
  constructor(options) { this.options = options; this.webContents = new FakeContents(); }
  setVisible(value) { this.visible = value; }
  setBounds(value) { this.bounds = value; }
}

const fakeWebSession = {
  userAgent: "Mozilla/5.0 Chrome/144 Safari/537.36 Electron/42.3.2 WASM Agent/0.1.0",
  getUserAgent() { return this.userAgent; },
  setUserAgent(value) { this.userAgent = value; },
  clearCache: async () => { fakeWebSession.cacheCleared = true; },
  clearStorageData: async (options) => { fakeWebSession.clearedStorage = options.storages; },
  webRequest: { onBeforeSendHeaders(handler) { fakeWebSession.beforeSendHeaders = handler; } },
  setPermissionRequestHandler() {},
  on() {},
};
const fakeSession = { fromPartition: () => fakeWebSession };
let nowMs = Date.parse("2026-08-20T16:00:00.000Z");
let receiptSequence = 0;
const expiryTimers = [];
const manager = createWebSurfaceManager({
  WebContentsView: FakeView,
  session: fakeSession,
  shell: { openExternal() {} },
  chromeVersion: "148.0.7778.218",
  now: () => nowMs,
  receiptId: () => `receipt-${++receiptSequence}`,
  scheduleExpiry(callback, delay) {
    const timer = { callback, delay, cancelled: false, unref() {} };
    expiryTimers.push(timer);
    return timer;
  },
  cancelExpiry(timer) { timer.cancelled = true; },
});
const owner = {
  id: 1,
  focus() { this.focused = true; },
  contentView: { addChildView(view) { this.view = view; }, removeChildView() {} },
  webContents: { sent: [], send(channel, payload) { this.sent.push({ channel, payload }); } },
  isDestroyed: () => false,
};

assert.equal(normalizedUrl("https://example.com/path"), "https://example.com/path");
assert.throws(() => normalizedUrl("http://example.com"), /navigation_protocol_denied/);
assert.deepEqual(normalizedBounds({ x: 1.4, y: -2, width: 500.6, height: 300 }), { x: 1, y: 0, width: 501, height: 300 });
assert.equal(chromeClientHint("Mozilla/5.0 Chrome/148.0.0.0 Safari/537.36"), '"Google Chrome";v="148", "Chromium";v="148", "Not_A Brand";v="99"');
assert.equal(canonicalChromeUserAgent("148.0.7778.218"), "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.7778.218 Safari/537.36");

(async () => {
  const created = await manager.handle(owner, { operation: "create", args: { id: "browser", url: "https://example.com", bounds: { x: 10, y: 20, width: 600, height: 400 } } });
  assert.equal(created.id, "browser");
  assert.equal(created.url, "https://example.com/");
  assert.equal(created.inputReceiptEnabled, false);
  assert.equal(fakeWebSession.userAgent, "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.7778.218 Safari/537.36");
  assert.equal(fakeWebSession.cacheCleared, true);
  assert.deepEqual(fakeWebSession.clearedStorage, ["serviceworkers", "cachestorage"]);
  let sentHeaders;
  fakeWebSession.beforeSendHeaders({ requestHeaders: { "user-agent": "stale", Accept: "text/html" } }, ({ requestHeaders }) => { sentHeaders = requestHeaders; });
  assert.equal(sentHeaders["user-agent"], fakeWebSession.userAgent);
  assert.match(sentHeaders["Sec-CH-UA"], /Google Chrome.*148/);
  assert.deepEqual(owner.contentView.view.bounds, { x: 10, y: 20, width: 600, height: 400 });
  assert.equal((await manager.handle(owner, { operation: "visibility", args: { id: "browser", visible: true } })).visible, true);
  assert.equal(Object.hasOwn(manager.handle(owner, { operation: "status", args: { id: "browser" } }), "inputReceipt"), false);
  const contents = owner.contentView.view.webContents;
  contents.emit("before-mouse-event", {}, { type: "mouseDown", button: "left", x: 42, y: 31 });
  contents.emit("before-mouse-event", {}, { type: "mouseUp", button: "left", x: 42, y: 31 });
  const disabled = manager.handle(owner, { operation: "status", args: { id: "browser", includeInputReceipt: true } });
  assert.equal(disabled.inputReceiptEnabled, false);
  assert.equal(disabled.inputReceipt, null);
  assert.throws(() => manager.handle(owner, { operation: "input-receipt", args: { id: "browser", enabled: "yes" } }), /invalid_input_receipt_state/);
  assert.equal(manager.handle(owner, { operation: "input-receipt", args: { id: "browser", enabled: true } }).inputReceiptEnabled, true);
  assert.equal(owner.webContents.sent.at(-1).payload.type, "input-receipt");
  assert.equal(owner.webContents.sent.at(-1).payload.surface.inputReceiptEnabled, true);
  assert.equal((await manager.handle(owner, { operation: "create", args: { id: "browser" } })).inputReceiptEnabled, true);
  const sentBeforeInput = owner.webContents.sent.length;
  contents.emit("before-mouse-event", {}, { type: "mouseDown", button: "right", x: 42, y: 31 });
  contents.emit("before-mouse-event", {}, { type: "mouseUp", button: "right", x: 42, y: 31 });
  contents.emit("before-mouse-event", {}, { type: "mouseMove", button: "left", x: 42, y: 31 });
  let prevented = false;
  const nativeEvent = { preventDefault() { prevented = true; } };
  contents.emit("before-mouse-event", nativeEvent, { type: "mouseDown", button: "left", x: 42, y: 31, globalX: 900, text: "secret" });
  contents.emit("before-mouse-event", nativeEvent, { type: "mouseUp", button: "left", x: 42.4, y: 30.6, globalY: 800, modifiers: ["shift"] });
  const firstReceipt = manager.handle(owner, { operation: "status", args: { id: "browser", includeInputReceipt: true } }).inputReceipt;
  assert.deepEqual(firstReceipt, {
    schema: "hermes.wasm_agent.native_web_surface_input_receipt.v1",
    id: "receipt-1",
    surface_id: "browser",
    at: "2026-08-20T16:00:00.000Z",
    action: "pointer.primary_gesture",
    outcome: "observed_pre_dispatch",
    button: "left",
    x: 42,
    y: 31,
    viewport: { width: 600, height: 400 },
    current_document: true,
    input_source: "unattributed_native_input",
    redacted: true,
    age_ms: 0,
  });
  assert.equal(prevented, false);
  assert.equal(owner.webContents.sent.length, sentBeforeInput);
  contents.emit("before-mouse-event", {}, { type: "mouseDown", button: "left", x: 10, y: 10 });
  contents.emit("blur");
  contents.emit("before-mouse-event", {}, { type: "mouseUp", button: "left", x: 10, y: 10 });
  assert.equal(manager.handle(owner, { operation: "status", args: { id: "browser", includeInputReceipt: true } }).inputReceipt.id, "receipt-1");
  contents.emit("before-mouse-event", {}, { type: "mouseDown", button: "left", x: -100, y: 9999 });
  contents.emit("before-mouse-event", {}, { type: "mouseUp", button: "left", x: -100, y: 9999 });
  assert.equal(manager.handle(owner, { operation: "status", args: { id: "browser", includeInputReceipt: true } }).inputReceipt.id, "receipt-1");
  const firstExpiry = expiryTimers.find((timer) => !timer.cancelled);
  assert.equal(firstExpiry.delay, 120000);
  contents.emit("before-mouse-event", {}, { type: "mouseDown", button: "left", x: 11, y: 12 });
  nowMs += 120000;
  firstExpiry.callback();
  assert.equal(manager.handle(owner, { operation: "status", args: { id: "browser", includeInputReceipt: true } }).inputReceipt, null);
  contents.emit("before-mouse-event", {}, { type: "mouseUp", button: "left", x: 13, y: 14 });
  const secondReceipt = manager.handle(owner, { operation: "status", args: { id: "browser", includeInputReceipt: true } }).inputReceipt;
  assert.equal(secondReceipt.id, "receipt-2");
  assert.deepEqual({ x: secondReceipt.x, y: secondReceipt.y }, { x: 13, y: 14 });
  const secondExpiry = expiryTimers.find((timer) => !timer.cancelled && timer !== firstExpiry);
  nowMs -= 600000;
  assert.equal(manager.handle(owner, { operation: "status", args: { id: "browser", includeInputReceipt: true } }).inputReceipt.age_ms, 0);
  secondExpiry.callback();
  assert.equal(manager.handle(owner, { operation: "status", args: { id: "browser", includeInputReceipt: true } }).inputReceipt, null);
  nowMs = Date.parse("2026-08-20T16:05:00.000Z");
  contents.emit("before-mouse-event", {}, { type: "mouseDown", button: "left", x: 10, y: 10 });
  contents.emit("before-mouse-event", {}, { type: "mouseUp", button: "left", x: 10, y: 10 });
  contents.emit("did-start-navigation", { isMainFrame: true });
  assert.equal(manager.handle(owner, { operation: "status", args: { id: "browser", includeInputReceipt: true } }).inputReceipt, null);
  contents.emit("before-mouse-event", {}, { type: "mouseDown", button: "left", x: 10, y: 10 });
  contents.emit("before-mouse-event", {}, { type: "mouseUp", button: "left", x: 10, y: 10 });
  assert.ok(manager.handle(owner, { operation: "status", args: { id: "browser", includeInputReceipt: true } }).inputReceipt);
  assert.equal(manager.handle(owner, { operation: "input-receipt", args: { id: "browser", enabled: false } }).inputReceiptEnabled, false);
  assert.equal(manager.handle(owner, { operation: "status", args: { id: "browser", includeInputReceipt: true } }).inputReceipt, null);
  contents.emit("before-mouse-event", {}, { type: "mouseDown", button: "left", x: 20, y: 20 });
  contents.emit("before-mouse-event", {}, { type: "mouseUp", button: "left", x: 20, y: 20 });
  assert.equal(manager.handle(owner, { operation: "status", args: { id: "browser", includeInputReceipt: true } }).inputReceipt, null);
  assert.throws(() => manager.handle(owner, { operation: "pointer-dispatch", args: { id: "browser", x: 20, y: 20, commandId: "command-disabled" } }), /input_receipt_not_enabled/);
  manager.handle(owner, { operation: "input-receipt", args: { id: "browser", enabled: true } });
  contents.loading = true;
  contents.emit("did-start-loading");
  assert.equal(manager.handle(owner, { operation: "status", args: { id: "browser" } }).status, "loading");
  contents.loading = false;
  assert.equal(manager.handle(owner, { operation: "status", args: { id: "browser" } }).status, "ready");
  assert.throws(() => manager.handle(owner, { operation: "pointer-dispatch", args: { id: "browser", x: -1, y: 20, commandId: "command-current-ready" } }), /invalid_pointer_dispatch_position/);
  contents.emit("did-finish-load");
  assert.throws(() => manager.handle(owner, { operation: "pointer-dispatch", args: { id: "browser", x: -1, y: 20, commandId: "command-invalid-position" } }), /invalid_pointer_dispatch_position/);
  assert.throws(() => manager.handle(owner, { operation: "pointer-dispatch", args: { id: "browser", x: 20, y: 20, commandId: "invalid id" } }), /invalid_pointer_dispatch_command_id/);
  const dispatched = manager.handle(owner, { operation: "pointer-dispatch", args: { id: "browser", x: 20, y: 21, commandId: "command-1" } });
  assert.deepEqual(dispatched, {
    schema: "hermes.wasm_agent.native_web_surface_pointer_dispatch.v1",
    ok: true,
    surface_id: "browser",
    command_id: "command-1",
    input_source: "electron_synthetic",
    dispatch_accepted: true,
    receipt_observed: false,
    receipt_id: null,
    current_document: true,
    redacted: true,
  });
  assert.equal(owner.focused, true);
  assert.equal(contents.focused, true);
  assert.deepEqual(contents.inputEvents.slice(-2), [
    { type: "mouseDown", button: "left", clickCount: 1, x: 20, y: 21 },
    { type: "mouseUp", button: "left", clickCount: 1, x: 20, y: 21 },
  ]);
  assert.equal(manager.handle(owner, { operation: "status", args: { id: "browser", includeInputReceipt: true } }).inputReceipt, null);
  contents.emit("before-mouse-event", {}, contents.inputEvents.at(-2));
  contents.emit("before-mouse-event", {}, contents.inputEvents.at(-1));
  const correlatedReceipt = manager.handle(owner, { operation: "status", args: { id: "browser", includeInputReceipt: true } }).inputReceipt;
  assert.equal(correlatedReceipt.input_source, "electron_synthetic");
  assert.equal(correlatedReceipt.command_id, "command-1");
  contents.emitInputEvents = true;
  const observedDispatch = manager.handle(owner, { operation: "pointer-dispatch", args: { id: "browser", x: 22, y: 23, commandId: "command-2" } });
  assert.equal(observedDispatch.receipt_observed, true);
  assert.equal(observedDispatch.receipt_id, "receipt-6");
  const observedReceipt = manager.handle(owner, { operation: "status", args: { id: "browser", includeInputReceipt: true } }).inputReceipt;
  assert.equal(observedReceipt.input_source, "electron_synthetic");
  assert.equal(observedReceipt.command_id, "command-2");
  const snapshot = await manager.handle(owner, { operation: "snapshot", args: { id: "browser" } });
  assert.deepEqual({ status: snapshot.status, mime: snapshot.mime, width: snapshot.width, height: snapshot.height }, { status: "captured", mime: "image/png", width: 600, height: 400 });
  assert.match(snapshot.dataUrl, /^data:image\/png;base64,/);
  const javascript = await manager.handle(owner, { operation: "javascript-execute-unrestricted", args: { id: "browser", source: "({answer: 42})", commandId: "js-command-1" } });
  assert.deepEqual(owner.contentView.view.webContents.executedJavaScript, { source: "({answer: 42})", userGesture: true });
  assert.deepEqual(javascript, {
    schema: "hermes.wasm_agent.native_web_surface_javascript_execution.v1",
    ok: true,
    surface_id: "browser",
    command_id: "js-command-1",
    url: "https://example.com/",
    result_json: '{"answer":42}',
    result_bytes: 13,
    result_truncated: false,
    error: "",
    stack: "",
    execution_scope: "web_contents_main_world",
  });
  assert.equal(owner.contentView.view.webContents.executedJavaScript.userGesture, true);
  assert.equal(owner.contentView.view.webContents.executedJavaScript.source, "({answer: 42})");
  manager.handle(owner, { operation: "action", args: { id: "browser", action: "reload" } });
  assert.equal(owner.contentView.view.webContents.hardReloaded, true);
  owner.contentView.view.webContents.loadURL = async (url) => { owner.contentView.view.webContents.url = url; throw Object.assign(new Error("ERR_ABORTED"), { errno: -3 }); };
  assert.equal((await manager.handle(owner, { operation: "navigate", args: { id: "browser", url: "https://www.google.com/" } })).url, "https://www.google.com/");
  owner.contentView.view.webContents.loadURL = async () => { throw Object.assign(new Error("ERR_FAILED"), { errno: -2 }); };
  await assert.rejects(manager.handle(owner, { operation: "navigate", args: { id: "browser", url: "https://example.org/" } }), /ERR_FAILED/);
  assert.equal(manager.handle(owner, { operation: "close", args: { id: "browser" } }).status, "closed");
  assert.equal(owner.contentView.view.webContents.closed, true);
  console.log("native web surface manager tests passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
