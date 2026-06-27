export const moduleDefinition = {
  id: "speech-transcription",
  title: "Speech Transcription",
  status: "lazy local ASR",
  detail: "Adds on-demand microphone transcription for the embedded chat composer through a worker-owned local Transformers.js/WebGPU/WASM pipeline.",
  defaultEnabled: true,
  firmware: "/modules/speech-transcription/speech-transcription.js",
  worker: "/modules/speech-transcription/speech-transcription-worker.js",
  metadata: "/modules/speech-transcription/models/english-v1/metadata.json",
  analyzer: {
    kind: "audio",
    mode: "lazy-worker",
    cache: "immutable versioned SHA assets",
    evidence: "transcript",
    default_engine: "transformers.js",
    acceleration: ["webgpu", "wasm"],
    browser_speech_recognition: "disabled",
  },
};
