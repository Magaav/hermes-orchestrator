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

const temporaryRoots = [];
function registerTemporaryRoot(root) {
  temporaryRoots.push(root);
  return root;
}

function cleanupTemporaryRoots() {
  for (const root of temporaryRoots.splice(0)) {
    try {
      fs.rmSync(root, { recursive: true, force: true });
    } catch (error) {
      console.error(`Failed to remove verifier temporary directory ${root}: ${error.message}`);
    }
  }
}

process.once("exit", cleanupTemporaryRoots);
for (const [signal, exitCode] of [["SIGINT", 130], ["SIGTERM", 143]]) {
  process.once(signal, () => {
    cleanupTemporaryRoots();
    process.exit(exitCode);
  });
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
const installerSizeBytes = fs.statSync(installerPath).size;
const sevenZip = sevenZipPath();
if (!sevenZip) fail("Missing 7zip-bin executable for this platform");

const extractRoot = registerTemporaryRoot(fs.mkdtempSync(path.join(os.tmpdir(), "wasm-agent-installer-")));
const asarRoot = registerTemporaryRoot(fs.mkdtempSync(path.join(os.tmpdir(), "wasm-agent-asar-")));
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
const resourceIconPath = findFile(path.dirname(appAsarPath), "icon.ico");
const resourceSupervisorPath = findFile(path.dirname(appAsarPath), "wasm-agent-launcher.exe");
const resourceHorcRunnerPath = findFile(path.dirname(appAsarPath), "horc/horc-local.js");
const resourceAppSimulatorPath = findFile(path.dirname(appAsarPath), "horc/app-simulator/simulate.js");
const resourceAndroidApkPath = findFile(path.dirname(appAsarPath), "android/WASM-Agent-arm64.apk");
const packagedOldInstallers = walkFiles(path.dirname(appAsarPath)).filter((filePath) => /[\\/]public[\\/]native[\\/]releases[\\/]windows[\\/].*\.(exe|blockmap)$/i.test(filePath));
const mainJsPath = path.join(asarRoot, "main.js");
const preloadJsPath = path.join(asarRoot, "preload.js");
const supervisorClientPath = path.join(asarRoot, "main", "supervisor-client.js");
const dispatcherHealthPath = path.join(asarRoot, "main", "dispatcher-health.js");
const sourceDispatcherHealthPath = path.join(srcRoot, "main", "dispatcher-health.js");
const observabilityKernelPath = path.join(asarRoot, "main", "observability-kernel.js");
const audioStimulusPath = path.join(asarRoot, "main", "audio-stimulus.js");
const automaticUpdatesPath = path.join(asarRoot, "main", "automatic-updates.js");
const appLifecyclePath = path.join(asarRoot, "main", "app-lifecycle.js");
const packageIntegrityPath = path.join(asarRoot, "main", "package-integrity.js");
const nativeSessionProofPath = path.join(asarRoot, "main", "native-session-proof.js");
const fullPowerExecutorPath = path.join(asarRoot, "main", "full-power-executor.js");
const companionOverlayPath = path.join(asarRoot, "main", "companion-overlay.js");
const companionStartupPath = path.join(asarRoot, "main", "companion-startup.js");
const windowsNativeCommandsPath = path.join(asarRoot, "main", "windows-native-commands.js");
const windowsDesktopControlPath = path.join(asarRoot, "main", "windows-desktop-control.js");
const windowsDesktopUiaPath = path.join(asarRoot, "main", "windows-desktop", "uia-control.js");
const packagedTestFiles = walkFiles(asarRoot).filter((filePath) => /(?:^|[\\/])[^\\/]+\.test\.(?:js|mjs|cjs)$/i.test(filePath));
const nativeCapabilitiesPath = path.join(asarRoot, "main", "native-capabilities.js");
const sourcePreloadJsPath = path.join(srcRoot, "preload.js");
const sourcePackageIntegrityPath = path.join(srcRoot, "main", "package-integrity.js");
const sourceNativeSessionProofPath = path.join(srcRoot, "main", "native-session-proof.js");
const sourceFullPowerExecutorPath = path.join(srcRoot, "main", "full-power-executor.js");
const sourceCompanionOverlayPath = path.join(srcRoot, "main", "companion-overlay.js");
const sourceCompanionStartupPath = path.join(srcRoot, "main", "companion-startup.js");
const sourceWindowsNativeCommandsPath = path.join(srcRoot, "main", "windows-native-commands.js");
const sourceWindowsDesktopControlPath = path.join(srcRoot, "main", "windows-desktop-control.js");
const sourceWindowsDesktopUiaPath = path.join(srcRoot, "main", "windows-desktop", "uia-control.js");
const sourceNativeCapabilitiesPath = path.join(srcRoot, "main", "native-capabilities.js");
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
if (!String(nativeDefaults.googleClientId || "").trim()) fail("app.asar native-defaults.json is missing the production Google login client ID");
if (resourceDefaults.googleClientId !== nativeDefaults.googleClientId) fail("resources/native-defaults.json Google login client ID does not match app.asar");
if (sourceDefaults.buildId && nativeDefaults.buildId !== sourceDefaults.buildId) {
  fail(`app.asar native-defaults.json buildId (${nativeDefaults.buildId || ""}) does not match freshly generated source buildId (${sourceDefaults.buildId})`);
}
if (sourceDefaults.buildId && resourceDefaults.buildId !== sourceDefaults.buildId) {
  fail(`resources/native-defaults.json buildId (${resourceDefaults.buildId || ""}) does not match freshly generated source buildId (${sourceDefaults.buildId})`);
}
if (!fallbackHtml.includes('value="https://wa.colmeio.com"')) fail("fallback.html default input is not https://wa.colmeio.com");
if (!asarText.includes("wa.colmeio.com") || !payloadText.includes("wa.colmeio.com")) fail("Installer does not contain wa.colmeio.com");
if (fs.existsSync(resourcePublicRoot)) fail("Cloud-only Windows installer must not bundle the PWA public tree or on-demand models");
if (resourceAndroidApkPath) fail("Cloud-only Windows installer must download Android APKs on demand instead of bundling them");
if (packagedTestFiles.length) fail(`Production app.asar contains test files: ${packagedTestFiles.map((item) => path.relative(asarRoot, item)).join(", ")}`);
if (!mainJs.includes("frontier_operator_commands_ready") || !mainJs.includes("collectNativeDiagnosticsBundle") || !mainJs.includes("captureNativeScreenshot") || !mainJs.includes("controlledNativeReload")) {
  fail("Extracted installer app.asar main.js is missing Frontier operator capabilities");
}
if (!mainJs.includes("WINDOWS_ANDROID_OAUTH_OPERATIONS") || !mainJs.includes("verify_android_oauth") || !mainJs.includes("read_latest_android_report") || !mainJs.includes("operation_not_allowlisted") || !mainJs.includes("horc simulate android --device --interactive-oauth")) {
  fail("Extracted installer app.asar main.js is missing the Windows Android OAuth diagnostics bridge");
}
if (!mainJs.includes("run_android_voice_tuning_goal_loop") || !mainJs.includes("screencap") || !mainJs.includes("uiautomator_dump") || !mainJs.includes("native-diagnostics/latest.json") || !mainJs.includes("permission_prompt_auto_clicked: false")) {
  fail("Extracted installer app.asar main.js is missing the guarded Android Hermes Wake goal loop");
}
if (!mainJs.includes("resolveLocalHorcRunner") || !mainJs.includes("bundledHorcRunnerPath") || !mainJs.includes("ELECTRON_RUN_AS_NODE") || !mainJs.includes("WASM_AGENT_SIM_ROOT_DIR") || !mainJs.includes("WASM_AGENT_ANDROID_APK")) {
  fail("Extracted installer app.asar main.js is missing deterministic bundled horc runner resolution");
}
if (!preloadJs.includes("nativeDiagnostics") || !preloadJs.includes("wasm-agent:native-diagnostics-operation")) fail("Extracted installer preload is missing the native diagnostics bridge");
if (!preloadJs.includes("__wasmAgentDevHmr")) fail("Extracted installer preload is missing the native HMR bridge");
if (!preloadJs.includes("wasm-agent:companion-window") || !preloadJs.includes("wasm-agent:companion-window-move")) fail("Extracted installer preload is missing the companion-window bridge");
if (sha256(preloadJsPath) !== sha256(sourcePreloadJsPath)) fail("Extracted installer preload does not match the release input");
if (!resourceIconPath || fs.statSync(resourceIconPath).size < 1024) fail("Extracted installer resources/icon.ico is missing or unexpectedly small");
if (!resourceSupervisorPath || fs.statSync(resourceSupervisorPath).size < 100000) fail("Extracted installer resources/wasm-agent-launcher.exe is missing or unexpectedly small");
if (!fs.readFileSync(resourceSupervisorPath).includes(Buffer.from("dispatcher.recover"))) fail("Extracted Windows supervisor lacks dispatcher.recover");
if (!fs.existsSync(supervisorClientPath) || !fs.readFileSync(supervisorClientPath, "utf8").includes("update.activate")) fail("Extracted app.asar is missing the Windows supervisor client contract");
const supervisorClientJs = fs.readFileSync(supervisorClientPath, "utf8");
if (!supervisorClientJs.includes('["/S", "/currentuser"]')) fail("Extracted app.asar is missing silent per-user fallback update activation");
if (!fs.existsSync(dispatcherHealthPath) || !fs.readFileSync(dispatcherHealthPath, "utf8").includes("windows_dispatcher_lease.v1")) fail("Extracted app.asar is missing the dispatcher recovery lease contract");
if (sha256(dispatcherHealthPath) !== sha256(sourceDispatcherHealthPath)) fail("Extracted dispatcher recovery lease module does not match the release input");
if (!fs.existsSync(observabilityKernelPath)) fail("Extracted app.asar is missing the observability kernel");
if (!fs.existsSync(audioStimulusPath)) fail("Extracted app.asar is missing the Windows audio stimulus module");
const audioStimulusJs = fs.readFileSync(audioStimulusPath, "utf8");
if (!audioStimulusJs.includes("voice_inventory") || !audioStimulusJs.includes("SelectVoice")) {
  fail("Extracted app.asar audio stimulus module is missing voice inventory or selection");
}
const observabilityKernelJs = fs.readFileSync(observabilityKernelPath, "utf8");
const nativeCapabilitiesJs = fs.readFileSync(nativeCapabilitiesPath, "utf8");
if (
  !mainJs.includes("observabilityKernel.execute")
  || !["observability_enable", "observability_collect", "observability_status", "observability_disable"].every(
    (operation) => nativeCapabilitiesJs.includes(operation) && observabilityKernelJs.includes(operation)
  )
) {
  fail("Extracted app.asar is missing the bounded observability command contract");
}
if (!fs.readFileSync(nativeCapabilitiesPath, "utf8").includes("observabilityLease") || !observabilityKernelJs.includes("public_debug_port: false")) {
  fail("Extracted app.asar does not advertise a private on-demand observability lease");
}
if (!fs.existsSync(automaticUpdatesPath) || !mainJs.includes("startAutomaticUpdateLoop")) {
  fail("Extracted app.asar is missing the automatic update policy");
}
if (!fs.existsSync(appLifecyclePath)) fail("Extracted app.asar is missing the main-process lifecycle guard");
if (!fs.existsSync(packageIntegrityPath) || !fs.readFileSync(packageIntegrityPath, "utf8").includes('require("original-fs")')) {
  fail("Extracted app.asar is missing raw installed app.asar integrity support");
}
if (!fs.existsSync(nativeSessionProofPath) || !fs.readFileSync(nativeSessionProofPath, "utf8").includes("safeCookieSessionSummary")) {
  fail("Extracted app.asar is missing the redacted native cookie-session proof projection");
}
if (sha256(packageIntegrityPath) !== sha256(sourcePackageIntegrityPath) || sha256(nativeSessionProofPath) !== sha256(sourceNativeSessionProofPath)) {
  fail("Extracted app.asar installed-proof modules do not match the release inputs");
}
if (
  !fs.existsSync(fullPowerExecutorPath)
  || sha256(fullPowerExecutorPath) !== sha256(sourceFullPowerExecutorPath)
  || !mainJs.includes("windows_shell_execute_unrestricted")
  || !mainJs.includes("fullPowerExecutor.execute")
  || !nativeCapabilitiesJs.includes("windows.shell.execute.unrestricted")
  || !fs.readFileSync(fullPowerExecutorPath, "utf8").includes("hermes.wasm_agent.windows_full_power_execution.v1")
) {
  fail("Extracted app.asar is missing the unrestricted Windows-user execution contract");
}
if (
  !fs.existsSync(companionOverlayPath)
  || !fs.existsSync(companionStartupPath)
  || !fs.existsSync(windowsNativeCommandsPath)
  || !fs.existsSync(windowsDesktopControlPath)
  || !fs.existsSync(windowsDesktopUiaPath)
  || sha256(companionOverlayPath) !== sha256(sourceCompanionOverlayPath)
  || sha256(companionStartupPath) !== sha256(sourceCompanionStartupPath)
  || sha256(windowsNativeCommandsPath) !== sha256(sourceWindowsNativeCommandsPath)
  || sha256(windowsDesktopControlPath) !== sha256(sourceWindowsDesktopControlPath)
  || sha256(windowsDesktopUiaPath) !== sha256(sourceWindowsDesktopUiaPath)
  || sha256(nativeCapabilitiesPath) !== sha256(sourceNativeCapabilitiesPath)
  || !mainJs.includes("windowsNativeCommands.execute")
) {
  fail("Extracted app.asar is missing the source-matched companion or Windows desktop automation contract");
}
const companionOverlayJs = fs.readFileSync(companionOverlayPath, "utf8");
const companionStartupJs = fs.readFileSync(companionStartupPath, "utf8");
const windowsNativeCommandsJs = fs.readFileSync(windowsNativeCommandsPath, "utf8");
const windowsDesktopUiaJs = fs.readFileSync(windowsDesktopUiaPath, "utf8");
if (
  !companionOverlayJs.includes("hermes.wasm_agent.companion_overlay.v2")
  || !companionOverlayJs.includes("pwa.agent-avatar-token")
  || !companionStartupJs.includes("authSessionStatus")
  || !["show_companion_overlay", "run_notepad_uia_canary", "windows_desktop_describe", "windows_desktop_inspect", "windows_desktop_act", "windows_desktop_prove"].every((operation) => windowsNativeCommandsJs.includes(operation) || nativeCapabilitiesJs.includes(operation.replaceAll("_", ".")))
  || !windowsDesktopUiaJs.includes("hermes.wasm_agent.windows_desktop_automation.v1")
  || !windowsDesktopUiaJs.includes("current_user_token")
  || !windowsDesktopUiaJs.includes("separate_signed_broker_required")
  || !["windows.desktop.describe", "windows.desktop.inspect", "windows.desktop.act", "windows.desktop.prove"].every((capability) => nativeCapabilitiesJs.includes(capability))
) {
  fail("Extracted app.asar companion ownership, auth bootstrap, UIA proof, or authority boundary is incomplete");
}
const packagedIntegrity = require(packageIntegrityPath).createPackageIntegrity({
  fs,
  rawFs: fs,
  rawHashSource: "verifier.node-fs",
  resourcesPath: path.dirname(appAsarPath),
});
const packagedAsarProof = packagedIntegrity.appAsarProof();
if (
  packagedAsarProof.schema !== "hermes.wasm_agent.windows_app_asar_observation.v1"
  || packagedAsarProof.ok !== true
  || packagedAsarProof.packaged !== true
  || packagedAsarProof.app_asar_sha256 !== sha256(appAsarPath)
  || packagedAsarProof.app_asar_size_bytes !== fs.statSync(appAsarPath).size
) {
  fail("Extracted app.asar installed package proof module disagrees with independent verifier evidence");
}
if (!mainJs.includes("activateOrLaunchInstaller")) fail("Extracted app.asar main.js does not delegate installer activation to the supervisor client");
if (!resourceHorcRunnerPath || !resourceHorcRunnerJs.includes("horc-local only supports") || !resourceHorcRunnerJs.includes("app-simulator")) {
  fail("Extracted installer resources/horc/horc-local.js is missing or stale");
}
if (!resourceAppSimulatorPath) fail("Extracted installer resources/horc/app-simulator/simulate.js is missing");
if (packagedOldInstallers.length) fail(`Extracted installer still bundles old Windows release artifacts: ${packagedOldInstallers.map((item) => path.relative(path.dirname(appAsarPath), item)).join(", ")}`);
if (!mainJs.includes("latestAndroidReleaseFeed") || !mainJs.includes("downloadAndroidVoiceTuningApk") || !mainJs.includes("release_feed")) {
  fail("Extracted installer app.asar main.js is missing Android APK release-feed download support");
}

const manifest = {
  app: "WASM Agent",
  target: "win-x64",
  mode: "production",
  buildId: String(nativeDefaults.buildId || ""),
  defaultServerUrl: "https://wa.colmeio.com",
  allowLocalDev: false,
  installerPath,
  installerSha256: sha256(installerPath),
  installerSizeBytes,
  appAsarSha256: sha256(appAsarPath),
  nativeDefaultsSha256: sha256(nativeDefaultsPath),
  iconSha256: resourceIconPath ? sha256(resourceIconPath) : "",
  supervisorSha256: resourceSupervisorPath ? sha256(resourceSupervisorPath) : "",
  horcRunnerSha256: resourceHorcRunnerPath ? sha256(resourceHorcRunnerPath) : "",
  appSimulatorSha256: resourceAppSimulatorPath ? sha256(resourceAppSimulatorPath) : "",
  androidApkSha256: resourceAndroidApkPath ? sha256(resourceAndroidApkPath) : "",
  androidApkBundled: Boolean(resourceAndroidApkPath),
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
  appAsarPath: "resources/app.asar (inside verified installer)",
  appAsarSha256: manifest.appAsarSha256,
  nativeUrlTarget: nativeDefaults.serverUrl,
  packageVersion: packageJson.version || "",
  buildId: String(nativeDefaults.buildId || ""),
  checks: [
    { name: "final NSIS installer extracted", ok: true, evidence: "temporary extraction removed after verification" },
    { name: "compressed installer size recorded", ok: true, evidence: `${installerSizeBytes} bytes` },
    { name: "installed app.asar present", ok: true, evidence: "resources/app.asar inside verified installer" },
    { name: "production URL target", ok: nativeDefaults.serverUrl === "https://wa.colmeio.com", evidence: nativeDefaults.serverUrl },
    { name: "production Google login client configured", ok: true, evidence: "matching app.asar and resources native defaults" },
    { name: "localhost production strings absent", ok: true },
    { name: "cloud PWA and on-demand models excluded", ok: true, evidence: "resources/public absent" },
    { name: "source tests excluded", ok: true, evidence: "no *.test.js/mjs/cjs files in app.asar" },
    { name: "frontier native commands present", ok: true, evidence: "main.js" },
    { name: "bundled local horc runner present", ok: true, evidence: resourceHorcRunnerPath ? path.relative(extractRoot, resourceHorcRunnerPath) : "" },
    { name: "bundled app simulator present", ok: true, evidence: resourceAppSimulatorPath ? path.relative(extractRoot, resourceAppSimulatorPath) : "" },
    { name: "Android APK excluded and release-feed download support present", ok: true, evidence: "resources/android APK absent; main.js release-feed path verified" },
    { name: "old Windows installers excluded from resources", ok: true, evidence: "public/native/releases/windows excluded" },
    { name: "icon metadata present", ok: true, evidence: resourceIconPath ? `${path.relative(extractRoot, resourceIconPath)} ${fs.statSync(resourceIconPath).size} bytes` : "" },
    { name: "Windows supervisor executable present", ok: true, evidence: resourceSupervisorPath ? `${path.relative(extractRoot, resourceSupervisorPath)} ${fs.statSync(resourceSupervisorPath).size} bytes; dispatcher.recover lease verified` : "" },
    { name: "Electron update activation delegates to supervisor", ok: true, evidence: "main/supervisor-client.js" },
    { name: "on-demand observability lease packaged", ok: true, evidence: "main/observability-kernel.js; no public debug port" },
    { name: "Windows selectable-voice audio module packaged", ok: true, evidence: "main/audio-stimulus.js" },
    { name: "automatic update policy packaged", ok: true, evidence: "login supervisor + startup/six-hour verified update loop" },
    { name: "main-process lifecycle guard packaged", ok: true, evidence: "main/app-lifecycle.js" },
    { name: "installed package and session proof modules packaged", ok: true, evidence: "raw app.asar SHA via original-fs; redacted durable-cookie summary" },
    { name: "source-matched companion token shell packaged", ok: true, evidence: "PWA-owned avatar token; auth bootstrap; transparent compact/expanded native bounds" },
    { name: "source-matched Windows desktop inspect-act-prove packaged", ok: true, evidence: "bounded UIA snapshots; revision-bound refs; independent scalar postconditions; current-user token boundary" },
    { name: "native preload bridge present", ok: true, evidence: "nativeDiagnostics + __wasmAgentDevHmr + companion-window" },
  ],
  caveat: "This verifies the final extracted NSIS artifact and app.asar contents. Real installed close/reopen auth lifecycle still requires verify-installed-app.ps1 on Windows.",
};
fs.writeFileSync(path.join(releaseRoot, "VERIFY.json"), `${JSON.stringify(verifyReport, null, 2)}\n`);
console.log(`release manifest: ${manifestPath}`);
console.log(`verify report: ${path.join(releaseRoot, "VERIFY.json")}`);

console.log("Windows installer verification ok");
