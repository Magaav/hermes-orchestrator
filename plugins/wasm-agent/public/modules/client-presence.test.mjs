import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const storage = new Map([["wasmAgent.frontierProtocol", "v6"]]);
let submitted = 0;
const agentInputPrototype = { set value(value) { this._value = value; }, get value() { return this._value || ""; } };
const agentInput = Object.assign(Object.create(agentInputPrototype), { _value: "", dispatchEvent() {} });
const agentForm = { requestSubmit() { submitted += 1; } };
const agentOverlay = { dataset: { sessionId: "old-session" } };
const agentNewSessionButton = { click() { agentInput._value = ""; agentOverlay.dataset.sessionId = "new-session"; } };
const context = vm.createContext({
  window: { wasmAgentNative: { runtime: "electron" } },
  document: {
    hidden: false,
    querySelectorAll() { return []; },
    querySelector(selector) { return ({ "#agentInput": agentInput, "#agentForm": agentForm, "#agentOverlay": agentOverlay, "#agentNewSessionButton": agentNewSessionButton })[selector] || null; },
    addEventListener() {},
  },
  location: { search: "", href: "https://wa.colmeio.com/home?native=electron", origin: "https://wa.colmeio.com" },
  localStorage: { getItem(key) { return storage.get(key) || null; } },
  URLSearchParams,
  CustomEvent: class CustomEvent { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } },
  Event: class Event { constructor(type, options = {}) { this.type = type; this.bubbles = options.bubbles; } },
  InputEvent: class InputEvent { constructor(type, options = {}) { this.type = type; Object.assign(this, options); } },
  addEventListener() {},
  dispatchEvent() {},
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  setInterval() { return 1; },
  clearInterval() {},
  setTimeout,
  clearTimeout,
  console,
});
const modules = new Map();
for (const [specifier, relative] of [
  ["./client-observability.js", "./client-observability.js"],
  ["./master-frontier/source-investigation.js?v=20260806-frontier-protocol1", "./master-frontier/source-investigation.js"],
  ["./runtime-refresh.js?v=20260826-runtime-refresh1", "./runtime-refresh.js"],
]) {
  modules.set(specifier, new vm.SourceTextModule(fs.readFileSync(new URL(relative, import.meta.url), "utf8"), { context }));
}
const parsed = new vm.SourceTextModule(fs.readFileSync(new URL("./client-presence.js", import.meta.url), "utf8"), { context });
await parsed.link((specifier) => modules.get(specifier));
await parsed.evaluate();
const module = parsed.namespace;

assert.equal(module.liveClientRuntimeType(), "electron");
const capabilities = Array.from(module.liveClientCapabilities());
assert.equal(capabilities.some((id) => id.startsWith("observe.browser.") || id.startsWith("control.browser.")), false);
assert.equal(capabilities.includes("control.runtime.refresh"), true);
assert.equal(capabilities.includes("control.agent.prompt.submit"), true);
assert.equal(capabilities.includes("control.agent.session.new"), true);
assert.deepEqual(JSON.parse(JSON.stringify(await module.executeLiveClientCommand({ id: "prompt", type: "agent_prompt_submit", payload: { message: "hello" } }))), {
  ok: true,
  submitted: true,
  message_chars: 5,
  proof: ["client.agent.prompt.submitted"],
});
assert.equal(agentInput.value, "hello");
assert.equal(submitted, 1);
assert.deepEqual(JSON.parse(JSON.stringify(await module.executeLiveClientCommand({ id: "session", type: "agent_session_new", payload: {} }))), {
  ok: true,
  created: true,
  before: "old-session",
  after: "new-session",
  input_empty: true,
  proof: ["client.agent.session.clean"],
});
assert.deepEqual(JSON.parse(JSON.stringify(await module.executeLiveClientCommand({ id: "legacy", type: "browser_navigate", payload: {} }))), {
  ok: false,
  error: "unsupported_pwa_control_command",
});

console.log("client presence excludes removed Electron Browser capabilities");
