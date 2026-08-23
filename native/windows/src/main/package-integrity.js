"use strict";

const nodeCrypto = require("node:crypto");
const nodeFs = require("node:fs");
const nodePath = require("node:path");

function electronRawFs() {
  try {
    return { fs: require("original-fs"), source: "electron.original-fs" };
  } catch {
    return { fs: null, source: "unavailable" };
  }
}

function createPackageIntegrity({
  fs = nodeFs,
  rawFs,
  rawHashSource = "",
  crypto = nodeCrypto,
  path = nodePath,
  resourcesPath = process.resourcesPath || "",
} = {}) {
  const raw = rawFs === null
    ? { fs: null, source: "unavailable" }
    : rawFs
      ? { fs: rawFs, source: rawHashSource || "injected.raw-fs" }
      : electronRawFs();
  let cachedAppAsarProof = null;

  function appAsarPath() {
    if (!resourcesPath) return "";
    const candidate = path.join(resourcesPath, "app.asar");
    try {
      return raw.fs?.existsSync(candidate) || fs.existsSync(candidate) ? candidate : "";
    } catch {
      return "";
    }
  }

  function digest(filePath, reader) {
    try {
      return crypto.createHash("sha256").update(reader.readFileSync(filePath)).digest("hex");
    } catch {
      return "";
    }
  }

  function sha256File(filePath) {
    return digest(filePath, fs);
  }

  function statFile(filePath) {
    try {
      return fs.statSync(filePath);
    } catch {
      return null;
    }
  }

  function appAsarProof() {
    if (cachedAppAsarProof) return { ...cachedAppAsarProof };
    const filePath = appAsarPath();
    let error = "";
    let sha256 = "";
    let sizeBytes = 0;
    if (!filePath) error = "app_asar_missing";
    else if (!raw.fs) error = "original_fs_unavailable";
    else {
      sha256 = digest(filePath, raw.fs);
      try {
        sizeBytes = Number(raw.fs.statSync(filePath).size || 0);
      } catch {
        sizeBytes = 0;
      }
      if (!sha256) error = "app_asar_raw_read_failed";
    }
    cachedAppAsarProof = {
      schema: "hermes.wasm_agent.windows_app_asar_observation.v1",
      ok: Boolean(filePath && sha256 && sizeBytes > 0),
      packaged: Boolean(filePath),
      app_asar_sha256: sha256,
      app_asar_size_bytes: sizeBytes,
      app_asar_fingerprint: sha256 ? `app.asar:${sha256.slice(0, 16)}` : "",
      hash_source: raw.source,
      error,
      redacted: true,
    };
    return { ...cachedAppAsarProof };
  }

  function appAsarFingerprint() {
    return appAsarProof().app_asar_fingerprint;
  }

  function installedPackageProjection({ buildId = "", appVersion = "", expectedAppAsarSha256 = "" } = {}) {
    const observation = appAsarProof();
    const expected = String(expectedAppAsarSha256 || "").trim().toLowerCase();
    const matchesExpected = /^[a-f0-9]{64}$/.test(expected)
      ? observation.ok && observation.app_asar_sha256 === expected
      : null;
    return {
      schema: "hermes.wasm_agent.windows_installed_package_proof.v1",
      build_id: String(buildId || ""),
      app_version: String(appVersion || ""),
      observed: observation.ok,
      packaged: observation.packaged,
      app_asar_sha256: observation.app_asar_sha256,
      app_asar_size_bytes: observation.app_asar_size_bytes,
      app_asar_fingerprint: observation.app_asar_fingerprint,
      hash_source: observation.hash_source,
      expected_app_asar_sha256: expected,
      matches_expected: matchesExpected,
      error: observation.error,
      redacted: true,
    };
  }

  return { appAsarFingerprint, appAsarPath, appAsarProof, installedPackageProjection, sha256File, statFile };
}

module.exports = { createPackageIntegrity };
