"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const mainJs = fs.readFileSync(path.join(__dirname, "main.js"), "utf8");
const hermesOp = require(path.join(__dirname, "..", "ops", "android", "hermes-wake-proof.js"));

assert(mainJs.includes('"run_hot_operation"'), "run_hot_operation must be allowlisted");
assert(mainJs.includes('"list_hot_operations"'), "list_hot_operations must be allowlisted");
assert(mainJs.includes('"play_wake_phrase_probe"'), "Windows speaker wake probe must be allowlisted");
assert(mainJs.includes('"play_audio_stimulus"'), "Windows room-state stimulus probe must be allowlisted");
assert(mainJs.includes('"refresh_downloaded_hot_ops"'), "refresh_downloaded_hot_ops must be allowlisted");
assert(mainJs.includes('"sync_downloaded_hot_ops"'), "sync_downloaded_hot_ops must be allowlisted");
assert(mainJs.includes('"get_native_kernel_status"'), "get_native_kernel_status must be allowlisted");
assert(mainJs.includes('"refresh_downloaded_runtime"'), "refresh_downloaded_runtime must be allowlisted");
assert(mainJs.includes('"sync_downloaded_runtime"'), "sync_downloaded_runtime must be allowlisted");
assert(mainJs.includes('"rollback_downloaded_runtime"'), "rollback_downloaded_runtime must be allowlisted");
assert(mainJs.includes('"run_shell_self_test"'), "run_shell_self_test must be allowlisted");
assert(mainJs.includes("NATIVE_CONTROL_DEFAULT_TIMEOUT_MS"), "native-control commands must have an executor watchdog");
assert(mainJs.includes("executeNativeControlCommandWithWatchdog"), "native-control polling must call handlers through the watchdog");
assert(mainJs.includes('"handler_timeout"'), "native-control watchdog must produce handler_timeout");
assert(mainJs.includes('action: "command_timeout"'), "native-control watchdog must audit timeout results");
assert(mainJs.includes('action: "command_result_upload_finished"'), "native-control results must upload from a finally path");
assert(mainJs.includes("finally {\n        upload = await postNativeControlResult(command, result);"), "native-control result upload must run in finally");
assert(mainJs.includes("function normalizeHotOperationModulePath"), "hot op path normalizer must exist");
assert(mainJs.includes("function scanHotOperationManifests"), "hot op manifest scanner must exist");
assert(mainJs.includes("function listHotOperations"), "list_hot_operations implementation must exist");
assert(mainJs.includes("function runShellSelfTest"), "run_shell_self_test implementation must exist");
assert(mainJs.includes("function runShellSelfTestSnapshot"), "default run_shell_self_test must have a synchronous snapshot path");
assert(mainJs.includes('mode: "constant_native_control_roundtrip"'), "default run_shell_self_test must avoid wedging deep probes");
assert(mainJs.includes("path.isAbsolute(modulePath)"), "absolute hot op paths must be rejected");
assert(mainJs.includes('part === ".."'), "path traversal must be rejected");
assert(mainJs.includes('"hot_operation_missing"'), "missing ops must return hot_operation_missing");
assert(mainJs.includes('"hot_operation_sha_mismatch"'), "SHA mismatches must return hot_operation_sha_mismatch");
assert(mainJs.includes('"hot_operation_capability_denied"'), "capability denial must be structured");
assert(mainJs.includes('"hot_operation_timeout"'), "timeouts must be structured");
assert(mainJs.includes("HOT_OPERATION_DEFAULT_TIMEOUT_MS = 45_000"), "generic hot op timeout must stay short");
assert(mainJs.includes("hotOperationTimeoutClassification"), "timeout classification must be operation-specific");
assert(mainJs.includes("timeoutMs: error?.timeoutMs || timeoutMs"), "timeout envelopes must expose timeoutMs");
assert(mainJs.includes("lastPhase"), "timeout envelopes must expose lastPhase");
assert(mainJs.includes('"hot_operation_exception"'), "exceptions must be structured");
assert(mainJs.includes("delete require.cache[require.resolve(moduleInfo.path)]"), "dev/user modules must reload from disk each run");
assert(mainJs.includes("WASM_AGENT_BRIDGE_OPS_DIR"), "dev override root must be supported");
assert(mainJs.includes("WASM_AGENT_DISABLE_HOT_OPS"), "hot ops kill switch must be supported");
assert(mainJs.includes("WASM_AGENT_HOT_OPS_DEV_RELOAD"), "hot ops dev reload flag must be supported");
assert(mainJs.includes("WASM_AGENT_HOT_OPS_REQUIRE_SHA"), "hot ops SHA policy flag must be supported");
assert(mainJs.includes("WASM_AGENT_ENABLE_HOT_OP_OVERRIDES"), "local hot-op overrides must require an explicit enable flag");
assert(mainJs.includes('path.join(os.homedir(), ".wasm-agent", "hot-ops")'), "installed local override root must live under ~/.wasm-agent/hot-ops");
assert(mainJs.includes('kind: "local_override"'), "local override root must be first-class provenance");
assert(mainJs.includes('kind: "downloaded"'), "downloaded/release-feed hot-op root must be first-class provenance");
assert(mainJs.includes("downloadedHotOperationManifestTrusted"), "downloaded hot ops must pass a trust guard");
assert(mainJs.includes("syncDownloadedHotOperationsFromFeed"), "downloaded hot ops must sync from the release feed");
assert(mainJs.includes("hotOperationBundleMetadataDiffers"), "downloaded hot-op sync must compare feed and cached metadata");
assert(mainJs.includes("normalizeHotOperationBundleTargetPath"), "downloaded hot-op bundles must validate module and manifest targets");
assert(mainJs.includes("filename.endsWith(HOT_OPERATION_MANIFEST_SUFFIX)"), "downloaded hot-op sync must allow trusted .manifest.json files");
assert(mainJs.includes('"/native/releases/hot-ops/"'), "downloaded hot ops must be restricted to the hot-op release path");
assert(mainJs.includes("await ensureDownloadedHotOperationsFromFeed(payload)"), "hot-op commands must hydrate downloaded ops before resolving");
assert(mainJs.includes("forceSync: true"), "explicit downloaded hot-op refresh must force release-feed sync");
assert(mainJs.includes("NATIVE_KERNEL_CONTRACT_VERSION"), "native capability kernel contract must be versioned");
assert(mainJs.includes("WINDOWS_NATIVE_KERNEL_CAPABILITIES"), "Windows native capability kernel must be explicit");
assert(mainJs.includes("syncDownloadedRuntimeFromFeed"), "downloaded runtime must sync from the release feed");
assert(mainJs.includes("ensureDownloadedRuntimeFromFeed"), "downloaded runtime must hydrate before bridge status and hot ops");
assert(mainJs.includes("rollbackDownloadedRuntimeToLastKnownGood"), "downloaded runtime must support last-known-good rollback");
assert(mainJs.includes("windowsArtifactFromFeed,"), "Windows self-update handler must import feed artifact extraction");
assert(mainJs.includes("const fetched = windowsArtifactFromFeed(feed);"), "Windows self-update handler must expose fetched build evidence");
assert(mainJs.includes("downloadedRuntimeMetadataDiffers"), "downloaded runtime sync must compare feed and cached metadata");
assert(mainJs.includes("downloadedRuntimeFileMismatch"), "downloaded runtime sync must compare cached file SHAs");
assert(mainJs.includes("releaseUrlAllowedForDownloadedRuntime"), "downloaded runtime URLs must be allowlisted");
assert(mainJs.includes('"/native/releases/runtime/"'), "downloaded runtime must be restricted to the runtime release path");
assert(mainJs.includes('path.join(appData, "WASM-Agent", "runtime")'), "downloaded runtime cache must live under app data runtime root");
assert(mainJs.includes('native.capabilities.downloadedRuntime.v1'), "downloaded runtime capability must be advertised");
assert(mainJs.includes("WASM_AGENT_ENABLE_VERBOSE_BRIDGE_LOGS"), "verbose bridge log flag must be supported");
assert(mainJs.includes('path.join(appData, "WASM-Agent", "bridge-ops")'), "user ops root must be supported");
assert(mainJs.includes('resourcePath("bridge-ops")'), "bundled fallback root must be supported");
assert(mainJs.includes("rawResult"), "hot op envelope must preserve raw result");
assert(mainJs.includes("failureClassification"), "hot op envelope must expose camelCase failure classification");
for (const field of ["hotOpSource", "hotOpPath", "hotOpSha", "bundledHotOpSha", "overrideEnabled", "manifestTimeoutMs"]) {
  assert(mainJs.includes(field), `hot op envelopes must expose ${field}`);
}
for (const field of ["downloadedHotOpsSync", "feedBundleId", "cachedBundleId", "moduleSha", "manifestSha", "cachePath"]) {
  assert(mainJs.includes(field), `downloaded hot-op sync must expose ${field}`);
}
for (const field of ["downloadedRuntime", "activeRuntimeId", "activeRuntimeSha", "lastKnownGoodRuntimeId", "activeRuntimePath"]) {
  assert(mainJs.includes(field), `downloaded runtime status must expose ${field}`);
}
assert(mainJs.includes("resolveBestVoiceWakeDiagnostics"), "diagnostics fallback primitive must exist");
assert(mainJs.includes("function playWindowsWakePhraseProbe"), "Windows native-control must expose a bounded speaker wake probe");
assert(mainJs.includes("System.Speech.Synthesis.SpeechSynthesizer"), "Windows speaker probe must use the fixed SpeechSynthesizer primitive");
assert(mainJs.includes("function powershellSingleQuoted"), "Windows audio probes must safely embed bounded PowerShell literals");
assert(mainJs.includes("$phrase = ${powershellSingleQuoted(phrase)};"), "Windows speaker probe must pass phrase as a sanitized literal");
assert(!mainJs.includes("$synth.Speak($args[0])"), "Windows speaker probe must not rely on broken PowerShell argv passing");
assert(mainJs.includes("function playWindowsAudioStimulus"), "Windows native-control must expose bounded non-speech audio stimuli");
assert(mainJs.includes("windows_fixed_audio_stimulus"), "Windows audio stimulus must report the fixed primitive source");
assert(mainJs.includes("[Console]::Beep(${frequencyHz}, ${durationMs});"), "Windows beep stimulus must embed bounded numeric arguments");
assert(mainJs.includes("native.capabilities.speaker.v1"), "Windows speaker primitive must be advertised as a native capability");

