import {
  createTranscriptDraftController,
  DEFAULT_TRANSCRIPT_DEBOUNCE_MS,
} from "./transcript-draft.js";

export const SPEECH_TRANSCRIPTION_STATES = Object.freeze([
  "idle",
  "requesting-permission",
  "loading-model",
  "listening",
  "quiet",
  "transcribing",
  "error",
  "unsupported",
]);

const ACTIVE_STATES = new Set(["requesting-permission", "loading-model", "listening", "quiet", "transcribing"]);
const DEFAULT_METADATA_URL = "/modules/speech-transcription/models/english-v1/metadata.json";
const DEFAULT_CAPTURE_WORKLET_PATH = "./speech-capture-worklet.js";
const DEFAULT_TARGET_SAMPLE_RATE = 16000;
const DEFAULT_IDLE_TIMEOUT_MS = 15000;
const DEFAULT_VAD_RMS_THRESHOLD = 0.015;
const DEFAULT_SCRIPT_PROCESSOR_SIZE = 4096;
const DEFAULT_WORKLET_FRAME_MS = 32;

function clamp(value, min, max) {
  const number = Number(value);
  if (!Number.isFinite(number)) return min;
  return Math.max(min, Math.min(max, number));
}

function errorMessage(error) {
  return error?.message || String(error || "Unknown error");
}

function shaLooksValid(value) {
  return /^[a-f0-9]{64}$/i.test(String(value || ""));
}

