package com.colmeio.wasmagent.voice

import kotlin.math.sqrt

class StubWakeWordEngine : WakeWordEngine {
    override val name: String = "StubWakeWordEngine(test-only)"
    override val ready: Boolean = true

    override fun processPcm16(samples: ShortArray, sampleRateHz: Int): WakeWordResult {
        val rms = if (samples.isEmpty()) {
            0.0
        } else {
            sqrt(samples.map { it.toDouble() * it.toDouble() }.average()) / Short.MAX_VALUE
        }
        return WakeWordResult(detected = rms > 0.18, confidence = rms.coerceIn(0.0, 1.0))
    }
}
