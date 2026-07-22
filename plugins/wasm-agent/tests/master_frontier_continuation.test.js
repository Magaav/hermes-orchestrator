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
    .replace("export function requiredMasterFrontierContinuationContext", "function requiredMasterFrontierContinuationContext")
    .replace("export function markMasterFrontierInterrupted", "function markMasterFrontierInterrupted")
    .replace("export async function resolvePendingAgentRunId", "async function resolvePendingAgentRunId")
    .replace("export async function recoverMasterFrontierFinal", "async function recoverMasterFrontierFinal")
    .replace("export function masterFrontierPartialReplyIsStale", "function masterFrontierPartialReplyIsStale")
    .replace("export function masterFrontierPartialReplyFromPending", "function masterFrontierPartialReplyFromPending")
    .replace("export function masterFrontierPartialReplyFromError", "function masterFrontierPartialReplyFromError")}\nexports.isAgentContinuationRequest=isAgentContinuationRequest;\nexports.masterFrontierContinuationContext=masterFrontierContinuationContext;\nexports.requiredMasterFrontierContinuationContext=requiredMasterFrontierContinuationContext;\nexports.markMasterFrontierInterrupted=markMasterFrontierInterrupted;\nexports.resolvePendingAgentRunId=resolvePendingAgentRunId;\nexports.recoverMasterFrontierFinal=recoverMasterFrontierFinal;`,
  sandbox,
  { filename: modulePath }
);

const { isAgentContinuationRequest, masterFrontierContinuationContext, requiredMasterFrontierContinuationContext, markMasterFrontierInterrupted, resolvePendingAgentRunId, recoverMasterFrontierFinal } = sandbox.exports;
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
assert.strictEqual(context.requested, true);
assert.strictEqual(context.previous_status, "interrupted");
assert(context.instruction.includes("before repeating any side effect"));
assert.strictEqual(interrupted.resumable, true);
assert.strictEqual(interrupted.phase, "Ready to continue");

const checkpoint = {
  schema: "master.frontier.v5.checkpoint.v1",
  protocol: "v5",
  scope: { source_run_id: "wa_run_1" },
  state: { schema: "master.frontier.v5.trajectory.v1" },
  sha256: "abc123",
};
const recoveredMessage = { role: "assistant", run_id: "wa_run_1", pending: true };
const missingMessage = { role: "assistant", turn_id: "missing", pending: true };
resolvePendingAgentRunId({ id: "session" }, missingMessage, { fetchRuns: async () => ({ runs: [] }) }).then((runId) => {
  assert.strictEqual(runId, "");
  assert.strictEqual(missingMessage.pending, false);
  assert.strictEqual(missingMessage.agent_run_status, "interrupted");
});
recoverMasterFrontierFinal(recoveredMessage, {
  fetchRun: async () => ({ run: { status: "interrupted", error: { message: "restart", resume_checkpoint: checkpoint } } }),
}).then((final) => {
  assert.strictEqual(final, null);
  assert.deepStrictEqual(JSON.parse(JSON.stringify(recoveredMessage.resume_checkpoint)), JSON.parse(JSON.stringify({
    schema: checkpoint.schema,
    protocol: "v5",
    scope: { source_run_id: "wa_run_1" },
    sha256: "abc123",
  })));
  const recoveredContext = masterFrontierContinuationContext({
    messages: [{ role: "user", content: "finish it" }, recoveredMessage],
  });
  assert.deepStrictEqual(JSON.parse(JSON.stringify(recoveredContext.resume_checkpoint)), JSON.parse(JSON.stringify(recoveredMessage.resume_checkpoint)));
  const newest = masterFrontierContinuationContext({ messages: [
    { role: "user", content: "old task" },
    { role: "assistant", content: "old partial", run_id: "old", pending: true },
    { role: "user", content: "new topic" },
    { role: "assistant", content: "new answer", run_id: "new", pending: false },
  ] });
  assert.strictEqual(newest.original_objective, "new topic");
  assert.strictEqual(newest.previous_run_id, "new");
  assert.throws(() => requiredMasterFrontierContinuationContext("continue", { messages: [
    { role: "assistant", content: "older valid run", run_id: "must-not-fallback" },
    { role: "assistant", content: "local placeholder without server identity" },
  ] }), (error) => error.code === "continuation_source_required");
  console.log("Master:frontier continuation tests: PASS");
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
