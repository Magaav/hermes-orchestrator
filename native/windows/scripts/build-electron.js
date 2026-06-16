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
const releaseRoot = path.join(windowsRoot, "release");
const nativeDefaultsPath = path.join(srcRoot, "build", "native-defaults.json");
const verifyWindowsInstaller = path.join(windowsRoot, "scripts", "verify-windows-installer.js");
const auditPackageSize = path.join(windowsRoot, "scripts", "audit-package-size.js");

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

if (platform === "win" && target === "nsis") {
  fs.rmSync(releaseRoot, { recursive: true, force: true });
  fs.mkdirSync(releaseRoot, { recursive: true });
}

const env = { ...process.env };
if (!env.ELECTRON_BUILDER_NSIS_DIR && fs.existsSync(path.join(hostNsisRoot, "linux", "makensis"))) {
  env.ELECTRON_BUILDER_NSIS_DIR = hostNsisRoot;
}

const args = [platformFlag, target, `--${arch}`, "--config", "electron-builder.json", "--publish=never"];
if (platform === "win" && process.env.WASM_AGENT_SKIP_WIN_RESOURCE_EDIT === "1") {
  args.push("-c.win.signAndEditExecutable=false");
}
const result = spawnSync(electronBuilder, args, {
  cwd: srcRoot,
  env,
  stdio: "inherit",
  shell: process.platform === "win32",
});
const status = result.status == null ? 1 : result.status;
if (status === 0 && platform === "win" && target === "nsis") {
  auditWindowsPackage();
  const versionedInstaller = promoteVersionedWindowsInstaller(arch);
  verifyInstaller(versionedInstaller || path.join(releaseRoot, `WASM-Agent-Setup-${arch}.exe`));
}
process.exit(status);

function safeFilenamePart(value) {
  return String(value || "").replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^[._-]+|[._-]+$/g, "");
}

function versionedWindowsInstallerName(archName, defaults) {
  const version = safeFilenamePart(defaults.wasmAgentVersion || defaults.nativeShellVersion || "0.1.0");
  const buildId = safeFilenamePart(defaults.buildId || "");
  const buildSuffix = buildId.startsWith(`win-${archName}-`) ? buildId.slice(`win-${archName}-`.length) : buildId.replace(/^win-[^-]+-/, "");
  return `WASM-Agent-Setup-${archName}-${[version, buildSuffix].filter(Boolean).join("-")}.exe`;
}

function promoteVersionedWindowsInstaller(archName) {
  const source = path.join(releaseRoot, `WASM-Agent-Setup-${archName}.exe`);
  if (!fs.existsSync(source) || !fs.existsSync(nativeDefaultsPath)) return "";
  const defaults = JSON.parse(fs.readFileSync(nativeDefaultsPath, "utf8"));
  const versionedName = versionedWindowsInstallerName(archName, defaults);
  const targetPath = path.join(releaseRoot, versionedName);
  const sidecarPath = path.join(releaseRoot, `${path.basename(targetPath, ".exe")}.native-defaults.json`);
  fs.copyFileSync(source, targetPath);
  fs.writeFileSync(sidecarPath, `${JSON.stringify(defaults, null, 2)}\n`);
  const unpackedDefaults = path.join(releaseRoot, "win-unpacked", "resources", "native-defaults.json");
  if (fs.existsSync(path.dirname(unpackedDefaults))) {
    fs.copyFileSync(nativeDefaultsPath, unpackedDefaults);
  }
  console.log(`Promoted ${path.relative(releaseRoot, targetPath)}`);
  console.log(`Wrote ${path.relative(releaseRoot, sidecarPath)}`);
  return targetPath;
}

function verifyInstaller(installerPath) {
  const result = spawnSync(process.execPath, [verifyWindowsInstaller, installerPath], {
    cwd: srcRoot,
    env: process.env,
    stdio: "inherit",
  });
  if (result.status !== 0) process.exit(result.status == null ? 1 : result.status);
}

function auditWindowsPackage() {
  const result = spawnSync(process.execPath, [auditPackageSize, path.join(releaseRoot, "win-unpacked")], {
    cwd: srcRoot,
    env: process.env,
    stdio: "inherit",
  });
  if (result.status !== 0) process.exit(result.status == null ? 1 : result.status);
}
