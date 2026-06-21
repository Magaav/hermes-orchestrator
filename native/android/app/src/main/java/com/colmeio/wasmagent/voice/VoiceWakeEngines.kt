package com.colmeio.wasmagent.voice

import android.content.Context
import android.content.Intent
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
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
import org.json.JSONArray
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
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

interface DiagnosticWakeWordEngine : WakeWordEngine {
    val diagnosticReason: String
    val onnxRuntimeAvailable: Boolean
    val onnxRuntimeError: String
    fun diagnostics(): JSONObject
}

interface TranscriptionEngine {
    val name: String
    fun transcribePcm16(samples: ShortArray, sampleRateHz: Int, timeoutMs: Long = 12_000): TranscriptionResult
    fun transcribeLiveAfterWake(timeoutMs: Long = 12_000, policy: TranscriptionPolicy = TranscriptionPolicy()): TranscriptionResult =
        transcribePcm16(ShortArray(0), 16_000, timeoutMs)
}

data class TranscriptionPolicy(
    val acceptPartialResults: Boolean = true,
    val minimumLengthMs: Long = 900,
    val completeSilenceMs: Long = 1_500,
    val possiblyCompleteSilenceMs: Long = 800,
    val attemptPlan: JSONObject = JSONObject(),
)

data class TranscriptionResult(
    val transcript: String,
    val confidence: Double,
    val error: String = "",
    val engine: String = "",
    val latencyMs: Long = 0,
    val audioCapturedMs: Long = 0,
    val partialTranscript: String = "",
    val diagnostics: JSONObject = JSONObject(),
)

class OpenWakeWordOnnxEngine(
    private val modelFile: File,
    private val threshold: Double = DEFAULT_CONFIDENCE_THRESHOLD,
    private val modelSource: String = "none",
) : DiagnosticWakeWordEngine {
    companion object {
        const val ASSET_BASE_MODEL_PATH = "assets/voice/base_hermes.onnx"
        const val APP_PRIVATE_BASE_MODEL_PATH = "files/voice/base_hermes.onnx"
        const val APP_PRIVATE_PERSONALIZED_MODEL_PATH = "files/voice/hermes.onnx"
        const val ASSET_MODEL_PATH = ASSET_BASE_MODEL_PATH
        const val APP_PRIVATE_MODEL_PATH = APP_PRIVATE_PERSONALIZED_MODEL_PATH
        const val SAMPLE_RATE_HZ = 16_000
        const val DEFAULT_WINDOW_SAMPLES = 16_000
        const val MIN_WINDOW_SAMPLES = 4_000
        const val MAX_WINDOW_SAMPLES = 32_000
        const val DEFAULT_CONFIDENCE_THRESHOLD = 0.92
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
                lastError = describeThrowable(error)
                lastOnnxRuntimeError = lastError
                null
            }
        }
    }
    private val session: OrtSession? by lazy {
        val runtime = env ?: return@lazy null
        try {
            runtime.createSession(modelFile.absolutePath, OrtSession.SessionOptions())
        } catch (error: Throwable) {
            lastError = describeThrowable(error)
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
    @Volatile private var lastOnnxRuntimeError: String = ""
    @Volatile private var lastConfidence: Double = 0.0

    override val name: String
        get() = when {
            !modelFile.exists() -> "OpenWakeWordOnnxEngine(model-missing)"
            session == null -> "OpenWakeWordOnnxEngine(load-error${if (lastError.isBlank()) "" else ":$lastError"})"
            modelContract != ModelContract.RAW_PCM -> "OpenWakeWordOnnxEngine(${modelContract.diagnostic})"
            else -> "OpenWakeWordOnnxEngine"
        }
    override val ready: Boolean
        get() = modelContract == ModelContract.RAW_PCM

    override val diagnosticReason: String
        get() = when (modelContract) {
            ModelContract.RAW_PCM -> ""
            ModelContract.MISSING -> "hermes_wake_model_missing"
            ModelContract.LOAD_ERROR -> "hermes_wake_model_load_error"
            ModelContract.UNSUPPORTED_INPUT_SHAPE,
            ModelContract.UNSUPPORTED_OUTPUT_SHAPE -> "hermes_wake_model_incompatible"
        }

    override val onnxRuntimeAvailable: Boolean
        get() = try {
            OrtEnvironment.getEnvironment()
            lastOnnxRuntimeError = ""
            true
        } catch (error: Throwable) {
            lastOnnxRuntimeError = describeThrowable(error)
            lastError = lastOnnxRuntimeError
            false
        }

    override val onnxRuntimeError: String
        get() {
            onnxRuntimeAvailable
            return lastOnnxRuntimeError
        }

    val wakeEngineError: String
        get() = if (ready) "" else lastError.ifBlank { diagnosticReason }

    override fun diagnostics(): JSONObject = JSONObject()
        .put("model_source", modelSource)
        .put("selected_model_path", relativeModelPath())
        .put("wake_model_path", relativeModelPath())
        .put("asset_model_path", ASSET_BASE_MODEL_PATH)
        .put("base_model_exists", modelSource == "base" && modelFile.exists() && modelFile.length() > 0L)
        .put("personalized_model_exists", modelSource == "personalized" && modelFile.exists() && modelFile.length() > 0L)
        .put("wake_model_exists", modelFile.exists() && modelFile.length() > 0L)
        .put("wake_engine_ready", ready)
        .put("wake_provider", name)
        .put("last_model_load_result", if (ready) "loaded" else modelContract.diagnostic)
        .put("last_model_load_error", if (ready) "" else lastError.ifBlank { diagnosticReason })
        .put("last_wake_confidence", lastConfidence)
        .put("onnx_runtime_available", onnxRuntimeAvailable)
        .put("onnx_runtime_error", onnxRuntimeError)
        .put("wake_engine_error", wakeEngineError)
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
                    lastConfidence = confidence
                    WakeWordResult(detected = confidence >= threshold, confidence = confidence)
                }
            }
        } catch (error: Exception) {
            lastError = error.javaClass.simpleName
            lastConfidence = 0.0
            WakeWordResult(false, confidence = 0.0)
        }
    }

    private fun resolveModelContract(): ModelContract {
        if (!modelFile.exists() || modelFile.length() <= 0L) return ModelContract.MISSING
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

    private fun relativeModelPath(): String =
        modelFile.path.substringAfter("/files/", modelFile.path).let { path ->
            if (path.startsWith("voice/")) "files/$path" else path
        }

    private fun describeThrowable(error: Throwable): String {
        val message = error.message?.takeIf { it.isNotBlank() }
        return if (message == null) error.javaClass.name else "${error.javaClass.name}: $message"
    }
}

