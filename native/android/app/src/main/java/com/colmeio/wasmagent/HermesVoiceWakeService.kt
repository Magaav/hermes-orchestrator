package com.colmeio.wasmagent

import android.Manifest
import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.AssetManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.IBinder
import android.os.SystemClock
import android.util.Log
import com.colmeio.wasmagent.voice.EnergyVoiceVad
import com.colmeio.wasmagent.voice.FalseWakeStore
import com.colmeio.wasmagent.voice.LocalCommandTranscriptionEngine
import com.colmeio.wasmagent.voice.OpenWakeWordOnnxEngine
import com.colmeio.wasmagent.voice.WakeWordResult
import com.colmeio.wasmagent.voice.WakeModelSelection
import com.colmeio.wasmagent.voice.WakeModelSelector
import com.colmeio.wasmagent.voice.VoiceCommandRouter
import com.colmeio.wasmagent.voice.VoiceProviderSelector
import com.colmeio.wasmagent.voice.VoiceProviderSet
import com.colmeio.wasmagent.voice.VoiceWakeEvent
import com.colmeio.wasmagent.voice.VoiceWakeStateMachine
import com.colmeio.wasmagent.voice.TranscriptionPolicy
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.security.MessageDigest
import java.util.UUID
import kotlin.concurrent.thread
import org.json.JSONArray
import org.json.JSONObject

class HermesVoiceWakeService : Service() {
    companion object {
        const val ACTION_START = "com.colmeio.wasmagent.voice.START"
        const val ACTION_STOP = "com.colmeio.wasmagent.voice.STOP"
        const val ACTION_STATUS = "com.colmeio.wasmagent.voice.STATUS"
        const val EXTRA_DEBUG_VOICE_MODE = "debug_voice_mode"
        const val EXTRA_ORIGIN = "origin"
        const val EXTRA_PROOF_SESSION = "proof_session"
        const val EXTRA_WAKE_THRESHOLD = "wake_threshold"
        const val PREFS_NAME = "wasm_agent_android_shell"
        const val PREF_ENABLED = "voice_wake_enabled"
        const val PREF_ORIGIN = "voice_wake_origin"
        const val PREF_WAKE_THRESHOLD = "voice_wake_threshold"
        const val PREF_WAKE_THRESHOLD_SOURCE = "voice_wake_threshold_source"
        const val PREF_VAD_RMS_THRESHOLD = "voice_wake_vad_rms_threshold"
        const val PREF_VAD_PEAK_THRESHOLD = "voice_wake_vad_peak_threshold"
        const val PREF_TUNING_SESSION_ID = "voice_wake_tuning_session_id"
        const val PREF_LAUNCH_APP_ON_WAKE = "voice_wake_launch_app_on_wake"
        const val PREF_RESTORE_ON_BOOT = "voice_wake_restore_on_boot"
        const val PREF_TRANSCRIPT_TIMEOUT_MS = "voice_wake_transcript_timeout_ms"
        const val PREF_TRANSCRIPT_MIN_LENGTH_MS = "voice_wake_transcript_min_length_ms"
        const val PREF_TRANSCRIPT_COMPLETE_SILENCE_MS = "voice_wake_transcript_complete_silence_ms"
        const val PREF_TRANSCRIPT_POSSIBLE_SILENCE_MS = "voice_wake_transcript_possible_silence_ms"
        const val PREF_TRANSCRIPT_ACCEPT_PARTIAL = "voice_wake_transcript_accept_partial"
        const val PREF_TRANSCRIPT_ENGINE = "voice_wake_transcript_engine"
        const val DEFAULT_WAKE_THRESHOLD = OpenWakeWordOnnxEngine.DEFAULT_CONFIDENCE_THRESHOLD
        const val DEFAULT_VAD_RMS_THRESHOLD = 0.012
        const val DEFAULT_VAD_PEAK_THRESHOLD = 1800
        const val DEFAULT_TRANSCRIPT_TIMEOUT_MS = 12_000L
        const val DEFAULT_TRANSCRIPT_MIN_LENGTH_MS = 900L
        const val DEFAULT_TRANSCRIPT_COMPLETE_SILENCE_MS = 1_500L
        const val DEFAULT_TRANSCRIPT_POSSIBLE_SILENCE_MS = 800L
        const val THRESHOLD_SOURCE_NATIVE_DEFAULT = "native_default"
        const val THRESHOLD_SOURCE_PROOF_INTENT_OVERRIDE = "proof_intent_override"
        const val THRESHOLD_SOURCE_REMOTE_CONFIG = "remote_config"
        private const val CHANNEL_ID = "wasm_agent_hermes_voice_wake"
        private const val NOTIFICATION_ID = 4721
        private const val LOG_TAG = "HermesVoiceWake"
        private const val MAX_CAPTURE_MS = 12_000L
        private const val FALSE_WAKE_AUDIO_WINDOW_MS = 3_000
        private const val RECENT_EVENT_MAX = 50
        private const val WAKE_COOLDOWN_MS = 2_500L
        private const val MIN_WAKE_THRESHOLD = 0.05
        private const val MAX_WAKE_THRESHOLD = 0.99
        private const val ACCEPTANCE_MODEL_SHA256 = "2abbebf21610f91f8d1fcfc12ac92f8ec19dc1191f3c90dbda4cba46e71027b2"

        fun statusFile(context: Context): File = File(context.filesDir, "native-diagnostics/voice-wake.json")

        fun normalizedWakeThreshold(value: Double): Double? =
            if (value.isFinite() && value in MIN_WAKE_THRESHOLD..MAX_WAKE_THRESHOLD) value else null

        fun configuredWakeThreshold(context: Context): Double {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val source = prefs.getString(PREF_WAKE_THRESHOLD_SOURCE, "").orEmpty()
            val raw = prefs
                .getFloat(PREF_WAKE_THRESHOLD, DEFAULT_WAKE_THRESHOLD.toFloat())
                .toDouble()
            if (source.isBlank() && raw < DEFAULT_WAKE_THRESHOLD) {
                prefs.edit()
                    .putFloat(PREF_WAKE_THRESHOLD, DEFAULT_WAKE_THRESHOLD.toFloat())
                    .putString(PREF_WAKE_THRESHOLD_SOURCE, THRESHOLD_SOURCE_NATIVE_DEFAULT)
                    .apply()
                return DEFAULT_WAKE_THRESHOLD
            }
            return normalizedWakeThreshold(raw) ?: DEFAULT_WAKE_THRESHOLD
        }

        fun configuredVadRmsThreshold(context: Context): Double {
            return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .getFloat(PREF_VAD_RMS_THRESHOLD, DEFAULT_VAD_RMS_THRESHOLD.toFloat())
                .toDouble()
                .coerceIn(0.001, 0.2)
        }

        fun configuredVadPeakThreshold(context: Context): Int {
            return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .getInt(PREF_VAD_PEAK_THRESHOLD, DEFAULT_VAD_PEAK_THRESHOLD)
                .coerceIn(100, 30000)
        }

        fun configuredTranscriptTimeoutMs(context: Context): Long {
            return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .getLong(PREF_TRANSCRIPT_TIMEOUT_MS, DEFAULT_TRANSCRIPT_TIMEOUT_MS)
                .coerceIn(2_000L, 30_000L)
        }

        fun configuredTranscriptPolicy(context: Context): TranscriptionPolicy {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return TranscriptionPolicy(
                acceptPartialResults = prefs.getBoolean(PREF_TRANSCRIPT_ACCEPT_PARTIAL, true),
                minimumLengthMs = prefs.getLong(PREF_TRANSCRIPT_MIN_LENGTH_MS, DEFAULT_TRANSCRIPT_MIN_LENGTH_MS).coerceIn(250L, 10_000L),
                completeSilenceMs = prefs.getLong(PREF_TRANSCRIPT_COMPLETE_SILENCE_MS, DEFAULT_TRANSCRIPT_COMPLETE_SILENCE_MS).coerceIn(250L, 10_000L),
                possiblyCompleteSilenceMs = prefs.getLong(PREF_TRANSCRIPT_POSSIBLE_SILENCE_MS, DEFAULT_TRANSCRIPT_POSSIBLE_SILENCE_MS).coerceIn(250L, 10_000L),
            )
        }

        fun configuredTranscriptEngine(context: Context): String {
            val raw = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .getString(PREF_TRANSCRIPT_ENGINE, LocalCommandTranscriptionEngine.PREF_ENGINE_VOSK)
                .orEmpty()
            return when (raw) {
                LocalCommandTranscriptionEngine.PREF_ENGINE_ANDROID,
                LocalCommandTranscriptionEngine.PREF_ENGINE_AUTO,
                LocalCommandTranscriptionEngine.PREF_ENGINE_VOSK -> raw
                else -> LocalCommandTranscriptionEngine.PREF_ENGINE_VOSK
            }
        }

        internal fun installBundledHermesModelIfPresent(
            modelFile: File,
            openAsset: (String) -> InputStream,
        ): Boolean {
            return try {
                openAsset("voice/base_hermes.onnx").use { input ->
                    val bytes = input.readBytes()
                    if (bytes.isEmpty()) return false
                    if (modelFile.exists() && modelFile.length() == bytes.size.toLong()) return false
                    modelFile.parentFile?.mkdirs()
                    FileOutputStream(modelFile).use { output -> output.write(bytes) }
                }
                true
            } catch (_: Exception) {
                false
            }
        }

        internal fun bundledHermesModelAvailable(assets: AssetManager): Boolean {
            return try {
                assets.open("voice/base_hermes.onnx").use { input -> input.read() >= 0 }
            } catch (_: Exception) {
                false
            }
        }

        fun start(context: Context, origin: String, proofSession: Boolean = false, wakeThreshold: Double? = null) {
            val intent = Intent(context, HermesVoiceWakeService::class.java)
                .setAction(ACTION_START)
                .putExtra(EXTRA_ORIGIN, origin)
                .putExtra(EXTRA_PROOF_SESSION, proofSession)
            normalizedWakeThreshold(wakeThreshold ?: Double.NaN)?.let { threshold ->
                intent.putExtra(EXTRA_WAKE_THRESHOLD, threshold)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(intent) else context.startService(intent)
        }

        fun requestStatus(context: Context, proofSession: Boolean = false) {
            val intent = Intent(context, HermesVoiceWakeService::class.java)
                .setAction(ACTION_STATUS)
                .putExtra(EXTRA_PROOF_SESSION, proofSession)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(intent) else context.startService(intent)
        }

        fun stop(context: Context) {
            context.startService(Intent(context, HermesVoiceWakeService::class.java).setAction(ACTION_STOP))
        }

        fun shouldRestore(context: Context): Boolean {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            return prefs.getBoolean(PREF_ENABLED, false) &&
                prefs.getBoolean(PREF_RESTORE_ON_BOOT, true)
        }

        fun restoreIfEnabled(context: Context, reason: String) {
            if (!shouldRestore(context)) return
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            val origin = prefs.getString(PREF_ORIGIN, "").orEmpty().ifBlank { BuildConfig.DEFAULT_SERVER_URL }
            Log.i(LOG_TAG, "voice_wake_restore_requested reason=$reason origin=$origin")
            start(context, origin)
        }
    }

    private val machine = VoiceWakeStateMachine()
    @Volatile private var running = false
    @Volatile private var worker: Thread? = null
    private val personalizedModelFile by lazy { File(filesDir, "voice/hermes.onnx") }
    private val baseModelFile by lazy { File(filesDir, "voice/base_hermes.onnx") }
    @Volatile private var wakeModelSelection: WakeModelSelection? = null
    private val router = VoiceCommandRouter()
    @Volatile private var providers: VoiceProviderSet? = null
    @Volatile private var audioRecordInitializedAt: Long = 0
    @Volatile private var audioRecordStartCalledAt: Long = 0
    @Volatile private var audioRecordStartedAt: Long = 0
    @Volatile private var lastAudioFrameAt: Long = 0
    @Volatile private var audioReadCalls: Long = 0
    @Volatile private var audioSamplesRead: Long = 0
    @Volatile private var audioReadErrors: Long = 0
    @Volatile private var lastInferenceAt: Long = 0
    @Volatile private var inferenceCount: Long = 0
    @Volatile private var lastInferenceConfidence: Double = 0.0
    @Volatile private var maxObservedConfidence: Double = 0.0
    @Volatile private var lastInferenceThresholdCrossed: Boolean = false
    @Volatile private var lastInferenceRejectionReason: String = "inference_not_started"
    @Volatile private var wakeDetectionCount: Long = 0
    @Volatile private var lastWakeDetectionAt: Long = 0
    @Volatile private var wakeCooldownUntil: Long = 0
    @Volatile private var lastProofStatusWriteAt: Long = 0
    @Volatile private var wakeDetectedEventEmittedAt: Long = 0
    @Volatile private var commandCaptureStartedAt: Long = 0
    @Volatile private var voiceCommandEventDispatchedAt: Long = 0
    private val inferenceWindows = ArrayDeque<JSONObject>()
    @Volatile private var lastWakePass: Boolean = false
    @Volatile private var lastWakeProofResult: String = "not_started"
    @Volatile private var lastAudioRecordError: String = ""
    @Volatile private var lastFailureReason: String = ""
    @Volatile private var lastException: String = ""
    @Volatile private var proofSessionActive: Boolean = false
    @Volatile private var proofWakeThresholdOverride: Double? = null
    @Volatile private var lastTranscriptResult: String = ""
    @Volatile private var lastAsrEngine: String = ""
    @Volatile private var lastAsrLatencyMs: Long = 0
    @Volatile private var lastAsrAudioCapturedMs: Long = 0
    @Volatile private var lastAsrPartialTranscript: String = ""
    @Volatile private var falseWakeCount: Long = 0
    @Volatile private var lastFalseWakeAt: Long = 0
    @Volatile private var standbyRestoredAt: Long = 0
    private val recentEvents = ArrayDeque<JSONObject>()

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.getBooleanExtra(EXTRA_PROOF_SESSION, false) == true) {
            proofSessionActive = true
        }
        val thresholdChanged = applyWakeThresholdExtra(intent, proofSessionActive)
        val vadPolicyChanged = applyVadPolicyExtra(intent)
        val transcriptPolicyChanged = applyTranscriptPolicyExtra(intent)
        when (intent?.action) {
            ACTION_STOP -> {
                rememberEvent("service_stopped", JSONObject().put("reason", "user_disabled"))
                stopListening("user_disabled")
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_STATUS -> {
                if (running) {
                    writeStatus(if (thresholdChanged || vadPolicyChanged || transcriptPolicyChanged) "wake_policy_updated" else if (proofSessionActive) "proof_status_requested" else "")
                } else {
                    startListening(intent?.getStringExtra(EXTRA_ORIGIN).orEmpty())
                }
            }
            else -> startListening(
                intent?.getStringExtra(EXTRA_ORIGIN).orEmpty(),
                intent?.getBooleanExtra(EXTRA_DEBUG_VOICE_MODE, false) == true,
            )
        }
        return START_STICKY
    }

