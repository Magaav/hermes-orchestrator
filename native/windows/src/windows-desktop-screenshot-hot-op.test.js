"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const modulePath = path.join(__dirname, "..", "ops", "desktop", "windows-desktop-screenshot.js");
const manifestPath = path.join(__dirname, "..", "ops", "desktop", "windows-desktop-screenshot.manifest.json");
const operation = require(modulePath);
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));

assert.strictEqual(manifest.operationId, "capture_windows_desktop_screenshot");
assert.strictEqual(manifest.entry, "windows-desktop-screenshot.js");
assert(manifest.requiredNativeCapabilities.includes("native.capabilities.hotOps.v1"));
assert.strictEqual(manifest.safetyLimits.modelPayload, "metadata only");
assert(!operation.powershellScript().includes("Convert]::ToBase64String"), "pixels must not enter the JSON receipt");

const normalized = operation.normalize({
  path: "C:\\Users\\Victor\\AppData\\Local\\WASM-Agent\\proof\\desktop.png",
  sha256: "a".repeat(64), width: 3840, height: 1080, left: -1920, top: 0,
  capturedAt: "2026-08-27T16:00:00.0000000Z",
});
assert.strictEqual(normalized.ok, true);
assert.strictEqual(normalized.artifact.scope, "virtual_desktop");
assert.strictEqual(normalized.artifact.containsSensitivePixels, true);
assert.deepStrictEqual(normalized.proof, ["windows.desktop.screenshot"]);
assert.strictEqual(operation.normalize({ path: "x", sha256: "bad", width: 1, height: 1 }), null);

operation.run({ markPhase() {} }, {
  platform: "win32",
  executeCapture: async () => ({ ok: true, stdout: JSON.stringify({ path: "C:\\proof.png", sha256: "b".repeat(64), width: 1920, height: 1080, left: 0, top: 0, capturedAt: "now" }) }),
}).then((result) => {
  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.artifact.width, 1920);
  console.log("windows desktop screenshot hot op ok");
}).catch((error) => { console.error(error); process.exitCode = 1; });
