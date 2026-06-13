"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const mainJs = fs.readFileSync(path.join(__dirname, "main.js"), "utf8");
const hermesOp = require(path.join(__dirname, "..", "ops", "android", "hermes-wake-proof.js"));

assert(mainJs.includes('"run_hot_operation"'), "run_hot_operation must be allowlisted");
assert(mainJs.includes('"list_hot_operations"'), "list_hot_operations must be allowlisted");
assert(mainJs.includes('"run_shell_self_test"'), "run_shell_self_test must be allowlisted");
assert(mainJs.includes("function normalizeHotOperationModulePath"), "hot op path normalizer must exist");
assert(mainJs.includes("function scanHotOperationManifests"), "hot op manifest scanner must exist");
assert(mainJs.includes("function listHotOperations"), "list_hot_operations implementation must exist");
assert(mainJs.includes("function runShellSelfTest"), "run_shell_self_test implementation must exist");
assert(mainJs.includes("path.isAbsolute(modulePath)"), "absolute hot op paths must be rejected");
assert(mainJs.includes('part === ".."'), "path traversal must be rejected");
assert(mainJs.includes('"hot_operation_missing"'), "missing ops must return hot_operation_missing");
assert(mainJs.includes('"hot_operation_sha_mismatch"'), "SHA mismatches must return hot_operation_sha_mismatch");
assert(mainJs.includes('"hot_operation_capability_denied"'), "capability denial must be structured");
assert(mainJs.includes('"hot_operation_timeout"'), "timeouts must be structured");
assert(mainJs.includes('"hot_operation_exception"'), "exceptions must be structured");
assert(mainJs.includes("delete require.cache[require.resolve(moduleInfo.path)]"), "dev/user modules must reload from disk each run");
assert(mainJs.includes("WASM_AGENT_BRIDGE_OPS_DIR"), "dev override root must be supported");
assert(mainJs.includes("WASM_AGENT_DISABLE_HOT_OPS"), "hot ops kill switch must be supported");
assert(mainJs.includes("WASM_AGENT_HOT_OPS_DEV_RELOAD"), "hot ops dev reload flag must be supported");
assert(mainJs.includes("WASM_AGENT_HOT_OPS_REQUIRE_SHA"), "hot ops SHA policy flag must be supported");
assert(mainJs.includes("WASM_AGENT_ENABLE_VERBOSE_BRIDGE_LOGS"), "verbose bridge log flag must be supported");
assert(mainJs.includes('path.join(appData, "WASM-Agent", "bridge-ops")'), "user ops root must be supported");
assert(mainJs.includes('resourcePath("bridge-ops")'), "bundled fallback root must be supported");
assert(mainJs.includes("rawResult"), "hot op envelope must preserve raw result");
assert(mainJs.includes("failureClassification"), "hot op envelope must expose camelCase failure classification");
assert(mainJs.includes("resolveBestVoiceWakeDiagnostics"), "diagnostics fallback primitive must exist");

const deniedIndex = mainJs.indexOf("function requireHotOperationCapability");
const helperIndex = mainJs.indexOf("function createHotOperationContext");
assert(deniedIndex >= 0 && helperIndex > deniedIndex, "helper context must use the capability guard");
for (const capability of ["adb.device", "adb.shell", "adb.install", "adb.pull", "adb.push", "adb.logcat", "diagnostics.read", "result.upload", "artifact.write"]) {
  assert(mainJs.includes(capability), `helper capability ${capability} must be named`);
}

const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "ops", "android", "hermes-wake-proof.manifest.json"), "utf8"));
assert.strictEqual(manifest.name, "run_android_hermes_wake_proof");
assert.strictEqual(manifest.entry, "hermes-wake-proof.js");
assert(manifest.capabilities.includes("adb.device"));

const canaryManifest = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "ops", "canary", "echo.manifest.json"), "utf8"));
const canaryOp = require(path.join(__dirname, "..", "ops", "canary", "echo.js"));
assert.strictEqual(canaryManifest.name, "canary_echo");
assert.strictEqual(canaryManifest.entry, "echo.js");
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
assert.strictEqual(incomplete.stable, false);
assert.strictEqual(incomplete.failure_classification, "wake_threshold_not_crossed");

const fixtures = [
  ["voice-wake-pass.json", "pass"],
  ["voice-wake-threshold-fail.json", "wake_threshold_not_crossed"],
  ["voice-wake-event-not-routed.json", "wake_event_not_emitted"],
  ["missing-permission.json", "missing_permission"],
  ["missing-model.json", "onnx_model_not_ready"],
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
