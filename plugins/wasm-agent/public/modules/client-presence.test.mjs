import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const storage = new Map([["wasmAgent.frontierProtocol", "v5"]]);
const nativeCalls = [];
const source = fs.readFileSync(new URL("./client-presence.js", import.meta.url), "utf8");
const context = vm.createContext({
  window: { wasmAgentNative: { runtime: "electron", webSurfaces: { async invoke(operation, args) {
    nativeCalls.push({ operation, args });
    if (operation === "capabilities") return { capabilities: ["web_surface.input_receipt", "web_surface.pointer.dispatch", "web_surface.javascript.execute.unrestricted"] };
    if (operation === "input-receipt") return { inputReceiptEnabled: args.enabled };
    if (operation === "pointer-dispatch") return {
      schema: "hermes.wasm_agent.native_web_surface_pointer_dispatch.v1",
      ok: true,
      surface_id: "browser",
      command_id: args.commandId,
      input_source: "electron_synthetic",
      dispatch_accepted: true,
      receipt_observed: false,
      receipt_id: null,
      current_document: true,
      redacted: true,
    };
    if (operation === "javascript-execute-unrestricted") return { schema: "hermes.wasm_agent.native_web_surface_javascript_execution.v1", ok: true, surface_id: "browser", command_id: args.commandId, result_json: "42" };
    throw new Error(`unexpected native operation: ${operation}`);
  } } } },
  document: {
    hidden: false,
    querySelectorAll() { return []; },
    querySelector() { return null; },
  },
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
  if (specifier === "./client-observability.js?v=20260820-native-input-receipt2") return observability;
  if (specifier === "./master-frontier/source-investigation.js?v=20260806-frontier-protocol1") return selector;
  throw new Error(`unexpected import: ${specifier}`);
});
await parsed.evaluate();
const module = parsed.namespace;

assert.equal(module.liveClientRuntimeType(), "electron");
assert.deepEqual(Array.from(module.liveClientCapabilities()), [
  "observe.status",
  "observe.analytics.on_demand",
  "observe.browser.inspect",
  "control.widget.open",
  "control.space.open",
  "control.browser.navigate",
  "control.navigate",
  "control.update.apply",
  "control.reload",
]);
await module.primeNativeWebSurfaceCapabilities();
assert.deepEqual(JSON.parse(JSON.stringify(nativeCalls)), [{ operation: "capabilities", args: {} }]);
assert.deepEqual(Array.from(module.liveClientCapabilities()), [
  "observe.status",
  "observe.analytics.on_demand",
  "observe.browser.inspect",
  "control.widget.open",
  "control.space.open",
  "control.browser.navigate",
  "control.navigate",
  "control.update.apply",
  "control.reload",
  "control.browser.input_receipt",
  "control.browser.pointer.dispatch",
  "control.browser.javascript.execute.unrestricted",
]);
assert.deepEqual(JSON.parse(JSON.stringify(await module.executeLiveClientCommand({ id: "enable-1", type: "browser_input_receipt", payload: { enabled: "yes" } }))), {
  ok: false,
  error: "invalid_input_receipt_state",
});
assert.deepEqual(JSON.parse(JSON.stringify(await module.executeLiveClientCommand({ id: "enable-2", type: "browser_input_receipt", payload: { enabled: true } }))), {
  ok: true,
  browser: { id: "browser", input_receipt_state: "enabled" },
  proof: ["native.web_surface.input_receipt_mode"],
});
assert.deepEqual(JSON.parse(JSON.stringify(nativeCalls.at(-1))), { operation: "input-receipt", args: { id: "browser", enabled: true } });
assert.deepEqual(JSON.parse(JSON.stringify(await module.executeLiveClientCommand({ id: "dispatch bad", type: "browser_pointer_dispatch", payload: { x: 20, y: 21 } }))), {
  ok: false,
  error: "invalid_pointer_dispatch_command_id",
});
const pointerResult = await module.executeLiveClientCommand({ id: "dispatch-1", type: "browser_pointer_dispatch", payload: { x: 20, y: 21 } });
assert.equal(pointerResult.ok, true);
assert.equal(pointerResult.browser.pointer_dispatch.input_source, "electron_synthetic");
assert.deepEqual(JSON.parse(JSON.stringify(nativeCalls.at(-1))), { operation: "pointer-dispatch", args: { id: "browser", x: 20, y: 21, commandId: "dispatch-1" } });
const javascriptResult = await module.executeLiveClientCommand({ id: "javascript-1", type: "browser_javascript_execute_unrestricted", payload: { javascript: "21 * 2" } });
assert.equal(javascriptResult.ok, true);
assert.equal(javascriptResult.browser.javascript_execution.result_json, "42");
assert.deepEqual(JSON.parse(JSON.stringify(nativeCalls.at(-1))), { operation: "javascript-execute-unrestricted", args: { id: "browser", source: "21 * 2", commandId: "javascript-1" } });
let openCalls = 0;
const openControls = { async openWidget() { openCalls += 1; return { opened: true, alreadyOpen: openCalls > 1 }; } };
assert.deepEqual(JSON.parse(JSON.stringify(await module.executeLiveClientCommand({ id: "open-1", type: "open_widget", payload: { widget_id: "browser" } }, openControls))), {
  ok: true, widget_id: "browser", opened: true,
});
assert.deepEqual(JSON.parse(JSON.stringify(await module.executeLiveClientCommand({ id: "open-2", type: "open_widget", payload: { widget_id: "browser" } }, openControls))), {
  ok: true, widget_id: "browser", opened: true, already_open: true,
});
assert.equal(openCalls, 2);
const spaceCalls = [];
assert.deepEqual(JSON.parse(JSON.stringify(await module.executeLiveClientCommand(
  { id: "space-1", type: "space_open", payload: { space: "Realure" } },
  { async openSpace(reference) { spaceCalls.push(reference); return { space_id: "space-realure", space_name: "Realure", opened: true, already_open: false }; } },
))), { ok: true, space_id: "space-realure", space_name: "Realure", opened: true, already_open: false, proof: ["client.ack", "client.space.active"] });
assert.deepEqual(spaceCalls, ["Realure"]);
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
assert.deepEqual(Array.from(module.liveClientCapabilities()), ["observe.status", "observe.analytics.on_demand", "observe.cdp.on_demand", "control.space.open", "control.navigate", "control.reload"]);
delete context.window.WasmAgentNative;
assert.equal(module.liveClientRuntimeType(), "pwa");
assert.deepEqual(Array.from(module.liveClientCapabilities()), ["observe.status", "observe.analytics.on_demand", "observe.cdp.external_on_demand", "control.space.open", "control.navigate", "control.reload"]);

console.log("client presence capability tests passed");
