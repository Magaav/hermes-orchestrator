#!/usr/bin/env node
const { spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const windowsRoot = path.resolve(__dirname, "..");
const srcRoot = path.join(windowsRoot, "src");
const releaseRoot = path.join(windowsRoot, "release");
const installerPath = path.resolve(process.argv[2] || path.join(releaseRoot, "WASM-Agent-Setup-x64.exe"));
const asar = require(path.join(srcRoot, "node_modules", "@electron", "asar"));

function fail(message) {
  console.error(message);
  process.exit(1);
}

function sha256(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function sevenZipPath() {
  const platform = process.platform === "darwin" ? "mac" : process.platform;
  const arch = { x64: "x64", arm64: "arm64", ia32: "ia32", arm: "arm" }[process.arch] || process.arch;
  const exe = process.platform === "win32" ? "7za.exe" : "7za";
  const candidate = path.join(srcRoot, "node_modules", "7zip-bin", platform, arch, exe);
  if (fs.existsSync(candidate)) {
    if (process.platform !== "win32") {
      try {
        fs.chmodSync(candidate, fs.statSync(candidate).mode | 0o755);
      } catch {
        // The following spawn will report the real failure with context.
      }
    }
    return candidate;
  }
  return "";
}

function run(command, args) {
  const result = spawnSync(command, args, { stdio: "pipe", encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed\n${result.stdout}\n${result.stderr}`);
  }
  return result.stdout;
}

function walkFiles(root) {
  const out = [];
  const stack = [root];
  while (stack.length) {
    const current = stack.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const entryPath = path.join(current, entry.name);
      if (entry.isDirectory()) stack.push(entryPath);
      else out.push(entryPath);
    }
  }
  return out;
}

function textForSearch(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (!["", ".cmd", ".html", ".js", ".json", ".md", ".nsh", ".ps1", ".txt"].includes(ext)) return "";
  try {
    const buffer = fs.readFileSync(filePath);
    if (buffer.includes(0)) return "";
    return buffer.toString("utf8");
  } catch {
    return "";
  }
}

function searchFiles(root, patterns) {
  const hits = [];
  for (const filePath of walkFiles(root)) {
    const text = textForSearch(filePath);
    if (!text) continue;
    const rel = path.relative(root, filePath);
    text.split(/\r?\n/).forEach((line, index) => {
      for (const pattern of patterns) {
        if (pattern.test(line)) hits.push(`${rel}:${index + 1}: ${line.trim()}`);
      }
    });
  }
  return hits;
}

function findFile(root, relativePath) {
  const normalized = relativePath.replace(/[\\/]+/g, path.sep);
  const direct = path.join(root, normalized);
  if (fs.existsSync(direct)) return direct;
  return walkFiles(root).find((filePath) => filePath.replace(/[\\/]+/g, "/").endsWith(relativePath.replace(/[\\/]+/g, "/"))) || "";
}

function findAppAsar(extractRoot) {
  const direct = path.join(extractRoot, "app", "resources", "app.asar");
  if (fs.existsSync(direct)) return direct;
  const found = walkFiles(extractRoot).find((filePath) => path.basename(filePath) === "app.asar");
  if (found) return found;
  const nestedArchives = walkFiles(extractRoot).filter((filePath) => /\.7z$/i.test(filePath));
  for (const archive of nestedArchives) {
    const nestedRoot = `${archive}.extract`;
    fs.mkdirSync(nestedRoot, { recursive: true });
    run(sevenZipPath(), ["x", "-y", `-o${nestedRoot}`, archive]);
    const nestedAsar = findAppAsar(nestedRoot);
    if (nestedAsar) return nestedAsar;
  }
  return "";
}

if (!fs.existsSync(installerPath)) fail(`Missing installer: ${installerPath}`);
const sevenZip = sevenZipPath();
if (!sevenZip) fail("Missing 7zip-bin executable for this platform");

const extractRoot = fs.mkdtempSync(path.join(os.tmpdir(), "wasm-agent-installer-"));
const asarRoot = fs.mkdtempSync(path.join(os.tmpdir(), "wasm-agent-asar-"));
run(sevenZip, ["x", "-y", `-o${extractRoot}`, installerPath]);
const appAsarPath = findAppAsar(extractRoot);
if (!appAsarPath) fail(`Installer did not contain resources/app.asar: ${installerPath}`);
asar.extractAll(appAsarPath, asarRoot);

const nativeDefaultsPath = [
  path.join(asarRoot, "native-defaults.json"),
  path.join(asarRoot, "build", "native-defaults.json"),
].find((candidate) => fs.existsSync(candidate)) || path.join(asarRoot, "native-defaults.json");
const sourceDefaultsPath = path.join(srcRoot, "build", "native-defaults.json");
const fallbackPath = path.join(asarRoot, "fallback.html");
const packagePath = path.join(asarRoot, "package.json");
const resourceDefaultsPath = path.join(path.dirname(appAsarPath), "native-defaults.json");
const resourcePublicRoot = path.join(path.dirname(appAsarPath), "public");
const resourceIndexHtmlPath = findFile(resourcePublicRoot, "index.html");
const resourceAppJsPath = findFile(resourcePublicRoot, "app.js");
const resourceDevHmrPath = findFile(resourcePublicRoot, "modules/hmr/dev-hmr.js");
const resourceBootJsPath = findFile(resourcePublicRoot, "boot.js");
const resourceIconPath = findFile(path.dirname(appAsarPath), "icon.ico");
const resourceHorcRunnerPath = findFile(path.dirname(appAsarPath), "horc/horc-local.js");
const resourceAppSimulatorPath = findFile(path.dirname(appAsarPath), "horc/app-simulator/simulate.js");
const resourceAndroidApkPath = findFile(path.dirname(appAsarPath), "android/WASM-Agent-arm64.apk");
const resourceAndroidApkDefaultsPath = findFile(path.dirname(appAsarPath), "android/WASM-Agent-arm64.native-defaults.json");
const mainJsPath = path.join(asarRoot, "main.js");
const preloadJsPath = path.join(asarRoot, "preload.js");
const nativeDefaults = fs.existsSync(nativeDefaultsPath)
  ? JSON.parse(fs.readFileSync(nativeDefaultsPath, "utf8"))
  : {};
const sourceDefaults = fs.existsSync(sourceDefaultsPath)
  ? JSON.parse(fs.readFileSync(sourceDefaultsPath, "utf8"))
  : {};
const resourceDefaults = fs.existsSync(resourceDefaultsPath)
  ? JSON.parse(fs.readFileSync(resourceDefaultsPath, "utf8"))
  : {};
const fallbackHtml = fs.existsSync(fallbackPath) ? fs.readFileSync(fallbackPath, "utf8") : "";
const packageJson = fs.existsSync(packagePath) ? JSON.parse(fs.readFileSync(packagePath, "utf8")) : {};
const resourceIndexHtml = resourceIndexHtmlPath ? fs.readFileSync(resourceIndexHtmlPath, "utf8") : "";
const resourceAppJs = resourceAppJsPath ? fs.readFileSync(resourceAppJsPath, "utf8") : "";
const resourceDevHmrJs = resourceDevHmrPath ? fs.readFileSync(resourceDevHmrPath, "utf8") : "";
const resourceBootJs = resourceBootJsPath ? fs.readFileSync(resourceBootJsPath, "utf8") : "";
const resourceHorcRunnerJs = resourceHorcRunnerPath ? fs.readFileSync(resourceHorcRunnerPath, "utf8") : "";
const mainJs = fs.existsSync(mainJsPath) ? fs.readFileSync(mainJsPath, "utf8") : "";
const preloadJs = fs.existsSync(preloadJsPath) ? fs.readFileSync(preloadJsPath, "utf8") : "";
const patterns = [
  /127\.0\.0\.1:8877/,
  /localhost:8877/,
  /0\.0\.0\.0:8877/,
  /native build loading/,
  /No backend with an available \/config\.json/,
  /native-defaults\.json/,
  /wa\.colmeio\.com/,
];
const payloadHits = searchFiles(extractRoot, patterns);
const asarHits = searchFiles(asarRoot, patterns);

console.log(`installer path: ${installerPath}`);
console.log(`installer build timestamp: ${fs.statSync(installerPath).mtime.toISOString()}`);
console.log(`installer SHA-256: ${sha256(installerPath)}`);
console.log(`resources/app.asar path: ${appAsarPath}`);
console.log(`resources/app.asar SHA-256: ${sha256(appAsarPath)}`);
console.log(`package.json version from app.asar: ${packageJson.version || ""}`);
console.log("native-defaults.json from app.asar:");
console.log(JSON.stringify(nativeDefaults, null, 2));
console.log("native-defaults.json from source build:");
console.log(JSON.stringify(sourceDefaults, null, 2));
console.log("native-defaults.json from extracted resources:");
console.log(JSON.stringify(resourceDefaults, null, 2));
console.log(`fallback.html SHA-256 from app.asar: ${fallbackHtml ? sha256(fallbackPath) : ""}`);
console.log("fallback.html contents from app.asar:");
console.log(fallbackHtml);
console.log("installer payload search hits:");
console.log(payloadHits.join("\n") || "(none)");
console.log("app.asar search hits:");
console.log(asarHits.join("\n") || "(none)");

const asarText = walkFiles(asarRoot).map((filePath) => textForSearch(filePath)).join("\n");
const payloadText = walkFiles(extractRoot).map((filePath) => textForSearch(filePath)).join("\n");
const banned = [
  "http://127.0.0.1:8877",
  "http://localhost:8877",
  "http://0.0.0.0:8877",
  "127.0.0.1:8877",
  "localhost:8877",
  "WASM Agent native build loading",
  "No backend with an available /config.json",
];
for (const value of banned) {
  if (asarText.includes(value)) fail(`Production app.asar contains banned backend literal: ${value}`);
  if (payloadText.includes(value)) fail(`Production installer payload contains banned backend literal: ${value}`);
}
if (nativeDefaults.serverUrl !== "https://wa.colmeio.com") fail(`app.asar native-defaults.json serverUrl is not cloud: ${nativeDefaults.serverUrl}`);
if (resourceDefaults.serverUrl !== "https://wa.colmeio.com") fail(`resources/native-defaults.json serverUrl is not cloud: ${resourceDefaults.serverUrl}`);
if (nativeDefaults.mode !== "production") fail(`app.asar native-defaults.json mode is not production: ${nativeDefaults.mode || ""}`);
if (nativeDefaults.allowLocalDev !== false) fail(`app.asar native-defaults.json allowLocalDev is not false: ${nativeDefaults.allowLocalDev}`);
if (resourceDefaults.mode !== "production") fail(`resources/native-defaults.json mode is not production: ${resourceDefaults.mode || ""}`);
if (resourceDefaults.allowLocalDev !== false) fail(`resources/native-defaults.json allowLocalDev is not false: ${resourceDefaults.allowLocalDev}`);
if (sourceDefaults.buildId && nativeDefaults.buildId !== sourceDefaults.buildId) {
  fail(`app.asar native-defaults.json buildId (${nativeDefaults.buildId || ""}) does not match freshly generated source buildId (${sourceDefaults.buildId})`);
}
if (sourceDefaults.buildId && resourceDefaults.buildId !== sourceDefaults.buildId) {
  fail(`resources/native-defaults.json buildId (${resourceDefaults.buildId || ""}) does not match freshly generated source buildId (${sourceDefaults.buildId})`);
}
if (!fallbackHtml.includes('value="https://wa.colmeio.com"')) fail("fallback.html default input is not https://wa.colmeio.com");
if (!asarText.includes("wa.colmeio.com") || !payloadText.includes("wa.colmeio.com")) fail("Installer does not contain wa.colmeio.com");
if (!resourceAppJs.includes("__wasmAgentAppDevHmr") || !resourceAppJs.includes("renderer_global_error") || !resourceAppJs.includes("loadAuthSessionReached")) {
  fail("Extracted installer public/app.js is missing Frontier fatal/HMR visibility patches");
}
if (!resourceDevHmrJs.includes("__wasmAgentAppDevHmr")) fail("Extracted installer dev-hmr.js does not prefer the app-owned HMR bridge");
if (!resourceBootJs.includes("renderer_boot_error") || !resourceBootJs.includes("loadAuthSessionReached")) fail("Extracted installer boot.js is missing early fatal diagnostics");
if (!mainJs.includes("frontier_operator_commands_ready") || !mainJs.includes("collectNativeDiagnosticsBundle") || !mainJs.includes("captureNativeScreenshot") || !mainJs.includes("controlledNativeReload")) {
  fail("Extracted installer app.asar main.js is missing Frontier operator capabilities");
}
if (!mainJs.includes("WINDOWS_ANDROID_OAUTH_OPERATIONS") || !mainJs.includes("verify_android_oauth") || !mainJs.includes("read_latest_android_report") || !mainJs.includes("operation_not_allowlisted") || !mainJs.includes("horc simulate android --device --interactive-oauth")) {
  fail("Extracted installer app.asar main.js is missing the Windows Android OAuth diagnostics bridge");
}
if (!mainJs.includes("resolveLocalHorcRunner") || !mainJs.includes("bundledHorcRunnerPath") || !mainJs.includes("ELECTRON_RUN_AS_NODE") || !mainJs.includes("WASM_AGENT_SIM_ROOT_DIR") || !mainJs.includes("WASM_AGENT_ANDROID_APK")) {
  fail("Extracted installer app.asar main.js is missing deterministic bundled horc runner resolution");
}
if (!preloadJs.includes("nativeDiagnostics") || !preloadJs.includes("wasm-agent:native-diagnostics-operation") || !resourceIndexHtml.includes("Verify Android OAuth on real phone") || !resourceIndexHtml.includes("Start Android OAuth verification") || !resourceAppJs.includes("startAndroidOAuthVerification")) {
  fail("Extracted installer preload/PWA assets are missing the Windows Android OAuth diagnostics UI");
}
if (!preloadJs.includes("__wasmAgentDevHmr") || !resourceAppJs.includes("__wasmAgentAppDevHmr")) {
  fail("Preload/PWA bridge layout does not preserve the native read-only bridge plus app-owned HMR bridge");
}
if (!resourceIconPath || fs.statSync(resourceIconPath).size < 1024) fail("Extracted installer resources/icon.ico is missing or unexpectedly small");
if (!resourceHorcRunnerPath || !resourceHorcRunnerJs.includes("horc-local only supports") || !resourceHorcRunnerJs.includes("app-simulator")) {
  fail("Extracted installer resources/horc/horc-local.js is missing or stale");
}
if (!resourceAppSimulatorPath) fail("Extracted installer resources/horc/app-simulator/simulate.js is missing");
if (!resourceAndroidApkPath || fs.statSync(resourceAndroidApkPath).size < 64 * 1024) fail("Extracted installer bundled Android APK is missing or unexpectedly small");
if (!resourceAndroidApkDefaultsPath) fail("Extracted installer bundled Android APK metadata sidecar is missing");

const manifest = {
  app: "WASM Agent",
  target: "win-x64",
  mode: "production",
  buildId: String(nativeDefaults.buildId || ""),
  defaultServerUrl: "https://wa.colmeio.com",
  allowLocalDev: false,
  installerPath,
  installerSha256: sha256(installerPath),
  appAsarSha256: sha256(appAsarPath),
  nativeDefaultsSha256: sha256(nativeDefaultsPath),
  iconSha256: resourceIconPath ? sha256(resourceIconPath) : "",
  horcRunnerSha256: resourceHorcRunnerPath ? sha256(resourceHorcRunnerPath) : "",
  appSimulatorSha256: resourceAppSimulatorPath ? sha256(resourceAppSimulatorPath) : "",
  androidApkSha256: resourceAndroidApkPath ? sha256(resourceAndroidApkPath) : "",
  verifiedAt: new Date().toISOString(),
  forbiddenStringsFound: [],
};
const manifestPath = path.join(releaseRoot, `${path.basename(installerPath, ".exe")}.release-manifest.json`);
fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
fs.writeFileSync(path.join(releaseRoot, "release-manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);
const verifyReport = {
  ok: true,
  schema: "hermes.wasm_agent.windows_release_verify.v1",
  generatedAt: manifest.verifiedAt,
  target: "extracted-nsis-installer",
  installerPath,
  installerSha256: manifest.installerSha256,
  appAsarPath,
  appAsarSha256: manifest.appAsarSha256,
  nativeUrlTarget: nativeDefaults.serverUrl,
  packageVersion: packageJson.version || "",
  buildId: String(nativeDefaults.buildId || ""),
  checks: [
    { name: "final NSIS installer extracted", ok: true, evidence: extractRoot },
    { name: "installed app.asar present", ok: true, evidence: appAsarPath },
    { name: "production URL target", ok: nativeDefaults.serverUrl === "https://wa.colmeio.com", evidence: nativeDefaults.serverUrl },
    { name: "localhost production strings absent", ok: true },
    { name: "patched public/app.js present", ok: true, evidence: path.relative(extractRoot, resourceAppJsPath) },
    { name: "patched dev-hmr.js present", ok: true, evidence: path.relative(extractRoot, resourceDevHmrPath) },
    { name: "early boot fatal trap present", ok: true, evidence: path.relative(extractRoot, resourceBootJsPath) },
    { name: "frontier native commands present", ok: true, evidence: "main.js" },
    { name: "bundled local horc runner present", ok: true, evidence: resourceHorcRunnerPath ? path.relative(extractRoot, resourceHorcRunnerPath) : "" },
    { name: "bundled app simulator present", ok: true, evidence: resourceAppSimulatorPath ? path.relative(extractRoot, resourceAppSimulatorPath) : "" },
    { name: "bundled Android APK present", ok: true, evidence: resourceAndroidApkPath ? `${path.relative(extractRoot, resourceAndroidApkPath)} ${fs.statSync(resourceAndroidApkPath).size} bytes` : "" },
    { name: "icon metadata present", ok: true, evidence: resourceIconPath ? `${path.relative(extractRoot, resourceIconPath)} ${fs.statSync(resourceIconPath).size} bytes` : "" },
    { name: "preload bridge does not conflict with PWA bridge", ok: true, evidence: "__wasmAgentDevHmr + __wasmAgentAppDevHmr" },
  ],
  caveat: "This verifies the final extracted NSIS artifact and app.asar contents. Real installed close/reopen auth lifecycle still requires verify-installed-app.ps1 on Windows.",
};
fs.writeFileSync(path.join(releaseRoot, "VERIFY.json"), `${JSON.stringify(verifyReport, null, 2)}\n`);
console.log(`release manifest: ${manifestPath}`);
console.log(`verify report: ${path.join(releaseRoot, "VERIFY.json")}`);

console.log("Windows installer verification ok");
