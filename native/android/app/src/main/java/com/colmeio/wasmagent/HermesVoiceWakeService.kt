package com.colmeio.wasmagent

import android.Manifest
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
import android.util.Log
import com.colmeio.wasmagent.voice.AndroidSpeechRecognizerEngine
import com.colmeio.wasmagent.voice.OpenWakeWordOnnxEngine
import com.colmeio.wasmagent.voice.WakeWordResult
import com.colmeio.wasmagent.voice.WakeModelSelection
import com.colmeio.wasmagent.voice.WakeModelSelector
import com.colmeio.wasmagent.voice.VoiceCommandRouter
import com.colmeio.wasmagent.voice.VoiceProviderSelector
import com.colmeio.wasmagent.voice.VoiceProviderSet
import com.colmeio.wasmagent.voice.VoiceWakeEvent
import com.colmeio.wasmagent.voice.VoiceWakeStateMachine
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
        const val DEFAULT_WAKE_THRESHOLD = OpenWakeWordOnnxEngine.DEFAULT_CONFIDENCE_THRESHOLD
        const val THRESHOLD_SOURCE_NATIVE_DEFAULT = "native_default"
        const val THRESHOLD_SOURCE_PROOF_INTENT_OVERRIDE = "proof_intent_override"
        const val THRESHOLD_SOURCE_REMOTE_CONFIG = "remote_config"
        private const val CHANNEL_ID = "wasm_agent_hermes_voice_wake"
        private const val NOTIFICATION_ID = 4721
        private const val LOG_TAG = "HermesVoiceWake"
        private const val MAX_CAPTURE_MS = 12_000L
        private const val MIN_WAKE_THRESHOLD = 0.05
        private const val MAX_WAKE_THRESHOLD = 0.99
        private const val ACCEPTANCE_MODEL_SHA256 = "23aee3f94d9499c7809b413037a59e3e6f8668767a49e077017e743dd959e58c"

        fun statusFile(context: Context): File = File(context.filesDir, "native-diagnostics/voice-wake.json")

        fun normalizedWakeThreshold(value: Double): Double? =
            if (value.isFinite() && value in MIN_WAKE_THRESHOLD..MAX_WAKE_THRESHOLD) value else null

        fun configuredWakeThreshold(context: Context): Double {
            val raw = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .getFloat(PREF_WAKE_THRESHOLD, DEFAULT_WAKE_THRESHOLD.toFloat())
                .toDouble()
            return normalizedWakeThreshold(raw) ?: DEFAULT_WAKE_THRESHOLD
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
    }

    private val machine = VoiceWakeStateMachine()
    @Volatile private var running = false
    @Volatile private var worker: Thread? = null
    private val personalizedModelFile by lazy { File(filesDir, "voice/hermes.onnx") }
    private val baseModelFile by lazy { File(filesDir, "voice/base_hermes.onnx") }
    @Volatile private var wakeModelSelection: WakeModelSelection? = null
    private val transcriptionEngine by lazy { AndroidSpeechRecognizerEngine(this) }
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

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.getBooleanExtra(EXTRA_PROOF_SESSION, false) == true) {
            proofSessionActive = true
        }
        val thresholdChanged = applyWakeThresholdExtra(intent, proofSessionActive)
        when (intent?.action) {
            ACTION_STOP -> {
                stopListening("user_disabled")
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_STATUS -> {
                if (running) {
                    writeStatus(if (thresholdChanged) "wake_threshold_updated" else if (proofSessionActive) "proof_status_requested" else "")
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

    override fun onDestroy() {
        if (running) {
            stopListening("service_destroy")
        } else {
            writeStatus("service_destroy")
        }
        super.onDestroy()
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
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit().putBoolean(PREF_ENABLED, false).apply()
        machine.disable()
        writeStatus(reason)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) stopForeground(STOP_FOREGROUND_REMOVE) else @Suppress("DEPRECATION") stopForeground(true)
    }

    private fun listenLoop(origin: String) {
        while (running) {
            val wake = listenForWake()
            if (wake == null || !running) continue
            val startedAt = System.currentTimeMillis()
            commandCaptureStartedAt = startedAt
            Log.i(LOG_TAG, "command_capture_started=true wake_detection_count=$wakeDetectionCount last_confidence=$lastInferenceConfidence")
            machine.beginTranscribing()
            writeStatus()
            val transcript = currentProviders().transcriber.transcribeLiveAfterWake(MAX_CAPTURE_MS)
            val endedAt = System.currentTimeMillis()
            if (transcript.transcript.isBlank()) {
                machine.fail(transcript.error.ifBlank { "transcription_empty" })
                writeStatus()
                machine.listenAgain()
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
            writeStatus()
            postVoiceEvent(origin, event)
            machine.listenAgain()
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
                val activeProviders = currentProviders()
                if (!proofSessionActive && !activeProviders.vad.isSpeech(frame, OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ)) continue
                val wake = activeProviders.wake.processPcm16(frame, OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ)
                recordInference(wake)
                if (inferenceCount == 1L || inferenceCount % 20L == 0L || wake.detected) {
                    Log.i(LOG_TAG, "inference_count=$inferenceCount last_confidence=$lastInferenceConfidence wake_detected=${wake.detected}")
                }
                if (proofSessionActive) {
                    if (wake.detected) {
                        wakeDetectionCount += 1
                        lastWakeDetectionAt = System.currentTimeMillis()
                        Log.i(LOG_TAG, "wake_detected=true wake_detection_count=$wakeDetectionCount last_confidence=$lastInferenceConfidence")
                        lastWakePass = true
                        lastWakeProofResult = "pass"
                        writeStatus("proof_wake_detected")
                        postWakeDetectedEvent(wake)
                        return wake
                    }
                    writeStatus("proof_inference_observed")
                    continue
                }
                if (machine.onWake(wake)) {
                    wakeDetectionCount += 1
                    lastWakeDetectionAt = System.currentTimeMillis()
                    lastWakePass = true
                    lastWakeProofResult = "pass"
                    writeStatus()
                    postWakeDetectedEvent(wake)
                    return wake
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
            machine.dispatched(result.toJson().put("event_type", "wake_detected"))
            if (!result.ok) {
                machine.fail("wake_detected_post_failed:${result.error.ifBlank { "http_${result.statusCode}" }}")
            }
            writeStatus("wake_detected_event")
        }
    }

    private fun postVoiceEvent(origin: String, event: VoiceWakeEvent) {
        thread(name = "hermes-voice-wake-event") {
            val result = router.dispatch(origin, event, currentProviders().transcriber.name)
            if (result.ok) voiceCommandEventDispatchedAt = System.currentTimeMillis()
            machine.dispatched(result.toJson())
            if (!result.ok) {
                machine.fail("voice_event_post_failed:${result.error.ifBlank { "http_${result.statusCode}" }}")
            }
            writeStatus(if (result.ok) "voice_command_event_dispatched" else "voice_command_event_dispatch_failed")
        }
    }

    private fun writeStatus(reason: String = "") {
        val activeSelection = currentWakeModelSelection()
        val activeWakeEngine = activeSelection.engine
        val wakeDiagnostics = activeWakeEngine.diagnostics()
        val activeProviders = currentProviders()
        val wakeThreshold = currentWakeThreshold()
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
            .put("last_inference_threshold_crossed", lastInferenceThresholdCrossed)
            .put("threshold_crossed", lastInferenceThresholdCrossed)
            .put("last_inference_rejection_reason", lastInferenceRejectionReason)
            .put("rejection_reason", lastInferenceRejectionReason)
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
            productionTranscriber = transcriptionEngine,
            modelSource = activeSelection.source,
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
