package com.colmeio.wasmagent.voice

import com.colmeio.wasmagent.BuildConfig
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

interface VoiceVad {
    val name: String
    fun isSpeech(samples: ShortArray, sampleRateHz: Int): Boolean
}

class DebugVad(private val enabled: Boolean) : VoiceVad {
    override val name: String = "debug_stub"
    override fun isSpeech(samples: ShortArray, sampleRateHz: Int): Boolean = enabled
}

class PassthroughVad : VoiceVad {
    override val name: String = "passthrough"
    override fun isSpeech(samples: ShortArray, sampleRateHz: Int): Boolean = true
}

class EnergyVoiceVad(
    private val rmsThreshold: Double = 0.012,
    private val peakThreshold: Int = 1800,
) : VoiceVad {
    override val name: String = "energy_gate"

    override fun isSpeech(samples: ShortArray, sampleRateHz: Int): Boolean {
        if (samples.isEmpty() || sampleRateHz <= 0) return false
        var sumSquares = 0.0
        var peak = 0
        for (sample in samples) {
            val value = kotlin.math.abs(sample.toInt())
            peak = maxOf(peak, value)
            val normalized = sample.toDouble() / Short.MAX_VALUE.toDouble()
            sumSquares += normalized * normalized
        }
        val rms = kotlin.math.sqrt(sumSquares / samples.size.toDouble())
        return rms >= rmsThreshold || peak >= peakThreshold
    }
}

class DebugWakeEngine(private val enabled: Boolean) : WakeWordEngine {
    override val name: String = "debug_stub"
    override val ready: Boolean = enabled
    private var emitted = false

    override fun processPcm16(samples: ShortArray, sampleRateHz: Int): WakeWordResult {
        if (!enabled || emitted) return WakeWordResult(false, confidence = 0.0)
        emitted = true
        return WakeWordResult(detected = true, confidence = 0.99)
    }
}

class DebugTranscriber(private val enabled: Boolean) : TranscriptionEngine {
    override val name: String = "debug_stub"
    override fun transcribePcm16(samples: ShortArray, sampleRateHz: Int, timeoutMs: Long): TranscriptionResult =
        if (enabled) TranscriptionResult("test command", 0.99) else TranscriptionResult("", 0.0, "debug_transcriber_disabled")
}

data class VoiceProviderSet(
    val vad: VoiceVad,
    val wake: WakeWordEngine,
    val transcriber: TranscriptionEngine,
    val debugVoiceModeEnabled: Boolean,
    val modelSource: String,
)

object VoiceProviderSelector {
    fun select(
        requestedDebugVoiceMode: Boolean,
        modelReady: Boolean,
        modelMissing: Boolean,
        productionWakeEngine: WakeWordEngine,
        productionTranscriber: TranscriptionEngine,
        modelSource: String = "",
        productionVad: VoiceVad = EnergyVoiceVad(),
        debugAllowed: Boolean = BuildConfig.DEBUG || BuildConfig.ALLOW_LOCAL_DEV,
    ): VoiceProviderSet {
        val debugEnabled = requestedDebugVoiceMode && debugAllowed
        return if (debugEnabled) {
            VoiceProviderSet(
                vad = DebugVad(enabled = true),
                wake = DebugWakeEngine(enabled = true),
                transcriber = DebugTranscriber(enabled = true),
                debugVoiceModeEnabled = true,
                modelSource = "debug_stub",
            )
        } else {
            VoiceProviderSet(
                vad = productionVad,
                wake = productionWakeEngine,
                transcriber = productionTranscriber,
                debugVoiceModeEnabled = false,
                modelSource = when {
                    modelReady -> modelSource.ifBlank { "base" }
                    modelMissing -> "none"
                    else -> "invalid_or_unavailable"
                },
            )
        }
    }
}

data class VoiceDispatchResult(
    val ok: Boolean,
    val statusCode: Int = 0,
    val error: String = "",
) {
    fun toJson(): JSONObject = JSONObject()
        .put("ok", ok)
        .put("status_code", statusCode)
        .put("error", error)
}

class VoiceCommandRouter {
    fun wakeDetectedPayload(event: VoiceWakeEvent, wakeProvider: String): JSONObject =
        JSONObject()
            .put("type", "wake_detected")
            .put("kind", "wake_detected")
            .put("platform", "android")
            .put("wake_word", "hermes")
            .put("wake_confidence", event.confidence)
            .put("confidence", event.confidence)
            .put("source", "android_native_voice_wake")
            .put("wake_provider", wakeProvider)
            .put("device_id", "android-${BuildConfig.NATIVE_BUILD_ID}")
            .put("build_id", event.buildId)
            .put("session_id", event.sessionId)
            .put("timestamp", System.currentTimeMillis())
            .put("started_at", event.startedAt)
            .put("ended_at", event.endedAt)
            .put("privacy_mode", event.privacyMode)
            .put("audio_retained", false)

    fun payload(event: VoiceWakeEvent, asrProvider: String): JSONObject =
        event.toJson()
            .put("kind", "voice_command")
            .put("platform", "android")
            .put("asr_provider", asrProvider)
            .put("device_id", "android-${BuildConfig.NATIVE_BUILD_ID}")
            .put("timestamp", System.currentTimeMillis())

    fun dispatchWakeDetected(origin: String, event: VoiceWakeEvent, wakeProvider: String): VoiceDispatchResult =
        dispatchPayload(origin, wakeDetectedPayload(event, wakeProvider))

    fun dispatch(origin: String, event: VoiceWakeEvent, asrProvider: String): VoiceDispatchResult {
        return dispatchPayload(origin, payload(event, asrProvider))
    }

    private fun dispatchPayload(origin: String, payload: JSONObject): VoiceDispatchResult {
        return try {
            val connection = (URL(origin.trimEnd('/') + "/native/events").openConnection() as HttpURLConnection).apply {
                connectTimeout = 3000
                readTimeout = 3000
                requestMethod = "POST"
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                doOutput = true
            }
            connection.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
            val status = connection.responseCode
            if (status in 200..299) {
                connection.inputStream.close()
                connection.disconnect()
                VoiceDispatchResult(ok = true, statusCode = status)
            } else {
                connection.errorStream?.close()
                connection.disconnect()
                VoiceDispatchResult(ok = false, statusCode = status, error = "http_$status")
            }
        } catch (error: Exception) {
            VoiceDispatchResult(ok = false, error = error.javaClass.simpleName)
        }
    }
}
