const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const PLATFORM = "win-x64";
const FEED_PATH = "/native/releases/latest.json";
const MIN_WINDOWS_INSTALLER_SIZE_BYTES = 50 * 1024 * 1024;

function normalizeUrl(value, baseUrl) {
  try {
    return new URL(String(value || ""), baseUrl).toString();
  } catch {
    return "";
  }
}

function normalizeSha256(value) {
  const text = String(value || "").trim().toLowerCase();
  return /^[a-f0-9]{64}$/.test(text) ? text : "";
}

function buildRank(value) {
  const text = String(value || "").trim();
  const match = text.match(/^win-x64-(\d{8}T\d{6}Z)$/i);
  if (match) return match[1];
  return text;
}

function compareBuildIds(currentBuildId, latestBuildId) {
  const current = buildRank(currentBuildId);
  const latest = buildRank(latestBuildId);
  if (!latest || latest === current) return 0;
  if (!current) return 1;
  return latest > current ? 1 : -1;
}

function feedUrlFor(serverUrl) {
  return normalizeUrl(FEED_PATH, serverUrl);
}

function allowedReleaseOrigins(serverUrl, extraOrigins = []) {
  const origins = new Set();
  [serverUrl, ...extraOrigins].forEach((value) => {
    try {
      const url = new URL(String(value || ""));
      if (url.protocol === "https:" || url.protocol === "http:") origins.add(url.origin.toLowerCase());
    } catch {
      // Ignore malformed origins.
    }
  });
  return origins;
}

function isAllowlistedReleaseUrl(value, serverUrl, extraOrigins = []) {
  const absolute = normalizeUrl(value, serverUrl);
  if (!absolute) return { ok: false, error: "invalid_url" };
  const url = new URL(absolute);
  if (!["https:", "http:"].includes(url.protocol)) return { ok: false, error: "invalid_url_protocol", url: absolute };
  if (!allowedReleaseOrigins(serverUrl, extraOrigins).has(url.origin.toLowerCase())) {
    return { ok: false, error: "unallowlisted_url", url: absolute };
  }
  if (!/^\/native\/releases\/windows\/[^/]+\.exe$/i.test(url.pathname)) {
    return { ok: false, error: "unallowlisted_url_path", url: absolute };
  }
  return { ok: true, url: absolute };
}

function windowsArtifactFromFeed(feed = {}) {
  const flatPlatform = String(feed.platform || "").trim();
  if (flatPlatform === PLATFORM) {
    return {
      platform: flatPlatform,
      buildId: feed.build_id || feed.buildId,
      version: feed.version,
      url: feed.installer_url || feed.artifact_url || feed.installerUrl || feed.artifactUrl,
      sha256: feed.sha256,
      sizeBytes: feed.size_bytes || feed.sizeBytes || feed.size,
      createdAt: feed.created_at || feed.createdAt || feed.publishedAt,
      productionTarget: feed.production_target || feed.productionTarget,
      minimumSupportedBuild: feed.minimum_supported_build || feed.minimumSupportedBuild,
      updateMode: feed.update_mode || feed.updateMode || "guided-installer",
      kind: feed.kind || "windows-installer",
      filename: feed.filename,
    };
  }
  const nested = feed?.artifacts?.windows?.x64 || {};
  return {
    platform: nested.platform === "windows" && nested.arch === "x64" ? PLATFORM : nested.platform,
    buildId: nested.build_id || nested.buildId,
    version: nested.version || feed.version,
    url: nested.installer_url || nested.artifact_url || nested.installerUrl || nested.artifactUrl || nested.url,
    sha256: nested.sha256,
    sizeBytes: nested.size_bytes || nested.sizeBytes || nested.size,
    createdAt: nested.created_at || nested.createdAt || nested.publishedAt || feed.publishedAt,
    productionTarget: nested.production_target || nested.productionTarget || feed.production_target || feed.productionTarget,
    minimumSupportedBuild: nested.minimum_supported_build || nested.minimumSupportedBuild,
    updateMode: nested.update_mode || nested.updateMode || "guided-installer",
    kind: nested.kind || "windows-installer",
    filename: nested.filename,
  };
}

