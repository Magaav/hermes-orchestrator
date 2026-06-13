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
)

data class VoiceWakeEvent(
    val transcript: String,
    val confidence: Double,
    val startedAt: Long,
    val endedAt: Long,
    val buildId: String,
    val sessionId: String = UUID.randomUUID().toString(),
    val privacyMode: String = "wake-word-local-transcript-only",
) {
    fun toJson(): JSONObject = JSONObject()
        .put("type", "voice_command")
        .put("wake_word", "hermes")
        .put("wake_confidence", confidence)
        .put("transcript", transcript)
        .put("confidence", confidence)
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
