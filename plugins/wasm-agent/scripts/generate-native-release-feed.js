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

function sha256Text(value) {
  return crypto.createHash("sha256").update(String(value || "")).digest("hex");
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

function newestFile(paths) {
  return paths
    .filter((candidate) => candidate && fs.existsSync(candidate) && fs.statSync(candidate).isFile())
    .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs)[0] || "";
}

function androidGradleOutputMetadata() {
  const output = readJson(path.join(repoRoot, "native", "android", "app", "build", "outputs", "apk", "release", "output-metadata.json"), {});
  const element = Array.isArray(output.elements) ? output.elements[0] || {} : {};
  return {
    version: element.versionName || "",
    versionCode: Number(element.versionCode || 0),
  };
}

function androidBuildConfigId(apkPath = "") {
  const buildConfig = path.join(repoRoot, "native", "android", "app", "build", "generated", "source", "buildConfig", "release", "com", "colmeio", "wasmagent", "BuildConfig.java");
  if (fs.existsSync(buildConfig)) {
    const match = fs.readFileSync(buildConfig, "utf8").match(/NATIVE_BUILD_ID\s*=\s*"([^"]+)"/);
    if (match) return match[1];
  }
  if (apkPath && fs.existsSync(apkPath)) {
    try {
      const output = require("child_process").execFileSync("bash", ["-lc", `unzip -p ${JSON.stringify(apkPath)} classes.dex | strings`], { encoding: "utf8", maxBuffer: 8 * 1024 * 1024 });
      const match = output.match(/\bandroid-(?:universal|arm64)-\d{8}T\d{6}Z\b/);
      if (match) return match[0];
    } catch {
      return "";
    }
  }
  return "";
}

function writeJsonArtifact(value, targetPath) {
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  fs.writeFileSync(targetPath, `${JSON.stringify(value, null, 2)}\n`);
  return targetPath;
}

