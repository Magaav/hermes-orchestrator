const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const modulePath = path.join(__dirname, "..", "public", "modules", "client-presence.js");
const source = fs.readFileSync(modulePath, "utf8");
const cadence = source
  .replace(/^import .*;$/gm, "")
  .replace(/^export function startClientPresence/m, "function startClientPresence")
  .replace(/^export \{[\s\S]*?^\};$/m, "")
  + "\nexports.clientPresencePollDelay=pollDelay;exports.automaticWindowsUpdatePayload=automaticWindowsUpdatePayload;";
const sandbox = { exports: {}, document: { hidden: false } };
vm.runInNewContext(cadence, sandbox, { filename: modulePath });
const pollDelay = sandbox.exports.clientPresencePollDelay;
const automaticWindowsUpdatePayload = sandbox.exports.automaticWindowsUpdatePayload;

assert.strictEqual(pollDelay("electron", false), 2000, "visible Electron control latency must stay below one polling interval");
assert.strictEqual(pollDelay("electron", true), 10000, "background Electron polling must be throttled");
assert.strictEqual(pollDelay("pwa", false), 15000, "active web polling must retain its existing cadence");
assert.strictEqual(pollDelay("pwa", true), 30000, "background web polling must remain throttled");
assert.strictEqual(pollDelay("android-kotlin", false), 15000, "Android polling must not inherit the desktop fast path");
assert(source.includes("if (!inFlight) inFlight = poll(controls)"), "presence polling must coalesce concurrent visibility and timer requests");
assert(!source.includes("setInterval("), "presence polling must remain completion-scheduled rather than overlap on an interval");
assert.deepStrictEqual(
  { ...automaticWindowsUpdatePayload({ reason: "remote-control", automatic: false, applyApproved: false }) },
  { reason: "remote-control", automatic: true, applyApproved: true },
  "remote update control must stay pre-approved and silent even when stale caller flags disagree",
);
assert(source.includes('updatePolicy: { mode: "automatic", approval: "preapproved" }'), "remote update receipts must expose the effective non-interactive policy");

console.log("Client presence polling tests: PASS");
