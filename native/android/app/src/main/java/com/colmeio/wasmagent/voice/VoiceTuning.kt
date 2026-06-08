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
import java.util.UUID
import kotlin.concurrent.thread

enum class VoiceTuningCategory(val id: String, val relativeDir: String, val targetCount: Int, val kind: String) {
    POSITIVE("positive", "positive", 5, "positive"),
    NEGATIVE_SILENCE("negative/silence", "negative/silence", 4, "negative_silence"),
    NEGATIVE_SPEECH("negative/speech", "negative/speech", 3, "negative_speech"),
    NEGATIVE_NOISE("negative/noise", "negative/noise", 3, "negative_noise");

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
        production = positive >= 200 && silence >= 100 && speech >= 100 && noise >= 100,
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
    fun categoryDir(category: VoiceTuningCategory): File = File(root, category.relativeDir)

    fun counts(): VoiceTuningCounts = VoiceTuningCounts(
        positive = wavCount(VoiceTuningCategory.POSITIVE),
        silence = wavCount(VoiceTuningCategory.NEGATIVE_SILENCE),
        speech = wavCount(VoiceTuningCategory.NEGATIVE_SPEECH),
        noise = wavCount(VoiceTuningCategory.NEGATIVE_NOISE),
    )

    fun nextSampleFile(category: VoiceTuningCategory, nowMs: Long = System.currentTimeMillis()): File {
        val safeCategory = category.id.replace("/", "-")
        val dir = categoryDir(category)
        dir.mkdirs()
        while (true) {
            val file = File(dir, "hermes-${safeCategory}-${nowMs}-${UUID.randomUUID()}.wav")
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
        val file = nextSampleFile(category)
        writePcm16Wav(file, pcm16, SAMPLE_RATE_HZ)
        if (file.length() <= WAV_HEADER_BYTES) {
            file.delete()
            throw IllegalArgumentException("zero_byte_recording")
        }
        writeMetadata(file, category, durationMs, source, deviceLabel)
        return sampleEvent("voice_tuning_sample_recorded", category, file, durationMs, source)
    }

    fun deleteLast(category: VoiceTuningCategory): JSONObject {
        val latest = categoryDir(category).listFiles { file -> file.extension == "wav" }
            ?.maxByOrNull { it.lastModified() }
        val deleted = latest?.delete() == true
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
            .put("encoding", "PCM16 WAV")
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
                .put("positives_required", TINY_POSITIVE_COUNT)
                .put("negatives_current", counts.negative)
                .put("negatives_required", TINY_NEGATIVE_COUNT))
            .put("dataset_ready", counts.thresholds().tiny)
            .put("model_status", modelStatus)
            .put("next_required_action", nextAction)
            .put("training_triggered", false)
            .put("real_wake_enabled", false)
            .put("continuous_audio_uploaded", false)
    }

    fun sampleEvent(type: String, category: VoiceTuningCategory, file: File?, durationMs: Int, source: String? = null): JSONObject {
        val counts = counts()
        val event = JSONObject()
            .put("type", type)
            .put("category", category.id)
            .put("kind", category.kind)
            .put("sample_count", counts.countFor(category))
            .put("duration_ms", durationMs)
            .put("duration", durationMs / 1000.0)
            .put("sample_rate", SAMPLE_RATE_HZ)
            .put("storage_path", file?.absolutePath ?: JSONObject.NULL)
            .put("thresholds", counts.thresholds().toJson())
            .put("counts", counts.toJson())
            .put("dataset_ready", counts.thresholds().tiny)
        if (!source.isNullOrBlank()) event.put("source", source)
        return event
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
            .put("kind", category.kind)
            .put("category", category.id)
            .put("source", source ?: JSONObject.NULL)
            .put("timestamp", System.currentTimeMillis())
            .put("duration", durationMs / 1000.0)
            .put("duration_ms", durationMs)
            .put("sample_rate", SAMPLE_RATE_HZ)
            .put("sample_rate_hz", SAMPLE_RATE_HZ)
            .put("device_label", deviceLabel ?: JSONObject.NULL)
            .put("audio_file", wavFile.name)
        File(wavFile.parentFile, wavFile.nameWithoutExtension + ".json").writeText(metadata.toString(2))
    }

    companion object {
        const val TINY_POSITIVE_COUNT = 5
        const val TINY_NEGATIVE_COUNT = 10
        const val SAMPLE_RATE_HZ = 16_000
        const val SAMPLE_DURATION_MS = 1_200
        const val SAMPLE_COUNT = SAMPLE_RATE_HZ * SAMPLE_DURATION_MS / 1_000
        const val WAV_HEADER_BYTES = 44L
        const val NEXT_ACTION = "Collect samples, export the dataset, then run audit/train/verify/import on the repository pipeline."

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
                val pcm = recordBoundedPcm16()
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
                onEvent(JSONObject()
                    .put("type", "voice_tuning_recording_failed")
                    .put("category", category.id)
                    .put("source", source ?: JSONObject.NULL)
                    .put("error", error.message ?: error.javaClass.simpleName))
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
        val recorder = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            VoiceTuningStore.SAMPLE_RATE_HZ,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minBuffer, VoiceTuningStore.SAMPLE_COUNT * 2),
        )
        val pcm = ShortArray(VoiceTuningStore.SAMPLE_COUNT)
        var offset = 0
        try {
            recorder.startRecording()
            while (active && offset < pcm.size) {
                val read = recorder.read(pcm, offset, pcm.size - offset)
                if (read > 0) offset += read
            }
        } finally {
            runCatching { recorder.stop() }
            recorder.release()
        }
        if (cancelRequested) throw IllegalStateException("voice_tuning_cancelled")
        if (offset <= 0) throw IllegalArgumentException("zero_byte_recording")
        return if (offset == pcm.size) pcm else pcm.copyOf(offset)
    }
}
