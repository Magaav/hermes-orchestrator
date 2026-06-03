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
        "native.capabilities",
        "native.install_status",
    )

    val inboundEvents = listOf(
        "native.configure",
        "native.enable_standby",
        "native.disable_standby",
        "native.request_status",
        "native.revoke_device",
    )
}
