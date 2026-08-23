"use strict";

const assert = require("node:assert");
const crypto = require("node:crypto");
const path = require("node:path");
const { createPackageIntegrity } = require("./package-integrity");

const archivePath = path.join("C:\\Program Files\\WASM Agent", "resources", "app.asar");
const archiveBytes = Buffer.from("raw-asar-archive");
const expectedSha = crypto.createHash("sha256").update(archiveBytes).digest("hex");
const regularFs = {
  existsSync: (value) => value === archivePath,
  readFileSync: () => { throw new Error("virtual asar is a directory"); },
  statSync: () => ({ size: 123 }),
};
const rawFs = {
  existsSync: (value) => value === archivePath,
  readFileSync: (value) => {
    assert.strictEqual(value, archivePath);
    rawFs.readCount += 1;
    return archiveBytes;
  },
  statSync: () => ({ size: archiveBytes.length }),
  readCount: 0,
};

{
  const integrity = createPackageIntegrity({ fs: regularFs, rawFs, rawHashSource: "electron.original-fs", resourcesPath: path.dirname(archivePath) });
  assert.strictEqual(integrity.appAsarPath(), archivePath);
  assert.strictEqual(integrity.sha256File(archivePath), "");
  assert.deepStrictEqual(integrity.appAsarProof(), {
    schema: "hermes.wasm_agent.windows_app_asar_observation.v1",
    ok: true,
    packaged: true,
    app_asar_sha256: expectedSha,
    app_asar_size_bytes: archiveBytes.length,
    app_asar_fingerprint: `app.asar:${expectedSha.slice(0, 16)}`,
    hash_source: "electron.original-fs",
    error: "",
    redacted: true,
  });
  assert.strictEqual(integrity.appAsarFingerprint(), `app.asar:${expectedSha.slice(0, 16)}`);
  assert.deepStrictEqual(integrity.installedPackageProjection({ buildId: "win-x64-test", appVersion: "0.1.0", expectedAppAsarSha256: expectedSha }), {
    schema: "hermes.wasm_agent.windows_installed_package_proof.v1",
    build_id: "win-x64-test",
    app_version: "0.1.0",
    observed: true,
    packaged: true,
    app_asar_sha256: expectedSha,
    app_asar_size_bytes: archiveBytes.length,
    app_asar_fingerprint: `app.asar:${expectedSha.slice(0, 16)}`,
    hash_source: "electron.original-fs",
    expected_app_asar_sha256: expectedSha,
    matches_expected: true,
    error: "",
    redacted: true,
  });
  assert.strictEqual(integrity.installedPackageProjection({ expectedAppAsarSha256: "f".repeat(64) }).matches_expected, false);
  assert.strictEqual(rawFs.readCount, 1, "raw app.asar proof must be memoized per process");
  assert.strictEqual(integrity.statFile(archivePath).size, 123);
}

{
  const missingFs = { existsSync: () => false, readFileSync: () => Buffer.alloc(0), statSync: () => { throw new Error("missing"); } };
  const integrity = createPackageIntegrity({ fs: missingFs, rawFs: missingFs, resourcesPath: "missing" });
  assert.deepStrictEqual(integrity.appAsarProof(), {
    schema: "hermes.wasm_agent.windows_app_asar_observation.v1",
    ok: false,
    packaged: false,
    app_asar_sha256: "",
    app_asar_size_bytes: 0,
    app_asar_fingerprint: "",
    hash_source: "injected.raw-fs",
    error: "app_asar_missing",
    redacted: true,
  });
  assert.strictEqual(integrity.statFile("missing"), null);
}

{
  const integrity = createPackageIntegrity({ fs: regularFs, rawFs: null, resourcesPath: path.dirname(archivePath) });
  const proof = integrity.appAsarProof();
  assert.strictEqual(proof.ok, false);
  assert.strictEqual(proof.hash_source, "unavailable");
  assert.strictEqual(proof.error, "original_fs_unavailable");
}

console.log("package integrity tests passed");
