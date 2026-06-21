package com.colmeio.wasmagent.voice

import org.json.JSONObject
import java.util.Locale
import java.util.UUID

enum class VoiceWakeState {
    DISABLED,
    LISTENING,
    CAPTURING,
    TRANSCRIBING,
    SENT,
    ERROR,
}

data class WakeWordResult(
    val detected: Boolean,
    val wakeWord: String = "hermes",
    val confidence: Double = 0.0,
    val audioWindow: ShortArray = ShortArray(0),
)

data class WakeConfirmationDecision(
    val wake: WakeWordResult,
    val rawDetected: Boolean,
    val accepted: Boolean,
    val frames: Int,
    val requiredFrames: Int,
    val windowMs: Long,
    val candidateStartedAt: Long,
    val acceptedAt: Long,
    val maxConfidence: Double,
    val rejectionReason: String,
)

class WakeConfirmationGate {
    @Volatile var candidateStartedAt: Long = 0
        private set
    @Volatile var candidateFrames: Int = 0
        private set
    @Volatile var acceptedAt: Long = 0
        private set
    @Volatile var candidateMaxConfidence: Double = 0.0
        private set
    @Volatile var rejectionReason: String = "not_started"
        private set

    fun reset(reason: String = "not_started") {
        candidateStartedAt = 0
        candidateFrames = 0
        acceptedAt = 0
        candidateMaxConfidence = 0.0
        rejectionReason = reason.ifBlank { "not_started" }.take(120)
    }

    fun observe(
        wake: WakeWordResult,
        now: Long = System.currentTimeMillis(),
        requiredFrames: Int = 2,
        windowMs: Long = 700L,
    ): WakeConfirmationDecision {
        val required = requiredFrames.coerceIn(1, 5)
        val window = windowMs.coerceIn(150L, 2_000L)
        if (!wake.detected) {
            if (candidateFrames > 0) reset("below_threshold")
            rejectionReason = "below_threshold"
            return decision(wake.copy(detected = false), false, false, required, window)
        }
        val confidence = wake.confidence.coerceIn(0.0, 1.0)
        if (candidateStartedAt <= 0L || now - candidateStartedAt > window) {
            candidateStartedAt = now
            candidateFrames = 1
            candidateMaxConfidence = confidence
        } else {
            candidateFrames += 1
            candidateMaxConfidence = maxOf(candidateMaxConfidence, confidence)
        }
        if (candidateFrames >= required) {
            acceptedAt = now
            rejectionReason = ""
            return decision(
                wake.copy(detected = true, confidence = candidateMaxConfidence),
                true,
                true,
                required,
                window,
            )
        }
        rejectionReason = "wake_confirmation_pending"
        return decision(wake.copy(detected = false), true, false, required, window)
    }

    fun snapshot(requiredFrames: Int = 2, windowMs: Long = 700L): JSONObject = JSONObject()
        .put("required_frames", requiredFrames.coerceIn(1, 5))
        .put("window_ms", windowMs.coerceIn(150L, 2_000L))
        .put("candidate_started_at", candidateStartedAt)
        .put("candidate_frames", candidateFrames)
        .put("candidate_max_confidence", candidateMaxConfidence)
        .put("accepted_at", acceptedAt)
        .put("rejection_reason", rejectionReason)

    private fun decision(
        wake: WakeWordResult,
        rawDetected: Boolean,
        accepted: Boolean,
        requiredFrames: Int,
        windowMs: Long,
    ): WakeConfirmationDecision = WakeConfirmationDecision(
        wake = wake,
        rawDetected = rawDetected,
        accepted = accepted,
        frames = candidateFrames,
        requiredFrames = requiredFrames,
        windowMs = windowMs,
        candidateStartedAt = candidateStartedAt,
        acceptedAt = acceptedAt,
        maxConfidence = candidateMaxConfidence,
        rejectionReason = rejectionReason,
    )
}

data class VoiceWakeEvent(
    val transcript: String,
    val confidence: Double,
    val startedAt: Long,
    val endedAt: Long,
    val buildId: String,
    val command: String = "",
    val wakeWord: String = "hermes",
    val sessionId: String = UUID.randomUUID().toString(),
    val privacyMode: String = "wake-word-local-transcript-only",
) {
    private fun safeConfidence(): Any =
        if (java.lang.Double.isFinite(confidence)) confidence else JSONObject.NULL

    fun toJson(): JSONObject = JSONObject()
        .put("type", "voice_command")
        .put("wake_word", wakeWord.ifBlank { "hermes" })
        .put("wake_confidence", safeConfidence())
        .put("transcript", transcript)
        .put("command", command)
        .put("confidence", safeConfidence())
        .put("started_at", startedAt)
        .put("ended_at", endedAt)
        .put("source", "android_native_voice_wake")
        .put("build_id", buildId)
        .put("session_id", sessionId)
        .put("privacy_mode", privacyMode)
        .put("audio_retained", false)
}

