#!/usr/bin/env node
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const androidRoot = path.resolve(__dirname, "..");
const appRoot = path.join(androidRoot, "app");
const releaseRoot = path.join(androidRoot, "release");
const signingRoot = path.join(androidRoot, "signing");
const cloudOrigin = "https://wa.colmeio.com";

function fail(message) {
  console.error(`android release: ${message}`);
  process.exit(2);
}

function run(command, args, options = {}) {
  console.log(`android release: ${[command, ...args].join(" ")}`);
  const result = spawnSync(command, args, {
    cwd: options.cwd || androidRoot,
    env: options.env || process.env,
    stdio: options.capture ? ["ignore", "pipe", "pipe"] : "inherit",
    shell: Boolean(options.shell),
    timeout: options.timeoutMs || 0,
    encoding: options.capture ? "utf8" : undefined,
  });
  if (result.error && result.error.code === "ETIMEDOUT") {
    fail(`${command} timed out after ${options.timeoutMs}ms`);
  }
  if (result.signal) {
    fail(`${command} terminated by signal ${result.signal}`);
  }
  if (result.status !== 0) {
    if (options.capture) {
      process.stderr.write(result.stdout || "");
      process.stderr.write(result.stderr || "");
    }
    fail(`${command} exited with status ${result.status}`);
  }
  return result;
}

function commandExists(command) {
  const probe = process.platform === "win32"
    ? spawnSync("where", [command], { stdio: "ignore" })
    : spawnSync("bash", ["-lc", `command -v ${JSON.stringify(command)}`], { stdio: "ignore" });
  return probe.status === 0;
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

function readVersionName() {
  const buildGradle = fs.readFileSync(path.join(appRoot, "build.gradle"), "utf8");
  const match = buildGradle.match(/versionName\s*=\s*"([^"]+)"/);
  return process.env.WASM_AGENT_ANDROID_VERSION || (match ? match[1] : "0.1.0");
}

function stamp(date = new Date()) {
  return date.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
}

function androidVersionCode(date = new Date()) {
  const explicit = Number(process.env.WASM_AGENT_ANDROID_VERSION_CODE || 0);
  if (Number.isFinite(explicit) && explicit > 0) return String(Math.floor(explicit));
  return String(Math.floor(date.getTime() / 1000));
}

