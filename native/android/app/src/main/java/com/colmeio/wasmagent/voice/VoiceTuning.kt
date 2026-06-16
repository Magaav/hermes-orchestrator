package com.colmeio.wasmagent.voice

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import org.json.JSONArray
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
import kotlin.math.log10
import kotlin.math.max
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
        production = positive >= 50 && negative >= 50,
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

data class VoiceTuningQuality(
    val accepted: Boolean,
    val rejectionReason: String,
    val durationMs: Int,
    val rmsDb: Double,
    val peakDb: Double,
    val clippingRatio: Double,
    val silenceRatio: Double,
    val snrEstimate: Double,
    val duplicate: Boolean,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("duration_ms", durationMs)
        .put("rms_db", rmsDb)
        .put("peak_db", peakDb)
        .put("clipping_ratio", clippingRatio)
        .put("silence_ratio", silenceRatio)
        .put("snr_estimate", snrEstimate)
        .put("accepted", accepted)
        .put("rejected", !accepted)
        .put("rejection_reason", rejectionReason)
        .put("duplicate", duplicate)
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
        val quality = analyzeQuality(category, pcm16)
        require(quality.accepted) { quality.rejectionReason }
        val file = nextSampleFile(category)
        try {
            writePcm16Wav(file, pcm16, SAMPLE_RATE_HZ)
        } catch (error: Exception) {
            throw IllegalArgumentException("failed_wav_write:${error.javaClass.simpleName}")
        }
        if (file.length() <= WAV_HEADER_BYTES) {
            file.delete()
            throw IllegalArgumentException("zero_byte_recording")
        }
        if (!isValidWav(file)) {
            file.delete()
            throw IllegalArgumentException("invalid_format")
        }
        writeMetadata(file, category, durationMs, source, deviceLabel, quality)
        invalidateCounts()
        return sampleEvent("voice_tuning_sample_recorded", category, file, durationMs, source)
            .put("quality_metrics", quality.toJson())
            .put("accepted", true)
            .put("rejection_reason", "")
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
            .put("quality_gates", JSONObject()
                .put("min_duration_ms", MIN_DURATION_MS)
                .put("max_duration_ms", MAX_DURATION_MS)
                .put("min_voice_rms_db", MIN_VOICE_RMS_DB)
                .put("max_clipping_ratio", MAX_CLIPPING_RATIO)
                .put("max_voice_silence_ratio", MAX_VOICE_SILENCE_RATIO)
                .put("sample_rate_hz", SAMPLE_RATE_HZ)
                .put("channels", 1))
            .put("collection_plan", collectionPlanJson())
            .put("readiness_score", readinessScore(counts))
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
        val samples = sampleMetadata()
        val accepted = samples.count { it.optBoolean("accepted", false) }
        val rejected = samples.count { !it.optBoolean("accepted", false) }
        return JSONObject()
            .put("schema", "hermes.wasm_agent.android_hermes_wake_dataset.v2")
            .put("name", "hermes-dataset")
            .put("build_id", "android")
            .put("wizard_version", WIZARD_VERSION)
            .put("wake_phrase", "Hermes")
            .put("model_target_wake_word", "hermes")
            .put("created_at", isoNow())
            .put("user_session_id_hash", JSONObject.NULL)
            .put("device_model", samples.firstOrNull()?.optString("device_model", "") ?: "")
            .put("android_version", JSONObject.NULL)
            .put("microphone_source", "MIC")
            .put("sample_category_counts", counts.toJson())
            .put("accepted_count", accepted)
            .put("rejected_count", rejected)
            .put("positive_count", counts.positive)
            .put("negative_silence_count", counts.silence)
            .put("negative_speech_count", counts.speech)
            .put("negative_noise_count", counts.noise)
            .put("total_negative_count", counts.negative)
            .put("sample_rate", SAMPLE_RATE_HZ)
            .put("channels", 1)
            .put("encoding", "PCM16")
            .put("duration_ms", SAMPLE_DURATION_MS)
            .put("sample_rate_hz", SAMPLE_RATE_HZ)
            .put("quality_gates", JSONObject()
                .put("min_duration_ms", MIN_DURATION_MS)
                .put("max_duration_ms", MAX_DURATION_MS)
                .put("min_voice_rms_db", MIN_VOICE_RMS_DB)
                .put("max_clipping_ratio", MAX_CLIPPING_RATIO)
                .put("max_voice_silence_ratio", MAX_VOICE_SILENCE_RATIO))
            .put("samples", JSONArray(samples))
            .put("collection_plan", collectionPlanJson())
            .put("readiness_score", readinessScore(counts))
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
            .put("accepted_count", sampleMetadata().count { it.optBoolean("accepted", false) })
            .put("rejected_count", sampleMetadata().count { !it.optBoolean("accepted", false) })
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
        quality: VoiceTuningQuality,
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
            .put("wizard_version", WIZARD_VERSION)
            .put("device_model", deviceLabel ?: JSONObject.NULL)
            .put("accepted", quality.accepted)
            .put("rejection_reason", quality.rejectionReason)
            .put("quality_metrics", quality.toJson())
            .put("rms_db", quality.rmsDb)
            .put("peak_db", quality.peakDb)
            .put("clipping_ratio", quality.clippingRatio)
            .put("silence_ratio", quality.silenceRatio)
            .put("snr_estimate", quality.snrEstimate)
            .put("fingerprint", fingerprint(readPcm16Wav(wavFile)))
            .put("device_label", deviceLabel ?: JSONObject.NULL)
            .put("audio_file", wavFile.name)
        File(wavFile.parentFile, wavFile.nameWithoutExtension + ".json").writeText(metadata.toString(2))
    }

    private fun allSampleFiles(): List<File> = VoiceTuningCategory.entries.flatMap { category ->
        categoryDir(category).listFiles()?.filter { it.isFile }.orEmpty()
    }

    private fun sampleMetadata(): List<JSONObject> = VoiceTuningCategory.entries.flatMap { category ->
        categoryDir(category).listFiles { file -> file.isFile && file.extension == "json" }
            ?.mapNotNull { file -> runCatching { JSONObject(file.readText()) }.getOrNull() }
            .orEmpty()
    }

    private fun analyzeQuality(category: VoiceTuningCategory, pcm16: ShortArray): VoiceTuningQuality {
        val durationMs = if (SAMPLE_RATE_HZ > 0) (pcm16.size * 1000) / SAMPLE_RATE_HZ else 0
        if (pcm16.isEmpty()) return rejectedQuality("zero_byte_recording", durationMs)
        val rmsValue = rms(pcm16)
        val peak = pcm16.maxOfOrNull { abs(it.toInt()) } ?: 0
        val rmsDb = amplitudeDb(rmsValue / Short.MAX_VALUE.toDouble())
        val peakDb = amplitudeDb(peak / Short.MAX_VALUE.toDouble())
        val clippingRatio = pcm16.count { abs(it.toInt()) >= CLIPPING_SAMPLE_ABS }.toDouble() / pcm16.size
        val silenceRatio = pcm16.count { abs(it.toInt()) <= SILENCE_SAMPLE_ABS }.toDouble() / pcm16.size
        val noiseFloor = percentileAbs(pcm16, 0.10).coerceAtLeast(1.0)
        val snrEstimate = 20.0 * log10((rmsValue.coerceAtLeast(1.0)) / noiseFloor)
            val duplicate = category != VoiceTuningCategory.NEGATIVE_SILENCE && hasNearDuplicate(pcm16)
        val reason = when {
            durationMs < MIN_DURATION_MS -> "too_short"
            durationMs > MAX_DURATION_MS -> "too_long"
            clippingRatio > MAX_CLIPPING_RATIO -> "clipped_audio"
            duplicate -> "duplicate_sample"
            category != VoiceTuningCategory.NEGATIVE_SILENCE && rmsDb < MIN_VOICE_RMS_DB -> "too_quiet"
            category != VoiceTuningCategory.NEGATIVE_SILENCE && silenceRatio > MAX_VOICE_SILENCE_RATIO -> "mostly_silence"
            category == VoiceTuningCategory.NEGATIVE_SILENCE && peakDb > MAX_SILENCE_PEAK_DB -> "excessive_noise"
            else -> ""
        }
        return VoiceTuningQuality(reason.isBlank(), reason, durationMs, rmsDb, peakDb, clippingRatio, silenceRatio, snrEstimate, duplicate)
    }

    private fun rejectedQuality(reason: String, durationMs: Int): VoiceTuningQuality =
        VoiceTuningQuality(false, reason, durationMs, -120.0, -120.0, 0.0, 1.0, 0.0, false)

    private fun hasNearDuplicate(pcm16: ShortArray): Boolean {
        val fingerprint = fingerprint(pcm16)
        return sampleMetadata().any { metadata ->
            metadata.optString("fingerprint", "") == fingerprint ||
                metadata.optJSONObject("quality_metrics")?.optBoolean("duplicate", false) == true
        }
    }

    private fun collectionPlanJson(): JSONObject = JSONObject()
        .put("positive_normal", 10)
        .put("positive_soft", 10)
        .put("positive_farther", 10)
        .put("positive_phone_on_desk", 10)
        .put("positive_noisy_room", 10)
        .put("silence_background", 20)
        .put("speech_negative", 20)
        .put("confuser_negative", 10)

    private fun readinessScore(counts: VoiceTuningCounts): Int {
        val positive = (counts.positive.toDouble() / REAL_POSITIVE_COUNT).coerceIn(0.0, 1.0)
        val silence = (counts.silence.toDouble() / 20.0).coerceIn(0.0, 1.0)
        val speech = (counts.speech.toDouble() / 30.0).coerceIn(0.0, 1.0)
        val noise = (counts.noise.toDouble() / 10.0).coerceIn(0.0, 1.0)
        return ((positive * 50.0) + (silence * 20.0) + (speech * 20.0) + (noise * 10.0)).toInt().coerceIn(0, 100)
    }

    companion object {
        const val SMOKE_POSITIVE_COUNT = 5
        const val SMOKE_NEGATIVE_COUNT = 10
        const val REAL_POSITIVE_COUNT = 50
        const val REAL_NEGATIVE_COUNT = 50
        const val SAMPLE_RATE_HZ = 16_000
        const val SAMPLE_DURATION_MS = 1_000
        const val SAMPLE_COUNT = SAMPLE_RATE_HZ * SAMPLE_DURATION_MS / 1_000
        const val MIN_DURATION_MS = 700
        const val MAX_DURATION_MS = 1400
        const val MIN_VOICE_RMS_DB = -45.0
        const val MAX_SILENCE_PEAK_DB = -28.0
        const val MAX_CLIPPING_RATIO = 0.01
        const val MAX_VOICE_SILENCE_RATIO = 0.85
        const val SILENCE_SAMPLE_ABS = 96
        const val CLIPPING_SAMPLE_ABS = 32100
        const val WAV_HEADER_BYTES = 44L
        const val WIZARD_VERSION = "2026.06.hermes-balanced-v2"
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

        fun amplitudeDb(amplitude: Double): Double =
            if (amplitude <= 0.0) -120.0 else (20.0 * log10(amplitude)).coerceAtLeast(-120.0)

        fun percentileAbs(pcm16: ShortArray, percentile: Double): Double {
            if (pcm16.isEmpty()) return 0.0
            val values = pcm16.map { abs(it.toInt()).toDouble() }.sorted()
            val index = ((values.size - 1) * percentile.coerceIn(0.0, 1.0)).toInt()
            return values[index]
        }

        fun fingerprint(pcm16: ShortArray): String {
            if (pcm16.isEmpty()) return ""
            val buckets = 64
            val bucketSize = max(1, pcm16.size / buckets)
            return (0 until buckets).joinToString(":") { bucket ->
                val start = bucket * bucketSize
                val end = minOf(pcm16.size, start + bucketSize)
                val avg = if (start >= end) 0 else pcm16.sliceArray(start until end).map { abs(it.toInt()) }.average().toInt()
                (avg / 16).coerceIn(0, 4095).toString(16)
            }
        }

        fun readPcm16Wav(file: File): ShortArray {
            val bytes = file.readBytes()
            if (bytes.size <= WAV_HEADER_BYTES) return ShortArray(0)
            val count = (bytes.size - WAV_HEADER_BYTES.toInt()) / 2
            return ShortArray(count) { index ->
                val offset = WAV_HEADER_BYTES.toInt() + index * 2
                ((bytes[offset].toInt() and 0xff) or (bytes[offset + 1].toInt() shl 8)).toShort()
            }
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
