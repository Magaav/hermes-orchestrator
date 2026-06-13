package com.colmeio.wasmagent

object NativeBridgeContract {
    const val GENERAL_BRIDGE_OBJECT = "wasmAgentNative"
    const val VOICE_TUNING_BRIDGE_OBJECT = "WasmAgentNativeVoiceTuning"

    val voiceTuningMethods = listOf(
        "getStatus",
        "getBuildInfo",
        "isRecordingSupported",
        "stopVoiceTuningSample",
        "startVoiceTuningSample",
        "deleteLastVoiceTuningSample",
        "exportHermesDataset",
        "installHermesWakeModel",
        "getVoiceTuningDiagnostics",
        "beginHermesWakeProof",
        "getHermesWakeProof",
        "voiceTuningStatus",
        "cancelVoiceTuning",
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
