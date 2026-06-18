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
)

data class TranscriptionResult(
    val transcript: String,
    val confidence: Double,
    val error: String = "",
    val engine: String = "",
    val latencyMs: Long = 0,
    val audioCapturedMs: Long = 0,
    val partialTranscript: String = "",
)

class OpenWakeWordOnnxEngine(
    private val modelFile: File,
    private val threshold: Double = DEFAULT_CONFIDENCE_THRESHOLD,
    private val modelSource: String = "none",
) : WakeWordEngine {
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
            lastOnnxRuntimeError = ""
            true
        } catch (error: Throwable) {
            lastOnnxRuntimeError = describeThrowable(error)
            lastError = lastOnnxRuntimeError
            false
        }

    val onnxRuntimeError: String
        get() {
            onnxRuntimeAvailable
            return lastOnnxRuntimeError
        }

    val wakeEngineError: String
        get() = if (ready) "" else lastError.ifBlank { diagnosticReason }

    fun diagnostics(): JSONObject = JSONObject()
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

data class WakeModelCandidate(
    val source: String,
    val file: File,
)

data class WakeModelSelection(
    val source: String,
    val engine: OpenWakeWordOnnxEngine,
    val personalizedModelExists: Boolean,
    val baseModelExists: Boolean,
    val attempted: List<OpenWakeWordOnnxEngine>,
) {
    val ready: Boolean get() = engine.ready
}

object WakeModelSelector {
    const val PERSONALIZED_SOURCE = "personalized"
    const val BASE_SOURCE = "base"
    const val NONE_SOURCE = "none"

    fun select(
        personalizedModelFile: File,
        baseModelFile: File,
        threshold: Double = OpenWakeWordOnnxEngine.DEFAULT_CONFIDENCE_THRESHOLD,
    ): WakeModelSelection {
        val personalizedExists = validFile(personalizedModelFile)
        val baseExists = validFile(baseModelFile)
        val attempted = mutableListOf<OpenWakeWordOnnxEngine>()
        if (personalizedExists) {
            val engine = OpenWakeWordOnnxEngine(personalizedModelFile, threshold = threshold, modelSource = PERSONALIZED_SOURCE)
            attempted.add(engine)
            if (engine.ready) return WakeModelSelection(PERSONALIZED_SOURCE, engine, personalizedExists, baseExists, attempted)
        }
        if (baseExists) {
            val engine = OpenWakeWordOnnxEngine(baseModelFile, threshold = threshold, modelSource = BASE_SOURCE)
            attempted.add(engine)
            if (engine.ready) return WakeModelSelection(BASE_SOURCE, engine, personalizedExists, baseExists, attempted)
        }
        val engine = OpenWakeWordOnnxEngine(personalizedModelFile, threshold = threshold, modelSource = NONE_SOURCE)
        return WakeModelSelection(NONE_SOURCE, engine, personalizedExists, baseExists, attempted + engine)
    }

    private fun validFile(file: File): Boolean = file.exists() && file.isFile && file.length() > 0L
}

class AndroidSpeechRecognizerEngine(private val context: Context) : TranscriptionEngine {
    override val name: String = "AndroidSpeechRecognizerEngine"

    override fun transcribePcm16(samples: ShortArray, sampleRateHz: Int, timeoutMs: Long): TranscriptionResult =
        TranscriptionResult("", 0.0, "android_speech_recognizer_requires_live_capture", engine = name)

