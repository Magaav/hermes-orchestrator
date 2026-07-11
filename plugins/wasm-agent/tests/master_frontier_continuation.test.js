const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const modulePath = path.join(__dirname, "..", "public", "modules", "master-frontier", "continuation.js");
const source = fs.readFileSync(modulePath, "utf8");
const sandbox = { exports: {}, Set };
vm.runInNewContext(
  `${source
    .replace("export function isAgentContinuationRequest", "function isAgentContinuationRequest")
    .replace("export function masterFrontierContinuationContext", "function masterFrontierContinuationContext")
    .replace("export function markMasterFrontierInterrupted", "function markMasterFrontierInterrupted")
    .replace("export async function recoverMasterFrontierFinal", "async function recoverMasterFrontierFinal")
    .replace("export function masterFrontierPartialReplyIsStale", "function masterFrontierPartialReplyIsStale")
    .replace("export function masterFrontierPartialReplyFromPending", "function masterFrontierPartialReplyFromPending")
    .replace("export function masterFrontierPartialReplyFromError", "function masterFrontierPartialReplyFromError")}\nexports.isAgentContinuationRequest=isAgentContinuationRequest;\nexports.masterFrontierContinuationContext=masterFrontierContinuationContext;\nexports.markMasterFrontierInterrupted=markMasterFrontierInterrupted;`,
  sandbox,
  { filename: modulePath }
);

const { isAgentContinuationRequest, masterFrontierContinuationContext, markMasterFrontierInterrupted } = sandbox.exports;
assert.strictEqual(isAgentContinuationRequest("continue"), true);
assert.strictEqual(isAgentContinuationRequest("continue the refactor"), false);

const messages = [
  { id: "u1", role: "user", content: "fix budget enforcement without replaying edits" },
  { id: "a1", role: "assistant", content: "Inspected planner.py", pending: true, run_id: "wa_run_1", turn_id: "turn_1", changed_files: ["server/master_frontier/budget.py"] },
];
const interrupted = markMasterFrontierInterrupted(messages[1], new Error("server restarted"));
messages[1] = interrupted;
const context = masterFrontierContinuationContext({ messages }, { timelineRows: () => [{ label: "evidence.received" }] });
assert.strictEqual(context.original_objective, "fix budget enforcement without replaying edits");
assert.strictEqual(context.previous_run_id, "wa_run_1");
assert.strictEqual(context.previous_status, "interrupted");
assert(context.instruction.includes("before repeating any side effect"));
assert.strictEqual(interrupted.resumable, true);
assert.strictEqual(interrupted.phase, "Ready to continue");
console.log("Master:frontier continuation tests: PASS");