const deniedIndex = mainJs.indexOf("function requireHotOperationCapability");
const helperIndex = mainJs.indexOf("function createHotOperationContext");
assert(deniedIndex >= 0 && helperIndex > deniedIndex, "helper context must use the capability guard");
for (const capability of ["adb.device", "adb.shell", "adb.install", "adb.pull", "adb.push", "adb.logcat", "diagnostics.read", "result.upload", "artifact.write"]) {
  assert(mainJs.includes(capability), `helper capability ${capability} must be named`);
}

const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "ops", "android", "hermes-wake-proof.manifest.json"), "utf8"));
const hermesOpText = hermesOpSource();
assert.strictEqual(manifest.name, "run_android_hermes_wake_proof");
assert.strictEqual(manifest.entry, "hermes-wake-proof.js");
assert.strictEqual(manifest.schema, "hermes.wasm_agent.hot_operation_manifest.v1");
assert.strictEqual(manifest.operationId, "run_android_hermes_wake_proof");
assert(manifest.requiredNativeCapabilities.includes("native.capabilities.hotOps.v1"));
assert(manifest.inputsSchema.properties.wakeThreshold, "Hermes proof must accept downloaded wakeThreshold policy");
assert(manifest.inputsSchema.properties.wake_threshold, "Hermes proof must accept snake-case wake_threshold policy");
assert(hermesOpText.includes('"--ef"') && hermesOpText.includes('"wake_threshold"'), "Hermes proof must pass threshold policy to Android service");
assert(hermesOpText.includes("0.999"), "Hermes proof must preserve Android's high wake-threshold ceiling for false-wake hardening");
assert(mainJs.includes("/native/android/wake-word-state"), "Windows proof helper must prefer compact Wake Word state before large diagnostics");
assert(manifest.capabilities.includes("adb.device"));
assert(manifest.timeoutMs >= 120000 && manifest.timeoutMs <= 180000, "Hermes wake proof must request a bounded long timeout");
for (const phase of ["adb_ready", "app_launched", "service_start_requested", "foreground_service_seen", "audio_record_seen", "model_status_seen", "listening", "result_written"]) {
  assert(hermesOpText.includes(phase), `Hermes wake proof must report phase ${phase}`);
}

