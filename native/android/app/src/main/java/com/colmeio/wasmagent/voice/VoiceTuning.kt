package com.colmeio.wasmagent.voice

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlin.concurrent.thread
import kotlin.math.abs
import kotlin.math.sqrt

enum class VoiceTuningCategory(
    val id: String,
    val relativeDir: String,
    val targetCount: Int,
    val label: String,
    val kind: String,
    val filenamePrefix: String,
) {
    POSITIVE("positive", "positive", 50, "positive", "hermes", "hermes"),
    NEGATIVE_SILENCE("negative/silence", "negative/silence", 50, "negative", "silence", "silence"),
    NEGATIVE_SPEECH("negative/speech", "negative/speech", 100, "negative", "speech", "speech"),
    NEGATIVE_NOISE("negative/noise", "negative/noise", 50, "negative", "noise", "noise");

    companion object {
        fun fromId(id: String): VoiceTuningCategory? = entries.firstOrNull { it.id == id }
    }
}

data class VoiceTuningThresholds(
    val tiny: Boolean,
    val useful: Boolean,
    val production: Boolean,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("tiny", tiny)
        .put("useful", useful)
        .put("production", production)
}

data class VoiceTuningCounts(
    val positive: Int,
    val silence: Int,
    val speech: Int,
    val noise: Int,
) {
    val total: Int get() = positive + silence + speech + noise
    val negative: Int get() = silence + speech + noise

    fun thresholds(): VoiceTuningThresholds = VoiceTuningThresholds(
        tiny = positive >= 5 && negative >= 10,
        useful = positive >= 10 && silence >= 5 && speech >= 5 && noise >= 5,
        production = positive >= 50 && negative >= 200,
    )

    fun countFor(category: VoiceTuningCategory): Int = when (category) {
        VoiceTuningCategory.POSITIVE -> positive
        VoiceTuningCategory.NEGATIVE_SILENCE -> silence
        VoiceTuningCategory.NEGATIVE_SPEECH -> speech
        VoiceTuningCategory.NEGATIVE_NOISE -> noise
    }

    fun toJson(): JSONObject = JSONObject()
        .put("positive", positive)
        .put("negative_silence", silence)
        .put("negative_speech", speech)
        .put("negative_noise", noise)
        .put("negative", negative)
        .put("total", total)
}

class VoiceTuningStore(private val root: File) {
    @Volatile private var cachedCounts: VoiceTuningCounts? = null

    fun categoryDir(category: VoiceTuningCategory): File = File(root, category.relativeDir)

    @Synchronized
    fun counts(): VoiceTuningCounts {
        cachedCounts?.let { return it }
        val value = VoiceTuningCounts(
            positive = wavCount(VoiceTuningCategory.POSITIVE),
            silence = wavCount(VoiceTuningCategory.NEGATIVE_SILENCE),
            speech = wavCount(VoiceTuningCategory.NEGATIVE_SPEECH),
            noise = wavCount(VoiceTuningCategory.NEGATIVE_NOISE),
        )
        cachedCounts = value
        return value
    }

    fun nextSampleFile(category: VoiceTuningCategory, nowMs: Long = System.currentTimeMillis()): File {
        val dir = categoryDir(category)
        dir.mkdirs()
        val timestamp = filenameTimestamp(nowMs)
        while (true) {
            val file = File(dir, "${category.filenamePrefix}_${timestamp}_${UUID.randomUUID().toString().take(8)}.wav")
            if (!file.exists()) return file
        }
    }

    fun writeSample(
        category: VoiceTuningCategory,
        pcm16: ShortArray,
        durationMs: Int,
        source: String? = null,
        deviceLabel: String? = null,
    ): JSONObject {
        require(pcm16.isNotEmpty()) { "zero_byte_recording" }
        require(pcm16.size >= MIN_SAMPLE_COUNT) { "too_short" }
        if (category != VoiceTuningCategory.NEGATIVE_SILENCE && rms(pcm16) < MIN_VOICE_RMS) {
            throw IllegalArgumentException("too_quiet")
        }
        val file = nextSampleFile(category)
        writePcm16Wav(file, pcm16, SAMPLE_RATE_HZ)
        if (file.length() <= WAV_HEADER_BYTES) {
            file.delete()
            throw IllegalArgumentException("zero_byte_recording")
        }
        if (!isValidWav(file)) {
            file.delete()
            throw IllegalArgumentException("invalid_format")
        }
        writeMetadata(file, category, durationMs, source, deviceLabel)
        invalidateCounts()
        return sampleEvent("voice_tuning_sample_recorded", category, file, durationMs, source)
    }

