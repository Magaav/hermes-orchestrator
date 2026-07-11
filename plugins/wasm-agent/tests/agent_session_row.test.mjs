import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(new URL("../public/modules/assistant/session-row.js", import.meta.url), "utf8");
const { agentSessionReference } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

assert.equal(agentSessionReference({ id: " session_123 " }), "session_123");
assert.equal(agentSessionReference({}), "");

console.log("agent session row tests passed");
