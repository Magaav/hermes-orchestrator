"use strict";

function numberValue(...values) {
  for (const value of values) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return 0;
}

function latestWindow(status) {
  return status.latest_inference_window && typeof status.latest_inference_window === "object"
    ? status.latest_inference_window
    : {};
}

function metricsFrom(status) {
  return status.confidence_metrics && typeof status.confidence_metrics === "object"
    ? status.confidence_metrics
    : {};
}

const FAILURE_CLASSIFICATION_BY_STAGE = {
  service_alive: "foreground_service_not_started",
  audio_record_started: "audio_record_start_failed",
  audio_capture_alive: "audio_record_start_failed",
  onnx_model_ready: "onnx_model_load_failed",
  inference_running: "inference_not_running",
  wake_confidence_observed: "wake_confidence_missing",
  wake_threshold_crossed: "wake_threshold_not_crossed",
  wake_event_emitted: "wake_event_not_emitted",
  command_capture_ui_started: "command_capture_ui_not_started",
};

const NEXT_ACTION_BY_CLASSIFICATION = {
  pass: "Proceed to the next proof stage.",
  bridge_update_required: "Rebuild and reinstall the Windows shell before running hot-operation proofs.",
  adb_missing: "Install Android platform-tools and ensure adb is on PATH for the Windows app.",
  android_device_missing: "Connect one authorized Android device and accept the adb prompt.",
  android_app_missing: "Install the known-good WASM Agent Android APK before running wake proof.",
  missing_permission: "Grant RECORD_AUDIO to com.colmeio.wasmagent, then rerun the proof.",
  record_audio_permission_missing: "Grant RECORD_AUDIO to com.colmeio.wasmagent, then rerun the proof.",
  foreground_service_not_started: "Inspect the Android foreground service start path and notification requirements.",
  service_command_not_received: "Inspect the activity debug intent and service command delivery path.",
  diagnostics_status_missing: "Collect native diagnostics and logcat; voice-wake.json was not available.",
  audio_capture_not_started: "Open Hermes wake proof mode and verify the foreground service starts recording.",
  audio_record_init_failed: "Inspect AudioRecord buffer, source, and microphone availability on the Android device.",
  audio_record_start_failed: "Inspect AudioRecord startRecording failure details in voice-wake.json.",
  onnx_model_missing: "Install files/voice/hermes.onnx before running wake proof.",
  onnx_model_load_failed: "Inspect ONNX Runtime/model load diagnostics in voice-wake.json.",
  onnx_model_not_ready: "Install or verify files/voice/hermes.onnx and its expected model SHA.",
  inference_not_running: "Check Android voice wake service logs and ONNX runtime initialization.",
  wake_confidence_missing: "Collect debug artifacts; inference ran without confidence telemetry.",
  wake_threshold_not_crossed: "Speak the wake phrase near the phone or tune the threshold/model.",
  wake_event_not_emitted: "Inspect Android wake event routing from detector to UI command capture.",
  command_capture_ui_not_started: "Verify the command capture screen starts after wake detection.",
  hermes_wake_timeout_before_phase: "Inspect bridge logs; the wake proof timed out before reporting progress.",
  diagnostics_missing: "Collect native diagnostics and logcat; voice-wake.json was not available.",
  unknown_failure: "Inspect result artifacts and bridge logs.",
};

function nextActionFor(classification) {
  if (String(classification || "").startsWith("hermes_wake_timeout_after_")) {
    return "Inspect the reported lastPhase and rerun with device logs if the Android proof is still waiting.";
  }
  return NEXT_ACTION_BY_CLASSIFICATION[classification] || NEXT_ACTION_BY_CLASSIFICATION.unknown_failure;
}

function markPhase(context, phase, details = {}) {
  if (context && typeof context.markPhase === "function") {
    context.markPhase(phase, details);
  }
}

function modelReady(status) {
  return Boolean(status.onnx_runtime_available && status.wake_engine_ready && status.personalized_model_exists && status.model_sha_match);
}

function normalizeFailureClassification(status, stable, firstMissing) {
  if (stable) return "pass";
  if (!status || !Object.keys(status).length) return "diagnostics_status_missing";
  const reason = String(status.failure_reason || status.disabled_reason || "").trim();
  if (reason && NEXT_ACTION_BY_CLASSIFICATION[reason]) return reason;
  if (status.permission_record_audio === false) return "record_audio_permission_missing";
  if (status.status_source !== "live_service") return "diagnostics_status_missing";
  if (status.proof_session_active !== true) return "service_command_not_received";
  if (!(status.foreground_service_started || status.foreground_service_running || status.service_running)) return "foreground_service_not_started";
  if (status.audio_record_error) return status.audio_record_started ? "audio_record_start_failed" : "audio_record_init_failed";
  if (status.personalized_model_exists === false || status.model_exists === false || status.wake_model_exists === false) return "onnx_model_missing";
  if (status.onnx_runtime_available === false || status.wake_engine_ready === false) return "onnx_model_load_failed";
  if (status.model_sha_match === false) {
    return "onnx_model_load_failed";
  }
  return FAILURE_CLASSIFICATION_BY_STAGE[firstMissing?.[0]] || "unknown_failure";
}

