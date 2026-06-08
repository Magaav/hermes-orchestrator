package com.colmeio.wasmagent.voice

class MockHermesWakeWordEngine(
    private val triggerAfterFrames: Int = 3,
) : WakeWordEngine {
    override val name: String = "MockHermesWakeWordEngine(test-only)"
    override val ready: Boolean = true
    private var framesSeen = 0

    override fun processPcm16(samples: ShortArray, sampleRateHz: Int): WakeWordResult {
        if (sampleRateHz != 16_000 || samples.isEmpty()) return WakeWordResult(false, confidence = 0.0)
        framesSeen += 1
        return WakeWordResult(detected = framesSeen == triggerAfterFrames, confidence = if (framesSeen == triggerAfterFrames) 0.99 else 0.0)
    }
}
