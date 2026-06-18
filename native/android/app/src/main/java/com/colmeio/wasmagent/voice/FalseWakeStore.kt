package com.colmeio.wasmagent.voice

import android.content.Context
import android.util.Base64
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.concurrent.thread

object FalseWakeStore {
    const val MAX_SAMPLES = 50
    private const val LOG_TAG = "FalseWakeStore"
    private const val PREFS_NAME = "wasm_agent_android_shell"
    private const val PREF_LAST_UPLOADED_AT = "false_wake_last_uploaded_at"
    private const val PREF_LAST_DELETED_COUNT = "false_wake_last_deleted_count"
    private const val SAMPLE_RATE_HZ = 16_000

    fun directory(context: Context): File = File(context.filesDir, "voice/false-wakes")

    fun captureAsync(context: Context, metadata: JSONObject, pcm16: ShortArray) {
        val appContext = context.applicationContext
        val metadataCopy = JSONObject(metadata.toString())
        val audioCopy = pcm16.copyOf()
        thread(name = "hermes-false-wake-store") {
            try {
                capture(appContext, metadataCopy, audioCopy)
            } catch (error: Exception) {
                Log.w(LOG_TAG, "false wake capture failed: ${error.javaClass.simpleName}")
            }
        }
    }

    fun diagnostics(context: Context): JSONObject {
        val samples = sampleDirs(context)
        return JSONObject()
            .put("false_wake_buffer_count", samples.size)
            .put("false_wake_buffer_max", MAX_SAMPLES)
            .put("false_wake_last_uploaded_at", context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).getLong(PREF_LAST_UPLOADED_AT, 0L))
            .put("false_wake_last_deleted_count", context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).getInt(PREF_LAST_DELETED_COUNT, 0))
            .put("false_wake_storage_bytes", storageBytes(directory(context)))
    }

    fun batch(context: Context): JSONObject {
        val items = JSONArray()
        sampleDirs(context).forEach { dir ->
            val metadataFile = File(dir, "metadata.json")
            val audioFile = File(dir, "audio.wav")
            if (!metadataFile.isFile || !audioFile.isFile) return@forEach
            val metadata = runCatching { JSONObject(metadataFile.readText()) }.getOrNull() ?: return@forEach
            val audioBase64 = runCatching {
                Base64.encodeToString(audioFile.readBytes(), Base64.NO_WRAP)
            }.getOrDefault("")
            items.put(metadata
                .put("id", metadata.optString("id", dir.name))
                .put("audio_format", "wav_pcm16_mono_16khz")
                .put("audio_base64", audioBase64)
                .put("audio_bytes", audioFile.length()))
        }
        return diagnostics(context)
            .put("ok", true)
            .put("schema", "hermes.wasm_agent.android_false_wake_batch.v1")
            .put("samples", items)
    }

    fun deleteConfirmed(context: Context, ids: List<String> = emptyList()): JSONObject {
        var deleted = 0
        val keep = ids.map { safeId(it) }.filter { it.isNotBlank() }.toSet()
        sampleDirs(context).forEach { dir ->
            if (keep.isEmpty() || dir.name in keep) {
                if (deleteRecursively(dir)) deleted += 1
            }
        }
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
            .putLong(PREF_LAST_UPLOADED_AT, System.currentTimeMillis())
            .putInt(PREF_LAST_DELETED_COUNT, deleted)
            .apply()
        enforceLimit(context)
        return diagnostics(context).put("ok", true).put("deleted_count", deleted)
    }

    private fun capture(context: Context, metadata: JSONObject, pcm16: ShortArray) {
        val root = directory(context)
        root.mkdirs()
        enforceLimit(context, roomForNewSample = true)
        val timestamp = metadata.optLong("timestamp", System.currentTimeMillis())
        val id = safeId(metadata.optString("id")).ifBlank { "fw-$timestamp-${System.nanoTime()}" }
        val dir = File(root, id)
        if (!dir.mkdirs() && !dir.isDirectory) throw IllegalStateException("sample_dir_create_failed")
        val boundedPcm = lastSamples(pcm16, SAMPLE_RATE_HZ * 3)
        File(dir, "audio.wav").writeBytes(wavBytes(boundedPcm, SAMPLE_RATE_HZ))
        File(dir, "metadata.json").writeText(metadata
            .put("id", id)
            .put("schema", "hermes.wasm_agent.android_false_wake_sample.v1")
            .put("audio_format", "wav_pcm16_mono_16khz")
            .put("audio_duration_ms", (boundedPcm.size * 1000L) / SAMPLE_RATE_HZ)
            .put("audio_bytes", File(dir, "audio.wav").length())
            .toString(2))
        enforceLimit(context)
    }

    private fun enforceLimit(context: Context, roomForNewSample: Boolean = false) {
        val targetMax = if (roomForNewSample) MAX_SAMPLES - 1 else MAX_SAMPLES
        val dirs = sampleDirs(context).toMutableList()
        while (dirs.size > targetMax) {
            val oldest = dirs.removeAt(0)
            deleteRecursively(oldest)
        }
    }

    private fun sampleDirs(context: Context): List<File> =
        directory(context).listFiles()
            ?.filter { it.isDirectory }
            ?.sortedWith(compareBy<File> { metadataTimestamp(it) }.thenBy { it.name })
            ?: emptyList()

    private fun metadataTimestamp(dir: File): Long =
        runCatching { JSONObject(File(dir, "metadata.json").readText()).optLong("timestamp", dir.lastModified()) }
            .getOrDefault(dir.lastModified())

    private fun storageBytes(file: File): Long {
        if (!file.exists()) return 0L
        if (file.isFile) return file.length()
        return file.listFiles()?.sumOf { storageBytes(it) } ?: 0L
    }

    private fun deleteRecursively(file: File): Boolean =
        runCatching { file.deleteRecursively() }.getOrDefault(false)

    private fun safeId(value: String): String =
        value.replace(Regex("[^A-Za-z0-9._-]"), "_").take(96)

    private fun lastSamples(samples: ShortArray, maxSamples: Int): ShortArray {
        if (samples.size <= maxSamples) return samples
        return samples.copyOfRange(samples.size - maxSamples, samples.size)
    }

    private fun wavBytes(samples: ShortArray, sampleRateHz: Int): ByteArray {
        val dataBytes = samples.size * 2
        val buffer = ByteBuffer.allocate(44 + dataBytes).order(ByteOrder.LITTLE_ENDIAN)
        buffer.put("RIFF".toByteArray(Charsets.US_ASCII))
        buffer.putInt(36 + dataBytes)
        buffer.put("WAVEfmt ".toByteArray(Charsets.US_ASCII))
        buffer.putInt(16)
        buffer.putShort(1.toShort())
        buffer.putShort(1.toShort())
        buffer.putInt(sampleRateHz)
        buffer.putInt(sampleRateHz * 2)
        buffer.putShort(2.toShort())
        buffer.putShort(16.toShort())
        buffer.put("data".toByteArray(Charsets.US_ASCII))
        buffer.putInt(dataBytes)
        samples.forEach { buffer.putShort(it) }
        return buffer.array()
    }
}
