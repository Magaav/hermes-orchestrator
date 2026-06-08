package com.colmeio.wasmagent

object NativeBridgeContract {
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
        "voice_tuning_sample_recorded",
        "voice_tuning_sample_deleted",
        "voice_tuning_completed",
        "voice_tuning_counts_updated",
        "voice_tuning_threshold_met",
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