function sha256(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function newestApk(dir) {
  if (!fs.existsSync(dir)) return "";
  const candidates = fs.readdirSync(dir)
    .filter((name) => name.endsWith(".apk") && !name.includes("unsigned"))
    .map((name) => path.join(dir, name))
    .filter((candidate) => fs.statSync(candidate).isFile())
    .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
  return candidates[0] || "";
}

function gradleCommand() {
  const gradleBin = process.env.GRADLE_BIN || "";
  if (gradleBin) return { command: gradleBin, args: [] };
  const wrapper = process.platform === "win32" ? path.join(androidRoot, "gradlew.bat") : path.join(androidRoot, "gradlew");
  if (fs.existsSync(wrapper)) return { command: wrapper, args: [] };
  const cachedVersion = process.env.HORC_ANDROID_GRADLE_VERSION || "8.9";
  const cachedGradle = path.join(androidRoot, ".gradle-dist", `gradle-${cachedVersion}`, "bin", process.platform === "win32" ? "gradle.bat" : "gradle");
  if (fs.existsSync(cachedGradle)) return { command: cachedGradle, args: [] };
  if (commandExists("gradle")) return { command: "gradle", args: [] };
  fail("Gradle was not found. Install Gradle, set GRADLE_BIN, or add a Gradle wrapper.");
}

function findApksigner(env = process.env) {
  if (env.APKSIGNER_BIN) return env.APKSIGNER_BIN;
  if (commandExists("apksigner")) return "apksigner";
  const sdkRoot = env.ANDROID_HOME || env.ANDROID_SDK_ROOT || "";
  const buildToolsRoot = sdkRoot ? path.join(sdkRoot, "build-tools") : "";
  if (!buildToolsRoot || !fs.existsSync(buildToolsRoot)) return "";
  const versions = fs.readdirSync(buildToolsRoot).sort().reverse();
  for (const version of versions) {
    const candidate = path.join(buildToolsRoot, version, process.platform === "win32" ? "apksigner.bat" : "apksigner");
    if (fs.existsSync(candidate)) return candidate;
  }
  return "";
}

function ensureSideloadSigningKey(env) {
  const externalKeystore = Boolean(process.env.WASM_AGENT_ANDROID_KEYSTORE);
  const keystore = env.WASM_AGENT_ANDROID_KEYSTORE;
  if (fs.existsSync(keystore)) return externalKeystore ? "external" : "local-sideload";
  if (externalKeystore) fail(`configured WASM_AGENT_ANDROID_KEYSTORE does not exist: ${keystore}`);
  if (!commandExists("keytool")) fail("keytool was not found. Install a JDK or provide WASM_AGENT_ANDROID_KEYSTORE.");
  fs.mkdirSync(path.dirname(keystore), { recursive: true });
  run("keytool", [
    "-genkeypair",
    "-keystore", keystore,
    "-storetype", "PKCS12",
    "-storepass", env.WASM_AGENT_ANDROID_KEYSTORE_PASSWORD,
    "-keypass", env.WASM_AGENT_ANDROID_KEY_PASSWORD,
    "-alias", env.WASM_AGENT_ANDROID_KEY_ALIAS,
    "-keyalg", "RSA",
    "-keysize", "2048",
    "-validity", "10000",
    "-dname", "CN=WASM Agent Android Sideload,O=Colmeio,C=US",
    "-noprompt",
  ]);
  return "local-sideload";
}

function verifyProductionApk(apkPath, env = process.env) {
  const bytes = fs.readFileSync(apkPath);
  if (bytes.length < 1024) fail(`APK is unexpectedly small: ${apkPath}`);
  let text = bytes.toString("latin1");
  if (commandExists("zipinfo") && commandExists("unzip")) {
    const listing = run("zipinfo", ["-1", apkPath], { capture: true }).stdout || "";
    const inspectEntries = listing
      .split(/\r?\n/)
      .filter((entry) => entry === "resources.arsc" || /^classes\d*\.dex$/.test(entry));
    for (const entry of inspectEntries) {
      const extracted = spawnSync("unzip", ["-p", apkPath, entry], { encoding: "latin1" });
      if (extracted.status === 0) text += extracted.stdout || "";
      if (commandExists("strings")) {
        const stringified = spawnSync("bash", ["-lc", `unzip -p ${shellQuote(apkPath)} ${shellQuote(entry)} | strings`], { encoding: "utf8" });
        if (stringified.status === 0) text += stringified.stdout || "";
      }
    }
  }
  for (const forbidden of ["127.0.0.1:8877", "localhost:8877", "0.0.0.0:8877"]) {
    if (text.includes(forbidden)) fail(`production APK contains forbidden local backend literal: ${forbidden}`);
  }
  if (!text.includes("wa.colmeio.com")) fail("production APK does not contain the cloud backend origin");
  const apksigner = findApksigner(env);
  if (!apksigner && env.WASM_AGENT_ANDROID_SKIP_APKSIGNER_VERIFY !== "1") {
    fail("apksigner was not found. Install Android build-tools or set WASM_AGENT_ANDROID_SKIP_APKSIGNER_VERIFY=1.");
  }
  if (apksigner) {
    const timeoutMs = Number(env.WASM_AGENT_ANDROID_APKSIGNER_TIMEOUT_MS || 600_000);
    run(apksigner, ["verify", "--verbose", apkPath], { env, timeoutMs });
  }
}

function metadataFor(target, sourceApk, env, signingLevel) {
  return {
    schema: "hermes.wasm_agent.native_defaults.v1",
    appId: "wasm-agent",
    service: "wasm-agent",
    serverUrl: cloudOrigin,
    serverUrlCandidates: [cloudOrigin],
    mode: "production",
    allowLocalDev: false,
    buildPlatform: "android",
    targetArch: target.arch,
    nativeShellVersion: env.WASM_AGENT_ANDROID_VERSION,
    wasmAgentVersion: env.WASM_AGENT_ANDROID_VERSION,
    installableVersion: env.WASM_AGENT_ANDROID_VERSION,
    versionCode: Number(env.WASM_AGENT_ANDROID_VERSION_CODE),
    buildId: env.WASM_AGENT_ANDROID_BUILD_ID,
    buildGeneratedAt: env.WASM_AGENT_ANDROID_BUILD_GENERATED_AT,
    artifactKind: "android-apk",
    signingLevel,
    universalApk: true,
    sourceApk: path.relative(androidRoot, sourceApk),
    artifactSha256: sha256(target.path),
    artifactSize: fs.statSync(target.path).size,
  };
}

function main() {
  const generatedAt = new Date();
  const version = readVersionName();
  const buildStamp = stamp(generatedAt);
  const env = {
    ...process.env,
    WASM_AGENT_ANDROID_VERSION: version,
    WASM_AGENT_ANDROID_VERSION_CODE: androidVersionCode(generatedAt),
    WASM_AGENT_ANDROID_BUILD_ID: process.env.WASM_AGENT_ANDROID_BUILD_ID || `android-universal-${buildStamp}`,
    WASM_AGENT_ANDROID_BUILD_GENERATED_AT: generatedAt.toISOString(),
    WASM_AGENT_ANDROID_KEYSTORE: process.env.WASM_AGENT_ANDROID_KEYSTORE || path.join(signingRoot, "wasm-agent-sideload.jks"),
    WASM_AGENT_ANDROID_KEYSTORE_PASSWORD: process.env.WASM_AGENT_ANDROID_KEYSTORE_PASSWORD || "wasm-agent-sideload",
    WASM_AGENT_ANDROID_KEY_ALIAS: process.env.WASM_AGENT_ANDROID_KEY_ALIAS || "wasm-agent-sideload",
  };
  env.WASM_AGENT_ANDROID_KEY_PASSWORD = process.env.WASM_AGENT_ANDROID_KEY_PASSWORD || env.WASM_AGENT_ANDROID_KEYSTORE_PASSWORD;
  const localSdkRoot = path.join(androidRoot, ".android-sdk");
  if (!env.ANDROID_HOME && fs.existsSync(localSdkRoot)) {
    env.ANDROID_HOME = localSdkRoot;
  }
  if (!env.ANDROID_SDK_ROOT && env.ANDROID_HOME) {
    env.ANDROID_SDK_ROOT = env.ANDROID_HOME;
  }
  const qemuLdPrefix = path.join(androidRoot, ".android-sdk-qemu-root");
  if (!env.QEMU_LD_PREFIX && fs.existsSync(qemuLdPrefix)) {
    env.QEMU_LD_PREFIX = qemuLdPrefix;
  }

  fs.mkdirSync(releaseRoot, { recursive: true });
  const signingLevel = ensureSideloadSigningKey(env);
  const gradle = gradleCommand();
  const gradleArgs = [...gradle.args, "--no-daemon", "--build-cache"];
  if (env.HORC_ANDROID_KOTLIN_IN_PROCESS === "1") {
    gradleArgs.push("-Pkotlin.compiler.execution.strategy=in-process");
    gradleArgs.push("-Dkotlin.compiler.execution.strategy=in-process");
  }
  if (env.HORC_ANDROID_RUN_UNIT_TESTS === "1") {
    run(gradle.command, [...gradleArgs, ":app:testReleaseUnitTest"], { cwd: androidRoot, env });
  }
  if (env.WASM_AGENT_ANDROID_SKIP_LINT === "1") {
    gradleArgs.push("-x", "lintVitalAnalyzeRelease", "-x", "lintVitalReportRelease", "-x", "lintVitalRelease");
  }
  gradleArgs.push(":app:assembleRelease");
  run(gradle.command, gradleArgs, { cwd: androidRoot, env });

  const apkPath = newestApk(path.join(appRoot, "build", "outputs", "apk", "release"));
  if (!apkPath) fail("Gradle did not produce a signed release APK.");
  verifyProductionApk(apkPath, env);

  const targets = [
    { arch: "universal", path: path.join(releaseRoot, "WASM-Agent-universal.apk") },
    { arch: "arm64", path: path.join(releaseRoot, "WASM-Agent-arm64.apk") },
  ];
  for (const target of targets) {
    fs.copyFileSync(apkPath, target.path);
    const metadata = metadataFor(target, apkPath, env, signingLevel);
    fs.writeFileSync(target.path.replace(/\.apk$/, ".native-defaults.json"), `${JSON.stringify(metadata, null, 2)}\n`);
  }

  const manifest = {
    schema: "hermes.wasm_agent.android_release_manifest.v1",
    generatedAt: generatedAt.toISOString(),
    host: { os: os.platform(), arch: os.arch() },
    buildId: env.WASM_AGENT_ANDROID_BUILD_ID,
    version,
    versionCode: Number(env.WASM_AGENT_ANDROID_VERSION_CODE),
    sourceApk: path.relative(androidRoot, apkPath),
    serverUrl: cloudOrigin,
    allowLocalDev: false,
    signingLevel,
    artifacts: targets.map((target) => ({
      arch: target.arch,
      path: path.relative(androidRoot, target.path),
      sha256: sha256(target.path),
      size: fs.statSync(target.path).size,
      kind: "android-apk",
    })),
  };
  fs.writeFileSync(path.join(releaseRoot, "release-manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);
  console.log(`android release: wrote ${path.join(releaseRoot, "WASM-Agent-universal.apk")}`);
  console.log(`android release: wrote ${path.join(releaseRoot, "WASM-Agent-arm64.apk")}`);
  console.log(`android release: buildId=${env.WASM_AGENT_ANDROID_BUILD_ID} signing=${signingLevel}`);
}

main();
