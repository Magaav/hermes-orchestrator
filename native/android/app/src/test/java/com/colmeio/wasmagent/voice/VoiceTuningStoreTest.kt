package com.colmeio.wasmagent.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.json.JSONObject
import java.io.File

class VoiceTuningStoreTest {
    private var sampleSeed = 0
    @Test
    fun sampleFileNamesAvoidCollisions() {
        val root = tempRoot()
        try {
            val store = VoiceTuningStore(root)
            val first = store.nextSampleFile(VoiceTuningCategory.POSITIVE, nowMs = 1234)
            first.writeText("existing")
            val second = store.nextSampleFile(VoiceTuningCategory.POSITIVE, nowMs = 1234)

            assertFalse(first.name == second.name)
            assertTrue(first.name.startsWith("hermes_19700101_000001_234_"))
            assertTrue(second.parentFile!!.path.endsWith("positive"))
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun zeroByteRecordingsAreRejected() {
        val root = tempRoot()
        try {
            val store = VoiceTuningStore(root)

            try {
                store.writeSample(VoiceTuningCategory.NEGATIVE_SILENCE, ShortArray(0), VoiceTuningStore.SAMPLE_DURATION_MS)
                throw AssertionError("expected zero_byte_recording")
            } catch (error: IllegalArgumentException) {
                assertEquals("zero_byte_recording", error.message)
            }

            assertEquals(0, store.counts().silence)
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun sampleCountsAndThresholdsUpdate() {
        val root = tempRoot()
        try {
            val store = VoiceTuningStore(root)
            repeat(5) { store.writeSample(VoiceTuningCategory.POSITIVE, samplePcm(), VoiceTuningStore.SAMPLE_DURATION_MS) }
            repeat(4) { store.writeSample(VoiceTuningCategory.NEGATIVE_SILENCE, samplePcm(), VoiceTuningStore.SAMPLE_DURATION_MS) }
            repeat(3) { store.writeSample(VoiceTuningCategory.NEGATIVE_SPEECH, samplePcm(), VoiceTuningStore.SAMPLE_DURATION_MS) }
            repeat(3) { store.writeSample(VoiceTuningCategory.NEGATIVE_NOISE, samplePcm(), VoiceTuningStore.SAMPLE_DURATION_MS) }

            val counts = store.counts()
            assertEquals(5, counts.positive)
            assertEquals(4, counts.silence)
            assertEquals(3, counts.speech)
            assertEquals(3, counts.noise)
            assertEquals(10, counts.negative)
            assertTrue(counts.thresholds().tiny)
            assertFalse(counts.thresholds().useful)
            assertFalse(counts.thresholds().production)
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun datasetReadyRemainsFalseBeforeSmokeGateAndTrueAtGate() {
        val root = tempRoot()
        try {
            val store = VoiceTuningStore(root)
            repeat(4) { store.writeSample(VoiceTuningCategory.POSITIVE, samplePcm(), VoiceTuningStore.SAMPLE_DURATION_MS) }
            repeat(10) { store.writeSample(VoiceTuningCategory.NEGATIVE_SILENCE, samplePcm(), VoiceTuningStore.SAMPLE_DURATION_MS) }

            var status = store.status()
            assertFalse(status.getBoolean("dataset_ready"))
            assertEquals(4, status.getJSONObject("progress").getInt("positives_current"))
            assertEquals(10, status.getJSONObject("progress").getInt("negatives_current"))

            store.writeSample(VoiceTuningCategory.POSITIVE, samplePcm(), VoiceTuningStore.SAMPLE_DURATION_MS)
            status = store.status()
            assertTrue(status.getBoolean("dataset_ready"))
            assertEquals(50, status.getJSONObject("progress").getInt("positives_required"))
            assertEquals(50, status.getJSONObject("progress").getInt("negatives_required"))
            assertEquals(5, status.getJSONObject("progress").getInt("smoke_positives_required"))
            assertEquals(10, status.getJSONObject("progress").getInt("smoke_negatives_required"))
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun deleteLastDoesNotCorruptOtherCounts() {
        val root = tempRoot()
        try {
            val store = VoiceTuningStore(root)
            store.writeSample(VoiceTuningCategory.POSITIVE, samplePcm(), VoiceTuningStore.SAMPLE_DURATION_MS)
            store.writeSample(VoiceTuningCategory.NEGATIVE_NOISE, samplePcm(), VoiceTuningStore.SAMPLE_DURATION_MS)

            val event = store.deleteLast(VoiceTuningCategory.POSITIVE)

            assertTrue(event.getBoolean("deleted"))
            assertEquals(0, store.counts().positive)
            assertEquals(1, store.counts().noise)
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun cachedCountsAreInvalidatedAfterWritesAndDeletes() {
        val root = tempRoot()
        try {
            val store = VoiceTuningStore(root)
            assertEquals(0, store.counts().positive)

            store.writeSample(VoiceTuningCategory.POSITIVE, samplePcm(), VoiceTuningStore.SAMPLE_DURATION_MS)
            assertEquals(1, store.counts().positive)

            store.deleteLast(VoiceTuningCategory.POSITIVE)
            assertEquals(0, store.counts().positive)
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun statusNeverClaimsTrainingOrRealWake() {
        val root = tempRoot()
        try {
            val status = VoiceTuningStore(root).status()

            assertFalse(status.getBoolean("training_triggered"))
            assertFalse(status.getBoolean("real_wake_enabled"))
            assertFalse(status.getBoolean("continuous_audio_uploaded"))
            assertEquals("no_model", status.getString("model_status"))
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun sampleEventsIncludeSpaceHomeTuneVoiceSource() {
        val root = tempRoot()
        try {
            val store = VoiceTuningStore(root)
            val event = store.writeSample(
                VoiceTuningCategory.POSITIVE,
                samplePcm(),
                VoiceTuningStore.SAMPLE_DURATION_MS,
                source = "space-home:tune-voice",
                deviceLabel = "Pixel Test",
            )

            assertEquals("space-home:tune-voice", event.getString("source"))
            assertEquals("positive", event.getString("label"))
            assertEquals("hermes", event.getString("kind"))
            assertEquals("files/voice/hermes-dataset", store.status().getString("storage_path"))
            val metadataFile = requireNotNull(root.resolve("positive").listFiles { file -> file.extension == "json" }?.single())
            val metadata = JSONObject(metadataFile.readText())
            assertEquals("positive", metadata.getString("label"))
            assertEquals("hermes", metadata.getString("kind"))
            assertEquals("Hermes", metadata.getString("wake_phrase"))
            assertEquals("space-home:tune-voice", metadata.getString("source"))
            assertEquals(1.0, metadata.getDouble("duration"), 0.0)
            assertEquals(VoiceTuningStore.SAMPLE_RATE_HZ, metadata.getInt("sample_rate"))
            assertEquals(1, metadata.getInt("channels"))
            assertEquals("PCM16", metadata.getString("encoding"))
            assertTrue(metadata.getBoolean("accepted"))
            assertTrue(metadata.getJSONObject("quality_metrics").getBoolean("accepted"))
            assertTrue(metadata.has("rms_db"))
            assertTrue(metadata.has("peak_db"))
            assertTrue(metadata.has("clipping_ratio"))
            assertTrue(metadata.has("silence_ratio"))
            assertTrue(metadata.has("snr_estimate"))
            assertEquals("Pixel Test", metadata.getString("device_label"))
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun negativeSamplesAreCategorizedCorrectly() {
        val root = tempRoot()
        try {
            val store = VoiceTuningStore(root)

            val silence = store.writeSample(VoiceTuningCategory.NEGATIVE_SILENCE, samplePcm(), VoiceTuningStore.SAMPLE_DURATION_MS)
            val speech = store.writeSample(VoiceTuningCategory.NEGATIVE_SPEECH, samplePcm(), VoiceTuningStore.SAMPLE_DURATION_MS)
            val noise = store.writeSample(VoiceTuningCategory.NEGATIVE_NOISE, samplePcm(), VoiceTuningStore.SAMPLE_DURATION_MS)

            assertEquals("silence", silence.getString("kind"))
            assertEquals("speech", speech.getString("kind"))
            assertEquals("noise", noise.getString("kind"))
            assertEquals(3, store.counts().negative)
            assertEquals(1, root.resolve("negative/silence").listFiles { file -> file.extension == "wav" }?.size)
            assertEquals(1, root.resolve("negative/speech").listFiles { file -> file.extension == "wav" }?.size)
            assertEquals(1, root.resolve("negative/noise").listFiles { file -> file.extension == "wav" }?.size)
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun exportDatasetZipIncludesMetadataAndSamples() {
        val root = tempRoot()
        try {
            val store = VoiceTuningStore(root)
            store.writeSample(VoiceTuningCategory.POSITIVE, samplePcm(), 1000)
            store.writeSample(VoiceTuningCategory.NEGATIVE_NOISE, samplePcm(), 1000)

            val event = store.exportDataset(root.resolve("exports"))

            assertTrue(event.getBoolean("ok"))
            assertEquals("hermes-dataset.zip", event.getString("filename"))
            assertTrue(File(event.getString("path")).length() > 0)
            val metadata = event.getJSONObject("metadata")
            assertEquals("hermes-dataset", metadata.getString("name"))
            assertEquals("hermes.wasm_agent.android_hermes_wake_dataset.v2", metadata.getString("schema"))
            assertEquals("hermes", metadata.getString("model_target_wake_word"))
            assertTrue(metadata.has("wizard_version"))
            assertTrue(metadata.has("sample_category_counts"))
            assertTrue(metadata.has("samples"))
            assertEquals(1, metadata.getInt("positive_count"))
            assertEquals(1, metadata.getInt("negative_noise_count"))
            assertFalse(metadata.getBoolean("real_gate_ready"))
        } finally {
            root.deleteRecursively()
        }
    }

    private fun tempRoot(): File = File("build/test-voice-tuning-${System.nanoTime()}")

    private fun samplePcm(): ShortArray {
        sampleSeed += 1
        val amplitude = 600 + sampleSeed * 37
        var state = 17 + sampleSeed * 101
        return ShortArray(VoiceTuningStore.SAMPLE_RATE_HZ) { index ->
            state = (state * 1103515245 + 12345 + index) and 0x7fffffff
            val sign = if (((index / (23 + sampleSeed)) + sampleSeed) % 2 == 0) 1 else -1
            val jitter = (state % 180) - 90
            (sign * (amplitude + jitter)).toShort()
        }
    }
}
