"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const root = fs.mkdtempSync(path.join(os.tmpdir(), "wasm-agent-hot-ops-hmr-"));
const opDir = path.join(root, "android");
fs.mkdirSync(opDir, { recursive: true });
const manifestPath = path.join(opDir, "hmr-proof.manifest.json");
const opPath = path.join(opDir, "hmr-proof.js");

fs.writeFileSync(manifestPath, JSON.stringify({
  name: "hmr_proof",
  version: "A",
  entry: "hmr-proof.js",
  capabilities: [],
  timeoutMs: 1000,
}, null, 2));

function writeOp(version) {
  fs.writeFileSync(opPath, `"use strict"; module.exports.run = async () => ({ ok: true, stable: true, version: "${version}" });\n`);
}

async function runOnce() {
  delete require.cache[require.resolve(opPath)];
  const loaded = require(opPath);
  return loaded.run({});
}

(async () => {
  writeOp("A");
  const first = await runOnce();
  assert.strictEqual(first.version, "A");
  writeOp("B");
  const second = await runOnce();
  assert.strictEqual(second.version, "B");
  assert(fs.existsSync(manifestPath), "manifest stayed in the same hot ops root");
  console.log("windows hot ops hmr ok");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
