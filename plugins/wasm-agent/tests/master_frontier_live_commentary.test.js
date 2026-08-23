const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const pluginRoot = path.resolve(__dirname, "..");
const modulePath = path.join(pluginRoot, "public", "modules", "master-frontier", "live-commentary.js");
const appPath = path.join(pluginRoot, "public", "app.js");
const source = fs.readFileSync(modulePath, "utf8");
const sandbox = { exports: {} };
vm.runInNewContext(
  `${source.replace(/export\s+(function|const)\s+/g, "$1 ")}
exports.masterFrontierLiveStepFromAction = masterFrontierLiveStepFromAction;
exports.masterFrontierCommentaryFromAction = masterFrontierCommentaryFromAction;`,
  sandbox,
  { filename: modulePath },
);
const commentary = sandbox.exports;

assert.equal(
  commentary.masterFrontierCommentaryFromAction({ event_type: "route.resolved", detail: "private route data" }),
  "I found the owning route. I’m inspecting the relevant implementation now.",
);
assert.equal(
  commentary.masterFrontierCommentaryFromAction({ event_type: "llm.reason.summary", detail: "private reasoning" }),
  "I’ve reviewed the current evidence and I’m choosing the next step.",
);
assert.equal(
  commentary.masterFrontierCommentaryFromAction({
    event_type: "llm.reason.summary",
    detail: "ignored summary",
    arguments: { commentary: {
      schema: "master.frontier.v6.commentary.v1",
      authored_by: "model",
      visibility: "public",
      message: "I found the live Electron client. I’m opening its Browser widget now.",
    } },
  }),
  "I found the live Electron client. I’m opening its Browser widget now.",
);
assert.equal(
  commentary.masterFrontierCommentaryFromAction({
    event_type: "llm.reason.summary",
    arguments: { commentary: { authored_by: "model", visibility: "private", message: "hidden" } },
  }),
  "I’ve reviewed the current evidence and I’m choosing the next step.",
);
assert.equal(
  commentary.masterFrontierCommentaryFromAction({ event_type: "llm.inference.started", detail: "decision 3" }),
  "Choosing the next bounded action (decision 3).",
);
assert.equal(
  commentary.masterFrontierCommentaryFromAction({
    event_type: "llm.inference.started", detail: "decision 3", arguments: { protocol: "v6" },
  }),
  "",
  "V6 must preserve the last meaningful update instead of showing a decision counter",
);
assert.equal(
  commentary.masterFrontierCommentaryFromAction({
    event_type: "semantic.decision",
    arguments: { protocol: "v6", tool: "discover", matches: 6 },
  }),
  "I found 6 route-authorized capabilities and I’m narrowing the executable path.",
);
assert.equal(
  commentary.masterFrontierCommentaryFromAction({
    event_type: "semantic.decision",
    arguments: { protocol: "v6", tool: "detail", details: [
      { kind: "capability", found: true }, { kind: "capability", found: true },
      { kind: "evidence", found: true },
    ] },
  }),
  "I loaded 2 capability schemas and 1 evidence lens.",
);
assert.equal(
  commentary.masterFrontierCommentaryFromAction({
    event_type: "evidence.received", detail: "repo.read", arguments: { protocol: "v6" },
  }),
  "",
  "V6 receipts must not overwrite model-authored operation commentary",
);
assert.equal(
  commentary.masterFrontierCommentaryFromAction({ event_type: "duplicate_action_repair_requested" }),
  "That action repeated existing evidence. I’m switching to a permitted alternative.",
);
assert.equal(
  commentary.masterFrontierCommentaryFromAction({ event_type: "evidence.received", detail: "Read public/widget.js lines 1-40." }),
  "Checking new evidence: Read public/widget.js lines 1-40.",
);
assert.equal(
  commentary.masterFrontierCommentaryFromAction({ event_type: "answer.final", detail: "finished" }),
  "",
  "the final response replaces temporary commentary",
);
assert.equal(
  commentary.masterFrontierLiveStepFromAction({ label: "read_file", status: "running" }),
  "Reading file",
);

const appJs = fs.readFileSync(appPath, "utf8");
assert(appJs.includes('from "./modules/master-frontier/live-commentary.js?v=20260803-codex-commentary1"'));
assert(appJs.includes("masterFrontierCommentaryFromAction(normalized)"));
assert(appJs.indexOf("isAgentTimelineAction(nextAction)") < appJs.indexOf("masterFrontierCommentaryFromAction(normalized)"), "timeline classification remains the routing gate for public commentary");
assert(!appJs.includes("function agentLiveStepFromAction("), "live commentary policy must stay out of the frozen app monolith");

console.log("master_frontier_live_commentary.test.js: ok");
