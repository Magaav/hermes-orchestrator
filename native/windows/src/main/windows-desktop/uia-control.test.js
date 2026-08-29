"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { ACTIONS, automationScript, createWindowsDesktopAutomation, normalizedRequest } = require("./uia-control");

assert(ACTIONS.includes("set_value") && ACTIONS.includes("invoke"));
assert.deepStrictEqual(normalizedRequest("windows_desktop_inspect", { max_elements: 999, max_depth: 0 }), { target: {}, max_elements: 200, max_depth: 12, include_values: false, timeout_ms: 15000 });
assert.throws(() => normalizedRequest("windows_desktop_act", { snapshot_id: "bad", ref: "e0", action: "invoke" }), /snapshot_ref_invalid/);
assert.throws(() => normalizedRequest("windows_desktop_act", { snapshot_id: "s-0123456789abcdef", ref: "e0", action: "arbitrary" }), /action_invalid/);
const script = automationScript({ operation: "inspect", target: {}, max_elements: 20, max_depth: 4 });
assert(script.includes("AutomationElement") && script.includes("GetForegroundWindow") && script.includes("windows.uia.snapshot"));
assert(script.includes("return $result.ToArray()") && !script.includes("return ,$result.ToArray()"));
assert(script.includes("windows_desktop_enumeration_empty") && script.includes("enumeration_errors=$enumerationErrors"));
assert(script.includes("throw 'windows_desktop_target_missing'") && script.includes("process_id=[int]$current.ProcessId"));
assert(script.includes("IsPassword") && script.includes("value_truncated") && script.includes("include_values"));
const packageConfig = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "electron-builder.json"), "utf8"));
assert(packageConfig.files.includes("main/windows-desktop/uia-control.js"));
assert(!packageConfig.files.some((entry) => entry.includes("windows-desktop/*.js")));
assert(packageConfig.files.includes("main/windows-native-commands.js"));
const verifier = fs.readFileSync(path.join(__dirname, "..", "..", "..", "scripts", "verify-windows-installer.js"), "utf8");
assert(verifier.includes("sourceWindowsDesktopUiaPath") && verifier.includes("sourceCompanionStartupPath") && verifier.includes("wasm-agent:companion-window"));

(async () => {
  const control = createWindowsDesktopAutomation({ platform: "linux" });
  const described = control.describe();
  assert.strictEqual(described.authority, "current_user_token");
  assert.strictEqual(described.elevation_supported, false);
  assert.strictEqual((await control.execute("windows_desktop_inspect", {}, "cmd-1")).error, "windows_native_shell_required");
  console.log("generic Windows desktop UIA tests passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
