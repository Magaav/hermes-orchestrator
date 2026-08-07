const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const script = path.join(__dirname, "audit-package-size.js");

function runFixture(files, env = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "wasm-agent-size-policy-"));
  try {
    for (const [relative, bytes] of Object.entries(files)) {
      const target = path.join(root, relative);
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.writeFileSync(target, Buffer.alloc(bytes));
    }
    return spawnSync(process.execPath, [script, root], { encoding: "utf8", env: { ...process.env, ...env } });
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

assert.strictEqual(runFixture({ "WASM Agent.exe": 2 * 1024 * 1024 }).status, 0, "size alone must not fail the semantic inventory policy");
assert.strictEqual(runFixture({ "resources/app.asar": 1024, "resources/bridge-ops/canary/echo.js": 1024 }).status, 0);
assert.notStrictEqual(runFixture({ "resources/public/models/model.onnx": 1024 }).status, 0);
assert.notStrictEqual(runFixture({ "resources/android/WASM-Agent.apk": 1024 }).status, 0);
assert.notStrictEqual(runFixture({ "resources/mystery/payload.dat": 1024 }).status, 0, "undeclared resource owners must fail");
console.log("windows package size policy tests passed");