const canaryManifest = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "ops", "canary", "echo.manifest.json"), "utf8"));
const canaryOp = require(path.join(__dirname, "..", "ops", "canary", "echo.js"));
assert.strictEqual(canaryManifest.name, "canary_echo");
assert.strictEqual(canaryManifest.entry, "echo.js");
assert.strictEqual(canaryManifest.schema, "hermes.wasm_agent.hot_operation_manifest.v1");
assert.strictEqual(canaryManifest.operationId, "canary_echo");
assert(canaryManifest.requiredNativeCapabilities.includes("native.capabilities.hotOps.v1"));
assert(canaryManifest.timeoutMs <= 5000, "canary hot op must keep a short timeout");

const diagnosticsManifest = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "ops", "diagnostics", "native-diagnostics-classifier.manifest.json"), "utf8"));
const diagnosticsOpText = fs.readFileSync(path.join(__dirname, "..", "ops", "diagnostics", "native-diagnostics-classifier.js"), "utf8");
assert.strictEqual(diagnosticsManifest.operationId, "classify_native_diagnostics");
assert(diagnosticsManifest.requiredNativeCapabilities.includes("native.capabilities.diagnostics.v1"));
assert(diagnosticsOpText.includes("classify_native_diagnostics"), "diagnostics classifier must be a real non-Hermes hot op");
assert(fs.existsSync(path.join(__dirname, "..", "scripts", "sync-hot-op-override.js")), "sync hot-op override helper must exist");
assert(mainJs.includes('"get_bridge_status"'), "get_bridge_status must be allowlisted");
assert(mainJs.includes("SHELL_PROTOCOL_VERSION = 2"), "shell protocol v2 must be advertised");
assert(mainJs.includes("MINIMUM_RUNNER_VERSION"), "minimum runner version must be advertised");
assert(mainJs.includes("logsTail"), "bridge results must include logsTail");
assert(mainJs.includes("dryRun"), "run_hot_operation must pass dryRun into hot ops");