class VoiceWakeStateMachine {
    var state: VoiceWakeState = VoiceWakeState.DISABLED
        private set
    var lastWakeAt: Long = 0
        private set
    var lastTranscript: String = ""
        private set
    var lastError: String = ""
        private set
    var lastCommandCaptureDurationMs: Long = 0
        private set
    var lastTranscriptStatus: String = "idle"
        private set
    var lastEvent: VoiceWakeEvent? = null
        private set
    var lastWakeConfidence: Double = 0.0
        private set
    var lastDispatchResult: Any = JSONObject.NULL
        private set

    fun enable() {
        lastError = ""
        state = VoiceWakeState.LISTENING
    }

    fun disable() {
        state = VoiceWakeState.DISABLED
    }

    fun onWake(result: WakeWordResult, now: Long = System.currentTimeMillis()): Boolean {
        if (state != VoiceWakeState.LISTENING || !result.detected) return false
        lastWakeAt = now
        lastWakeConfidence = result.confidence
        state = VoiceWakeState.CAPTURING
        return true
    }

    fun beginTranscribing() {
        if (state == VoiceWakeState.CAPTURING) {
            lastTranscriptStatus = "capturing"
            state = VoiceWakeState.TRANSCRIBING
        }
    }

    fun complete(event: VoiceWakeEvent) {
        lastEvent = event
        lastTranscript = event.transcript
        lastCommandCaptureDurationMs = (event.endedAt - event.startedAt).coerceAtLeast(0)
        lastTranscriptStatus = "transcribed"
        lastError = ""
        state = VoiceWakeState.SENT
    }

    fun dispatched(result: JSONObject) {
        lastDispatchResult = result
    }

    fun listenAgain() {
        if (state != VoiceWakeState.DISABLED) state = VoiceWakeState.LISTENING
    }

    fun fail(message: String) {
        lastError = message.ifBlank { "voice wake error" }.take(240)
        lastTranscriptStatus = if (state == VoiceWakeState.TRANSCRIBING || state == VoiceWakeState.CAPTURING) "failed" else lastTranscriptStatus
        state = VoiceWakeState.ERROR
    }

    fun blocked(message: String) {
        lastError = message.ifBlank { "voice wake unavailable" }.take(240)
        lastTranscriptStatus = "blocked"
        state = VoiceWakeState.LISTENING
    }

    fun snapshot(
        enabled: Boolean,
        permissionGranted: Boolean,
        foregroundServiceRunning: Boolean,
        wakeEngine: String,
        wakeEngineReady: Boolean,
        transcriptionEngine: String,
        vadProvider: String = "",
        wakeProvider: String = "",
        asrProvider: String = "",
        modelSource: String = "",
        selectedModelPath: String = "files/voice/hermes.onnx",
        debugVoiceModeEnabled: Boolean = false,
        batteryWarning: String = "",
    ): JSONObject = JSONObject()
        .put("schema", "hermes.wasm_agent.android_voice_wake.v1")
        .put("enabled", enabled)
        .put("state", state.name.lowercase(Locale.US))
        .put("visible_state", when (state) {
            VoiceWakeState.DISABLED -> "Disabled"
            VoiceWakeState.LISTENING -> "Listening for Hermes"
            VoiceWakeState.CAPTURING -> "Capturing"
            VoiceWakeState.TRANSCRIBING -> "Transcribing"
            VoiceWakeState.SENT -> "Sent"
            VoiceWakeState.ERROR -> "Error"
        })
        .put("wake_word", "hermes")
        .put("permission_record_audio", permissionGranted)
        .put("voice_service_running", foregroundServiceRunning)
        .put("foreground_service_running", foregroundServiceRunning)
        .put("notification_active", foregroundServiceRunning)
        .put("service_running", foregroundServiceRunning)
        .put("sample_rate_hz", 16000)
        .put("channels", 1)
        .put("bounded_capture_min_ms", 8000)
        .put("bounded_capture_max_ms", 20000)
        .put("wake_engine", wakeEngine)
        .put("vad_provider", vadProvider.ifBlank { "unknown" })
        .put("wake_provider", wakeProvider.ifBlank { wakeEngine })
        .put("asr_provider", asrProvider.ifBlank { transcriptionEngine })
        .put("wake_engine_ready", wakeEngineReady)
        .put("model_source", modelSource.ifBlank { "unknown" })
        .put("wake_model_path", selectedModelPath)
        .put("selected_model_path", selectedModelPath)
        .put("transcription_engine", transcriptionEngine)
        .put("last_wake_at", lastWakeAt)
        .put("last_wake_confidence", lastWakeConfidence)
        .put("last_command_capture_duration_ms", lastCommandCaptureDurationMs)
        .put("last_transcript_status", lastTranscriptStatus)
        .put("last_transcript", lastTranscript)
        .put("last_error", lastError)
        .put("last_voice_command_event", lastEvent?.toJson() ?: JSONObject.NULL)
        .put("last_dispatch_result", lastDispatchResult)
        .put("debug_voice_mode_enabled", debugVoiceModeEnabled)
        .put("last_emitted_voice_event", lastEvent?.toJson() ?: JSONObject.NULL)
        .put("last_event", lastEvent?.toJson() ?: JSONObject.NULL)
        .put("battery_warning", batteryWarning)
        .put("privacy_mode", "wake-word-local-transcript-only")
        .put("audio_retained", false)
        .put("continuous_transcription", false)
        .put("continuous_audio_uploaded", false)
}
