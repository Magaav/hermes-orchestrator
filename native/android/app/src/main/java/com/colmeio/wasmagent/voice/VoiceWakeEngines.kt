package com.colmeio.wasmagent.voice

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtException
import ai.onnxruntime.OrtSession
import ai.onnxruntime.TensorInfo
import org.json.JSONObject
import java.io.File
import java.nio.FloatBuffer
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

interface WakeWordEngine {
    val name: String
    val ready: Boolean
    fun processPcm16(samples: ShortArray, sampleRateHz: Int): WakeWordResult
}

interface TranscriptionEngine {
    val name: String
    fun transcribePcm16(samples: ShortArray, sampleRateHz: Int, timeoutMs: Long = 12_000): TranscriptionResult
    fun transcribeLiveAfterWake(timeoutMs: Long = 12_000): TranscriptionResult =
        transcribePcm16(ShortArray(0), 16_000, timeoutMs)
}

data class TranscriptionResult(
    val transcript: String,
    val confidence: Double,
    val error: String = "",
)

class OpenWakeWordOnnxEngine(
    private val modelFile: File,
    private val threshold: Double = DEFAULT_CONFIDENCE_THRESHOLD,
) : WakeWordEngine {
    companion object {
        const val ASSET_MODEL_PATH = "assets/voice/hermes.onnx"
        const val APP_PRIVATE_MODEL_PATH = "files/voice/hermes.onnx"
        const val SAMPLE_RATE_HZ = 16_000
        const val DEFAULT_WINDOW_SAMPLES = 16_000
        const val MIN_WINDOW_SAMPLES = 4_000
        const val MAX_WINDOW_SAMPLES = 32_000
        const val DEFAULT_CONFIDENCE_THRESHOLD = 0.58
        const val INPUT_FORMAT = "pcm16_mono_16khz_normalized_float32"
        const val INPUT_NAME_FALLBACK = "first_input"
        const val OUTPUT_NAME_FALLBACK = "first_output"
    }

    private enum class ModelContract(val diagnostic: String) {
        RAW_PCM("raw_pcm_16khz_mono_float_window"),
        MISSING("model_missing"),
        LOAD_ERROR("model_load_error"),
        UNSUPPORTED_INPUT_SHAPE("unsupported_model_input_shape"),
        UNSUPPORTED_OUTPUT_SHAPE("unsupported_model_output_shape"),
    }

    private val env: OrtEnvironment? by lazy {
        if (!modelFile.exists()) {
            null
        } else {
            try {
                OrtEnvironment.getEnvironment()
            } catch (error: Throwable) {
                lastError = error.javaClass.simpleName
                null
            }
        }
    }
    private val session: OrtSession? by lazy {
        val runtime = env ?: return@lazy null
        try {
            runtime.createSession(modelFile.absolutePath, OrtSession.SessionOptions())
        } catch (error: Throwable) {
            lastError = error.javaClass.simpleName
            null
        }
    }
    private val inputName: String by lazy { session?.inputNames?.firstOrNull().orEmpty() }
    private val inputShape: LongArray by lazy { resolveInputShape(session) }
    private val outputName: String by lazy { session?.outputNames?.firstOrNull().orEmpty() }
    private val outputShape: LongArray by lazy { resolveOutputShape(session) }
    private val modelContract: ModelContract by lazy { resolveModelContract() }
    private val windowSamples: Int by lazy {
        if (modelContract != ModelContract.RAW_PCM) DEFAULT_WINDOW_SAMPLES
        else inputShape.filter { it > 1 }.lastOrNull()?.toInt()?.coerceIn(MIN_WINDOW_SAMPLES, MAX_WINDOW_SAMPLES)
            ?: DEFAULT_WINDOW_SAMPLES
    }
    private val rollingWindow = ArrayDeque<Float>()
    @Volatile private var lastError: String = ""

    override val name: String
        get() = when {
            !modelFile.exists() -> "OpenWakeWordOnnxEngine(model-missing)"
            session == null -> "OpenWakeWordOnnxEngine(load-error${if (lastError.isBlank()) "" else ":$lastError"})"
            modelContract != ModelContract.RAW_PCM -> "OpenWakeWordOnnxEngine(${modelContract.diagnostic})"
            else -> "OpenWakeWordOnnxEngine"
        }
    override val ready: Boolean
        get() = modelContract == ModelContract.RAW_PCM

    val diagnosticReason: String
        get() = when (modelContract) {
            ModelContract.RAW_PCM -> ""
            ModelContract.MISSING -> "hermes_wake_model_missing"
            ModelContract.LOAD_ERROR -> "hermes_wake_model_load_error"
            ModelContract.UNSUPPORTED_INPUT_SHAPE,
            ModelContract.UNSUPPORTED_OUTPUT_SHAPE -> "hermes_wake_model_incompatible"
        }

    val onnxRuntimeAvailable: Boolean
        get() = try {
            OrtEnvironment.getEnvironment()
            true
        } catch (error: Throwable) {
            lastError = error.javaClass.simpleName
            false
        }

    fun diagnostics(): JSONObject = JSONObject()
        .put("wake_model_path", APP_PRIVATE_MODEL_PATH)
        .put("asset_model_path", ASSET_MODEL_PATH)
        .put("wake_model_exists", modelFile.exists())
        .put("onnx_runtime_available", onnxRuntimeAvailable)
        .put("wake_model_contract", modelContract.diagnostic)
        .put("wake_model_input_name", inputName.ifBlank { INPUT_NAME_FALLBACK })
        .put("wake_model_input_shape", inputShape.joinToString(prefix = "[", postfix = "]"))
        .put("wake_model_input_format", INPUT_FORMAT)
        .put("wake_model_sample_rate_hz", SAMPLE_RATE_HZ)
        .put("wake_model_output_name", outputName.ifBlank { OUTPUT_NAME_FALLBACK })
        .put("wake_model_output_shape", outputShape.joinToString(prefix = "[", postfix = "]"))
        .put("wake_model_window_samples", windowSamples)
        .put("wake_model_threshold", threshold)
        .put("wake_model_error", lastError)

    override fun processPcm16(samples: ShortArray, sampleRateHz: Int): WakeWordResult {
        val activeSession = session ?: return WakeWordResult(false, confidence = 0.0)
        val runtime = env ?: return WakeWordResult(false, confidence = 0.0)
        if (!ready) return WakeWordResult(false, confidence = 0.0)
        if (sampleRateHz != SAMPLE_RATE_HZ) {
            lastError = "unsupported_sample_rate_$sampleRateHz"
            return WakeWordResult(false, confidence = 0.0)
        }
        for (sample in samples) {
            rollingWindow.addLast((sample.toFloat() / Short.MAX_VALUE).coerceIn(-1f, 1f))
            while (rollingWindow.size > windowSamples) rollingWindow.removeFirst()
        }
        if (rollingWindow.size < windowSamples) return WakeWordResult(false, confidence = 0.0)
        val input = FloatArray(windowSamples)
        var index = 0
        for (value in rollingWindow) {
            input[index] = value
            index += 1
        }
        return try {
            OnnxTensor.createTensor(runtime, FloatBuffer.wrap(input), inputShape).use { tensor ->
                activeSession.run(mapOf(inputName to tensor)).use { results ->
                    val confidence = firstConfidence(results[0].value)
                    WakeWordResult(detected = confidence >= threshold, confidence = confidence)
                }
            }
        } catch (error: Exception) {
            lastError = error.javaClass.simpleName
            WakeWordResult(false, confidence = 0.0)
        }
    }

    private fun resolveModelContract(): ModelContract {
        if (!modelFile.exists()) return ModelContract.MISSING
        if (session == null || inputName.isBlank() || inputShape.isEmpty()) return ModelContract.LOAD_ERROR
        val concrete = inputShape.filter { it > 1 }
        val window = concrete.lastOrNull() ?: return ModelContract.UNSUPPORTED_INPUT_SHAPE
        val rankSupported = inputShape.size in 1..3
        val hasSingleChannelOrBatch = inputShape.dropLast(1).all { it == 1L }
        if (!rankSupported || !hasSingleChannelOrBatch || window !in MIN_WINDOW_SAMPLES.toLong()..MAX_WINDOW_SAMPLES.toLong()) {
            return ModelContract.UNSUPPORTED_INPUT_SHAPE
        }
        if (outputName.isBlank() || outputShape.isEmpty()) return ModelContract.LOAD_ERROR
        val outputRankSupported = outputShape.size in 0..3
        val outputConcrete = outputShape.filter { it > 1 }
        return if (outputRankSupported && outputConcrete.all { it <= 2L }) {
            ModelContract.RAW_PCM
        } else {
            ModelContract.UNSUPPORTED_OUTPUT_SHAPE
        }
    }

    private fun resolveInputShape(activeSession: OrtSession?): LongArray {
        val info = activeSession?.inputInfo?.values?.firstOrNull()?.info as? TensorInfo ?: return longArrayOf()
        val raw = info.shape
        if (raw.isEmpty()) return longArrayOf()
        val resolved = raw.map { dimension ->
            when {
                dimension == 0L -> 1L
                dimension < 0L -> DEFAULT_WINDOW_SAMPLES.toLong()
                else -> dimension
            }
        }.toLongArray()
        return when (resolved.size) {
            1 -> longArrayOf(1L, resolved[0])
            else -> resolved
        }
    }

    private fun resolveOutputShape(activeSession: OrtSession?): LongArray {
        val info = activeSession?.outputInfo?.values?.firstOrNull()?.info as? TensorInfo ?: return longArrayOf()
        val raw = info.shape
        if (raw.isEmpty()) return longArrayOf(1L)
        return raw.map { dimension ->
            when {
                dimension <= 0L -> 1L
                else -> dimension
            }
        }.toLongArray()
    }

    private fun firstConfidence(value: Any?): Double {
        return when (value) {
            is FloatArray -> value.firstOrNull()?.toDouble() ?: 0.0
            is DoubleArray -> value.firstOrNull() ?: 0.0
            is Array<*> -> value.firstOrNull()?.let { firstConfidence(it) } ?: 0.0
            is Number -> value.toDouble()
            else -> 0.0
        }.coerceIn(0.0, 1.0)
    }
}