function classify(status) {
  const metrics = metricsFrom(status);
  const window = latestWindow(status);
  const confidence = numberValue(status.last_wake_confidence, metrics.last_confidence, window.confidence, null);
  const maxConfidence = numberValue(status.max_observed_confidence, metrics.max_confidence, window.max_confidence, confidence);
  const wakeThreshold = numberValue(status.wake_threshold, status.threshold, metrics.threshold, window.threshold, 0.58);
  const inferenceCount = numberValue(status.inference_count, metrics.inference_count, window.inference_count, 0);
  const wakeDetectedCount = numberValue(status.wake_detection_count, window.detection_count, status.last_wake_at ? 1 : 0);
  const stages = {
    service_alive: Boolean(status.status_source === "live_service" && status.proof_session_active && (status.foreground_service_started || status.foreground_service_running || status.service_running)),
    audio_record_started: Boolean(status.permission_record_audio && status.audio_record_started),
    audio_capture_alive: Boolean(status.permission_record_audio && status.audio_capture_alive !== false && status.audio_record_started && numberValue(status.audio_read_calls, 0) > 0),
    onnx_model_ready: Boolean(status.onnx_model_ready || (status.onnx_runtime_available && status.wake_engine_ready && status.personalized_model_exists && status.model_sha_match)),
    inference_running: Boolean(status.inference_running || inferenceCount > 0),
    wake_confidence_observed: Boolean(status.wake_confidence_observed || inferenceCount > 0 || maxConfidence > 0),
    wake_threshold_crossed: Boolean(status.threshold_crossed || status.last_inference_threshold_crossed || metrics.threshold_crossed || window.threshold_crossed || maxConfidence >= wakeThreshold),
    wake_event_emitted: Boolean(status.wake_detected_event_emitted || wakeDetectedCount > 0),
    command_capture_ui_started: Boolean(status.command_capture_started || numberValue(status.command_capture_started_at, 0) > 0 || ["capturing", "transcribing", "sent"].includes(String(status.state || "").toLowerCase())),
  };
  const requiredStages = {
    service_alive: stages.service_alive,
    audio_record_started: stages.audio_record_started,
    audio_capture_alive: stages.audio_capture_alive,
    onnx_model_ready: stages.onnx_model_ready,
    inference_running: stages.inference_running,
  };
  const stable = Object.values(requiredStages).every(Boolean);
  const firstMissing = Object.entries(requiredStages).find(([, passed]) => !passed);
  const failureClassification = normalizeFailureClassification(status, stable, firstMissing);
  return {
    stable,
    operation: "run_android_hermes_wake_proof",
    source: "hot_operation",
    stages,
    metrics: {
      confidence: Number.isFinite(confidence) && confidence > 0 ? confidence : null,
      max_confidence: Number.isFinite(maxConfidence) && maxConfidence > 0 ? maxConfidence : null,
      wake_threshold: wakeThreshold,
      wake_detected_count: wakeDetectedCount,
      inference_count: inferenceCount,
    },
    failureClassification,
    failure_classification: failureClassification,
    nextAction: nextActionFor(failureClassification),
  };
}

