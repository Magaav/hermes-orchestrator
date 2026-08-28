#!/usr/bin/env node
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const windowsRoot = path.resolve(__dirname, "..");
const launcherRoot = path.join(windowsRoot, "launcher");
const defaultOutput = path.join(windowsRoot, "src", "build", "wasm-agent-launcher.exe");

function buildWindowsLauncher(outputPath = defaultOutput) {
  const result = spawnSync("go", ["build", "-trimpath", "-ldflags", "-s -w", "-o", outputPath, "."], {
    cwd: launcherRoot,
    env: { ...process.env, GOOS: "windows", GOARCH: "amd64", CGO_ENABLED: "0" },
    stdio: "inherit",
  });
  if (result.status !== 0) throw new Error(`go build failed while building ${outputPath}`);
  return outputPath;
}

if (require.main === module) buildWindowsLauncher();

module.exports = { buildWindowsLauncher };
