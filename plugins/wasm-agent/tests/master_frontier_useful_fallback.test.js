const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const pluginRoot = path.resolve(__dirname, "..");
const modulePath = path.join(pluginRoot, "public", "modules", "master-frontier", "useful-fallback.js");
const appPath = path.join(pluginRoot, "public", "app.js");
const source = fs.readFileSync(modulePath, "utf8");
const sandbox = { exports: {} };
vm.runInNewContext(
  `${source.replace("export function masterFrontierObjectiveKind", "function masterFrontierObjectiveKind").replace("export function masterFrontierOutputBudget", "function masterFrontierOutputBudget").replace("export function masterFrontierUsefulFallback", "function masterFrontierUsefulFallback")}\nexports.masterFrontierObjectiveKind = masterFrontierObjectiveKind;\nexports.masterFrontierOutputBudget = masterFrontierOutputBudget;\nexports.masterFrontierUsefulFallback = masterFrontierUsefulFallback;`,
  sandbox,
  { filename: modulePath }
);

const { masterFrontierObjectiveKind, masterFrontierOutputBudget, masterFrontierUsefulFallback } = sandbox.exports;

{
  const prompt = "check out our master:frontier node inside wasm. critisize it";
  assert.strictEqual(masterFrontierObjectiveKind(prompt), "diagnosis");
  assert.strictEqual(masterFrontierOutputBudget(prompt), 1800);
}

{
  const fallback = masterFrontierUsefulFallback("continue", {
    reason: "Agent run was interrupted by a server restart.",
    provider_interrupted: true,
    original_objective: "audit the current controller and fix its budget enforcement",
    route_id: "wasm-agent.avatar-chat.ui",
    continuation_context: { previous_run_id: "wa_run_1" },
  });
  assert(fallback);
  assert.strictEqual(fallback.status, "resumable_interruption");
  assert.strictEqual(fallback.objective, "audit the current controller and fix its budget enforcement");
  assert(fallback.answer.includes("I kept the objective:"));
  assert(fallback.answer.includes("Saved run: wa_run_1"));
  assert(!fallback.answer.includes("what can you do"));
  assert.strictEqual(fallback.metrics.objectivePreserved, true);
}

{
  const fallback = masterFrontierUsefulFallback("fix the repo code", {
    reason: "Provider transport interrupted",
    provider_interrupted: true,
  });
  assert.strictEqual(fallback.objective_kind, "implementation");
  assert(fallback.answer.includes("before repeating a side effect"));
  assert.strictEqual(fallback.metrics.sideEffectReplayGuarded, true);
}

{
  const fallback = masterFrontierUsefulFallback("hello", { reason: "all good" });
  assert.strictEqual(fallback, null);
}

{
  const fallback = masterFrontierUsefulFallback("hello", { reason: "structured_action required" });
  assert.strictEqual(fallback, null);
}

assert(!source.includes("feelings"), "fallback policy must not contain prompt-specific feelings handling");
assert(!source.includes("improove"), "fallback policy must not contain captured prompt typos");
const appJs = fs.readFileSync(appPath, "utf8");
assert(appJs.includes('from "./modules/master-frontier/useful-fallback.js"'));
assert(appJs.includes("original_objective: userMessageContent"));
assert(appJs.includes("continuation_context: continuationCheckpoint"));
console.log("Master:frontier useful fallback tests: PASS");
