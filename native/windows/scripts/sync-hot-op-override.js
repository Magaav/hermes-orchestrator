"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");

function usage() {
  console.error("Usage: node native/windows/scripts/sync-hot-op-override.js <platform> <op>");
  console.error("Example: node native/windows/scripts/sync-hot-op-override.js android hermes-wake-proof");
}

const platform = String(process.argv[2] || "").trim();
const op = String(process.argv[3] || "").trim();
if (!platform || !op || platform.includes("..") || op.includes("..") || path.isAbsolute(platform) || path.isAbsolute(op)) {
  usage();
  process.exit(2);
}

const repoRoot = path.resolve(__dirname, "..", "..", "..");
const sourceDir = path.join(repoRoot, "native", "windows", "ops", platform);
const overrideRoot = process.env.WASM_AGENT_HOT_OPS_OVERRIDE_DIR
  ? path.resolve(process.env.WASM_AGENT_HOT_OPS_OVERRIDE_DIR)
  : path.join(os.homedir(), ".wasm-agent", "hot-ops");
const targetDir = path.join(overrideRoot, platform);

const sourceOp = path.join(sourceDir, `${op}.js`);
const sourceManifest = path.join(sourceDir, `${op}.manifest.json`);
const targetOp = path.join(targetDir, `${op}.js`);
const targetManifest = path.join(targetDir, `${op}.manifest.json`);

for (const source of [sourceOp, sourceManifest]) {
  if (!fs.existsSync(source) || !fs.statSync(source).isFile()) {
    console.error(`Missing hot-op source: ${source}`);
    process.exit(1);
  }
}

fs.mkdirSync(targetDir, { recursive: true });
fs.copyFileSync(sourceOp, targetOp);
fs.copyFileSync(sourceManifest, targetManifest);

console.log(JSON.stringify({
  ok: true,
  platform,
  op,
  overrideRoot,
  files: [targetOp, targetManifest],
  enableRuntime: "Set WASM_AGENT_ENABLE_HOT_OP_OVERRIDES=1 before launching the installed Windows app.",
}, null, 2));