class OpenWakeWordBundleEngine(
    private val bundleDir: File,
    private val threshold: Double = DEFAULT_CONFIDENCE_THRESHOLD,
    private val modelSource: String = "openwakeword_bundle",
) : DiagnosticWakeWordEngine {
    companion object {
        const val SAMPLE_RATE_HZ = OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ
        const val DEFAULT_CONFIDENCE_THRESHOLD = 0.5
        const val BUNDLE_DIR = "files/voice/openwakeword"
        const val MEL_MODEL_NAME = "melspectrogram.onnx"
        const val EMBEDDING_MODEL_NAME = "embedding_model.onnx"
        const val CLASSIFIER_MODEL_NAME = "hey_jarvis.onnx"
        private const val PREPARED_SAMPLES = 1_280
        private const val RAW_BUFFER_MAX = SAMPLE_RATE_HZ * 10
        private const val MEL_BUFFER_MAX = 10 * 97
        private const val FEATURE_BUFFER_MAX = 120
        private const val MEL_WINDOW = 76
        private const val MEL_STEP = 8
        private const val FEATURE_FRAMES = 16
        private const val MEL_CONTEXT_SAMPLES = 480
    }

    private enum class BundleContract(val diagnostic: String) {
        OPEN_WAKE_WORD("openwakeword_bundle"),
        MISSING("openwakeword_bundle_missing"),
        LOAD_ERROR("openwakeword_bundle_load_error"),
        INFERENCE_ERROR("openwakeword_bundle_inference_error"),
    }

    private val melFile = File(bundleDir, MEL_MODEL_NAME)
    private val embeddingFile = File(bundleDir, EMBEDDING_MODEL_NAME)
    private val classifierFile = File(bundleDir, CLASSIFIER_MODEL_NAME)
    private val env: OrtEnvironment? by lazy {
        try {
            OrtEnvironment.getEnvironment()
        } catch (error: Throwable) {
            lastError = describeThrowable(error)
            lastOnnxRuntimeError = lastError
            null
        }
    }
    private val melSession: OrtSession? by lazy { createSession(melFile) }
    private val embeddingSession: OrtSession? by lazy { createSession(embeddingFile) }
    private val classifierSession: OrtSession? by lazy { createSession(classifierFile) }
    private val bundleContract: BundleContract by lazy { resolveBundleContract() }
    private val rawData = ArrayDeque<Float>()
    private var accumulatedSamples = 0
    private var melBuffer: Array<FloatArray> = Array(MEL_WINDOW) { FloatArray(32) { 1.0f } }
    private var featureBuffer: Array<FloatArray> = Array(FEATURE_BUFFER_MAX) { FloatArray(96) { 0.0f } }
    @Volatile private var lastError: String = ""
    @Volatile private var lastOnnxRuntimeError: String = ""
    @Volatile private var lastConfidence: Double = 0.0

    override val name: String
        get() = when {
            bundleContract == BundleContract.OPEN_WAKE_WORD -> "OpenWakeWordBundleEngine"
            else -> "OpenWakeWordBundleEngine(${bundleContract.diagnostic}${if (lastError.isBlank()) "" else ":$lastError"})"
        }

    override val ready: Boolean
        get() = bundleContract == BundleContract.OPEN_WAKE_WORD

    override val diagnosticReason: String
        get() = when (bundleContract) {
            BundleContract.OPEN_WAKE_WORD -> ""
            BundleContract.MISSING -> "openwakeword_bundle_missing"
            BundleContract.LOAD_ERROR -> "openwakeword_bundle_load_error"
            BundleContract.INFERENCE_ERROR -> "openwakeword_bundle_inference_error"
        }

    override val onnxRuntimeAvailable: Boolean
        get() = try {
            OrtEnvironment.getEnvironment()
            lastOnnxRuntimeError = ""
            true
        } catch (error: Throwable) {
            lastOnnxRuntimeError = describeThrowable(error)
            lastError = lastOnnxRuntimeError
            false
        }

    override val onnxRuntimeError: String
        get() {
            onnxRuntimeAvailable
            return lastOnnxRuntimeError
        }

    override fun diagnostics(): JSONObject = JSONObject()
        .put("model_source", modelSource)
        .put("selected_model_path", BUNDLE_DIR)
        .put("wake_model_path", BUNDLE_DIR)
        .put("asset_model_path", "assets/voice/openwakeword")
        .put("base_model_exists", false)
        .put("personalized_model_exists", false)
        .put("openwakeword_bundle_exists", bundleFilesExist())
        .put("openwakeword_melspectrogram_exists", validFile(melFile))
        .put("openwakeword_embedding_exists", validFile(embeddingFile))
        .put("openwakeword_classifier_exists", validFile(classifierFile))
        .put("wake_model_exists", bundleFilesExist())
        .put("wake_engine_ready", ready)
        .put("wake_provider", name)
        .put("last_model_load_result", if (ready) "loaded" else bundleContract.diagnostic)
        .put("last_model_load_error", if (ready) "" else lastError.ifBlank { diagnosticReason })
        .put("last_wake_confidence", lastConfidence)
        .put("onnx_runtime_available", onnxRuntimeAvailable)
        .put("onnx_runtime_error", onnxRuntimeError)
        .put("wake_engine_error", if (ready) "" else lastError.ifBlank { diagnosticReason })
        .put("wake_model_contract", bundleContract.diagnostic)
        .put("wake_model_input_format", OpenWakeWordOnnxEngine.INPUT_FORMAT)
        .put("openwakeword_pcm_scale", "pcm16_as_float32")
        .put("wake_model_sample_rate_hz", SAMPLE_RATE_HZ)
        .put("wake_model_threshold", threshold)
        .put("wake_model_error", lastError)
        .put("wake_model_bundle_files", JSONArray()
            .put(MEL_MODEL_NAME)
            .put(EMBEDDING_MODEL_NAME)
            .put(CLASSIFIER_MODEL_NAME))

    override fun processPcm16(samples: ShortArray, sampleRateHz: Int): WakeWordResult {
        if (!ready) return WakeWordResult(false, confidence = 0.0)
        if (sampleRateHz != SAMPLE_RATE_HZ) {
            lastError = "unsupported_sample_rate_$sampleRateHz"
            return WakeWordResult(false, confidence = 0.0)
        }
        val floats = FloatArray(samples.size) { index -> samples[index].toFloat() }
        return try {
            processAudio(floats)
            val features = latestFeatures()
            val confidence = runClassifier(features).toDouble().coerceIn(0.0, 1.0)
            lastConfidence = confidence
            WakeWordResult(detected = confidence >= threshold, confidence = confidence)
        } catch (error: Exception) {
            lastError = describeThrowable(error)
            lastConfidence = 0.0
            WakeWordResult(false, confidence = 0.0)
        }
    }

    private fun createSession(file: File): OrtSession? {
        val runtime = env ?: return null
        if (!validFile(file)) return null
        return try {
            runtime.createSession(file.readBytes(), OrtSession.SessionOptions())
        } catch (error: Throwable) {
            lastError = describeThrowable(error)
            null
        }
    }

    private fun resolveBundleContract(): BundleContract {
        if (!bundleFilesExist()) return BundleContract.MISSING
        if (env == null || melSession == null || embeddingSession == null || classifierSession == null) {
            return BundleContract.LOAD_ERROR
        }
        return try {
            runClassifier(latestFeatures())
            BundleContract.OPEN_WAKE_WORD
        } catch (error: Exception) {
            lastError = describeThrowable(error)
            BundleContract.INFERENCE_ERROR
        }
    }

    private fun processAudio(audio: FloatArray) {
        if (audio.isEmpty()) return
        bufferRawData(audio)
        accumulatedSamples += audio.size
        if (accumulatedSamples < PREPARED_SAMPLES) return
        val chunkCount = accumulatedSamples / PREPARED_SAMPLES
        updateMelBuffer(accumulatedSamples)
        for (chunk in chunkCount - 1 downTo 0) {
            val end = if (chunk == 0) melBuffer.size else melBuffer.size - MEL_STEP * chunk
            val start = maxOf(0, end - MEL_WINDOW)
            val window = Array(1) { Array(MEL_WINDOW) { Array(32) { FloatArray(1) } } }
            for ((row, source) in (start until end).withIndex()) {
                for (column in 0 until 32) window[0][row][column][0] = melBuffer[source][column]
            }
            appendFeatures(runEmbedding(window))
        }
        accumulatedSamples %= PREPARED_SAMPLES
    }

    private fun bufferRawData(data: FloatArray) {
        while (rawData.size + data.size > RAW_BUFFER_MAX) rawData.removeFirst()
        data.forEach { rawData.addLast(it) }
    }

    private fun updateMelBuffer(sampleCount: Int) {
        if (rawData.size < 400) return
        val input = rawData.toList().takeLast(sampleCount + MEL_CONTEXT_SAMPLES).toFloatArray()
        val mel = runMelSpectrogram(input)
        melBuffer = (melBuffer + mel).takeLast(MEL_BUFFER_MAX).toTypedArray()
    }

    private fun runMelSpectrogram(samples: FloatArray): Array<FloatArray> {
        val runtime = env ?: throw IllegalStateException("onnx_runtime_unavailable")
        val session = melSession ?: throw IllegalStateException("melspectrogram_session_missing")
        OnnxTensor.createTensor(runtime, FloatBuffer.wrap(samples), longArrayOf(1L, samples.size.toLong())).use { tensor ->
            session.run(mapOf(session.inputNames.first() to tensor)).use { results ->
                return transformMel(squeezeMel(results[0].value))
            }
        }
    }

    @Suppress("UNCHECKED_CAST")
    private fun squeezeMel(value: Any?): Array<FloatArray> {
        val raw = value as? Array<Array<Array<FloatArray>>>
            ?: throw IllegalStateException("unexpected_melspectrogram_output")
        return Array(raw[0][0].size) { row -> raw[0][0][row].copyOf() }
    }

    private fun transformMel(input: Array<FloatArray>): Array<FloatArray> =
        Array(input.size) { row -> FloatArray(input[row].size) { col -> input[row][col] / 10.0f + 2.0f } }

    private fun runEmbedding(input: Array<Array<Array<FloatArray>>>): Array<FloatArray> {
        val runtime = env ?: throw IllegalStateException("onnx_runtime_unavailable")
        val session = embeddingSession ?: throw IllegalStateException("embedding_session_missing")
        OnnxTensor.createTensor(runtime, input).use { tensor ->
            session.run(mapOf(session.inputNames.first() to tensor)).use { results ->
                return squeezeEmbedding(results[0].value)
            }
        }
    }

    @Suppress("UNCHECKED_CAST")
    private fun squeezeEmbedding(value: Any?): Array<FloatArray> {
        val raw = value as? Array<Array<Array<FloatArray>>>
            ?: throw IllegalStateException("unexpected_embedding_output")
        return Array(raw.size) { row -> raw[row][0][0].copyOf() }
    }

    private fun appendFeatures(newFeatures: Array<FloatArray>) {
        featureBuffer = (featureBuffer + newFeatures).takeLast(FEATURE_BUFFER_MAX).toTypedArray()
    }

    private fun latestFeatures(): Array<Array<FloatArray>> =
        arrayOf(featureBuffer.takeLast(FEATURE_FRAMES).toTypedArray())

    private fun runClassifier(features: Array<Array<FloatArray>>): Float {
        val runtime = env ?: throw IllegalStateException("onnx_runtime_unavailable")
        val session = classifierSession ?: throw IllegalStateException("classifier_session_missing")
        OnnxTensor.createTensor(runtime, features).use { tensor ->
            session.run(mapOf(session.inputNames.first() to tensor)).use { results ->
                return firstFloat(results[0].value)
            }
        }
    }

    private fun firstFloat(value: Any?): Float = when (value) {
        is FloatArray -> value.firstOrNull() ?: 0.0f
        is DoubleArray -> value.firstOrNull()?.toFloat() ?: 0.0f
        is Array<*> -> value.firstOrNull()?.let { firstFloat(it) } ?: 0.0f
        is Number -> value.toFloat()
        else -> 0.0f
    }

    private fun bundleFilesExist(): Boolean = validFile(melFile) && validFile(embeddingFile) && validFile(classifierFile)

    private fun validFile(file: File): Boolean = file.exists() && file.isFile && file.length() > 0L

    private fun describeThrowable(error: Throwable): String {
        val message = error.message?.takeIf { it.isNotBlank() }
        return if (message == null) error.javaClass.name else "${error.javaClass.name}: $message"
    }
}

