const assert = require("assert");
const fs = require("fs");
const path = require("path");

const pluginRoot = path.resolve(__dirname, "..");
const engineSource = fs.readFileSync(path.join(pluginRoot, "public", "modules", "wis", "engine.js"), "utf8");

(async () => {
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(engineSource).toString("base64")}`;
  const { createWisSandbox } = await import(moduleUrl);
  const sandbox = createWisSandbox();

  let surface = sandbox.inspect();
  assert.strictEqual(surface.schema, "hermes.wasm_agent.wis.surface_state.v1");
  assert.strictEqual(surface.document.id, "counter-app");
  assert.strictEqual(surface.sandbox.noBackend, true);
  assert.strictEqual(surface.sandbox.noIframe, true);
  assert(surface.nodeCount >= 8, "WIS should expose a DOM-like node tree");
  assert(surface.automation.actions.some((action) => action.targetId === "increment"), "increment action is missing");

  const clickResult = sandbox.act({ type: "click", targetId: "increment" });
  assert.strictEqual(clickResult.ok, true);
  surface = sandbox.inspect();
  assert.strictEqual(surface.state.count, 1);
  assert(surface.recentEvents.some((event) => event.type === "wis.state_changed"), "state change event is missing");

  sandbox.act({ type: "input", targetId: "task-input", value: "Export artifact" });
  sandbox.act({ type: "click", targetId: "add-task" });
  surface = sandbox.inspect();
  assert(surface.state.tasks.includes("Export artifact"), "input-driven state change is missing");

  const exported = sandbox.exportSpace();
  assert.strictEqual(exported.schema, "hermes.wasm_agent.wis.export.v1");
  assert.strictEqual(exported.guarantees.backendDependency, false);
  assert.strictEqual(exported.guarantees.iframePrimaryArchitecture, false);
  assert.strictEqual(exported.guarantees.portableArtifactDefinition, true);
  assert.strictEqual(exported.space.schema, "hermes.wasm_agent.wis.space.v1");

  console.log("wis engine ok");
})();