export function validateSpeechModelMetadata(metadata = {}) {
  const errors = [];
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    return { ok: false, errors: ["metadata must be an object"] };
  }
  if (metadata.schemaVersion !== 1) errors.push("schemaVersion must be 1");
  if (!metadata.id || typeof metadata.id !== "string") errors.push("id is required");
  if (!metadata.version || typeof metadata.version !== "string") errors.push("version is required");
  if (!Array.isArray(metadata.languageTags) || !metadata.languageTags.includes("en")) {
    errors.push("languageTags must include en");
  }
  if (!metadata.engine || typeof metadata.engine !== "object") errors.push("engine is required");
  if (!metadata.model || typeof metadata.model !== "object") errors.push("model is required");
  if (!Number.isFinite(Number(metadata.model?.sizeBytes)) || Number(metadata.model?.sizeBytes) <= 0) {
    errors.push("model.sizeBytes must be a positive number");
  }
  if (!shaLooksValid(metadata.model?.sha256)) errors.push("model.sha256 must be a 64 character hex digest");
  if (!metadata.cachePolicy || metadata.cachePolicy.kind !== "immutable-versioned-sha") {
    errors.push("cachePolicy.kind must be immutable-versioned-sha");
  }
  const assets = Array.isArray(metadata.assets) ? metadata.assets : [];
  if (!assets.length) errors.push("assets must list versioned runtime/model artifacts");
  assets.forEach((asset, index) => {
    if (!asset || typeof asset !== "object") {
      errors.push(`assets[${index}] must be an object`);
      return;
    }
    if (!asset.url || typeof asset.url !== "string" || !asset.url.startsWith("/modules/speech-transcription/")) {
      errors.push(`assets[${index}].url must be a static speech-transcription path`);
    }
    if (!Number.isFinite(Number(asset.sizeBytes)) || Number(asset.sizeBytes) < 0) {
      errors.push(`assets[${index}].sizeBytes must be a non-negative number`);
    }
    if (!shaLooksValid(asset.sha256)) errors.push(`assets[${index}].sha256 must be a 64 character hex digest`);
    if (!asset.version || asset.version !== metadata.version) {
      errors.push(`assets[${index}].version must match metadata.version`);
    }
  });
  if (metadata.engine?.name !== "transformers.js") errors.push("engine.name must be transformers.js for english-v1");
  if (!metadata.engine?.acceleration?.includes("webgpu")) errors.push("engine.acceleration must include webgpu");
  if (!metadata.engine?.fallbacks?.includes("wasm")) errors.push("engine.fallbacks must include wasm");
  const decode = metadata.engine?.decode;
  if (!decode || typeof decode !== "object" || Array.isArray(decode)) {
    errors.push("engine.decode must declare speech transcription decode knobs");
  } else {
    if (!Number.isFinite(Number(decode.finalNumBeams)) || Number(decode.finalNumBeams) < 1) {
      errors.push("engine.decode.finalNumBeams must be a positive number");
    }
    if (!Number.isFinite(Number(decode.partialNumBeams)) || Number(decode.partialNumBeams) < 1) {
      errors.push("engine.decode.partialNumBeams must be a positive number");
    }
    if (!Number.isFinite(Number(decode.temperature)) || Number(decode.temperature) < 0) {
      errors.push("engine.decode.temperature must be a non-negative number");
    }
    if (typeof decode.doSample !== "boolean") errors.push("engine.decode.doSample must be boolean");
    if (!Number.isFinite(Number(decode.maxTokensPerSecond)) || Number(decode.maxTokensPerSecond) <= 0) {
      errors.push("engine.decode.maxTokensPerSecond must be a positive number");
    }
    if (!Number.isFinite(Number(decode.maxNewTokensBase)) || Number(decode.maxNewTokensBase) < 0) {
      errors.push("engine.decode.maxNewTokensBase must be a non-negative number");
    }
    if (!Number.isFinite(Number(decode.partialMaxNewTokens)) || Number(decode.partialMaxNewTokens) <= 0) {
      errors.push("engine.decode.partialMaxNewTokens must be a positive number");
    }
    if (!Number.isFinite(Number(decode.finalMaxNewTokens)) || Number(decode.finalMaxNewTokens) <= 0) {
      errors.push("engine.decode.finalMaxNewTokens must be a positive number");
    }
    if (typeof decode.streamPartialText !== "boolean") errors.push("engine.decode.streamPartialText must be boolean");
    if (!Number.isFinite(Number(decode.streamEmitEveryMs)) || Number(decode.streamEmitEveryMs) <= 0) {
      errors.push("engine.decode.streamEmitEveryMs must be a positive number");
    }
    if (typeof decode.warmupOnLoad !== "boolean") errors.push("engine.decode.warmupOnLoad must be boolean");
    if (!Number.isFinite(Number(decode.warmupAudioMs)) || Number(decode.warmupAudioMs) <= 0) {
      errors.push("engine.decode.warmupAudioMs must be a positive number");
    }
    if (!Number.isFinite(Number(decode.warmupMaxNewTokens)) || Number(decode.warmupMaxNewTokens) <= 0) {
      errors.push("engine.decode.warmupMaxNewTokens must be a positive number");
    }
  }
  if (!metadata.engine?.onnxRuntime?.wasmPaths?.mjs || !metadata.engine?.onnxRuntime?.wasmPaths?.wasm) {
    errors.push("engine.onnxRuntime.wasmPaths must include local mjs and wasm paths");
  }
  if (metadata.engine?.browserSpeechRecognition === true) {
    errors.push("browser SpeechRecognition is not a production ASR engine");
  }
  const audio = metadata.audio;
  if (!audio || typeof audio !== "object" || Array.isArray(audio)) {
    errors.push("audio must declare speech capture/VAD policy");
  } else {
    if (!Number.isFinite(Number(audio.sampleRate)) || Number(audio.sampleRate) <= 0) {
      errors.push("audio.sampleRate must be a positive number");
    }
    if (!Number.isFinite(Number(audio.vadRmsThreshold)) || Number(audio.vadRmsThreshold) <= 0) {
      errors.push("audio.vadRmsThreshold must be a positive number");
    }
    if (!Number.isFinite(Number(audio.workletFrameMs)) || Number(audio.workletFrameMs) <= 0) {
      errors.push("audio.workletFrameMs must be a positive number");
    }
    if (typeof audio.vadAdaptiveNoise !== "boolean") errors.push("audio.vadAdaptiveNoise must be boolean");
    if (!Number.isFinite(Number(audio.vadNoiseFloorRms)) || Number(audio.vadNoiseFloorRms) < 0) {
      errors.push("audio.vadNoiseFloorRms must be a non-negative number");
    }
    if (!Number.isFinite(Number(audio.vadNoiseFloorAlpha)) || Number(audio.vadNoiseFloorAlpha) <= 0 || Number(audio.vadNoiseFloorAlpha) > 1) {
      errors.push("audio.vadNoiseFloorAlpha must be in (0, 1]");
    }
    if (!Number.isFinite(Number(audio.vadStartRatio)) || Number(audio.vadStartRatio) < 1) {
      errors.push("audio.vadStartRatio must be >= 1");
    }
    if (!Number.isFinite(Number(audio.vadHoldRatio)) || Number(audio.vadHoldRatio) < 1) {
      errors.push("audio.vadHoldRatio must be >= 1");
    }
    if (!Number.isFinite(Number(audio.vadMinStartRms)) || Number(audio.vadMinStartRms) < 0) {
      errors.push("audio.vadMinStartRms must be a non-negative number");
    }
    if (!Number.isFinite(Number(audio.vadMinHoldRms)) || Number(audio.vadMinHoldRms) < 0) {
      errors.push("audio.vadMinHoldRms must be a non-negative number");
    }
    if (!Number.isFinite(Number(audio.vadHangoverMs)) || Number(audio.vadHangoverMs) < 0) {
      errors.push("audio.vadHangoverMs must be a non-negative number");
    }
    if (!Number.isFinite(Number(audio.minSegmentMs)) || Number(audio.minSegmentMs) <= 0) {
      errors.push("audio.minSegmentMs must be a positive number");
    }
    if (!Number.isFinite(Number(audio.quietAfterMs)) || Number(audio.quietAfterMs) <= 0) {
      errors.push("audio.quietAfterMs must be a positive number");
    }
    if (!Number.isFinite(Number(audio.partialEveryMs)) || Number(audio.partialEveryMs) <= 0) {
      errors.push("audio.partialEveryMs must be a positive number");
    }
    if (!Number.isFinite(Number(audio.preRollMs)) || Number(audio.preRollMs) < 0) {
      errors.push("audio.preRollMs must be a non-negative number");
    }
    if (!Number.isFinite(Number(audio.partialWindowMs)) || Number(audio.partialWindowMs) <= 0) {
      errors.push("audio.partialWindowMs must be a positive number");
    }
    if (!Number.isFinite(Number(audio.partialOverlapMs)) || Number(audio.partialOverlapMs) < 0) {
      errors.push("audio.partialOverlapMs must be a non-negative number");
    }
    if (!Number.isFinite(Number(audio.partialCooldownMs)) || Number(audio.partialCooldownMs) < 0) {
      errors.push("audio.partialCooldownMs must be a non-negative number");
    }
    if (!Number.isFinite(Number(audio.minPartialWindowMs)) || Number(audio.minPartialWindowMs) <= 0) {
      errors.push("audio.minPartialWindowMs must be a positive number");
    }
    if (
      Number.isFinite(Number(audio.minPartialWindowMs))
      && Number.isFinite(Number(audio.partialWindowMs))
      && Number(audio.minPartialWindowMs) > Number(audio.partialWindowMs)
    ) {
      errors.push("audio.minPartialWindowMs must be <= audio.partialWindowMs");
    }
    if (!Number.isFinite(Number(audio.partialWindowStepMs)) || Number(audio.partialWindowStepMs) <= 0) {
      errors.push("audio.partialWindowStepMs must be a positive number");
    }
    if (!Number.isFinite(Number(audio.partialBackpressureRtf)) || Number(audio.partialBackpressureRtf) <= 0) {
      errors.push("audio.partialBackpressureRtf must be a positive number");
    }
    if (!Number.isFinite(Number(audio.partialRecoveryRtf)) || Number(audio.partialRecoveryRtf) <= 0) {
      errors.push("audio.partialRecoveryRtf must be a positive number");
    }
    if (!Number.isFinite(Number(audio.partialCooldownMaxMs)) || Number(audio.partialCooldownMaxMs) < Number(audio.partialCooldownMs || 0)) {
      errors.push("audio.partialCooldownMaxMs must be >= audio.partialCooldownMs");
    }
  }
  return { ok: errors.length === 0, errors };
}

