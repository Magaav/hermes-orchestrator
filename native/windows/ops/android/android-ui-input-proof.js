"use strict";

function numberInRange(min, max, value, fallback) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, Math.round(parsed)));
}

function launchExtras(args) {
  const extras = [];
  const stringKeys = [
    "voiceWakeCommand",
    "voice_wake_command",
    "wakePhrase",
    "wake_phrase",
    "tuningSessionId",
    "tuning_session_id",
    "transcriptEngine",
    "transcript_engine",
    "transcriptAttemptPlan",
    "transcript_attempt_plan",
    "bundleUrl",
    "bundle_url",
  ];
  const floatKeys = [
    "wakeThreshold",
    "wake_threshold",
    "vadRmsThreshold",
    "vad_rms_threshold",
  ];
  const intKeys = [
    "wakeConfirmationFrames",
    "wake_confirmation_frames",
    "wakeVerificationFrames",
    "wakeCooldownMs",
    "wake_cooldown_ms",
    "wakeConfirmationWindowMs",
    "wake_confirmation_window_ms",
    "wakeVerificationWindowMs",
    "transcriptTimeoutMs",
    "transcript_timeout_ms",
    "transcriptMinLengthMs",
    "transcript_min_length_ms",
    "transcriptCompleteSilenceMs",
    "transcript_complete_silence_ms",
    "transcriptPossibleSilenceMs",
    "transcript_possible_silence_ms",
    "vadPeakThreshold",
    "vad_peak_threshold",
  ];
  const boolKeys = [
    "transcriptAcceptPartial",
    "transcript_accept_partial",
  ];
  for (const key of stringKeys) {
    const value = String(args[key] ?? "").trim();
    if (value) extras.push("--es", key, value.slice(0, 160));
  }
  for (const key of floatKeys) {
    const value = Number(args[key]);
    if (Number.isFinite(value)) extras.push("--es", key, String(value));
  }
  for (const key of intKeys) {
    const value = Number(args[key]);
    if (Number.isFinite(value)) extras.push("--el", key, String(Math.round(value)));
  }
  for (const key of boolKeys) {
    if (args[key] === true || args[key] === "true" || args[key] === 1 || args[key] === "1") extras.push("--ez", key, "true");
    if (args[key] === false || args[key] === "false" || args[key] === 0 || args[key] === "0") extras.push("--ez", key, "false");
  }
  return extras;
}

function serviceExtras(args) {
  return launchExtras(args).filter((item, index, all) => {
    const previous = all[index - 1] || "";
    return item !== "voiceWakeCommand" && item !== "voice_wake_command" && previous !== "--es";
  });
}

