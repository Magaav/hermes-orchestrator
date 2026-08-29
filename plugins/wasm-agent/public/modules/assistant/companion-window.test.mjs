import assert from "node:assert/strict";
import fs from "node:fs/promises";

const source = await fs.readFile(new URL("./companion-window.js", import.meta.url), "utf8");
const companionCss = await fs.readFile(new URL("./companion-window.css", import.meta.url), "utf8");
const sharedCss = await fs.readFile(new URL("../../styles.css", import.meta.url), "utf8");
const appSource = await fs.readFile(new URL("../../app.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { companionWindowMode, installAgentPanelDragging, isAgentCompactViewport, isNativeCompanionWindow, nativeCompanionPanelSize, syncNativeCompanionTopmostPolicy } = await import(moduleUrl);

assert.equal(isNativeCompanionWindow("https://wa.colmeio.com/home?native=electron&companion=overlay"), true);
assert.equal(isNativeCompanionWindow("https://wa.colmeio.com/home?native=electron"), false);
assert.equal(isAgentCompactViewport(true, "https://wa.colmeio.com/home?native=electron&companion=overlay"), false);
assert.deepEqual(companionWindowMode(false), { mode: "compact", panel_width: 430, panel_height: 620 });
assert.deepEqual(companionWindowMode(true, { panelWidth: 600, panelHeight: 800 }), { mode: "expanded", panel_width: 600, panel_height: 800 });
assert.deepEqual(companionWindowMode(true, { panelWidth: 1, panelHeight: 9999 }), { mode: "expanded", panel_width: 320, panel_height: 1200 });
assert.deepEqual(nativeCompanionPanelSize({ panelWidth: 320, panelHeight: 420 }, "https://wa.colmeio.com/home?native=electron&companion=overlay"), { width: 430, height: 620 });
assert.deepEqual(nativeCompanionPanelSize({ width: 600, height: 800 }, "https://wa.colmeio.com/home?native=electron&companion=overlay"), { width: 600, height: 800 });
assert.equal(nativeCompanionPanelSize({ width: 320, height: 420 }, "https://wa.colmeio.com/home"), null);
assert.match(sharedCss, /\.agent-avatar-button\s*\{[\s\S]*width: 58px;[\s\S]*height: 58px;/);
assert.doesNotMatch(companionCss, /\.agent-avatar-core\s*\{/);
assert.match(appSource, /if \(isAgentCompactViewport\(isCompactViewport\(\)\)\) \{[\s\S]*panel\.dataset\.x = "fullscreen"/);
assert.match(source, /requestAnimationFrame\(flush\)/);

class FakeEventTarget {
  constructor() { this.listeners = new Map(); }
  addEventListener(type, listener, options = {}) {
    const entries = this.listeners.get(type) || [];
    entries.push({ listener, once: Boolean(options?.once) });
    this.listeners.set(type, entries);
  }
  removeEventListener(type, listener) {
    this.listeners.set(type, (this.listeners.get(type) || []).filter((entry) => entry.listener !== listener));
  }
  emit(type, event = {}) {
    const entries = [...(this.listeners.get(type) || [])];
    for (const entry of entries) {
      entry.listener(event);
      if (entry.once) this.removeEventListener(type, entry.listener);
    }
  }
  setPointerCapture() {}
}

const savedGlobals = new Map();
for (const key of ["location", "wasmAgentNative", "addEventListener", "removeEventListener", "requestAnimationFrame", "cancelAnimationFrame"]) {
  savedGlobals.set(key, { exists: Object.hasOwn(globalThis, key), value: globalThis[key] });
}
const windowEvents = new FakeEventTarget();
let nextFrame = 1;
const frames = new Map();
const bridgeCalls = { begin: [], update: [], end: [], topmost: [], legacy: 0 };
Object.defineProperty(globalThis, "location", { configurable: true, value: { href: "https://wa.colmeio.com/home?native=electron&companion=overlay" } });
globalThis.wasmAgentNative = { companion: {
  configureTopmost: (value) => { bridgeCalls.topmost.push(value); },
  beginMove: (value) => { bridgeCalls.begin.push(value); },
  updateMove: (value) => { bridgeCalls.update.push(value); },
  moveBy: () => { bridgeCalls.legacy += 1; },
  endMove: (value) => { bridgeCalls.end.push(value); },
} };
assert.equal(syncNativeCompanionTopmostPolicy({ enabled: true, interval_ms: 900 }), true);
assert.deepEqual(bridgeCalls.topmost, [{ enabled: true, interval_ms: 900 }]);
globalThis.addEventListener = windowEvents.addEventListener.bind(windowEvents);
globalThis.removeEventListener = windowEvents.removeEventListener.bind(windowEvents);
globalThis.requestAnimationFrame = (callback) => { const id = nextFrame++; frames.set(id, callback); return id; };
globalThis.cancelAnimationFrame = (id) => frames.delete(id);

const dragHandle = new FakeEventTarget();
const bodyClasses = new Set();
const records = [];
installAgentPanelDragging({
  panel: { querySelector: () => dragHandle },
  body: { classList: { add: (value) => bodyClasses.add(value), remove: (value) => bodyClasses.delete(value) } },
  state: { agentDragSuppressClick: false },
  isPrimaryPointer: () => true,
  moveAgentGroupFromPanelRect: () => assert.fail("native drag must not run PWA panel movement"),
  placeAgentPanel: () => {},
  saveAgentLayout: () => {},
  recordUserEvent: (...args) => records.push(args),
});
dragHandle.emit("pointerdown", {
  pointerId: 1, screenX: 100, screenY: 100, preventDefault: () => assert.fail("header buttons must retain their pointer event"),
  target: { closest: () => ({ id: "agentSessionsButton" }) },
});
assert.equal(bridgeCalls.begin.length, 0, "header buttons must not begin native dragging");
dragHandle.emit("pointerdown", {
  pointerId: 2, screenX: 100, screenY: 100, preventDefault: () => {},
  target: { closest: () => null },
});
assert.deepEqual(bridgeCalls.begin, [{ session_id: "pointer-1", pointer_x: 100, pointer_y: 100 }]);
windowEvents.emit("pointermove", { pointerId: 2, screenX: 125, screenY: 112 });
for (const callback of [...frames.values()]) callback();
frames.clear();
assert.deepEqual(bridgeCalls.update, [{ session_id: "pointer-1", pointer_x: 125, pointer_y: 112 }], "one animation frame must carry its captured pointer position");
windowEvents.emit("pointerup", { pointerId: 2 });
assert.deepEqual(bridgeCalls.end, [{ moved: true, session_id: "pointer-1", pointer_x: 125, pointer_y: 112 }]);
assert.equal(bridgeCalls.update.length, 2, "drag end must apply the last captured pointer position");
assert.equal(bridgeCalls.legacy, 0, "the session protocol must replace incremental deltas");
assert.equal(bodyClasses.has("is-agent-dragging"), false);
assert.equal(records.length, 1);

dragHandle.emit("pointerdown", {
  pointerId: 3, screenX: 140, screenY: 120, preventDefault: () => {},
  target: { closest: () => null },
});
windowEvents.emit("pointermove", { pointerId: 3, screenX: 150, screenY: 130 });
for (const callback of [...frames.values()]) callback();
frames.clear();
const updatesBeforeCaptureLoss = bridgeCalls.update.length;
dragHandle.emit("lostpointercapture", { pointerId: 3 });
windowEvents.emit("pointermove", { pointerId: 3, screenX: 180, screenY: 160 });
assert.equal(bridgeCalls.update.length, updatesBeforeCaptureLoss + 1, "capture loss must apply only the final sample and remove the move listener");
assert.equal(bodyClasses.has("is-agent-dragging"), false);

for (const [key, saved] of savedGlobals) {
  if (saved.exists) Object.defineProperty(globalThis, key, { configurable: true, writable: true, value: saved.value });
  else delete globalThis[key];
}

console.log("companion window module tests passed");
