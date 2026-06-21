package com.colmeio.wasmagent

object NativeBridgeContract {
    const val GENERAL_BRIDGE_OBJECT = "wasmAgentNative"
    const val VOICE_TUNING_BRIDGE_OBJECT = "WasmAgentNativeVoiceTuning"
    const val KERNEL_CONTRACT_VERSION = "2026.06.14"

    val allKernelCapabilities = listOf(
        "native.capabilities.runtimeLoader.v1",
        "native.capabilities.hotOps.v1",
        "native.capabilities.statusBus.v1",
        "native.capabilities.diagnostics.v1",
        "native.capabilities.fileStore.v1",
        "native.capabilities.downloadedRuntime.v1",
        "native.capabilities.downloadedOperations.v1",
        "native.capabilities.deviceControl.v1",
        "native.capabilities.audioCapture.v1",
        "native.capabilities.modelRuntime.v1",
        "native.capabilities.foregroundSession.v1",
        "native.capabilities.webViewBridge.v1",
        "native.capabilities.boundedCommand.v1",
        "native.capabilities.auditLog.v1",
        "native.capabilities.releaseFeedValidation.v1",
        "native.capabilities.nativeControlPolling.v1",
        "native.capabilities.crashSafeStatus.v1",
        "native.capabilities.capabilityManifest.v1",
    )

    val androidKernelCapabilities = listOf(
        "native.capabilities.runtimeLoader.v1",
        "native.capabilities.hotOps.v1",
        "native.capabilities.statusBus.v1",
        "native.capabilities.diagnostics.v1",
        "native.capabilities.fileStore.v1",
        "native.capabilities.downloadedRuntime.v1",
        "native.capabilities.downloadedOperations.v1",
        "native.capabilities.audioCapture.v1",
        "native.capabilities.modelRuntime.v1",
        "native.capabilities.foregroundSession.v1",
        "native.capabilities.webViewBridge.v1",
        "native.capabilities.boundedCommand.v1",
        "native.capabilities.auditLog.v1",
        "native.capabilities.releaseFeedValidation.v1",
        "native.capabilities.crashSafeStatus.v1",
        "native.capabilities.capabilityManifest.v1",
    )

    val nativeKernelMethods = listOf(
        "getKernelStatus",
        "syncDownloadedRuntime",
        "forceSyncDownloadedRuntime",
        "rollbackDownloadedRuntime",
        "runDownloadedOperation",
        "getWakeWordState",
    )

    val voiceTuningMethods = listOf(
        "getStatus",
        "getBuildInfo",
        "isRecordingSupported",
        "stopVoiceTuningSample",
        "startVoiceTuningSample",
        "deleteLastVoiceTuningSample",
        "exportHermesDataset",
        "installHermesWakeModel",
        "installOpenWakeWordBundle",
        "playWakePhraseProbe",
        "scoreWakePhraseProbe",
        "getVoiceTuningDiagnostics",
        "beginHermesWakeProof",
        "getHermesWakeProof",
        "voiceTuningStatus",
        "cancelVoiceTuning",
        *nativeKernelMethods.toTypedArray(),
    )

    /*
     * Train Hermes Wake bridge contract:
     *
     * Canonical frontend object:
     *   window.WasmAgentNativeVoiceTuning
     *
     * Compatibility frontend object:
     *   window.wasmAgentNative
     *
     * Frontend methods:
     *   window.WasmAgentNativeVoiceTuning.getStatus()
     *   window.WasmAgentNativeVoiceTuning.getBuildInfo()
     *   window.WasmAgentNativeVoiceTuning.isRecordingSupported()
     *   window.WasmAgentNativeVoiceTuning.startVoiceTuningSample(JSON.stringify(request))
     *   window.WasmAgentNativeVoiceTuning.stopVoiceTuningSample()
     *   window.WasmAgentNativeVoiceTuning.deleteLastVoiceTuningSample(categoryId)
     *   window.WasmAgentNativeVoiceTuning.exportHermesDataset()
     *   window.WasmAgentNativeVoiceTuning.installHermesWakeModel(modelUrl, sha256)
     *   window.WasmAgentNativeVoiceTuning.installOpenWakeWordBundle(bundleUrl, sha256)
     *   window.WasmAgentNativeVoiceTuning.playWakePhraseProbe(JSON.stringify({ phrase: "hey jarvis" }))
     *   window.WasmAgentNativeVoiceTuning.scoreWakePhraseProbe(JSON.stringify({ durationMs: 3500 }))
     *   window.WasmAgentNativeVoiceTuning.getVoiceTuningDiagnostics()
     *
     * Native bridge method:
     *   AndroidVoiceTuningBridge.startVoiceTuningSample(requestJson: String)
     *
     * Request payload:
     *   {
     *     "kind": "hermes" | "silence" | "speech" | "noise",
     *     "label": "positive" | "negative",
     *     "duration_ms": 1000,
     *     "prompt": "...",
     *     "category": "positive" | "negative/silence" | "negative/speech" | "negative/noise",
     *     "source": "..."
     *   }
     *
     * Native result event:
     *   window event "wasm-agent:native-voice-tuning"
     *
     * Success payload:
     *   {
     *     "ok": true,
     *     "type": "voice_tuning_sample_recorded",
     *     "kind": "...",
     *     "label": "...",
     *     "path": "...",
     *     "filename": "...",
     *     "duration_ms": 1000,
     *     "quality": "saved",
     *     "diagnostics": { ... }
     *   }
     *
     * Failure payload:
     *   {
     *     "ok": false,
     *     "type": "voice_tuning_recording_failed",
     *     "kind": "...",
     *     "label": "...",
     *     "error": "permission_denied | recorder_unavailable | too_quiet | too_short | timeout | invalid_wav | native_error",
     *     "message": "Human readable message"
     *   }
     */
    val outboundEvents = listOf(
        "device.register",
        "device.status",
        "device.heartbeat",
        "voice.wake",
        "voice.partial_transcript",
        "voice.final_transcript",
        "voice.error",
        "voice_command",
        "voice_tuning_started",
        "native_record_started",
        "native_record_finished",
        "voice_tuning_sample_recorded",
        "voice_tuning_recording_failed",
        "voice_tuning_sample_deleted",
        "voice_tuning_completed",
        "voice_tuning_counts_updated",
        "voice_tuning_threshold_met",
        "hermes_wake_model_installed",
        "native.capabilities",
        "native.install_status",
    )

    val inboundEvents = listOf(
        "native.configure",
        "native.enable_standby",
        "native.disable_standby",
        "native.enable_voice_wake",
        "native.disable_voice_wake",
        "native.request_status",
        "native.revoke_device",
    )
}
