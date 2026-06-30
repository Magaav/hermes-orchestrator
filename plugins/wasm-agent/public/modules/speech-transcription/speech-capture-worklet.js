const DEFAULT_TARGET_FRAME_COUNT = 512;
const MIN_TARGET_FRAME_COUNT = 128;
const MAX_TARGET_FRAME_COUNT = 4096;

class WasmAgentSpeechCaptureProcessor extends AudioWorkletProcessor {
  constructor(options = {}) {
    super();
    const configuredFrameCount = Number(options.processorOptions?.targetFrameCount);
    this.targetFrameCount = Number.isFinite(configuredFrameCount)
      ? Math.max(MIN_TARGET_FRAME_COUNT, Math.min(MAX_TARGET_FRAME_COUNT, Math.round(configuredFrameCount)))
      : DEFAULT_TARGET_FRAME_COUNT;
    this.pending = new Float32Array(this.targetFrameCount);
    this.pendingLength = 0;
    this.pendingSumSquares = 0;
  }

  flush() {
    if (!this.pendingLength) return;
    const audio = this.pendingLength === this.targetFrameCount
      ? this.pending
      : this.pending.slice(0, this.pendingLength);
    const length = this.pendingLength;
    const sumSquares = this.pendingSumSquares;
    this.port.postMessage({
      type: "audio",
      audio,
      rms: Math.sqrt(sumSquares / length),
    }, [audio.buffer]);
    this.pending = new Float32Array(this.targetFrameCount);
    this.pendingLength = 0;
    this.pendingSumSquares = 0;
  }

  process(inputs) {
    const channel = inputs?.[0]?.[0];
    if (!channel?.length) return true;
    let offset = 0;
    while (offset < channel.length) {
      const writable = Math.min(channel.length - offset, this.targetFrameCount - this.pendingLength);
      for (let index = 0; index < writable; index += 1) {
        const sample = Number(channel[offset + index]) || 0;
        this.pending[this.pendingLength + index] = sample;
        this.pendingSumSquares += sample * sample;
      }
      this.pendingLength += writable;
      offset += writable;
      if (this.pendingLength >= this.targetFrameCount) this.flush();
    }
    return true;
  }
}

registerProcessor("wasm-agent-speech-capture", WasmAgentSpeechCaptureProcessor);
