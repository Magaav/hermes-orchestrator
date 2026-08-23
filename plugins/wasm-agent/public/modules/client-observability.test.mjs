import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

class TestTarget extends EventTarget {}
const NOW = Date.parse("2026-08-20T16:00:00.000Z");
class FixedDate extends Date {
  constructor(...args) { super(...(args.length ? args : [NOW])); }
  static now() { return NOW; }
}
const target = new TestTarget();
const document = new TestTarget();
const context = vm.createContext({
  addEventListener: target.addEventListener.bind(target),
  dispatchEvent: target.dispatchEvent.bind(target),
  document,
  location: { href: "https://wa.colmeio.com/home?native=electron" },
  URL,
  Date: FixedDate,
  setTimeout,
  clearTimeout,
  console,
});

const source = fs.readFileSync(new URL("./client-observability.js", import.meta.url), "utf8");
const parsed = new vm.SourceTextModule(source, { context });
await parsed.link(() => { throw new Error("unexpected import"); });
await parsed.evaluate();
const module = parsed.namespace;
module.appendInteractionOutcome({ widget: "browser", action: "icon.click", outcome: "received" });
for (let index = 0; index < module.INTERACTION_TRAIL_LIMIT + 3; index += 1) {
  module.appendInteractionOutcome({ widget: "browser", action: "widget.toggle", outcome: "opened", reason: `attempt-${index}` });
}

const missing = await module.executeClientObservability("observability_browser_surface", {});
assert.equal(missing.ok, false);
assert.equal(missing.error, "native_browser_unavailable");
assert.equal(missing.interaction_trail.length, module.INTERACTION_TRAIL_LIMIT);
assert.equal(missing.interaction_trail[0].reason, `attempt-${module.INTERACTION_TRAIL_LIMIT + 2}`);

let invokedWith;
let surface = {
  id: "browser", status: "ready", visible: false, url: "https://web.whatsapp.com/", title: "WhatsApp", loading: false,
  inputReceiptEnabled: true,
  inputReceipt: {
    schema: "hermes.wasm_agent.native_web_surface_input_receipt.v1",
    id: "receipt-7",
    surface_id: "browser",
    at: "2026-08-20T15:59:59.250Z",
    action: "pointer.primary_gesture",
    outcome: "observed_pre_dispatch",
    button: "left",
    x: 123.4,
    y: 45.6,
    viewport: { width: 800, height: 600, secret: "viewport-secret" },
    current_document: true,
    age_ms: 750,
    redacted: true,
    url: "https://secret.example/private?q=token",
    dom_target: "button#private",
    text: "private text",
    cookie: "wa_uid=secret",
  },
};
context.wasmAgentNative = { webSurfaces: { invoke: async (...args) => {
  invokedWith = args;
  return surface;
} } };
const inspected = await module.executeClientObservability("observability_browser_surface", {});
assert.equal(inspected.ok, true);
assert.equal(inspected.browser.status, "ready");
assert.equal(inspected.browser.input_receipt_state, "enabled");
assert.deepEqual(JSON.parse(JSON.stringify(invokedWith)), ["status", { id: "browser", includeInputReceipt: true }]);
assert.deepEqual(Array.from(inspected.proof), ["native.web_surface.status", "client.interaction_outcome.trail", "native.web_surface.input_receipt"]);
assert.deepEqual(JSON.parse(JSON.stringify(inspected.browser.input_receipt)), {
  schema: "hermes.wasm_agent.native_web_surface_input_receipt.v1",
  id: "receipt-7",
  surface_id: "browser",
  at: "2026-08-20T15:59:59.250Z",
  action: "pointer.primary_gesture",
  outcome: "observed_pre_dispatch",
  button: "left",
  x: 123,
  y: 46,
  viewport: { width: 800, height: 600 },
  current_document: true,
  age_ms: 750,
  input_source: "unattributed_native_input",
  redacted: true,
});
assert.doesNotMatch(JSON.stringify(inspected), /secret|dom_target|cookie|private text/);
assert.equal(inspected.interaction_trail.length, module.INTERACTION_TRAIL_LIMIT);

