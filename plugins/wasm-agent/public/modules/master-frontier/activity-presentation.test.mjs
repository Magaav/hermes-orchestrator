import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(new URL("./activity-presentation.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { masterFrontierActivityText, masterFrontierInitialCommentary, showMasterFrontierRunActivity } = await import(moduleUrl);

assert.equal(showMasterFrontierRunActivity({ role: "assistant", pending: true }), true);
assert.equal(showMasterFrontierRunActivity({ role: "assistant", pending: false }), false);
assert.equal(showMasterFrontierRunActivity({ role: "assistant", pending: true }, true), false);
assert.equal(masterFrontierActivityText({ event_type: "llm.reason.summary", detail: "I’m checking the route." }), "I’m checking the route.");
assert.equal(masterFrontierActivityText({ event_type: "command.started", detail: "repo.read" }), "");
assert.equal(masterFrontierInitialCommentary(), "I’m thinking through your request now.");

console.log("master frontier activity presentation tests passed");