function bundleShaForFiles(files = []) {
  return sha256Text(JSON.stringify(
    files
      .map((file) => ({
        role: file.role || "",
        targetPath: file.targetPath || "",
        sha256: file.sha256 || "",
      }))
      .sort((a, b) => a.targetPath.localeCompare(b.targetPath)),
  ));
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

function buildRank(value) {
  const text = String(value || "").trim();
  const match = text.match(/^(?:win-x64-|android-(?:universal|arm64)-)?(\d{8}T\d{6}Z)$/i);
  return match ? match[1] : text;
}

function buildIdFromWindowsInstallerName(name = "") {
  const match = String(name || "").match(/(win-x64-\d{8}T\d{6}Z|\d{8}T\d{6}Z)/);
  if (!match) return "";
  return match[1].startsWith("win-x64-") ? match[1] : `win-x64-${match[1]}`;
}

function newestWindowsInstaller(releaseRoot, preferredBuildId = "") {
  if (!fs.existsSync(releaseRoot)) return "";
  const preferredRank = buildRank(preferredBuildId);
  const candidates = fs.readdirSync(releaseRoot)
    .filter((name) => /^WASM-Agent-Setup-x64(?:-[^-]+-\d{8}T\d{6}Z)?\.exe$/i.test(name))
    .map((name) => {
      const filePath = path.join(releaseRoot, name);
      const stat = fs.statSync(filePath);
      const buildId = buildIdFromWindowsInstallerName(name);
      const rank = buildRank(buildId);
      const isVersioned = Boolean(buildId);
      return { filePath, stat, buildId, rank, isVersioned };
    })
    .filter((item) => item.stat.isFile());
  if (!candidates.length) return "";
  const preferred = candidates
    .filter((item) => item.buildId === preferredBuildId)
    .sort((a, b) => Number(b.isVersioned) - Number(a.isVersioned) || b.stat.mtimeMs - a.stat.mtimeMs)[0];
  if (preferred) return preferred.filePath;
  candidates.sort((a, b) => {
    if (a.isVersioned !== b.isVersioned) return a.isVersioned ? -1 : 1;
    if (a.rank !== b.rank) return a.rank > b.rank ? -1 : 1;
    return b.stat.mtimeMs - a.stat.mtimeMs;
  });
  if (preferredRank && candidates[0]?.rank && candidates[0].rank < preferredRank) {
    return "";
  }
  return candidates[0].filePath;
}

function latestWindowsArtifact() {
  const releaseRoot = path.join(repoRoot, "native", "windows", "release");
  const manifest = readJson(path.join(releaseRoot, "release-manifest.json"), {});
  const horcManifest = readJson(path.join(releaseRoot, "horc-build-manifest.json"), {});
  const verify = readJson(path.join(releaseRoot, "VERIFY.json"), {});
  const preferredBuildId = manifest.buildId || verify.buildId || "";
  const installer = [
    manifest.installerPath,
    horcManifest.installer_path,
    newestWindowsInstaller(releaseRoot, preferredBuildId),
    path.join(releaseRoot, "WASM-Agent-Setup-x64.exe"),
  ].filter(Boolean).find((candidate) => fs.existsSync(candidate));
  if (!installer) return latestPublishedWindowsArtifact();
  copyFileArtifact(installer, path.join(publicReleaseRoot, "windows"));
  const artifact = fileArtifact(installer, `/native/releases/windows/${path.basename(installer)}`, {
    platform: "windows",
    updatePlatform: "win-x64",
    arch: "x64",
    kind: "windows-installer",
    buildId: preferredBuildId || buildIdFromWindowsInstallerName(path.basename(installer)),
    build_id: preferredBuildId || buildIdFromWindowsInstallerName(path.basename(installer)),
    version: manifest.version || verify.packageVersion || "",
    installableVersion: manifest.installableVersion || verify.packageVersion || "",
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
  const gradleReleaseApk = path.join(repoRoot, "native", "android", "app", "build", "outputs", "apk", "release", "app-release.apk");
  const manifest = readJson(path.join(releaseRoot, "release-manifest.json"), {});
  const artifacts = {};
  for (const arch of ["arm64", "universal"]) {
    const releaseApk = path.join(releaseRoot, `WASM-Agent-${arch}.apk`);
    const apk = newestFile([releaseApk, gradleReleaseApk]);
    if (!fs.existsSync(apk)) continue;
    const sourceIsPromotedRelease = path.resolve(apk) === path.resolve(releaseApk);
    const publishedName = `WASM-Agent-${arch}.apk`;
    const releaseTarget = path.join(releaseRoot, publishedName);
    fs.mkdirSync(releaseRoot, { recursive: true });
    if (path.resolve(apk) !== path.resolve(releaseTarget)) {
      fs.copyFileSync(apk, releaseTarget);
    }
    const sidecar = path.join(releaseRoot, `WASM-Agent-${arch}.native-defaults.json`);
    const existingSidecar = readJson(sidecar, {});
    const releaseSha = sha256(releaseTarget);
    const gradleMetadata = androidGradleOutputMetadata();
    const embeddedBuildId = androidBuildConfigId(releaseTarget);
    const manifestShaMatches = Array.isArray(manifest.artifacts)
      && manifest.artifacts.some((item) => item && item.arch === arch && item.sha256 === releaseSha);
    if (!fs.existsSync(sidecar) || existingSidecar.artifactSha256 !== releaseSha || (embeddedBuildId && existingSidecar.buildId !== embeddedBuildId)) {
      const stat = fs.statSync(releaseTarget);
      const generatedAt = new Date(stat.mtimeMs).toISOString();
      const generatedBuildId = `android-${generatedAt.replace(/[-:.]/g, "").slice(0, 15)}Z-${releaseSha.slice(0, 8)}`;
      const buildId = embeddedBuildId || (sourceIsPromotedRelease && manifest.buildId ? manifest.buildId : generatedBuildId);
      const version = gradleMetadata.version || manifest.version || "0.1.0";
      const versionCode = Number(gradleMetadata.versionCode || manifest.versionCode || 1);
      writeJsonArtifact({
        schema: "hermes.wasm_agent.native_defaults.v1",
        appId: "wasm-agent",
        service: "wasm-agent",
        serverUrl: "https://wa.colmeio.com",
        serverUrlCandidates: ["https://wa.colmeio.com"],
        mode: "production",
        allowLocalDev: false,
        buildPlatform: "android",
        targetArch: arch,
        nativeShellVersion: version,
        wasmAgentVersion: version,
        installableVersion: version,
        versionCode,
        buildId,
        buildGeneratedAt: generatedAt,
        artifactKind: "android-apk",
        signingLevel: manifest.signingLevel || "unknown",
        universalApk: true,
        sourceApk: path.relative(path.join(repoRoot, "native", "android"), apk),
        artifactSha256: releaseSha,
        artifactSize: stat.size,
      }, sidecar);
    }
    copyFileArtifact(releaseTarget, path.join(publicReleaseRoot, "android"));
    const sidecarPayload = readJson(sidecar, {});
    const buildId = sidecarPayload.buildId || manifest.buildId || `android-${new Date(fs.statSync(releaseTarget).mtimeMs).toISOString().replace(/[-:.]/g, "").slice(0, 15)}Z-${sha256(releaseTarget).slice(0, 8)}`;
    artifacts[arch] = fileArtifact(releaseTarget, `/native/releases/android/${publishedName}`, {
      platform: "android",
      arch,
      kind: "android-apk",
      buildId,
      version: sidecarPayload.wasmAgentVersion || sidecarPayload.installableVersion || manifest.version || "",
      versionCode: Number(sidecarPayload.versionCode || manifest.versionCode || process.env.WASM_AGENT_ANDROID_VERSION_CODE || 1),
      packageName: manifest.packageName || "com.colmeio.wasmagent",
      signingLevel: sidecarPayload.signingLevel || manifest.signingLevel || "local-sideload",
      updateMode: "guided-apk-installer",
      runtimeProofStatus: manifestShaMatches ? (manifest.runtimeProofStatus || "not-runtime-verified") : "not-runtime-verified",
      runtimeProof: manifestShaMatches ? (manifest.runtimeProof || undefined) : undefined,
    });
  }
  return artifacts;
}

function hotOperationArtifacts() {
  const opsRoot = path.join(repoRoot, "native", "windows", "ops");
  const releaseRoot = path.join(publicReleaseRoot, "hot-ops");
  const specs = [
    {
      id: "native-diagnostics-classifier",
      platform: "diagnostics",
      name: "nativeDiagnosticsClassifier",
      operationName: "classify_native_diagnostics",
      sourceModule: path.join(opsRoot, "diagnostics", "native-diagnostics-classifier.js"),
      sourceManifest: path.join(opsRoot, "diagnostics", "native-diagnostics-classifier.manifest.json"),
      publicDir: path.join(releaseRoot, "diagnostics"),
      publicBase: "/native/releases/hot-ops/diagnostics",
      moduleName: "native-diagnostics-classifier.js",
      manifestName: "native-diagnostics-classifier.manifest.json",
    },
    {
      id: "android-hermes-wake-proof",
      platform: "android",
      name: "hermesWakeProof",
      operationName: "run_android_hermes_wake_proof",
      sourceModule: path.join(opsRoot, "android", "hermes-wake-proof.js"),
      sourceManifest: path.join(opsRoot, "android", "hermes-wake-proof.manifest.json"),
      publicDir: path.join(releaseRoot, "android"),
      publicBase: "/native/releases/hot-ops/android",
      moduleName: "hermes-wake-proof.js",
      manifestName: "hermes-wake-proof.manifest.json",
    },
    {
      id: "android-ui-input-proof",
      platform: "android",
      name: "uiInputProof",
      operationName: "run_android_ui_input_proof",
      sourceModule: path.join(opsRoot, "android", "android-ui-input-proof.js"),
      sourceManifest: path.join(opsRoot, "android", "android-ui-input-proof.manifest.json"),
      publicDir: path.join(releaseRoot, "android"),
      publicBase: "/native/releases/hot-ops/android",
      moduleName: "android-ui-input-proof.js",
      manifestName: "android-ui-input-proof.manifest.json",
    },
  ];
  const artifacts = {};
  for (const spec of specs) {
    if (!fs.existsSync(spec.sourceModule) || !fs.existsSync(spec.sourceManifest)) continue;
    const moduleTarget = copyFileArtifact(spec.sourceModule, spec.publicDir);
    const moduleSha = sha256(moduleTarget);
    const sourceManifest = readJson(spec.sourceManifest, {});
    const bundleId = `${spec.id}-${moduleSha.slice(0, 16)}`;
    const trustedManifest = {
      ...sourceManifest,
      schema: sourceManifest.schema || "hermes.wasm_agent.hot_operation_manifest.v1",
      bundleId,
      trusted: true,
      trustedSha256: moduleSha,
      sha256: moduleSha,
      publishedAt: new Date().toISOString(),
    };
    const manifestTarget = writeJsonArtifact(trustedManifest, path.join(spec.publicDir, spec.manifestName));
    artifacts[spec.platform] = artifacts[spec.platform] || {};
    artifacts[spec.platform][spec.name] = {
      platform: spec.platform,
      kind: "windows-hot-op-bundle",
      id: bundleId,
      bundleId,
      bundleSha: bundleShaForFiles([
        fileArtifact(moduleTarget, `${spec.publicBase}/${spec.moduleName}`, {
          role: "module",
          targetPath: `${spec.platform}/${spec.moduleName}`,
        }),
        fileArtifact(manifestTarget, `${spec.publicBase}/${spec.manifestName}`, {
          role: "manifest",
          targetPath: `${spec.platform}/${spec.manifestName}`,
        }),
      ].filter(Boolean)),
      operationName: spec.operationName,
      updateMode: "trusted-hot-op-download",
      runtimeProofStatus: "not-runtime-verified",
      files: [
        fileArtifact(moduleTarget, `${spec.publicBase}/${spec.moduleName}`, {
          role: "module",
          targetPath: `${spec.platform}/${spec.moduleName}`,
        }),
        fileArtifact(manifestTarget, `${spec.publicBase}/${spec.manifestName}`, {
          role: "manifest",
          targetPath: `${spec.platform}/${spec.manifestName}`,
        }),
      ].filter(Boolean),
    };
  }
  return artifacts;
}

function runtimeArtifacts() {
  const runtimeRoot = path.join(pluginRoot, "native-runtime", "launcher");
  const releaseRoot = path.join(publicReleaseRoot, "runtime", "launcher");
  const sourceManifestPath = path.join(runtimeRoot, "runtime-manifest.json");
  if (!fs.existsSync(sourceManifestPath)) return {};
  const sourceManifest = readJson(sourceManifestPath, {});
  const specs = [
    ["manifest", "runtime-manifest.json"],
    ["entry", "launcher.html"],
    ["style", "launcher.css"],
    ["script", "launcher.js"],
    ["diagnosticsSchema", "diagnostics-schema.json"],
    ["config", "runtime-config.json"],
    ["modelMetadata", "model-metadata.json"],
  ];
  fs.mkdirSync(releaseRoot, { recursive: true });
  const copied = [];
  for (const [role, filename] of specs) {
    const source = path.join(runtimeRoot, filename);
    if (!fs.existsSync(source)) continue;
    const target = copyFileArtifact(source, releaseRoot);
    copied.push(fileArtifact(target, `/native/releases/runtime/launcher/${filename}`, {
      role,
      targetPath: `launcher/${filename}`,
    }));
  }
  const bundleSha = bundleShaForFiles(copied);
  const bundleId = `native-launcher-runtime-${bundleSha.slice(0, 16)}`;
  const trustedManifest = {
    ...sourceManifest,
    schema: sourceManifest.schema || "hermes.wasm_agent.downloaded_runtime.v1",
    runtimeId: bundleId,
    bundleId,
    bundleSha,
    trusted: true,
    trustedSha256: bundleSha,
    publishedAt: new Date().toISOString(),
    files: copied.map((file) => ({
      role: file.role,
      targetPath: file.targetPath,
      sha256: file.sha256,
      sizeBytes: file.sizeBytes,
    })),
  };
  const manifestTarget = writeJsonArtifact(trustedManifest, path.join(releaseRoot, "runtime-manifest.json"));
  const files = copied.map((file) => (
    file.role === "manifest"
      ? fileArtifact(manifestTarget, "/native/releases/runtime/launcher/runtime-manifest.json", {
        role: "manifest",
        targetPath: "launcher/runtime-manifest.json",
      })
      : file
  ));
  const manifestSha = files.find((file) => file.role === "manifest")?.sha256 || "";
  return {
    launcher: {
      platform: "all",
      kind: "native-runtime-bundle",
      id: bundleId,
      bundleId,
      runtimeId: bundleId,
      bundleSha,
      manifestSha,
      updateMode: "downloaded-runtime-atomic",
      runtimeProofStatus: "not-runtime-verified",
      fallback: "last-known-good",
      files,
    },
  };
}

function writeFeed() {
  const publishedAt = new Date().toISOString();
  const android = androidArtifacts();
  const windows = latestWindowsArtifact();
  const hotOps = hotOperationArtifacts();
  const runtime = runtimeArtifacts();
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
    shellBuildId: windows?.buildId || "",
    shellSha256: windows?.sha256 || "",
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
      runtime,
      hotOps,
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
      "Downloaded runtime and hot-op bundles are activated by SHA-verified release-feed sync with last-known-good fallback.",
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
  const entries = Object.values(value || {}).filter((item) => item && (item.url || item.files));
  for (const artifact of entries) {
    console.log(`${platform}\t${artifact.kind}\t${artifact.url || artifact.bundleId || "-"}\t${artifact.sha256 || "-"}\t${artifact.runtimeProofStatus || "unknown"}`);
  }
}
