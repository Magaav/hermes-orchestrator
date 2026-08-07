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
  `${source.replace(/export\s+function\s+/g, "function ")}\nexports.masterFrontierObjectiveKind = masterFrontierObjectiveKind;\nexports.masterFrontierOutputBudget = masterFrontierOutputBudget;\nexports.masterFrontierRouteId = masterFrontierRouteId;\nexports.masterFrontierUsefulFallback = masterFrontierUsefulFallback;`,
  sandbox,
  { filename: modulePath }
);

const { masterFrontierObjectiveKind, masterFrontierOutputBudget, masterFrontierRouteId, masterFrontierUsefulFallback } = sandbox.exports;

{
  const prompt = "check out our master:frontier node inside wasm. critisize it";
  assert.strictEqual(masterFrontierObjectiveKind(prompt), "diagnosis");
  assert.strictEqual(masterFrontierOutputBudget(prompt), 1800);
}

{
  assert.strictEqual(masterFrontierObjectiveKind("hello"), "model_decision");
  assert.strictEqual(
    masterFrontierObjectiveKind("heard you got upgrades brand new state of art"),
    "model_decision"
  );
  assert.strictEqual(
    masterFrontierObjectiveKind("hello, can you se the Property Photo Cleaner widget?"),
    "model_decision"
  );
}

{
  const prompt = "Verify the current widget revision, run its test, inspect the diff, and report the exact changed files.";
  assert.strictEqual(masterFrontierObjectiveKind(prompt), "verification");
  const preservedRevision = "Finish the existing widget fixes. Inspect the current worktree, preserve the correct mutation, run the registered focused test, inspect the current diff, collect scoped proof, and finalize only with revision-bound changed-file evidence.";
  assert.strictEqual(masterFrontierObjectiveKind(preservedRevision), "verification");
  assert.strictEqual(masterFrontierObjectiveKind("Fix the widget code and test the patch."), "implementation");
  assert.strictEqual(masterFrontierObjectiveKind("Inspect the current diff, then patch the widget and run its test."), "implementation");
  assert.strictEqual(
    masterFrontierObjectiveKind("Inspect the current planner contract and explain it. Cite the files you read."),
    "diagnosis"
  );
  assert.strictEqual(
    masterFrontierObjectiveKind("I need you to create a new experience where I can start and stop a live transcript."),
    "implementation"
  );
  assert.strictEqual(masterFrontierObjectiveKind("Can you create that?"), "implementation");
  assert.strictEqual(masterFrontierRouteId("implementation"), "wasm-agent.space.ui");
  assert.strictEqual(masterFrontierRouteId("conversation"), "wasm-agent.avatar-chat.ui");
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

{
  const billingUrl = "https://opencode.ai/workspace/example/billing";
  const fallback = masterFrontierUsefulFallback("hello", {
    reason: `Insufficient balance. Manage your billing here: ${billingUrl}`,
    provider_interrupted: true,
    continuation_context: { previous_run_id: "wa_run_billing" },
  });
  assert(fallback);
  assert.strictEqual(fallback.status, "provider_billing_required");
  assert.strictEqual(fallback.continuation_context, null);
  assert.strictEqual(fallback.metrics.resumable, false);
  assert(fallback.answer.includes("Insufficient balance"));
  assert(fallback.answer.includes(billingUrl));
  assert(fallback.answer.includes("Add funds or switch to a funded provider"));
  assert(!fallback.answer.includes("I was interrupted"));
  assert(!fallback.answer.includes("next attempt"));
  assert(!fallback.answer.includes("Saved run"));
}

assert(!source.includes("feelings"), "fallback policy must not contain prompt-specific feelings handling");
assert(!source.includes("improove"), "fallback policy must not contain captured prompt typos");
const appJs = fs.readFileSync(appPath, "utf8");
assert(/from "\.\/modules\/master-frontier\/useful-fallback\.js(?:\?[^"]+)?"/.test(appJs));
assert(appJs.includes("original_objective: userMessageContent"));
assert(appJs.includes("continuation_context: continuationCheckpoint"));
assert(appJs.includes("route_id: envelope.route_id"), "the immutable run request must preserve the selected route outside the envelope");
console.log("Master:frontier useful fallback tests: PASS");
