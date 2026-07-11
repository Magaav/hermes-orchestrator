const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const pluginRoot = path.resolve(__dirname, "..");
const modulePath = path.join(pluginRoot, "public", "modules", "master-frontier", "timeline.js");
const appPath = path.join(pluginRoot, "public", "app.js");
const source = fs.readFileSync(modulePath, "utf8");
const sandbox = { exports: {} };
vm.runInNewContext(
  `${source.replace(/export\s+(function|const)\s+/g, "$1 ")}
exports.isMasterFrontierTimelineEventType = isMasterFrontierTimelineEventType;
exports.isMasterFrontierTimelineAction = isMasterFrontierTimelineAction;`,
  sandbox,
  { filename: modulePath }
);

const {
  isMasterFrontierTimelineEventType,
  isMasterFrontierTimelineAction,
} = sandbox.exports;

[
  "llm.inference.started",
  "llm.reason.summary",
  "semantic.decision",
  "command.proposed",
  "command.dispatched",
  "evidence.received",
  "turn.usage.updated",
  "gate.decision",
  "answer.final",
  "loop_contract_violation",
].forEach((eventType) => {
  assert(isMasterFrontierTimelineEventType(eventType), `${eventType} must be timeline-visible`);
  assert(
    isMasterFrontierTimelineAction({ id: eventType.replaceAll(".", "_"), event_type: eventType, label: eventType, status: "done" }),
    `${eventType} stream action must merge into the live timeline`
  );
});

[
  "route.resolved",
  "head.decision",
  "envelope.created",
  "files.changed",
  "proof.collected",
  "tests.finished",
  "loop.finished",
].forEach((eventType) => {
  assert(isMasterFrontierTimelineAction({ event_type: eventType, label: eventType }), `${eventType} legacy timeline action regressed`);
});

assert(isMasterFrontierTimelineAction({ label: "tool.finished", meta: "tool.completed" }), "tool completion metadata should stay timeline-visible");
assert(isMasterFrontierTimelineAction({ id: "bridge_token_usage", label: "Token usage" }), "token usage action should stay timeline-visible");
assert(!isMasterFrontierTimelineAction({ id: "bridge_run_poll", label: "bridge.run.poll" }), "poll action must stay out of the visible timeline");
assert(!isMasterFrontierTimelineAction({ id: "node_reply", label: "Node reply", event_type: "node.reply" }), "ordinary action rows must not be promoted");
assert(!isMasterFrontierTimelineAction({ id: "mf_llm_1", label: "LLM decision", topic: "run-api", kind: "trace", meta: "buffered" }), "buffered LLM decisions belong in the per-turn action chain");
assert(!isMasterFrontierTimelineAction({ id: "mf_tool_1", label: "files", topic: "run-api", kind: "tool", meta: "calling" }), "function/dataflow rows belong in the per-turn action chain");

const appJs = fs.readFileSync(appPath, "utf8");
assert(appJs.includes('from "./modules/master-frontier/timeline.js"'), "app.js must import the owned timeline classifier");
assert(appJs.includes("return isMasterFrontierTimelineAction(action);"), "app.js timeline predicate must delegate to the owned module");

console.log("Master:frontier timeline tests: PASS");
