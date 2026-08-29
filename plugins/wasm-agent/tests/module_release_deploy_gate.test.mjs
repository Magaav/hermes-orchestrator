import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

const pluginRoot = path.resolve(new URL("..", import.meta.url).pathname);
const generator = path.join(pluginRoot, "scripts", "generate-module-release.mjs");
const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "wasm-agent-module-release-"));
const candidate = path.join(tempRoot, "module-release.json");
try {
  let result = spawnSync(process.execPath, [generator, "--output", candidate], { cwd: pluginRoot, encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  result = spawnSync(process.execPath, [generator, "--check", "--output", candidate], { cwd: pluginRoot, encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).mode, "check");

  const stale = JSON.parse(fs.readFileSync(candidate, "utf8"));
  stale.release_id = "0".repeat(64);
  fs.writeFileSync(candidate, `${JSON.stringify(stale, null, 2)}\n`);
  result = spawnSync(process.execPath, [generator, "--check", "--output", candidate], { cwd: pluginRoot, encoding: "utf8" });
  assert.equal(result.status, 2);
  assert.equal(JSON.parse(result.stderr).error, "module_release_stale");
} finally {
  fs.rmSync(tempRoot, { recursive: true, force: true });
}

const service = fs.readFileSync(path.join(pluginRoot, "systemd", "wasm-agent-production.service"), "utf8");
assert.match(service, /^ExecStartPre=\/usr\/bin\/node plugins\/wasm-agent\/scripts\/generate-module-release\.mjs --check$/m);
const deploy = fs.readFileSync(path.join(pluginRoot, "scripts", "deploy-cloud-modules.sh"), "utf8");
assert.match(deploy, /generate-module-release\.mjs\nnode scripts\/generate-module-release\.mjs --check\nsystemctl --user restart/);
console.log("module release deployment gate tests passed");