data class WakeModelCandidate(
    val source: String,
    val file: File,
)

data class WakeModelSelection(
    val source: String,
    val engine: DiagnosticWakeWordEngine,
    val personalizedModelExists: Boolean,
    val baseModelExists: Boolean,
    val openWakeWordBundleExists: Boolean = false,
    val attempted: List<DiagnosticWakeWordEngine>,
) {
    val ready: Boolean get() = engine.ready
}

object WakeModelSelector {
    const val PERSONALIZED_SOURCE = "personalized"
    const val BASE_SOURCE = "base"
    const val OPENWAKEWORD_SOURCE = "openwakeword_bundle"
    const val NONE_SOURCE = "none"

    fun select(
        personalizedModelFile: File,
        baseModelFile: File,
        threshold: Double = OpenWakeWordOnnxEngine.DEFAULT_CONFIDENCE_THRESHOLD,
    ): WakeModelSelection {
        val personalizedExists = validFile(personalizedModelFile)
        val baseExists = validFile(baseModelFile)
        val openWakeWordBundleDir = File(personalizedModelFile.parentFile ?: baseModelFile.parentFile ?: File("."), "openwakeword")
        val openWakeWordBundle = OpenWakeWordBundleEngine(openWakeWordBundleDir, threshold = threshold)
        val openWakeWordBundleExists = openWakeWordBundle.diagnostics().optBoolean("openwakeword_bundle_exists", false)
        val attempted = mutableListOf<DiagnosticWakeWordEngine>()
        if (openWakeWordBundleExists) {
            attempted.add(openWakeWordBundle)
            if (openWakeWordBundle.ready) {
                return WakeModelSelection(OPENWAKEWORD_SOURCE, openWakeWordBundle, personalizedExists, baseExists, openWakeWordBundleExists, attempted)
            }
        }
        if (personalizedExists) {
            val engine = OpenWakeWordOnnxEngine(personalizedModelFile, threshold = threshold, modelSource = PERSONALIZED_SOURCE)
            attempted.add(engine)
            if (engine.ready) return WakeModelSelection(PERSONALIZED_SOURCE, engine, personalizedExists, baseExists, openWakeWordBundleExists, attempted)
        }
        if (baseExists) {
            val engine = OpenWakeWordOnnxEngine(baseModelFile, threshold = threshold, modelSource = BASE_SOURCE)
            attempted.add(engine)
            if (engine.ready) return WakeModelSelection(BASE_SOURCE, engine, personalizedExists, baseExists, openWakeWordBundleExists, attempted)
        }
        val engine = OpenWakeWordOnnxEngine(personalizedModelFile, threshold = threshold, modelSource = NONE_SOURCE)
        return WakeModelSelection(NONE_SOURCE, engine, personalizedExists, baseExists, openWakeWordBundleExists, attempted + engine)
    }