async function run(context) {
  const args = context.args || {};
  const packageName = String(args.packageName || args.package_name || "com.colmeio.wasmagent");
  if (packageName !== "com.colmeio.wasmagent") {
    return { ok: false, stable: false, status: "invalid_package", failureClassification: "unknown_failure", failure_classification: "unknown_failure", nextAction: nextActionFor("unknown_failure") };
  }
  if (context.dryRun || args.dryRun || args.dry_run) {
    const device = await context.adb.findAuthorizedDevice();
    const classification = device.status === "one_authorized_device" ? "pass" : "android_device_missing";
    return {
      ok: classification === "pass",
      stable: classification === "pass",
      operation: "run_android_hermes_wake_proof",
      source: "hot_operation",
      status: classification === "pass" ? "dry_run_passed" : device.status,
      devices: device,
      dryRun: true,
      failureClassification: classification,
      failure_classification: classification,
      nextAction: nextActionFor(classification),
    };
  }
  const device = await context.adb.findAuthorizedDevice();
  if (device.status !== "one_authorized_device") {
    return { ok: false, stable: false, status: device.status, devices: device, failureClassification: "android_device_missing", failure_classification: "android_device_missing", nextAction: nextActionFor("android_device_missing") };
  }
  markPhase(context, "adb_ready", { serial: device.serial || "" });
  const waitMs = Math.max(5000, Math.min(Number(args.waitMs || args.wait_ms || args.timeoutMs || 30000), 120000));
  const rawWakeThreshold = numberValue(args.wakeThreshold, args.wake_threshold, args.threshold, 0.58);
  const wakeThreshold = Math.max(0.05, Math.min(Number.isFinite(rawWakeThreshold) ? rawWakeThreshold : 0.58, 0.99));
  const serial = device.serial || "";
  await context.adb.shell(serial, ["input", "keyevent", "KEYCODE_WAKEUP"], { timeoutMs: 5000, maxBuffer: 64 * 1024 });
  await context.adb.launchIntent(serial, [
    "-W",
    "-n",
    `${packageName}/.MainActivity`,
    "--es",
    "debug_screen",
    String(args.debugScreen || args.debug_screen || "hermes-wake-proof"),
    "--es",
    "native_screen",
    String(args.nativeScreen || args.native_screen || "hermes-wake-proof"),
  ], { timeoutMs: 15000, maxBuffer: 512 * 1024 });
  markPhase(context, "app_launched", { packageName });
  const serviceStart = await context.adb.shell(serial, [
    "am",
    "start-foreground-service",
    "-n",
    `${packageName}/.HermesVoiceWakeService`,
    "-a",
    "com.colmeio.wasmagent.voice.START",
    "--ez",
    "proof_session",
    "true",
    "--ef",
    "wake_threshold",
    String(wakeThreshold),
  ], { timeoutMs: 10000, maxBuffer: 256 * 1024 });
  markPhase(context, "service_start_requested", {
    packageName,
    source: "activity_debug_screen_and_foreground_service",
    wakeThreshold,
    exitCode: serviceStart.exitCode,
  });
  context.logger.info("hermes_wake_proof_listening", { waitMs });
  markPhase(context, "listening", { waitMs });
  await new Promise((resolve) => setTimeout(resolve, waitMs));
  await new Promise((resolve) => setTimeout(resolve, 1000));
  const statusCommand = await context.adb.shell(serial, ["run-as", packageName, "cat", "files/native-diagnostics/voice-wake.json"], { timeoutMs: 12000, maxBuffer: 4 * 1024 * 1024 });
  let status = {};
  try {
    status = JSON.parse(String(statusCommand.stdout || "{}"));
  } catch {
    status = {};
  }
  let statusSource = "run-as";
  const runAsText = `${statusCommand.stdout || ""}\n${statusCommand.stderr || ""}\n${statusCommand.error || ""}`;
  const statusIsEmpty = !status || !Object.keys(status).length;
  if (statusIsEmpty || !status.schema || /run-as:\s*package not debuggable/i.test(runAsText)) {
    const resolved = await context.diagnostics.resolveBestVoiceWakeDiagnostics();
    if (resolved && resolved.data && Object.keys(resolved.data).length) {
      status = resolved.data || {};
      statusSource = resolved.source || "diagnostics";
    } else {
      const backend = await context.diagnostics.readLatestServerDiagnostics();
      if (backend.ok) {
        status = backend.payload || {};
        statusSource = "backend-upload";
      }
    }
  }
  if (status.status_source === "live_service" && (status.foreground_service_started || status.foreground_service_running || status.service_running)) {
    markPhase(context, "foreground_service_seen");
  }
  if (status.permission_record_audio && status.audio_record_started && numberValue(status.audio_read_calls, 0) > 0) {
    markPhase(context, "audio_record_seen", { audioReadCalls: numberValue(status.audio_read_calls, 0) });
  }
  if (modelReady(status)) {
    markPhase(context, "model_status_seen", { modelShaMatch: status.model_sha_match === true });
  }
  const classification = classify(status);
  const result = {
    ok: classification.stable,
    status: classification.stable ? "hermes_wake_proof_passed" : "hermes_wake_proof_incomplete",
    ...classification,
    packageName,
    waitMs,
    requestedWakeThreshold: wakeThreshold,
    statusSource,
    lastPhase: context.progress?.lastPhase || "",
    phaseHistory: context.progress?.phases || [],
    devices: device,
    voiceWakeStatus: status,
  };
  await context.diagnostics.uploadResult(result);
  context.fs.writeJsonSafe("latest-hermes-wake-proof.json", result);
  markPhase(context, "result_written");
  result.lastPhase = context.progress?.lastPhase || result.lastPhase;
  result.phaseHistory = context.progress?.phases || result.phaseHistory;
  return result;
}

module.exports = { run, classify };
