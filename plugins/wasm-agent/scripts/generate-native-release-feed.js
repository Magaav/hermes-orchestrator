#!/usr/bin/env node
"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const repoRoot = path.resolve(__dirname, "..", "..", "..");
const pluginRoot = path.join(repoRoot, "plugins", "wasm-agent");
const publicReleaseRoot = path.join(pluginRoot, "public", "native", "releases");
const channel = process.env.WASM_AGENT_NATIVE_RELEASE_CHANNEL || "dev";

function readJson(filePath, fallback = null) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return fallback;
  }
}

function sha256(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function fileArtifact(filePath, publicPath, extra = {}) {
  if (!fs.existsSync(filePath)) return null;
  const stats = fs.statSync(filePath);
  return {
    ...extra,
    filename: path.basename(filePath),
    path: filePath,
    url: publicPath,
    sha256: sha256(filePath),
    size: stats.size,
    sizeBytes: stats.size,
  };
}

function copyFileArtifact(filePath, publicDir) {
  fs.mkdirSync(publicDir, { recursive: true });
  const target = path.join(publicDir, path.basename(filePath));
  fs.copyFileSync(filePath, target);
  return target;
}

function gitCommit() {
  try {
    return require("child_process")
      .execFileSync("git", ["rev-parse", "--short=12", "HEAD"], { cwd: repoRoot, encoding: "utf8" })
      .trim();
  } catch {
    return "";
  }
}

function latestWindowsArtifact() {
  const releaseRoot = path.join(repoRoot, "native", "windows", "release");
  const manifest = readJson(path.join(releaseRoot, "release-manifest.json"), {});
  const horcManifest = readJson(path.join(releaseRoot, "horc-build-manifest.json"), {});
  const verify = readJson(path.join(releaseRoot, "VERIFY.json"), {});
  const installer = [
    manifest.installerPath,
    horcManifest.installer_path,
    path.join(releaseRoot, "WASM-Agent-Setup-x64.exe"),
  ].filter(Boolean).find((candidate) => fs.existsSync(candidate));
  if (!installer) return latestPublishedWindowsArtifact();
  copyFileArtifact(installer, path.join(publicReleaseRoot, "windows"));
  const artifact = fileArtifact(installer, `/native/releases/windows/${path.basename(installer)}`, {
    platform: "windows",
    updatePlatform: "win-x64",
    arch: "x64",
    kind: "windows-installer",
    buildId: manifest.buildId || verify.buildId || "",
    build_id: manifest.buildId || verify.buildId || "",
    version: manifest.version || "",
    installableVersion: manifest.installableVersion || "",
    runtimeProofStatus: verify.ok ? "extracted-installer-verified" : "not-runtime-verified",
    updateMode: "guided-installer",
    productionTarget: "https://wa.colmeio.com",
    production_target: "https://wa.colmeio.com",
  });
  const blockmap = `${installer}.blockmap`;
  if (artifact && fs.existsSync(blockmap)) {
    copyFileArtifact(blockmap, path.join(publicReleaseRoot, "windows"));
    artifact.blockmapUrl = `/native/releases/windows/${path.basename(blockmap)}`;
  }
  return artifact;
}

function latestPublishedWindowsArtifact() {
  const publicDir = path.join(publicReleaseRoot, "windows");
  if (!fs.existsSync(publicDir)) return null;
  const candidates = fs.readdirSync(publicDir)
    .filter((name) => /^WASM-Agent-Setup-x64-.*\.exe$/i.test(name))
    .map((name) => path.join(publicDir, name))
    .filter((candidate) => fs.statSync(candidate).isFile())
    .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
  const installer = candidates[0] || "";
  if (!installer) return null;
  const name = path.basename(installer);
  const buildMatch = name.match(/(win-x64-\d{8}T\d{6}Z|\d{8}T\d{6}Z)/);
  const buildId = buildMatch ? (buildMatch[1].startsWith("win-x64-") ? buildMatch[1] : `win-x64-${buildMatch[1]}`) : "";
  const versionMatch = name.match(/WASM-Agent-Setup-x64-([0-9][^-]*)-/);
  return fileArtifact(installer, `/native/releases/windows/${name}`, {
    platform: "windows",
    updatePlatform: "win-x64",
    arch: "x64",
    kind: "windows-installer",
    buildId,
    build_id: buildId,
    version: versionMatch ? versionMatch[1] : "",
    installableVersion: versionMatch ? versionMatch[1] : "",
    runtimeProofStatus: "published-artifact-preserved",
    updateMode: "guided-installer",
    productionTarget: "https://wa.colmeio.com",
    production_target: "https://wa.colmeio.com",
  });
}

function androidArtifacts() {
  const releaseRoot = path.join(repoRoot, "native", "android", "release");
  const manifest = readJson(path.join(releaseRoot, "release-manifest.json"), {});
  const artifacts = {};
  for (const arch of ["arm64", "universal"]) {
    const apk = path.join(releaseRoot, `WASM-Agent-${arch}.apk`);
    if (!fs.existsSync(apk)) continue;
    copyFileArtifact(apk, path.join(publicReleaseRoot, "android"));
    artifacts[arch] = fileArtifact(apk, `/native/releases/android/${path.basename(apk)}`, {
      platform: "android",
      arch,
      kind: "android-apk",
      buildId: manifest.buildId || "",
      version: manifest.version || "",
      versionCode: Number(manifest.versionCode || process.env.WASM_AGENT_ANDROID_VERSION_CODE || 1),
      packageName: manifest.packageName || "com.colmeio.wasmagent",
      signingLevel: manifest.signingLevel || "local-sideload",
      updateMode: "guided-apk-installer",
      runtimeProofStatus: manifest.runtimeProofStatus || "not-runtime-verified",
      runtimeProof: manifest.runtimeProof || undefined,
    });
  }
  return artifacts;
}

function writeFeed() {
  const publishedAt = new Date().toISOString();
  const android = androidArtifacts();
  const windows = latestWindowsArtifact();
  const buildIds = [windows?.buildId, android.arm64?.buildId, android.universal?.buildId].filter(Boolean);
  const manifest = {
    schema: "hermes.wasm_agent.native_release_feed.v1",
    app: "wasm-agent",
    name: "wasm-agent",
    channel,
    platform: "win-x64",
    version: windows?.version || android.universal?.version || android.arm64?.version || "",
    semanticVersion: windows?.version || android.universal?.version || android.arm64?.version || "",
    buildId: buildIds[0] || `native-feed-${publishedAt.replace(/[-:.]/g, "").slice(0, 15)}Z`,
    build_id: windows?.buildId || "",
    installer_url: windows?.url || "",
    artifact_url: windows?.url || "",
    sha256: windows?.sha256 || "",
    size_bytes: windows?.sizeBytes || 0,
    created_at: publishedAt,
    production_target: "https://wa.colmeio.com",
    gitCommit: gitCommit(),
    publishedAt,
    artifacts: {
      windows: windows ? { x64: windows } : {},
      android,
      web: {
        current: {
          platform: "web",
          kind: "pwa",
          buildId: process.env.WASM_AGENT_WEB_BUILD_ID || `web-${publishedAt.replace(/[-:.]/g, "").slice(0, 15)}Z`,
          url: "/",
          updateMode: "service-worker-refresh",
          runtimeProofStatus: "not-runtime-verified",
        },
      },
    },
    notes: [
      "Android sideload updates require OS confirmation and install-unknown-apps permission when needed.",
      "Windows update is a guided installer handoff unless electron-builder updater metadata is added.",
      "Build proof is not runtime proof.",
    ],
  };
  fs.mkdirSync(publicReleaseRoot, { recursive: true });
  fs.writeFileSync(path.join(publicReleaseRoot, "latest.json"), `${JSON.stringify(manifest, null, 2)}\n`);
  return manifest;
}

const manifest = writeFeed();
console.log(`native release feed: ${path.join(publicReleaseRoot, "latest.json")}`);
for (const [platform, value] of Object.entries(manifest.artifacts)) {
  const entries = Object.values(value || {}).filter((item) => item && item.url);
  for (const artifact of entries) {
    console.log(`${platform}\t${artifact.kind}\t${artifact.url}\t${artifact.sha256 || "-"}\t${artifact.runtimeProofStatus || "unknown"}`);
  }
}
