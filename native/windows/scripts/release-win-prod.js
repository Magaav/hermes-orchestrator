#!/usr/bin/env node
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const windowsRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(windowsRoot, "..", "..");
const srcRoot = path.join(windowsRoot, "src");

function rm(target) {
  fs.rmSync(target, { recursive: true, force: true });
  console.log(`cleaned ${path.relative(repoRoot, target) || target}`);
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: srcRoot,
    env: {
      ...process.env,
      WASM_AGENT_DEFAULT_SERVER_URL: "https://wa.colmeio.com",
      WASM_AGENT_ALLOW_LOCAL_DEV: "",
    },
    stdio: "inherit",
    shell: process.platform === "win32",
    ...options,
  });
  if (result.status !== 0) process.exit(result.status == null ? 1 : result.status);
}

[
  path.join(windowsRoot, "dist"),
  path.join(windowsRoot, "release"),
  path.join(repoRoot, "dist"),
  path.join(repoRoot, "release"),
  path.join(srcRoot, "dist"),
  path.join(srcRoot, "release"),
].forEach(rm);

run(process.platform === "win32" ? "npm.cmd" : "npm", ["run", "prepare:native-assets"]);
run(process.execPath, [path.join(windowsRoot, "scripts", "build-electron.js"), "nsis", "x64"]);
