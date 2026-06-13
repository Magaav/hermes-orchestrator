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
vm.runInContext(`${mainJs.slice(start, end)}\nthis.parseAndroidConnectionState = parseAndroidConnectionState;`, context);

function parse(stdout, commandOk = true) {
  return context.parseAndroidConnectionState(stdout, commandOk);
}

const header = "List of devices attached\n";

assert.strictEqual(parse(header).status, "no_device");
assert.match(parse(header).instructions, /Change cable or USB port/);

const unauthorized = parse(`${header}R58N1234567 unauthorized usb:1-1 transport_id:4\n`);
assert.strictEqual(unauthorized.status, "unauthorized");
assert.match(unauthorized.instructions, /accept the USB debugging prompt/);
assert.match(unauthorized.instructions, /revoke USB debugging authorizations/);

const one = parse(`${header}R58N1234567 device usb:1-1 product:o1q model:SM_G991U device:o1q transport_id:5\n`);
assert.strictEqual(one.status, "one_authorized_device");
assert.strictEqual(one.ok, true);
assert.strictEqual(one.serial, "R58N1234567");
assert.strictEqual(one.model, "SM_G991U");
assert.strictEqual(one.product, "o1q");
assert.strictEqual(one.device, "o1q");

assert.strictEqual(parse(`${header}R58N1234567 device product:o1q model:SM_G991U device:o1q\nemulator-5554 device product:sdk_gphone model:sdk_gphone device:emu64x\n`).status, "multiple_devices");
assert.strictEqual(parse(`${header}R58N1234567 unauthorized usb:1-1\nemulator-5554 offline\n`).status, "unauthorized");
assert.strictEqual(parse(`${header}emulator-5554 offline\n0123456789ABCDEF offline\n`).status, "multiple_devices");
assert.strictEqual(parse(header, false).status, "adb_error");

console.log("android connection parser ok");