function dispatchDiagnostic(callback, detail = {}) {
  callback?.({
    timestamp: new Date().toISOString(),
    ...detail,
  });
}

function applyButtonState(button, state, level = 0) {
  if (!button) return;
  const active = ACTIVE_STATES.has(state);
  const cleanLevel = clamp(level, 0, 1);
  button.dataset.speechState = state;
  button.style?.setProperty?.("--agent-speech-level", String(cleanLevel));
  button.style?.setProperty?.("--agent-speech-opacity", String(0.18 + cleanLevel * 0.36));
  button.style?.setProperty?.("--agent-speech-scale", String(0.82 + cleanLevel * 0.28));
  button.classList?.toggle?.("is-active", active);
  button.classList?.toggle?.("is-listening", state === "listening");
  button.classList?.toggle?.("is-quiet", state === "quiet");
  button.classList?.toggle?.("is-loading", state === "requesting-permission" || state === "loading-model");
  button.classList?.toggle?.("is-transcribing", state === "transcribing");
  button.classList?.toggle?.("is-error", state === "error" || state === "unsupported");
  button.setAttribute?.("aria-pressed", active ? "true" : "false");
  const titles = {
    idle: "Start voice input",
    "requesting-permission": "Requesting microphone",
    "loading-model": "Loading local speech model",
    listening: "Stop voice input",
    quiet: "Stop voice input",
    transcribing: "Transcribing locally",
    error: "Voice input error",
    unsupported: "Voice input unsupported",
  };
  button.title = titles[state] || titles.idle;
  button.setAttribute?.("aria-label", button.title);
}

