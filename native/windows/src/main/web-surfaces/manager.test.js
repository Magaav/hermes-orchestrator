const assert = require("assert");
const { EventEmitter } = require("events");
const { createWebSurfaceManager, normalizedBounds, normalizedUrl } = require("./manager");

class FakeContents extends EventEmitter {
  constructor() { super(); this.url = ""; this.title = ""; this.loading = false; this.sent = []; this.userAgent = "Mozilla/5.0 Chrome/144 Safari/537.36 Electron/42.3.2 WASM Agent/0.1.0"; this.navigationHistory = { canGoBack: () => false, canGoForward: () => false }; }
  async loadURL(url) { this.url = url; }
  getURL() { return this.url; }
  getTitle() { return this.title; }
  isLoading() { return this.loading; }
  getUserAgent() { return this.userAgent; }
  setUserAgent(value) { this.userAgent = value; }
  setWindowOpenHandler(handler) { this.openHandler = handler; }
  reload() {}
  stop() {}
  close() { this.closed = true; }
}

class FakeView {
  constructor(options) { this.options = options; this.webContents = new FakeContents(); }
  setVisible(value) { this.visible = value; }
  setBounds(value) { this.bounds = value; }
}

const fakeSession = { fromPartition: () => ({ setPermissionRequestHandler() {}, on() {} }) };
const manager = createWebSurfaceManager({ WebContentsView: FakeView, session: fakeSession, shell: { openExternal() {} } });
const owner = {
  id: 1,
  contentView: { addChildView(view) { this.view = view; }, removeChildView() {} },
  webContents: { send() {} },
  isDestroyed: () => false,
};

assert.equal(normalizedUrl("https://example.com/path"), "https://example.com/path");
assert.throws(() => normalizedUrl("http://example.com"), /navigation_protocol_denied/);
assert.deepEqual(normalizedBounds({ x: 1.4, y: -2, width: 500.6, height: 300 }), { x: 1, y: 0, width: 501, height: 300 });

(async () => {
  const created = await manager.handle(owner, { operation: "create", args: { id: "browser", url: "https://example.com", bounds: { x: 10, y: 20, width: 600, height: 400 } } });
  assert.equal(created.id, "browser");
  assert.equal(created.url, "https://example.com/");
  assert.equal(owner.contentView.view.webContents.userAgent, "Mozilla/5.0 Chrome/144 Safari/537.36");
  assert.deepEqual(owner.contentView.view.bounds, { x: 10, y: 20, width: 600, height: 400 });
  assert.equal((await manager.handle(owner, { operation: "visibility", args: { id: "browser", visible: true } })).visible, true);
  owner.contentView.view.webContents.loadURL = async (url) => { owner.contentView.view.webContents.url = url; throw Object.assign(new Error("ERR_ABORTED"), { errno: -3 }); };
  assert.equal((await manager.handle(owner, { operation: "navigate", args: { id: "browser", url: "https://www.google.com/" } })).url, "https://www.google.com/");
  owner.contentView.view.webContents.loadURL = async () => { throw Object.assign(new Error("ERR_FAILED"), { errno: -2 }); };
  await assert.rejects(manager.handle(owner, { operation: "navigate", args: { id: "browser", url: "https://example.org/" } }), /ERR_FAILED/);
  assert.equal(manager.handle(owner, { operation: "close", args: { id: "browser" } }).status, "closed");
  assert.equal(owner.contentView.view.webContents.closed, true);
  console.log("native web surface manager tests passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