    private fun validFile(file: File): Boolean = file.exists() && file.isFile && file.length() > 0L
}

class AndroidSpeechRecognizerEngine(private val context: Context) : TranscriptionEngine {
    override val name: String = "AndroidSpeechRecognizerEngine"

    override fun transcribePcm16(samples: ShortArray, sampleRateHz: Int, timeoutMs: Long): TranscriptionResult =
        TranscriptionResult("", 0.0, "android_speech_recognizer_requires_live_capture", engine = name)

    override fun transcribeLiveAfterWake(timeoutMs: Long, policy: TranscriptionPolicy): TranscriptionResult {
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            return TranscriptionResult(
                "",
                0.0,
                "android_speech_recognizer_unavailable",
                engine = name,
                diagnostics = androidSpeechDiagnostics(
                    language = Locale.US,
                    languageTag = Locale.US.toLanguageTag(),
                    timeoutMs = timeoutMs,
                    policy = policy,
                    recognitionAvailable = false,
                ),
            )
        }
        val startedAt = System.currentTimeMillis()
        val attempts = JSONArray()
        val languages = androidSpeechLanguageAttempts(policy)
        var best = SpeechAttemptResult(languageTag = languages.firstOrNull())
        for (languageTag in languages) {
            val remainingMs = timeoutMs - (System.currentTimeMillis() - startedAt)
            if (remainingMs < 1_500L) break
            val attempt = runSpeechAttempt(languageTag, remainingMs.coerceAtMost(8_000L), policy)
            attempts.put(attempt.diagnostics)
            if (attempt.transcript.isNotBlank()) {
                val latency = System.currentTimeMillis() - startedAt
                return TranscriptionResult(
                    transcript = attempt.transcript,
                    confidence = attempt.confidence,
                    error = "",
                    engine = name,
                    latencyMs = latency,
                    partialTranscript = attempt.partialTranscript,
                    diagnostics = attempt.diagnostics
                        .put("latency_ms", latency)
                        .put("attempts", attempts)
                        .put("selected_language", attempt.languageTag ?: "default"),
                )
            }
            if (attempt.score > best.score) best = attempt
            if (!attempt.retryable) break
        }
        val latency = System.currentTimeMillis() - startedAt
        val error = best.error.ifBlank { "android_speech_timeout" }
        return TranscriptionResult(
            transcript = "",
            confidence = 0.0,
            error = error,
            engine = name,
            latencyMs = latency,
            partialTranscript = best.partialTranscript,
            diagnostics = best.diagnostics
                .put("latency_ms", latency)
                .put("attempts", attempts)
                .put("selected_language", best.languageTag ?: "default")
                .put("error", error),
        )
    }

    private data class SpeechAttemptResult(
        val languageTag: String? = null,
        val transcript: String = "",
        val partialTranscript: String = "",
        val confidence: Double = 0.0,
        val error: String = "",
        val errorCode: Int = 0,
        val retryable: Boolean = true,
        val diagnostics: JSONObject = JSONObject(),
    ) {
        val score: Int
            get() = when {
                transcript.isNotBlank() -> 100
                partialTranscript.isNotBlank() -> 80
                errorCode == SpeechRecognizer.ERROR_NO_MATCH -> 30
                errorCode == SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> 20
                error.isNotBlank() -> 10
                else -> 0
            }
    }

    private fun runSpeechAttempt(languageTag: String?, timeoutMs: Long, policy: TranscriptionPolicy): SpeechAttemptResult {
        val attemptStartedAt = System.currentTimeMillis()
        val latch = CountDownLatch(1)
        var transcript = ""
        var partialTranscript = ""
        var confidence = 0.0
        var error = ""
        var errorCode = 0
        var readyForSpeech = false
        var beginningOfSpeech = false
        var endOfSpeech = false
        var readyAtMs = 0L
        var beginningAtMs = 0L
        var endAtMs = 0L
        var errorAtMs = 0L
        var partialCount = 0
        var resultCount = 0
        var rmsEventCount = 0
        var maxRmsDb = Float.NEGATIVE_INFINITY
        var bufferBytes = 0
        var recognizer: SpeechRecognizer? = null
        val main = Handler(Looper.getMainLooper())
        main.post {
            recognizer = SpeechRecognizer.createSpeechRecognizer(context).also { instance ->
                instance.setRecognitionListener(object : RecognitionListener {
                    override fun onReadyForSpeech(params: Bundle?) {
                        readyForSpeech = true
                        readyAtMs = System.currentTimeMillis() - attemptStartedAt
                    }
                    override fun onBeginningOfSpeech() {
                        beginningOfSpeech = true
                        beginningAtMs = System.currentTimeMillis() - attemptStartedAt
                    }
                    override fun onRmsChanged(rmsdB: Float) {
                        rmsEventCount += 1
                        if (rmsdB > maxRmsDb) maxRmsDb = rmsdB
                    }
                    override fun onBufferReceived(buffer: ByteArray?) {
                        bufferBytes += buffer?.size ?: 0
                    }
                    override fun onEndOfSpeech() {
                        endOfSpeech = true
                        endAtMs = System.currentTimeMillis() - attemptStartedAt
                    }
                    override fun onPartialResults(partialResults: Bundle?) {
                        partialTranscript = partialResults
                            ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                            ?.firstOrNull()
                            .orEmpty()
                        partialCount += 1
                    }
                    override fun onEvent(eventType: Int, params: Bundle?) {}
                    override fun onError(code: Int) {
                        errorAtMs = System.currentTimeMillis() - attemptStartedAt
                        errorCode = code
                        error = "android_speech_error_$code"
                        latch.countDown()
                    }
                    override fun onResults(results: Bundle?) {
                        val matches = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION).orEmpty()
                        val scores = results?.getFloatArray(SpeechRecognizer.CONFIDENCE_SCORES)
                        transcript = matches.firstOrNull().orEmpty()
                        confidence = scores?.firstOrNull()?.toDouble()?.coerceIn(0.0, 1.0) ?: if (transcript.isBlank()) 0.0 else 0.72
                        resultCount = matches.size
                        latch.countDown()
                    }
                })
                val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                    .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, policy.acceptPartialResults)
                    .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
                    .putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS, policy.minimumLengthMs)
                    .putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, policy.completeSilenceMs)
                    .putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, policy.possiblyCompleteSilenceMs)
                    .putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, context.packageName)
                if (!languageTag.isNullOrBlank()) {
                    intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, languageTag)
                    intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, languageTag)
                }
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
        if (policy.acceptPartialResults && transcript.isBlank() && partialTranscript.isNotBlank()) {
            transcript = partialTranscript
            confidence = 0.55
            error = ""
        }
        if (transcript.isBlank() && error.isBlank()) error = "android_speech_timeout"
        val retryable = transcript.isBlank() && errorCode in setOf(
            0,
            SpeechRecognizer.ERROR_NO_MATCH,
            SpeechRecognizer.ERROR_SPEECH_TIMEOUT,
            SpeechRecognizer.ERROR_CLIENT,
        )
        return SpeechAttemptResult(
            languageTag = languageTag,
            transcript = transcript,
            partialTranscript = partialTranscript,
            confidence = confidence,
            error = error,
            errorCode = errorCode,
            retryable = retryable,
            diagnostics = androidSpeechDiagnostics(
                language = languageTag?.let { Locale.forLanguageTag(it) } ?: Locale.ROOT,
                languageTag = languageTag ?: "default",
                timeoutMs = timeoutMs,
                policy = policy,
                recognitionAvailable = true,
                readyForSpeech = readyForSpeech,
                beginningOfSpeech = beginningOfSpeech,
                endOfSpeech = endOfSpeech,
                readyAtMs = readyAtMs,
                beginningAtMs = beginningAtMs,
                endAtMs = endAtMs,
                errorCode = errorCode,
                error = error,
                errorAtMs = errorAtMs,
                partialCount = partialCount,
                resultCount = resultCount,
                rmsEventCount = rmsEventCount,
                maxRmsDb = maxRmsDb,
                bufferBytes = bufferBytes,
                latencyMs = System.currentTimeMillis() - attemptStartedAt,
                partialTranscript = partialTranscript,
            ),
        )
    }

    private fun androidSpeechLanguageAttempts(policy: TranscriptionPolicy): List<String?> {
        val attempts = ArrayList<String?>()
        fun add(tag: String?) {
            val clean = tag?.trim().orEmpty()
            if (clean.isBlank()) {
                if (!attempts.contains(null)) attempts.add(null)
                return
            }
            if (attempts.none { it.equals(clean, ignoreCase = true) }) attempts.add(clean)
        }
        val configured = policy.attemptPlan.optJSONArray("androidSpeechLanguages")
            ?: policy.attemptPlan.optJSONArray("android_speech_languages")
        if (configured != null) {
            for (index in 0 until configured.length()) {
                val raw = configured.opt(index)
                if (raw == JSONObject.NULL) add(null) else add(raw?.toString())
            }
        }
        if (attempts.isEmpty()) {
            add(Locale.US.toLanguageTag())
            add(Locale.getDefault().toLanguageTag())
            val defaultLanguage = Locale.getDefault().language
            if (defaultLanguage.isNotBlank()) add(defaultLanguage)
            add(null)
        }
        return attempts
    }

    private fun androidSpeechDiagnostics(
        language: Locale,
        languageTag: String = language.toLanguageTag(),
        timeoutMs: Long,
        policy: TranscriptionPolicy,
        recognitionAvailable: Boolean,
        readyForSpeech: Boolean = false,
        beginningOfSpeech: Boolean = false,
        endOfSpeech: Boolean = false,
        readyAtMs: Long = 0,
        beginningAtMs: Long = 0,
        endAtMs: Long = 0,
        errorCode: Int = 0,
        error: String = "",
        errorAtMs: Long = 0,
        partialCount: Int = 0,
        resultCount: Int = 0,
        rmsEventCount: Int = 0,
        maxRmsDb: Float = Float.NEGATIVE_INFINITY,
        bufferBytes: Int = 0,
        latencyMs: Long = 0,
        partialTranscript: String = "",
    ): JSONObject = JSONObject()
        .put("schema", "hermes.wasm_agent.android_speech_recognizer_debug.v1")
        .put("recognition_available", recognitionAvailable)
        .put("language", languageTag)
        .put("device_locale", Locale.getDefault().toLanguageTag())
        .put("language_model", RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        .put("timeout_ms", timeoutMs)
        .put("accept_partial_results", policy.acceptPartialResults)
        .put("minimum_length_ms", policy.minimumLengthMs)
        .put("complete_silence_ms", policy.completeSilenceMs)
        .put("possibly_complete_silence_ms", policy.possiblyCompleteSilenceMs)
        .put("ready_for_speech", readyForSpeech)
        .put("beginning_of_speech", beginningOfSpeech)
        .put("end_of_speech", endOfSpeech)
        .put("ready_at_ms", readyAtMs)
        .put("beginning_at_ms", beginningAtMs)
        .put("end_at_ms", endAtMs)
        .put("error_code", errorCode)
        .put("error_name", androidSpeechErrorName(errorCode))
        .put("error", error)
        .put("error_at_ms", errorAtMs)
        .put("partial_count", partialCount)
        .put("result_count", resultCount)
        .put("rms_event_count", rmsEventCount)
        .put("max_rms_db", if (maxRmsDb == Float.NEGATIVE_INFINITY) JSONObject.NULL else maxRmsDb)
        .put("buffer_bytes", bufferBytes)
        .put("latency_ms", latencyMs)
        .put("partial_transcript", partialTranscript.take(160))

    private fun androidSpeechErrorName(errorCode: Int): String = when (errorCode) {
        SpeechRecognizer.ERROR_AUDIO -> "ERROR_AUDIO"
        SpeechRecognizer.ERROR_CLIENT -> "ERROR_CLIENT"
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "ERROR_INSUFFICIENT_PERMISSIONS"
        SpeechRecognizer.ERROR_NETWORK -> "ERROR_NETWORK"
        SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "ERROR_NETWORK_TIMEOUT"
        SpeechRecognizer.ERROR_NO_MATCH -> "ERROR_NO_MATCH"
        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "ERROR_RECOGNIZER_BUSY"
        SpeechRecognizer.ERROR_SERVER -> "ERROR_SERVER"
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "ERROR_SPEECH_TIMEOUT"
        0 -> ""
        else -> "ERROR_$errorCode"
    }
}