    private fun applyWakeThresholdExtra(intent: Intent?, proofSession: Boolean): Boolean {
        val extras = intent?.extras ?: return false
        val raw = when {
            extras.containsKey(EXTRA_WAKE_THRESHOLD) -> extras.get(EXTRA_WAKE_THRESHOLD)
            extras.containsKey("threshold") -> extras.get("threshold")
            else -> null
        }
        val threshold = when (raw) {
            is Number -> normalizedWakeThreshold(raw.toDouble())
            is String -> normalizedWakeThreshold(raw.toDoubleOrNull() ?: Double.NaN)
            else -> null
        } ?: return false
        if (proofSession) {
            val previous = proofWakeThresholdOverride
            if (previous != null && kotlin.math.abs(previous - threshold) < 0.0001) return false
            proofWakeThresholdOverride = threshold
            wakeModelSelection = null
            providers = null
            Log.i(LOG_TAG, "threshold_policy_source=$THRESHOLD_SOURCE_PROOF_INTENT_OVERRIDE proof_threshold_override=$threshold effective_wake_threshold=$threshold")
            return true
        }
        val previous = currentWakeThreshold()
        if (kotlin.math.abs(previous - threshold) < 0.0001) return false
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
            .putFloat(PREF_WAKE_THRESHOLD, threshold.toFloat())
            .putString(PREF_WAKE_THRESHOLD_SOURCE, THRESHOLD_SOURCE_REMOTE_CONFIG)
            .apply()
        wakeModelSelection = null
        providers = null
        Log.i(LOG_TAG, "threshold_policy_source=$THRESHOLD_SOURCE_REMOTE_CONFIG effective_wake_threshold=$threshold")
        return true
    }

