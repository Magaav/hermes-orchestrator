const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const asar = require("@electron/asar");

const releaseRoot = path.resolve(__dirname, "..", "release");
const artifacts = [
  path.join(releaseRoot, "win-unpacked", "resources", "app.asar"),
  path.join(releaseRoot, "linux-arm64-unpacked", "resources", "app.asar"),
].filter((candidate) => fs.existsSync(candidate));

assert(artifacts.length > 0, "expected at least one unpacked Electron app.asar artifact");

for (const artifact of artifacts) {
  const files = asar.listPackage(artifact);
  assert(files.includes("/main.js"), `${artifact} must include main.js`);
  assert(files.includes("/preload.js"), `${artifact} must include preload.js`);
  assert(files.includes("/native-backend-resolver.js"), `${artifact} must include native-backend-resolver.js`);
  assert(files.includes("/native-shell-policy.js"), `${artifact} must include native-shell-policy.js`);

  const mainJs = asar.extractFile(artifact, "main.js").toString("utf8");
  const preloadJs = asar.extractFile(artifact, "preload.js").toString("utf8");
  const policyJs = asar.extractFile(artifact, "native-shell-policy.js").toString("utf8");
  const resolverJs = asar.extractFile(artifact, "native-backend-resolver.js").toString("utf8");
  const fallbackHtml = files.includes("/fallback.html") ? asar.extractFile(artifact, "fallback.html").toString("utf8") : "";
  const nativeDefaultsEntry = files.includes("/native-defaults.json") ? "native-defaults.json" : files.includes("/build/native-defaults.json") ? "build/native-defaults.json" : "";
  const nativeDefaults = nativeDefaultsEntry ? JSON.parse(asar.extractFile(artifact, nativeDefaultsEntry).toString("utf8")) : {};
  const packageText = files
    .filter((file) => /\.(html|js|css|json)$/i.test(file))
    .map((file) => asar.extractFile(artifact, file.replace(/^\//, "")).toString("utf8"))
    .join("\n");

  assert(mainJs.includes('"remote-pwa"'), `${artifact} must prefer the validated remote PWA entrance`);
  assert(policyJs.includes('DEFAULT_SERVER_URL = "https://wa.colmeio.com"'), `${artifact} must ship the cloud default backend`);
  assert(fallbackHtml.includes("Tested URL:") && fallbackHtml.includes("fetchResult") && fallbackHtml.includes("reason"), `${artifact} fallback shell must show tested URL and failure reason`);
  assert(fallbackHtml.includes("Packaged default:") && fallbackHtml.includes("Build timestamp:") && fallbackHtml.includes("Resolver candidates:") && fallbackHtml.includes("App package:") && fallbackHtml.includes("Saved config source:"), `${artifact} fallback shell must expose build stamp, saved config source, and resolver diagnostics`);
  assert(fallbackHtml.includes("native-defaults.json serverUrl:") && fallbackHtml.includes("Saved config raw JSON:") && fallbackHtml.includes("Env WASM_AGENT_ALLOW_LOCAL_DEV:") && fallbackHtml.includes("Selected/tested source:"), `${artifact} fallback shell must print native defaults, raw saved config, env, and candidate source diagnostics`);
  assert(fallbackHtml.includes("fallbackInputDefault") && fallbackHtml.includes("isLocalDevUrl") && fallbackHtml.includes("https://wa.colmeio.com/config.json"), `${artifact} fallback shell must independently refuse localhost defaults in production`);
  assert.strictEqual(nativeDefaults.serverUrl, "https://wa.colmeio.com", `${artifact} packaged defaults must use the cloud backend`);
  assert.deepStrictEqual(nativeDefaults.serverUrlCandidates, ["https://wa.colmeio.com"], `${artifact} production packaged defaults must not include localhost/LAN candidates`);
  assert.strictEqual(nativeDefaults.mode, "production", `${artifact} packaged defaults must identify production mode`);
  assert.strictEqual(nativeDefaults.allowLocalDev, false, `${artifact} packaged defaults must disable local-dev candidates`);
  assert(!packageText.includes("127.0.0.1:8877") && !packageText.includes("localhost:8877"), `${artifact} production app.asar must not contain exact localhost backend defaults`);
  assert(!packageText.includes("WASM Agent native build loading") && !packageText.includes("No backend with an available /config.json"), `${artifact} production app.asar must not contain stale fallback copy`);
  assert(mainJs.includes("validateWasmAgentOrigin") && resolverJs.includes("validateWasmAgentOrigin"), `${artifact} must validate backend identity`);
  assert(!packageText.includes("Google client ID missing"), `${artifact} must not ship the old misleading Google client id literal`);
  assert(!fallbackHtml.includes("googleSignInButton") && !fallbackHtml.includes("authGateGoogleSignInButton") && !fallbackHtml.includes("accounts.google.com"), `${artifact} fallback shell must not contain Google login UI`);
  if (artifact.includes(`${path.sep}win-unpacked${path.sep}`)) {
    assert(mainJs.includes("Promise.all(candidates.map"), `${artifact} must probe backend candidates in parallel for fast first paint`);
    assert(mainJs.includes("clearNativeWebShellCache"), `${artifact} must clear stale service-worker shell caches on startup`);
    assert(mainJs.includes("nativeAuthCookieStatus") && mainJs.includes("cookies.flushStore") && mainJs.includes("wasm-agent:native-flush-auth-cookies"), `${artifact} must expose native auth cookie status and flush persistent cookies after login`);
    assert(mainJs.includes("function readJsonFile"), `${artifact} must keep native diagnostics upload working when reading runtime diagnostics`);
    assert(resolverJs.includes('"config_json_unavailable"'), `${artifact} must reject backend candidates whose /config.json is unavailable`);
    assert(resolverJs.includes("googleClientIdConfigured") && resolverJs.includes("preference: 0"), `${artifact} must prefer backend candidates configured for Google login`);
    assert(mainJs.includes('url.searchParams.set("native", "electron")'), `${artifact} must load the remote PWA with native=electron`);
    assert(mainJs.includes('if (isGoogleAuthUrl(url)) return { action: "allow" };') && mainJs.includes("win.loadURL(url)") && mainJs.includes("Could not route auth popup in main window"), `${artifact} must keep Google popups out of the primary native window while routing same-origin auth completions back into it`);
    assert(mainJs.includes("installableVersion") && mainJs.includes("buildGeneratedAt"), `${artifact} must expose installable version metadata`);
    assert(mainJs.includes('ipcMain.handle("wasm-agent:native-config", async () => nativeConfigPayload())'), `${artifact} must expose full native/backend config through preload`);
    assert(mainJs.includes("recoverReachableServerUrl") && mainJs.includes("googleClientId"), `${artifact} must recover backend Google login config after startup`);
    assert(mainJs.includes("migrateLegacyNativeConfig") && mainJs.includes("legacy-local-config-migrated") && mainJs.includes("userExplicit"), `${artifact} must migrate stale auto-saved localhost config unless explicitly user-saved`);
    assert(mainJs.includes("appAsarFingerprint") && mainJs.includes("packagedDefaultServerUrl"), `${artifact} must expose build/package diagnostics to fallback`);
    assert(mainJs.includes("WASM_AGENT_ALLOW_LOCAL_DEV") && mainJs.includes("allowLocalDevCandidates") && mainJs.includes("discarded local dev backend in production") && mainJs.includes("candidateSourceEntries"), `${artifact} must gate localhost candidates behind WASM_AGENT_ALLOW_LOCAL_DEV and trace candidate sources`);
    assert(mainJs.includes("startupDiagnostics.savedConfigRawJson"), `${artifact} must preserve pre-migration raw saved config for fallback diagnostics`);
  }
  assert(mainJs.includes("payloadIdentifiesWrongApp"), `${artifact} must reject wrong app identity`);
  assert(mainJs.includes("setUserAgent"), `${artifact} must set a browser-like user agent`);
  assert(mainJs.includes("wasm-agent:native-dev-hmr-reload"), `${artifact} must expose native HMR reload`);
  assert(preloadJs.includes("__wasmAgentDevHmr"), `${artifact} preload must expose the HMR bridge`);
  assert(policyJs.includes("GOOGLE_AUTH_ORIGINS"), `${artifact} policy must allow Google auth origins in-session`);
  assert(policyJs.includes("chromeLikeUserAgent"), `${artifact} policy must strip Electron user agent markers`);
  assert(policyJs.includes('PWA_HOME_PATH = "/home"'), `${artifact} policy must route to PWA /home`);
}

console.log(`native shell artifact ok (${artifacts.length})`);
