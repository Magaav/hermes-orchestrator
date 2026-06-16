const assert = require("assert");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const pluginRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(pluginRoot, "..", "..");
const generator = path.join(pluginRoot, "scripts", "generate-native-release-feed.js");
const manifestPath = path.join(pluginRoot, "public", "native", "releases", "latest.json");

const result = spawnSync(process.execPath, [generator], {
  cwd: repoRoot,
  encoding: "utf8",
});

assert.strictEqual(result.status, 0, result.stderr || result.stdout);
assert(fs.existsSync(manifestPath), "native release feed latest.json must be generated");

const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
assert.strictEqual(manifest.app, "wasm-agent");
assert.strictEqual(manifest.channel, "dev");
assert(manifest.artifacts.android.arm64, "arm64 Android APK must be present in feed");
assert(manifest.artifacts.android.universal, "universal Android APK must be present in feed");
assert(manifest.artifacts.runtime.launcher, "downloaded launcher runtime bundle must be present in feed");
assert(manifest.artifacts.hotOps.android.hermesWakeProof, "Hermes wake hot-op bundle must be present in feed");
assert(manifest.artifacts.hotOps.diagnostics.nativeDiagnosticsClassifier, "diagnostics classifier hot-op bundle must be present in feed");

const androidBuildConfigPath = path.join(repoRoot, "native", "android", "app", "build", "generated", "source", "buildConfig", "release", "com", "colmeio", "wasmagent", "BuildConfig.java");
const androidOutputMetadataPath = path.join(repoRoot, "native", "android", "app", "build", "outputs", "apk", "release", "output-metadata.json");
let embeddedAndroidBuildId = "";
if (fs.existsSync(androidBuildConfigPath)) {
  const match = fs.readFileSync(androidBuildConfigPath, "utf8").match(/NATIVE_BUILD_ID\s*=\s*"([^"]+)"/);
  embeddedAndroidBuildId = match ? match[1] : "";
}
let gradleAndroidVersionCode = 0;
if (fs.existsSync(androidOutputMetadataPath)) {
  const outputMetadata = JSON.parse(fs.readFileSync(androidOutputMetadataPath, "utf8"));
  gradleAndroidVersionCode = Number(outputMetadata.elements?.[0]?.versionCode || 0);
}

for (const artifact of [manifest.artifacts.android.arm64, manifest.artifacts.android.universal]) {
  const filePath = path.resolve(artifact.path);
  assert(fs.existsSync(filePath), `artifact path must exist: ${filePath}`);
  const bytes = fs.statSync(filePath).size;
  const hash = crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
  assert.strictEqual(artifact.sizeBytes, bytes, "artifact sizeBytes must match file size");
  assert.strictEqual(artifact.sha256, hash, "artifact sha256 must match file hash");
  assert(artifact.url.startsWith("/native/releases/android/"), "Android release URLs must be served from /native/releases/android/");
  if (embeddedAndroidBuildId) {
    assert.strictEqual(artifact.buildId, embeddedAndroidBuildId, "Android feed buildId must match the APK runtime BuildConfig.NATIVE_BUILD_ID");
    assert(!/-[0-9a-f]{8}$/i.test(artifact.buildId), "Android feed buildId must not be an invented hash/mtime identifier");
  }
  if (gradleAndroidVersionCode) {
    assert.strictEqual(artifact.versionCode, gradleAndroidVersionCode, "Android feed versionCode must match Gradle output metadata");
  }
}

const hermesHotOp = manifest.artifacts.hotOps.android.hermesWakeProof;
assert.strictEqual(hermesHotOp.kind, "windows-hot-op-bundle");
assert.strictEqual(hermesHotOp.operationName, "run_android_hermes_wake_proof");
assert(hermesHotOp.bundleId, "hot-op bundle must expose a bundleId");
assert.match(hermesHotOp.bundleSha, /^[a-f0-9]{64}$/i, "hot-op bundle must expose a bundle SHA");
assert(Array.isArray(hermesHotOp.files) && hermesHotOp.files.length === 2, "hot-op bundle must include module and manifest files");
for (const artifact of hermesHotOp.files) {
  const filePath = path.resolve(artifact.path);
  assert(fs.existsSync(filePath), `hot-op file path must exist: ${filePath}`);
  const hash = crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
  assert.strictEqual(artifact.sha256, hash, "hot-op sha256 must match file hash");
  assert(artifact.url.startsWith("/native/releases/hot-ops/"), "hot-op URLs must be served from /native/releases/hot-ops/");
  assert(!path.isAbsolute(artifact.targetPath), "hot-op targetPath must be relative");
}

const diagnosticsHotOp = manifest.artifacts.hotOps.diagnostics.nativeDiagnosticsClassifier;
assert.strictEqual(diagnosticsHotOp.kind, "windows-hot-op-bundle");
assert.strictEqual(diagnosticsHotOp.operationName, "classify_native_diagnostics");
assert.match(diagnosticsHotOp.bundleSha, /^[a-f0-9]{64}$/i, "diagnostics hot-op bundle must expose a bundle SHA");
assert(Array.isArray(diagnosticsHotOp.files) && diagnosticsHotOp.files.length === 2, "diagnostics hot-op bundle must include module and manifest files");

const runtimeBundle = manifest.artifacts.runtime.launcher;
assert.strictEqual(runtimeBundle.kind, "native-runtime-bundle");
assert.strictEqual(runtimeBundle.platform, "all");
assert.strictEqual(runtimeBundle.updateMode, "downloaded-runtime-atomic");
assert.strictEqual(runtimeBundle.fallback, "last-known-good");
assert(runtimeBundle.bundleId && runtimeBundle.runtimeId === runtimeBundle.bundleId, "runtime bundle must expose stable bundle/runtime ids");
assert.match(runtimeBundle.bundleSha, /^[a-f0-9]{64}$/i, "runtime bundle must expose a bundle SHA");
assert.match(runtimeBundle.manifestSha, /^[a-f0-9]{64}$/i, "runtime bundle must expose a manifest SHA");
assert(Array.isArray(runtimeBundle.files) && runtimeBundle.files.length >= 6, "runtime bundle must publish launcher files");
assert(runtimeBundle.files.some((artifact) => artifact.role === "manifest" && artifact.targetPath === "launcher/runtime-manifest.json"), "runtime bundle must include the trusted manifest");
for (const artifact of runtimeBundle.files) {
  const filePath = path.resolve(artifact.path);
  assert(fs.existsSync(filePath), `runtime file path must exist: ${filePath}`);
  const hash = crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
  assert.strictEqual(artifact.sha256, hash, "runtime sha256 must match file hash");
  assert(artifact.url.startsWith("/native/releases/runtime/"), "runtime URLs must be served from /native/releases/runtime/");
  assert(!path.isAbsolute(artifact.targetPath), "runtime targetPath must be relative");
}

assert(
  manifest.notes.some((note) => /last-known-good fallback/i.test(note)),
  "feed notes must describe runtime/hot-op last-known-good fallback"
);
assert(
  manifest.notes.some((note) => /OS confirmation/i.test(note)),
  "feed notes must not imply silent Android sideload updates"
);
