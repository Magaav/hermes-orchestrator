const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const modulePath = path.join(__dirname, "..", "public", "modules", "assistant", "session-persistence.js");
const source = fs.readFileSync(modulePath, "utf8");
const sandbox = { exports: {} };
vm.runInNewContext(
  `${source.replace("export function serializeAgentSessions", "function serializeAgentSessions")}
exports.serializeAgentSessions=serializeAgentSessions;`,
  sandbox,
  { filename: modulePath }
);

const sessions = [{
  id: "active",
  messages: [{
    id: "answer",
    role: "assistant",
    content: "verified",
    run_id: "wa_run_proof",
    diagnostics: {
      diff_seen: true,
      observed_changed_files: ["public/widget.js", "tests/widget.test.js"],
      oversized: "x".repeat(20_000),
    },
    actions: Array.from({ length: 100 }, (_, index) => ({ id: index, detail: "y".repeat(10_000) })),
  }],
}];
const serialized = sandbox.exports.serializeAgentSessions(sessions, "active", 100_000);
const restored = JSON.parse(serialized);
assert(serialized.length <= 100_000);
assert.strictEqual(restored[0].messages[0].run_id, "wa_run_proof");
assert.strictEqual(restored[0].messages[0].diagnostics.diff_seen, true);
assert.deepStrictEqual(
  JSON.parse(JSON.stringify(restored[0].messages[0].diagnostics.observed_changed_files)),
  ["public/widget.js", "tests/widget.test.js"]
);
console.log("Agent session persistence tests: PASS");