class LocalCommandTranscriptionEngine(
    private val context: Context,
    private val fallback: TranscriptionEngine = AndroidSpeechRecognizerEngine(context),
    private val preferredEngine: String = PREF_ENGINE_VOSK,
) : TranscriptionEngine {
    companion object {
        const val PREF_ENGINE_ANDROID = "android_speech"
        const val PREF_ENGINE_VOSK = "vosk"
        const val PREF_ENGINE_AUTO = "auto"
        const val SAMPLE_RATE_HZ = 16_000
        const val MODEL_PATH = "asr/vosk-model"
        const val ASSET_MODEL_PATH = "asr/vosk-model"
        private const val COMMAND_GRAMMAR = "[\"open wake word\", \"wake word\", \"open\", \"start listener\", \"stop listener\", \"[unk]\"]"
    }

    private val vosk by lazy { VoskOfflineEngine(File(context.filesDir, MODEL_PATH), COMMAND_GRAMMAR) }

    override val name: String
        get() = when (preferredEngine) {
            PREF_ENGINE_ANDROID -> fallback.name
            PREF_ENGINE_AUTO -> "LocalCommandTranscriptionEngine(auto:${if (vosk.ready) vosk.name else fallback.name})"
            else -> "LocalCommandTranscriptionEngine(${vosk.name})"
        }

    fun diagnostics(): JSONObject = JSONObject()
        .put("local_asr_engine", name)
        .put("local_asr_preferred_engine", preferredEngine)
        .put("local_asr_vosk_ready", vosk.ready)
        .put("local_asr_vosk_model_path", "files/$MODEL_PATH")
        .put("local_asr_vosk_asset_path", "assets/$ASSET_MODEL_PATH")
        .put("local_asr_vosk_error", vosk.lastError)
        .put("local_asr_fallback_engine", fallback.name)

    override fun transcribePcm16(samples: ShortArray, sampleRateHz: Int, timeoutMs: Long): TranscriptionResult {
        if (preferredEngine != PREF_ENGINE_ANDROID && vosk.ready) {
            return vosk.transcribePcm16(samples, sampleRateHz, timeoutMs)
        }
        return fallback.transcribePcm16(samples, sampleRateHz, timeoutMs)
    }

    override fun transcribeLiveAfterWake(timeoutMs: Long, policy: TranscriptionPolicy): TranscriptionResult {
        val planned = transcribeFromAttemptPlan(timeoutMs, policy)
        if (planned != null) return planned
        if (preferredEngine == PREF_ENGINE_ANDROID) return fallback.transcribeLiveAfterWake(timeoutMs, policy)
        if (!vosk.ready) {
            if (preferredEngine == PREF_ENGINE_AUTO) return fallback.transcribeLiveAfterWake(timeoutMs, policy)
            return TranscriptionResult("", 0.0, vosk.lastError.ifBlank { "vosk_model_missing" }, engine = name)
        }
        val startedAt = System.currentTimeMillis()
        val capture = captureCommandPcm(timeoutMs, policy)
        if (capture.error.isNotBlank()) {
            return TranscriptionResult(
                transcript = "",
                confidence = 0.0,
                error = capture.error,
                engine = name,
                latencyMs = 0,
                audioCapturedMs = capture.durationMs,
                diagnostics = JSONObject()
                    .put("schema", "hermes.wasm_agent.local_command_capture_debug.v1")
                    .put("capture_error", capture.error)
                    .put("audio_captured_ms", capture.durationMs)
                    .put("sample_count", capture.samples.size)
                    .put("peak", capture.peak)
                    .put("rms", capture.rms),
            )
        }
        val result = vosk.transcribePcm16(capture.samples, SAMPLE_RATE_HZ, timeoutMs, policy.attemptPlan)
        return result.copy(
            engine = name,
            latencyMs = System.currentTimeMillis() - startedAt,
            audioCapturedMs = capture.durationMs,
            diagnostics = result.diagnostics
                .put("capture_audio_ms", capture.durationMs)
                .put("capture_sample_count", capture.samples.size)
                .put("capture_peak", capture.peak)
                .put("capture_rms", capture.rms),
        )
    }

    private fun transcribeFromAttemptPlan(timeoutMs: Long, policy: TranscriptionPolicy): TranscriptionResult? {
        val attempts = policy.attemptPlan.optJSONArray("attempts") ?: return null
        if (attempts.length() <= 0) return null
        val startedAt = System.currentTimeMillis()
        val diagnostics = JSONArray()
        var best = TranscriptionResult("", 0.0, "transcript_plan_empty", engine = name)
        var captured: PcmCapture? = null
        for (index in 0 until attempts.length()) {
            val attempt = attempts.optJSONObject(index) ?: continue
            val engine = attempt.optString("engine", attempt.optString("type", "")).trim()
            val remaining = timeoutMs - (System.currentTimeMillis() - startedAt)
            if (remaining < 1_000L) break
            val result = when (engine) {
                PREF_ENGINE_ANDROID, "speech", "android" -> {
                    val language = attempt.optString("language", attempt.optString("languageTag", "")).trim()
                    val speechPlan = JSONObject()
                    if (language.isNotBlank()) speechPlan.put("androidSpeechLanguages", JSONArray().put(language))
                    fallback.transcribeLiveAfterWake(remaining.coerceAtMost(8_000L), policy.copy(attemptPlan = speechPlan))
                }
                PREF_ENGINE_VOSK, "local_vosk" -> {
                    if (!vosk.ready) TranscriptionResult("", 0.0, vosk.lastError.ifBlank { "vosk_model_missing" }, engine = name)
                    else {
                        val capture = captured ?: captureCommandPcm(remaining, policy).also { captured = it }
                        if (capture.error.isNotBlank()) {
                            TranscriptionResult("", 0.0, capture.error, engine = name, audioCapturedMs = capture.durationMs)
                        } else {
                            val voskResult = vosk.transcribePcm16(capture.samples, SAMPLE_RATE_HZ, remaining, JSONObject().put("attempts", JSONArray().put(attempt)))
                            voskResult.copy(
                                audioCapturedMs = capture.durationMs,
                                diagnostics = JSONObject()
                                    .put("schema", "hermes.wasm_agent.transcript_plan_attempt.v1")
                                    .put("attempt", attempt)
                                    .put("asr_diagnostics", voskResult.diagnostics)
                                    .put("capture_audio_ms", capture.durationMs)
                                    .put("capture_sample_count", capture.samples.size)
                                    .put("capture_peak", capture.peak)
                                    .put("capture_rms", capture.rms),
                            )
                        }
                    }
                }
                else -> TranscriptionResult("", 0.0, "unsupported_transcript_plan_engine:$engine", engine = name)
            }
            diagnostics.put(JSONObject()
                .put("attempt", attempt)
                .put("engine", result.engine)
                .put("transcript", result.transcript.take(160))
                .put("partial", result.partialTranscript.take(160))
                .put("error", result.error)
                .put("diagnostics", result.diagnostics))
            if (result.transcript.isNotBlank()) {
                val latency = System.currentTimeMillis() - startedAt
                return result.copy(
                    engine = name,
                    latencyMs = latency,
                    diagnostics = JSONObject()
                        .put("schema", "hermes.wasm_agent.transcript_plan_debug.v1")
                        .put("selected_attempt", index)
                        .put("attempts", diagnostics)
                        .put("latency_ms", latency),
                )
            }
            if (transcriptionScore(result) > transcriptionScore(best)) best = result
        }
        val latency = System.currentTimeMillis() - startedAt
        return best.copy(
            engine = name,
            latencyMs = latency,
            diagnostics = JSONObject()
                .put("schema", "hermes.wasm_agent.transcript_plan_debug.v1")
                .put("selected_attempt", -1)
                .put("attempts", diagnostics)
                .put("latency_ms", latency),
        )
    }

    private fun transcriptionScore(result: TranscriptionResult): Int = when {
        result.transcript.isNotBlank() -> 100
        result.partialTranscript.isNotBlank() -> 80
        result.error.isBlank() -> 20
        else -> 0
    }

    private data class PcmCapture(
        val samples: ShortArray,
        val durationMs: Long,
        val error: String = "",
        val peak: Int = 0,
        val rms: Double = 0.0,
    )

    private fun captureCommandPcm(timeoutMs: Long, policy: TranscriptionPolicy): PcmCapture {
        val captureMs = timeoutMs.coerceIn(1_500L, 8_000L)
        val minBuffer = AudioRecord.getMinBufferSize(
            SAMPLE_RATE_HZ,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        if (minBuffer <= 0) return PcmCapture(ShortArray(0), 0, "local_asr_audio_min_buffer_$minBuffer")
        val readBuffer = ShortArray(maxOf(minBuffer / 2, SAMPLE_RATE_HZ / 10))
        val captured = ArrayList<Short>((SAMPLE_RATE_HZ * captureMs / 1000L).toInt())
        var recorder: AudioRecord? = null
        return try {
            recorder = AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION,
                SAMPLE_RATE_HZ,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                maxOf(minBuffer * 2, readBuffer.size * 2),
            )
            if (recorder.state != AudioRecord.STATE_INITIALIZED) {
                return PcmCapture(ShortArray(0), 0, "local_asr_audio_state_${recorder.state}")
            }
            recorder.startRecording()
            if (recorder.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
                return PcmCapture(ShortArray(0), 0, "local_asr_audio_start_failed_${recorder.recordingState}")
            }
            val startedAt = System.currentTimeMillis()
            var lastLoudAt = startedAt
            var maxPeak = 0
            var energy = 0.0
            var energySamples = 0L
            var readErrors = 0
            while (System.currentTimeMillis() - startedAt < captureMs) {
                if (Thread.currentThread().isInterrupted) {
                    return PcmCapture(ShortArray(0), System.currentTimeMillis() - startedAt, "local_asr_audio_interrupted", peak = maxPeak)
                }
                val read = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.M) {
                    recorder.read(readBuffer, 0, readBuffer.size, AudioRecord.READ_NON_BLOCKING)
                } else {
                    recorder.read(readBuffer, 0, readBuffer.size)
                }
                if (read <= 0) {
                    readErrors += 1
                    if (readErrors > 250 && captured.isEmpty()) {
                        return PcmCapture(ShortArray(0), System.currentTimeMillis() - startedAt, "local_asr_audio_no_samples_$read")
                    }
                    Thread.sleep(20)
                    continue
                }
                var peak = 0
                for (index in 0 until read) {
                    val sample = readBuffer[index]
                    captured.add(sample)
                    val absolute = kotlin.math.abs(sample.toInt())
                    peak = maxOf(peak, absolute)
                    energy += sample.toDouble() * sample.toDouble()
                    energySamples += 1
                }
                maxPeak = maxOf(maxPeak, peak)
                if (peak > 250) lastLoudAt = System.currentTimeMillis()
                val elapsed = System.currentTimeMillis() - startedAt
                if (elapsed >= policy.minimumLengthMs && System.currentTimeMillis() - lastLoudAt >= policy.completeSilenceMs) break
            }
            val samples = ShortArray(captured.size)
            for (index in captured.indices) samples[index] = captured[index]
            val rms = if (energySamples <= 0L) 0.0 else kotlin.math.sqrt(energy / energySamples.toDouble())
            if (samples.isEmpty()) return PcmCapture(samples, System.currentTimeMillis() - startedAt, "local_asr_audio_empty", peak = maxPeak, rms = rms)
            PcmCapture(samples, System.currentTimeMillis() - startedAt, peak = maxPeak, rms = rms)
        } catch (error: Throwable) {
            PcmCapture(ShortArray(0), 0, "local_asr_audio_${error.javaClass.simpleName}")
        } finally {
            try { recorder?.stop() } catch (_: Throwable) {}
            recorder?.release()
        }
    }
}

