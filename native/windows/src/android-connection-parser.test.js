const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const mainJs = fs.readFileSync(path.join(__dirname, "main.js"), "utf8");
const start = mainJs.indexOf("function parseAdbDevices");
const end = mainJs.indexOf("async function runWindowsDiagnosticExec");
assert(start >= 0 && end > start, "ADB connection parser block must be present");

const context = {};
vm.createContext(context);
vm.runInContext(`${mainJs.slice(start, end)}\nthis.parseAndroidConnectionState = parseAndroidConnectionState;\nthis.shouldRecoverAdbDevicesResult = shouldRecoverAdbDevicesResult;\nthis.isAdbServerStartupOutput = isAdbServerStartupOutput;`, context);

function parse(stdout, commandOk = true, commandResult = {}) {
  return context.parseAndroidConnectionState(stdout, commandOk, commandResult);
}

const header = "List of devices attached\n";

assert.strictEqual(parse(header).status, "no_device");
assert.match(parse(header).instructions, /Phone not visible to Windows ADB/);
assert.strictEqual(context.shouldRecoverAdbDevicesResult({ ok: true, stdout: header, stderr: "", error: "" }), true);

const unauthorized = parse(`${header}R58N1234567 unauthorized usb:1-1 transport_id:4\n`);
assert.strictEqual(unauthorized.status, "unauthorized");
assert.match(unauthorized.instructions, /accept the USB debugging authorization prompt/);

const offline = parse(`${header}R58N1234567 offline usb:1-1 transport_id:4\n`);
assert.strictEqual(offline.status, "offline");
assert.match(offline.instructions, /Reconnect USB, toggle USB debugging/);

const one = parse(`${header}R58N1234567 device usb:1-1 product:o1q model:SM_G991U device:o1q transport_id:5\n`);
assert.strictEqual(one.status, "one_authorized_device");
assert.strictEqual(one.ok, true);
assert.strictEqual(one.hasAuthorizedDevice, true);
assert.strictEqual(one.serial, "R58N1234567");
assert.strictEqual(one.model, "SM_G991U");
assert.strictEqual(one.product, "o1q");
assert.strictEqual(one.device, "o1q");

assert.strictEqual(parse(`${header}R58N1234567 device product:o1q model:SM_G991U device:o1q\nemulator-5554 device product:sdk_gphone model:sdk_gphone device:emu64x\n`).status, "multiple_devices");
assert.strictEqual(parse(`${header}R58N1234567 unauthorized usb:1-1\nemulator-5554 offline\n`).status, "unauthorized");
assert.strictEqual(parse(`${header}emulator-5554 offline\n0123456789ABCDEF offline\n`).status, "multiple_devices");

const coldStart = {
  ok: false,
  timedOut: true,
  stdout: "",
  stderr: "* daemon not running; starting now at tcp:5037\n",
  error: "timed out after 5000ms",
};
assert.strictEqual(context.isAdbServerStartupOutput(coldStart), true);
assert.strictEqual(context.shouldRecoverAdbDevicesResult(coldStart), true);
assert.strictEqual(parse("", false, coldStart).status, "adb_timeout");
assert.match(parse("", false, coldStart).instructions, /timed out/);

const startMessage = { ok: true, stdout: "", stderr: "* daemon not running; starting now at tcp:5037\n* daemon started successfully\n" };
assert.strictEqual(context.shouldRecoverAdbDevicesResult(startMessage), true);

const missing = { ok: false, stdout: "", stderr: "", error: "spawn adb ENOENT" };
assert.strictEqual(context.shouldRecoverAdbDevicesResult(missing), false);
assert.strictEqual(parse("", false, missing).status, "adb_missing");

console.log("android connection parser ok");