function validateReleaseArtifact(feed, options = {}) {
  const serverUrl = String(options.serverUrl || "");
  const currentBuildId = String(options.currentBuildId || "");
  const expectedProductionTarget = String(options.productionTarget || serverUrl || "").replace(/\/$/, "");
  const artifact = windowsArtifactFromFeed(feed);
  const sha256 = normalizeSha256(artifact.sha256);
  if (artifact.platform !== PLATFORM) return { ok: false, error: "wrong_platform", artifact };
  if (!artifact.buildId) return { ok: false, error: "missing_build_id", artifact };
  if (!sha256) return { ok: false, error: "missing_hash", artifact };
  const sizeBytes = Number(artifact.sizeBytes || 0);
  if (!Number.isFinite(sizeBytes) || sizeBytes <= 0) return { ok: false, error: "missing_size", artifact };
  if (sizeBytes < MIN_WINDOWS_INSTALLER_SIZE_BYTES) return { ok: false, error: "suspicious_artifact_size", artifact, minSizeBytes: MIN_WINDOWS_INSTALLER_SIZE_BYTES };
  if (artifact.kind && !/windows-installer|nsis/i.test(String(artifact.kind))) return { ok: false, error: "wrong_artifact_type", artifact };
  const productionTarget = String(artifact.productionTarget || expectedProductionTarget || "").replace(/\/$/, "");
  if (expectedProductionTarget && productionTarget && productionTarget !== expectedProductionTarget) {
    return { ok: false, error: "production_target_mismatch", artifact, productionTarget, expectedProductionTarget };
  }
  const allowed = isAllowlistedReleaseUrl(artifact.url, serverUrl, options.extraAllowedOrigins || []);
  if (!allowed.ok) return { ...allowed, artifact };
  const comparison = compareBuildIds(currentBuildId, artifact.buildId);
  return {
    ok: true,
    updateAvailable: comparison > 0,
    reason: comparison > 0 ? "newer_build_available" : comparison < 0 ? "older_build_ignored" : "same_build",
    artifact: {
      ...artifact,
      platform: PLATFORM,
      sha256,
      sizeBytes,
      url: allowed.url,
      productionTarget,
    },
  };
}

function validateDownloadedInstaller(filePath, artifact = {}) {
  const stat = fs.existsSync(filePath) ? fs.statSync(filePath) : null;
  if (!stat || !stat.isFile()) return { ok: false, error: "download_failed", path: filePath };
  if (!/\.exe$/i.test(filePath)) return { ok: false, error: "wrong_artifact_type", path: filePath };
  if (artifact.sizeBytes && stat.size !== Number(artifact.sizeBytes)) {
    return { ok: false, error: "size_mismatch", path: filePath, sizeBytes: stat.size, expectedSizeBytes: Number(artifact.sizeBytes) };
  }
  if (stat.size < MIN_WINDOWS_INSTALLER_SIZE_BYTES) {
    return { ok: false, error: "suspicious_artifact_size", path: filePath, sizeBytes: stat.size, minSizeBytes: MIN_WINDOWS_INSTALLER_SIZE_BYTES };
  }
  const hash = crypto.createHash("sha256");
  hash.update(fs.readFileSync(filePath));
  const sha256 = hash.digest("hex");
  if (!artifact.sha256) return { ok: false, error: "missing_hash", path: filePath, sha256 };
  if (sha256 !== artifact.sha256) return { ok: false, error: "hash_mismatch", path: filePath, sha256, expectedSha256: artifact.sha256 };
  return { ok: true, path: filePath, sizeBytes: stat.size, sha256 };
}

function stagedInstallerPath(stagingRoot, artifact = {}) {
  const rawName = String(artifact.filename || path.basename(new URL(artifact.url).pathname) || "WASM-Agent-Setup.exe");
  const filename = rawName.replace(/[^A-Za-z0-9._ -]/g, "_");
  return path.join(stagingRoot, filename);
}

module.exports = {
  FEED_PATH,
  MIN_WINDOWS_INSTALLER_SIZE_BYTES,
  PLATFORM,
  compareBuildIds,
  feedUrlFor,
  isAllowlistedReleaseUrl,
  stagedInstallerPath,
  validateDownloadedInstaller,
  validateReleaseArtifact,
  windowsArtifactFromFeed,
};
