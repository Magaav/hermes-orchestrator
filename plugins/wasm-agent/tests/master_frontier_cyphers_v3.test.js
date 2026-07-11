const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const pluginRoot = path.resolve(__dirname, "..");
const modulePath = path.join(pluginRoot, "public", "modules", "master-frontier", "cyphers-v3.js");
const registryPath = path.join(pluginRoot, "public", "modules", "master-frontier", "cyphers-v3.json");
const appPath = path.join(pluginRoot, "public", "app.js");
const source = fs.readFileSync(modulePath, "utf8");
const sandbox = { exports: {} };
vm.runInNewContext(
  `${source.replace(/export /g, "")}\nexports.values={MASTER_FRONTIER_V3_SCHEMA,MASTER_FRONTIER_V3_CYPHER,masterFrontierV3OutputBudget,masterFrontierV3Instructions};`,
  sandbox,
  { filename: modulePath }
);

const values = sandbox.exports.values;
const registry = JSON.parse(fs.readFileSync(registryPath, "utf8"));
const app = fs.readFileSync(appPath, "utf8");

assert.strictEqual(values.MASTER_FRONTIER_V3_SCHEMA, "hermes.wasm_agent.master_frontier.v3");
assert.strictEqual(values.MASTER_FRONTIER_V3_CYPHER, registry.id);
assert.strictEqual(values.masterFrontierV3OutputBudget(), 32768);
assert(values.masterFrontierV3Instructions().includes("@search query='term'"));
assert(values.masterFrontierV3Instructions().includes("@read"));
assert(!values.masterFrontierV3Instructions().includes(">q q='term'"));
assert(values.masterFrontierV3Instructions().includes("with no prose"));
assert(!values.masterFrontierV3Instructions().includes('{"c":code,"a":args}'));
assert(values.masterFrontierV3Instructions().includes("reason like Codex"));
assert(app.includes("schema: MASTER_FRONTIER_V3_SCHEMA"));
assert(app.includes("instructions: masterFrontierV3Instructions()"));
assert(!/objective_kind:\s*masterFrontierObjectiveKind/.test(app));
console.log("Master:frontier C3 browser contract: PASS");
