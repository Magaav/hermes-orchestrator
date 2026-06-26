package com.colmeio.wasmagent

import android.Manifest
import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.AssetManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.IBinder
import android.os.SystemClock
import android.provider.MediaStore
import android.provider.Settings
import android.util.Log
import com.colmeio.wasmagent.shell.NativeShellV2Activity
import com.colmeio.wasmagent.observability.NativeTelemetryBus
import com.colmeio.wasmagent.voice.EnergyVoiceVad
import com.colmeio.wasmagent.voice.FalseWakeStore
import com.colmeio.wasmagent.voice.LocalCommandTranscriptionEngine
import com.colmeio.wasmagent.voice.OpenWakeWordBundleEngine
import com.colmeio.wasmagent.voice.OpenWakeWordOnnxEngine
import com.colmeio.wasmagent.voice.PartialTranscriptionEngine
import com.colmeio.wasmagent.voice.WakeWordResult
import com.colmeio.wasmagent.voice.WakeConfirmationGate
import com.colmeio.wasmagent.voice.WakeModelSelection
import com.colmeio.wasmagent.voice.WakeModelSelector
import com.colmeio.wasmagent.voice.VoiceCommandNormalizer
import com.colmeio.wasmagent.voice.VoiceCommandRouter
import com.colmeio.wasmagent.voice.VoiceProviderSelector
import com.colmeio.wasmagent.voice.VoiceProviderSet
import com.colmeio.wasmagent.voice.VoiceWakeEvent
import com.colmeio.wasmagent.voice.VoiceWakeStateMachine
import com.colmeio.wasmagent.voice.TranscriptionPolicy
import com.colmeio.wasmagent.voice.TranscriptionResult
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.security.MessageDigest
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException
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
        const val PREF_INSTALL_ID = "install_id"
        const val PREF_ENABLED = "voice_wake_enabled"
        const val PREF_ORIGIN = "voice_wake_origin"
        const val PREF_WAKE_THRESHOLD = "voice_wake_threshold"
        const val PREF_WAKE_THRESHOLD_SOURCE = "voice_wake_threshold_source"
        const val PREF_WAKE_PHRASE = "voice_wake_phrase"
        const val PREF_WAKE_COOLDOWN_MS = "voice_wake_cooldown_ms"
        const val PREF_WAKE_CONFIRMATION_FRAMES = "voice_wake_confirmation_frames"
        const val PREF_WAKE_CONFIRMATION_WINDOW_MS = "voice_wake_confirmation_window_ms"
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
        const val PREF_TRANSCRIPT_ATTEMPT_PLAN = "voice_wake_transcript_attempt_plan"
        const val PREF_FOREGROUND_UI_ACTIVE_UNTIL = "voice_wake_foreground_ui_active_until"
        const val DEFAULT_WAKE_THRESHOLD = 0.98
        const val DEFAULT_WAKE_PHRASE = "alexa"
        const val DEFAULT_VAD_RMS_THRESHOLD = 0.001
        const val DEFAULT_VAD_PEAK_THRESHOLD = 100
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
        const val DEFAULT_WAKE_COOLDOWN_MS = 3_000L
        const val DEFAULT_WAKE_CONFIRMATION_FRAMES = 2
        const val DEFAULT_WAKE_CONFIRMATION_WINDOW_MS = 1_800L
        private const val AUDIO_CAPTURE_ALIVE_WINDOW_MS = 5_000L
        private const val AUDIO_FRAME_STALE_RESTART_MS = 8_000L
        private const val AUDIO_WATCHDOG_INTERVAL_MS = 2_000L
        private const val FALSE_WAKE_STORM_WINDOW_MS = 120_000L
        private const val FALSE_WAKE_STORM_LIMIT = 5
        private const val FOREGROUND_UI_INFERENCE_SKIP_MS = 2_500L
        private const val FOREGROUND_UI_ACTIVE_PREF_READ_INTERVAL_MS = 250L
        private const val MIN_WAKE_THRESHOLD = 0.05
        private const val MAX_WAKE_THRESHOLD = 0.999
        private const val ACCEPTANCE_MODEL_SHA256 = "2abbebf21610f91f8d1fcfc12ac92f8ec19dc1191f3c90dbda4cba46e71027b2"

        fun statusFile(context: Context): File = File(context.filesDir, "native-diagnostics/voice-wake.json")
        fun lifecycleFile(context: Context): File = File(context.filesDir, "native-diagnostics/voice-wake-lifecycle.json")

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

        fun configuredWakePhrase(context: Context): String {
            val raw = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .getString(PREF_WAKE_PHRASE, DEFAULT_WAKE_PHRASE)
                .orEmpty()
                .trim()
                .lowercase()
            return raw.takeIf { it.isNotBlank() }?.take(40) ?: DEFAULT_WAKE_PHRASE
        }

        fun configuredVadRmsThreshold(context: Context): Double {
            return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .getFloat(PREF_VAD_RMS_THRESHOLD, DEFAULT_VAD_RMS_THRESHOLD.toFloat())
                .toDouble()
                .coerceIn(0.001, 0.2)
        }

        fun configuredWakeCooldownMs(context: Context): Long {
            return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .getLong(PREF_WAKE_COOLDOWN_MS, DEFAULT_WAKE_COOLDOWN_MS)
                .coerceIn(500L, 60_000L)
        }

        fun configuredWakeConfirmationFrames(context: Context): Int {
            return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .getInt(PREF_WAKE_CONFIRMATION_FRAMES, DEFAULT_WAKE_CONFIRMATION_FRAMES)
                .coerceIn(1, 5)
        }

        fun configuredWakeConfirmationWindowMs(context: Context): Long {
            return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .getLong(PREF_WAKE_CONFIRMATION_WINDOW_MS, DEFAULT_WAKE_CONFIRMATION_WINDOW_MS)
                .coerceIn(150L, 2_000L)
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
                attemptPlan = parseJsonObject(prefs.getString(PREF_TRANSCRIPT_ATTEMPT_PLAN, "{}").orEmpty()),
            )
        }

        fun configuredTranscriptAttemptPlan(context: Context): JSONObject {
            val raw = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .getString(PREF_TRANSCRIPT_ATTEMPT_PLAN, "{}")
                .orEmpty()
            return parseJsonObject(raw)
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

        private fun parseJsonObject(raw: String): JSONObject {
            return try {
                val parsed = JSONObject(raw)
                parsed
            } catch (_: Exception) {
                JSONObject()
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

        internal fun installBundledVoskModelIfPresent(
            modelDir: File,
            assetManager: AssetManager,
        ): Boolean {
            return try {
                if (!assetDirectoryHasFiles(assetManager, LocalCommandTranscriptionEngine.ASSET_MODEL_PATH)) return false
                if (modelDir.exists() && modelDir.isDirectory && modelDir.list()?.isNotEmpty() == true) return false
                modelDir.deleteRecursively()
                copyAssetDirectory(assetManager, LocalCommandTranscriptionEngine.ASSET_MODEL_PATH, modelDir)
                modelDir.exists() && modelDir.isDirectory && modelDir.list()?.isNotEmpty() == true
            } catch (_: Exception) {
                false
            }
        }

        internal fun bundledVoskModelAvailable(assets: AssetManager): Boolean {
            return assetDirectoryHasFiles(assets, LocalCommandTranscriptionEngine.ASSET_MODEL_PATH)
        }

        private fun assetDirectoryHasFiles(assetManager: AssetManager, path: String): Boolean {
            return try {
                val children = assetManager.list(path).orEmpty()
                children.any { child ->
                    val childPath = "$path/$child"
                    val grandChildren = assetManager.list(childPath).orEmpty()
                    grandChildren.isNotEmpty() || try {
                        assetManager.open(childPath).use { input -> input.read() >= 0 }
                    } catch (_: Exception) {
                        false
                    }
                }
            } catch (_: Exception) {
                false
            }
        }

        private fun copyAssetDirectory(assetManager: AssetManager, assetPath: String, targetDir: File) {
            val children = assetManager.list(assetPath).orEmpty()
            targetDir.mkdirs()
            for (child in children) {
                val childAssetPath = "$assetPath/$child"
                val childTarget = File(targetDir, child)
                val grandChildren = assetManager.list(childAssetPath).orEmpty()
                if (grandChildren.isNotEmpty()) {
                    copyAssetDirectory(assetManager, childAssetPath, childTarget)
                } else {
                    childTarget.parentFile?.mkdirs()
                    assetManager.open(childAssetPath).use { input ->
                        FileOutputStream(childTarget).use { output -> input.copyTo(output) }
                    }
                }
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
    @Volatile private var watchdogWorker: Thread? = null
    @Volatile private var watchdogGeneration: Long = 0L
    @Volatile private var activeWatchdogGeneration: Long = 0L
    @Volatile private var watchdogLastProgressAt: Long = 0L
    @Volatile private var watchdogLastAudioReadCalls: Long = 0L
    @Volatile private var watchdogLastInferenceCount: Long = 0L
    @Volatile private var activeRecorder: AudioRecord? = null
    private val personalizedModelFile by lazy { File(filesDir, "voice/hermes.onnx") }
    private val baseModelFile by lazy { File(filesDir, "voice/base_hermes.onnx") }
    private val voskModelDir by lazy { File(filesDir, LocalCommandTranscriptionEngine.MODEL_PATH) }
    @Volatile private var wakeModelSelection: WakeModelSelection? = null
    private val router = VoiceCommandRouter()
    private val wakeConfirmationGate = WakeConfirmationGate()
    @Volatile private var providers: VoiceProviderSet? = null
    @Volatile private var audioRecordInitializedAt: Long = 0
    @Volatile private var audioRecordStartCalledAt: Long = 0
    @Volatile private var audioRecordStartedAt: Long = 0
    @Volatile private var lastAudioFrameAt: Long = 0
    @Volatile private var audioReadCalls: Long = 0
    @Volatile private var audioSamplesRead: Long = 0
    @Volatile private var audioReadErrors: Long = 0
    @Volatile private var audioLoopStallCount: Long = 0
    @Volatile private var lastAudioLoopStallAt: Long = 0
    @Volatile private var audioSourceIndex: Int = 0
    @Volatile private var activeAudioSource: Int = MediaRecorder.AudioSource.VOICE_RECOGNITION
    @Volatile private var activeAudioSourceName: String = "VOICE_RECOGNITION"
    @Volatile private var audioSourceRestartCount: Long = 0
    @Volatile private var lastWakeFramePeak: Int = 0
    @Volatile private var maxWakeFramePeak: Int = 0
    @Volatile private var lastWakeFrameRms: Double = 0.0
    @Volatile private var maxWakeFrameRms: Double = 0.0
    @Volatile private var vadPassCount: Long = 0
    @Volatile private var vadRejectCount: Long = 0
    @Volatile private var lastVadSpeech: Boolean = false
    @Volatile private var lastInferenceAt: Long = 0
    @Volatile private var inferenceCount: Long = 0
    @Volatile private var lastInferenceConfidence: Double = 0.0
    @Volatile private var maxObservedConfidence: Double = 0.0
    @Volatile private var lastInferenceThresholdCrossed: Boolean = false
    @Volatile private var lastInferenceRejectionReason: String = "inference_not_started"
    @Volatile private var rawWakeDetectionCount: Long = 0
    @Volatile private var lastRawWakeDetectionAt: Long = 0
    @Volatile private var wakeDetectionCount: Long = 0
    @Volatile private var lastWakeDetectionAt: Long = 0
    @Volatile private var wakeCooldownUntil: Long = 0
    @Volatile private var lastProofStatusWriteAt: Long = 0
    @Volatile private var lastLifecycleInferenceWriteAt: Long = 0
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
    @Volatile private var lastAsrDiagnostics: String = "{}"
    @Volatile private var lastNormalizedTranscript: String = ""
    @Volatile private var lastVoiceCommand: String = ""
    @Volatile private var activeTranscriptCaptureId: Long = 0
    @Volatile private var falseWakeCount: Long = 0
    @Volatile private var lastFalseWakeAt: Long = 0
    @Volatile private var falseWakeStormStartedAt: Long = 0
    @Volatile private var falseWakeStormCount: Int = 0
    @Volatile private var falseWakeRunawayPausedAt: Long = 0
    @Volatile private var falseWakeRunawayReason: String = ""
    @Volatile private var standbyRestoredAt: Long = 0
    @Volatile private var lastListenerLoopStartedAt: Long = 0
    @Volatile private var lastListenerLoopEndedAt: Long = 0
    @Volatile private var lastListenExitReason: String = ""
    @Volatile private var lastListenExitDetail: String = ""
    @Volatile private var foregroundUiActiveUntilCache: Long = 0L
    @Volatile private var foregroundUiActiveUntilCacheReadAt: Long = 0L
    private val recentEvents = ArrayDeque<JSONObject>()

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        writeLifecycleMarker("on_start_command_entered", intent, startId)
        val requestedProofSession = intent?.getBooleanExtra(EXTRA_PROOF_SESSION, false) == true
        val proofSessionChanged = proofSessionActive != requestedProofSession
        if (proofSessionChanged) {
            proofSessionActive = requestedProofSession
            if (requestedProofSession) {
                rememberEvent("proof_session_started")
            } else {
                proofWakeThresholdOverride = null
                wakeModelSelection = null
                providers = null
                rememberEvent("proof_session_cleared")
            }
        }
        val thresholdChanged = applyWakeThresholdExtra(intent, proofSessionActive)
        val vadPolicyChanged = applyVadPolicyExtra(intent)
        val cooldownPolicyChanged = applyWakeCooldownPolicyExtra(intent)
        val confirmationPolicyChanged = applyWakeConfirmationPolicyExtra(intent)
        val transcriptPolicyChanged = applyTranscriptPolicyExtra(intent)
        when (intent?.action) {
            ACTION_STOP -> {
                writeLifecycleMarker("action_stop", intent, startId)
                rememberEvent("service_stopped", JSONObject().put("reason", "user_disabled"))
                stopListening("user_disabled")
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_STATUS -> {
                writeLifecycleMarker(if (running) "action_status_running" else "action_status_start_listening", intent, startId)
                if (running) {
                    writeStatus(
                        if (thresholdChanged || vadPolicyChanged || cooldownPolicyChanged || confirmationPolicyChanged || transcriptPolicyChanged) "wake_policy_updated"
                        else if (proofSessionChanged && proofSessionActive) "proof_session_started"
                        else if (proofSessionChanged) "proof_session_cleared"
                        else if (proofSessionActive) "proof_status_requested"
                        else ""
                    )
                } else {
                    startListening(intent?.getStringExtra(EXTRA_ORIGIN).orEmpty())
                }
            }
            else -> {
                writeLifecycleMarker("action_start_listening", intent, startId)
                startListening(
                    intent?.getStringExtra(EXTRA_ORIGIN).orEmpty(),
                    intent?.getBooleanExtra(EXTRA_DEBUG_VOICE_MODE, false) == true,
                )
            }
        }
        writeLifecycleMarker("on_start_command_returning_sticky", intent, startId)
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
            NativeTelemetryBus.publishPolicy("proof_threshold_override", threshold, configuredVadRmsThreshold(this), configuredVadPeakThreshold(this))
            return true
        }
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
            .putFloat(PREF_WAKE_THRESHOLD, threshold.toFloat())
            .putString(PREF_WAKE_THRESHOLD_SOURCE, THRESHOLD_SOURCE_REMOTE_CONFIG)
            .commit()
        wakeModelSelection = null
        providers = null
        rememberEvent("wake_policy_updated", JSONObject().put("threshold", threshold))
        Log.i(LOG_TAG, "threshold_policy_source=$THRESHOLD_SOURCE_REMOTE_CONFIG effective_wake_threshold=$threshold")
        NativeTelemetryBus.publishPolicy("remote_threshold", threshold, configuredVadRmsThreshold(this), configuredVadPeakThreshold(this))
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
            if (!value.isNaN()) {
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
            editor.putInt(PREF_VAD_PEAK_THRESHOLD, value)
            changed = true
        }
        if (extras.containsKey("tuning_session_id") || extras.containsKey("tuningSessionId")) {
            val raw = extras.get("tuning_session_id") ?: extras.get("tuningSessionId")
            val value = raw.toString().take(120)
            if (value.isNotBlank()) {
                editor.putString(PREF_TUNING_SESSION_ID, value)
                changed = true
            }
        }
        if (!changed) return false
        editor.commit()
        providers = null
        rememberEvent("wake_policy_updated", JSONObject()
            .put("vad_rms_threshold", configuredVadRmsThreshold(this))
            .put("vad_peak_threshold", configuredVadPeakThreshold(this)))
        NativeTelemetryBus.publishPolicy("vad_policy", currentWakeThreshold(), configuredVadRmsThreshold(this), configuredVadPeakThreshold(this))
        return true
    }

    private fun applyWakeCooldownPolicyExtra(intent: Intent?): Boolean {
        val extras = intent?.extras ?: return false
        if (!extras.containsKey("wake_cooldown_ms") && !extras.containsKey("wakeCooldownMs")) return false
        val raw = extras.get("wake_cooldown_ms") ?: extras.get("wakeCooldownMs")
        val value = when (raw) {
            is Number -> raw.toLong()
            is String -> raw.toLongOrNull() ?: DEFAULT_WAKE_COOLDOWN_MS
            else -> DEFAULT_WAKE_COOLDOWN_MS
        }.coerceIn(500L, 60_000L)
        if (configuredWakeCooldownMs(this) == value) return false
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
            .putLong(PREF_WAKE_COOLDOWN_MS, value)
            .apply()
        rememberEvent("wake_policy_updated", JSONObject().put("wake_cooldown_ms", value))
        return true
    }

    private fun applyWakeConfirmationPolicyExtra(intent: Intent?): Boolean {
        val extras = intent?.extras ?: return false
        val hasFrames = extras.containsKey("wake_confirmation_frames") ||
            extras.containsKey("wakeConfirmationFrames") ||
            extras.containsKey("wakeVerificationFrames")
        val hasWindow = extras.containsKey("wake_confirmation_window_ms") ||
            extras.containsKey("wakeConfirmationWindowMs") ||
            extras.containsKey("wakeVerificationWindowMs")
        if (!hasFrames && !hasWindow) return false
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val editor = prefs.edit()
        if (hasFrames) {
            val raw = extras.get("wake_confirmation_frames")
                ?: extras.get("wakeConfirmationFrames")
                ?: extras.get("wakeVerificationFrames")
            val value = when (raw) {
                is Number -> raw.toInt()
                is String -> raw.toIntOrNull() ?: DEFAULT_WAKE_CONFIRMATION_FRAMES
                else -> DEFAULT_WAKE_CONFIRMATION_FRAMES
            }.coerceIn(1, 5)
            editor.putInt(PREF_WAKE_CONFIRMATION_FRAMES, value)
        }
        if (hasWindow) {
            val raw = extras.get("wake_confirmation_window_ms")
                ?: extras.get("wakeConfirmationWindowMs")
                ?: extras.get("wakeVerificationWindowMs")
            val value = when (raw) {
                is Number -> raw.toLong()
                is String -> raw.toLongOrNull() ?: DEFAULT_WAKE_CONFIRMATION_WINDOW_MS
                else -> DEFAULT_WAKE_CONFIRMATION_WINDOW_MS
            }.coerceIn(150L, 2_000L)
            editor.putLong(PREF_WAKE_CONFIRMATION_WINDOW_MS, value)
        }
        editor.commit()
        wakeConfirmationGate.reset("policy_updated")
        rememberEvent("wake_policy_updated", JSONObject()
            .put("wake_confirmation_frames", configuredWakeConfirmationFrames(this))
            .put("wake_confirmation_window_ms", configuredWakeConfirmationWindowMs(this)))
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
        if (extras.containsKey("transcript_attempt_plan") || extras.containsKey("transcriptAttemptPlan") || extras.containsKey("transcriptPlan")) {
            val raw = extras.get("transcript_attempt_plan") ?: extras.get("transcriptAttemptPlan") ?: extras.get("transcriptPlan")
            val value = normalizeTranscriptAttemptPlan(raw)
            if (value.isNotBlank() && prefs.getString(PREF_TRANSCRIPT_ATTEMPT_PLAN, "{}") != value) {
                editor.putString(PREF_TRANSCRIPT_ATTEMPT_PLAN, value)
                changed = true
            }
        }
        if (!changed) return false
        editor.apply()
        providers = null
        if (commandCaptureStartedAt <= 0L) {
            lastTranscriptResult = ""
            lastAsrEngine = ""
            lastAsrLatencyMs = 0L
            lastAsrAudioCapturedMs = 0L
            lastAsrPartialTranscript = ""
            lastAsrDiagnostics = "{}"
        }
        val policy = configuredTranscriptPolicy(this)
        rememberEvent("transcript_policy_updated", JSONObject()
            .put("transcript_timeout_ms", configuredTranscriptTimeoutMs(this))
            .put("transcript_min_length_ms", policy.minimumLengthMs)
            .put("transcript_complete_silence_ms", policy.completeSilenceMs)
            .put("transcript_possible_silence_ms", policy.possiblyCompleteSilenceMs)
            .put("transcript_accept_partial", policy.acceptPartialResults)
            .put("transcript_engine", configuredTranscriptEngine(this))
            .put("transcript_attempt_plan", configuredTranscriptAttemptPlan(this)))
        return true
    }

    private fun normalizeTranscriptAttemptPlan(raw: Any?): String {
        return try {
            val parsed = when (raw) {
                is JSONObject -> raw
                is String -> JSONObject(raw)
                else -> JSONObject(raw?.toString().orEmpty())
            }
            if (!parsed.has("attempts") && !parsed.has("androidSpeechLanguages") && !parsed.has("android_speech_languages")) {
                ""
            } else {
                parsed.toString()
            }
        } catch (_: Exception) {
            ""
        }
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
        installBundledVoskModelIfPresent()
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
            val activeWorker = worker
            val now = System.currentTimeMillis()
            val audioStartAgeMs = if (audioRecordStartedAt > 0L) now - audioRecordStartedAt else 0L
            val staleStartedCapture = audioRecordStartedAt > 0L &&
                lastAudioFrameAt <= 0L &&
                audioStartAgeMs >= AUDIO_FRAME_STALE_RESTART_MS
            if (activeWorker == null || !activeWorker.isAlive || staleStartedCapture) {
                rememberEvent("stale_listener_worker_recovered", JSONObject().put("requested_origin", selectedOrigin))
                running = false
                if (staleStartedCapture) {
                    lastAudioRecordError = "audio_capture_no_frames:${audioStartAgeMs}ms"
                    lastFailureReason = "audio_capture_no_frames"
                    rotateWakeAudioSource(lastFailureReason)
                    try {
                        activeRecorder?.stop()
                    } catch (_: Exception) {
                    }
                }
                if (activeWorker != null && activeWorker.isAlive) {
                    try {
                        activeWorker.join(1_000)
                    } catch (_: InterruptedException) {
                        Thread.currentThread().interrupt()
                        return
                    }
                }
                if (worker === activeWorker) worker = null
                activeRecorder = null
            } else {
                rememberEvent("duplicate_listener_prevented", JSONObject().put("requested_origin", selectedOrigin))
                writeStatus()
                return
            }
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
        resetListenerCounters()
        machine.enable()
        NativeTelemetryBus.start(applicationContext, selectedOrigin, telemetryDeviceId(), BuildConfig.NATIVE_BUILD_ID)
        NativeTelemetryBus.heartbeat()
        rememberEvent("service_started", JSONObject().put("origin", selectedOrigin))
        rememberEvent("listener_started", JSONObject().put("listener_lane", "foreground_service"))
        Log.i(LOG_TAG, "foreground_service_started=true audio_record_permission_granted=true")
        watchdogGeneration += 1L
        if (providers?.wake?.ready != true) {
            machine.blocked(activeSelection.engine.diagnosticReason)
            Log.w(LOG_TAG, "wake_engine_ready=false onnx_runtime_available=${activeSelection.engine.onnxRuntimeAvailable} reason=${activeSelection.engine.diagnosticReason}")
            writeStatus("Place a compatible raw-PCM ONNX wake model at files/voice/hermes.onnx or bundle assets/voice/base_hermes.onnx. Wake detection is not active until the model is ready.")
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
                        startAudioWatchdog()
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
        startAudioWatchdog()
        worker = thread(name = "hermes-voice-wake-listener") {
            listenLoop(selectedOrigin)
        }
    }

    private fun startAudioWatchdog() {
        val activeWatchdog = watchdogWorker
        val generation = watchdogGeneration
        if (activeWatchdog != null && activeWatchdog.isAlive && activeWatchdogGeneration == generation) return
        activeWatchdogGeneration = generation
        watchdogLastProgressAt = System.currentTimeMillis()
        watchdogLastAudioReadCalls = audioReadCalls
        watchdogLastInferenceCount = inferenceCount
        watchdogWorker = thread(name = "hermes-voice-wake-watchdog", isDaemon = true) {
            while (running && activeWatchdogGeneration == generation) {
                try {
                    Thread.sleep(AUDIO_WATCHDOG_INTERVAL_MS)
                } catch (_: InterruptedException) {
                    Thread.currentThread().interrupt()
                    return@thread
                }
                val now = System.currentTimeMillis()
                val lastFrameAt = lastAudioFrameAt
                if (!running) continue
                val reads = audioReadCalls
                val inferences = inferenceCount
                if (reads != watchdogLastAudioReadCalls || inferences != watchdogLastInferenceCount) {
                    watchdogLastAudioReadCalls = reads
                    watchdogLastInferenceCount = inferences
                    watchdogLastProgressAt = now
                    continue
                }
                val progressBase = maxOf(watchdogLastProgressAt, audioRecordStartedAt, lastListenerLoopStartedAt)
                if (progressBase <= 0L) continue
                val staleMs = if (lastFrameAt > 0L) maxOf(now - lastFrameAt, now - progressBase) else now - progressBase
                if (staleMs < AUDIO_FRAME_STALE_RESTART_MS) continue
                if (now - lastAudioLoopStallAt < AUDIO_FRAME_STALE_RESTART_MS) continue
                lastAudioLoopStallAt = now
                audioLoopStallCount += 1
                val reason = when {
                    audioRecordStartedAt <= 0L -> "audio_capture_no_frames"
                    reads > 0L -> "audio_capture_progress_stalled"
                    else -> "audio_capture_stalled"
                }
                lastAudioRecordError = "$reason:${staleMs}ms"
                lastFailureReason = reason
                rememberEvent("audio_capture_stalled", JSONObject()
                    .put("reason", reason)
                    .put("stale_ms", staleMs)
                    .put("audio_read_calls", reads)
                    .put("inference_count", inferences)
                    .put("stall_count", audioLoopStallCount))
                Log.w(LOG_TAG, "audio_capture_stalled=true reason=$reason stale_ms=$staleMs stall_count=$audioLoopStallCount")
                writeStatus(reason)
                try {
                    activeRecorder?.stop()
                } catch (_: Exception) {
                }
                try {
                    activeRecorder?.release()
                } catch (_: Exception) {
                }
                restartListenerAfterAudioStall(reason)
            }
        }
    }

    private fun restartListenerAfterAudioStall(reason: String) {
        val origin = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(PREF_ORIGIN, BuildConfig.DEFAULT_SERVER_URL)
            .orEmpty()
            .ifBlank { BuildConfig.DEFAULT_SERVER_URL }
        val activeWorker = worker
        running = false
        if (activeWorker != null && activeWorker != Thread.currentThread() && activeWorker.isAlive) {
            try {
                activeWorker.join(1_000)
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
                return
            }
        }
        if (worker === activeWorker) worker = null
        activeRecorder = null
        rememberEvent("listener_restart_requested", JSONObject().put("reason", reason))
        startListening(origin)
    }

    private fun telemetryDeviceId(): String {
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val installId = prefs.getString(PREF_INSTALL_ID, "").orEmpty().ifBlank {
            UUID.randomUUID().toString().also { created ->
                prefs.edit().putString(PREF_INSTALL_ID, created).apply()
            }
        }
        val androidId = try {
            Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID).orEmpty()
        } catch (_: Exception) {
            ""
        }
        val hash = sha256Text("$packageName|$installId|$androidId").take(24)
        return if (hash.isNotBlank()) "android-${BuildConfig.NATIVE_BUILD_ID}-$hash" else "android-${BuildConfig.NATIVE_BUILD_ID}"
    }

    private fun resetListenerCounters() {
        audioRecordInitializedAt = 0L
        audioRecordStartCalledAt = 0L
        audioRecordStartedAt = 0L
        lastAudioFrameAt = 0L
        audioReadCalls = 0L
        audioSamplesRead = 0L
        audioReadErrors = 0L
        audioLoopStallCount = 0L
        lastAudioLoopStallAt = 0L
        lastWakeFramePeak = 0
        maxWakeFramePeak = 0
        lastWakeFrameRms = 0.0
        maxWakeFrameRms = 0.0
        vadPassCount = 0L
        vadRejectCount = 0L
        lastVadSpeech = false
        lastInferenceAt = 0L
        inferenceCount = 0L
        lastInferenceConfidence = 0.0
        maxObservedConfidence = 0.0
        lastInferenceThresholdCrossed = false
        lastInferenceRejectionReason = "inference_not_started"
        rawWakeDetectionCount = 0L
        lastRawWakeDetectionAt = 0L
        wakeConfirmationGate.reset()
        synchronized(inferenceWindows) {
            inferenceWindows.clear()
        }
    }

    private fun stopListening(reason: String) {
        running = false
        try {
            activeRecorder?.stop()
        } catch (_: Exception) {
        }
        val activeWorker = worker
        if (activeWorker != null && activeWorker != Thread.currentThread() && activeWorker.isAlive) {
            try {
                activeWorker.join(1_500)
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
            }
        }
        if (worker === activeWorker) worker = null
        val activeWatchdog = watchdogWorker
        if (activeWatchdog != null && activeWatchdog != Thread.currentThread() && activeWatchdog.isAlive) {
            activeWatchdog.interrupt()
            try {
                activeWatchdog.join(500)
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
            }
        }
        if (watchdogWorker === activeWatchdog) watchdogWorker = null
        if (reason == "user_disabled") {
            getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit().putBoolean(PREF_ENABLED, false).apply()
        }
        machine.disable()
        rememberEvent("listener_stopped", JSONObject().put("reason", reason))
        writeStatus(reason)
        NativeTelemetryBus.stop()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) stopForeground(STOP_FOREGROUND_REMOVE) else @Suppress("DEPRECATION") stopForeground(true)
    }

    private fun listenLoop(origin: String) {
        lastListenerLoopStartedAt = System.currentTimeMillis()
        try {
        while (running) {
            val wake = listenForWake()
            if (wake == null || !running) {
                writeLifecycleMarker(if (running) "listen_loop_null_wake_continue" else "listen_loop_running_false")
                continue
            }
            val startedAt = System.currentTimeMillis()
            val voiceSessionId = UUID.randomUUID().toString()
            val falseWakeAudio = wake.audioWindow.copyOf()
            commandCaptureStartedAt = startedAt
            activeTranscriptCaptureId = startedAt
            rememberEvent("command_capture_started", JSONObject().put("wake_hit_count", wakeDetectionCount))
            Log.i(LOG_TAG, "command_capture_started=true wake_detection_count=$wakeDetectionCount last_confidence=$lastInferenceConfidence")
            machine.beginTranscribing()
            val transcriptProviders = currentProviders()
            val transcriptTimeoutMs = configuredTranscriptTimeoutMs(this)
            val transcriptPolicy = configuredTranscriptPolicy(this)
            val captureEvent = VoiceWakeEvent(
                transcript = "",
                command = "",
                confidence = wake.confidence.coerceIn(0.0, 1.0),
                startedAt = startedAt,
                endedAt = startedAt,
                buildId = BuildConfig.NATIVE_BUILD_ID,
                wakeWord = configuredWakePhrase(this),
                sessionId = voiceSessionId,
            )
            lastTranscriptResult = "transcript_attempt_started"
            lastAsrEngine = transcriptProviders.transcriber.name
            lastAsrLatencyMs = 0L
            lastAsrAudioCapturedMs = 0L
            lastAsrPartialTranscript = ""
            lastNormalizedTranscript = ""
            lastVoiceCommand = ""
            lastAsrDiagnostics = safeJsonString(transcriptAttemptStartedDiagnostics(
                transcriptProviders.transcriber.name,
                transcriptTimeoutMs,
                transcriptPolicy,
            ))
            rememberEvent("transcript_attempt_started", JSONObject()
                .put("engine", transcriptProviders.transcriber.name)
                .put("timeout_ms", transcriptTimeoutMs))
            writeStatus("transcript_attempt_started")
            writeLifecycleMarker("transcript_attempt_started")
            postCommandCaptureStartedEvent(origin, captureEvent, transcriptProviders.transcriber.name)
            bringAppToForegroundAfterWakeAsync(wake)
            val partialEngine = transcriptProviders.transcriber as? PartialTranscriptionEngine
            partialEngine?.setPartialTranscriptListener { partial ->
                postVoicePartialEvent(origin, captureEvent, transcriptProviders.transcriber.name, partial)
            }
            startTranscriptWatchdog(startedAt, transcriptProviders.transcriber.name, transcriptTimeoutMs, transcriptPolicy)
            val transcript = try {
                transcribeWithTimeout(
                    transcriptProviders.transcriber,
                    transcriptTimeoutMs,
                    transcriptPolicy,
                    falseWakeAudio,
                )
            } finally {
                partialEngine?.setPartialTranscriptListener(null)
            }
            if (activeTranscriptCaptureId != startedAt) {
                rememberEvent("transcript_late_result_ignored", JSONObject()
                    .put("engine", transcript.engine.ifBlank { transcriptProviders.transcriber.name })
                    .put("result", transcript.transcript.ifBlank { transcript.error }.take(160)))
                writeStatus("transcript_late_result_ignored")
                continue
            }
            activeTranscriptCaptureId = 0L
            commandCaptureStartedAt = 0L
            val endedAt = System.currentTimeMillis()
            lastTranscriptResult = transcript.transcript.ifBlank { transcript.error }
            lastAsrEngine = transcript.engine.ifBlank { transcriptProviders.transcriber.name }
            lastAsrLatencyMs = transcript.latencyMs
            lastAsrAudioCapturedMs = transcript.audioCapturedMs
            lastAsrPartialTranscript = transcript.partialTranscript.take(160)
            lastAsrDiagnostics = safeJsonString(transcript.diagnostics)
            lastNormalizedTranscript = VoiceCommandNormalizer.normalizeTranscript(transcript.transcript).take(160)
            if (transcript.transcript.isBlank()) {
                lastVoiceCommand = ""
                val reason = falseWakeReasonForTranscript(transcript.error)
                val runawayPaused = captureFalseWake(wake, falseWakeAudio, transcript.transcript, reason, startedAt)
                rememberEvent("transcript_rejected", JSONObject().put("reason", reason))
                writeLifecycleMarker("transcript_rejected")
                postVoiceEvent(origin, VoiceWakeEvent(
                    transcript = transcript.transcript,
                    command = "",
                    confidence = wake.confidence.coerceIn(0.0, 1.0),
                    startedAt = startedAt,
                    endedAt = endedAt,
                    buildId = BuildConfig.NATIVE_BUILD_ID,
                    wakeWord = configuredWakePhrase(this),
                    sessionId = voiceSessionId,
                ), falseWakeAudio)
                if (runawayPaused) {
                    writeStatus("false_wake_runaway_paused")
                    continue
                }
                machine.fail(transcript.error.ifBlank { "transcription_empty" })
                writeStatus()
                machine.listenAgain()
                standbyRestoredAt = System.currentTimeMillis()
                rememberEvent("standby_restored")
                continue
            }
            val command = VoiceCommandNormalizer.commandForTranscript(transcript.transcript)
            lastVoiceCommand = command.ifBlank { "freeform_transcript" }
            if (command.isBlank()) {
                rememberEvent("transcript_freeform", JSONObject()
                    .put("normalized_transcript", lastNormalizedTranscript)
                    .put("transcript", transcript.transcript.take(160)))
            }
            val event = VoiceWakeEvent(
                transcript = transcript.transcript,
                command = command,
                confidence = wake.confidence.coerceIn(0.0, 1.0),
                startedAt = startedAt,
                endedAt = endedAt,
                buildId = BuildConfig.NATIVE_BUILD_ID,
                wakeWord = configuredWakePhrase(this),
                sessionId = voiceSessionId,
            )
            machine.complete(event)
            resetFalseWakeStorm()
            rememberEvent("transcript_accepted", JSONObject()
                .put("command", command)
                .put("normalized_transcript", lastNormalizedTranscript))
            writeStatus()
            writeLifecycleMarker("transcript_accepted")
            postVoiceEvent(origin, event, falseWakeAudio)
            val wakeCooldownMs = configuredWakeCooldownMs(this)
            wakeCooldownUntil = maxOf(wakeCooldownUntil, System.currentTimeMillis() + wakeCooldownMs)
            rememberEvent("post_transcript_cooldown", JSONObject()
                .put("wake_cooldown_ms", wakeCooldownMs)
                .put("wake_cooldown_until", wakeCooldownUntil))
            machine.listenAgain()
            standbyRestoredAt = System.currentTimeMillis()
            rememberEvent("standby_restored")
            writeStatus()
        }
        } finally {
            lastListenerLoopEndedAt = System.currentTimeMillis()
            writeLifecycleMarker("listen_loop_ended")
            recoverUnexpectedListenerExit(origin)
        }
    }

    private fun recoverUnexpectedListenerExit(origin: String) {
        if (running || lastListenExitReason != "running_false") return
        val enabled = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).getBoolean(PREF_ENABLED, false)
        if (!enabled || falseWakeRunawayReason.isNotBlank()) return
        rememberEvent("listener_unexpected_exit_recovery_scheduled", JSONObject()
            .put("last_listen_exit_reason", lastListenExitReason)
            .put("audio_read_calls", audioReadCalls)
            .put("inference_count", inferenceCount))
        thread(name = "hermes-voice-wake-exit-recovery", isDaemon = true) {
            try {
                Thread.sleep(350L)
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
                return@thread
            }
            if (!running) startListening(origin)
        }
    }

    private fun listenForWake(): WakeWordResult? {
        var recorder: AudioRecord? = null
        lastListenExitReason = "listen_for_wake_entered"
        lastListenExitDetail = ""
        writeLifecycleMarker("listen_for_wake_entered")
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
                markListenExit("audio_record_min_buffer_failed", lastAudioRecordError)
                return null
            }
            val minBuffer = rawMinBuffer.coerceAtLeast(OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ)
            val audioSource = selectedWakeAudioSource()
            activeAudioSource = audioSource.first
            activeAudioSourceName = audioSource.second
            recorder = AudioRecord(
                audioSource.first,
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
                markListenExit("audio_record_init_failed", lastAudioRecordError)
                return null
            }
            audioRecordInitializedAt = System.currentTimeMillis()
            activeRecorder = recorder
            Log.i(LOG_TAG, "audio_record_initialized=true min_buffer=$minBuffer audio_source=${audioSource.second}")
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
                markListenExit("audio_record_start_failed", lastAudioRecordError)
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
            var zeroReadStartedAt = 0L
            while (running) {
                val count = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    recorder.read(buffer, 0, buffer.size, AudioRecord.READ_NON_BLOCKING)
                } else {
                    recorder.read(buffer, 0, buffer.size)
                }
                if (count <= 0) {
                    if (count == 0) {
                        val now = System.currentTimeMillis()
                        if (zeroReadStartedAt <= 0L) zeroReadStartedAt = now
                        if (now - zeroReadStartedAt < 1_500L &&
                            !lastAudioRecordError.startsWith("audio_capture_stalled") &&
                            !lastAudioRecordError.startsWith("audio_capture_no_frames")) {
                            Thread.sleep(10)
                            continue
                        }
                        lastAudioRecordError = "audio_capture_no_frames:${now - zeroReadStartedAt}ms"
                    }
                    val restartRequested = lastAudioRecordError.startsWith("audio_capture_stalled") ||
                        lastAudioRecordError.startsWith("audio_capture_no_frames")
                    if (count == 0 && !restartRequested) {
                        Thread.sleep(10)
                        continue
                    }
                    audioReadErrors += 1
                    if (!restartRequested) lastAudioRecordError = "AudioRecord.read returned $count"
                    Log.w(LOG_TAG, "audio_record_read_error_count=$audioReadErrors audio_record_last_error=$lastAudioRecordError")
                    if (restartRequested || recorder.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
                        lastFailureReason = if (restartRequested) {
                            if (lastAudioRecordError.startsWith("audio_capture_no_frames")) "audio_capture_no_frames" else "audio_capture_stalled"
                        } else {
                            "audio_capture_restart_requested"
                        }
                        if (lastFailureReason == "audio_capture_no_frames" || lastFailureReason == "audio_capture_stalled") {
                            rotateWakeAudioSource(lastFailureReason)
                        }
                        writeStatus(lastFailureReason)
                        markListenExit(lastFailureReason, lastAudioRecordError)
                        return null
                    }
                    continue
                }
                zeroReadStartedAt = 0L
                audioReadCalls += 1
                audioSamplesRead += count.toLong()
                lastAudioFrameAt = System.currentTimeMillis()
                if (lastAudioRecordError.startsWith("AudioRecord.read returned ") ||
                    lastAudioRecordError.startsWith("audio_capture_stalled")) {
                    lastAudioRecordError = ""
                }
                if (lastFailureReason == "audio_capture_stalled" ||
                    lastFailureReason == "audio_capture_restart_requested") {
                    lastFailureReason = ""
                }
                if (audioReadCalls == 1L || audioReadCalls % 50L == 0L) {
                    Log.i(LOG_TAG, "audio_record_read_count=$audioReadCalls audio_samples_read=$audioSamplesRead")
                }
                val frame = buffer.copyOf(count)
                recordWakeFrameAudioMetrics(frame)
                rollingAudio.append(frame)
                val nowMs = System.currentTimeMillis()
                if (!proofSessionActive && foregroundUiInferenceShouldYield(nowMs)) {
                    Thread.sleep(FOREGROUND_UI_INFERENCE_SKIP_MS)
                    continue
                }
                if (nowMs < wakeCooldownUntil) continue
                val activeProviders = currentProviders()
                val vadSpeech = proofSessionActive || activeProviders.vad.isSpeech(frame, OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ)
                lastVadSpeech = vadSpeech
                if (vadSpeech) vadPassCount += 1L else vadRejectCount += 1L
                if (!vadSpeech) {
                    if (vadRejectCount == 1L || vadRejectCount % 100L == 0L) {
                        rememberEvent("vad_rejected_frame", JSONObject()
                            .put("vad_reject_count", vadRejectCount)
                            .put("audio_peak", lastWakeFramePeak)
                            .put("audio_rms", lastWakeFrameRms))
                    }
                    continue
                }
                val wake = activeProviders.wake.processPcm16(frame, OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ)
                val confirmedWake = wakeConfirmationGate.observe(
                    wake,
                    requiredFrames = configuredWakeConfirmationFrames(this),
                    windowMs = configuredWakeConfirmationWindowMs(this),
                ).wake
                recordInference(wake, confirmedWake)
                if (inferenceCount == 1L || inferenceCount % 100L == 0L) {
                    rememberEvent("inference_tick", JSONObject()
                        .put("inference_count", inferenceCount)
                        .put("last_confidence", lastInferenceConfidence))
                }
                if (inferenceCount == 1L || inferenceCount % 20L == 0L || wake.detected || confirmedWake.detected) {
                    Log.i(LOG_TAG, "inference_count=$inferenceCount last_confidence=$lastInferenceConfidence raw_wake_detected=${wake.detected} wake_confirmed=${confirmedWake.detected}")
                }
                if (nowMs - lastLifecycleInferenceWriteAt >= 1000L || wake.detected || confirmedWake.detected) {
                    lastLifecycleInferenceWriteAt = nowMs
                    writeLifecycleMarker(if (confirmedWake.detected) "wake_confirmed" else if (wake.detected) "raw_wake_detected" else "inference_observed")
                }
                if (proofSessionActive) {
                    if (confirmedWake.detected) {
                        if (machine.onWake(confirmedWake)) {
                            wakeDetectionCount += 1
                            lastWakeDetectionAt = System.currentTimeMillis()
                            wakeCooldownUntil = lastWakeDetectionAt + configuredWakeCooldownMs(this)
                            rememberEvent("wake_hit", JSONObject()
                                .put("confidence", confirmedWake.confidence)
                                .put("raw_confidence", wake.confidence)
                                .put("confirmation_frames", configuredWakeConfirmationFrames(this)))
                            NativeTelemetryBus.publishWakeHit(confirmedWake.confidence, wakeDetectionCount)
                            Log.i(LOG_TAG, "wake_detected=true wake_detection_count=$wakeDetectionCount last_confidence=$lastInferenceConfidence")
                            lastWakePass = true
                            lastWakeProofResult = "pass"
                            writeStatus("proof_wake_detected")
                            postWakeDetectedEvent(confirmedWake)
                            markListenExit("proof_wake_detected", "confidence=${confirmedWake.confidence}")
                            return confirmedWake.copy(audioWindow = rollingAudio.snapshot())
                        }
                        continue
                    }
                    val now = System.currentTimeMillis()
                    if (now - lastProofStatusWriteAt >= 1000L) {
                        lastProofStatusWriteAt = now
                        writeStatus(if (wake.detected) "proof_wake_confirmation_pending" else "proof_inference_observed")
                    }
                    continue
                }
                if (machine.onWake(confirmedWake)) {
                    wakeDetectionCount += 1
                    lastWakeDetectionAt = System.currentTimeMillis()
                    wakeCooldownUntil = lastWakeDetectionAt + configuredWakeCooldownMs(this)
                    rememberEvent("wake_hit", JSONObject()
                        .put("confidence", confirmedWake.confidence)
                        .put("raw_confidence", wake.confidence)
                        .put("confirmation_frames", configuredWakeConfirmationFrames(this)))
                    NativeTelemetryBus.publishWakeHit(confirmedWake.confidence, wakeDetectionCount)
                    lastWakePass = true
                    lastWakeProofResult = "pass"
                    writeStatus()
                    postWakeDetectedEvent(confirmedWake)
                    markListenExit("wake_detected", "confidence=${confirmedWake.confidence}")
                    return confirmedWake.copy(audioWindow = rollingAudio.snapshot())
                }
            }
            markListenExit("running_false", "audio_read_calls=$audioReadCalls inference_count=$inferenceCount")
        } catch (error: Exception) {
            lastException = formatException(error)
            lastAudioRecordError = lastException
            lastFailureReason = if (audioRecordStartedAt <= 0L) "audio_record_start_failed" else "audio_capture_failed"
            lastWakeProofResult = "fail:${error.javaClass.name}"
            machine.fail(lastFailureReason)
            Log.e(LOG_TAG, "audio_record_last_error=$lastAudioRecordError failure_reason=$lastFailureReason")
            writeStatus(lastFailureReason)
            markListenExit(lastFailureReason, lastException)
        } finally {
            if (activeRecorder === recorder) activeRecorder = null
            try {
                recorder?.stop()
            } catch (_: Exception) {
            }
            recorder?.release()
            writeLifecycleMarker("listen_for_wake_finally")
        }
        return null
    }

    private fun markListenExit(reason: String, detail: String = "") {
        lastListenExitReason = reason
        lastListenExitDetail = detail.take(500)
        rememberEvent("listen_for_wake_exit", JSONObject()
            .put("reason", lastListenExitReason)
            .put("detail", lastListenExitDetail)
            .put("audio_read_calls", audioReadCalls)
            .put("audio_samples_read", audioSamplesRead)
            .put("inference_count", inferenceCount)
            .put("running", running))
        writeLifecycleMarker("listen_for_wake_exit")
    }

    private fun wakeAudioSources(): List<Pair<Int, String>> = listOf(
        MediaRecorder.AudioSource.VOICE_RECOGNITION to "VOICE_RECOGNITION",
        MediaRecorder.AudioSource.MIC to "MIC",
        MediaRecorder.AudioSource.CAMCORDER to "CAMCORDER",
        MediaRecorder.AudioSource.DEFAULT to "DEFAULT",
    )

    private fun selectedWakeAudioSource(): Pair<Int, String> {
        val sources = wakeAudioSources()
        return sources[audioSourceIndex.coerceIn(0, sources.lastIndex)]
    }

    private fun rotateWakeAudioSource(reason: String) {
        val sources = wakeAudioSources()
        audioSourceIndex = (audioSourceIndex + 1) % sources.size
        audioSourceRestartCount += 1L
        val next = selectedWakeAudioSource()
        rememberEvent("audio_source_rotated", JSONObject()
            .put("reason", reason)
            .put("audio_source", next.second)
            .put("restart_count", audioSourceRestartCount))
    }

    private fun recordInference(rawWake: WakeWordResult, confirmedWake: WakeWordResult) {
        val now = System.currentTimeMillis()
        val wakeThreshold = currentWakeThreshold()
        val confirmation = wakeConfirmationGate.snapshot(
            configuredWakeConfirmationFrames(this),
            configuredWakeConfirmationWindowMs(this),
        )
        lastInferenceAt = now
        inferenceCount += 1
        lastInferenceConfidence = rawWake.confidence.coerceIn(0.0, 1.0)
        maxObservedConfidence = maxOf(maxObservedConfidence, lastInferenceConfidence)
        lastInferenceThresholdCrossed = lastInferenceConfidence >= wakeThreshold
        if (rawWake.detected) {
            rawWakeDetectionCount += 1
            lastRawWakeDetectionAt = now
        }
        lastInferenceRejectionReason = when {
            confirmedWake.detected -> ""
            !lastInferenceThresholdCrossed -> "below_threshold"
            rawWake.detected -> confirmation.optString("rejection_reason", "wake_confirmation_pending").ifBlank { "wake_confirmation_pending" }
            else -> "state_machine_not_listening"
        }
        lastWakePass = confirmedWake.detected
        lastWakeProofResult = when {
            confirmedWake.detected -> "pass"
            lastInferenceThresholdCrossed -> "threshold_crossed:${lastInferenceRejectionReason}"
            else -> "listening:${lastInferenceRejectionReason}"
        }
        if (rawWake.detected || confirmedWake.detected || inferenceCount == 1L || inferenceCount % 10L == 0L || (lastInferenceThresholdCrossed && inferenceCount % 3L == 0L)) {
            NativeTelemetryBus.publishWakeState(
                reason = if (confirmedWake.detected) "wake_confirmed" else if (rawWake.detected) "wake_confirmation_pending" else "inference",
                inferenceCount = inferenceCount,
                confidence = lastInferenceConfidence,
                maxConfidence = maxObservedConfidence,
                threshold = wakeThreshold,
                thresholdCrossed = lastInferenceThresholdCrossed,
                detected = confirmedWake.detected,
                wakeHitCount = wakeDetectionCount,
                audioPeak = lastWakeFramePeak,
                audioRms = lastWakeFrameRms,
                rejectionReason = lastInferenceRejectionReason,
            )
        }
        synchronized(inferenceWindows) {
            inferenceWindows.addLast(JSONObject()
                .put("index", inferenceCount)
                .put("timestamp", now)
                .put("confidence", lastInferenceConfidence)
                .put("max_confidence", maxObservedConfidence)
                .put("threshold", wakeThreshold)
                .put("threshold_crossed", lastInferenceThresholdCrossed)
                .put("raw_detected", rawWake.detected)
                .put("detected", confirmedWake.detected)
                .put("wake_confirmed", confirmedWake.detected)
                .put("wake_confirmation", confirmation)
                .put("audio_peak", lastWakeFramePeak)
                .put("audio_rms", lastWakeFrameRms)
                .put("detection_count", wakeDetectionCount)
                .put("last_detection_timestamp", lastWakeDetectionAt)
                .put("rejection_reason", lastInferenceRejectionReason))
            while (inferenceWindows.size > 24) inferenceWindows.removeFirst()
        }
    }

    private fun recordWakeFrameAudioMetrics(frame: ShortArray) {
        var peak = 0
        var energy = 0.0
        for (sample in frame) {
            val value = sample.toInt()
            val absolute = if (value == Short.MIN_VALUE.toInt()) Short.MAX_VALUE.toInt() else kotlin.math.abs(value)
            peak = maxOf(peak, absolute)
            val normalized = value.toDouble() / Short.MAX_VALUE.toDouble()
            energy += normalized * normalized
        }
        val rms = if (frame.isEmpty()) 0.0 else kotlin.math.sqrt(energy / frame.size.toDouble())
        lastWakeFramePeak = peak
        lastWakeFrameRms = rms
        maxWakeFramePeak = maxOf(maxWakeFramePeak, peak)
        maxWakeFrameRms = maxOf(maxWakeFrameRms, rms)
    }

    private fun foregroundUiActiveUntil(forceRefresh: Boolean = false, nowMs: Long = System.currentTimeMillis()): Long {
        val shouldRefresh = forceRefresh ||
            foregroundUiActiveUntilCacheReadAt <= 0L ||
            nowMs - foregroundUiActiveUntilCacheReadAt >= FOREGROUND_UI_ACTIVE_PREF_READ_INTERVAL_MS
        if (!shouldRefresh) return foregroundUiActiveUntilCache
        val activeUntil = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getLong(PREF_FOREGROUND_UI_ACTIVE_UNTIL, 0L)
        foregroundUiActiveUntilCache = activeUntil
        foregroundUiActiveUntilCacheReadAt = nowMs
        return activeUntil
    }

    private fun foregroundUiInferenceShouldYield(nowMs: Long = System.currentTimeMillis()): Boolean =
        foregroundUiActiveUntil(nowMs = nowMs) > nowMs

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
            wakeWord = configuredWakePhrase(this),
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
        try {
            startActivity(wakeForegroundIntent(wake))
            rememberEvent("wake_app_foreground_requested", JSONObject().put("confidence", wake.confidence))
            Log.i(LOG_TAG, "wake_app_foreground_requested=true confidence=${wake.confidence}")
        } catch (error: Exception) {
            lastException = formatException(error)
            rememberEvent("wake_app_foreground_failed", JSONObject().put("error", error.javaClass.simpleName))
            Log.w(LOG_TAG, "wake_app_foreground_requested=false error=$lastException")
        }
    }

    private fun bringAppToForegroundAfterWakeAsync(wake: WakeWordResult) {
        thread(name = "hermes-wake-foreground-after-asr-start", isDaemon = true) {
            try {
                Thread.sleep(250L)
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
                return@thread
            }
            bringAppToForegroundAfterWake(wake)
        }
    }

    private fun wakeForegroundIntent(wake: WakeWordResult? = null): Intent {
        val uri = wakeForegroundUri(wake)
        return Intent(this, NativeShellV2Activity::class.java)
            .setData(uri)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            .putExtra("native_screen", "wake-word")
            .putExtra("wake_source", "hermes_voice_wake")
            .also { intent ->
                wake?.let { intent.putExtra("wake_confidence", it.confidence) }
            }
    }

    private fun wakeForegroundUri(wake: WakeWordResult? = null): Uri {
        val origin = BuildConfig.DEFAULT_SERVER_URL.trim().trimEnd('/').ifBlank { "https://wa.colmeio.com" }
        val builder = Uri.parse("$origin/home").buildUpon()
            .appendQueryParameter("native", "android")
            .appendQueryParameter("shell", "android-webview-v2")
            .appendQueryParameter("android_shell", "android-webview-v2")
            .appendQueryParameter("android_runtime", "user-full")
            .appendQueryParameter("android_startup", if (wake == null) "notification" else "wake-foreground")
            .appendQueryParameter("native_screen", "wake-word")
            .appendQueryParameter("wake_source", "hermes_voice_wake")
            .appendQueryParameter("wake", "off")
            .appendQueryParameter("bridgeDiagnostics", "off")
            .appendQueryParameter("healthProbes", "off")
            .appendQueryParameter("nativeControl", "off")
            .appendQueryParameter("buildId", BuildConfig.NATIVE_BUILD_ID)
        wake?.let { builder.appendQueryParameter("wake_confidence", it.confidence.coerceIn(0.0, 1.0).toString()) }
        return builder.build()
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

    private fun postCommandCaptureStartedEvent(origin: String, event: VoiceWakeEvent, asrProvider: String) {
        thread(name = "hermes-command-capture-event") {
            val result = router.dispatchCommandCaptureStarted(origin, event, asrProvider)
            rememberEvent("wake_event_delivered_to_app", JSONObject()
                .put("delivery", if (result.ok) "backend" else "none")
                .put("event_type", "command_capture_started"))
        }
    }

    private fun postVoicePartialEvent(origin: String, event: VoiceWakeEvent, asrProvider: String, partialTranscript: String) {
        val partial = partialTranscript.trim().take(240)
        if (!nativeVoicePartialLooksUsable(partial)) return
        if (partial.isBlank()) return
        thread(name = "hermes-voice-partial-event") {
            router.dispatchPartial(origin, event, asrProvider, partial)
        }
    }

    private fun nativeVoicePartialLooksUsable(transcript: String): Boolean {
        val normalized = transcript
            .replace(Regex("\\[(unk|spn|noise|sil)]|<(unk|spn|noise|sil)>", RegexOption.IGNORE_CASE), " ")
            .replace(Regex("[^A-Za-z0-9 ?!.,'’-]+"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()
            .lowercase(Locale.US)
        if (normalized.isBlank()) return false
        val weak = setOf("word", "words", "uh", "um", "hmm", "noise", "unknown", "open")
        val meaningful = normalized.split(" ").filter { it.isNotBlank() && it !in weak }
        return meaningful.joinToString(" ").length >= 3
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
            recentEvents.forEach { event -> array.put(sanitizeJsonValue(event) as? JSONObject ?: JSONObject()) }
        }
        return array
    }

    private fun writeStatus(reason: String = "") {
        reconcileStaleTranscript(reason)
        val activeSelection = currentWakeModelSelection()
        val activeWakeEngine = activeSelection.engine
        val wakeDiagnostics = activeWakeEngine.diagnostics()
        val activeProviders = currentProviders()
        val wakeThreshold = currentWakeThreshold()
        val transcriptPolicy = configuredTranscriptPolicy(this)
        val personalizedSha256 = sha256OrBlank(personalizedModelFile)
        val baseSha256 = sha256OrBlank(baseModelFile)
        val modelPath = wakeDiagnostics.getString("selected_model_path")
        val modelExists = wakeDiagnostics.getBoolean("wake_model_exists")
        val selectedModelSha256 = when (modelPath) {
            OpenWakeWordOnnxEngine.APP_PRIVATE_BASE_MODEL_PATH -> baseSha256
            OpenWakeWordBundleEngine.BUNDLE_DIR -> ""
            else -> personalizedSha256
        }
        val modelShaMatch = selectedModelSha256.equals(ACCEPTANCE_MODEL_SHA256, ignoreCase = true)
        val disabledReason = readinessDisabledReason(
            enabled = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).getBoolean(PREF_ENABLED, false),
            permissionGranted = hasRecordAudioPermission(),
            foregroundServiceRunning = running,
            wakeDiagnostics = wakeDiagnostics,
            modelExists = modelExists,
        )
        val now = System.currentTimeMillis()
        val foregroundUiActiveUntil = foregroundUiActiveUntil(forceRefresh = true, nowMs = now)
        val audioRecordStarted = audioRecordStartedAt > 0L && lastAudioRecordError.isBlank()
        val audioCaptureStaleMs = if (lastAudioFrameAt > 0L) maxOf(0L, now - lastAudioFrameAt) else 0L
        val inferenceStaleMs = if (lastInferenceAt > 0L) maxOf(0L, now - lastInferenceAt) else 0L
        val audioCaptureStale = lastAudioFrameAt > 0L && audioCaptureStaleMs > AUDIO_CAPTURE_ALIVE_WINDOW_MS
        val inferenceStale = lastInferenceAt > 0L && inferenceStaleMs > AUDIO_CAPTURE_ALIVE_WINDOW_MS
        val audioCaptureAlive = running && audioRecordStarted && lastAudioFrameAt > 0L && !audioCaptureStale
        val inferenceAlive = audioCaptureAlive && lastInferenceAt > 0L && !inferenceStale
        val listenerReady = running && hasRecordAudioPermission() && audioCaptureAlive && activeProviders.wake.ready
        val localAsrDiagnostics = (activeProviders.transcriber as? LocalCommandTranscriptionEngine)?.diagnostics() ?: JSONObject()
        val onnxModelReady = wakeDiagnostics.optBoolean("onnx_runtime_available", false) &&
            activeProviders.wake.ready &&
            modelExists
        val failureReason = failureReasonForStatus(
            permissionGranted = hasRecordAudioPermission(),
            foregroundServiceRunning = running,
            audioRecordStarted = audioRecordStarted,
            audioCaptureAlive = audioCaptureAlive,
            wakeDiagnostics = wakeDiagnostics,
            modelExists = modelExists,
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
            .put("audio_capture_stale", audioCaptureStale)
            .put("audio_capture_stale_ms", audioCaptureStaleMs)
            .put("audio_capture_alive_window_ms", AUDIO_CAPTURE_ALIVE_WINDOW_MS)
            .put("audio_loop_stall_count", audioLoopStallCount)
            .put("last_audio_loop_stall_at", lastAudioLoopStallAt)
            .put("audio_source", activeAudioSourceName)
            .put("audio_source_id", activeAudioSource)
            .put("audio_source_index", audioSourceIndex)
            .put("audio_source_restart_count", audioSourceRestartCount)
            .put("audio_watchdog_active", watchdogWorker?.isAlive == true)
            .put("active_audio_recorder_present", activeRecorder != null)
            .put("foreground_service_started", running)
            .put("audio_record_error", lastAudioRecordError)
            .put("audio_record_last_error", lastAudioRecordError)
            .put("audio_record_started_at", audioRecordStartedAt)
            .put("last_audio_frame_at", lastAudioFrameAt)
            .put("audio_read_calls", audioReadCalls)
            .put("audio_record_read_count", audioReadCalls)
            .put("audio_samples_read", audioSamplesRead)
            .put("audio_read_errors", audioReadErrors)
            .put("last_wake_frame_peak", lastWakeFramePeak)
            .put("max_wake_frame_peak", maxWakeFramePeak)
            .put("last_wake_frame_rms", lastWakeFrameRms)
            .put("max_wake_frame_rms", maxWakeFrameRms)
            .put("vad_pass_count", vadPassCount)
            .put("vad_reject_count", vadRejectCount)
            .put("last_vad_speech", lastVadSpeech)
            .put("audio_sample_rate_hz", OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ)
            .put("audio_channels", 1)
            .put("audio_format", "pcm16_mono_16khz")
            .put("foreground_ui_inference_paused", foregroundUiActiveUntil > now)
            .put("foreground_ui_active_until", foregroundUiActiveUntil)
            .put("last_inference_at", lastInferenceAt)
            .put("last_inference_timestamp", lastInferenceAt)
            .put("inference_running", inferenceAlive)
            .put("inference_stale", inferenceStale)
            .put("inference_stale_ms", inferenceStaleMs)
            .put("inference_count", inferenceCount)
            .put("last_confidence", lastInferenceConfidence)
            .put("last_wake_confidence", lastInferenceConfidence)
            .put("max_observed_confidence", maxObservedConfidence)
            .put("wake_threshold", wakeThreshold)
            .put("wake_word", configuredWakePhrase(this))
            .put("threshold", wakeThreshold)
            .put("proof_threshold_override", proofWakeThresholdOverride ?: JSONObject.NULL)
            .put("effective_wake_threshold", wakeThreshold)
            .put("threshold_margin", maxObservedConfidence - wakeThreshold)
            .put("threshold_policy_source", currentWakeThresholdSource())
            .put("policy_source", currentWakeThresholdSource())
            .put("wake_confirmation_frames", configuredWakeConfirmationFrames(this))
            .put("wake_confirmation_required_frames", configuredWakeConfirmationFrames(this))
            .put("wake_confirmation_window_ms", configuredWakeConfirmationWindowMs(this))
            .put("wake_confirmation", wakeConfirmationGate.snapshot(
                configuredWakeConfirmationFrames(this),
                configuredWakeConfirmationWindowMs(this),
            ))
            .put("vad_rms_threshold", configuredVadRmsThreshold(this))
            .put("vad_peak_threshold", configuredVadPeakThreshold(this))
            .put("transcript_timeout_ms", configuredTranscriptTimeoutMs(this))
            .put("transcript_min_length_ms", transcriptPolicy.minimumLengthMs)
            .put("transcript_complete_silence_ms", transcriptPolicy.completeSilenceMs)
            .put("transcript_possible_silence_ms", transcriptPolicy.possiblyCompleteSilenceMs)
            .put("transcript_accept_partial", transcriptPolicy.acceptPartialResults)
            .put("transcript_engine", configuredTranscriptEngine(this))
            .put("transcript_attempt_plan", configuredTranscriptAttemptPlan(this))
            .put("local_asr_engine", localAsrDiagnostics.optString("local_asr_engine", activeProviders.transcriber.name))
            .put("local_asr_preferred_engine", localAsrDiagnostics.optString("local_asr_preferred_engine", configuredTranscriptEngine(this)))
            .put("local_asr_vosk_ready", localAsrDiagnostics.optBoolean("local_asr_vosk_ready", false))
            .put("local_asr_vosk_model_path", localAsrDiagnostics.optString("local_asr_vosk_model_path", "files/${LocalCommandTranscriptionEngine.MODEL_PATH}"))
            .put("local_asr_vosk_asset_path", "assets/${LocalCommandTranscriptionEngine.ASSET_MODEL_PATH}")
            .put("local_asr_vosk_asset_available", bundledVoskModelAvailable())
            .put("local_asr_vosk_error", localAsrDiagnostics.optString("local_asr_vosk_error", ""))
            .put("last_asr_engine", lastAsrEngine)
            .put("last_asr_latency_ms", lastAsrLatencyMs)
            .put("last_asr_audio_captured_ms", lastAsrAudioCapturedMs)
            .put("last_asr_partial_transcript", lastAsrPartialTranscript)
            .put("last_asr_diagnostics", parseJsonObject(lastAsrDiagnostics))
            .put("last_normalized_transcript", lastNormalizedTranscript)
            .put("last_voice_command", lastVoiceCommand)
            .put("wake_cooldown_ms", configuredWakeCooldownMs(this))
            .put("wake_cooldown_until", wakeCooldownUntil)
            .put("tuning_session_id", getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).getString(PREF_TUNING_SESSION_ID, "").orEmpty())
            .put("last_inference_threshold_crossed", lastInferenceThresholdCrossed)
            .put("threshold_crossed", lastInferenceThresholdCrossed)
            .put("last_inference_rejection_reason", lastInferenceRejectionReason)
            .put("rejection_reason", lastInferenceRejectionReason)
            .put("raw_wake_detection_count", rawWakeDetectionCount)
            .put("last_raw_wake_detection_at", lastRawWakeDetectionAt)
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
            .put("model_sha256", selectedModelSha256)
            .put("model_sha", selectedModelSha256)
            .put("personalized_model_sha256", personalizedSha256)
            .put("base_model_sha256", baseSha256)
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
            .put("openwakeword_bundle_exists", activeSelection.openWakeWordBundleExists)
            .put("model_path", modelPath)
            .put("selected_model_path", modelPath)
            .put("model_exists", modelExists)
            .put("wake_model_exists", modelExists)
            .put("last_model_load_result", wakeDiagnostics.getString("last_model_load_result"))
            .put("last_model_load_error", wakeDiagnostics.getString("last_model_load_error"))
            .put("wake_model", wakeDiagnostics
                .put("base_model_exists", activeSelection.baseModelExists)
                .put("personalized_model_exists", activeSelection.personalizedModelExists)
                .put("openwakeword_bundle_exists", activeSelection.openWakeWordBundleExists))
            .put("wake_word_schema", "hermes.wasm_agent.android_wake_word_state.v1")
            .put("app_version", packageManager.getPackageInfo(packageName, 0).versionName.orEmpty())
            .put("android_build_id", BuildConfig.NATIVE_BUILD_ID)
            .put("loaded_model_sha", selectedModelSha256)
            .put("expected_model_sha", ACCEPTANCE_MODEL_SHA256)
            .put("prototype_threshold", proofWakeThresholdOverride ?: JSONObject.NULL)
            .put("wake_service_ready", listenerReady)
            .put("wake_service_enabled", getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).getBoolean(PREF_ENABLED, false))
            .put("foreground_service_active", running)
            .put("foreground_service_running", running)
            .put("listener_ready", listenerReady)
            .put("listener_loop_started_at", lastListenerLoopStartedAt)
            .put("listener_loop_ended_at", lastListenerLoopEndedAt)
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
            .put("false_wake_storm_count", falseWakeStormCount)
            .put("false_wake_storm_limit", FALSE_WAKE_STORM_LIMIT)
            .put("false_wake_storm_window_ms", FALSE_WAKE_STORM_WINDOW_MS)
            .put("false_wake_runaway_paused_at", falseWakeRunawayPausedAt)
            .put("false_wake_runaway_reason", falseWakeRunawayReason)
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
            writeText((sanitizeJsonValue(status) as? JSONObject ?: JSONObject()).toString(2))
        }
    }

    private fun writeLifecycleMarker(stage: String, intent: Intent? = null, startId: Int = 0) {
        val activeProviders = providers
        val marker = JSONObject()
            .put("schema", "hermes.wasm_agent.android_wake_lifecycle.v1")
            .put("build_id", BuildConfig.NATIVE_BUILD_ID)
            .put("stage", stage)
            .put("action", intent?.action.orEmpty())
            .put("start_id", startId)
            .put("running", running)
            .put("worker_alive", worker?.isAlive == true)
            .put("audio_record_started", audioRecordStartedAt > 0L && lastAudioRecordError.isBlank())
            .put("audio_read_calls", audioReadCalls)
            .put("audio_samples_read", audioSamplesRead)
            .put("inference_count", inferenceCount)
            .put("last_confidence", lastInferenceConfidence)
            .put("max_observed_confidence", maxObservedConfidence)
            .put("wake_threshold", currentWakeThreshold())
            .put("wake_confirmation_frames", configuredWakeConfirmationFrames(this))
            .put("wake_confirmation_window_ms", configuredWakeConfirmationWindowMs(this))
            .put("wake_cooldown_ms", configuredWakeCooldownMs(this))
            .put("raw_wake_detection_count", rawWakeDetectionCount)
            .put("wake_detection_count", wakeDetectionCount)
            .put("last_wake_frame_peak", lastWakeFramePeak)
            .put("max_wake_frame_peak", maxWakeFramePeak)
            .put("last_wake_frame_rms", lastWakeFrameRms)
            .put("max_wake_frame_rms", maxWakeFrameRms)
            .put("vad_rms_threshold", configuredVadRmsThreshold(this))
            .put("vad_peak_threshold", configuredVadPeakThreshold(this))
            .put("vad_pass_count", vadPassCount)
            .put("vad_reject_count", vadRejectCount)
            .put("last_vad_speech", lastVadSpeech)
            .put("wake_provider", activeProviders?.wake?.name.orEmpty())
            .put("vad_provider", activeProviders?.vad?.name.orEmpty())
            .put("model_source", activeProviders?.modelSource.orEmpty())
            .put("last_listen_exit_reason", lastListenExitReason)
            .put("last_listen_exit_detail", lastListenExitDetail)
            .put("last_failure_reason", lastFailureReason)
            .put("last_audio_record_error", lastAudioRecordError)
            .put("voice_state", machine.state.name.lowercase(Locale.US))
            .put("last_wake_at", machine.lastWakeAt)
            .put("last_wake_confidence", machine.lastWakeConfidence)
            .put("command_capture_started", commandCaptureStartedAt > 0L)
            .put("command_capture_started_at", commandCaptureStartedAt)
            .put("active_transcript_capture_id", activeTranscriptCaptureId)
            .put("last_transcript_status", machine.lastTranscriptStatus)
            .put("last_transcript_result", lastTranscriptResult)
            .put("last_asr_engine", lastAsrEngine)
            .put("last_asr_latency_ms", lastAsrLatencyMs)
            .put("last_asr_audio_captured_ms", lastAsrAudioCapturedMs)
            .put("last_asr_partial_transcript", lastAsrPartialTranscript)
            .put("last_asr_diagnostics", parseJsonObject(lastAsrDiagnostics))
            .put("last_normalized_transcript", lastNormalizedTranscript)
            .put("last_voice_command", lastVoiceCommand)
            .put("voice_command_event_dispatched", voiceCommandEventDispatchedAt > 0L)
            .put("voice_command_event_dispatched_at", voiceCommandEventDispatchedAt)
            .put("last_voice_command_event", machine.lastEvent?.toJson() ?: JSONObject.NULL)
            .put("last_error", machine.lastError)
            .put("last_exception", if (lastException.isBlank()) JSONObject.NULL else lastException)
            .put("timestamp_ms", System.currentTimeMillis())
        try {
            lifecycleFile(this).apply {
                parentFile?.mkdirs()
                writeText(marker.toString(2))
            }
        } catch (_: Exception) {
        }
        try {
            writePublicLifecycleMarker(marker)
        } catch (_: Exception) {
        }
        Log.i(LOG_TAG, "wake_lifecycle_marker=${marker.toString().take(1200)}")
    }

    private fun writePublicLifecycleMarker(marker: JSONObject) {
        val json = marker.toString(2)
        try {
            getExternalFilesDir(null)?.resolve("native-diagnostics/wake-lifecycle.json")?.apply {
                parentFile?.mkdirs()
                writeText(json)
            }
        } catch (_: Exception) {
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val resolver = contentResolver
            val collection = MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
            val relativePath = "${Environment.DIRECTORY_DOWNLOADS}/WASM-Agent"
            resolver.delete(
                collection,
                "${MediaStore.MediaColumns.DISPLAY_NAME}=? AND ${MediaStore.MediaColumns.RELATIVE_PATH}=?",
                arrayOf("wake-lifecycle.json", "$relativePath/"),
            )
            val values = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, "wake-lifecycle.json")
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
        val file = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "WASM-Agent/wake-lifecycle.json")
        file.parentFile?.mkdirs()
        file.writeText(json)
    }

    private fun confidenceMetricsJson(): JSONObject = JSONObject()
        .put("last_confidence", lastInferenceConfidence)
        .put("max_confidence", maxObservedConfidence)
        .put("threshold", currentWakeThreshold())
        .put("proof_threshold_override", proofWakeThresholdOverride ?: JSONObject.NULL)
        .put("effective_wake_threshold", currentWakeThreshold())
        .put("threshold_margin", maxObservedConfidence - currentWakeThreshold())
        .put("threshold_policy_source", currentWakeThresholdSource())
        .put("wake_confirmation", wakeConfirmationGate.snapshot(
            configuredWakeConfirmationFrames(this),
            configuredWakeConfirmationWindowMs(this),
        ))
        .put("threshold_crossed", lastInferenceThresholdCrossed)
        .put("raw_wake_detection_count", rawWakeDetectionCount)
        .put("last_raw_wake_detection_at", lastRawWakeDetectionAt)
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
                .put("raw_detected", false)
                .put("detected", false)
                .put("wake_confirmed", false)
                .put("wake_confirmation", wakeConfirmationGate.snapshot(
                    configuredWakeConfirmationFrames(this),
                    configuredWakeConfirmationWindowMs(this),
                ))
                .put("detection_count", wakeDetectionCount)
                .put("last_detection_timestamp", lastWakeDetectionAt)
                .put("rejection_reason", lastInferenceRejectionReason)
            else sanitizeJsonValue(inferenceWindows.last()) as? JSONObject ?: JSONObject()
        }
    }

    private fun inferenceWindowsJson(): JSONArray {
        val array = JSONArray()
        synchronized(inferenceWindows) {
            inferenceWindows.forEach { item -> array.put(sanitizeJsonValue(item) as? JSONObject ?: JSONObject()) }
        }
        return array
    }

    private fun sanitizeJsonValue(value: Any?, depth: Int = 0): Any {
        if (depth > 10) return "[depth-limit]"
        if (value == null || value == JSONObject.NULL) return JSONObject.NULL
        return when (value) {
            is JSONObject -> {
                val output = JSONObject()
                val keys = value.keys()
                while (keys.hasNext()) {
                    val key = keys.next()
                    output.put(key, sanitizeJsonValue(value.opt(key), depth + 1))
                }
                output
            }
            is JSONArray -> {
                val output = JSONArray()
                for (index in 0 until value.length()) {
                    output.put(sanitizeJsonValue(value.opt(index), depth + 1))
                }
                output
            }
            is Double -> if (java.lang.Double.isFinite(value)) value else JSONObject.NULL
            is Float -> if (java.lang.Float.isFinite(value)) value else JSONObject.NULL
            is Number, is Boolean, is String -> value
            else -> value.toString()
        }
    }

    private fun parseJsonObject(raw: String): JSONObject = try {
        sanitizeJsonValue(JSONObject(raw)) as? JSONObject ?: JSONObject()
    } catch (_: Exception) {
        JSONObject()
    }

    private fun safeJsonString(value: Any?, indentSpaces: Int = 0): String {
        return try {
            when (val safe = sanitizeJsonValue(value)) {
                is JSONObject -> if (indentSpaces > 0) safe.toString(indentSpaces) else safe.toString()
                is JSONArray -> if (indentSpaces > 0) safe.toString(indentSpaces) else safe.toString()
                else -> JSONObject().put("value", safe).toString()
            }
        } catch (_: Throwable) {
            JSONObject().put("available", false).put("error", "json_serialization_failed").toString()
        }
    }

    private fun transcriptAttemptStartedDiagnostics(
        engine: String,
        timeoutMs: Long,
        policy: TranscriptionPolicy,
    ): JSONObject = JSONObject()
        .put("schema", "hermes.wasm_agent.transcript_attempt_started.v1")
        .put("engine", engine)
        .put("timeout_ms", timeoutMs)
        .put("accept_partial_results", policy.acceptPartialResults)
        .put("minimum_length_ms", policy.minimumLengthMs)
        .put("complete_silence_ms", policy.completeSilenceMs)
        .put("possibly_complete_silence_ms", policy.possiblyCompleteSilenceMs)
        .put("attempt_plan", policy.attemptPlan)
        .put("started_at", System.currentTimeMillis())

    private fun reconcileStaleTranscript(reason: String = "") {
        val captureId = activeTranscriptCaptureId.takeIf { it > 0L } ?: commandCaptureStartedAt
        if (captureId <= 0L) return
        val timeoutMs = configuredTranscriptTimeoutMs(this)
        val elapsed = System.currentTimeMillis() - captureId
        if (elapsed < timeoutMs + 2_500L) return
        val policy = configuredTranscriptPolicy(this)
        val engine = lastAsrEngine.ifBlank { currentProviders().transcriber.name }
        val diagnostics = JSONObject()
            .put("schema", "hermes.wasm_agent.transcript_status_reconciled_timeout.v1")
            .put("engine", engine)
            .put("timeout_ms", timeoutMs)
            .put("elapsed_ms", elapsed)
            .put("capture_id", captureId)
            .put("reason", reason)
            .put("attempt_plan", policy.attemptPlan)
        lastTranscriptResult = "transcript_status_reconciled_timeout"
        lastAsrEngine = engine
        lastAsrLatencyMs = elapsed
        lastAsrAudioCapturedMs = 0L
        lastAsrPartialTranscript = ""
        lastAsrDiagnostics = safeJsonString(diagnostics)
        lastException = "transcript_status_reconciled_timeout"
        activeTranscriptCaptureId = 0L
        commandCaptureStartedAt = 0L
        rememberEvent("transcript_status_reconciled_timeout", diagnostics)
        machine.fail("transcript_status_reconciled_timeout")
        machine.listenAgain()
        standbyRestoredAt = System.currentTimeMillis()
        rememberEvent("standby_restored", JSONObject().put("reason", "transcript_status_reconciled_timeout"))
    }

    private fun startTranscriptWatchdog(
        captureId: Long,
        engine: String,
        timeoutMs: Long,
        policy: TranscriptionPolicy,
    ) {
        thread(name = "hermes-transcript-watchdog", isDaemon = true) {
            try {
                Thread.sleep(timeoutMs + 2_500L)
            } catch (_: InterruptedException) {
                return@thread
            }
            if (!running || activeTranscriptCaptureId != captureId) return@thread
            val elapsed = System.currentTimeMillis() - captureId
            val diagnostics = JSONObject()
                .put("schema", "hermes.wasm_agent.transcript_watchdog_timeout.v1")
                .put("engine", engine)
                .put("timeout_ms", timeoutMs)
                .put("elapsed_ms", elapsed)
                .put("capture_id", captureId)
                .put("attempt_plan", policy.attemptPlan)
            lastTranscriptResult = "transcript_watchdog_timeout"
            lastAsrEngine = engine
            lastAsrLatencyMs = elapsed
            lastAsrAudioCapturedMs = 0L
            lastAsrPartialTranscript = ""
            lastAsrDiagnostics = safeJsonString(diagnostics)
            lastException = "transcript_watchdog_timeout"
            rememberEvent("transcript_watchdog_timeout", diagnostics)
            writeStatus("transcript_watchdog_timeout")
        }
    }

    private fun transcribeWithTimeout(
        transcriber: com.colmeio.wasmagent.voice.TranscriptionEngine,
        timeoutMs: Long,
        policy: TranscriptionPolicy,
        prebufferAudio: ShortArray = ShortArray(0),
    ): TranscriptionResult {
        val executor = Executors.newSingleThreadExecutor { runnable ->
            Thread(runnable, "hermes-transcript-engine").apply { isDaemon = true }
        }
        val startedAt = System.currentTimeMillis()
        val future = executor.submit<TranscriptionResult> {
            transcriber.transcribeLiveAfterWake(timeoutMs, policy)
        }
        return try {
            val primary = future.get(timeoutMs + 1_500L, TimeUnit.MILLISECONDS)
            transcriptWithPrebufferFallback(primary, prebufferAudio, startedAt)
        } catch (error: TimeoutException) {
            future.cancel(true)
            lastException = "transcript_engine_timeout"
            val primary = TranscriptionResult(
                transcript = "",
                confidence = 0.0,
                error = "transcript_engine_timeout",
                engine = transcriber.name,
                latencyMs = System.currentTimeMillis() - startedAt,
                diagnostics = JSONObject()
                    .put("schema", "hermes.wasm_agent.transcript_engine_timeout.v1")
                    .put("engine", transcriber.name)
                    .put("timeout_ms", timeoutMs)
                    .put("elapsed_ms", System.currentTimeMillis() - startedAt)
                    .put("attempt_plan", policy.attemptPlan),
            )
            transcriptWithPrebufferFallback(primary, prebufferAudio, startedAt)
        } catch (error: Throwable) {
            val root = error.cause ?: error
            val failure = "transcript_engine_${root.javaClass.simpleName}"
            lastException = describeThrowable(root)
            val primary = TranscriptionResult(
                transcript = "",
                confidence = 0.0,
                error = failure,
                engine = transcriber.name,
                latencyMs = System.currentTimeMillis() - startedAt,
                diagnostics = JSONObject()
                    .put("schema", "hermes.wasm_agent.transcript_engine_exception.v1")
                    .put("engine", transcriber.name)
                    .put("error", failure)
                    .put("exception", lastException),
            )
            transcriptWithPrebufferFallback(primary, prebufferAudio, startedAt)
        } finally {
            executor.shutdownNow()
        }
    }

    private fun transcriptWithPrebufferFallback(
        primary: TranscriptionResult,
        prebufferAudio: ShortArray,
        startedAt: Long,
    ): TranscriptionResult {
        if (prebufferAudio.isEmpty()) return primary
        val normalizedPrimary = VoiceCommandNormalizer.normalizeTranscript(primary.transcript)
        val clippedPrimary = normalizedPrimary.isBlank() || normalizedPrimary == "word"
        val primaryCommand = VoiceCommandNormalizer.commandForTranscript(primary.transcript)
        if (!clippedPrimary || primaryCommand.isNotBlank()) return primary
        val fallback = LocalCommandTranscriptionEngine(
            this,
            preferredEngine = LocalCommandTranscriptionEngine.PREF_ENGINE_VOSK,
        )
        val diagnostics = fallback.diagnostics()
        if (!diagnostics.optBoolean("local_asr_vosk_ready", false)) return primary
        val retry = fallback.transcribePcm16(
            prebufferAudio,
            LocalCommandTranscriptionEngine.SAMPLE_RATE_HZ,
            3_000L,
        )
        val normalizedRetry = VoiceCommandNormalizer.normalizeTranscript(retry.transcript)
        val retryCommand = VoiceCommandNormalizer.commandForTranscript(retry.transcript)
        val retryBetter = when {
            retryCommand.isNotBlank() -> true
            normalizedPrimary.isBlank() && normalizedRetry.isNotBlank() -> true
            normalizedPrimary == "word" && normalizedRetry.split(" ").size > 1 -> true
            else -> false
        }
        val combinedDiagnostics = JSONObject()
            .put("schema", "hermes.wasm_agent.prebuffer_transcript_retry.v1")
            .put("primary", primary.diagnostics)
            .put("primary_engine", primary.engine)
            .put("primary_transcript", primary.transcript.take(160))
            .put("primary_normalized", normalizedPrimary)
            .put("retry", retry.diagnostics)
            .put("retry_engine", retry.engine)
            .put("retry_transcript", retry.transcript.take(160))
            .put("retry_normalized", normalizedRetry)
            .put("retry_command", retryCommand)
            .put("prebuffer_sample_count", prebufferAudio.size)
            .put("selected", if (retryBetter) "prebuffer" else "primary")
        rememberEvent("transcript_prebuffer_retry", JSONObject()
            .put("selected", if (retryBetter) "prebuffer" else "primary")
            .put("primary_normalized", normalizedPrimary)
            .put("retry_normalized", normalizedRetry)
            .put("retry_command", retryCommand))
        return if (retryBetter) {
            retry.copy(
                engine = "${primary.engine.ifBlank { "primary" }}+prebuffer:${retry.engine}",
                latencyMs = System.currentTimeMillis() - startedAt,
                audioCapturedMs = retry.audioCapturedMs,
                diagnostics = combinedDiagnostics,
            )
        } else {
            primary.copy(diagnostics = combinedDiagnostics)
        }
    }

    private fun describeThrowable(error: Throwable): String {
        val message = error.message?.takeIf { it.isNotBlank() }
        return if (message == null) error.javaClass.name else "${error.javaClass.name}: $message"
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
    ): Boolean {
        val modelSha = sha256OrBlank(personalizedModelFile)
        falseWakeCount += 1
        lastFalseWakeAt = timestamp
        val stormCount = recordFalseWakeStorm(timestamp)
        val wakeCooldownMs = configuredWakeCooldownMs(this)
        wakeCooldownUntil = System.currentTimeMillis() + wakeCooldownMs
        val metadata = JSONObject()
            .put("id", "fw-$timestamp-${UUID.randomUUID()}")
            .put("timestamp", timestamp)
            .put("wake_confidence", wake.confidence.coerceIn(0.0, 1.0))
            .put("threshold", currentWakeThreshold())
            .put("wake_cooldown_ms", wakeCooldownMs)
            .put("false_wake_storm_count", stormCount)
            .put("false_wake_storm_limit", FALSE_WAKE_STORM_LIMIT)
            .put("false_wake_storm_window_ms", FALSE_WAKE_STORM_WINDOW_MS)
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
            .put("false_wake_count", falseWakeCount)
            .put("false_wake_storm_count", stormCount))
        if (stormCount < FALSE_WAKE_STORM_LIMIT) return false
        pauseAfterFalseWakeRunaway(rejectionReason, stormCount)
        return true
    }

    private fun recordFalseWakeStorm(timestamp: Long): Int {
        if (falseWakeStormStartedAt <= 0L || timestamp - falseWakeStormStartedAt > FALSE_WAKE_STORM_WINDOW_MS) {
            falseWakeStormStartedAt = timestamp
            falseWakeStormCount = 0
        }
        falseWakeStormCount += 1
        return falseWakeStormCount
    }

    private fun resetFalseWakeStorm() {
        falseWakeStormStartedAt = 0L
        falseWakeStormCount = 0
        falseWakeRunawayReason = ""
    }

    private fun pauseAfterFalseWakeRunaway(reason: String, stormCount: Int) {
        running = false
        activeTranscriptCaptureId = 0L
        commandCaptureStartedAt = 0L
        falseWakeRunawayPausedAt = System.currentTimeMillis()
        falseWakeRunawayReason = reason
        lastFailureReason = "false_wake_runaway_paused"
        lastException = ""
        machine.fail(lastFailureReason)
        machine.disable()
        rememberEvent("false_wake_runaway_paused", JSONObject()
            .put("reason", reason)
            .put("false_wake_storm_count", stormCount)
            .put("false_wake_storm_limit", FALSE_WAKE_STORM_LIMIT)
            .put("false_wake_storm_window_ms", FALSE_WAKE_STORM_WINDOW_MS)
            .put("threshold", currentWakeThreshold())
            .put("last_confidence", lastInferenceConfidence))
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) stopForeground(STOP_FOREGROUND_REMOVE) else @Suppress("DEPRECATION") stopForeground(true)
        stopSelf()
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

    private fun sha256Text(value: String): String {
        return try {
            MessageDigest.getInstance("SHA-256")
                .digest(value.toByteArray(Charsets.UTF_8))
                .joinToString("") { "%02x".format(it) }
        } catch (_: Exception) {
            ""
        }
    }

    private fun readinessDisabledReason(
        enabled: Boolean,
        permissionGranted: Boolean,
        foregroundServiceRunning: Boolean,
        wakeDiagnostics: org.json.JSONObject,
        modelExists: Boolean,
    ): String {
        if (!permissionGranted) return "record_audio_permission_missing"
        if (!enabled) return "voice_wake_disabled"
        if (!foregroundServiceRunning) return "foreground_service_not_running"
        if (!wakeDiagnostics.optBoolean("onnx_runtime_available", false)) return "onnx_runtime_unavailable"
        if (!modelExists) return "wake_model_missing"
        if (!wakeDiagnostics.optBoolean("wake_engine_ready", false)) return "wake_engine_not_ready"
        if (lastAudioRecordError.startsWith("audio_capture_stalled")) return "audio_capture_stalled"
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
    ): String {
        if (lastFailureReason.isNotBlank()) return lastFailureReason
        if (!permissionGranted) return "record_audio_permission_missing"
        if (!foregroundServiceRunning) return "foreground_service_not_started"
        if (!modelExists) return "onnx_model_missing"
        if (!wakeDiagnostics.optBoolean("onnx_runtime_available", false)) return "onnx_model_load_failed"
        if (!wakeDiagnostics.optBoolean("wake_engine_ready", false)) return "onnx_model_load_failed"
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

    private fun installBundledVoskModelIfPresent() {
        if (installBundledVoskModelIfPresent(voskModelDir, assets)) {
            providers = null
            rememberEvent("vosk_model_installed", JSONObject().put("path", "files/${LocalCommandTranscriptionEngine.MODEL_PATH}"))
        }
    }

    private fun bundledVoskModelAvailable(): Boolean {
        return bundledVoskModelAvailable(assets)
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
                wakeForegroundIntent(),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            ))
            .build()
    }

    override fun onCreate() {
        super.onCreate()
        writeLifecycleMarker("on_create")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel(
                CHANNEL_ID,
                "Hermes Voice Wake",
                NotificationManager.IMPORTANCE_LOW,
            ))
        }
        writeLifecycleMarker("on_create_complete")
    }
}
