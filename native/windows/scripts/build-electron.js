#!/usr/bin/env node
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const windowsRoot = path.resolve(__dirname, "..");
const srcRoot = path.join(windowsRoot, "src");
const platformOrTarget = process.argv[2] || "win";
const targetOrArch = process.argv[3] || "nsis";
const archArg = process.argv[4] || "x64";
const electronBuilder = path.join(srcRoot, "node_modules", ".bin", process.platform === "win32" ? "electron-builder.cmd" : "electron-builder");
const hostNsisRoot = path.join(srcRoot, "build", "nsis-host");

const knownPlatforms = new Set(["win", "windows", "linux", "mac", "macos"]);
const requestedPlatform = knownPlatforms.has(platformOrTarget) ? platformOrTarget : "win";
const platform = requestedPlatform === "windows" ? "win" : requestedPlatform === "macos" ? "mac" : requestedPlatform;
const target = knownPlatforms.has(platformOrTarget) ? targetOrArch : platformOrTarget;
const arch = knownPlatforms.has(platformOrTarget) ? archArg : targetOrArch;
const platformFlag = {
  win: "--win",
  linux: "--linux",
  mac: "--mac",
}[platform];

if (!platformFlag) {
  console.error(`Unsupported Electron platform: ${platform}`);
  process.exit(1);
}

const env = { ...process.env };
if (!env.ELECTRON_BUILDER_NSIS_DIR && fs.existsSync(path.join(hostNsisRoot, "linux", "makensis"))) {
  env.ELECTRON_BUILDER_NSIS_DIR = hostNsisRoot;
}

const args = [platformFlag, target, `--${arch}`, "--config", "electron-builder.json", "--publish=never"];
const result = spawnSync(electronBuilder, args, {
  cwd: srcRoot,
  env,
  stdio: "inherit",
  shell: process.platform === "win32",
});
process.exit(result.status == null ? 1 : result.status);