    override fun transcribeLiveAfterWake(timeoutMs: Long, policy: TranscriptionPolicy): TranscriptionResult {
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            return TranscriptionResult("", 0.0, "android_speech_recognizer_unavailable", engine = name)
        }
        val startedAt = System.currentTimeMillis()
        val latch = CountDownLatch(1)
        var transcript = ""
        var partialTranscript = ""
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
                    override fun onPartialResults(partialResults: Bundle?) {
                        partialTranscript = partialResults
                            ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                            ?.firstOrNull()
                            .orEmpty()
                    }
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
                    .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, policy.acceptPartialResults)
                    .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
                    .putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS, policy.minimumLengthMs)
                    .putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, policy.completeSilenceMs)
                    .putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, policy.possiblyCompleteSilenceMs)
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
        return TranscriptionResult(
            transcript = transcript,
            confidence = confidence,
            error = error,
            engine = name,
            latencyMs = System.currentTimeMillis() - startedAt,
            partialTranscript = partialTranscript,
        )
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
        private const val COMMAND_GRAMMAR = "[\"open wake world\", \"open wake word\", \"wake world\", \"wake word\", \"open\", \"start listener\", \"stop listener\", \"[unk]\"]"
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
        .put("local_asr_vosk_error", vosk.lastError)
        .put("local_asr_fallback_engine", fallback.name)

    override fun transcribePcm16(samples: ShortArray, sampleRateHz: Int, timeoutMs: Long): TranscriptionResult {
        if (preferredEngine != PREF_ENGINE_ANDROID && vosk.ready) {
            return vosk.transcribePcm16(samples, sampleRateHz, timeoutMs)
        }
        return fallback.transcribePcm16(samples, sampleRateHz, timeoutMs)
    }

    override fun transcribeLiveAfterWake(timeoutMs: Long, policy: TranscriptionPolicy): TranscriptionResult {
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
                latencyMs = System.currentTimeMillis() - startedAt,
                audioCapturedMs = capture.durationMs,
            )
        }
        val result = vosk.transcribePcm16(capture.samples, SAMPLE_RATE_HZ, timeoutMs)
        return result.copy(
            engine = name,
            latencyMs = System.currentTimeMillis() - startedAt,
            audioCapturedMs = capture.durationMs,
        )
    }

    private data class PcmCapture(val samples: ShortArray, val durationMs: Long, val error: String = "")

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
            recorder.startRecording()
            val startedAt = System.currentTimeMillis()
            var lastLoudAt = startedAt
            while (System.currentTimeMillis() - startedAt < captureMs) {
                val read = recorder.read(readBuffer, 0, readBuffer.size)
                if (read <= 0) continue
                var peak = 0
                for (index in 0 until read) {
                    val sample = readBuffer[index]
                    captured.add(sample)
                    peak = maxOf(peak, kotlin.math.abs(sample.toInt()))
                }
                if (peak > 250) lastLoudAt = System.currentTimeMillis()
                val elapsed = System.currentTimeMillis() - startedAt
                if (elapsed >= policy.minimumLengthMs && System.currentTimeMillis() - lastLoudAt >= policy.completeSilenceMs) break
            }
            val samples = ShortArray(captured.size)
            for (index in captured.indices) samples[index] = captured[index]
            PcmCapture(samples, System.currentTimeMillis() - startedAt)
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
        val startedAt = System.currentTimeMillis()
        if (samples.isEmpty()) return TranscriptionResult("", 0.0, "vosk_audio_empty", engine = name)
        if (sampleRateHz != LocalCommandTranscriptionEngine.SAMPLE_RATE_HZ) {
            return TranscriptionResult("", 0.0, "vosk_unsupported_sample_rate_$sampleRateHz", engine = name)
        }
        val activeModel = model ?: return TranscriptionResult("", 0.0, lastError.ifBlank { "vosk_model_missing" }, engine = name)
        return try {
            Recognizer(activeModel, sampleRateHz.toFloat(), grammar).use { recognizer ->
                recognizer.acceptWaveForm(samples, samples.size)
                val finalJson = JSONObject(recognizer.finalResult ?: "{}")
                val text = finalJson.optString("text", "").trim()
                val confidence = if (text.isBlank()) 0.0 else 0.75
                TranscriptionResult(
                    transcript = text,
                    confidence = confidence,
                    error = if (text.isBlank()) "vosk_transcript_empty" else "",
                    engine = name,
                    latencyMs = System.currentTimeMillis() - startedAt,
                )
            }
        } catch (error: Throwable) {
            lastError = "vosk_transcribe_${error.javaClass.simpleName}"
            TranscriptionResult("", 0.0, lastError, engine = name, latencyMs = System.currentTimeMillis() - startedAt)
        }
    }
}

class WhisperCppEngine : TranscriptionEngine {
    override val name: String = "WhisperCppEngine(future)"
    override fun transcribePcm16(samples: ShortArray, sampleRateHz: Int, timeoutMs: Long): TranscriptionResult =
        TranscriptionResult("", 0.0, "whisper_cpp_engine_not_bundled", engine = name)
}
