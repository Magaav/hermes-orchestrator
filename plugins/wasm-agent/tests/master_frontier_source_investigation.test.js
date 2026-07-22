#!/usr/bin/env node
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

(async () => {
  const moduleSource = fs.readFileSync(path.join(__dirname, "../public/modules/master-frontier/source-investigation.js"), "utf8");
  const sandbox = { exports: {}, URLSearchParams };
  vm.runInNewContext(`${moduleSource.replace(/export /g, "")}\nexports.values={masterFrontierSourceInvestigationRequest,masterFrontierProtocolRequest,masterFrontierExplicitProtocol};`, sandbox);
  const source = sandbox.exports.values;
  const fallbackModuleSource = fs.readFileSync(path.join(__dirname, "../public/modules/master-frontier/useful-fallback.js"), "utf8");
  const fallbackSandbox = { exports: {} };
  vm.runInNewContext(`${fallbackModuleSource.replace(/export /g, "")}\nexports.values={masterFrontierObjectiveKind};`, fallbackSandbox);
  const objectiveKind = fallbackSandbox.exports.values.masterFrontierObjectiveKind;
  const sandboxInspectPrompt = "Review the repository text at tests/fixtures/master_frontier_v5_live_sandbox.txt and report its exact current values using repository read evidence. Include this future-state note verbatim in your answer: target status=after and target proof=verified. Do not modify anything.";
  assert.strictEqual(objectiveKind(sandboxInspectPrompt), "diagnosis");
  assert.strictEqual(objectiveKind("Change it."), "conversation");
  assert.strictEqual(objectiveKind("Fix the tests."), "implementation");
  const selected = source.masterFrontierSourceInvestigationRequest("Criticize this widget implementation", "diagnosis");
  assert.strictEqual(selected.protocol, "v4-source-investigation");
  assert.strictEqual(selected.investigation_mode, "source-investigation-read-only");
  assert.strictEqual(source.masterFrontierSourceInvestigationRequest("great, critisize meta-analysis widget", "diagnosis").protocol, "v4-source-investigation");
  assert.strictEqual(source.masterFrontierSourceInvestigationRequest("Why is the device offline?", "diagnosis").protocol, "v3");
  assert.strictEqual(source.masterFrontierSourceInvestigationRequest("Fix this widget implementation", "implementation").protocol, "v3");
  assert.strictEqual(source.masterFrontierSourceInvestigationRequest("Hello", "conversation").protocol, "v3");
  assert.strictEqual(source.masterFrontierProtocolRequest("Hello", "conversation", "v5").protocol, "v5");
  assert.strictEqual(source.masterFrontierProtocolRequest("Criticize this widget implementation", "diagnosis", "").protocol, "v5");
  assert.strictEqual(source.masterFrontierProtocolRequest("Hello", "conversation", "v3").protocol, "v3");
  assert.strictEqual(source.masterFrontierProtocolRequest("Hello", "conversation", "v4-source-investigation").protocol, "v4-source-investigation");
  assert.strictEqual(source.masterFrontierExplicitProtocol("?frontier=v5", ""), "v5");
  assert.strictEqual(source.masterFrontierExplicitProtocol("", "v5"), "v5");
  assert.strictEqual(source.masterFrontierExplicitProtocol("", ""), "v5");
  const app = fs.readFileSync(path.join(__dirname, "../public/app.js"), "utf8");
  assert(app.includes("masterFrontierProtocolRequest"));
  assert(app.includes("investigation_mode: protocolSelection.investigation_mode"));
  assert(!app.includes('enforcement: objectiveKind === "conversation" ? "soft" : "hard"'));
  const runEvidence = require(path.join(__dirname, "../../../tools/app-simulator/core/run-evidence"));
  const sourceEvents = [
    { type: "evidence.received", payload: { tool: "search", result: { matches: [{ excerpt: "route to kernel.inspect then runtime_action_entity_denied" }] } } },
    { type: "evidence.received", payload: { tool: "read", result: { ok: true } } },
  ];
  assert.deepStrictEqual(runEvidence.evidenceToolNames(sourceEvents), ["search", "read"]);
  assert.strictEqual(runEvidence.runtimeInspectWasExecuted(sourceEvents), false);
  assert.strictEqual(runEvidence.runtimeInspectWasExecuted([
    { type: "command.started", summary: "kernel.inspect", payload: {} },
  ]), true);
  assert.strictEqual(runEvidence.runtimeInspectWasExecuted([
    { type: "command.failed", payload: { tool: "inspect", result: { code: "runtime_action_entity_denied" } } },
  ]), true);
  console.log("master-frontier source investigation selection ok");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
