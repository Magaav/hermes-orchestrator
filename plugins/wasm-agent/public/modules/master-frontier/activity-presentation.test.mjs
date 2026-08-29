import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(new URL("./activity-presentation.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const {
  appendMasterFrontierDecisionTrace,
  masterFrontierActivityText,
  masterFrontierInitialCommentary,
  masterFrontierInitialDecisionTrace,
  masterFrontierHeartbeatBodyContent,
  masterFrontierDecisionTraceEntries,
  masterFrontierMessageContentNodes,
  masterFrontierPublicCommentary,
  renderMasterFrontierDecisionTrace,
  renderMasterFrontierRunDetails,
  showMasterFrontierAnswerBody,
  showMasterFrontierRunActivity,
} = await import(moduleUrl);

assert.equal(showMasterFrontierRunActivity({ role: "assistant", pending: true }), true);
assert.equal(showMasterFrontierRunActivity({ role: "assistant", pending: false }), false);
assert.equal(showMasterFrontierRunActivity({ role: "assistant", pending: false, actions: [{ id: "decision-1" }] }), true);
assert.equal(showMasterFrontierRunActivity({ role: "assistant", pending: false, timeline: [{ id: "trace-1" }] }), true);
assert.equal(showMasterFrontierRunActivity({ role: "assistant", pending: false, token_ledger: {} }), true);
assert.equal(showMasterFrontierRunActivity({ role: "assistant", pending: false, decision_trace: [{ id: "decision-1" }] }), true);
assert.equal(showMasterFrontierRunActivity({ role: "assistant", pending: true }, true), false);
assert.equal(showMasterFrontierAnswerBody({ mode: "direct_head", pending: true }), false);
assert.equal(showMasterFrontierAnswerBody({ mode: "direct_head", pending: true, agent_delta_started: true }), true);
assert.equal(showMasterFrontierAnswerBody({ mode: "direct_head", pending: false }), true);
assert.equal(showMasterFrontierAnswerBody({ mode: "direct_api", pending: true }), true);
assert.equal(masterFrontierHeartbeatBodyContent({ mode: "direct_head", pending: true, content: "" }, "Waiting"), "");
assert.equal(masterFrontierHeartbeatBodyContent({ mode: "direct_api", pending: true, content: "" }, "Waiting"), "Waiting");
const initialTrace = masterFrontierInitialDecisionTrace();
const publicCommentaryAction = {
  id: "tl_reason_2",
  arguments: {
    commentary: {
      schema: "master.frontier.v6.commentary.v1",
      authored_by: "model",
      visibility: "public",
      phase: "evidence",
      message: "I found the relevant evidence.",
    },
    decision: 2,
  },
};
assert.equal(masterFrontierPublicCommentary(publicCommentaryAction), "I found the relevant evidence.");
const secondTrace = appendMasterFrontierDecisionTrace(initialTrace, {
  id: "tl_reason_2",
  arguments: { commentary: { phase: "evidence" }, decision: 2 },
}, "I found the relevant evidence.");
const thirdTrace = appendMasterFrontierDecisionTrace(secondTrace, {
  id: "tl_reason_3",
  arguments: { commentary: { phase: "verification" }, decision: 3 },
}, "I’m checking the result.");
assert.deepEqual(thirdTrace.map((entry) => entry.message), [
  "I’m thinking through your request now.",
  "I found the relevant evidence.",
  "I’m checking the result.",
]);
assert.equal(
  appendMasterFrontierDecisionTrace(thirdTrace, { id: "tl_reason_3" }, "I verified the result.").length,
  3
);
assert.deepEqual(
  masterFrontierDecisionTraceEntries({ mode: "direct_head", actions: [publicCommentaryAction] }).map((entry) => entry.message),
  ["I found the relevant evidence."]
);
class FakeElement {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.className = "";
    this.textContent = "";
  }
  append(...children) {
    this.children.push(...children);
  }
}
const renderedTrace = renderMasterFrontierDecisionTrace(
  { decision_trace: thirdTrace },
  { createElement: (tagName) => new FakeElement(tagName) }
);
assert.equal(renderedTrace.className, "agent-timeline agent-decision-trace");
assert.deepEqual(renderedTrace.children[0].children.map((row) => row.children[0].textContent), [
  "I’m thinking through your request now.",
  "I found the relevant evidence.",
  "I’m checking the result.",
]);
assert.ok(renderedTrace.children[0].children.every((row) => row.children[0].className === "agent-timeline-detail agent-decision-trace-text"));
const renderedDetails = renderMasterFrontierRunDetails(
  { timeline: "timeline", tokenLedger: "tokens", actions: "actions", decisionTrace: "decisions" },
  { pending: false },
  { createElement: (tagName) => new FakeElement(tagName) }
);
assert.equal(renderedDetails.tagName, "details");
assert.equal(renderedDetails.children[0].children[0].textContent, "Assistant details");
assert.deepEqual(renderedDetails.children[1].children, ["timeline", "tokens", "actions", "decisions"]);
assert.deepEqual(
  masterFrontierMessageContentNodes({
    body: "answer",
    commandChoices: null,
    header: "header",
    runDetails: "details",
  }),
  ["header", "details", "answer"]
);
assert.equal(masterFrontierActivityText({ event_type: "llm.reason.summary", detail: "I’m checking the route." }), "I’m checking the route.");
assert.equal(masterFrontierActivityText({ event_type: "command.started", detail: "repo.read" }), "");
assert.equal(masterFrontierInitialCommentary(), "I’m thinking through your request now.");

console.log("master frontier activity presentation tests passed");
