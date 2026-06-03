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
  const packageText = files
    .filter((file) => /\.(html|js|css|json)$/i.test(file))
    .map((file) => asar.extractFile(artifact, file.replace(/^\//, "")).toString("utf8"))
    .join("\n");

  assert(mainJs.includes('"remote-pwa"'), `${artifact} must prefer the validated remote PWA entrance`);
  assert(mainJs.includes("validateWasmAgentOrigin") && resolverJs.includes("validateWasmAgentOrigin"), `${artifact} must validate backend identity`);
  assert(!packageText.includes("Google client ID missing"), `${artifact} must not ship the old misleading Google client id literal`);
  assert(!fallbackHtml.includes("googleSignInButton") && !fallbackHtml.includes("authGateGoogleSignInButton") && !fallbackHtml.includes("accounts.google.com"), `${artifact} fallback shell must not contain Google login UI`);
  if (artifact.includes(`${path.sep}win-unpacked${path.sep}`)) {
    assert(mainJs.includes("Promise.all(candidates.map"), `${artifact} must probe backend candidates in parallel for fast first paint`);
    assert(mainJs.includes("clearNativeWebShellCache"), `${artifact} must clear stale service-worker shell caches on startup`);
    assert(resolverJs.includes('"config_json_unavailable"'), `${artifact} must reject backend candidates whose /config.json is unavailable`);
    assert(resolverJs.includes("googleClientIdConfigured") && resolverJs.includes("preference: 0"), `${artifact} must prefer backend candidates configured for Google login`);
    assert(mainJs.includes('url.searchParams.set("native", "electron")'), `${artifact} must load the remote PWA with native=electron`);
    assert(mainJs.includes("installableVersion") && mainJs.includes("buildGeneratedAt"), `${artifact} must expose installable version metadata`);
    assert(mainJs.includes('ipcMain.handle("wasm-agent:native-config", async () => nativeConfigPayload())'), `${artifact} must expose full native/backend config through preload`);
    assert(mainJs.includes("recoverReachableServerUrl") && mainJs.includes("googleClientId"), `${artifact} must recover backend Google login config after startup`);
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
