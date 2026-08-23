const assert = require("assert");
const { automaticUpdatesEnabled, automaticUpdatePayload, startAutomaticUpdateLoop } = require("./automatic-updates");
const fs = require("fs");
const path = require("path");

assert.strictEqual(automaticUpdatesEnabled({}), true);
assert.strictEqual(automaticUpdatesEnabled({ WASM_AGENT_DISABLE_AUTOMATIC_UPDATES: "1" }), false);
assert.deepStrictEqual(automaticUpdatePayload({}), { automatic: true, applyApproved: true, cacheBypass: true });
assert.match(fs.readFileSync(path.join(__dirname, "..", "main.js"), "utf8"), /runWindowsSelfUpdate\(sender, opId, \{\s*\.\.\.payload,/s, "native-control must preserve automatic update policy fields");

const timers = [];
const immediate = [];
let calls = 0;
const loop = startAutomaticUpdateLoop({ run: async (payload) => { calls += 1; assert.strictEqual(payload.automatic, true); }, scheduleImmediate: (fn) => immediate.push(fn), setTimer: (fn, ms) => { timers.push({ fn, ms }); return { unref() {} }; } });
assert.strictEqual(loop.started, true);
assert.strictEqual(loop.initialDelayMs, 0);
assert.strictEqual(immediate.length, 1);
assert.strictEqual(timers.length, 1);
immediate[0]();
setImmediate(() => {
  assert.strictEqual(calls, 1);
  assert.strictEqual(startAutomaticUpdateLoop({ run() {}, env: { WASM_AGENT_DISABLE_AUTOMATIC_UPDATES: "1" } }).started, false);
  console.log("automatic updates policy tests passed");
});
