#!/usr/bin/env node
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const windowsRoot = path.resolve(__dirname, "..");
const srcRoot = path.join(windowsRoot, "src");
const buildRoot = path.join(srcRoot, "build");
const defaultOutput = path.join(srcRoot, "generated", "wasm-agent-uninstaller.exe");
const uninstallerScript = path.join(buildRoot, "uninstaller.nsi");

function resolveMakensis(platform = process.platform) {
  const candidates = platform === "win32"
    ? [path.join(srcRoot, "node_modules", "@nsis-u", "makensis", "makensis.exe")]
    : platform === "linux"
      ? ["/usr/bin/makensis"]
      : [];
  return candidates.find((candidate) => fs.existsSync(candidate)) || "";
}

function buildWindowsUninstaller(outputPath = defaultOutput) {
  const makensis = resolveMakensis();
  if (!makensis) {
    if (process.platform === "darwin") return "";
    throw new Error(`makensis is unavailable on ${process.platform}`);
  }
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  const result = spawnSync(makensis, [`-DOUT_FILE=${outputPath}`, uninstallerScript], {
    cwd: buildRoot,
    stdio: "inherit",
  });
  if (result.status !== 0) throw new Error(`makensis failed while building ${outputPath}`);
  return outputPath;
}

if (require.main === module) buildWindowsUninstaller();

module.exports = { buildWindowsUninstaller, resolveMakensis };
