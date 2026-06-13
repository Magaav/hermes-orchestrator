const assert = require("node:assert");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {
  compareBuildIds,
  isAllowlistedReleaseUrl,
  validateDownloadedInstaller,
  validateReleaseArtifact,
  windowsArtifactFromFeed,
} = require("./windows-self-update");

const serverUrl = "https://wa.colmeio.com";
const baseFeed = {
  platform: "win-x64",
  build_id: "win-x64-20260610T010203Z",
  version: "0.1.0",
  installer_url: "/native/releases/windows/WASM-Agent-Setup-x64-0.1.0-20260610T010203Z.exe",
  sha256: "a".repeat(64),
  size_bytes: 100 * 1024 * 1024,
  created_at: "2026-06-10T01:02:03Z",
  production_target: serverUrl,
};

function validate(feed, currentBuildId = "win-x64-20260609T010203Z") {
  return validateReleaseArtifact(feed, { serverUrl, currentBuildId, productionTarget: serverUrl });
}

assert.strictEqual(compareBuildIds("win-x64-20260609T010203Z", "win-x64-20260610T010203Z"), 1);
assert.strictEqual(compareBuildIds("win-x64-20260610T010203Z", "win-x64-20260610T010203Z"), 0);
assert.strictEqual(compareBuildIds("win-x64-20260611T010203Z", "win-x64-20260610T010203Z"), -1);

assert.strictEqual(windowsArtifactFromFeed(baseFeed).platform, "win-x64");
assert.strictEqual(validate(baseFeed).ok, true);
assert.strictEqual(validate(baseFeed).updateAvailable, true);
assert.strictEqual(validate(baseFeed, baseFeed.build_id).updateAvailable, false);
assert.strictEqual(validate({ ...baseFeed, build_id: "win-x64-20260608T010203Z" }).reason, "older_build_ignored");
assert.strictEqual(validate({ ...baseFeed, platform: "linux-x64" }).error, "wrong_platform");
assert.strictEqual(validate({ ...baseFeed, sha256: "" }).error, "missing_hash");
assert.strictEqual(validate({ ...baseFeed, installer_url: "https://evil.example/native/releases/windows/WASM-Agent.exe" }).error, "unallowlisted_url");
assert.strictEqual(validate({ ...baseFeed, installer_url: "https://wa.colmeio.com/downloads/WASM-Agent.exe" }).error, "unallowlisted_url_path");
assert.strictEqual(validate({ ...baseFeed, installer_url: "https://wa.colmeio.com/native/releases/windows/not-an-msi.msi" }).error, "unallowlisted_url_path");
assert.strictEqual(validate({ ...baseFeed, size_bytes: 1024 }).error, "suspicious_artifact_size");
assert.strictEqual(validate({ ...baseFeed, production_target: "https://staging.example.test" }).error, "production_target_mismatch");
assert.strictEqual(isAllowlistedReleaseUrl("/native/releases/windows/WASM-Agent-Setup.exe", serverUrl).ok, true);

const nested = {
  production_target: serverUrl,
  artifacts: {
    windows: {
      x64: {
        platform: "windows",
        arch: "x64",
        kind: "windows-installer",
        buildId: "win-x64-20260610T010203Z",
        url: "/native/releases/windows/WASM-Agent-Setup-x64.exe",
        sha256: "b".repeat(64),
        sizeBytes: 100 * 1024 * 1024,
      },
    },
  },
};
assert.strictEqual(validate(nested).ok, true);
assert.strictEqual(validate(nested).artifact.platform, "win-x64");

const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "wasm-agent-update-test-"));
try {
  const artifactPath = path.join(tempDir, "WASM-Agent-Setup.exe");
  const data = Buffer.alloc(51 * 1024 * 1024, 7);
  fs.writeFileSync(artifactPath, data);
  const sha256 = crypto.createHash("sha256").update(data).digest("hex");
  assert.strictEqual(validateDownloadedInstaller(artifactPath, { sha256, sizeBytes: data.length }).ok, true);
  assert.strictEqual(validateDownloadedInstaller(artifactPath, { sha256: "c".repeat(64), sizeBytes: data.length }).error, "hash_mismatch");
  assert.strictEqual(validateDownloadedInstaller(artifactPath, {}).error, "missing_hash");
  const tinyPath = path.join(tempDir, "tiny.exe");
  fs.writeFileSync(tinyPath, "stub");
  assert.strictEqual(validateDownloadedInstaller(tinyPath, { sha256: crypto.createHash("sha256").update("stub").digest("hex") }).error, "suspicious_artifact_size");
} finally {
  fs.rmSync(tempDir, { recursive: true, force: true });
}

console.log("windows self update ok");
