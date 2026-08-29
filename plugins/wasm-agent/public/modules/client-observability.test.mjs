import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

class TestTarget extends EventTarget {}
const target = new TestTarget();
const context = vm.createContext({
  addEventListener: target.addEventListener.bind(target),
  dispatchEvent: target.dispatchEvent.bind(target),
  location: { href: "https://wa.colmeio.com/home?native=electron" },
  URL,
  Date,
  console,
});
const source = fs.readFileSync(new URL("./client-observability.js", import.meta.url), "utf8");
const parsed = new vm.SourceTextModule(source, { context });
await parsed.link(() => { throw new Error("unexpected import"); });
await parsed.evaluate();
const module = parsed.namespace;
const releaseId = "b".repeat(64);

assert.deepEqual(JSON.parse(JSON.stringify(module.moduleReleaseStatus({
  schema: "hermes.wasm_agent.module_release.v1",
  release_id: releaseId,
  entry: `/app.js?v=${releaseId}`,
}))), { release_id: releaseId, entry: `/app.js?v=${releaseId}` });
assert.deepEqual(JSON.parse(JSON.stringify(module.moduleReleaseStatus({ release_id: "manual" }))), { release_id: null, entry: null });

for (let index = 0; index < module.INTERACTION_TRAIL_LIMIT + 3; index += 1) {
  module.appendInteractionOutcome({ widget: "settings", action: "widget.toggle", outcome: "opened", reason: `attempt-${index}` });
}
assert.deepEqual(JSON.parse(JSON.stringify(await module.executeClientObservability("unknown", {}))), {
  ok: false,
  error: "unsupported_observability_command",
});

console.log("client observability bounded projection tests passed");