    private fun applyVadPolicyExtra(intent: Intent?): Boolean {
        val extras = intent?.extras ?: return false
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val editor = prefs.edit()
        var changed = false
        if (extras.containsKey("vad_rms_threshold") || extras.containsKey("vadRmsThreshold")) {
            val raw = extras.get("vad_rms_threshold") ?: extras.get("vadRmsThreshold")
            val value = when (raw) {
                is Number -> raw.toDouble()
                is String -> raw.toDoubleOrNull() ?: Double.NaN
                else -> Double.NaN
            }.coerceIn(0.001, 0.2)
            if (!value.isNaN() && kotlin.math.abs(configuredVadRmsThreshold(this) - value) > 0.0001) {
                editor.putFloat(PREF_VAD_RMS_THRESHOLD, value.toFloat())
                changed = true
            }
        }
        if (extras.containsKey("vad_peak_threshold") || extras.containsKey("vadPeakThreshold")) {
            val raw = extras.get("vad_peak_threshold") ?: extras.get("vadPeakThreshold")
            val value = when (raw) {
                is Number -> raw.toInt()
                is String -> raw.toIntOrNull() ?: DEFAULT_VAD_PEAK_THRESHOLD
                else -> DEFAULT_VAD_PEAK_THRESHOLD
            }.coerceIn(100, 30000)
            if (configuredVadPeakThreshold(this) != value) {
                editor.putInt(PREF_VAD_PEAK_THRESHOLD, value)
                changed = true
            }
        }
        if (extras.containsKey("tuning_session_id") || extras.containsKey("tuningSessionId")) {
            val raw = extras.get("tuning_session_id") ?: extras.get("tuningSessionId")
            val value = raw.toString().take(120)
            if (value.isNotBlank() && prefs.getString(PREF_TUNING_SESSION_ID, "") != value) {
                editor.putString(PREF_TUNING_SESSION_ID, value)
                changed = true
            }
        }
        if (!changed) return false
        editor.apply()
        providers = null
        rememberEvent("wake_policy_updated", JSONObject()
            .put("vad_rms_threshold", configuredVadRmsThreshold(this))
            .put("vad_peak_threshold", configuredVadPeakThreshold(this)))
        return true
    }

    private fun applyTranscriptPolicyExtra(intent: Intent?): Boolean {
        val extras = intent?.extras ?: return false
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val editor = prefs.edit()
        var changed = false
        fun longExtra(snake: String, camel: String, defaultValue: Long, min: Long, max: Long): Long? {
            if (!extras.containsKey(snake) && !extras.containsKey(camel)) return null
            val raw = extras.get(snake) ?: extras.get(camel)
            val value = when (raw) {
                is Number -> raw.toLong()
                is String -> raw.toLongOrNull() ?: defaultValue
                else -> defaultValue
            }.coerceIn(min, max)
            return value
        }
        fun booleanExtra(snake: String, camel: String): Boolean? {
            if (!extras.containsKey(snake) && !extras.containsKey(camel)) return null
            val raw = extras.get(snake) ?: extras.get(camel)
            return when (raw) {
                is Boolean -> raw
                is String -> raw.equals("true", ignoreCase = true) || raw == "1"
                is Number -> raw.toInt() != 0
                else -> null
            }
        }
        longExtra("transcript_timeout_ms", "transcriptTimeoutMs", DEFAULT_TRANSCRIPT_TIMEOUT_MS, 2_000L, 30_000L)?.let { value ->
            if (configuredTranscriptTimeoutMs(this) != value) {
                editor.putLong(PREF_TRANSCRIPT_TIMEOUT_MS, value)
                changed = true
            }
        }
        longExtra("transcript_min_length_ms", "transcriptMinLengthMs", DEFAULT_TRANSCRIPT_MIN_LENGTH_MS, 250L, 10_000L)?.let { value ->
            if (prefs.getLong(PREF_TRANSCRIPT_MIN_LENGTH_MS, DEFAULT_TRANSCRIPT_MIN_LENGTH_MS).coerceIn(250L, 10_000L) != value) {
                editor.putLong(PREF_TRANSCRIPT_MIN_LENGTH_MS, value)
                changed = true
            }
        }
        longExtra("transcript_complete_silence_ms", "transcriptCompleteSilenceMs", DEFAULT_TRANSCRIPT_COMPLETE_SILENCE_MS, 250L, 10_000L)?.let { value ->
            if (prefs.getLong(PREF_TRANSCRIPT_COMPLETE_SILENCE_MS, DEFAULT_TRANSCRIPT_COMPLETE_SILENCE_MS).coerceIn(250L, 10_000L) != value) {
                editor.putLong(PREF_TRANSCRIPT_COMPLETE_SILENCE_MS, value)
                changed = true
            }
        }
        longExtra("transcript_possible_silence_ms", "transcriptPossibleSilenceMs", DEFAULT_TRANSCRIPT_POSSIBLE_SILENCE_MS, 250L, 10_000L)?.let { value ->
            if (prefs.getLong(PREF_TRANSCRIPT_POSSIBLE_SILENCE_MS, DEFAULT_TRANSCRIPT_POSSIBLE_SILENCE_MS).coerceIn(250L, 10_000L) != value) {
                editor.putLong(PREF_TRANSCRIPT_POSSIBLE_SILENCE_MS, value)
                changed = true
            }
        }
        booleanExtra("transcript_accept_partial", "transcriptAcceptPartial")?.let { value ->
            if (prefs.getBoolean(PREF_TRANSCRIPT_ACCEPT_PARTIAL, true) != value) {
                editor.putBoolean(PREF_TRANSCRIPT_ACCEPT_PARTIAL, value)
                changed = true
            }
        }
        if (extras.containsKey("transcript_engine") || extras.containsKey("transcriptEngine")) {
            val raw = (extras.get("transcript_engine") ?: extras.get("transcriptEngine")).toString()
            val value = when (raw) {
                LocalCommandTranscriptionEngine.PREF_ENGINE_ANDROID,
                LocalCommandTranscriptionEngine.PREF_ENGINE_AUTO,
                LocalCommandTranscriptionEngine.PREF_ENGINE_VOSK -> raw
                else -> ""
            }
            if (value.isNotBlank() && configuredTranscriptEngine(this) != value) {
                editor.putString(PREF_TRANSCRIPT_ENGINE, value)
                changed = true
            }
        }
        if (!changed) return false
        editor.apply()
        providers = null
        val policy = configuredTranscriptPolicy(this)
        rememberEvent("transcript_policy_updated", JSONObject()
            .put("transcript_timeout_ms", configuredTranscriptTimeoutMs(this))
            .put("transcript_min_length_ms", policy.minimumLengthMs)
            .put("transcript_complete_silence_ms", policy.completeSilenceMs)
            .put("transcript_possible_silence_ms", policy.possiblyCompleteSilenceMs)
            .put("transcript_accept_partial", policy.acceptPartialResults)
            .put("transcript_engine", configuredTranscriptEngine(this)))
        return true
    }