    fun deleteLast(category: VoiceTuningCategory): JSONObject {
        val latest = categoryDir(category).listFiles { file -> file.extension == "wav" }
            ?.maxByOrNull { it.lastModified() }
        val metadata = latest?.let { File(it.parentFile, it.nameWithoutExtension + ".json") }
        val deleted = latest?.delete() == true
        if (deleted) metadata?.delete()
        if (deleted) invalidateCounts()
        return sampleEvent("voice_tuning_sample_deleted", category, latest, 0)
            .put("deleted", deleted)
    }

    fun status(modelStatus: String = "no_model", nextAction: String = NEXT_ACTION): JSONObject {
        val counts = counts()
        return JSONObject()
            .put("schema", "hermes.wasm_agent.android_voice_tuning.v1")
            .put("wake_phrase", "Hermes")
            .put("sample_rate_hz", SAMPLE_RATE_HZ)
            .put("channels", 1)
            .put("encoding", "PCM16")
            .put("sample_duration_ms", SAMPLE_DURATION_MS)
            .put("storage_path", "files/voice/hermes-dataset")
            .put("repo_export_paths", JSONObject()
                .put("positive", "data/voice/hermes/positive/")
                .put("negative_silence", "data/voice/hermes/negative/silence/")
                .put("negative_speech", "data/voice/hermes/negative/speech/")
                .put("negative_noise", "data/voice/hermes/negative/noise/"))
            .put("counts", counts.toJson())
            .put("thresholds", counts.thresholds().toJson())
            .put("progress", JSONObject()
                .put("positives_current", counts.positive)
                .put("positives_required", REAL_POSITIVE_COUNT)
                .put("negatives_current", counts.negative)
                .put("negatives_required", REAL_NEGATIVE_COUNT)
                .put("smoke_positives_required", SMOKE_POSITIVE_COUNT)
                .put("smoke_negatives_required", SMOKE_NEGATIVE_COUNT))
            .put("dataset_ready", counts.thresholds().tiny)
            .put("diagnostics", diagnostics())
            .put("positive_count", counts.positive)
            .put("negative_silence_count", counts.silence)
            .put("negative_speech_count", counts.speech)
            .put("negative_noise_count", counts.noise)
            .put("total_negative_count", counts.negative)
            .put("smoke_gate_ready", counts.positive >= SMOKE_POSITIVE_COUNT && counts.negative >= SMOKE_NEGATIVE_COUNT)
            .put("real_gate_ready", counts.positive >= REAL_POSITIVE_COUNT && counts.negative >= REAL_NEGATIVE_COUNT)
            .put("model_status", modelStatus)
            .put("next_required_action", nextAction)
            .put("training_triggered", false)
            .put("real_wake_enabled", false)
            .put("continuous_audio_uploaded", false)
    }

    fun sampleEvent(type: String, category: VoiceTuningCategory, file: File?, durationMs: Int, source: String? = null): JSONObject {
        val counts = counts()
        val event = JSONObject()
            .put("ok", type != "voice_tuning_recording_failed")
            .put("type", type)
            .put("category", category.id)
            .put("kind", category.kind)
            .put("label", category.label)
            .put("filename", file?.name ?: JSONObject.NULL)
            .put("path", file?.absolutePath ?: JSONObject.NULL)
            .put("sample_count", counts.countFor(category))
            .put("duration_ms", durationMs)
            .put("duration", durationMs / 1000.0)
            .put("sample_rate", SAMPLE_RATE_HZ)
            .put("storage_path", file?.absolutePath ?: JSONObject.NULL)
            .put("diagnostics", diagnostics())
            .put("thresholds", counts.thresholds().toJson())
            .put("counts", counts.toJson())
            .put("dataset_ready", counts.thresholds().tiny)
            .put("quality", if (file != null) "saved" else "pending")
        if (!source.isNullOrBlank()) event.put("source", source)
        return event
    }

