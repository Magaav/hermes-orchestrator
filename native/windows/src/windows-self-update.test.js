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
  writeResponseBodyToClosedFile,
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
assert.strictEqual(validate({ ...baseFeed, version: "0.1.0", build_id: "win-x64-20260611T010203Z" }, "win-x64-20260610T010203Z").updateAvailable, true);
assert.strictEqual(validate({ ...baseFeed, version: "0.1.0", build_id: "win-x64-20260610T010203Z" }, "win-x64-20260610T010203Z").reason, "same_build");
assert.strictEqual(validate({ ...baseFeed, version: "0.1.0", build_id: "win-x64-20260609T010203Z" }, "win-x64-20260610T010203Z").updateAvailable, false);
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

async function verifyClosedDownloadHandle() {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "wasm-agent-update-close-test-"));
  const target = path.join(tempDir, "closed.exe");
  const originalCreateWriteStream = fs.createWriteStream;
  let writerClosed = false;
  fs.createWriteStream = (...args) => {
    const writer = originalCreateWriteStream(...args);
    writer.once("close", () => { writerClosed = true; });
    return writer;
  };
  try {
    const result = await writeResponseBodyToClosedFile([Buffer.from("installer")], target);
    assert.strictEqual(result.ok, true);
    assert.strictEqual(writerClosed, true, "download helper must not return before the file handle closes");
  } finally {
    fs.createWriteStream = originalCreateWriteStream;
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

async function verifyAtomicConcurrentDownloads() {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "wasm-agent-update-atomic-test-"));
  const target = path.join(tempDir, "atomic.exe");
  const first = Buffer.alloc(2 * 1024 * 1024, 0x31);
  const second = Buffer.alloc(2 * 1024 * 1024, 0x32);
  async function* chunked(data, stride) {
    for (let offset = 0; offset < data.length; offset += stride) {
      await new Promise((resolve) => setImmediate(resolve));
      yield data.subarray(offset, Math.min(offset + stride, data.length));
    }
  }
  try {
    const results = await Promise.all([
      writeResponseBodyToClosedFile(chunked(first, 31_337), target),
      writeResponseBodyToClosedFile(chunked(second, 47_111), target),
    ]);
    assert.strictEqual(results.every((result) => result.ok), true);
    const written = fs.readFileSync(target);
    assert.strictEqual(written.equals(first) || written.equals(second), true, "concurrent staging must publish one complete stream, never mixed bytes");
    assert.deepStrictEqual(fs.readdirSync(tempDir), ["atomic.exe"], "temporary download files must not remain after success");
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

Promise.all([verifyClosedDownloadHandle(), verifyAtomicConcurrentDownloads()])
  .then(() => console.log("windows self update ok"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
