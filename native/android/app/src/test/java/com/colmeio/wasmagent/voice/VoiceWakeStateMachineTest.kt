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
    fun wakeConfirmationGateRejectsSingleSpike() {
        val gate = WakeConfirmationGate()

        val decision = gate.observe(
            WakeWordResult(detected = true, confidence = 0.99),
            now = 1_000L,
            requiredFrames = 2,
            windowMs = 700L,
        )

        assertTrue(decision.rawDetected)
        assertFalse(decision.accepted)
        assertFalse(decision.wake.detected)
        assertEquals("wake_confirmation_pending", decision.rejectionReason)
        assertEquals(1, decision.frames)
    }

    @Test
    fun wakeConfirmationGateAcceptsConsecutiveFrames() {
        val gate = WakeConfirmationGate()
        gate.observe(WakeWordResult(detected = true, confidence = 0.93), now = 1_000L, requiredFrames = 2, windowMs = 700L)

        val decision = gate.observe(
            WakeWordResult(detected = true, confidence = 0.97),
            now = 1_120L,
            requiredFrames = 2,
            windowMs = 700L,
        )

        assertTrue(decision.accepted)
        assertTrue(decision.wake.detected)
        assertEquals(2, decision.frames)
        assertEquals(0.97, decision.wake.confidence, 0.0)
    }

    @Test
    fun wakeConfirmationGateExpiresOldCandidate() {
        val gate = WakeConfirmationGate()
        gate.observe(WakeWordResult(detected = true, confidence = 0.96), now = 1_000L, requiredFrames = 2, windowMs = 300L)

        val decision = gate.observe(
            WakeWordResult(detected = true, confidence = 0.98),
            now = 1_500L,
            requiredFrames = 2,
            windowMs = 300L,
        )

        assertFalse(decision.accepted)
        assertFalse(decision.wake.detected)
        assertEquals(1, decision.frames)
        assertEquals(1_500L, decision.candidateStartedAt)
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
        assertEquals("android_native_voice_wake", event.getString("source"))
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
        val model = File("build/test-installed-hermes-${System.nanoTime()}/voice/base_hermes.onnx")
        val missingEngine = OpenWakeWordOnnxEngine(model)
        assertEquals("hermes_wake_model_missing", missingEngine.diagnosticReason)

        val installed = HermesVoiceWakeService.installBundledHermesModelIfPresent(model) { path ->
            assertEquals("voice/base_hermes.onnx", path)
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

        assertEquals(model.path, diagnostics.getString("wake_model_path"))
        assertEquals(OpenWakeWordOnnxEngine.ASSET_BASE_MODEL_PATH, diagnostics.getString("asset_model_path"))
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

    @Test
    fun debugProviderSelectionProducesExpectedVoiceCommandShape() {
        val providers = VoiceProviderSelector.select(
            requestedDebugVoiceMode = true,
            modelReady = false,
            modelMissing = true,
            productionWakeEngine = OpenWakeWordOnnxEngine(File("build/test-debug-missing-${System.nanoTime()}.onnx")),
            productionTranscriber = DebugTranscriber(enabled = false),
            debugAllowed = true,
        )

        val wake = providers.wake.processPcm16(ShortArray(16_000) { 1 }, 16_000)
        val transcript = providers.transcriber.transcribeLiveAfterWake()
        val event = VoiceWakeEvent(
            transcript = transcript.transcript,
            confidence = wake.confidence,
            startedAt = 10,
            endedAt = 20,
            buildId = "test-build",
            sessionId = "debug-session",
        )
        val payload = VoiceCommandRouter().payload(event, providers.transcriber.name)

        assertEquals("debug_stub", providers.vad.name)
        assertEquals("debug_stub", providers.wake.name)
        assertEquals("debug_stub", providers.transcriber.name)
        assertTrue(wake.detected)
        assertEquals(0.99, wake.confidence, 0.0)
        assertEquals("test command", transcript.transcript)
        assertEquals("voice_command", payload.getString("type"))
        assertEquals("android_native_voice_wake", payload.getString("source"))
        assertEquals("hermes", payload.getString("wake_word"))
        assertEquals(0.99, payload.getDouble("wake_confidence"), 0.0)
        assertEquals("test command", payload.getString("transcript"))
        assertEquals("debug_stub", payload.getString("asr_provider"))
    }

    @Test
    fun commandNormalizerStripsVoskUnknownTokenAndRoutesWakeWordOpen() {
        val transcript = "[unk] open wake word"

        assertEquals("open wake word", VoiceCommandNormalizer.normalizeTranscript(transcript))
        assertEquals("open_wake_word", VoiceCommandNormalizer.commandForTranscript(transcript))
        assertEquals("open_wake_word", VoiceCommandNormalizer.commandForTranscript("Hermes, please open the Wake Word"))
        assertEquals("open_wake_word", VoiceCommandNormalizer.commandForTranscript("wake word"))
    }

    @Test
    fun commandNormalizerAcceptsVoskGrammarAliases() {
        assertEquals("open_wake_word", VoiceCommandNormalizer.commandForTranscript("start listener"))
        assertEquals("open_wake_word", VoiceCommandNormalizer.commandForTranscript("listener"))
        assertEquals("stop_listening", VoiceCommandNormalizer.commandForTranscript("stop listener"))
        assertEquals("stop_listening", VoiceCommandNormalizer.commandForTranscript("stop wake word"))
        assertEquals("show_diagnostics", VoiceCommandNormalizer.commandForTranscript("show diagnostics"))
        assertEquals("train_hermes_wake", VoiceCommandNormalizer.commandForTranscript("train Hermes wake"))
        assertEquals("go_home", VoiceCommandNormalizer.commandForTranscript("go home"))
        assertEquals("", VoiceCommandNormalizer.commandForTranscript("open"))
    }

    @Test
    fun voiceCommandPayloadCarriesCanonicalCommand() {
        val command = VoiceCommandNormalizer.commandForTranscript("[unk] open wake word")
        val event = VoiceWakeEvent(
            transcript = "[unk] open wake word",
            command = command,
            confidence = 0.88,
            startedAt = 100,
            endedAt = 200,
            buildId = "test-build",
            sessionId = "route-session",
        )
        val payload = VoiceCommandRouter().payload(event, "VoskOfflineEngine")

        assertEquals("open_wake_word", payload.getString("command"))
        assertEquals("[unk] open wake word", payload.getString("transcript"))
        assertEquals("VoskOfflineEngine", payload.getString("asr_provider"))
    }

    @Test
    fun voiceCommandPayloadPreservesFreeformTranscriptWithoutFalseCommand() {
        val transcript = "can you hear me"
        val command = VoiceCommandNormalizer.commandForTranscript(transcript)
        val event = VoiceWakeEvent(
            transcript = transcript,
            command = command,
            confidence = 0.99,
            startedAt = 300,
            endedAt = 700,
            buildId = "test-build",
            sessionId = "freeform-session",
        )
        val payload = VoiceCommandRouter().payload(event, "AndroidSpeechRecognizer")

        assertEquals("", command)
        assertEquals("hear me", VoiceCommandNormalizer.normalizeTranscript(transcript))
        assertEquals("", payload.getString("command"))
        assertEquals(transcript, payload.getString("transcript"))
        assertEquals("AndroidSpeechRecognizer", payload.getString("asr_provider"))
    }

    @Test
    fun noModelProductionSelectionStaysSafe() {
        val model = File("build/test-provider-missing-${System.nanoTime()}.onnx")
        val providers = VoiceProviderSelector.select(
            requestedDebugVoiceMode = false,
            modelReady = false,
            modelMissing = true,
            productionWakeEngine = OpenWakeWordOnnxEngine(model),
            productionTranscriber = object : TranscriptionEngine {
                override val name: String = "prod_transcriber_stub"
                override fun transcribePcm16(samples: ShortArray, sampleRateHz: Int, timeoutMs: Long): TranscriptionResult =
                    TranscriptionResult("", 0.0, "not_used")
            },
            debugAllowed = false,
        )

        assertFalse(providers.debugVoiceModeEnabled)
        assertEquals("none", providers.modelSource)
        assertFalse(providers.wake.ready)
        assertFalse(providers.wake.processPcm16(ShortArray(16_000) { 12_000 }, 16_000).detected)
    }

    @Test
    fun debugProvidersAreBlockedWhenDebugNotAllowed() {
        val model = File("build/test-release-blocked-${System.nanoTime()}.onnx")
        val productionTranscriber = object : TranscriptionEngine {
            override val name: String = "prod_transcriber_stub"
            override fun transcribePcm16(samples: ShortArray, sampleRateHz: Int, timeoutMs: Long): TranscriptionResult =
                TranscriptionResult("", 0.0, "not_used")
        }
        val providers = VoiceProviderSelector.select(
            requestedDebugVoiceMode = true,
            modelReady = false,
            modelMissing = true,
            productionWakeEngine = OpenWakeWordOnnxEngine(model),
            productionTranscriber = productionTranscriber,
            debugAllowed = false,
        )

        assertFalse(providers.debugVoiceModeEnabled)
        assertFalse(providers.wake.name == "debug_stub")
        assertFalse(providers.transcriber.name == "debug_stub")
        assertFalse(providers.wake.ready)
    }

    @Test
    fun wakeModelSelectorReportsNoneWhenNoModelExists() {
        val root = File("build/test-selector-none-${System.nanoTime()}")
        val selection = WakeModelSelector.select(
            File(root, "voice/hermes.onnx"),
            File(root, "voice/base_hermes.onnx"),
        )

        assertEquals("none", selection.source)
        assertFalse(selection.ready)
        assertFalse(selection.personalizedModelExists)
        assertFalse(selection.baseModelExists)
        assertEquals("none", selection.engine.diagnostics().getString("model_source"))
        assertEquals("hermes_wake_model_missing", selection.engine.diagnosticReason)
    }

    @Test
    fun wakeModelSelectorRecognizesOpenWakeWordBundleCandidate() {
        val root = File("build/test-selector-openwakeword-${System.nanoTime()}")
        val bundle = File(root, "voice/openwakeword")
        bundle.mkdirs()
        File(bundle, "melspectrogram.onnx").writeText("not an onnx mel model")
        File(bundle, "embedding_model.onnx").writeText("not an onnx embedding model")
        File(bundle, "hey_jarvis.onnx").writeText("not an onnx classifier model")
        try {
            val selection = WakeModelSelector.select(
                File(root, "voice/hermes.onnx"),
                File(root, "voice/base_hermes.onnx"),
            )

            assertTrue(selection.openWakeWordBundleExists)
            assertEquals("openwakeword_bundle", selection.attempted[0].diagnostics().getString("model_source"))
            assertEquals("openwakeword_bundle_load_error", selection.attempted[0].diagnosticReason)
            assertEquals("none", selection.source)
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun wakeModelSelectorAttemptsPersonalizedBeforeBaseAndFallsBackSafely() {
        val root = File("build/test-selector-priority-${System.nanoTime()}")
        val personalized = File(root, "voice/hermes.onnx")
        val base = File(root, "voice/base_hermes.onnx")
        personalized.parentFile?.mkdirs()
        personalized.writeText("not an onnx personalized model")
        base.writeText("not an onnx base model")
        try {
            val selection = WakeModelSelector.select(personalized, base)

            assertEquals("none", selection.source)
            assertFalse(selection.ready)
            assertTrue(selection.personalizedModelExists)
            assertTrue(selection.baseModelExists)
            assertEquals("personalized", selection.attempted[0].diagnostics().getString("model_source"))
            assertEquals("base", selection.attempted[1].diagnostics().getString("model_source"))
            assertEquals("none", selection.engine.diagnostics().getString("model_source"))
            assertFalse(selection.engine.diagnostics().getBoolean("wake_engine_ready"))
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun bundledBaseModelCopyDoesNotOverwritePersonalizedModel() {
        val root = File("build/test-base-copy-${System.nanoTime()}")
        val personalized = File(root, "voice/hermes.onnx")
        val base = File(root, "voice/base_hermes.onnx")
        personalized.parentFile?.mkdirs()
        personalized.writeText("personalized")

        val installed = HermesVoiceWakeService.installBundledHermesModelIfPresent(base) { path ->
            assertEquals("voice/base_hermes.onnx", path)
            ByteArrayInputStream("base".toByteArray())
        }

        assertTrue(installed)
        assertEquals("personalized", personalized.readText())
        assertEquals("base", base.readText())
        root.deleteRecursively()
    }

    @Test
    fun bundledBaseModelCopyRefreshesStaleBaseOnly() {
        val root = File("build/test-base-copy-stale-${System.nanoTime()}")
        val base = File(root, "voice/base_hermes.onnx")
        base.parentFile?.mkdirs()
        base.writeText("old")

        val installed = HermesVoiceWakeService.installBundledHermesModelIfPresent(base) {
            ByteArrayInputStream("new-base".toByteArray())
        }

        assertTrue(installed)
        assertEquals("new-base", base.readText())
        root.deleteRecursively()
    }

    @Test
    fun failedModelLoadDiagnosticsDoNotClaimReadiness() {
        val root = File("build/test-failed-load-diagnostics-${System.nanoTime()}")
        val base = File(root, "voice/base_hermes.onnx")
        base.parentFile?.mkdirs()
        base.writeText("not an onnx base model")
        try {
            val selection = WakeModelSelector.select(File(root, "voice/hermes.onnx"), base)
            val diagnostics = selection.attempted[0].diagnostics()

            assertEquals("base", diagnostics.getString("model_source"))
            assertEquals("model_load_error", diagnostics.getString("last_model_load_result"))
            assertFalse(diagnostics.getBoolean("wake_engine_ready"))
            assertEquals("none", selection.source)
        } finally {
            root.deleteRecursively()
        }
    }
}