    fun exportDataset(outputDir: File = File(root.parentFile ?: root, "exports")): JSONObject {
        outputDir.mkdirs()
        val output = File(outputDir, "hermes-dataset.zip")
        ZipOutputStream(FileOutputStream(output)).use { zip ->
            addJson(zip, "metadata.json", exportMetadata())
            for (category in VoiceTuningCategory.entries) {
                val base = category.relativeDir
                categoryDir(category).listFiles { file -> file.isFile && (file.extension == "wav" || file.extension == "json") }
                    ?.sortedBy { it.name }
                    ?.forEach { file -> addFile(zip, "$base/${file.name}", file) }
            }
        }
        return JSONObject()
            .put("ok", true)
            .put("type", "voice_tuning_dataset_exported")
            .put("filename", output.name)
            .put("path", output.absolutePath)
            .put("bytes", output.length())
            .put("metadata", exportMetadata())
    }

    fun exportMetadata(): JSONObject {
        val counts = counts()
        return JSONObject()
            .put("name", "hermes-dataset")
            .put("wake_phrase", "Hermes")
            .put("created_at", isoNow())
            .put("positive_count", counts.positive)
            .put("negative_silence_count", counts.silence)
            .put("negative_speech_count", counts.speech)
            .put("negative_noise_count", counts.noise)
            .put("total_negative_count", counts.negative)
            .put("sample_rate", SAMPLE_RATE_HZ)
            .put("channels", 1)
            .put("encoding", "PCM16")
            .put("duration_ms", SAMPLE_DURATION_MS)
            .put("smoke_gate_ready", counts.positive >= SMOKE_POSITIVE_COUNT && counts.negative >= SMOKE_NEGATIVE_COUNT)
            .put("real_gate_ready", counts.positive >= REAL_POSITIVE_COUNT && counts.negative >= REAL_NEGATIVE_COUNT)
    }

    private fun diagnostics(): JSONObject {
        val counts = counts()
        val sampleFiles = allSampleFiles()
        return JSONObject()
            .put("positive_count", counts.positive)
            .put("negative_silence_count", counts.silence)
            .put("negative_speech_count", counts.speech)
            .put("negative_noise_count", counts.noise)
            .put("total_negative_count", counts.negative)
            .put("zero_byte_count", sampleFiles.count { it.extension == "wav" && it.length() == 0L })
            .put("invalid_format_count", sampleFiles.count { it.extension == "wav" && !isValidWav(it) })
            .put("smoke_gate_ready", counts.positive >= SMOKE_POSITIVE_COUNT && counts.negative >= SMOKE_NEGATIVE_COUNT)
            .put("real_gate_ready", counts.positive >= REAL_POSITIVE_COUNT && counts.negative >= REAL_NEGATIVE_COUNT)
    }

    @Synchronized
    private fun invalidateCounts() {
        cachedCounts = null
    }

    private fun wavCount(category: VoiceTuningCategory): Int {
        return categoryDir(category).listFiles { file -> file.isFile && file.extension == "wav" }?.size ?: 0
    }

    private fun writeMetadata(
        wavFile: File,
        category: VoiceTuningCategory,
        durationMs: Int,
        source: String?,
        deviceLabel: String?,
    ) {
        val metadata = JSONObject()
            .put("schema", "hermes.wasm_agent.android_voice_tuning_sample.v1")
            .put("label", category.label)
            .put("kind", category.kind)
            .put("wake_phrase", "Hermes")
            .put("filename", wavFile.name)
            .put("category", category.id)
            .put("source", source ?: JSONObject.NULL)
            .put("timestamp", System.currentTimeMillis())
            .put("created_at", isoNow())
            .put("duration", durationMs / 1000.0)
            .put("duration_ms", durationMs)
            .put("sample_rate", SAMPLE_RATE_HZ)
            .put("sample_rate_hz", SAMPLE_RATE_HZ)
            .put("channels", 1)
            .put("encoding", "PCM16")
            .put("app_build", "android")
            .put("device_model", deviceLabel ?: JSONObject.NULL)
            .put("accepted", true)
            .put("device_label", deviceLabel ?: JSONObject.NULL)
            .put("audio_file", wavFile.name)
        File(wavFile.parentFile, wavFile.nameWithoutExtension + ".json").writeText(metadata.toString(2))
    }

    private fun allSampleFiles(): List<File> = VoiceTuningCategory.entries.flatMap { category ->
        categoryDir(category).listFiles()?.filter { it.isFile }.orEmpty()
    }

