"use strict";

const assert = require("node:assert");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const tempHome = fs.mkdtempSync(path.join(os.tmpdir(), "wasm-agent-hot-op-override-"));
const repoRoot = path.resolve(__dirname, "..", "..", "..");
const script = path.join(__dirname, "..", "scripts", "sync-hot-op-override.js");

const output = execFileSync(process.execPath, [script, "android", "hermes-wake-proof"], {
  cwd: repoRoot,
  env: { ...process.env, HOME: tempHome, USERPROFILE: tempHome },
  encoding: "utf8",
});
const result = JSON.parse(output);
assert.strictEqual(result.ok, true);
assert.strictEqual(result.platform, "android");
assert.strictEqual(result.op, "hermes-wake-proof");
assert.strictEqual(result.overrideRoot, path.join(tempHome, ".wasm-agent", "hot-ops"));

const sourceOp = path.join(repoRoot, "native", "windows", "ops", "android", "hermes-wake-proof.js");
const sourceManifest = path.join(repoRoot, "native", "windows", "ops", "android", "hermes-wake-proof.manifest.json");
const overrideOp = path.join(tempHome, ".wasm-agent", "hot-ops", "android", "hermes-wake-proof.js");
const overrideManifest = path.join(tempHome, ".wasm-agent", "hot-ops", "android", "hermes-wake-proof.manifest.json");

assert(fs.existsSync(overrideOp), "override hot op was copied");
assert(fs.existsSync(overrideManifest), "override manifest was copied");
assert.strictEqual(sha256(overrideOp), sha256(sourceOp), "override hot op matches patched source");
assert.strictEqual(sha256(overrideManifest), sha256(sourceManifest), "override manifest matches patched source");

console.log("windows hot ops override sync ok");

function sha256(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}
