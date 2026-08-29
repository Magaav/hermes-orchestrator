"use strict";

const assert = require("assert");
const { cleanCanary, createWindowsDesktopControl, notepadCanaryScript } = require("./windows-desktop-control");

assert.strictEqual(cleanCanary(" hello\nworld "), "hello world");
assert.throws(() => cleanCanary(""), /notepad_canary_missing/);
assert.throws(() => cleanCanary("unsafe+keys"), /notepad_canary_invalid/);
const script = notepadCanaryScript("proof-123");
assert(script.includes("AutomationElement") && script.includes("Start-Process notepad.exe") && script.includes("ControlType]::Document") && script.includes("$proofName") && script.includes("independently_verified"));

const unavailable = createWindowsDesktopControl({ platform: "linux" });
unavailable.runNotepadCanary({ canary: "proof" }, "cmd-1").then((result) => {
  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.error, "windows_native_shell_required");
  console.log("windows desktop control tests passed");
});