    companion object {
        const val SMOKE_POSITIVE_COUNT = 5
        const val SMOKE_NEGATIVE_COUNT = 10
        const val REAL_POSITIVE_COUNT = 50
        const val REAL_NEGATIVE_COUNT = 200
        const val SAMPLE_RATE_HZ = 16_000
        const val SAMPLE_DURATION_MS = 1_000
        const val SAMPLE_COUNT = SAMPLE_RATE_HZ * SAMPLE_DURATION_MS / 1_000
        const val MIN_SAMPLE_COUNT = SAMPLE_RATE_HZ * 800 / 1_000
        const val MIN_VOICE_RMS = 25.0
        const val WAV_HEADER_BYTES = 44L
        const val NEXT_ACTION = "Collect samples, export the dataset, then run audit/train/verify/import on the repository pipeline."

        fun filenameTimestamp(nowMs: Long): String =
            SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.US).format(Date(nowMs))

        fun isoNow(): String =
            SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US).format(Date())

        fun rms(pcm16: ShortArray): Double {
            if (pcm16.isEmpty()) return 0.0
            val sum = pcm16.fold(0.0) { acc, sample -> acc + abs(sample.toDouble()) * abs(sample.toDouble()) }
            return sqrt(sum / pcm16.size)
        }

        fun isValidWav(file: File): Boolean {
            if (!file.isFile || file.length() <= WAV_HEADER_BYTES) return false
            val header = file.inputStream().use { input -> ByteArray(44).also { input.read(it) } }
            return String(header, 0, 4, Charsets.US_ASCII) == "RIFF" &&
                String(header, 8, 4, Charsets.US_ASCII) == "WAVE" &&
                String(header, 12, 4, Charsets.US_ASCII) == "fmt " &&
                String(header, 36, 4, Charsets.US_ASCII) == "data"
        }

        private fun addFile(zip: ZipOutputStream, path: String, file: File) {
            zip.putNextEntry(ZipEntry(path))
            file.inputStream().use { it.copyTo(zip) }
            zip.closeEntry()
        }

        private fun addJson(zip: ZipOutputStream, path: String, json: JSONObject) {
            zip.putNextEntry(ZipEntry(path))
            zip.write(json.toString(2).toByteArray(Charsets.UTF_8))
            zip.closeEntry()
        }

        fun writePcm16Wav(file: File, pcm16: ShortArray, sampleRateHz: Int) {
            file.parentFile?.mkdirs()
            val dataBytes = pcm16.size * 2
            FileOutputStream(file).use { output ->
                output.write("RIFF".toByteArray(Charsets.US_ASCII))
                output.writeIntLe(36 + dataBytes)
                output.write("WAVEfmt ".toByteArray(Charsets.US_ASCII))
                output.writeIntLe(16)
                output.writeShortLe(1)
                output.writeShortLe(1)
                output.writeIntLe(sampleRateHz)
                output.writeIntLe(sampleRateHz * 2)
                output.writeShortLe(2)
                output.writeShortLe(16)
                output.write("data".toByteArray(Charsets.US_ASCII))
                output.writeIntLe(dataBytes)
                pcm16.forEach { output.writeShortLe(it.toInt()) }
            }
        }

        private fun FileOutputStream.writeIntLe(value: Int) {
            write(byteArrayOf(
                (value and 0xff).toByte(),
                ((value ushr 8) and 0xff).toByte(),
                ((value ushr 16) and 0xff).toByte(),
                ((value ushr 24) and 0xff).toByte(),
            ))
        }

        private fun FileOutputStream.writeShortLe(value: Int) {
            write(byteArrayOf((value and 0xff).toByte(), ((value ushr 8) and 0xff).toByte()))
        }
    }
}

