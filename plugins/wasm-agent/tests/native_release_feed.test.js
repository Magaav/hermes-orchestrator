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

for (const artifact of [manifest.artifacts.android.arm64, manifest.artifacts.android.universal]) {
  const filePath = path.resolve(artifact.path);
  assert(fs.existsSync(filePath), `artifact path must exist: ${filePath}`);
  const bytes = fs.statSync(filePath).size;
  const hash = crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
  assert.strictEqual(artifact.sizeBytes, bytes, "artifact sizeBytes must match file size");
  assert.strictEqual(artifact.sha256, hash, "artifact sha256 must match file hash");
  assert(artifact.url.startsWith("/native/releases/android/"), "Android release URLs must be served from /native/releases/android/");
}

assert(
  manifest.notes.some((note) => /OS confirmation/i.test(note)),
  "feed notes must not imply silent Android sideload updates"
);
