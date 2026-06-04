#!/usr/bin/env node
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const windowsRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(windowsRoot, "..", "..");
const srcRoot = path.join(windowsRoot, "src");
const buildRoot = path.join(srcRoot, "build");
const pwaIcon = path.join(repoRoot, "plugins", "wasm-agent", "public", "icons", "icon.svg");
const nativeIconSvg = path.join(buildRoot, "icon.svg");
const nativeIconIco = path.join(buildRoot, "icon.ico");
const nativeDefaults = path.join(buildRoot, "native-defaults.json");
const nativeDefaultsApp = path.join(srcRoot, "native-defaults.json");
const nativeUninstaller = path.join(buildRoot, "wasm-agent-uninstaller.exe");
const nativeUninstallerScript = path.join(buildRoot, "uninstaller.nsi");
const hostNsisRoot = path.join(buildRoot, "nsis-host");
const packageJsonPath = path.join(srcRoot, "package.json");
const staticServerPath = path.join(repoRoot, "plugins", "wasm-agent", "server", "static_server.py");
const waEnvPath = path.join(repoRoot, "plugins", "wasm-agent", "conf", "wa.env");
const defaultServerUrl = normalizeUrl(process.env.WASM_AGENT_DEFAULT_SERVER_URL || "https://wa.colmeio.com");

function normalizeUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const withProtocol = /^https?:\/\//i.test(raw) ? raw : `http://${raw}`;
  try {
    const url = new URL(withProtocol);
    return url.toString().replace(/\/$/, "");
  } catch {
    return "";
  }
}

function addUrl(urls, value) {
  const url = normalizeUrl(value);
  if (!url) return;
  if (!urls.some((existing) => existing.toLowerCase() === url.toLowerCase())) urls.push(url);
}

function networkCandidateUrls(port) {
  const urls = [];
  Object.values(os.networkInterfaces()).flat().forEach((entry) => {
    if (!entry || entry.family !== "IPv4" || entry.internal) return;
    addUrl(urls, `http://${entry.address}:${port}`);
  });
  return urls;
}

function allowLocalDevCandidates() {
  return String(process.env.WASM_AGENT_ALLOW_LOCAL_DEV || "").trim() === "1";
}

function isLocalDevUrl(value) {
  const url = normalizeUrl(value);
  if (!url) return false;
  try {
    const hostname = new URL(url).hostname.toLowerCase();
    if (hostname === "localhost" || hostname === "0.0.0.0" || hostname === "::1" || hostname === "[::1]") return true;
    if (hostname === "host.docker.internal" || hostname.endsWith(".local")) return true;
    if (hostname.startsWith("127.")) return true;
    if (hostname.startsWith("10.")) return true;
    if (hostname.startsWith("192.168.")) return true;
    const match = hostname.match(/^172\.(\d+)\./);
    return Boolean(match && Number(match[1]) >= 16 && Number(match[1]) <= 31);
  } catch {
    return false;
  }
}

function readJsonFile(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return {};
  }
}

function readWasmAgentVersion() {
  try {
    const source = fs.readFileSync(staticServerPath, "utf8");
    const match = source.match(/PLUGIN_VERSION\s*=\s*"([^"]+)"/);
    return match ? match[1] : "";
  } catch {
    return "";
  }
}

function readEnvFileValue(filePath, name) {
  try {
    const source = fs.readFileSync(filePath, "utf8");
    for (const line of source.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const index = trimmed.indexOf("=");
      if (index <= 0) continue;
      if (trimmed.slice(0, index).trim() !== name) continue;
      return trimmed.slice(index + 1).trim().replace(/^['"]|['"]$/g, "");
    }
  } catch {
    return "";
  }
  return "";
}

function nativeBuildStamp(date = new Date()) {
  return date.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
}

function forceSymlink(target, linkPath) {
  fs.rmSync(linkPath, { recursive: true, force: true });
  fs.symlinkSync(target, linkPath, "junction");
}

function findCachedElectronBuilderFile(fileName) {
  const roots = [
    path.join(os.homedir(), ".cache", "electron-builder", "nsis"),
    path.join(process.env.XDG_CACHE_HOME || "", "electron-builder", "nsis"),
  ].filter(Boolean);
  const queue = roots.filter((root) => fs.existsSync(root));
  while (queue.length) {
    const current = queue.shift();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const entryPath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        queue.push(entryPath);
      } else if (entry.name === fileName) {
        return entryPath;
      }
    }
  }
  return "";
}