function resolveAudioContextClass(options = {}) {
  return options.AudioContextClass
    || globalThis.AudioContext
    || globalThis.webkitAudioContext
    || null;
}

function resolveAudioWorkletNodeClass(options = {}) {
  return options.AudioWorkletNodeClass
    || globalThis.AudioWorkletNode
    || null;
}

function createDefaultWorker() {
  return new Worker(new URL("./speech-transcription-worker.js", import.meta.url), {
    type: "module",
    name: "wasm-agent-speech-transcription",
  });
}

function rmsForBuffer(buffer) {
  if (!buffer?.length) return 0;
  let sum = 0;
  for (let index = 0; index < buffer.length; index += 1) {
    const sample = Number(buffer[index]) || 0;
    sum += sample * sample;
  }
  return Math.sqrt(sum / buffer.length);
}

export function createSpeechTranscriber(options = {}) {
  const textarea = options.textarea;
  if (!textarea) throw new Error("createSpeechTranscriber requires a textarea.");
  const button = options.button || null;
  const draft = createTranscriptDraftController({
    textarea,
    composer: options.composer,
    debounceMs: Number.isFinite(options.transcriptDebounceMs)
      ? options.transcriptDebounceMs
      : DEFAULT_TRANSCRIPT_DEBOUNCE_MS,
  });
  const metadataUrl = options.metadataUrl || DEFAULT_METADATA_URL;
  const language = options.language || "en";
  const idleTimeoutMs = Number.isFinite(options.idleTimeoutMs)
    ? Math.max(0, options.idleTimeoutMs)
    : DEFAULT_IDLE_TIMEOUT_MS;
  const vadRmsThreshold = Number.isFinite(options.vadRmsThreshold)
    ? Math.max(0, options.vadRmsThreshold)
    : DEFAULT_VAD_RMS_THRESHOLD;
  const targetSampleRate = Number.isFinite(options.targetSampleRate)
    ? clamp(options.targetSampleRate, 8000, 48000)
    : DEFAULT_TARGET_SAMPLE_RATE;
  const audioBufferSize = Number.isFinite(options.audioBufferSize)
    ? Math.max(256, options.audioBufferSize)
    : DEFAULT_SCRIPT_PROCESSOR_SIZE;
  const workletFrameMs = Number.isFinite(options.workletFrameMs)
    ? clamp(options.workletFrameMs, 10, 96)
    : DEFAULT_WORKLET_FRAME_MS;

  let state = "idle";
  let destroyed = false;
  let starting = null;
  let stream = null;
  let audioContext = null;
  let sourceNode = null;
  let workletNode = null;
  let processorNode = null;
  let silenceGain = null;
  let worker = null;
  let workerReady = false;
  let workerIdleTimer = 0;
  let latestLevel = 0;
  let levelFrame = 0;

  function emitState(nextState, detail = {}) {
    if (destroyed && nextState !== "idle") return;
    if (!SPEECH_TRANSCRIPTION_STATES.includes(nextState)) return;
    state = nextState;
    applyButtonState(button, state, latestLevel);
    options.onStateChange?.({ state, ...detail });
  }

  function emitError(error, context = "") {
    const message = errorMessage(error);
    emitState(context === "unsupported" ? "unsupported" : "error", { error: message, context });
    options.onError?.({ error: message, context });
    dispatchDiagnostic(options.onDiagnostic, { type: "error", context, error: message });
  }

  function postWorker(message, transfer = []) {
    try {
      worker?.postMessage?.(message, transfer);
    } catch (error) {
      emitError(error, "worker_post_message");
    }
  }

  function clearWorkerIdleTimer() {
    if (!workerIdleTimer) return;
    globalThis.clearTimeout?.(workerIdleTimer);
    workerIdleTimer = 0;
  }

  function terminateWorker() {
    clearWorkerIdleTimer();
    worker?.terminate?.();
    worker = null;
    workerReady = false;
  }

  function scheduleWorkerIdleTermination() {
    clearWorkerIdleTimer();
    if (!worker) return;
    if (idleTimeoutMs <= 0) {
      terminateWorker();
      return;
    }
    workerIdleTimer = globalThis.setTimeout?.(() => terminateWorker(), idleTimeoutMs) || 0;
  }

  function handleWorkerMessage(event) {
    const data = event?.data || {};
    if (data.type === "state") {
      if (data.state === "ready") {
        workerReady = true;
        if (stream || state === "loading-model") {
          emitState("quiet", { engine: data.engine || "" });
        } else {
          applyButtonState(button, state, latestLevel);
        }
        dispatchDiagnostic(options.onDiagnostic, { type: "ready", engine: data.engine || "", metadata: data.metadata || null });
        return;
      }
      if (SPEECH_TRANSCRIPTION_STATES.includes(data.state)) {
        emitState(data.state, data);
      }
      return;
    }
    if (data.type === "transcript") {
      const result = draft.applyTranscript({
        text: data.text,
        final: Boolean(data.final),
        immediate: Boolean(data.final),
      });
      options.onTranscript?.({
        text: data.text || "",
        final: Boolean(data.final),
        language: data.language || language,
        transcript: result.transcript,
      });
      return;
    }
    if (data.type === "diagnostic") {
      dispatchDiagnostic(options.onDiagnostic, data);
      return;
    }
    if (data.type === "error") {
      void stopCaptureForError();
      emitError(data.error || "speech_transcription_worker_error", data.context || "worker");
    }
  }

  function ensureWorker() {
    clearWorkerIdleTimer();
    if (worker) return worker;
    worker = options.workerFactory ? options.workerFactory() : createDefaultWorker();
    worker.onmessage = handleWorkerMessage;
    worker.onerror = (event) => {
      void stopCaptureForError();
      emitError(event?.message || event, "worker");
    };
    workerReady = false;
    postWorker({
      type: "init",
      metadataUrl,
      language,
      vad: {
        rmsThreshold: vadRmsThreshold,
        vadAdaptiveNoise: options.vadAdaptiveNoise,
        vadNoiseFloorRms: options.vadNoiseFloorRms,
        vadNoiseFloorAlpha: options.vadNoiseFloorAlpha,
        vadStartRatio: options.vadStartRatio,
        vadHoldRatio: options.vadHoldRatio,
        vadMinStartRms: options.vadMinStartRms,
        vadMinHoldRms: options.vadMinHoldRms,
        vadHangoverMs: options.vadHangoverMs,
        quietAfterMs: options.quietAfterMs,
        minSegmentMs: options.minSegmentMs,
        partialEveryMs: options.partialEveryMs,
        maxSegmentMs: options.maxSegmentMs,
        preRollMs: options.preRollMs,
        partialWindowMs: options.partialWindowMs,
        partialOverlapMs: options.partialOverlapMs,
        partialCooldownMs: options.partialCooldownMs,
      },
    });
    return worker;
  }

  function updateAudioLevel(rms) {
    latestLevel = clamp(rms / Math.max(vadRmsThreshold * 3, 0.001), 0, 1);
    if (!globalThis.requestAnimationFrame) {
      applyButtonState(button, state, latestLevel);
      return;
    }
    if (levelFrame) return;
    levelFrame = globalThis.requestAnimationFrame(() => {
      levelFrame = 0;
      applyButtonState(button, state, latestLevel);
    });
  }

  function disconnectAudio() {
    try {
      if (workletNode?.port) {
        workletNode.port.onmessage = null;
        workletNode.port.close?.();
      }
      workletNode?.disconnect?.();
      processorNode && (processorNode.onaudioprocess = null);
      processorNode?.disconnect?.();
      sourceNode?.disconnect?.();
      silenceGain?.disconnect?.();
    } catch {
      // Audio node cleanup is best effort across browser engines.
    }
    workletNode = null;
    processorNode = null;
    sourceNode = null;
    silenceGain = null;
  }

  async function closeAudioContext() {
    const context = audioContext;
    audioContext = null;
    try {
      if (context?.state !== "closed") await context?.close?.();
    } catch {
      // Closing can reject if the browser already tore the graph down.
    }
  }

  function stopStream() {
    const activeStream = stream;
    stream = null;
    activeStream?.getTracks?.().forEach((track) => track.stop?.());
  }

  async function stopCaptureForError() {
    stopStream();
    disconnectAudio();
    await closeAudioContext();
    latestLevel = 0;
    if (levelFrame) {
      globalThis.cancelAnimationFrame?.(levelFrame);
      levelFrame = 0;
    }
    terminateWorker();
  }

  function handleCapturedAudio(audio, rms, captureEngine = "script-processor") {
    updateAudioLevel(rms);
    if (workerReady && (state === "quiet" || state === "listening")) {
      emitState(rms >= vadRmsThreshold ? "listening" : "quiet", { rms });
    }
    postWorker({
      type: "audio",
      sampleRate: audioContext?.sampleRate || 48000,
      rms,
      captureEngine,
      audio,
    }, [audio.buffer]);
  }

  async function setupAudioWorkletCapture() {
    if (options.disableAudioWorklet) return false;
    const AudioWorkletNodeClass = resolveAudioWorkletNodeClass(options);
    if (!audioContext?.audioWorklet?.addModule || !AudioWorkletNodeClass) return false;
    try {
      const workletUrl = options.audioWorkletUrl || new URL(DEFAULT_CAPTURE_WORKLET_PATH, import.meta.url);
      await audioContext.audioWorklet.addModule(String(workletUrl));
      const targetFrameCount = Math.max(128, Math.round(((audioContext.sampleRate || targetSampleRate) * workletFrameMs) / 1000));
      workletNode = new AudioWorkletNodeClass(audioContext, "wasm-agent-speech-capture", {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [1],
        processorOptions: { targetFrameCount },
      });
      workletNode.port.onmessage = (event) => {
        if (destroyed || !stream) return;
        const data = event?.data || {};
        const audio = data.audio instanceof Float32Array ? data.audio : new Float32Array(data.audio || []);
        if (!audio.length) return;
        handleCapturedAudio(audio, Number(data.rms || 0), "audio-worklet");
      };
      sourceNode.connect(workletNode);
      workletNode.connect(silenceGain);
      silenceGain.connect(audioContext.destination);
      dispatchDiagnostic(options.onDiagnostic, {
        type: "diagnostic",
        event: "audio_capture_engine",
        engine: "audio-worklet",
        sampleRate: audioContext.sampleRate || 0,
        frameMs: workletFrameMs,
        targetFrameCount,
      });
      return true;
    } catch (error) {
      try {
        workletNode?.disconnect?.();
        workletNode?.port?.close?.();
      } catch {
        // Worklet fallback cleanup is best effort.
      }
      workletNode = null;
      dispatchDiagnostic(options.onDiagnostic, {
        type: "diagnostic",
        event: "audio_worklet_capture_fallback",
        error: errorMessage(error),
      });
      return false;
    }
  }

  function setupScriptProcessorCapture() {
    processorNode = audioContext.createScriptProcessor(audioBufferSize, 1, 1);
    processorNode.onaudioprocess = (event) => {
      if (destroyed || !stream) return;
      const source = event.inputBuffer?.getChannelData?.(0);
      if (!source) return;
      const audio = new Float32Array(source);
      handleCapturedAudio(audio, rmsForBuffer(audio), "script-processor");
    };
    sourceNode.connect(processorNode);
    processorNode.connect(silenceGain);
    silenceGain.connect(audioContext.destination);
    dispatchDiagnostic(options.onDiagnostic, {
      type: "diagnostic",
      event: "audio_capture_engine",
      engine: "script-processor",
      sampleRate: audioContext.sampleRate || 0,
      bufferSize: audioBufferSize,
    });
  }

  async function setupAudioPipeline(mediaStream) {
    const AudioContextClass = resolveAudioContextClass(options);
    if (!AudioContextClass) throw new Error("audio_context_unavailable");
    try {
      audioContext = new AudioContextClass({ latencyHint: "interactive", sampleRate: targetSampleRate });
    } catch (error) {
      dispatchDiagnostic(options.onDiagnostic, {
        type: "diagnostic",
        event: "audio_context_sample_rate_fallback",
        targetSampleRate,
        error: errorMessage(error),
      });
      audioContext = new AudioContextClass({ latencyHint: "interactive" });
    }
    sourceNode = audioContext.createMediaStreamSource(mediaStream);
    silenceGain = audioContext.createGain();
    silenceGain.gain.value = 0;
    if (await setupAudioWorkletCapture()) return;
    setupScriptProcessorCapture();
  }

  function supported() {
    const mediaDevices = options.mediaDevices || globalThis.navigator?.mediaDevices;
    return Boolean(
      mediaDevices?.getUserMedia
      && resolveAudioContextClass(options)
      && (options.workerFactory || globalThis.Worker)
    );
  }

  async function start(startOptions = {}) {
    if (destroyed) return false;
    if (ACTIVE_STATES.has(state)) return true;
    if (starting) return starting;
    if (!supported()) {
      emitError("browser_runtime_unavailable", "unsupported");
      return false;
    }
    starting = (async () => {
      try {
        draft.reset({ baseDraft: textarea.value });
        emitState("requesting-permission");
        const mediaDevices = options.mediaDevices || globalThis.navigator.mediaDevices;
        if (startOptions.mediaStream) {
          stream = startOptions.mediaStream;
        } else {
          stream = await mediaDevices.getUserMedia({
            audio: options.audioConstraints || {
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            },
            video: false,
          });
        }
        await setupAudioPipeline(stream);
        emitState("loading-model");
        ensureWorker();
        postWorker({ type: "start", language });
        await audioContext?.resume?.();
        return true;
      } catch (error) {
        stopStream();
        disconnectAudio();
        await closeAudioContext();
        if (error?.name === "NotAllowedError" || error?.name === "PermissionDeniedError") {
          window.alert("Microphone access is blocked. Please allow it in your browser/site settings (on Android Chrome: tap the lock icon in the address bar → Site settings → Microphone → Allow), then try again.");
        } else if (typeof window !== "undefined" && window.isSecureContext === false) {
          window.alert("Microphone access requires a secure HTTPS connection. Please access this page via HTTPS.");
        }
        emitError(error, error?.name === "NotAllowedError" ? "microphone_permission" : "start");
        return false;
      } finally {
        starting = null;
      }
    })();
    return starting;
  }

  function preload() {
    if (destroyed) return false;
    if (!(options.workerFactory || globalThis.Worker)) return false;
    ensureWorker();
    return true;
  }

  async function stop(optionsForStop = {}) {
    if (starting) await starting.catch(() => false);
    stopStream();
    disconnectAudio();
    await closeAudioContext();
    latestLevel = 0;
    if (levelFrame) {
      globalThis.cancelAnimationFrame?.(levelFrame);
      levelFrame = 0;
    }
    if (worker) {
      postWorker({
        type: "stop",
        flush: optionsForStop.flush !== false,
        reason: optionsForStop.reason || "user",
      });
      scheduleWorkerIdleTermination();
    }
    if (optionsForStop.flush === false) draft.reset({ baseDraft: textarea.value });
    else draft.flush();
    emitState("idle", { reason: optionsForStop.reason || "user" });
    return true;
  }

  async function toggle() {
    return ACTIVE_STATES.has(state) ? stop() : start();
  }

  async function destroy() {
    destroyed = true;
    if (buttonClickHandler) button?.removeEventListener?.("click", buttonClickHandler);
    await stop({ flush: false, reason: "destroy" });
    terminateWorker();
    draft.destroy();
  }

  const buttonClickHandler = options.autoBindButton === false
    ? null
    : (event) => {
        event?.preventDefault?.();
        void toggle();
      };
  if (buttonClickHandler) button?.addEventListener?.("click", buttonClickHandler);
  applyButtonState(button, state, latestLevel);

  return {
    preload,
    start,
    stop,
    toggle,
    destroy,
    get state() {
      return state;
    },
    get transcript() {
      return draft.transcript;
    },
  };
}