class VoiceTuningRecorder(
    private val context: Context,
    private val store: VoiceTuningStore,
    private val deviceLabelProvider: () -> String? = { null },
) {
    @Volatile private var active = false
    @Volatile private var cancelRequested = false

    fun isRecording(): Boolean = active

    @SuppressLint("MissingPermission")
    fun record(category: VoiceTuningCategory, source: String? = null, onEvent: (JSONObject) -> Unit): JSONObject {
        if (active) return JSONObject().put("ok", false).put("error", "voice_tuning_recording_active")
        if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            return JSONObject().put("ok", false).put("error", "record_audio_permission_missing")
        }
        active = true
        cancelRequested = false
        onEvent(store.sampleEvent("voice_tuning_started", category, null, VoiceTuningStore.SAMPLE_DURATION_MS, source))
        thread(name = "hermes-voice-tuning-sample") {
            try {
                onEvent(store.sampleEvent("native_record_started", category, null, VoiceTuningStore.SAMPLE_DURATION_MS, source))
                val pcm = recordBoundedPcm16()
                onEvent(store.sampleEvent("native_record_finished", category, null, VoiceTuningStore.SAMPLE_DURATION_MS, source))
                val event = store.writeSample(category, pcm, VoiceTuningStore.SAMPLE_DURATION_MS, source, deviceLabelProvider())
                onEvent(event)
                onEvent(store.status().put("type", "voice_tuning_counts_updated"))
                val thresholds = store.counts().thresholds()
                if (thresholds.tiny || thresholds.useful || thresholds.production) {
                    onEvent(JSONObject()
                        .put("type", "voice_tuning_threshold_met")
                        .put("thresholds", thresholds.toJson())
                        .put("counts", store.counts().toJson()))
                }
                if (thresholds.useful) {
                    onEvent(JSONObject()
                        .put("type", "voice_tuning_completed")
                        .put("message", "Samples collected. Training and validation still required.")
                        .put("counts", store.counts().toJson())
                        .put("thresholds", thresholds.toJson()))
                }
            } catch (error: Exception) {
                val normalized = normalizeRecordError(error)
                onEvent(JSONObject()
                    .put("ok", false)
                    .put("type", "voice_tuning_recording_failed")
                    .put("category", category.id)
                    .put("kind", category.kind)
                    .put("label", category.label)
                    .put("duration_ms", VoiceTuningStore.SAMPLE_DURATION_MS)
                    .put("source", source ?: JSONObject.NULL)
                    .put("error", normalized.first)
                    .put("message", normalized.second))
            } finally {
                active = false
                cancelRequested = false
            }
        }
        return JSONObject().put("ok", true).put("bounded", true).put("duration_ms", VoiceTuningStore.SAMPLE_DURATION_MS)
    }

    fun cancel(): JSONObject {
        cancelRequested = true
        active = false
        return JSONObject().put("ok", true).put("type", "voice_tuning_cancelled")
    }

    private fun recordBoundedPcm16(): ShortArray {
        val minBuffer = AudioRecord.getMinBufferSize(
            VoiceTuningStore.SAMPLE_RATE_HZ,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        if (minBuffer <= 0) throw IllegalStateException("recorder_unavailable")
        val recorder = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            VoiceTuningStore.SAMPLE_RATE_HZ,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minBuffer, VoiceTuningStore.SAMPLE_COUNT * 2),
        )
        if (recorder.state != AudioRecord.STATE_INITIALIZED) {
            recorder.release()
            throw IllegalStateException("recorder_unavailable")
        }
        val pcm = ShortArray(VoiceTuningStore.SAMPLE_COUNT)
        var offset = 0
        try {
            recorder.startRecording()
            if (recorder.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
                throw IllegalStateException("recorder_unavailable")
            }
            while (active && offset < pcm.size) {
                val read = recorder.read(pcm, offset, pcm.size - offset)
                if (read > 0) offset += read
                else if (read == AudioRecord.ERROR_INVALID_OPERATION || read == AudioRecord.ERROR_BAD_VALUE || read == AudioRecord.ERROR_DEAD_OBJECT) {
                    throw IllegalStateException("recorder_unavailable")
                }
            }
        } finally {
            runCatching { recorder.stop() }
            recorder.release()
        }
        if (cancelRequested) throw IllegalStateException("voice_tuning_cancelled")
        if (offset <= 0) throw IllegalArgumentException("zero_byte_recording")
        return if (offset == pcm.size) pcm else pcm.copyOf(offset)
    }

    private fun normalizeRecordError(error: Exception): Pair<String, String> {
        val raw = error.message ?: error.javaClass.simpleName
        return when (raw) {
            "record_audio_permission_missing" -> "permission_denied" to "Microphone permission is required to record training samples."
            "recorder_unavailable", "audio_record_initialization_failed" -> "recorder_unavailable" to "Recorder unavailable."
            "too_quiet" -> "too_quiet" to "Too quiet. Try again."
            "too_short" -> "too_short" to "Too short. Try again."
            "zero_byte_recording" -> "too_short" to "Too short. Try again."
            "invalid_format" -> "invalid_wav" to "Recorder wrote an invalid WAV."
            "voice_tuning_cancelled" -> "native_error" to "Recording cancelled."
            else -> "native_error" to raw
        }
    }
}
