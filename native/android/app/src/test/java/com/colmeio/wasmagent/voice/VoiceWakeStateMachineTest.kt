package com.colmeio.wasmagent.voice

import com.colmeio.wasmagent.HermesVoiceWakeService
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.File

class VoiceWakeStateMachineTest {
    @Test
    fun fakePcmSilenceDoesNotWake() {
        val engine = StubWakeWordEngine()
        val silence = ShortArray(16_000) { 0 }

        val result = engine.processPcm16(silence, 16_000)

        assertFalse(result.detected)
    }

    @Test
    fun fakePcmHermesFixtureWakes() {
        val engine = StubWakeWordEngine()
        val hermesFixture = ShortArray(16_000) { index ->
            (if (index % 32 < 16) 12_000 else -12_000).toShort()
        }

        val result = engine.processPcm16(hermesFixture, 16_000)

        assertTrue(result.detected)
        assertTrue(result.confidence > 0.18)
    }

    @Test
    fun mockHermesWakeTriggersExactlyOnce() {
        val engine = MockHermesWakeWordEngine(triggerAfterFrames = 2)
        val frame = ShortArray(1024) { 1200 }

        assertFalse(engine.processPcm16(frame, 16_000).detected)
        assertTrue(engine.processPcm16(frame, 16_000).detected)
        assertFalse(engine.processPcm16(frame, 16_000).detected)
    }

    @Test
    fun silenceDoesNotWake() {
        val machine = VoiceWakeStateMachine()
        machine.enable()

        val woke = machine.onWake(WakeWordResult(detected = false))

        assertFalse(woke)
        assertEquals(VoiceWakeState.LISTENING, machine.state)
    }

    @Test
    fun hermesWakeCapturesAndEmitsTranscriptEvent() {
        val machine = VoiceWakeStateMachine()
        machine.enable()

        assertTrue(machine.onWake(WakeWordResult(detected = true, confidence = 0.9), now = 1234))
        machine.beginTranscribing()
        machine.complete(VoiceWakeEvent(
            transcript = "open my current run logs",
            confidence = 0.82,
            startedAt = 1234,
            endedAt = 2234,
            buildId = "test-build",
            sessionId = "test-session",
        ))

        assertEquals(VoiceWakeState.SENT, machine.state)
        assertEquals("open my current run logs", machine.lastTranscript)
        val event = machine.lastEvent!!.toJson()
        assertEquals("voice_command", event.getString("type"))
        assertEquals("hermes", event.getString("wake_word"))
        assertEquals("android_native_hermes_voice_wake", event.getString("source"))
        assertFalse(event.getBoolean("audio_retained"))
        assertEquals(1000, machine.lastCommandCaptureDurationMs)
        assertEquals("transcribed", machine.lastTranscriptStatus)
    }

    @Test
    fun missingModelCanBeReportedWithoutCrashing() {
        val machine = VoiceWakeStateMachine()
        machine.enable()

        machine.blocked("hermes_wake_model_missing")
        val snapshot = machine.snapshot(
            enabled = true,
            permissionGranted = true,
            foregroundServiceRunning = true,
            wakeEngine = "OpenWakeWordOnnxEngine(model-missing)",
            wakeEngineReady = false,
            transcriptionEngine = "AndroidSpeechRecognizerEngine",
        )

        assertEquals(VoiceWakeState.LISTENING, machine.state)
        assertEquals("hermes_wake_model_missing", snapshot.getString("last_error"))
        assertTrue(snapshot.getBoolean("notification_active"))
    }

    @Test
    fun missingOnnxModelNeverClaimsWake() {
        val model = File("build/test-missing-hermes-${System.nanoTime()}.onnx")
        val engine = OpenWakeWordOnnxEngine(model)

        val result = engine.processPcm16(ShortArray(16_000) { 12_000 }, 16_000)

        assertFalse(engine.ready)
        assertFalse(result.detected)
        assertEquals("hermes_wake_model_missing", engine.diagnosticReason)
        assertEquals("model_missing", engine.diagnostics().getString("wake_model_contract"))
    }

    @Test
    fun incompatibleOnnxModelReportsDeterministicLoadDiagnostic() {
        val model = File("build/test-incompatible-hermes-${System.nanoTime()}.onnx")
        model.parentFile?.mkdirs()
        model.writeText("not an onnx model")
        try {
            val engine = OpenWakeWordOnnxEngine(model)
            val result = engine.processPcm16(ShortArray(OpenWakeWordOnnxEngine.DEFAULT_WINDOW_SAMPLES) { 12_000 }, 16_000)

            assertFalse(engine.ready)
            assertFalse(result.detected)
            assertEquals("hermes_wake_model_load_error", engine.diagnosticReason)
            assertEquals("model_load_error", engine.diagnostics().getString("wake_model_contract"))
            assertTrue(engine.diagnostics().getBoolean("wake_model_exists"))
        } finally {
            model.delete()
        }
    }

    @Test
    fun bundledModelInstallRefreshesAwayFromMissingState() {
        val model = File("build/test-installed-hermes-${System.nanoTime()}/voice/hermes.onnx")
        val missingEngine = OpenWakeWordOnnxEngine(model)
        assertEquals("hermes_wake_model_missing", missingEngine.diagnosticReason)

        val installed = HermesVoiceWakeService.installBundledHermesModelIfPresent(model) { path ->
            assertEquals("voice/hermes.onnx", path)
            ByteArrayInputStream("not an onnx model".toByteArray())
        }
        val refreshedEngine = OpenWakeWordOnnxEngine(model)

        assertTrue(installed)
        assertTrue(model.exists())
        assertEquals("hermes_wake_model_load_error", refreshedEngine.diagnosticReason)
        assertFalse(refreshedEngine.diagnostics().getString("wake_model_contract") == "model_missing")
        model.parentFile?.parentFile?.deleteRecursively()
    }

    @Test
    fun modelContractDiagnosticsAreRepositoryVisible() {
        val model = File("build/test-missing-contract-${System.nanoTime()}.onnx")
        val diagnostics = OpenWakeWordOnnxEngine(model).diagnostics()

        assertEquals(OpenWakeWordOnnxEngine.APP_PRIVATE_MODEL_PATH, diagnostics.getString("wake_model_path"))
        assertEquals(OpenWakeWordOnnxEngine.ASSET_MODEL_PATH, diagnostics.getString("asset_model_path"))
        assertEquals(OpenWakeWordOnnxEngine.INPUT_FORMAT, diagnostics.getString("wake_model_input_format"))
        assertEquals(OpenWakeWordOnnxEngine.SAMPLE_RATE_HZ, diagnostics.getInt("wake_model_sample_rate_hz"))
        assertEquals(OpenWakeWordOnnxEngine.DEFAULT_CONFIDENCE_THRESHOLD, diagnostics.getDouble("wake_model_threshold"), 0.0)
    }

    @Test
    fun noTranscriptEventExistsBeforeWake() {
        val machine = VoiceWakeStateMachine()
        machine.enable()

        machine.beginTranscribing()

        assertEquals(VoiceWakeState.LISTENING, machine.state)
        assertEquals(null, machine.lastEvent)
    }

    @Test
    fun speechFixtureWithoutTranscriptReportsError() {
        val machine = VoiceWakeStateMachine()
        machine.enable()
        machine.onWake(WakeWordResult(detected = true, confidence = 0.7), now = 111)
        machine.beginTranscribing()

        machine.fail("android_speech_recognizer_unavailable")

        assertEquals(VoiceWakeState.ERROR, machine.state)
        assertEquals("android_speech_recognizer_unavailable", machine.lastError)
    }
}
