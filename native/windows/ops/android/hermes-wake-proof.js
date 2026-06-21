"use strict";

function numberValue(...values) {
  for (const value of values) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return 0;
}

function finiteNumberOrNull(...values) {
  for (const value of values) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function boundedIntOrNull(min, max, ...values) {
  const value = finiteNumberOrNull(...values);
  if (value === null) return null;
  return Math.max(min, Math.min(Math.round(value), max));
}

function boundedFloatOrNull(min, max, ...values) {
  const value = finiteNumberOrNull(...values);
  if (value === null) return null;
  return Math.max(min, Math.min(value, max));
}

function servicePolicyExtras(args) {
  const extras = [];
  const phrase = String(args.wakePhrase || args.wake_phrase || "").trim().toLowerCase();
  if (phrase) extras.push("--es", "wakePhrase", phrase.slice(0, 40));
  const confirmationFrames = boundedIntOrNull(1, 5, args.wakeConfirmationFrames, args.wake_confirmation_frames, args.wakeVerificationFrames);
  if (confirmationFrames !== null) extras.push("--ei", "wakeConfirmationFrames", String(confirmationFrames));
  const confirmationWindowMs = boundedIntOrNull(150, 2000, args.wakeConfirmationWindowMs, args.wake_confirmation_window_ms, args.wakeVerificationWindowMs);
  if (confirmationWindowMs !== null) extras.push("--el", "wakeConfirmationWindowMs", String(confirmationWindowMs));
  const cooldownMs = boundedIntOrNull(500, 60000, args.wakeCooldownMs, args.wake_cooldown_ms);
  if (cooldownMs !== null) extras.push("--el", "wakeCooldownMs", String(cooldownMs));
  const vadRms = boundedFloatOrNull(0.001, 0.2, args.vadRmsThreshold, args.vad_rms_threshold);
  if (vadRms !== null) extras.push("--ef", "vadRmsThreshold", String(vadRms));
  const vadPeak = boundedIntOrNull(100, 30000, args.vadPeakThreshold, args.vad_peak_threshold);
  if (vadPeak !== null) extras.push("--ei", "vadPeakThreshold", String(vadPeak));
  return extras;
}

function booleanValue(value, fallback) {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (["1", "true", "yes", "on"].includes(normalized)) return true;
    if (["0", "false", "no", "off"].includes(normalized)) return false;
  }
  return fallback;
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

function modelSourceFrom(status) {
  return String(status.model_source || status.modelSource || status.wake_model_source || status.wakeProvider || status.wake_provider || "").toLowerCase();
}

function openWakeWordBundleReady(status) {
  const source = modelSourceFrom(status);
  return Boolean(
    (source === "openwakeword_bundle" || source.includes("openwakeword"))
      && status.onnx_runtime_available !== false
      && (status.wake_engine_ready === true || status.onnx_model_ready === true)
      && status.openwakeword_bundle_exists !== false
  );
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
  service_start_rejected: "Use the app/native-control policy path; Android rejected direct ADB service start for the non-exported wake service.",
  production_policy_not_applied: "Use apply_wake_word_policy or an exported app-mediated control path; production listener policy did not reach the Android service.",
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
  return Boolean(
    status.onnx_model_ready === true
      || openWakeWordBundleReady(status)
      || (status.onnx_runtime_available && status.wake_engine_ready && status.personalized_model_exists && status.model_sha_match)
  );
}

function normalizeFailureClassification(status, stable, firstMissing) {
  if (!status || !Object.keys(status).length) return "diagnostics_status_missing";
  if (numberValue(status.service_start_exit_code, 0) !== 0) return "service_start_rejected";
  if (status.requested_proof_session === false && status.proof_session_active === true) return "production_policy_not_applied";
  if (stable) return "pass";
  const reason = String(status.failure_reason || status.disabled_reason || "").trim();
  if (reason && NEXT_ACTION_BY_CLASSIFICATION[reason]) return reason;
  if (status.permission_record_audio === false) return "record_audio_permission_missing";
  const serviceVisible = Boolean(status.foreground_service_started || status.foreground_service_running || status.foreground_service_active || status.service_running || status.voice_service_running);
  if (!serviceVisible && status.status_source && status.status_source !== "live_service" && status.status_source !== "lightweight_no_model_load") return "diagnostics_status_missing";
  if (status.proof_session_active === false && !serviceVisible) return "service_command_not_received";
  if (!serviceVisible) return "foreground_service_not_started";
  if (status.audio_record_error) return status.audio_record_started ? "audio_record_start_failed" : "audio_record_init_failed";
  if (status.personalized_model_exists === false || status.model_exists === false || status.wake_model_exists === false) return "onnx_model_missing";
  if (status.onnx_runtime_available === false || status.wake_engine_ready === false) return "onnx_model_load_failed";
  if (status.model_sha_match === false && !openWakeWordBundleReady(status)) {
    return "onnx_model_load_failed";
  }
  return FAILURE_CLASSIFICATION_BY_STAGE[firstMissing?.[0]] || "unknown_failure";
}

function classify(status) {
  const metrics = metricsFrom(status);
  const window = latestWindow(status);
  const confidence = numberValue(status.last_wake_confidence, status.last_confidence, metrics.last_confidence, window.confidence, null);
  const maxConfidence = numberValue(status.max_observed_confidence, status.max_confidence_since_start, status.max_confidence, metrics.max_confidence, window.max_confidence, confidence);
  const wakeThreshold = numberValue(status.wake_threshold, status.threshold, metrics.threshold, window.threshold, 0.58);
  const inferenceCount = numberValue(status.inference_count, metrics.inference_count, window.inference_count, 0);
  const wakeDetectedCount = numberValue(status.wake_detection_count, status.wake_hit_count, window.detection_count, status.last_wake_at ? 1 : 0);
  const serviceAlive = Boolean((status.status_source === "live_service" || status.status_source === "lightweight_no_model_load" || !status.status_source) && (status.foreground_service_started || status.foreground_service_running || status.foreground_service_active || status.service_running || status.voice_service_running));
  const audioStarted = Boolean(status.permission_record_audio !== false && (status.audio_record_started || status.audio_capture_alive || numberValue(status.audio_read_calls, 0) > 0 || inferenceCount > 0));
  const stages = {
    service_alive: serviceAlive,
    audio_record_started: audioStarted,
    audio_capture_alive: Boolean(status.permission_record_audio !== false && status.audio_capture_alive !== false && audioStarted),
    onnx_model_ready: modelReady(status),
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
  const runtimeStable = Object.values(requiredStages).every(Boolean);
  const firstMissing = Object.entries(requiredStages).find(([, passed]) => !passed);
  const failureClassification = normalizeFailureClassification(status, runtimeStable, firstMissing);
  const stable = failureClassification === "pass";
  return {
    stable,
    runtimeStable,
    runtime_stable: runtimeStable,
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
  const wakeThreshold = Math.max(0.05, Math.min(Number.isFinite(rawWakeThreshold) ? rawWakeThreshold : 0.58, 0.999));
  const policyExtras = servicePolicyExtras(args);
  const proofSession = booleanValue(args.proofSession ?? args.proof_session, true);
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
  const serviceStartArgs = [
    "am",
    "start-foreground-service",
    "-n",
    `${packageName}/.HermesVoiceWakeService`,
    "-a",
    "com.colmeio.wasmagent.voice.START",
    "--ez",
    "proof_session",
    String(proofSession),
    "--ef",
    "wake_threshold",
    String(wakeThreshold),
    ...policyExtras,
  ];
  let serviceStart = await context.adb.shell(serial, serviceStartArgs, { timeoutMs: 10000, maxBuffer: 256 * 1024 });
  let serviceStartMethod = "start-foreground-service";
  if (serviceStart.exitCode !== 0) {
    const fallbackArgs = [...serviceStartArgs];
    fallbackArgs[1] = "startservice";
    const fallback = await context.adb.shell(serial, fallbackArgs, { timeoutMs: 10000, maxBuffer: 256 * 1024 });
    if (fallback.exitCode === 0 || serviceStart.exitCode !== 0) {
      serviceStart = fallback;
      serviceStartMethod = "startservice";
    }
  }
  markPhase(context, "service_start_requested", {
    packageName,
    source: "activity_debug_screen_and_foreground_service",
    method: serviceStartMethod,
    wakeThreshold,
    policyExtras,
    proofSession,
    exitCode: serviceStart.exitCode,
    stdout: String(serviceStart.stdout || "").slice(0, 1200),
    stderr: String(serviceStart.stderr || serviceStart.error || "").slice(0, 1200),
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
  status.service_start_exit_code = Number(serviceStart.exitCode || 0);
  status.service_start_method = serviceStartMethod;
  status.service_start_stdout = String(serviceStart.stdout || "").slice(0, 1200);
  status.service_start_stderr = String(serviceStart.stderr || serviceStart.error || "").slice(0, 1200);
  status.requested_proof_session = proofSession;
  status.requested_wake_threshold = wakeThreshold;
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