const pass = hermesOp.classify({
  status_source: "live_service",
  proof_session_active: true,
  foreground_service_started: true,
  permission_record_audio: true,
  audio_record_started: true,
  audio_read_calls: 10,
  onnx_runtime_available: true,
  wake_engine_ready: true,
  personalized_model_exists: true,
  model_sha_match: true,
  inference_count: 4,
  max_observed_confidence: 0.7,
  wake_threshold: 0.58,
  wake_detected_event_emitted: true,
  command_capture_started: true,
});
assert.strictEqual(pass.stable, true);
assert.strictEqual(pass.failureClassification, "pass");
assert.strictEqual(pass.stages.service_alive, true);
assert.strictEqual(pass.stages.command_capture_ui_started, true);

const openWakeWordBundle = hermesOp.classify({
  status_source: "lightweight_no_model_load",
  proof_session_active: true,
  foreground_service_active: true,
  service_running: true,
  permission_record_audio: true,
  audio_record_started: true,
  audio_read_calls: 10,
  onnx_runtime_available: true,
  onnx_model_ready: true,
  wake_engine_ready: true,
  model_source: "openwakeword_bundle",
  openwakeword_bundle_exists: true,
  personalized_model_exists: true,
  model_sha_match: false,
  inference_count: 68940,
  last_confidence: 0.000009,
  max_confidence_since_start: 0.9997,
  threshold: 0.99,
  wake_hit_count: 8,
});
assert.strictEqual(openWakeWordBundle.stable, true);
assert.strictEqual(openWakeWordBundle.failureClassification, "pass");
assert.strictEqual(openWakeWordBundle.stages.onnx_model_ready, true);
assert.strictEqual(openWakeWordBundle.metrics.inference_count, 68940);
assert.strictEqual(openWakeWordBundle.metrics.wake_detected_count, 8);

const incomplete = hermesOp.classify({
  status_source: "live_service",
  proof_session_active: true,
  foreground_service_started: true,
  permission_record_audio: true,
  audio_record_started: true,
  audio_read_calls: 10,
  onnx_runtime_available: true,
  wake_engine_ready: true,
  personalized_model_exists: true,
  model_sha_match: true,
  inference_count: 4,
  max_observed_confidence: 0.3,
  wake_threshold: 0.58,
});
assert.strictEqual(incomplete.stable, true);
assert.strictEqual(incomplete.failure_classification, "pass");
assert.strictEqual(incomplete.stages.wake_threshold_crossed, false);

const noInference = hermesOp.classify({
  status_source: "live_service",
  proof_session_active: true,
  foreground_service_started: true,
  permission_record_audio: true,
  audio_record_started: true,
  audio_capture_alive: true,
  audio_read_calls: 10,
  onnx_runtime_available: true,
  wake_engine_ready: true,
  personalized_model_exists: true,
  model_sha_match: true,
  inference_count: 0,
});
assert.strictEqual(noInference.stable, false);
assert.strictEqual(noInference.failure_classification, "inference_not_running");

assert.strictEqual(hermesOp.classify({}).failureClassification, "diagnostics_status_missing");

const fixtures = [
  ["voice-wake-pass.json", "pass"],
  ["voice-wake-threshold-fail.json", "pass"],
  ["voice-wake-event-not-routed.json", "pass"],
  ["missing-permission.json", "record_audio_permission_missing"],
  ["missing-model.json", "onnx_model_missing"],
];
for (const [name, expected] of fixtures) {
  const payload = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "..", "fixtures", "hermes", name), "utf8"));
  assert.strictEqual(hermesOp.classify(payload).failureClassification, expected, `${name} must classify as ${expected}`);
}
const bridgeFixture = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "..", "fixtures", "hermes", "bridge-update-required.json"), "utf8"));
assert.strictEqual(bridgeFixture.failureClassification, "bridge_update_required");

canaryOp.run({ operation: { version: canaryManifest.version }, dryRun: true }).then((result) => {
  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.operation, "canary_echo");
  assert.strictEqual(result.source, "hot_operation");
  assert.strictEqual(result.message, "hot op loaded");
});

console.log("windows hot ops ok");

function hermesOpSource() {
  return fs.readFileSync(path.join(__dirname, "..", "ops", "android", "hermes-wake-proof.js"), "utf8");
}