function looseJsonStatus(text) {
  const raw = String(text || "");
  const nestedObject = (key) => {
    const keyIndex = raw.indexOf(`"${key}"`);
    if (keyIndex < 0) return null;
    const start = raw.indexOf("{", keyIndex);
    if (start < 0) return null;
    let depth = 0;
    let inString = false;
    let escaped = false;
    for (let index = start; index < raw.length; index += 1) {
      const char = raw[index];
      if (escaped) {
        escaped = false;
        continue;
      }
      if (char === "\\") {
        escaped = true;
        continue;
      }
      if (char === "\"") {
        inString = !inString;
        continue;
      }
      if (inString) continue;
      if (char === "{") depth += 1;
      if (char === "}") {
        depth -= 1;
        if (depth === 0) return raw.slice(start, index + 1);
      }
    }
    return null;
  };
  const getString = (key) => {
    const match = raw.match(new RegExp(`"${key}"\\s*:\\s*"([^"]*)"`, "i"));
    return match ? match[1].replace(/\\\//g, "/") : "";
  };
  const getBool = (key) => {
    const match = raw.match(new RegExp(`"${key}"\\s*:\\s*(true|false)`, "i"));
    return match ? match[1].toLowerCase() === "true" : false;
  };
  const getNumber = (key) => {
    const match = raw.match(new RegExp(`"${key}"\\s*:\\s*(-?\\d+(?:\\.\\d+)?(?:[eE][+-]?\\d+)?)`, "i"));
    const value = match ? Number(match[1]) : 0;
    return Number.isFinite(value) ? value : 0;
  };
  const schema = getString("schema");
  if (!schema) return {};
  const parseNested = (key) => {
    const objectText = nestedObject(key);
    if (!objectText) return null;
    try {
      return JSON.parse(objectText);
    } catch {
      return null;
    }
  };
  const control = parseNested("voice_wake_control");
  const lifecycle = parseNested("voice_wake_lifecycle");
  return {
    schema,
    build_id: getString("build_id"),
    origin: getString("origin"),
    voice_wake_lifecycle: lifecycle,
    voice_wake_lifecycle_stage: getString("voice_wake_lifecycle_stage") || (lifecycle ? lifecycle.stage : ""),
    voice_wake_lifecycle_action: getString("voice_wake_lifecycle_action") || (lifecycle ? lifecycle.action : ""),
    voice_wake_lifecycle_running: getBool("voice_wake_lifecycle_running"),
    voice_wake_lifecycle_worker_alive: getBool("voice_wake_lifecycle_worker_alive"),
    voice_wake_lifecycle_audio_read_calls: getNumber("voice_wake_lifecycle_audio_read_calls"),
    voice_wake_lifecycle_audio_samples_read: getNumber("voice_wake_lifecycle_audio_samples_read"),
    voice_wake_lifecycle_inference_count: getNumber("voice_wake_lifecycle_inference_count"),
    voice_wake_lifecycle_last_listen_exit_reason: getString("voice_wake_lifecycle_last_listen_exit_reason"),
    voice_wake_lifecycle_last_listen_exit_detail: getString("voice_wake_lifecycle_last_listen_exit_detail"),
    voice_wake_lifecycle_last_failure_reason: getString("voice_wake_lifecycle_last_failure_reason"),
    voice_wake_lifecycle_last_audio_record_error: getString("voice_wake_lifecycle_last_audio_record_error"),
    voice_wake_control: control,
    voice_wake_control_command: getString("voice_wake_control_command") || (control ? control.command : ""),
    voice_wake_control_action: getString("voice_wake_control_action") || (control ? control.action : ""),
    voice_wake_control_ok: getBool("voice_wake_control_ok") || (control ? control.ok : false),
    voice_wake_control_stage: getString("voice_wake_control_stage") || (control ? control.stage : ""),
    voice_wake_control_error: getString("voice_wake_control_error") || (control ? control.error : ""),
    status_source: getString("status_source"),
    service_alive: getBool("service_alive"),
    audio_record_started: getBool("audio_record_started"),
    audio_capture_alive: getBool("audio_capture_alive"),
    audio_source: getString("audio_source"),
    audio_source_id: getNumber("audio_source_id"),
    audio_source_restart_count: getNumber("audio_source_restart_count"),
    audio_read_calls: getNumber("audio_read_calls"),
    audio_samples_read: getNumber("audio_samples_read"),
    audio_record_error: getString("audio_record_error"),
    inference_running: getBool("inference_running"),
    inference_count: getNumber("inference_count"),
    last_confidence: getNumber("last_confidence"),
    max_observed_confidence: getNumber("max_observed_confidence"),
    wake_threshold: getNumber("wake_threshold"),
    wake_confirmation_frames: getNumber("wake_confirmation_frames"),
    wake_confirmation_window_ms: getNumber("wake_confirmation_window_ms"),
    wake_cooldown_ms: getNumber("wake_cooldown_ms"),
    vad_rms_threshold: getNumber("vad_rms_threshold"),
    vad_peak_threshold: getNumber("vad_peak_threshold"),
    vad_pass_count: getNumber("vad_pass_count"),
    vad_reject_count: getNumber("vad_reject_count"),
    last_vad_speech: getBool("last_vad_speech"),
    wake_detection_count: getNumber("wake_detection_count"),
    raw_wake_detection_count: getNumber("raw_wake_detection_count"),
    rejection_reason: getString("rejection_reason"),
    tuning_session_id: getString("tuning_session_id"),
  };
}

async function run(context) {
  const args = context.args || {};
  const action = String(args.action || args.input || "tap").trim().toLowerCase();
  const device = await context.adb.findAuthorizedDevice();
  if (device.status !== "one_authorized_device") {
    return {
      ok: false,
      stable: false,
      operation: "run_android_ui_input_proof",
      status: device.status,
      devices: device,
      failureClassification: "android_device_missing",
    };
  }
  const serial = device.serial || "";
  context.markPhase("adb_ready", { serial, action });
  await context.adb.shell(serial, ["input", "keyevent", "KEYCODE_WAKEUP"], { timeoutMs: 5000, maxBuffer: 64 * 1024 });
  const screenReady = [];
  for (const commandArgs of [
    ["wm", "dismiss-keyguard"],
  ]) {
    const attempt = await context.adb.shell(serial, commandArgs, { timeoutMs: 5000, maxBuffer: 64 * 1024 });
    screenReady.push({
      commandArgs,
      exitCode: attempt.exitCode,
      ok: Number(attempt.exitCode || 0) === 0,
      stdout: String(attempt.stdout || "").slice(0, 400),
      stderr: String(attempt.stderr || attempt.error || "").slice(0, 400),
      elapsedMs: attempt.elapsedMs ?? null,
    });
  }
  context.markPhase("screen_ready", { attempts: screenReady.map((item) => ({ commandArgs: item.commandArgs, ok: item.ok })) });
  if (action === "install_apk") {
    const apk = await context.release.resolveAndroidApk();
    if (!apk.ok) {
      return {
        ok: false,
        stable: false,
        operation: "run_android_ui_input_proof",
        action,
        devices: device,
        apk,
        failureClassification: apk.error || "android_apk_resolve_failed",
      };
    }
    context.markPhase("apk_resolved", { source: apk.source || "", path: apk.path || "", buildId: apk.buildId || "", sha256: apk.sha256 || "" });
    const install = await context.adb.install(serial, apk.path, { timeoutMs: 180000, maxBuffer: 1024 * 1024 });
    const ok = Number(install.exitCode || 0) === 0;
    const result = {
      ok,
      stable: ok,
      operation: "run_android_ui_input_proof",
      action,
      apk,
      install: {
        exitCode: install.exitCode,
        stdout: String(install.stdout || "").slice(0, 4000),
        stderr: String(install.stderr || install.error || "").slice(0, 4000),
        elapsedMs: install.elapsedMs ?? null,
      },
      devices: device,
      screenReady,
      failureClassification: ok ? "pass" : "adb_install_failed",
      lastPhase: context.progress?.lastPhase || "",
      phaseHistory: context.progress?.phases || [],
    };
    context.fs.writeJsonSafe("latest-android-ui-input-proof.json", result);
    return result;
  }
  if (action === "launch") {
    const packageName = String(args.packageName || args.package_name || "com.colmeio.wasmagent");
    const method = String(args.method || "activity").trim().toLowerCase();
    const componentName = String(args.componentName || args.component_name || `${packageName}/.MainActivity`).trim();
    const dataUri = String(args.dataUri || args.data_uri || args.url || "").trim();
    const intentAction = String(args.intentAction || args.intent_action || (dataUri ? "android.intent.action.VIEW" : "android.intent.action.MAIN")).trim();
    const categories = Array.isArray(args.categories)
      ? args.categories.map((item) => String(item || "").trim()).filter(Boolean)
      : dataUri
        ? ["android.intent.category.DEFAULT", "android.intent.category.BROWSABLE"]
        : ["android.intent.category.LAUNCHER"];
    const launchArgs = [
      "-W",
      ...(args.stopFirst || args.stop_first ? ["-S"] : []),
      "-a",
      intentAction,
      ...categories.flatMap((category) => ["-c", category]),
      "-n",
      componentName,
      ...launchExtras(args),
      ...(dataUri ? ["-d", dataUri] : []),
    ];
    const launch = method === "monkey"
      ? await context.adb.shell(serial, ["monkey", "-p", packageName, "-c", "android.intent.category.LAUNCHER", "1"], { timeoutMs: 15000, maxBuffer: 512 * 1024 })
      : await context.adb.launchIntent(serial, launchArgs, { timeoutMs: 15000, maxBuffer: 512 * 1024 });
    const ok = Number(launch.exitCode || 0) === 0;
    return {
      ok,
      stable: ok,
      operation: "run_android_ui_input_proof",
      action,
      method,
      componentName,
      dataUri,
      intentAction,
      categories,
      launch: {
        exitCode: launch.exitCode,
        stdout: String(launch.stdout || "").slice(0, 3000),
        stderr: String(launch.stderr || launch.error || "").slice(0, 3000),
        elapsedMs: launch.elapsedMs ?? null,
      },
      devices: device,
      screenReady,
      failureClassification: ok ? "pass" : "adb_launch_failed",
      lastPhase: context.progress?.lastPhase || "",
      phaseHistory: context.progress?.phases || [],
    };
  }
  if (action === "force_stop") {
    const packageName = String(args.packageName || args.package_name || "com.android.chrome");
    const stopped = await context.adb.shell(serial, ["am", "force-stop", packageName], { timeoutMs: 10000, maxBuffer: 128 * 1024 });
    const ok = Number(stopped.exitCode || 0) === 0;
    return {
      ok,
      stable: ok,
      operation: "run_android_ui_input_proof",
      action,
      packageName,
      stopped: {
        exitCode: stopped.exitCode,
        stdout: String(stopped.stdout || "").slice(0, 2000),
        stderr: String(stopped.stderr || stopped.error || "").slice(0, 2000),
        elapsedMs: stopped.elapsedMs ?? null,
      },
      devices: device,
      screenReady,
      failureClassification: ok ? "pass" : "adb_force_stop_failed",
      lastPhase: context.progress?.lastPhase || "",
      phaseHistory: context.progress?.phases || [],
    };
  }
  if (action === "keyevent") {
    const key = String(args.key || args.keyCode || args.key_code || "KEYCODE_HOME").trim() || "KEYCODE_HOME";
    const input = await context.adb.shell(serial, ["input", "keyevent", key], { timeoutMs: 10000, maxBuffer: 128 * 1024 });
    const ok = Number(input.exitCode || 0) === 0;
    return {
      ok,
      stable: ok,
      operation: "run_android_ui_input_proof",
      action,
      key,
      input: {
        exitCode: input.exitCode,
        stdout: String(input.stdout || "").slice(0, 2000),
        stderr: String(input.stderr || input.error || "").slice(0, 2000),
        elapsedMs: input.elapsedMs ?? null,
      },
      devices: device,
      screenReady,
      failureClassification: ok ? "pass" : "adb_keyevent_failed",
      lastPhase: context.progress?.lastPhase || "",
      phaseHistory: context.progress?.phases || [],
    };
  }
  if (action === "adb_shell") {
    const commandArgs = Array.isArray(args.commandArgs)
      ? args.commandArgs.map((item) => String(item)).filter(Boolean).slice(0, 40)
      : String(args.command || "")
        .split(/\s+/)
        .map((item) => item.trim())
        .filter(Boolean)
        .slice(0, 40);
    if (commandArgs.length === 0) {
      return {
        ok: false,
        stable: false,
        operation: "run_android_ui_input_proof",
        action,
        commandArgs,
        devices: device,
        screenReady,
        failureClassification: "adb_shell_command_missing",
        lastPhase: context.progress?.lastPhase || "",
        phaseHistory: context.progress?.phases || [],
      };
    }
    const timeoutMs = numberInRange(1000, 60000, args.timeoutMs ?? args.timeout_ms, 12000);
    const maxBuffer = numberInRange(64 * 1024, 8 * 1024 * 1024, args.maxBuffer ?? args.max_buffer, 1024 * 1024);
    const shell = await context.adb.shell(serial, commandArgs, { timeoutMs, maxBuffer });
    const ok = Number(shell.exitCode || 0) === 0;
    return {
      ok,
      stable: ok,
      operation: "run_android_ui_input_proof",
      action,
      commandArgs,
      shell: {
        exitCode: shell.exitCode,
        stdout: String(shell.stdout || "").slice(0, maxBuffer),
        stderr: String(shell.stderr || shell.error || "").slice(0, 4000),
        elapsedMs: shell.elapsedMs ?? null,
      },
      devices: device,
      screenReady,
      failureClassification: ok ? "pass" : "adb_shell_failed",
      lastPhase: context.progress?.lastPhase || "",
      phaseHistory: context.progress?.phases || [],
    };
  }
  if (action === "adb_write_url") {
    const url = String(args.url || args.sourceUrl || args.source_url || "").trim();
    const dest = String(args.dest || args.destination || "/sdcard/Download/WASM-Agent/openwakeword.zip").trim();
    if (!/^https?:\/\//i.test(url) || !dest.startsWith("/sdcard/")) {
      return {
        ok: false,
        stable: false,
        operation: "run_android_ui_input_proof",
        action,
        url,
        dest,
        devices: device,
        screenReady,
        failureClassification: "adb_write_url_invalid_input",
        lastPhase: context.progress?.lastPhase || "",
        phaseHistory: context.progress?.phases || [],
      };
    }
    const response = await fetch(url);
    if (!response.ok) {
      return {
        ok: false,
        stable: false,
        operation: "run_android_ui_input_proof",
        action,
        url,
        dest,
        status: response.status,
        devices: device,
        screenReady,
        failureClassification: "adb_write_url_download_failed",
        lastPhase: context.progress?.lastPhase || "",
        phaseHistory: context.progress?.phases || [],
      };
    }
    const bytes = Buffer.from(await response.arrayBuffer());
    const b64 = bytes.toString("base64");
    const tmp = `${dest}.b64`;
    const startOffset = numberInRange(0, b64.length, args.startOffset ?? args.start_offset, 0);
    const maxChunks = numberInRange(1, 5000, args.maxChunks ?? args.max_chunks, 80);
    const mkdir = startOffset === 0
      ? await context.adb.shell(serial, ["mkdir", "-p", dest.replace(/\/[^/]+$/, "")], { timeoutMs: 10000, maxBuffer: 128 * 1024 })
      : { exitCode: 0, stderr: "" };
    const clear = startOffset === 0
      ? await context.adb.shell(serial, ["rm", "-f", tmp, dest], { timeoutMs: 10000, maxBuffer: 128 * 1024 })
      : { exitCode: 0, stderr: "" };
    const chunks = [];
    let nextOffset = startOffset;
    for (let index = startOffset; index < b64.length && chunks.length < maxChunks; index += 3000) {
      const chunk = b64.slice(index, index + 3000);
      const append = await context.adb.shell(serial, ["sh", "-c", `echo '${chunk}' >> '${tmp}'`], { timeoutMs: 15000, maxBuffer: 128 * 1024 });
      chunks.push({ index: chunks.length, exitCode: append.exitCode, stderr: String(append.stderr || append.error || "").slice(0, 500) });
      nextOffset = index + chunk.length;
      if (Number(append.exitCode || 0) !== 0) break;
    }
    const complete = nextOffset >= b64.length;
    const decode = complete
      ? await context.adb.shell(serial, ["sh", "-c", `base64 -d '${tmp}' > '${dest}' 2>/dev/null || toybox base64 -d '${tmp}' > '${dest}'; rc=$?; rm -f '${tmp}'; test $rc -eq 0 && ls -l '${dest}'; exit $rc`], { timeoutMs: 60000, maxBuffer: 256 * 1024 })
      : { exitCode: 0, stdout: "", stderr: "" };
    const ok = Number(mkdir.exitCode || 0) === 0 &&
      Number(clear.exitCode || 0) === 0 &&
      chunks.every((item) => Number(item.exitCode || 0) === 0) &&
      Number(decode.exitCode || 0) === 0;
    return {
      ok,
      stable: ok,
      operation: "run_android_ui_input_proof",
      action,
      url,
      dest,
      bytes: bytes.length,
      base64Bytes: b64.length,
      startOffset,
      nextOffset,
      complete,
      chunkCount: chunks.length,
      mkdir: { exitCode: mkdir.exitCode, stderr: String(mkdir.stderr || mkdir.error || "").slice(0, 500) },
      clear: { exitCode: clear.exitCode, stderr: String(clear.stderr || clear.error || "").slice(0, 500) },
      decode: {
        exitCode: decode.exitCode,
        stdout: String(decode.stdout || "").slice(0, 1000),
        stderr: String(decode.stderr || decode.error || "").slice(0, 1000),
      },
      chunkErrors: chunks.filter((item) => Number(item.exitCode || 0) !== 0).slice(0, 5),
      devices: device,
      screenReady,
      failureClassification: ok ? "pass" : "adb_write_url_failed",
      lastPhase: context.progress?.lastPhase || "",
      phaseHistory: context.progress?.phases || [],
    };
  }
  if (action === "delete_wake_snapshot") {
    const packageName = String(args.packageName || args.package_name || "com.colmeio.wasmagent");
    const paths = [
      "/sdcard/Download/WASM-Agent/wake-state-snapshot.json",
      "/storage/emulated/0/Download/WASM-Agent/wake-state-snapshot.json",
      `/sdcard/Android/data/${packageName}/files/native-diagnostics/wake-state-snapshot.json`,
    ];
    const removed = [];
    for (const path of paths) {
      const result = await context.adb.shell(serial, ["rm", "-f", path], { timeoutMs: 10000, maxBuffer: 128 * 1024 });
      removed.push({
        path,
        exitCode: result.exitCode,
        stdout: String(result.stdout || "").slice(0, 500),
        stderr: String(result.stderr || result.error || "").slice(0, 500),
      });
    }
    return {
      ok: true,
      stable: true,
      operation: "run_android_ui_input_proof",
      action,
      removed,
      devices: device,
      screenReady,
      failureClassification: "pass",
      lastPhase: context.progress?.lastPhase || "",
      phaseHistory: context.progress?.phases || [],
    };
  }
  if (action === "voice_wake_service") {
    const packageName = String(args.packageName || args.package_name || "com.colmeio.wasmagent");
    const command = String(args.voiceWakeCommand || args.voice_wake_command || args.command || "start").trim().toLowerCase();
    const serviceAction = command === "stop" || command === "disable"
      ? "com.colmeio.wasmagent.voice.STOP"
      : command === "status" || command === "policy"
        ? "com.colmeio.wasmagent.voice.STATUS"
        : "com.colmeio.wasmagent.voice.START";
    const componentName = String(args.componentName || args.component_name || `${packageName}/.HermesVoiceWakeService`).trim();
    const origin = String(args.origin || "https://wa.colmeio.com").trim() || "https://wa.colmeio.com";
    const serviceArgs = [
      "am",
      "start-foreground-service",
      "-n",
      componentName,
      "-a",
      serviceAction,
      "--es",
      "origin",
      origin,
      ...launchExtras(args),
    ];
    const service = await context.adb.shell(serial, serviceArgs, { timeoutMs: 15000, maxBuffer: 512 * 1024 });
    let fallback = null;
    if (Number(service.exitCode || 0) !== 0) {
      fallback = await context.adb.shell(serial, ["am", "startservice", ...serviceArgs.slice(2)], { timeoutMs: 15000, maxBuffer: 512 * 1024 });
    }
    const ok = Number(service.exitCode || 0) === 0 || Number(fallback?.exitCode || 0) === 0;
    return {
      ok,
      stable: ok,
      operation: "run_android_ui_input_proof",
      action,
      command,
      serviceAction,
      componentName,
      service: {
        exitCode: service.exitCode,
        stdout: String(service.stdout || "").slice(0, 3000),
        stderr: String(service.stderr || service.error || "").slice(0, 3000),
        elapsedMs: service.elapsedMs ?? null,
      },
      fallback: fallback ? {
        exitCode: fallback.exitCode,
        stdout: String(fallback.stdout || "").slice(0, 3000),
        stderr: String(fallback.stderr || fallback.error || "").slice(0, 3000),
        elapsedMs: fallback.elapsedMs ?? null,
      } : null,
      devices: device,
      screenReady,
      failureClassification: ok ? "pass" : "voice_wake_service_failed",
      lastPhase: context.progress?.lastPhase || "",
      phaseHistory: context.progress?.phases || [],
    };
  }
  if (action === "ui_dump") {
    const dump = await context.adb.shell(serial, ["uiautomator", "dump", "/sdcard/wasm-agent-ui.xml"], { timeoutMs: 12000, maxBuffer: 256 * 1024 });
    const read = await context.adb.shell(serial, ["cat", "/sdcard/wasm-agent-ui.xml"], { timeoutMs: 12000, maxBuffer: 2 * 1024 * 1024 });
    const ok = Number(dump.exitCode || 0) === 0 && Number(read.exitCode || 0) === 0;
    return {
      ok,
      stable: ok,
      operation: "run_android_ui_input_proof",
      action,
      dump: {
        exitCode: dump.exitCode,
        stdout: String(dump.stdout || "").slice(0, 2000),
        stderr: String(dump.stderr || dump.error || "").slice(0, 2000),
      },
      uiXml: String(read.stdout || "").slice(0, 200000),
      devices: device,
      screenReady,
      failureClassification: ok ? "pass" : "adb_ui_dump_failed",
      lastPhase: context.progress?.lastPhase || "",
      phaseHistory: context.progress?.phases || [],
    };
  }
  if (action === "gfxinfo") {
    const packageName = String(args.packageName || args.package_name || "com.colmeio.wasmagent");
    const gfx = await context.adb.shell(serial, ["dumpsys", "gfxinfo", packageName, "framestats"], { timeoutMs: 15000, maxBuffer: 4 * 1024 * 1024 });
    const ok = Number(gfx.exitCode || 0) === 0;
    return {
      ok,
      stable: ok,
      operation: "run_android_ui_input_proof",
      action,
      gfxinfo: String(gfx.stdout || "").slice(0, 200000),
      stderr: String(gfx.stderr || gfx.error || "").slice(0, 2000),
      devices: device,
      screenReady,
      failureClassification: ok ? "pass" : "adb_gfxinfo_failed",
      lastPhase: context.progress?.lastPhase || "",
      phaseHistory: context.progress?.phases || [],
    };
  }
  if (action === "gfx_reset") {
    const packageName = String(args.packageName || args.package_name || "com.colmeio.wasmagent");
    const reset = await context.adb.shell(serial, ["dumpsys", "gfxinfo", packageName, "reset"], { timeoutMs: 10000, maxBuffer: 256 * 1024 });
    const ok = Number(reset.exitCode || 0) === 0;
    return {
      ok,
      stable: ok,
      operation: "run_android_ui_input_proof",
      action,
      stdout: String(reset.stdout || "").slice(0, 2000),
      stderr: String(reset.stderr || reset.error || "").slice(0, 2000),
      devices: device,
      screenReady,
      failureClassification: ok ? "pass" : "adb_gfx_reset_failed",
      lastPhase: context.progress?.lastPhase || "",
      phaseHistory: context.progress?.phases || [],
    };
  }
  if (action === "status") {
    const packageName = String(args.packageName || args.package_name || "com.colmeio.wasmagent");
    const activity = await context.adb.shell(serial, ["dumpsys", "activity", "top"], { timeoutMs: 12000, maxBuffer: 2 * 1024 * 1024 });
    const windowDump = await context.adb.shell(serial, ["dumpsys", "window", "windows"], { timeoutMs: 12000, maxBuffer: 2 * 1024 * 1024 });
    const pkg = await context.adb.shell(serial, ["dumpsys", "package", packageName], { timeoutMs: 12000, maxBuffer: 2 * 1024 * 1024 });
    const ok = [activity, windowDump, pkg].every((item) => Number(item.exitCode || 0) === 0);
    return {
      ok,
      stable: ok,
      operation: "run_android_ui_input_proof",
      action,
      activity: String(activity.stdout || "").slice(0, 120000),
      window: String(windowDump.stdout || "").slice(0, 120000),
      package: String(pkg.stdout || "").slice(0, 120000),
      stderr: [activity, windowDump, pkg].map((item) => String(item.stderr || item.error || "")).filter(Boolean).join("\n").slice(0, 4000),
      devices: device,
      screenReady,
      failureClassification: ok ? "pass" : "adb_status_failed",
      lastPhase: context.progress?.lastPhase || "",
      phaseHistory: context.progress?.phases || [],
    };
  }
  if (action === "voice_wake_status") {
    const packageName = String(args.packageName || args.package_name || "com.colmeio.wasmagent");
    const componentName = String(args.componentName || args.component_name || `${packageName}/.shell.NativeShellV2Activity`).trim();
    const refreshSnapshot = args.refreshSnapshot !== false && args.refresh_snapshot !== false;
    let snapshotRefresh = null;
    if (refreshSnapshot) {
      snapshotRefresh = await context.adb.launchIntent(serial, [
        "-W",
        "-a",
        "android.intent.action.MAIN",
        "-c",
        "android.intent.category.LAUNCHER",
        "-n",
        componentName,
        "--es",
        "voiceWakeCommand",
        "dump_state",
      ], { timeoutMs: 15000, maxBuffer: 512 * 1024 });
    }
    const status = await context.adb.shell(serial, ["run-as", packageName, "cat", "files/native-diagnostics/voice-wake.json"], { timeoutMs: 12000, maxBuffer: 4 * 1024 * 1024 });
    const externalCandidates = [
      `/sdcard/Android/data/${packageName}/files/native-diagnostics/wake-state-snapshot.json`,
      "/sdcard/Download/WASM-Agent/wake-state-snapshot.json",
      "/storage/emulated/0/Download/WASM-Agent/wake-state-snapshot.json",
    ];
    let externalStatus = { exitCode: 1, stdout: "", stderr: "" };
    if (Number(status.exitCode || 0) !== 0) {
      for (const candidate of externalCandidates) {
        externalStatus = await context.adb.shell(serial, ["tail", "-c", "1048576", candidate], { timeoutMs: 12000, maxBuffer: 1024 * 1024 });
        if (Number(externalStatus.exitCode || 0) === 0 && String(externalStatus.stdout || "").trim()) {
          externalStatus.path = candidate;
          break;
        }
      }
    }
    let voiceWake = {};
    try {
      const rawStatus = String(status.stdout || externalStatus.stdout || "{}").trim();
      const firstBrace = rawStatus.indexOf("{");
      const lastBrace = rawStatus.lastIndexOf("}");
      voiceWake = JSON.parse(firstBrace >= 0 && lastBrace > firstBrace ? rawStatus.slice(firstBrace, lastBrace + 1) : rawStatus);
    } catch {
      voiceWake = looseJsonStatus(status.stdout || externalStatus.stdout || "");
    }
    const ok = Number(status.exitCode || 0) === 0 && voiceWake && Object.keys(voiceWake).length > 0;
    const externalOk = Number(externalStatus.exitCode || 0) === 0 && voiceWake && Object.keys(voiceWake).length > 0;
    return {
      ok: ok || externalOk,
      stable: ok || externalOk,
      operation: "run_android_ui_input_proof",
      action,
      voiceWake,
      snapshotRefresh: snapshotRefresh ? {
        exitCode: snapshotRefresh.exitCode,
        stdout: String(snapshotRefresh.stdout || "").slice(0, 1200),
        stderr: String(snapshotRefresh.stderr || snapshotRefresh.error || "").slice(0, 1200),
        elapsedMs: snapshotRefresh.elapsedMs ?? null,
      } : null,
      statusSource: ok ? "run-as" : externalOk ? "public_snapshot" : "missing",
      externalPath: externalStatus.path || "",
      stderr: String(status.stderr || status.error || "").slice(0, 2000),
      externalStderr: String(externalStatus.stderr || externalStatus.error || "").slice(0, 2000),
      externalStdoutPreview: String(externalStatus.stdout || "").slice(0, 1600),
      devices: device,
      screenReady,
      failureClassification: ok || externalOk ? "pass" : "voice_wake_status_missing",
      lastPhase: context.progress?.lastPhase || "",
      phaseHistory: context.progress?.phases || [],
    };
  }
  if (action === "voice_wake_logcat_summary") {
    const since = String(args.since || args.sinceTime || args.since_time || "5m").trim() || "5m";
    const tailArg = /^\d+$/.test(since) ? since : String(Math.max(200, Math.min(4000, Number(args.tailLines || args.tail_lines || 1200) || 1200)));
    const logcat = await context.adb.shell(serial, ["logcat", "-d", "-v", "time", "-t", tailArg], { timeoutMs: 15000, maxBuffer: 8 * 1024 * 1024 });
    const lines = String(logcat.stdout || "")
      .split(/\r?\n/)
      .filter((line) => /HermesVoiceWake|voice_wake|wake_detected|inference_count|threshold_policy|audio_record|command_capture|transcript_|AndroidRuntime|FATAL EXCEPTION|ForegroundService|ServiceStart|startForeground|ActivityManager|com\.colmeio\.wasmagent/i.test(line))
      .slice(-800);
    const summary = {
      wakeStateSnapshot: null,
      inferenceCount: 0,
      lastConfidence: null,
      maxConfidence: null,
      wakeDetectedCount: 0,
      commandCaptureStartedCount: 0,
      transcriptAcceptedCount: 0,
      transcriptRejectedCount: 0,
      audioRecordStarted: false,
      thresholdPolicy: "",
      latestWakeDetected: "",
      latestInference: "",
      latestTranscript: "",
      latestAndroidRuntime: "",
      latestServiceStart: "",
    };
    for (const line of lines) {
      const snapshot = line.match(/wake_state_snapshot=(\{.*\})/i);
      if (snapshot) {
        try {
          summary.wakeStateSnapshot = JSON.parse(snapshot[1]);
        } catch {
          summary.wakeStateSnapshot = null;
        }
      }
      const inference = line.match(/inference_count=(\d+)/i);
      if (inference) summary.inferenceCount = Math.max(summary.inferenceCount, Number(inference[1]) || 0);
      const confidence = line.match(/last_confidence=([0-9.]+)/i);
      if (confidence) {
        const value = Number(confidence[1]);
        if (Number.isFinite(value)) {
          summary.lastConfidence = value;
          summary.maxConfidence = summary.maxConfidence === null ? value : Math.max(summary.maxConfidence, value);
          summary.latestInference = line;
        }
      }
      if (/wake_detected=true|wake_hit|proof_wake_detected/i.test(line)) {
        summary.wakeDetectedCount += 1;
        summary.latestWakeDetected = line;
      }
      if (/command_capture_started=true|command_capture_started/i.test(line)) summary.commandCaptureStartedCount += 1;
      if (/transcript_accepted/i.test(line)) {
        summary.transcriptAcceptedCount += 1;
        summary.latestTranscript = line;
      }
      if (/transcript_rejected/i.test(line)) {
        summary.transcriptRejectedCount += 1;
        summary.latestTranscript = line;
      }
      if (/audio_record_started=true/i.test(line)) summary.audioRecordStarted = true;
      if (/threshold_policy_source|effective_wake_threshold|remote_threshold|proof_threshold_override/i.test(line)) summary.thresholdPolicy = line;
      if (/AndroidRuntime|FATAL EXCEPTION/i.test(line)) summary.latestAndroidRuntime = line;
      if (/ForegroundService|ServiceStart|startForeground|ActivityManager/i.test(line)) summary.latestServiceStart = line;
    }
    const ok = Number(logcat.exitCode || 0) === 0;
    return {
      ok,
      stable: ok,
      operation: "run_android_ui_input_proof",
      action,
      since,
      tailLines: tailArg,
      summary,
      lines,
      stderr: String(logcat.stderr || logcat.error || "").slice(0, 2000),
      devices: device,
      screenReady,
      failureClassification: ok ? "pass" : "voice_wake_logcat_failed",
      lastPhase: context.progress?.lastPhase || "",
      phaseHistory: context.progress?.phases || [],
    };
  }
  if (action === "task_trace") {
    const since = String(args.since || args.sinceTime || args.since_time || "5m").trim() || "5m";
    const activityTop = await context.adb.shell(serial, ["dumpsys", "activity", "top"], { timeoutMs: 12000, maxBuffer: 2 * 1024 * 1024 });
    const activityActivities = await context.adb.shell(serial, ["dumpsys", "activity", "activities"], { timeoutMs: 12000, maxBuffer: 4 * 1024 * 1024 });
    const activityRecents = await context.adb.shell(serial, ["dumpsys", "activity", "recents"], { timeoutMs: 12000, maxBuffer: 4 * 1024 * 1024 });
    const windowDump = await context.adb.shell(serial, ["dumpsys", "window"], { timeoutMs: 12000, maxBuffer: 4 * 1024 * 1024 });
    const logcat = await context.adb.shell(serial, ["logcat", "-d", "-v", "time", "-t", since], { timeoutMs: 15000, maxBuffer: 8 * 1024 * 1024 });
    const ok = [activityTop, activityActivities, activityRecents, windowDump, logcat].every((item) => Number(item.exitCode || 0) === 0);
    const interestingLogcat = String(logcat.stdout || "")
      .split(/\r?\n/)
      .filter((line) => /colmeio|WasmAgentNative|AndroidRuntime|ActivityTaskManager|ActivityManager|crash|Exception|FATAL|am_finish_activity|START u0|Displayed|Force stopping/i.test(line))
      .slice(-400)
      .join("\n");
    return {
      ok,
      stable: ok,
      operation: "run_android_ui_input_proof",
      action,
      activityTop: String(activityTop.stdout || "").slice(0, 120000),
      activityActivities: String(activityActivities.stdout || "").slice(0, 240000),
      activityRecents: String(activityRecents.stdout || "").slice(0, 160000),
      window: String(windowDump.stdout || "").slice(0, 160000),
      logcatInteresting: interestingLogcat.slice(0, 240000),
      stderr: [activityTop, activityActivities, activityRecents, windowDump, logcat].map((item) => String(item.stderr || item.error || "")).filter(Boolean).join("\n").slice(0, 4000),
      devices: device,
      screenReady,
      failureClassification: ok ? "pass" : "adb_task_trace_failed",
      lastPhase: context.progress?.lastPhase || "",
      phaseHistory: context.progress?.phases || [],
    };
  }
  if (action === "foreground_summary") {
    const packageName = String(args.packageName || args.package_name || "com.colmeio.wasmagent");
    const runAdb = async (label, commandArgs, timeoutMs = 12000, maxBuffer = 2 * 1024 * 1024) => {
      const result = await context.adb.shell(serial, commandArgs, { timeoutMs, maxBuffer });
      return {
        label,
        exitCode: result.exitCode,
        stdout: String(result.stdout || "").split(/\r?\n/).filter(Boolean).slice(0, 220),
        stderr: String(result.stderr || result.error || "").slice(0, 1000),
        elapsedMs: result.elapsedMs ?? null,
      };
    };
    const pick = (label, command, pattern, timeoutMs = 12000) => runAdb(label, command, timeoutMs).then((result) => ({
      ...result,
      stdout: result.stdout.filter((line) => pattern.test(line)).slice(0, 120),
    }));
    const checks = [];
    checks.push(await runAdb("pid", ["pidof", packageName], 5000, 128 * 1024));
    checks.push(await runAdb("package_path", ["pm", "path", packageName], 5000, 128 * 1024));
    checks.push(await pick("package_version", ["dumpsys", "package", packageName], /Package \[|versionCode|versionName|firstInstallTime|lastUpdateTime|codePath|resourcePath|userId=/i));
    checks.push(await pick("window_focus", ["dumpsys", "window"], /mCurrentFocus|mFocusedApp|mInputMethodTarget|com\.colmeio\.wasmagent/i));
    checks.push(await pick("activity_resumed", ["dumpsys", "activity", "activities"], /mResumedActivity|topResumed|ResumedActivity|mLastPausedActivity|mFocusedRootTask|com\.colmeio\.wasmagent/i));
    checks.push(await pick("process_manager", ["dumpsys", "ProcessManager"], /ForegroundInfo|mForeground|com\.colmeio\.wasmagent|com\.miui\.home/i));
    checks.push(await pick("recent_log", ["logcat", "-d", "-v", "time", "-t", "180"], /colmeio|WasmAgentNative|AndroidRuntime|ActivityTaskManager|ActivityManager|START u0|Displayed|Force stopping|am_finish_activity|cmp=com\.colmeio\.wasmagent/i, 15000));
    const ok = checks.every((item) => Number(item.exitCode || 0) === 0);
    return {
      ok,
      stable: ok,
      operation: "run_android_ui_input_proof",
      action,
      checks,
      devices: device,
      screenReady,
      failureClassification: ok ? "pass" : "adb_foreground_summary_failed",
      lastPhase: context.progress?.lastPhase || "",
      phaseHistory: context.progress?.phases || [],
    };
  }
  if (action === "web_log") {
    const since = String(args.since || args.sinceTime || args.since_time || "300").trim() || "300";
    const logcat = await context.adb.shell(serial, ["logcat", "-d", "-v", "time", "-t", since], { timeoutMs: 15000, maxBuffer: 8 * 1024 * 1024 });
    const ok = Number(logcat.exitCode || 0) === 0;
    const lines = String(logcat.stdout || "")
      .split(/\r?\n/)
      .filter((line) => /chromium|cr_|WebView|Console|app\.js|Uncaught|SyntaxError|ReferenceError|TypeError|wasm.?agent|colmeio/i.test(line))
      .slice(-500);
    return {
      ok,
      stable: ok,
      operation: "run_android_ui_input_proof",
      action,
      lines,
      stderr: String(logcat.stderr || logcat.error || "").slice(0, 2000),
      devices: device,
      screenReady,
      failureClassification: ok ? "pass" : "adb_web_log_failed",
      lastPhase: context.progress?.lastPhase || "",
      phaseHistory: context.progress?.phases || [],
    };
  }
  if (action === "screenshot") {
    const shot = await context.adb.shell(serial, ["sh", "-c", "screencap -p /sdcard/wasm-agent-screen.png && (base64 -w 0 /sdcard/wasm-agent-screen.png 2>/dev/null || toybox base64 /sdcard/wasm-agent-screen.png | tr -d '\\n')"], { timeoutMs: 15000, maxBuffer: 24 * 1024 * 1024 });
    const ok = Number(shot.exitCode || 0) === 0;
    const pngBase64 = String(shot.stdout || "").replace(/\s+/g, "");
    return {
      ok,
      stable: ok,
      operation: "run_android_ui_input_proof",
      action,
      pngBase64: pngBase64.slice(0, 16 * 1024 * 1024),
      pngBase64Bytes: pngBase64.length,
      truncated: pngBase64.length > 16 * 1024 * 1024,
      stderr: String(shot.stderr || shot.error || "").slice(0, 2000),
      devices: device,
      screenReady,
      failureClassification: ok ? "pass" : "adb_screenshot_failed",
      lastPhase: context.progress?.lastPhase || "",
      phaseHistory: context.progress?.phases || [],
    };
  }
  let commandArgs;
  if (action === "swipe") {
    commandArgs = [
      "input",
      "swipe",
      String(numberInRange(1, 10000, args.x1 ?? args.startX ?? args.start_x, 500)),
      String(numberInRange(1, 10000, args.y1 ?? args.startY ?? args.start_y, 500)),
      String(numberInRange(1, 10000, args.x2 ?? args.endX ?? args.end_x, 500)),
      String(numberInRange(1, 10000, args.y2 ?? args.endY ?? args.end_y, 200)),
      String(numberInRange(1, 5000, args.durationMs ?? args.duration_ms, 180)),
    ];
  } else {
    commandArgs = [
      "input",
      "tap",
      String(numberInRange(1, 10000, args.x, 500)),
      String(numberInRange(1, 10000, args.y, 500)),
    ];
  }
  context.markPhase("input_dispatch", { commandArgs });
  const dispatch = await context.adb.shell(serial, commandArgs, { timeoutMs: 8000, maxBuffer: 128 * 1024 });
  const ok = Number(dispatch.exitCode || 0) === 0;
  const result = {
    ok,
    stable: ok,
    operation: "run_android_ui_input_proof",
    action,
    commandArgs,
    dispatch: {
      exitCode: dispatch.exitCode,
      stdout: String(dispatch.stdout || "").slice(0, 2000),
      stderr: String(dispatch.stderr || dispatch.error || "").slice(0, 2000),
      elapsedMs: dispatch.elapsedMs ?? null,
    },
    devices: device,
    screenReady,
    failureClassification: ok ? "pass" : "adb_input_failed",
    lastPhase: context.progress?.lastPhase || "",
    phaseHistory: context.progress?.phases || [],
  };
  context.fs.writeJsonSafe("latest-android-ui-input-proof.json", result);
  return result;
}

module.exports = { run };
