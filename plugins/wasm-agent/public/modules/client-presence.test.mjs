import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const storage = new Map([["wasmAgent.frontierProtocol", "v5"]]);
const source = fs.readFileSync(new URL("./client-presence.js", import.meta.url), "utf8");
const context = vm.createContext({
  window: { wasmAgentNative: { runtime: "electron", webSurfaces: { invoke() {} } } },
  document: { querySelectorAll() { return []; }, querySelector() { return null; } },
  location: { search: "", href: "https://wa.colmeio.com/home?native=electron", origin: "https://wa.colmeio.com" },
  localStorage: { getItem(key) { return storage.get(key) || null; } },
  URLSearchParams,
  console,
});
const observabilitySource = fs.readFileSync(new URL("./client-observability.js", import.meta.url), "utf8");
const observability = new vm.SourceTextModule(observabilitySource, { context });
const selectorSource = fs.readFileSync(new URL("./master-frontier/source-investigation.js", import.meta.url), "utf8");
const selector = new vm.SourceTextModule(selectorSource, { context });
const parsed = new vm.SourceTextModule(source, { context });
await parsed.link((specifier) => {
  if (specifier === "./client-observability.js") return observability;
  if (specifier === "./master-frontier/source-investigation.js?v=20260806-frontier-protocol1") return selector;
  throw new Error(`unexpected import: ${specifier}`);
});
await parsed.evaluate();
const module = parsed.namespace;

assert.equal(module.liveClientRuntimeType(), "electron");
assert.deepEqual(Array.from(module.liveClientCapabilities()), [
  "observe.status",
  "observe.analytics.on_demand",
  "control.widget.open",
  "control.browser.navigate",
  "control.update.apply",
  "control.reload",
]);
assert.deepEqual(JSON.parse(JSON.stringify(module.liveClientUiSummary())), {
  canvas_app_ids: [],
  open_widget_ids: [],
  widget_icons: [],
  widget_windows: [],
  resize_directions: [],
  frontier_protocol: { effective: "v6", stored: "legacy" },
  shell_overlay: { avatar_chat_open: false, suppressed_native_widget_ids: [] },
});
storage.set("wasmAgent.frontierProtocol", "explicit:v5");
assert.deepEqual(JSON.parse(JSON.stringify(module.liveClientUiSummary().frontier_protocol)), { effective: "v5", stored: "explicit" });

delete context.window.wasmAgentNative;
context.window.WasmAgentNative = {};
assert.equal(module.liveClientRuntimeType(), "android-kotlin");
assert.deepEqual(Array.from(module.liveClientCapabilities()), ["observe.status", "observe.analytics.on_demand", "observe.cdp.on_demand", "control.navigate", "control.reload"]);
delete context.window.WasmAgentNative;
assert.equal(module.liveClientRuntimeType(), "pwa");
assert.deepEqual(Array.from(module.liveClientCapabilities()), ["observe.status", "observe.analytics.on_demand", "observe.cdp.external_on_demand", "control.navigate", "control.reload"]);

console.log("client presence capability tests passed");