function prepareHostNsisShim() {
  if (process.platform !== "linux") return;
  const systemNsisRoot = "/usr/share/nsis";
  const systemMakensis = "/usr/bin/makensis";
  if (!fs.existsSync(systemNsisRoot) || !fs.existsSync(systemMakensis)) return;
  fs.mkdirSync(path.join(hostNsisRoot, "linux"), { recursive: true });
  fs.rmSync(path.join(hostNsisRoot, "linux", "makensis"), { force: true });
  fs.symlinkSync(systemMakensis, path.join(hostNsisRoot, "linux", "makensis"));
  ["Bin", "Contrib", "Include", "Plugins", "Stubs"].forEach((name) => {
    forceSymlink(path.join(systemNsisRoot, name), path.join(hostNsisRoot, name));
  });
  const elevate = findCachedElectronBuilderFile("elevate.exe");
  if (elevate) fs.copyFileSync(elevate, path.join(hostNsisRoot, "elevate.exe"));
}

function prepareUninstaller() {
  const systemMakensis = "/usr/bin/makensis";
  if (process.platform !== "linux" || !fs.existsSync(systemMakensis) || !fs.existsSync(nativeUninstallerScript)) return;
  const result = spawnSync(systemMakensis, [`-DOUT_FILE=${nativeUninstaller}`, nativeUninstallerScript], {
    cwd: buildRoot,
    stdio: "inherit",
  });
  if (result.status !== 0) throw new Error(`makensis failed while building ${nativeUninstaller}`);
}

function main() {
  fs.mkdirSync(buildRoot, { recursive: true });
  if (!fs.existsSync(pwaIcon)) throw new Error(`Missing PWA icon: ${pwaIcon}`);
  if (!fs.existsSync(nativeIconIco)) throw new Error(`Missing Windows icon: ${nativeIconIco}`);
  fs.copyFileSync(pwaIcon, nativeIconSvg);
  prepareHostNsisShim();
  prepareUninstaller();

  const port = String(process.env.HERMES_WASM_AGENT_PORT || "8877").trim() || "8877";
  const host = String(process.env.HERMES_WASM_AGENT_HOST || "").trim();
  const urls = [];
  const allowLocal = allowLocalDevCandidates();
  const candidateValues = [
    defaultServerUrl,
    process.env.HERMES_WASM_AGENT_NATIVE_SERVER_URL,
    process.env.HERMES_WASM_AGENT_PUBLIC_URL,
    process.env.WASM_AGENT_PUBLIC_URL,
    process.env.WASM_AGENT_SERVER_URL,
  ];
  if (allowLocal) {
    candidateValues.push(
      host ? `http://${host}:${port}` : "",
    ...networkCandidateUrls(port),
      `http://${os.hostname()}:${port}`,
      `http://${os.hostname()}.local:${port}`,
      `http://host.docker.internal:${port}`,
      `http://localhost:${port}`,
      `http://127.0.0.1:${port}`,
    );
  }
  candidateValues.forEach((value) => {
    if (!allowLocal && isLocalDevUrl(value)) return;
    addUrl(urls, value);
  });

  const builtAt = new Date();
  const nativePackage = readJsonFile(packageJsonPath);
  const nativeShellVersion = String(nativePackage.version || "0.1.0");
  const wasmAgentVersion = readWasmAgentVersion() || nativeShellVersion;
  const buildId = process.env.WASM_AGENT_NATIVE_BUILD_ID || `win-x64-${nativeBuildStamp(builtAt)}`;
  const googleClientId = String(
    process.env.HERMES_WASM_AGENT_GOOGLE_CLIENT_ID
    || process.env.GOOGLE_LOGIN_CLIENT_ID
    || readEnvFileValue(waEnvPath, "GOOGLE_LOGIN_CLIENT_ID")
    || ""
  ).trim();
  const payload = {
    schema: "hermes.wasm_agent.native_defaults.v1",
    appId: "wasm-agent",
    service: "wasm-agent",
    mode: allowLocal ? "development" : "production",
    allowLocalDev: allowLocal,
    generatedAt: builtAt.toISOString(),
    wasmAgentVersion,
    nativeShellVersion,
    installableVersion: `${wasmAgentVersion}+${buildId}`,
    buildId,
    buildPlatform: "windows",
    buildArch: "x64",
    buildChannel: "nsis",
    googleClientId,
    serverUrl: urls[0] || defaultServerUrl,
    serverUrlCandidates: urls,
  };
  const payloadText = `${JSON.stringify(payload, null, 2)}\n`;
  fs.writeFileSync(nativeDefaults, payloadText);
  fs.writeFileSync(nativeDefaultsApp, payloadText);
  console.log(`Prepared ${path.relative(windowsRoot, nativeIconSvg)}`);
  console.log(`Prepared ${path.relative(windowsRoot, nativeDefaults)}`);
  console.log(`Prepared ${path.relative(windowsRoot, nativeDefaultsApp)}`);
  if (fs.existsSync(path.join(hostNsisRoot, "linux", "makensis"))) {
    console.log(`Prepared ${path.relative(windowsRoot, hostNsisRoot)}`);
  }
  if (fs.existsSync(nativeUninstaller)) {
    console.log(`Prepared ${path.relative(windowsRoot, nativeUninstaller)}`);
  }
}

main();
