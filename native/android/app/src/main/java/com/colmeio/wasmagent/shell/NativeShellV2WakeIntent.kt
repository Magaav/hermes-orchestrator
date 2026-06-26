package com.colmeio.wasmagent.shell

import android.app.Activity
import android.content.ContentValues
import android.content.Intent
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import com.colmeio.wasmagent.HermesVoiceWakeService
import com.colmeio.wasmagent.voice.OpenWakeWordBundleEngine
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.zip.ZipInputStream
import org.json.JSONArray
import org.json.JSONObject

object NativeShellV2WakeIntent {
    private const val LOG_TAG = "HermesVoiceWake"
    @Volatile private var lastControlDiagnostic = JSONObject()

    fun handle(
        activity: Activity,
        config: NativeShellV2Config,
        diagnostics: NativeShellV2Diagnostics,
        intent: Intent?,
    ) {
        val activeIntent = intent ?: return
        val command = activeIntent.getStringExtra("voiceWakeCommand")
            ?: activeIntent.getStringExtra("voice_wake_command")
            ?: return
        when (command.trim().lowercase()) {
            "start", "start_voice_wake", "enable" -> start(activity, config, diagnostics, activeIntent, HermesVoiceWakeService.ACTION_START)
            "policy", "apply_policy", "apply_wake_word_policy" -> start(activity, config, diagnostics, activeIntent, HermesVoiceWakeService.ACTION_STATUS)
            "install_openwakeword_bundle", "install_openwakeword", "install_alexa_bundle" -> {
                val installIntent = Intent(activeIntent)
                Thread({
                    installOpenWakeWordBundle(activity, config, diagnostics, installIntent)
                }, "native-shell-openwakeword-install").start()
            }
            "dump", "dump_state", "status_snapshot", "wake_state" -> dumpState(activity, config, diagnostics)
            "stop", "stop_voice_wake", "disable" -> HermesVoiceWakeService.stop(activity)
        }
    }

