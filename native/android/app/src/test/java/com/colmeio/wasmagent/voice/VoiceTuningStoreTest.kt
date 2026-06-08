package com.colmeio.wasmagent.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.json.JSONObject
import java.io.File

class VoiceTuningStoreTest {
    @Test
    fun sampleFileNamesAvoidCollisions() {
        val root = tempRoot()
        try {
            val store = VoiceTuningStore(root)
            val first = store.nextSampleFile(VoiceTuningCategory.POSITIVE, nowMs = 1234)
            first.writeText("existing")
            val second = store.nextSampleFile(VoiceTuningCategory.POSITIVE, nowMs = 1234)

            assertFalse(first.name == second.name)
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
                store.writeSample(VoiceTuningCategory.NEGATIVE_SILENCE, ShortArray(0), 1200)
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
            repeat(5) { store.writeSample(VoiceTuningCategory.POSITIVE, samplePcm(), 1200) }
            repeat(4) { store.writeSample(VoiceTuningCategory.NEGATIVE_SILENCE, samplePcm(), 1200) }
            repeat(3) { store.writeSample(VoiceTuningCategory.NEGATIVE_SPEECH, samplePcm(), 1200) }
            repeat(3) { store.writeSample(VoiceTuningCategory.NEGATIVE_NOISE, samplePcm(), 1200) }

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
            repeat(4) { store.writeSample(VoiceTuningCategory.POSITIVE, samplePcm(), 1200) }
            repeat(10) { store.writeSample(VoiceTuningCategory.NEGATIVE_SILENCE, samplePcm(), 1200) }

            var status = store.status()
            assertFalse(status.getBoolean("dataset_ready"))
            assertEquals(4, status.getJSONObject("progress").getInt("positives_current"))
            assertEquals(10, status.getJSONObject("progress").getInt("negatives_current"))

            store.writeSample(VoiceTuningCategory.POSITIVE, samplePcm(), 1200)
            status = store.status()
            assertTrue(status.getBoolean("dataset_ready"))
            assertEquals(5, status.getJSONObject("progress").getInt("positives_required"))
            assertEquals(10, status.getJSONObject("progress").getInt("negatives_required"))
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun deleteLastDoesNotCorruptOtherCounts() {
        val root = tempRoot()
        try {
            val store = VoiceTuningStore(root)
            store.writeSample(VoiceTuningCategory.POSITIVE, samplePcm(), 1200)
            store.writeSample(VoiceTuningCategory.NEGATIVE_NOISE, samplePcm(), 1200)

            val event = store.deleteLast(VoiceTuningCategory.POSITIVE)

            assertTrue(event.getBoolean("deleted"))
            assertEquals(0, store.counts().positive)
            assertEquals(1, store.counts().noise)
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
                1200,
                source = "space-home:tune-voice",
                deviceLabel = "Pixel Test",
            )

            assertEquals("space-home:tune-voice", event.getString("source"))
            assertEquals("positive", event.getString("kind"))
            assertEquals("files/voice/hermes-dataset", store.status().getString("storage_path"))
            val metadataFile = requireNotNull(root.resolve("positive").listFiles { file -> file.extension == "json" }?.single())
            val metadata = JSONObject(metadataFile.readText())
            assertEquals("positive", metadata.getString("kind"))
            assertEquals("space-home:tune-voice", metadata.getString("source"))
            assertEquals(1.2, metadata.getDouble("duration"), 0.0)
            assertEquals(VoiceTuningStore.SAMPLE_RATE_HZ, metadata.getInt("sample_rate"))
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

            val silence = store.writeSample(VoiceTuningCategory.NEGATIVE_SILENCE, samplePcm(), 1200)
            val speech = store.writeSample(VoiceTuningCategory.NEGATIVE_SPEECH, samplePcm(), 1200)
            val noise = store.writeSample(VoiceTuningCategory.NEGATIVE_NOISE, samplePcm(), 1200)

            assertEquals("negative_silence", silence.getString("kind"))
            assertEquals("negative_speech", speech.getString("kind"))
            assertEquals("negative_noise", noise.getString("kind"))
            assertEquals(3, store.counts().negative)
            assertEquals(1, root.resolve("negative/silence").listFiles { file -> file.extension == "wav" }?.size)
            assertEquals(1, root.resolve("negative/speech").listFiles { file -> file.extension == "wav" }?.size)
            assertEquals(1, root.resolve("negative/noise").listFiles { file -> file.extension == "wav" }?.size)
        } finally {
            root.deleteRecursively()
        }
    }

    private fun tempRoot(): File = File("build/test-voice-tuning-${System.nanoTime()}")

    private fun samplePcm(): ShortArray = ShortArray(VoiceTuningStore.SAMPLE_RATE_HZ / 10) { 42 }
}