    override fun onDestroy() {
        if (running) {
            stopListening("service_destroy")
        } else {
            writeStatus("service_destroy")
        }
        super.onDestroy()
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        super.onTaskRemoved(rootIntent)
        if (getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).getBoolean(PREF_ENABLED, false)) {
            rememberEvent("task_removed_restart_scheduled")
            scheduleSelfRestart("task_removed")
            writeStatus("task_removed_restart_scheduled")
        }
    }

    private fun startListening(origin: String, requestedDebugVoiceMode: Boolean = false) {
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val selectedOrigin = origin.ifBlank { prefs.getString(PREF_ORIGIN, "").orEmpty() }.ifBlank { BuildConfig.DEFAULT_SERVER_URL }
        prefs.edit().putBoolean(PREF_ENABLED, true).putString(PREF_ORIGIN, selectedOrigin).apply()
        installBundledHermesModelIfPresent()
        var activeSelection = refreshWakeModelSelection()
        providers = selectProviders(requestedDebugVoiceMode, activeSelection)
        if (!hasRecordAudioPermission()) {
            prefs.edit().putBoolean(PREF_ENABLED, false).apply()
            lastFailureReason = "record_audio_permission_missing"
            machine.fail("record_audio_permission_missing")
            Log.w(LOG_TAG, "audio_record_permission_granted=false foreground_service_started=false")
            writeStatus("record_audio_permission_missing")
            stopSelf()
            return
        }
        if (running) {
            rememberEvent("duplicate_listener_prevented", JSONObject().put("requested_origin", selectedOrigin))
            writeStatus()
            return
        }
        try {
            startForeground(NOTIFICATION_ID, notification("Listening for Hermes"))
        } catch (error: Exception) {
            prefs.edit().putBoolean(PREF_ENABLED, false).apply()
            lastException = formatException(error)
            lastFailureReason = "foreground_service_not_started"
            machine.fail("foreground_service_not_started:${error.javaClass.name}")
            Log.e(LOG_TAG, "foreground_service_started=false error=$lastException")
            writeStatus("foreground_service_not_started")
            stopSelf()
            return
        }
        running = true
        machine.enable()
        rememberEvent("service_started", JSONObject().put("origin", selectedOrigin))
        rememberEvent("listener_started", JSONObject().put("listener_lane", "foreground_service"))
        Log.i(LOG_TAG, "foreground_service_started=true audio_record_permission_granted=true")
        if (providers?.wake?.ready != true) {
            machine.blocked(activeSelection.engine.diagnosticReason)
            Log.w(LOG_TAG, "wake_engine_ready=false onnx_runtime_available=${activeSelection.engine.onnxRuntimeAvailable} reason=${activeSelection.engine.diagnosticReason}")
            writeStatus("Place a compatible Hermes raw-PCM ONNX wake model at files/voice/hermes.onnx or bundle assets/voice/base_hermes.onnx. Wake detection is not active until the model is ready.")
            worker = thread(name = "hermes-voice-wake-blocked") {
                while (running) {
                    Thread.sleep(15_000)
                    installBundledHermesModelIfPresent()
                    activeSelection = refreshWakeModelSelection()
                    providers = selectProviders(requestedDebugVoiceMode, activeSelection)
                    if (providers?.wake?.ready == true) {
                        machine.enable()
                        rememberEvent("model_loaded", JSONObject().put("model_source", activeSelection.source))
                        Log.i(LOG_TAG, "wake_engine_ready=true onnx_runtime_available=${activeSelection.engine.onnxRuntimeAvailable}")
                        writeStatus("wake_engine_ready")
                        listenLoop(selectedOrigin)
                        return@thread
                    }
                    machine.blocked(activeSelection.engine.diagnosticReason)
                    writeStatus("wake_engine_not_ready")
                }
            }
            return
        }
        writeStatus()
        worker = thread(name = "hermes-voice-wake-listener") {
            listenLoop(selectedOrigin)
        }
    }

    private fun stopListening(reason: String) {
        running = false
        if (reason == "user_disabled") {
            getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit().putBoolean(PREF_ENABLED, false).apply()
        }
        machine.disable()
        rememberEvent("listener_stopped", JSONObject().put("reason", reason))
        writeStatus(reason)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) stopForeground(STOP_FOREGROUND_REMOVE) else @Suppress("DEPRECATION") stopForeground(true)
    }

    private fun listenLoop(origin: String) {
        while (running) {
            val wake = listenForWake()
            if (wake == null || !running) continue
            val startedAt = System.currentTimeMillis()
            val falseWakeAudio = wake.audioWindow.copyOf()
            commandCaptureStartedAt = startedAt
            rememberEvent("command_capture_started", JSONObject().put("wake_hit_count", wakeDetectionCount))
            Log.i(LOG_TAG, "command_capture_started=true wake_detection_count=$wakeDetectionCount last_confidence=$lastInferenceConfidence")
            bringAppToForegroundAfterWake(wake)
            machine.beginTranscribing()
            writeStatus()
            val transcript = currentProviders().transcriber.transcribeLiveAfterWake(
                configuredTranscriptTimeoutMs(this),
                configuredTranscriptPolicy(this),
            )
            val endedAt = System.currentTimeMillis()
            lastTranscriptResult = transcript.transcript.ifBlank { transcript.error }
            lastAsrEngine = transcript.engine.ifBlank { currentProviders().transcriber.name }
            lastAsrLatencyMs = transcript.latencyMs
            lastAsrAudioCapturedMs = transcript.audioCapturedMs
            lastAsrPartialTranscript = transcript.partialTranscript.take(160)
            if (transcript.transcript.isBlank()) {
                val reason = falseWakeReasonForTranscript(transcript.error)
                captureFalseWake(wake, falseWakeAudio, transcript.transcript, reason, startedAt)
                rememberEvent("transcript_rejected", JSONObject().put("reason", reason))
                machine.fail(transcript.error.ifBlank { "transcription_empty" })
                writeStatus()
                machine.listenAgain()
                standbyRestoredAt = System.currentTimeMillis()
                rememberEvent("standby_restored")
                continue
            }
            val command = wakeWorldCommandForTranscript(transcript.transcript)
            if (command.isBlank()) {
                val reason = "unknown_command"
                captureFalseWake(wake, falseWakeAudio, transcript.transcript, reason, startedAt)
                rememberEvent("transcript_rejected", JSONObject()
                    .put("reason", reason)
                    .put("transcript", transcript.transcript.take(160)))
                machine.fail(reason)
                writeStatus(reason)
                machine.listenAgain()
                standbyRestoredAt = System.currentTimeMillis()
                rememberEvent("standby_restored")
                writeStatus()
                continue
            }
            val event = VoiceWakeEvent(
                transcript = transcript.transcript,
                confidence = wake.confidence.coerceIn(0.0, 1.0),
                startedAt = startedAt,
                endedAt = endedAt,
                buildId = BuildConfig.NATIVE_BUILD_ID,
                sessionId = UUID.randomUUID().toString(),
            )
            machine.complete(event)
            rememberEvent("transcript_accepted", JSONObject().put("command", command))
            writeStatus()
            postVoiceEvent(origin, event, falseWakeAudio)
            machine.listenAgain()
            standbyRestoredAt = System.currentTimeMillis()
            rememberEvent("standby_restored")
            writeStatus()
        }
    }

    private fun listenForWake(): WakeWordResult? {
        var recorder: AudioRecord? = null
        try {
            val rawMinBuffer = AudioRecord.getMinBufferSize(
                OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
            )
            if (rawMinBuffer <= 0) {
                lastAudioRecordError = "AudioRecord.getMinBufferSize returned $rawMinBuffer"
                lastFailureReason = "audio_record_init_failed"
                lastWakeProofResult = "fail:audio_record_init_failed"
                machine.fail("audio_record_init_failed")
                Log.e(LOG_TAG, "audio_record_initialized=false audio_record_last_error=$lastAudioRecordError")
                writeStatus("audio_record_init_failed")
                return null
            }
            val minBuffer = rawMinBuffer.coerceAtLeast(OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ)
            recorder = AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION,
                OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                minBuffer,
            )
            if (recorder.state != AudioRecord.STATE_INITIALIZED) {
                lastAudioRecordError = "AudioRecord state=${recorder.state}"
                lastFailureReason = "audio_record_init_failed"
                lastWakeProofResult = "fail:audio_record_init_failed"
                machine.fail("audio_record_init_failed")
                Log.e(LOG_TAG, "audio_record_initialized=false audio_record_last_error=$lastAudioRecordError")
                writeStatus("audio_record_init_failed")
                return null
            }
            audioRecordInitializedAt = System.currentTimeMillis()
            Log.i(LOG_TAG, "audio_record_initialized=true min_buffer=$minBuffer")
            audioRecordStartCalledAt = System.currentTimeMillis()
            Log.i(LOG_TAG, "audio_record_start_called=true")
            recorder.startRecording()
            if (recorder.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
                lastAudioRecordError = "AudioRecord did not enter RECORDSTATE_RECORDING"
                lastFailureReason = "audio_record_start_failed"
                lastWakeProofResult = "fail:audio_record_start_failed"
                machine.fail("audio_record_start_failed")
                Log.e(LOG_TAG, "audio_record_started=false audio_record_last_error=$lastAudioRecordError")
                writeStatus("audio_record_start_failed")
                return null
            }
            audioRecordStartedAt = System.currentTimeMillis()
            lastAudioRecordError = ""
            lastFailureReason = ""
            lastException = ""
            lastWakeProofResult = "audio_record_started"
            Log.i(LOG_TAG, "audio_record_started=true")
            writeStatus("audio_record_started")
            val buffer = ShortArray(1024)
            val rollingAudio = RollingPcm16Window((OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ * FALSE_WAKE_AUDIO_WINDOW_MS) / 1000)
            while (running) {
                val count = recorder.read(buffer, 0, buffer.size)
                if (count <= 0) {
                    audioReadErrors += 1
                    lastAudioRecordError = "AudioRecord.read returned $count"
                    Log.w(LOG_TAG, "audio_record_read_error_count=$audioReadErrors audio_record_last_error=$lastAudioRecordError")
                    continue
                }
                audioReadCalls += 1
                audioSamplesRead += count.toLong()
                lastAudioFrameAt = System.currentTimeMillis()
                if (lastAudioRecordError.startsWith("AudioRecord.read returned ")) {
                    lastAudioRecordError = ""
                }
                if (audioReadCalls == 1L || audioReadCalls % 50L == 0L) {
                    Log.i(LOG_TAG, "audio_record_read_count=$audioReadCalls audio_samples_read=$audioSamplesRead")
                }
                val frame = buffer.copyOf(count)
                rollingAudio.append(frame)
                if (!proofSessionActive && System.currentTimeMillis() < wakeCooldownUntil) continue
                val activeProviders = currentProviders()
                if (!proofSessionActive && !activeProviders.vad.isSpeech(frame, OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ)) continue
                val wake = activeProviders.wake.processPcm16(frame, OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ)
                recordInference(wake)
                if (inferenceCount == 1L || inferenceCount % 100L == 0L) {
                    rememberEvent("inference_tick", JSONObject()
                        .put("inference_count", inferenceCount)
                        .put("last_confidence", lastInferenceConfidence))
                }
                if (inferenceCount == 1L || inferenceCount % 20L == 0L || wake.detected) {
                    Log.i(LOG_TAG, "inference_count=$inferenceCount last_confidence=$lastInferenceConfidence wake_detected=${wake.detected}")
                }
                if (proofSessionActive) {
                    if (wake.detected) {
                        wakeDetectionCount += 1
                        lastWakeDetectionAt = System.currentTimeMillis()
                        wakeCooldownUntil = lastWakeDetectionAt + WAKE_COOLDOWN_MS
                        rememberEvent("wake_hit", JSONObject().put("confidence", lastInferenceConfidence))
                        Log.i(LOG_TAG, "wake_detected=true wake_detection_count=$wakeDetectionCount last_confidence=$lastInferenceConfidence")
                        lastWakePass = true
                        lastWakeProofResult = "pass"
                        writeStatus("proof_wake_detected")
                        postWakeDetectedEvent(wake)
                        return wake.copy(audioWindow = rollingAudio.snapshot())
                    }
                    val now = System.currentTimeMillis()
                    if (now - lastProofStatusWriteAt >= 1000L) {
                        lastProofStatusWriteAt = now
                        writeStatus("proof_inference_observed")
                    }
                    continue
                }
                if (machine.onWake(wake)) {
                    wakeDetectionCount += 1
                    lastWakeDetectionAt = System.currentTimeMillis()
                    wakeCooldownUntil = lastWakeDetectionAt + WAKE_COOLDOWN_MS
                    rememberEvent("wake_hit", JSONObject().put("confidence", lastInferenceConfidence))
                    lastWakePass = true
                    lastWakeProofResult = "pass"
                    writeStatus()
                    postWakeDetectedEvent(wake)
                    return wake.copy(audioWindow = rollingAudio.snapshot())
                }
            }
        } catch (error: Exception) {
            lastException = formatException(error)
            lastAudioRecordError = lastException
            lastFailureReason = if (audioRecordStartedAt <= 0L) "audio_record_start_failed" else "audio_capture_failed"
            lastWakeProofResult = "fail:${error.javaClass.name}"
            machine.fail(lastFailureReason)
            Log.e(LOG_TAG, "audio_record_last_error=$lastAudioRecordError failure_reason=$lastFailureReason")
            writeStatus(lastFailureReason)
        } finally {
            try {
                recorder?.stop()
            } catch (_: Exception) {
            }
            recorder?.release()
        }
        return null
    }

    private fun recordInference(wake: WakeWordResult) {
        val now = System.currentTimeMillis()
        val wakeThreshold = currentWakeThreshold()
        lastInferenceAt = now
        inferenceCount += 1
        lastInferenceConfidence = wake.confidence.coerceIn(0.0, 1.0)
        maxObservedConfidence = maxOf(maxObservedConfidence, lastInferenceConfidence)
        lastInferenceThresholdCrossed = lastInferenceConfidence >= wakeThreshold
        lastInferenceRejectionReason = when {
            wake.detected -> ""
            !lastInferenceThresholdCrossed -> "below_threshold"
            else -> "state_machine_not_listening"
        }
        lastWakePass = lastInferenceThresholdCrossed
        lastWakeProofResult = if (lastWakePass) "threshold_crossed" else "listening:${lastInferenceRejectionReason}"
        synchronized(inferenceWindows) {
            inferenceWindows.addLast(JSONObject()
                .put("index", inferenceCount)
                .put("timestamp", now)
                .put("confidence", lastInferenceConfidence)
                .put("max_confidence", maxObservedConfidence)
                .put("threshold", wakeThreshold)
                .put("threshold_crossed", lastInferenceThresholdCrossed)
                .put("detected", wake.detected)
                .put("detection_count", wakeDetectionCount)
                .put("last_detection_timestamp", lastWakeDetectionAt)
                .put("rejection_reason", lastInferenceRejectionReason))
            while (inferenceWindows.size > 24) inferenceWindows.removeFirst()
        }
    }

    private fun postWakeDetectedEvent(wake: WakeWordResult) {
        val origin = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(PREF_ORIGIN, BuildConfig.DEFAULT_SERVER_URL)
            .orEmpty()
            .ifBlank { BuildConfig.DEFAULT_SERVER_URL }
        val now = System.currentTimeMillis()
        val event = VoiceWakeEvent(
            transcript = "",
            confidence = wake.confidence.coerceIn(0.0, 1.0),
            startedAt = now,
            endedAt = now,
            buildId = BuildConfig.NATIVE_BUILD_ID,
            sessionId = UUID.randomUUID().toString(),
        )
        thread(name = "hermes-wake-detected-event") {
            val result = router.dispatchWakeDetected(origin, event, currentProviders().wake.name)
            wakeDetectedEventEmittedAt = System.currentTimeMillis()
            rememberEvent("wake_event_delivered_to_app", JSONObject()
                .put("delivery", if (result.ok) "backend" else "none")
                .put("event_type", "wake_detected"))
            machine.dispatched(result.toJson().put("event_type", "wake_detected"))
            if (!result.ok) {
                machine.fail("wake_detected_post_failed:${result.error.ifBlank { "http_${result.statusCode}" }}")
            }
            writeStatus("wake_detected_event")
        }
    }

    private fun bringAppToForegroundAfterWake(wake: WakeWordResult) {
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        if (!prefs.getBoolean(PREF_LAUNCH_APP_ON_WAKE, true)) return
        val intent = Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            .putExtra("native_screen", "wake-world")
            .putExtra("wake_source", "hermes_voice_wake")
            .putExtra("wake_confidence", wake.confidence)
        try {
            startActivity(intent)
            rememberEvent("wake_app_foreground_requested", JSONObject().put("confidence", wake.confidence))
            Log.i(LOG_TAG, "wake_app_foreground_requested=true confidence=${wake.confidence}")
        } catch (error: Exception) {
            lastException = formatException(error)
            rememberEvent("wake_app_foreground_failed", JSONObject().put("error", error.javaClass.simpleName))
            Log.w(LOG_TAG, "wake_app_foreground_requested=false error=$lastException")
        }
    }

    private fun scheduleSelfRestart(reason: String) {
        val origin = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(PREF_ORIGIN, BuildConfig.DEFAULT_SERVER_URL)
            .orEmpty()
            .ifBlank { BuildConfig.DEFAULT_SERVER_URL }
        val intent = Intent(this, HermesVoiceWakeService::class.java)
            .setAction(ACTION_START)
            .putExtra(EXTRA_ORIGIN, origin)
            .putExtra("restart_reason", reason)
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) PendingIntent.FLAG_IMMUTABLE else 0
        val pending = PendingIntent.getService(this, NOTIFICATION_ID + 1, intent, flags)
        val alarm = getSystemService(AlarmManager::class.java)
        val triggerAt = SystemClock.elapsedRealtime() + 1500L
        try {
            alarm?.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, triggerAt, pending)
        } catch (_: Exception) {
            alarm?.set(AlarmManager.ELAPSED_REALTIME_WAKEUP, triggerAt, pending)
        }
    }

    private fun postVoiceEvent(origin: String, event: VoiceWakeEvent, falseWakeAudio: ShortArray) {
        thread(name = "hermes-voice-wake-event") {
            val result = router.dispatch(origin, event, currentProviders().transcriber.name)
            if (result.ok) voiceCommandEventDispatchedAt = System.currentTimeMillis()
            rememberEvent("wake_event_delivered_to_app", JSONObject()
                .put("delivery", if (result.ok) "backend" else "none")
                .put("event_type", "voice_command"))
            machine.dispatched(result.toJson())
            if (!result.ok) {
                captureFalseWake(
                    WakeWordResult(detected = true, confidence = event.confidence, audioWindow = falseWakeAudio),
                    falseWakeAudio,
                    event.transcript,
                    "no_hermes_intent",
                    event.startedAt,
                )
                machine.fail("voice_event_post_failed:${result.error.ifBlank { "http_${result.statusCode}" }}")
            }
            writeStatus(if (result.ok) "voice_command_event_dispatched" else "voice_command_event_dispatch_failed")
        }
    }

    private fun wakeWorldCommandForTranscript(transcript: String): String {
        val normalized = transcript
            .lowercase()
            .replace(Regex("[^a-z0-9 ]"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()
        return when (normalized) {
            "open wake word", "open wake world" -> "open_wake_world"
            "show diagnostics" -> "show_diagnostics"
            "train hermes wake", "train hermes" -> "train_hermes_wake"
            "stop listening" -> "stop_listening"
            "go home" -> "go_home"
            else -> ""
        }
    }

    private fun rememberEvent(type: String, detail: JSONObject = JSONObject()) {
        synchronized(recentEvents) {
            recentEvents.addLast(JSONObject()
                .put("type", type)
                .put("timestamp", System.currentTimeMillis())
                .put("detail", detail))
            while (recentEvents.size > RECENT_EVENT_MAX) recentEvents.removeFirst()
        }
    }

    private fun recentEventsJson(): JSONArray {
        val array = JSONArray()
        synchronized(recentEvents) {
            recentEvents.forEach { event -> array.put(JSONObject(event.toString())) }
        }
        return array
    }

    private fun writeStatus(reason: String = "") {
        val activeSelection = currentWakeModelSelection()
        val activeWakeEngine = activeSelection.engine
        val wakeDiagnostics = activeWakeEngine.diagnostics()
        val activeProviders = currentProviders()
        val wakeThreshold = currentWakeThreshold()
        val transcriptPolicy = configuredTranscriptPolicy(this)
        val personalizedSha256 = sha256OrBlank(personalizedModelFile)
        val modelPath = wakeDiagnostics.getString("selected_model_path")
        val modelExists = wakeDiagnostics.getBoolean("wake_model_exists")
        val modelShaMatch = personalizedSha256.equals(ACCEPTANCE_MODEL_SHA256, ignoreCase = true)
        val disabledReason = readinessDisabledReason(
            enabled = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).getBoolean(PREF_ENABLED, false),
            permissionGranted = hasRecordAudioPermission(),
            foregroundServiceRunning = running,
            wakeDiagnostics = wakeDiagnostics,
            modelPath = modelPath,
            modelExists = modelExists,
            modelShaMatch = modelShaMatch,
        )
        val now = System.currentTimeMillis()
        val audioRecordStarted = audioRecordStartedAt > 0L && lastAudioRecordError.isBlank()
        val audioCaptureAlive = running && audioRecordStarted && lastAudioFrameAt > 0L && now - lastAudioFrameAt <= 5_000L
        val localAsrDiagnostics = (activeProviders.transcriber as? LocalCommandTranscriptionEngine)?.diagnostics() ?: JSONObject()
        val onnxModelReady = wakeDiagnostics.optBoolean("onnx_runtime_available", false) &&
            activeProviders.wake.ready &&
            activeSelection.personalizedModelExists &&
            modelShaMatch
        val failureReason = failureReasonForStatus(
            permissionGranted = hasRecordAudioPermission(),
            foregroundServiceRunning = running,
            audioRecordStarted = audioRecordStarted,
            audioCaptureAlive = audioCaptureAlive,
            wakeDiagnostics = wakeDiagnostics,
            modelExists = modelExists,
            modelShaMatch = modelShaMatch,
        )
        val status = machine.snapshot(
            enabled = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).getBoolean(PREF_ENABLED, false),
            permissionGranted = hasRecordAudioPermission(),
            foregroundServiceRunning = running,
            wakeEngine = activeProviders.wake.name,
            wakeEngineReady = activeProviders.wake.ready,
            transcriptionEngine = activeProviders.transcriber.name,
            vadProvider = activeProviders.vad.name,
            wakeProvider = activeProviders.wake.name,
            asrProvider = activeProviders.transcriber.name,
            modelSource = activeProviders.modelSource,
            selectedModelPath = modelPath,
            debugVoiceModeEnabled = activeProviders.debugVoiceModeEnabled,
            batteryWarning = "Always-on microphone uses extra battery; disable Hermes Voice Wake when not needed.",
        )
            .put("reason", reason)
            .put("proof_schema", "hermes.wasm_agent.android_wake_proof.v1")
            .put("status_source", "live_service")
            .put("service_alive", running)
            .put("proof_session_active", proofSessionActive)
            .put("disabled_reason", disabledReason)
            .put("permission_foreground_service", hasManifestPermission(Manifest.permission.FOREGROUND_SERVICE))
            .put("permission_foreground_service_microphone", if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                hasManifestPermission(Manifest.permission.FOREGROUND_SERVICE_MICROPHONE)
            } else {
                true
            })
            .put("permission_post_notifications", if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
            } else {
                true
            })
            .put("audio_record_permission_granted", hasRecordAudioPermission())
            .put("audio_record_active", audioCaptureAlive)
            .put("audio_record_initialized", audioRecordInitializedAt > 0L)
            .put("audio_record_initialized_at", audioRecordInitializedAt)
            .put("audio_record_start_called", audioRecordStartCalledAt > 0L)
            .put("audio_record_start_called_at", audioRecordStartCalledAt)
            .put("audio_record_started", audioRecordStarted)
            .put("audio_capture_alive", audioCaptureAlive)
            .put("foreground_service_started", running)
            .put("audio_record_error", lastAudioRecordError)
            .put("audio_record_last_error", lastAudioRecordError)
            .put("audio_record_started_at", audioRecordStartedAt)
            .put("last_audio_frame_at", lastAudioFrameAt)
            .put("audio_read_calls", audioReadCalls)
            .put("audio_record_read_count", audioReadCalls)
            .put("audio_samples_read", audioSamplesRead)
            .put("audio_read_errors", audioReadErrors)
            .put("audio_sample_rate_hz", OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ)
            .put("audio_channels", 1)
            .put("audio_format", "pcm16_mono_16khz")
            .put("last_inference_at", lastInferenceAt)
            .put("last_inference_timestamp", lastInferenceAt)
            .put("inference_running", proofSessionActive && running && inferenceCount > 0L)
            .put("inference_count", inferenceCount)
            .put("last_confidence", lastInferenceConfidence)
            .put("last_wake_confidence", lastInferenceConfidence)
            .put("max_observed_confidence", maxObservedConfidence)
            .put("wake_threshold", wakeThreshold)
            .put("threshold", wakeThreshold)
            .put("proof_threshold_override", proofWakeThresholdOverride ?: JSONObject.NULL)
            .put("effective_wake_threshold", wakeThreshold)
            .put("threshold_margin", maxObservedConfidence - wakeThreshold)
            .put("threshold_policy_source", currentWakeThresholdSource())
            .put("policy_source", currentWakeThresholdSource())
            .put("vad_rms_threshold", configuredVadRmsThreshold(this))
            .put("vad_peak_threshold", configuredVadPeakThreshold(this))
            .put("transcript_timeout_ms", configuredTranscriptTimeoutMs(this))
            .put("transcript_min_length_ms", transcriptPolicy.minimumLengthMs)
            .put("transcript_complete_silence_ms", transcriptPolicy.completeSilenceMs)
            .put("transcript_possible_silence_ms", transcriptPolicy.possiblyCompleteSilenceMs)
            .put("transcript_accept_partial", transcriptPolicy.acceptPartialResults)
            .put("transcript_engine", configuredTranscriptEngine(this))
            .put("local_asr_engine", localAsrDiagnostics.optString("local_asr_engine", activeProviders.transcriber.name))
            .put("local_asr_preferred_engine", localAsrDiagnostics.optString("local_asr_preferred_engine", configuredTranscriptEngine(this)))
            .put("local_asr_vosk_ready", localAsrDiagnostics.optBoolean("local_asr_vosk_ready", false))
            .put("local_asr_vosk_model_path", localAsrDiagnostics.optString("local_asr_vosk_model_path", "files/${LocalCommandTranscriptionEngine.MODEL_PATH}"))
            .put("local_asr_vosk_error", localAsrDiagnostics.optString("local_asr_vosk_error", ""))
            .put("last_asr_engine", lastAsrEngine)
            .put("last_asr_latency_ms", lastAsrLatencyMs)
            .put("last_asr_audio_captured_ms", lastAsrAudioCapturedMs)
            .put("last_asr_partial_transcript", lastAsrPartialTranscript)
            .put("wake_cooldown_ms", WAKE_COOLDOWN_MS)
            .put("wake_cooldown_until", wakeCooldownUntil)
            .put("tuning_session_id", getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).getString(PREF_TUNING_SESSION_ID, "").orEmpty())
            .put("last_inference_threshold_crossed", lastInferenceThresholdCrossed)
            .put("threshold_crossed", lastInferenceThresholdCrossed)
            .put("last_inference_rejection_reason", lastInferenceRejectionReason)
            .put("rejection_reason", lastInferenceRejectionReason)
            .put("last_transcript_result", lastTranscriptResult)
            .put("wake_detection_count", wakeDetectionCount)
            .put("last_wake_detection_at", lastWakeDetectionAt)
            .put("last_detection_timestamp", lastWakeDetectionAt)
            .put("wake_detected_event_emitted", wakeDetectedEventEmittedAt > 0L)
            .put("wake_detected", wakeDetectionCount > 0L || wakeDetectedEventEmittedAt > 0L)
            .put("wake_detected_event_emitted_at", wakeDetectedEventEmittedAt)
            .put("command_capture_started", commandCaptureStartedAt > 0L)
            .put("command_capture_started_at", commandCaptureStartedAt)
            .put("voice_command_event_dispatched", voiceCommandEventDispatchedAt > 0L)
            .put("voice_command_event_dispatched_at", voiceCommandEventDispatchedAt)
            .put("wake_confidence_observed", inferenceCount > 0L)
            .put("confidence_metrics", confidenceMetricsJson())
            .put("latest_inference_window", latestInferenceWindowJson())
            .put("inference_windows", inferenceWindowsJson())
            .put("wake_proof_pass", lastWakePass)
            .put("wake_proof_result", lastWakeProofResult)
            .put("model_sha256", personalizedSha256)
            .put("model_sha", personalizedSha256)
            .put("expected_model_sha256", ACCEPTANCE_MODEL_SHA256)
            .put("model_sha_match", modelShaMatch)
            .put("acceptance_model_sha256_match", modelShaMatch)
            .put("bundled_model_available", bundledHermesModelAvailable())
            .put("model_asset_found", bundledHermesModelAvailable())
            .put("onnx_runtime_available", wakeDiagnostics.getBoolean("onnx_runtime_available"))
            .put("onnx_model_ready", onnxModelReady)
            .put("onnx_runtime_error", wakeDiagnostics.getString("onnx_runtime_error"))
            .put("wake_engine_error", wakeDiagnostics.getString("wake_engine_error"))
            .put("failure_reason", failureReason)
            .put("last_exception", if (lastException.isBlank()) JSONObject.NULL else lastException)
            .put("model_source", activeSelection.source)
            .put("base_model_exists", activeSelection.baseModelExists)
            .put("personalized_model_exists", activeSelection.personalizedModelExists)
            .put("model_path", modelPath)
            .put("selected_model_path", modelPath)
            .put("model_exists", modelExists)
            .put("wake_model_exists", modelExists)
            .put("last_model_load_result", wakeDiagnostics.getString("last_model_load_result"))
            .put("last_model_load_error", wakeDiagnostics.getString("last_model_load_error"))
            .put("wake_model", wakeDiagnostics
                .put("base_model_exists", activeSelection.baseModelExists)
                .put("personalized_model_exists", activeSelection.personalizedModelExists))
            .put("wake_world_schema", "hermes.wasm_agent.android_wake_world_state.v1")
            .put("app_version", packageManager.getPackageInfo(packageName, 0).versionName.orEmpty())
            .put("android_build_id", BuildConfig.NATIVE_BUILD_ID)
            .put("loaded_model_sha", personalizedSha256)
            .put("expected_model_sha", ACCEPTANCE_MODEL_SHA256)
            .put("prototype_threshold", proofWakeThresholdOverride ?: JSONObject.NULL)
            .put("wake_service_ready", running && hasRecordAudioPermission())
            .put("wake_service_enabled", getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).getBoolean(PREF_ENABLED, false))
            .put("foreground_service_active", running)
            .put("foreground_service_running", running)
            .put("listener_lane", if (running) "foreground_service" else "off")
            .put("listener_mode", when (machine.state) {
                com.colmeio.wasmagent.voice.VoiceWakeState.LISTENING -> "standby"
                com.colmeio.wasmagent.voice.VoiceWakeState.CAPTURING,
                com.colmeio.wasmagent.voice.VoiceWakeState.TRANSCRIBING -> "command_capture"
                com.colmeio.wasmagent.voice.VoiceWakeState.SENT -> "standby"
                else -> "off"
            })
            .put("app_visible", true)
            .put("screen_locked", JSONObject.NULL)
            .put("service_bound_to_app", true)
            .put("wake_event_delivery", "backend")
            .put("duplicate_listener_guard_active", true)
            .put("max_confidence_since_start", maxObservedConfidence)
            .put("wake_hit_count", wakeDetectionCount)
            .put("false_wake_count", falseWakeCount)
            .put("command_capture_active", machine.state == com.colmeio.wasmagent.voice.VoiceWakeState.CAPTURING || machine.state == com.colmeio.wasmagent.voice.VoiceWakeState.TRANSCRIBING)
            .put("transcript_gate_last_result", lastTranscriptResult.ifBlank { machine.lastTranscriptStatus })
            .put("last_rejection_reason", reason.ifBlank { lastInferenceRejectionReason.ifBlank { machine.lastError } })
            .put("last_wake_at", machine.lastWakeAt)
            .put("last_false_wake_at", lastFalseWakeAt)
            .put("standby_restored", standbyRestoredAt > 0L && machine.state == com.colmeio.wasmagent.voice.VoiceWakeState.LISTENING)
            .put("permission_state", JSONObject()
                .put("record_audio", if (hasRecordAudioPermission()) "granted" else "missing")
                .put("post_notifications", if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) "missing" else "granted"))
            .put("battery_optimization_state", "unknown")
            .put("recent_events", recentEventsJson())
        val falseWakeDiagnostics = FalseWakeStore.diagnostics(this)
        falseWakeDiagnostics.keys().forEach { key ->
            status.put(key, falseWakeDiagnostics.opt(key))
        }
        statusFile(this).apply {
            parentFile?.mkdirs()
            writeText(status.toString(2))
        }
    }

    private fun confidenceMetricsJson(): JSONObject = JSONObject()
        .put("last_confidence", lastInferenceConfidence)
        .put("max_confidence", maxObservedConfidence)
        .put("threshold", currentWakeThreshold())
        .put("proof_threshold_override", proofWakeThresholdOverride ?: JSONObject.NULL)
        .put("effective_wake_threshold", currentWakeThreshold())
        .put("threshold_margin", maxObservedConfidence - currentWakeThreshold())
        .put("threshold_policy_source", currentWakeThresholdSource())
        .put("threshold_crossed", lastInferenceThresholdCrossed)
        .put("wake_detection_count", wakeDetectionCount)
        .put("last_detection_timestamp", lastWakeDetectionAt)
        .put("rejection_reason", lastInferenceRejectionReason)

    private fun latestInferenceWindowJson(): JSONObject {
        synchronized(inferenceWindows) {
            return if (inferenceWindows.isEmpty()) JSONObject()
                .put("index", 0)
                .put("timestamp", 0)
                .put("confidence", lastInferenceConfidence)
                .put("max_confidence", maxObservedConfidence)
                .put("threshold", currentWakeThreshold())
                .put("proof_threshold_override", proofWakeThresholdOverride ?: JSONObject.NULL)
                .put("effective_wake_threshold", currentWakeThreshold())
                .put("threshold_margin", maxObservedConfidence - currentWakeThreshold())
                .put("threshold_policy_source", currentWakeThresholdSource())
                .put("threshold_crossed", lastInferenceThresholdCrossed)
                .put("detected", false)
                .put("detection_count", wakeDetectionCount)
                .put("last_detection_timestamp", lastWakeDetectionAt)
                .put("rejection_reason", lastInferenceRejectionReason)
            else JSONObject(inferenceWindows.last().toString())
        }
    }

    private fun inferenceWindowsJson(): JSONArray {
        val array = JSONArray()
        synchronized(inferenceWindows) {
            inferenceWindows.forEach { item -> array.put(JSONObject(item.toString())) }
        }
        return array
    }

    private fun falseWakeReasonForTranscript(error: String): String =
        when {
            error.contains("silence", ignoreCase = true) -> "silence_after_wake"
            error.contains("no_match", ignoreCase = true) ||
                error.contains("empty", ignoreCase = true) ||
                error.isBlank() -> "transcript_gate_rejected"
            else -> "transcript_gate_rejected"
        }

    private fun captureFalseWake(
        wake: WakeWordResult,
        audioWindow: ShortArray,
        transcript: String,
        rejectionReason: String,
        timestamp: Long,
    ) {
        val modelSha = sha256OrBlank(personalizedModelFile)
        falseWakeCount += 1
        lastFalseWakeAt = timestamp
        wakeCooldownUntil = System.currentTimeMillis() + WAKE_COOLDOWN_MS
        val metadata = JSONObject()
            .put("id", "fw-$timestamp-${UUID.randomUUID()}")
            .put("timestamp", timestamp)
            .put("wake_confidence", wake.confidence.coerceIn(0.0, 1.0))
            .put("threshold", currentWakeThreshold())
            .put("wake_cooldown_ms", WAKE_COOLDOWN_MS)
            .put("model_sha", modelSha)
            .put("model_sha256", modelSha)
            .put("transcript_result", transcript)
            .put("rejection_reason", rejectionReason)
            .put("wake_provider", currentProviders().wake.name)
            .put("asr_provider", currentProviders().transcriber.name)
            .put("build_id", BuildConfig.NATIVE_BUILD_ID)
        FalseWakeStore.captureAsync(this, metadata, audioWindow)
        rememberEvent("false_wake_saved", JSONObject()
            .put("reason", rejectionReason)
            .put("false_wake_count", falseWakeCount))
    }

    private class RollingPcm16Window(private val maxSamples: Int) {
        private val samples = ShortArray(maxSamples)
        private var size = 0
        private var writeIndex = 0

        fun append(frame: ShortArray) {
            frame.forEach { sample ->
                samples[writeIndex] = sample
                writeIndex = (writeIndex + 1) % maxSamples
                if (size < maxSamples) size += 1
            }
        }

        fun snapshot(): ShortArray {
            val out = ShortArray(size)
            val start = (writeIndex - size + maxSamples) % maxSamples
            for (index in 0 until size) {
                out[index] = samples[(start + index) % maxSamples]
            }
            return out
        }
    }

    private fun sha256OrBlank(file: File): String {
        if (!file.isFile || file.length() <= 0L) return ""
        return try {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    digest.update(buffer, 0, read)
                }
            }
            digest.digest().joinToString("") { "%02x".format(it) }
        } catch (_: Exception) {
            ""
        }
    }

    private fun readinessDisabledReason(
        enabled: Boolean,
        permissionGranted: Boolean,
        foregroundServiceRunning: Boolean,
        wakeDiagnostics: org.json.JSONObject,
        modelPath: String,
        modelExists: Boolean,
        modelShaMatch: Boolean,
    ): String {
        if (!permissionGranted) return "record_audio_permission_missing"
        if (!enabled) return "voice_wake_disabled"
        if (!foregroundServiceRunning) return "foreground_service_not_running"
        if (!wakeDiagnostics.optBoolean("onnx_runtime_available", false)) return "onnx_runtime_unavailable"
        if (modelPath != OpenWakeWordOnnxEngine.APP_PRIVATE_PERSONALIZED_MODEL_PATH) return "personalized_model_path_mismatch"
        if (!modelExists) return "personalized_model_missing"
        if (!modelShaMatch) return "model_sha_mismatch"
        if (!wakeDiagnostics.optBoolean("wake_engine_ready", false)) return "wake_engine_not_ready"
        if (audioRecordStartedAt <= 0L || lastAudioRecordError.isNotBlank()) return "audio_record_not_started"
        if (inferenceCount <= 0L) return "inference_not_observed"
        return ""
    }

    private fun failureReasonForStatus(
        permissionGranted: Boolean,
        foregroundServiceRunning: Boolean,
        audioRecordStarted: Boolean,
        audioCaptureAlive: Boolean,
        wakeDiagnostics: JSONObject,
        modelExists: Boolean,
        modelShaMatch: Boolean,
    ): String {
        if (lastFailureReason.isNotBlank()) return lastFailureReason
        if (!permissionGranted) return "record_audio_permission_missing"
        if (!foregroundServiceRunning) return "foreground_service_not_started"
        if (!modelExists) return "onnx_model_missing"
        if (!wakeDiagnostics.optBoolean("onnx_runtime_available", false)) return "onnx_model_load_failed"
        if (!wakeDiagnostics.optBoolean("wake_engine_ready", false)) return "onnx_model_load_failed"
        if (!modelShaMatch) return "model_sha_mismatch"
        if (lastAudioRecordError.isNotBlank() && audioRecordStartedAt <= 0L) return "audio_record_start_failed"
        if (!audioRecordStarted) return "audio_record_init_pending"
        if (!audioCaptureAlive) return "audio_capture_waiting_for_frame"
        if (inferenceCount <= 0L) return "inference_not_observed"
        return ""
    }

    private fun formatException(error: Exception): String =
        "${error.javaClass.name}${error.message?.let { ": $it" } ?: ""}".take(500)

    private fun currentWakeModelSelection(): WakeModelSelection =
        wakeModelSelection ?: refreshWakeModelSelection()

    private fun refreshWakeModelSelection(): WakeModelSelection =
        WakeModelSelector.select(personalizedModelFile, baseModelFile, currentWakeThreshold()).also {
            wakeModelSelection = it
        }

    private fun currentWakeThreshold(): Double = proofWakeThresholdOverride ?: configuredWakeThreshold(this)

    private fun currentWakeThresholdSource(): String {
        if (proofWakeThresholdOverride != null) return THRESHOLD_SOURCE_PROOF_INTENT_OVERRIDE
        val stored = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(PREF_WAKE_THRESHOLD_SOURCE, "")
            .orEmpty()
        return when (stored) {
            THRESHOLD_SOURCE_REMOTE_CONFIG, "downloaded_operation" -> THRESHOLD_SOURCE_REMOTE_CONFIG
            else -> THRESHOLD_SOURCE_NATIVE_DEFAULT
        }
    }

    private fun currentProviders(): VoiceProviderSet =
        providers ?: selectProviders(false, currentWakeModelSelection()).also { providers = it }

    private fun selectProviders(requestedDebugVoiceMode: Boolean, activeSelection: WakeModelSelection): VoiceProviderSet =
        VoiceProviderSelector.select(
            requestedDebugVoiceMode = requestedDebugVoiceMode,
            modelReady = activeSelection.ready,
            modelMissing = activeSelection.source == WakeModelSelector.NONE_SOURCE,
            productionWakeEngine = activeSelection.engine,
            productionTranscriber = LocalCommandTranscriptionEngine(
                this,
                preferredEngine = configuredTranscriptEngine(this),
            ),
            modelSource = activeSelection.source,
            productionVad = EnergyVoiceVad(
                configuredVadRmsThreshold(this),
                configuredVadPeakThreshold(this),
            ),
        )

    private fun installBundledHermesModelIfPresent() {
        installBundledHermesModelIfPresent(baseModelFile) { path -> assets.open(path) }
    }

    private fun bundledHermesModelAvailable(): Boolean {
        return bundledHermesModelAvailable(assets)
    }

    private fun hasRecordAudioPermission(): Boolean {
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.M ||
            checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
    }

    private fun hasManifestPermission(permission: String): Boolean {
        return try {
            val info = packageManager.getPackageInfo(packageName, PackageManager.GET_PERMISSIONS)
            info.requestedPermissions?.contains(permission) == true
        } catch (_: Exception) {
            false
        }
    }

    private fun notification(text: String): Notification {
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        return builder
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("WASM Agent listening for Hermes")
            .setContentText(text)
            .setOngoing(true)
            .setContentIntent(PendingIntent.getActivity(
                this,
                0,
                Intent(this, MainActivity::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            ))
            .build()
    }

    override fun onCreate() {
        super.onCreate()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel(
                CHANNEL_ID,
                "Hermes Voice Wake",
                NotificationManager.IMPORTANCE_LOW,
            ))
        }
    }
}