    private fun installOpenWakeWordBundle(
        activity: Activity,
        config: NativeShellV2Config,
        diagnostics: NativeShellV2Diagnostics,
        intent: Intent,
    ) {
        val source = File(intent.getStringExtra("bundlePath") ?: intent.getStringExtra("bundle_path") ?: "/sdcard/Download/WASM-Agent/openwakeword.zip")
        val bundleUrl = (intent.getStringExtra("bundleUrl") ?: intent.getStringExtra("bundle_url") ?: "").trim()
        val expectedSha = (intent.getStringExtra("sha256") ?: intent.getStringExtra("expectedSha256") ?: "").trim().lowercase()
        val voiceDir = File(activity.filesDir, "voice")
        val downloadedZip = File(voiceDir, "openwakeword.download.zip")
        val targetDir = File(voiceDir, "openwakeword")
        val tempDir = File(voiceDir, "openwakeword.tmp")
        val required = setOf(
            OpenWakeWordBundleEngine.MEL_MODEL_NAME,
            OpenWakeWordBundleEngine.EMBEDDING_MODEL_NAME,
            OpenWakeWordBundleEngine.CLASSIFIER_MODEL_NAME,
        )
        val result = JSONObject()
            .put("schema", "hermes.wasm_agent.android_openwakeword_install.v1")
            .put("build_id", config.buildId)
            .put("origin", config.origin)
            .put("source", source.absolutePath)
            .put("bundle_url", bundleUrl)
            .put("path", OpenWakeWordBundleEngine.BUNDLE_DIR)
            .put("ok", false)
        try {
            voiceDir.mkdirs()
            val installSource = if (bundleUrl.isNotBlank()) {
                val resolved = URL(URL("${config.origin.trimEnd('/')}/"), bundleUrl)
                if (resolved.protocol != "https" || resolved.host.lowercase() != URL(config.origin).host.lowercase()) {
                    throw IllegalArgumentException("bundle_url_not_allowed")
                }
                val connection = (resolved.openConnection() as HttpURLConnection).apply {
                    connectTimeout = 15_000
                    readTimeout = 120_000
                    requestMethod = "GET"
                }
                if (connection.responseCode !in 200..299) {
                    throw IllegalStateException("bundle_download_failed:${connection.responseCode}")
                }
                var total = 0L
                connection.inputStream.use { input ->
                    FileOutputStream(downloadedZip).use { output ->
                        val buffer = ByteArray(64 * 1024)
                        while (true) {
                            val read = input.read(buffer)
                            if (read < 0) break
                            total += read
                            if (total > 96L * 1024L * 1024L) throw IllegalStateException("bundle_too_large")
                            output.write(buffer, 0, read)
                        }
                    }
                }
                result.put("downloaded_bytes", total).put("source", downloadedZip.absolutePath)
                downloadedZip
            } else {
                source
            }
            if (!installSource.isFile || installSource.length() <= 0L) {
                result.put("error", "source_missing")
            } else {
                val digest = MessageDigest.getInstance("SHA-256")
                installSource.inputStream().use { input ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        digest.update(buffer, 0, read)
                    }
                }
                val actualSha = digest.digest().joinToString("") { "%02x".format(it) }
                result.put("sha256", actualSha).put("bytes", installSource.length())
                if (expectedSha.isNotBlank() && actualSha != expectedSha) {
                    result.put("error", "sha256_mismatch").put("expected_sha256", expectedSha)
                } else {
                    tempDir.deleteRecursively()
                    tempDir.mkdirs()
                    val extracted = mutableSetOf<String>()
                    ZipInputStream(installSource.inputStream()).use { zip ->
                        while (true) {
                            val entry = zip.nextEntry ?: break
                            val name = entry.name.substringAfterLast('/').trim()
                            if (!entry.isDirectory && name in required) {
                                FileOutputStream(File(tempDir, name)).use { output ->
                                    val buffer = ByteArray(64 * 1024)
                                    while (true) {
                                        val read = zip.read(buffer)
                                        if (read < 0) break
                                        output.write(buffer, 0, read)
                                    }
                                }
                                extracted.add(name)
                            }
                            zip.closeEntry()
                        }
                    }
                    result.put("extracted", JSONArray(extracted))
                    if (!extracted.containsAll(required)) {
                        tempDir.deleteRecursively()
                        result.put("error", "bundle_missing_required_models")
                            .put("required", JSONArray(required))
                    } else {
                        targetDir.deleteRecursively()
                        if (!tempDir.renameTo(targetDir)) {
                            tempDir.copyRecursively(targetDir, overwrite = true)
                            tempDir.deleteRecursively()
                        }
                        result.put("ok", true).put("error", "")
                    }
                }
            }
        } catch (error: Exception) {
            tempDir.deleteRecursively()
            result.put("error", error.javaClass.name).put("message", error.message.orEmpty().take(500))
        }
        try {
            activity.getExternalFilesDir(null)?.resolve("native-diagnostics/openwakeword-install.json")?.also {
                it.parentFile?.mkdirs()
                it.writeText(result.toString(2))
            }
        } catch (_: Exception) {
        }
        diagnostics.record("openwakeword_install", result)
        Log.i(LOG_TAG, "openwakeword_install=${result.toString().take(1200)}")
        dumpState(activity, config, diagnostics)
    }

    private fun dumpState(
        activity: Activity,
        config: NativeShellV2Config,
        diagnostics: NativeShellV2Diagnostics,
    ) {
        val status = try {
            val file = HermesVoiceWakeService.statusFile(activity)
            if (file.isFile) JSONObject(file.readText()) else JSONObject()
        } catch (_: Exception) {
            JSONObject()
        }
        val lifecycle = try {
            val file = HermesVoiceWakeService.lifecycleFile(activity)
            if (file.isFile) JSONObject(file.readText()) else JSONObject()
        } catch (_: Exception) {
            JSONObject()
        }
        val snapshot = JSONObject()
            .put("schema", "hermes.wasm_agent.android_wake_state_snapshot.v1")
            .put("build_id", config.buildId)
            .put("origin", config.origin)
            .put("voice_wake_lifecycle_stage", lifecycle.optString("stage", ""))
            .put("voice_wake_lifecycle_action", lifecycle.optString("action", ""))
            .put("voice_wake_lifecycle_running", lifecycle.optBoolean("running", false))
            .put("voice_wake_lifecycle_worker_alive", lifecycle.optBoolean("worker_alive", false))
            .put("voice_wake_lifecycle_audio_read_calls", lifecycle.optLong("audio_read_calls", 0L))
            .put("voice_wake_lifecycle_audio_samples_read", lifecycle.optLong("audio_samples_read", 0L))
            .put("voice_wake_lifecycle_inference_count", lifecycle.optLong("inference_count", 0L))
            .put("voice_wake_lifecycle_last_listen_exit_reason", lifecycle.optString("last_listen_exit_reason", ""))
            .put("voice_wake_lifecycle_last_listen_exit_detail", lifecycle.optString("last_listen_exit_detail", ""))
            .put("voice_wake_lifecycle_last_failure_reason", lifecycle.optString("last_failure_reason", ""))
            .put("voice_wake_lifecycle_last_audio_record_error", lifecycle.optString("last_audio_record_error", ""))
            .put("voice_wake_control", lastControlDiagnostic)
            .put("voice_wake_control_command", lastControlDiagnostic.optString("command", ""))
            .put("voice_wake_control_action", lastControlDiagnostic.optString("action", ""))
            .put("voice_wake_control_ok", lastControlDiagnostic.optBoolean("ok", false))
            .put("voice_wake_control_stage", lastControlDiagnostic.optString("stage", ""))
            .put("voice_wake_control_error", lastControlDiagnostic.optString("error", ""))
            .put("status_source", status.optString("status_source", "activity_snapshot"))
            .put("service_alive", status.optBoolean("service_alive", false))
            .put("audio_record_started", status.optBoolean("audio_record_started", lifecycle.optBoolean("audio_record_started", false)))
            .put("audio_capture_alive", status.optBoolean("audio_capture_alive", lifecycle.optBoolean("running", false)))
            .put("audio_source", status.optString("audio_source", ""))
            .put("audio_source_id", status.optInt("audio_source_id", 0))
            .put("audio_source_restart_count", status.optLong("audio_source_restart_count", 0L))
            .put("audio_read_calls", status.optLong("audio_read_calls", lifecycle.optLong("audio_read_calls", 0L)))
            .put("audio_samples_read", status.optLong("audio_samples_read", lifecycle.optLong("audio_samples_read", 0L)))
            .put("audio_record_error", status.optString("audio_record_error", ""))
            .put("inference_running", status.optBoolean("inference_running", lifecycle.optLong("inference_count", 0L) > 0L))
            .put("inference_count", status.optLong("inference_count", lifecycle.optLong("inference_count", 0L)))
            .put("last_confidence", status.optDouble("last_confidence", lifecycle.optDouble("last_confidence", 0.0)))
            .put("max_observed_confidence", status.optDouble("max_observed_confidence", lifecycle.optDouble("max_observed_confidence", 0.0)))
            .put("wake_threshold", positiveDouble(status, "wake_threshold", positiveDouble(lifecycle, "wake_threshold", HermesVoiceWakeService.configuredWakeThreshold(activity))))
            .put("wake_confirmation_frames", positiveInt(status, "wake_confirmation_frames", positiveInt(lifecycle, "wake_confirmation_frames", HermesVoiceWakeService.configuredWakeConfirmationFrames(activity))))
            .put("wake_confirmation_window_ms", positiveLong(status, "wake_confirmation_window_ms", positiveLong(lifecycle, "wake_confirmation_window_ms", HermesVoiceWakeService.configuredWakeConfirmationWindowMs(activity))))
            .put("wake_cooldown_ms", positiveLong(status, "wake_cooldown_ms", positiveLong(lifecycle, "wake_cooldown_ms", HermesVoiceWakeService.configuredWakeCooldownMs(activity))))
            .put("vad_rms_threshold", positiveDouble(status, "vad_rms_threshold", positiveDouble(lifecycle, "vad_rms_threshold", HermesVoiceWakeService.configuredVadRmsThreshold(activity))))
            .put("vad_peak_threshold", positiveInt(status, "vad_peak_threshold", positiveInt(lifecycle, "vad_peak_threshold", HermesVoiceWakeService.configuredVadPeakThreshold(activity))))
            .put("vad_pass_count", status.optLong("vad_pass_count", lifecycle.optLong("vad_pass_count", 0L)))
            .put("vad_reject_count", status.optLong("vad_reject_count", lifecycle.optLong("vad_reject_count", 0L)))
            .put("last_vad_speech", status.optBoolean("last_vad_speech", lifecycle.optBoolean("last_vad_speech", false)))
            .put("wake_detection_count", status.optLong("wake_detection_count", lifecycle.optLong("wake_detection_count", 0L)))
            .put("raw_wake_detection_count", status.optLong("raw_wake_detection_count", lifecycle.optLong("raw_wake_detection_count", 0L)))
            .put("last_wake_frame_peak", status.optInt("last_wake_frame_peak", lifecycle.optInt("last_wake_frame_peak", 0)))
            .put("max_wake_frame_peak", status.optInt("max_wake_frame_peak", lifecycle.optInt("max_wake_frame_peak", 0)))
            .put("last_wake_frame_rms", status.optDouble("last_wake_frame_rms", lifecycle.optDouble("last_wake_frame_rms", 0.0)))
            .put("max_wake_frame_rms", status.optDouble("max_wake_frame_rms", lifecycle.optDouble("max_wake_frame_rms", 0.0)))
            .put("wake_provider", status.optString("wake_provider", lifecycle.optString("wake_provider", "")))
            .put("vad_provider", status.optString("vad_provider", lifecycle.optString("vad_provider", "")))
            .put("model_source", status.optString("model_source", lifecycle.optString("model_source", "")))
            .put("rejection_reason", status.optString("rejection_reason", ""))
            .put("voice_state", status.optString("voice_state", lifecycle.optString("voice_state", "")))
            .put("command_capture_started", status.optBoolean("command_capture_started", lifecycle.optBoolean("command_capture_started", false)))
            .put("command_capture_started_at", status.optLong("command_capture_started_at", lifecycle.optLong("command_capture_started_at", 0L)))
            .put("active_transcript_capture_id", status.optLong("active_transcript_capture_id", lifecycle.optLong("active_transcript_capture_id", 0L)))
            .put("last_transcript_status", status.optString("last_transcript_status", lifecycle.optString("last_transcript_status", "")))
            .put("last_transcript_result", status.optString("last_transcript_result", lifecycle.optString("last_transcript_result", "")))
            .put("last_asr_engine", status.optString("last_asr_engine", lifecycle.optString("last_asr_engine", "")))
            .put("last_asr_latency_ms", status.optLong("last_asr_latency_ms", lifecycle.optLong("last_asr_latency_ms", 0L)))
            .put("last_asr_audio_captured_ms", status.optLong("last_asr_audio_captured_ms", lifecycle.optLong("last_asr_audio_captured_ms", 0L)))
            .put("last_asr_partial_transcript", status.optString("last_asr_partial_transcript", lifecycle.optString("last_asr_partial_transcript", "")))
            .put("last_asr_diagnostics", status.opt("last_asr_diagnostics") ?: lifecycle.opt("last_asr_diagnostics") ?: JSONObject())
            .put("last_normalized_transcript", status.optString("last_normalized_transcript", lifecycle.optString("last_normalized_transcript", "")))
            .put("last_voice_command", status.optString("last_voice_command", lifecycle.optString("last_voice_command", "")))
            .put("voice_command_event_dispatched", status.optBoolean("voice_command_event_dispatched", lifecycle.optBoolean("voice_command_event_dispatched", false)))
            .put("voice_command_event_dispatched_at", status.optLong("voice_command_event_dispatched_at", lifecycle.optLong("voice_command_event_dispatched_at", 0L)))
            .put("last_error", status.optString("last_error", lifecycle.optString("last_error", "")))
            .put("last_exception", status.opt("last_exception") ?: lifecycle.opt("last_exception") ?: JSONObject.NULL)
            .put("tuning_session_id", status.optString("tuning_session_id", ""))
        val line = snapshot.toString().take(2500)
        try {
            val file = activity.getExternalFilesDir(null)?.resolve("native-diagnostics/wake-state-snapshot.json")
            file?.parentFile?.mkdirs()
            file?.writeText(snapshot.toString(2))
        } catch (_: Exception) {
        }
        try {
            writePublicSnapshot(activity, snapshot)
        } catch (_: Exception) {
        }
        Log.i(LOG_TAG, "wake_state_snapshot=$line")
        diagnostics.record("voice_wake_state_snapshot", snapshot)
    }

    private fun positiveDouble(status: JSONObject, name: String, fallback: Double): Double {
        val value = status.optDouble(name, fallback)
        return if (value > 0.0) value else fallback
    }

    private fun positiveInt(status: JSONObject, name: String, fallback: Int): Int {
        val value = status.optInt(name, fallback)
        return if (value > 0) value else fallback
    }

    private fun positiveLong(status: JSONObject, name: String, fallback: Long): Long {
        val value = status.optLong(name, fallback)
        return if (value > 0L) value else fallback
    }

    private fun writePublicSnapshot(activity: Activity, snapshot: JSONObject) {
        val json = snapshot.toString(2)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val resolver = activity.contentResolver
            val collection = MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
            val relativePath = "${Environment.DIRECTORY_DOWNLOADS}/WASM-Agent"
            resolver.delete(
                collection,
                "${MediaStore.MediaColumns.DISPLAY_NAME}=? AND ${MediaStore.MediaColumns.RELATIVE_PATH}=?",
                arrayOf("wake-state-snapshot.json", "$relativePath/"),
            )
            val values = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, "wake-state-snapshot.json")
                put(MediaStore.MediaColumns.MIME_TYPE, "application/json")
                put(MediaStore.MediaColumns.RELATIVE_PATH, relativePath)
                put(MediaStore.MediaColumns.IS_PENDING, 1)
            }
            val uri = resolver.insert(collection, values) ?: return
            resolver.openOutputStream(uri, "wt")?.use { it.write(json.toByteArray(Charsets.UTF_8)) }
            values.clear()
            values.put(MediaStore.MediaColumns.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
            return
        }
        val file = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "WASM-Agent/wake-state-snapshot.json")
        file.parentFile?.mkdirs()
        file.writeText(json)
    }

    private fun start(
        activity: Activity,
        config: NativeShellV2Config,
        diagnostics: NativeShellV2Diagnostics,
        intent: Intent,
        action: String,
    ) {
        val serviceIntent = Intent(activity, HermesVoiceWakeService::class.java)
            .setAction(action)
            .putExtra(HermesVoiceWakeService.EXTRA_ORIGIN, config.origin)
        copyExtra(intent, serviceIntent, HermesVoiceWakeService.EXTRA_WAKE_THRESHOLD, "wakeThreshold")
        copyExtra(intent, serviceIntent, "wakePhrase", "wake_phrase")
        copyExtra(intent, serviceIntent, "wake_cooldown_ms", "wakeCooldownMs")
        copyExtra(intent, serviceIntent, "wake_confirmation_frames", "wakeConfirmationFrames", "wakeVerificationFrames")
        copyExtra(intent, serviceIntent, "wake_confirmation_window_ms", "wakeConfirmationWindowMs", "wakeVerificationWindowMs")
        copyExtra(intent, serviceIntent, "vad_rms_threshold", "vadRmsThreshold")
        copyExtra(intent, serviceIntent, "vad_peak_threshold", "vadPeakThreshold")
        copyExtra(intent, serviceIntent, "transcript_engine", "transcriptEngine")
        copyExtra(intent, serviceIntent, "transcript_timeout_ms", "transcriptTimeoutMs")
        copyExtra(intent, serviceIntent, "transcript_min_length_ms", "transcriptMinLengthMs")
        copyExtra(intent, serviceIntent, "transcript_complete_silence_ms", "transcriptCompleteSilenceMs")
        copyExtra(intent, serviceIntent, "transcript_possible_silence_ms", "transcriptPossibleSilenceMs")
        copyExtra(intent, serviceIntent, "transcript_accept_partial", "transcriptAcceptPartial")
        copyExtra(intent, serviceIntent, "transcript_attempt_plan", "transcriptAttemptPlan", "transcriptPlan")
        copyExtra(intent, serviceIntent, "tuning_session_id", "tuningSessionId")
        val command = intent.getStringExtra("voiceWakeCommand") ?: intent.getStringExtra("voice_wake_command") ?: ""
        val control = JSONObject()
            .put("schema", "hermes.wasm_agent.android_wake_control.v1")
            .put("command", command)
            .put("action", action)
            .put("origin", config.origin)
            .put("stage", "prepared")
            .put("ok", false)
            .put("sdk", Build.VERSION.SDK_INT)
            .put("service_intent_action", serviceIntent.action ?: "")
        lastControlDiagnostic = control
        try {
            control.put("stage", "calling_service_intent")
            lastControlDiagnostic = JSONObject(control.toString())
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) activity.startForegroundService(serviceIntent) else activity.startService(serviceIntent)
            control
                .put("stage", "service_intent_returned")
                .put("ok", true)
                .put("used_start_foreground_service", Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
            lastControlDiagnostic = JSONObject(control.toString())
            diagnostics.record("voice_wake_control_intent", JSONObject()
                .put("command", command)
                .put("action", action)
                .put("control", control))
        } catch (error: Exception) {
            control
                .put("stage", "service_intent_failed")
                .put("ok", false)
                .put("error", error.javaClass.name)
                .put("message", error.message.orEmpty().take(500))
            lastControlDiagnostic = JSONObject(control.toString())
            diagnostics.record("voice_wake_control_intent_failed", JSONObject()
                .put("action", action)
                .put("error", error.javaClass.simpleName)
                .put("control", control))
        }
    }

    private fun copyExtra(source: Intent, target: Intent, vararg names: String) {
        val extras = source.extras ?: return
        val name = names.firstOrNull { extras.containsKey(it) } ?: return
        val targetName = names.first()
        when (val value = extras.get(name)) {
            is Boolean -> target.putExtra(targetName, value)
            is Int -> target.putExtra(targetName, value)
            is Long -> target.putExtra(targetName, value)
            is Float -> target.putExtra(targetName, value)
            is Double -> target.putExtra(targetName, value)
            is String -> target.putExtra(targetName, value)
        }
    }
}
