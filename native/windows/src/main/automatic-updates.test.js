const assert = require("assert");
const { automaticUpdatesEnabled, automaticUpdatePayload, startAutomaticUpdateLoop } = require("./automatic-updates");

assert.strictEqual(automaticUpdatesEnabled({}), true);
assert.strictEqual(automaticUpdatesEnabled({ WASM_AGENT_DISABLE_AUTOMATIC_UPDATES: "1" }), false);
assert.deepStrictEqual(automaticUpdatePayload({}), { automatic: true, applyApproved: true, cacheBypass: true });

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