surface = {
  ...surface,
  inputReceipt: {
    ...surface.inputReceipt,
    id: "receipt-synthetic",
    input_source: "electron_synthetic",
    command_id: "cmd-72f9b4a8:browser.pointer",
  },
};
const synthetic = await module.executeClientObservability("observability_browser_surface", {});
assert.equal(synthetic.browser.input_receipt.input_source, "electron_synthetic");
assert.equal(synthetic.browser.input_receipt.command_id, "cmd-72f9b4a8:browser.pointer");
assert.doesNotMatch(JSON.stringify(synthetic.browser.input_receipt), /secret|dom_target|cookie|private text/);

surface = {
  ...surface,
  inputReceipt: {
    ...surface.inputReceipt,
    id: "receipt-invalid-source",
    input_source: "user_physical_click",
  },
};
const invalidSource = await module.executeClientObservability("observability_browser_surface", {});
assert.equal(invalidSource.browser.input_receipt, null);
assert.equal(invalidSource.proof.includes("native.web_surface.input_receipt"), false);

surface = {
  ...surface,
  inputReceipt: {
    ...surface.inputReceipt,
    id: "receipt-invalid-command",
    input_source: "electron_synthetic",
    command_id: `cmd-${"x".repeat(121)}`,
  },
};
const invalidCommand = await module.executeClientObservability("observability_browser_surface", {});
assert.equal(invalidCommand.browser.input_receipt, null);
assert.equal(invalidCommand.proof.includes("native.web_surface.input_receipt"), false);

surface = {
  ...surface,
  inputReceipt: {
    ...surface.inputReceipt,
    id: "receipt-contradictory-command",
    input_source: "unattributed_native_input",
    command_id: "cmd-should-not-project",
  },
};
const contradictoryCommand = await module.executeClientObservability("observability_browser_surface", {});
assert.equal(contradictoryCommand.browser.input_receipt, null);
assert.equal(contradictoryCommand.proof.includes("native.web_surface.input_receipt"), false);

surface = {
  ...surface,
  inputReceipt: {
    schema: "hermes.wasm_agent.native_web_surface_input_receipt.v1",
    id: "receipt-8",
    surface_id: "browser",
    at: "2026-08-20T15:59:58.000Z",
    action: "pointer.primary_gesture",
    outcome: "observed_pre_dispatch",
    button: "left",
    current_document: true,
    age_ms: 2000,
    redacted: true,
  },
};
const coordinateFree = await module.executeClientObservability("observability_browser_surface", {});
assert.equal(coordinateFree.browser.input_receipt, null);
assert.equal(coordinateFree.proof.includes("native.web_surface.input_receipt"), false);

surface = { ...surface, inputReceipt: { ...surface.inputReceipt, action: "page.click" } };
const legacyClickClaim = await module.executeClientObservability("observability_browser_surface", {});
assert.equal(legacyClickClaim.browser.input_receipt, null);
assert.equal(legacyClickClaim.proof.includes("native.web_surface.input_receipt"), false);

surface = {
  ...surface,
  inputReceipt: {
    ...surface.inputReceipt,
    id: "receipt-stale",
    action: "pointer.primary_gesture",
    at: "2026-08-20T15:57:59.000Z",
    age_ms: 121000,
  },
};
const stale = await module.executeClientObservability("observability_browser_surface", {});
assert.equal(stale.browser.input_receipt, null);
assert.equal(stale.browser.input_receipt_state, "enabled");
assert.equal(stale.proof.includes("native.web_surface.input_receipt"), false);

surface = { ...surface, inputReceiptEnabled: false };
const disabled = await module.executeClientObservability("observability_browser_surface", {});
assert.equal(disabled.browser.input_receipt_state, "disabled");
assert.equal(disabled.browser.input_receipt, null);
assert.equal(disabled.proof.includes("native.web_surface.input_receipt"), false);

const { inputReceiptEnabled: _unsupported, ...unsupportedSurface } = surface;
surface = unsupportedSurface;
const unsupported = await module.executeClientObservability("observability_browser_surface", {});
assert.equal(unsupported.browser.input_receipt_state, "unsupported");
assert.equal(unsupported.browser.input_receipt, null);
assert.equal(unsupported.proof.includes("native.web_surface.input_receipt"), false);

console.log("client observability interaction and receipt projection tests passed");