class AndroidSpeechRecognizerEngine(private val context: Context) : TranscriptionEngine {
    override val name: String = "AndroidSpeechRecognizerEngine"

    override fun transcribePcm16(samples: ShortArray, sampleRateHz: Int, timeoutMs: Long): TranscriptionResult =
        TranscriptionResult("", 0.0, "android_speech_recognizer_requires_live_capture")

    override fun transcribeLiveAfterWake(timeoutMs: Long): TranscriptionResult {
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            return TranscriptionResult("", 0.0, "android_speech_recognizer_unavailable")
        }
        val latch = CountDownLatch(1)
        var transcript = ""
        var confidence = 0.0
        var error = ""
        var recognizer: SpeechRecognizer? = null
        val main = Handler(Looper.getMainLooper())
        main.post {
            recognizer = SpeechRecognizer.createSpeechRecognizer(context).also { instance ->
                instance.setRecognitionListener(object : RecognitionListener {
                    override fun onReadyForSpeech(params: Bundle?) {}
                    override fun onBeginningOfSpeech() {}
                    override fun onRmsChanged(rmsdB: Float) {}
                    override fun onBufferReceived(buffer: ByteArray?) {}
                    override fun onEndOfSpeech() {}
                    override fun onPartialResults(partialResults: Bundle?) {}
                    override fun onEvent(eventType: Int, params: Bundle?) {}
                    override fun onError(errorCode: Int) {
                        error = "android_speech_error_$errorCode"
                        latch.countDown()
                    }
                    override fun onResults(results: Bundle?) {
                        val matches = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION).orEmpty()
                        val scores = results?.getFloatArray(SpeechRecognizer.CONFIDENCE_SCORES)
                        transcript = matches.firstOrNull().orEmpty()
                        confidence = scores?.firstOrNull()?.toDouble()?.coerceIn(0.0, 1.0) ?: if (transcript.isBlank()) 0.0 else 0.72
                        latch.countDown()
                    }
                })
                val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                    .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    .putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
                    .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false)
                    .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
                instance.startListening(intent)
            }
        }
        latch.await(timeoutMs, TimeUnit.MILLISECONDS)
        main.post {
            try {
                recognizer?.stopListening()
            } catch (_: Exception) {
            }
            recognizer?.destroy()
        }
        if (transcript.isBlank() && error.isBlank()) error = "android_speech_timeout"
        return TranscriptionResult(transcript, confidence, error)
    }
}

class VoskOfflineEngine : TranscriptionEngine {
    override val name: String = "VoskOfflineEngine(optional-not-bundled)"
    override fun transcribePcm16(samples: ShortArray, sampleRateHz: Int, timeoutMs: Long): TranscriptionResult =
        TranscriptionResult("", 0.0, "vosk_engine_not_bundled")
}

class WhisperCppEngine : TranscriptionEngine {
    override val name: String = "WhisperCppEngine(future)"
    override fun transcribePcm16(samples: ShortArray, sampleRateHz: Int, timeoutMs: Long): TranscriptionResult =
        TranscriptionResult("", 0.0, "whisper_cpp_engine_not_bundled")
}