class VoskOfflineEngine(
    private val modelDir: File,
    private val grammar: String = "",
) : TranscriptionEngine {
    companion object {
        private const val MAX_DIAGNOSTIC_RESULTS = 8
    }

    override val name: String = "VoskOfflineEngine"
    @Volatile var lastError: String = ""
        private set
    val ready: Boolean
        get() = modelDir.exists() && modelDir.isDirectory && modelDir.list()?.isNotEmpty() == true

    private val model: Model? by lazy {
        if (!ready) {
            lastError = "vosk_model_missing"
            null
        } else {
            try {
                Model(modelDir.absolutePath).also { lastError = "" }
            } catch (error: Throwable) {
                lastError = "vosk_model_load_${error.javaClass.simpleName}"
                null
            }
        }
    }

    override fun transcribePcm16(samples: ShortArray, sampleRateHz: Int, timeoutMs: Long): TranscriptionResult {
        return transcribePcm16(samples, sampleRateHz, timeoutMs, JSONObject())
    }

    fun transcribePcm16(samples: ShortArray, sampleRateHz: Int, timeoutMs: Long, attemptPlan: JSONObject): TranscriptionResult {
        val startedAt = System.currentTimeMillis()
        if (samples.isEmpty()) return TranscriptionResult("", 0.0, "vosk_audio_empty", engine = name)
        if (sampleRateHz != LocalCommandTranscriptionEngine.SAMPLE_RATE_HZ) {
            return TranscriptionResult("", 0.0, "vosk_unsupported_sample_rate_$sampleRateHz", engine = name)
        }
        val activeModel = model ?: return TranscriptionResult("", 0.0, lastError.ifBlank { "vosk_model_missing" }, engine = name)
        val attempts = JSONArray()
        val configuredAttempts = attemptPlan.optJSONArray("attempts")
        if (configuredAttempts != null && configuredAttempts.length() > 0) {
            var best: TranscriptionResult? = null
            for (index in 0 until configuredAttempts.length()) {
                val item = configuredAttempts.optJSONObject(index) ?: continue
                val itemEngine = item.optString("engine", item.optString("type", "vosk"))
                if (itemEngine !in setOf("vosk", "local_vosk")) continue
                val mode = item.optString("mode", if (item.optBoolean("free", false)) "free" else "grammar")
                val itemGrammar = when {
                    mode == "free" -> ""
                    item.has("grammar") -> grammarFromJson(item.opt("grammar"))
                    else -> grammar
                }
                val result = runVoskAttempt(activeModel, samples, sampleRateHz, itemGrammar, mode)
                attempts.put(result.diagnostics)
                if (result.transcript.isNotBlank()) {
                    val latency = System.currentTimeMillis() - startedAt
                    return result.copy(
                        engine = name,
                        latencyMs = latency,
                        diagnostics = result.diagnostics
                            .put("attempts", attempts)
                            .put("selected_mode", mode)
                            .put("latency_ms", latency),
                    )
                }
                if (best == null || result.score > best.score) best = result
            }
            best?.let { selected ->
                val latency = System.currentTimeMillis() - startedAt
                return selected.copy(
                    engine = name,
                    latencyMs = latency,
                    diagnostics = selected.diagnostics
                        .put("attempts", attempts)
                        .put("selected_mode", selected.diagnostics.optString("mode", ""))
                        .put("latency_ms", latency),
                )
            }
        }
        val grammarResult = runVoskAttempt(activeModel, samples, sampleRateHz, grammar, "grammar")
        attempts.put(grammarResult.diagnostics)
        val selected = if (grammarResult.transcript.isNotBlank() || grammar.isBlank()) {
            grammarResult
        } else {
            val freeResult = runVoskAttempt(activeModel, samples, sampleRateHz, "", "free")
            attempts.put(freeResult.diagnostics)
            if (freeResult.transcript.isNotBlank() || freeResult.score > grammarResult.score) freeResult else grammarResult
        }
        val latency = System.currentTimeMillis() - startedAt
        return selected.copy(
            engine = name,
            latencyMs = latency,
            diagnostics = selected.diagnostics
                .put("attempts", attempts)
                .put("selected_mode", selected.diagnostics.optString("mode", ""))
                .put("latency_ms", latency),
        )
    }

    private fun grammarFromJson(raw: Any?): String {
        return when (raw) {
            is JSONArray -> raw.toString()
            is String -> raw.trim()
            else -> grammar
        }
    }

    private fun runVoskAttempt(
        activeModel: Model,
        samples: ShortArray,
        sampleRateHz: Int,
        activeGrammar: String,
        mode: String,
    ): TranscriptionResult {
        val attemptStartedAt = System.currentTimeMillis()
        return try {
            val partials = JSONArray()
            val results = JSONArray()
            var bestPartial = ""
            var bestText = ""
            var partialCount = 0
            var resultCount = 0
            val activeRecognizer = if (activeGrammar.isBlank()) {
                Recognizer(activeModel, sampleRateHz.toFloat())
            } else {
                Recognizer(activeModel, sampleRateHz.toFloat(), activeGrammar)
            }
            activeRecognizer.use { recognizer ->
                var offset = 0
                val chunkSize = LocalCommandTranscriptionEngine.SAMPLE_RATE_HZ / 4
                while (offset < samples.size) {
                    val count = minOf(chunkSize, samples.size - offset)
                    val chunk = samples.copyOfRange(offset, offset + count)
                    if (recognizer.acceptWaveForm(chunk, chunk.size)) {
                        val resultJson = JSONObject(recognizer.result ?: "{}")
                        val text = resultJson.optString("text", "").trim()
                        if (text.isNotBlank()) bestText = text
                        putBounded(results, resultJson)
                        resultCount += 1
                    } else {
                        val partialJson = JSONObject(recognizer.partialResult ?: "{}")
                        val partial = partialJson.optString("partial", "").trim()
                        if (partial.isNotBlank()) bestPartial = partial
                        putBounded(partials, partialJson)
                        partialCount += 1
                    }
                    offset += count
                }
                val finalJson = JSONObject(recognizer.finalResult ?: "{}")
                val finalText = finalJson.optString("text", "").trim()
                val text = finalText.ifBlank { bestText.ifBlank { bestPartial } }
                val confidence = if (text.isBlank()) 0.0 else if (finalText.isBlank()) 0.55 else 0.75
                TranscriptionResult(
                    transcript = text,
                    confidence = confidence,
                    error = if (text.isBlank()) "vosk_transcript_empty" else "",
                    engine = name,
                    partialTranscript = bestPartial,
                    diagnostics = JSONObject()
                        .put("schema", "hermes.wasm_agent.vosk_transcription_debug.v1")
                        .put("mode", mode)
                        .put("sample_count", samples.size)
                        .put("sample_rate_hz", sampleRateHz)
                        .put("grammar", activeGrammar)
                        .put("chunk_size", chunkSize)
                        .put("partial_count", partialCount)
                        .put("intermediate_count", resultCount)
                        .put("partial_results", partials)
                        .put("intermediate_results", results)
                        .put("final_result", finalJson)
                        .put("best_partial", bestPartial)
                        .put("best_result_text", bestText)
                        .put("text", text),
                )
            }
        } catch (error: Throwable) {
            lastError = "vosk_transcribe_${error.javaClass.simpleName}"
            TranscriptionResult(
                "",
                0.0,
                lastError,
                engine = name,
                latencyMs = System.currentTimeMillis() - attemptStartedAt,
                diagnostics = JSONObject()
                    .put("schema", "hermes.wasm_agent.vosk_transcription_debug.v1")
                    .put("mode", mode)
                    .put("sample_count", samples.size)
                    .put("sample_rate_hz", sampleRateHz)
                    .put("grammar", activeGrammar)
                    .put("error", lastError),
            )
        }
    }

    private val TranscriptionResult.score: Int
        get() = when {
            transcript.isNotBlank() -> 100
            partialTranscript.isNotBlank() -> 80
            error.isBlank() -> 20
            else -> 0
        }

    private fun putBounded(array: JSONArray, value: JSONObject) {
        if (array.length() >= MAX_DIAGNOSTIC_RESULTS) array.remove(0)
        array.put(value)
    }
}

class WhisperCppEngine : TranscriptionEngine {
    override val name: String = "WhisperCppEngine(future)"
    override fun transcribePcm16(samples: ShortArray, sampleRateHz: Int, timeoutMs: Long): TranscriptionResult =
        TranscriptionResult("", 0.0, "whisper_cpp_engine_not_bundled", engine = name)
}
