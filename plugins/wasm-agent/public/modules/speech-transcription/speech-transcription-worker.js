import { validateSpeechModelMetadata } from "./speech-transcription.js";
import { normalizeTranscriptText } from "./transcript-draft.js";

const DEFAULT_TARGET_SAMPLE_RATE = 16000;
const DEFAULT_MIN_SEGMENT_MS = 900;
const DEFAULT_PARTIAL_EVERY_MS = 3500;
const DEFAULT_QUIET_AFTER_MS = 700;
const DEFAULT_MAX_SEGMENT_MS = 28000;
const DEFAULT_METADATA_URL = "/modules/speech-transcription/models/english-v1/metadata.json";

let metadata = null;
let pipelineInstance = null;
let loadingPipeline = null;
let language = "en";
let targetSampleRate = DEFAULT_TARGET_SAMPLE_RATE;
let minSegmentMs = DEFAULT_MIN_SEGMENT_MS;
let partialEveryMs = DEFAULT_PARTIAL_EVERY_MS;
let quietAfterMs = DEFAULT_QUIET_AFTER_MS;
let maxSegmentMs = DEFAULT_MAX_SEGMENT_MS;
let rmsThreshold = 0.015;
let segmentChunks = [];
let segmentSampleRate = DEFAULT_TARGET_SAMPLE_RATE;
let segmentMs = 0;
let quietMs = 0;
let busy = false;
let activeTranscription = null;
let lastPartialSegmentMs = 0;
let lastPartialText = "";
let lastPartialCoveredMs = 0;
let nextPartialAllowedAt = 0;

function nowMs() {
  return self.performance?.now?.() || Date.now();
}

function post(type, payload = {}) {
  self.postMessage({ type, ...payload });
}

function diagnostic(payload = {}) {
  post("diagnostic", {
    timestamp: new Date().toISOString(),
    ...payload,
  });
}

async function sha256(buffer) {
  const digest = await self.crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function fetchArrayBuffer(url) {
  const response = await fetch(url, { cache: "reload" });
  if (!response.ok) throw new Error(`asset_fetch_failed:${url}:${response.status}`);
  return {
    buffer: await response.arrayBuffer(),
    response,
  };
}

async function cachedShaMatches(cache, asset) {
  const cached = await cache.match(asset.url);
  if (!cached) return false;
  const buffer = await cached.arrayBuffer();
  const digest = await sha256(buffer);
  if (digest.toLowerCase() !== String(asset.sha256).toLowerCase()) {
    await cache.delete(asset.url);
    diagnostic({ event: "cached_asset_sha_mismatch", url: asset.url, sha256: digest });
    return false;
  }
  diagnostic({ event: "asset_cache_hit", url: asset.url, sizeBytes: buffer.byteLength, sha256: digest });
  return true;
}

async function cacheImmutableAssets(modelMetadata) {
  if (!self.caches || !self.crypto?.subtle) {
    diagnostic({ event: "cache_skipped", reason: "cache_or_crypto_unavailable" });
    return;
  }
  const cacheName = modelMetadata.cachePolicy?.cacheName || `wasm-agent-speech-${modelMetadata.version}`;
  const cache = await self.caches.open(cacheName);
  for (const asset of modelMetadata.assets || []) {
    if (asset.required === false) continue;
    if (await cachedShaMatches(cache, asset)) continue;
    const { buffer, response } = await fetchArrayBuffer(asset.url);
    const digest = await sha256(buffer);
    if (digest.toLowerCase() !== String(asset.sha256).toLowerCase()) {
      throw new Error(`asset_sha_mismatch:${asset.url}`);
    }
    await cache.put(asset.url, new Response(buffer, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers,
    }));
    diagnostic({ event: "asset_cached", url: asset.url, sizeBytes: buffer.byteLength, sha256: digest });
  }
}

async function loadMetadata(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`metadata_fetch_failed:${response.status}`);
  const nextMetadata = await response.json();
  const validation = validateSpeechModelMetadata(nextMetadata);
  if (!validation.ok) {
    throw new Error(`metadata_invalid:${validation.errors.join(",")}`);
  }
  return nextMetadata;
}

function runtimeImportUrl(runtimeUrl, modelMetadata, device, attemptIndex) {
  if (attemptIndex === 0) return runtimeUrl;
  const separator = runtimeUrl.includes("?") ? "&" : "?";
  return `${runtimeUrl}${separator}wa-speech-device=${encodeURIComponent(device)}&wa-speech-version=${encodeURIComponent(modelMetadata.version || "unknown")}`;
}

function runtimeCapabilitySnapshot(modelMetadata = {}) {
  const userAgent = self.navigator?.userAgent || "";
  const ua = userAgent.toLowerCase();
  const wasmPaths = modelMetadata.engine?.onnxRuntime?.wasmPaths || {};
  const wasmPathText = `${wasmPaths.mjs || ""} ${wasmPaths.wasm || ""}`;
  return {
    userAgent,
    android: /\bandroid\b/i.test(userAgent),
    mobile: /\b(android|mobile|mobi)\b/i.test(userAgent),
    webgpu: Boolean(self.navigator?.gpu),
    crossOriginIsolated: Boolean(self.crossOriginIsolated),
    sharedArrayBuffer: typeof self.SharedArrayBuffer !== "undefined",
    threadedOrtWasm: /threaded/i.test(wasmPathText),
    dtype: modelMetadata.engine?.dtype || "",
    wasmMjs: wasmPaths.mjs || "",
    wasm: wasmPaths.wasm || "",
    likelyAndroidWasmFallback: /\bandroid\b/.test(ua) && !self.navigator?.gpu,
  };
}

async function webGpuAdapterAvailable(modelMetadata) {
  if (!modelMetadata.engine?.acceleration?.includes("webgpu")) return false;
  const gpu = self.navigator?.gpu;
  if (!gpu?.requestAdapter) {
    diagnostic({ event: "webgpu_unavailable", reason: "navigator_gpu_missing" });
    return false;
  }
  try {
    const adapter = await gpu.requestAdapter({ powerPreference: "high-performance" });
    if (!adapter) {
      diagnostic({ event: "webgpu_unavailable", reason: "adapter_missing" });
      return false;
    }
    return true;
  } catch (error) {
    diagnostic({ event: "webgpu_unavailable", reason: "request_adapter_failed", error: error?.message || String(error) });
    return false;
  }
}

function configureRuntime(runtime, modelMetadata) {
  const pipeline = runtime.pipeline;
  const env = runtime.env || {};
  if (env) {
    env.allowRemoteModels = false;
    env.allowLocalModels = true;
    env.useBrowserCache = true;
    env.useWasmCache = false;
    env.cacheKey = modelMetadata.cachePolicy?.cacheName || env.cacheKey;
    if (modelMetadata.model?.basePath) env.localModelPath = modelMetadata.model.basePath;
    const wasmPaths = modelMetadata.engine?.onnxRuntime?.wasmPaths;
    if (env.backends?.onnx?.wasm && wasmPaths?.mjs && wasmPaths?.wasm) {
      env.backends.onnx.wasm.wasmPaths = {
        mjs: wasmPaths.mjs,
        wasm: wasmPaths.wasm,
      };
      env.backends.onnx.wasm.proxy = false;
      if (!self.crossOriginIsolated) env.backends.onnx.wasm.numThreads = 1;
    }
  }
  if (typeof pipeline !== "function") throw new Error("transformers_pipeline_unavailable");
  return { pipeline };
}

async function createPipeline(modelMetadata) {
  const runtimeAsset = (modelMetadata.assets || []).find((asset) => asset.kind === "runtime");
  const runtimeUrl = runtimeAsset?.url || modelMetadata.engine?.runtimeUrl;
  if (!runtimeUrl) throw new Error("transformers_runtime_url_missing");
  const runtime = runtimeCapabilitySnapshot(modelMetadata);
  diagnostic({ event: "runtime_capability", runtime });
  await cacheImmutableAssets(modelMetadata);
  const modelId = modelMetadata.model?.id || modelMetadata.id;
  const canUseWebGpu = await webGpuAdapterAvailable(modelMetadata);
  const pipelineOptions = canUseWebGpu ? [{ device: "webgpu" }, { device: "wasm" }] : [{ device: "wasm" }];
  let lastError = null;
  for (const [attemptIndex, options] of pipelineOptions.entries()) {
    try {
      const runtime = await import(runtimeImportUrl(runtimeUrl, modelMetadata, options.device, attemptIndex));
      const { pipeline } = configureRuntime(runtime, modelMetadata);
      const instance = await pipeline(modelMetadata.engine.task || "automatic-speech-recognition", modelId, {
        ...options,
        dtype: modelMetadata.engine?.dtype || "fp16",
        revision: modelMetadata.model?.revision || "main",
        local_files_only: true,
        session_options: {
          executionProviders: [options.device],
          graphOptimizationLevel: modelMetadata.engine?.graphOptimizationLevel || "all",
        },
      });
      diagnostic({ event: "pipeline_ready", engine: "transformers.js", device: options.device });
      return { instance, device: options.device };
    } catch (error) {
      lastError = error;
      diagnostic({ event: "pipeline_init_failed", device: options.device, error: error?.message || String(error), runtime });
    }
  }
  throw lastError || new Error("pipeline_init_failed");
}

async function ensurePipeline(metadataUrl = DEFAULT_METADATA_URL) {
  if (pipelineInstance) return pipelineInstance;
  if (loadingPipeline) return loadingPipeline;
  loadingPipeline = (async () => {
    post("state", { state: "loading-model" });
    metadata = await loadMetadata(metadataUrl);
    targetSampleRate = Number(metadata.audio?.sampleRate || DEFAULT_TARGET_SAMPLE_RATE) || DEFAULT_TARGET_SAMPLE_RATE;
    minSegmentMs = Number(metadata.audio?.minSegmentMs || minSegmentMs) || minSegmentMs;
    partialEveryMs = Number(metadata.audio?.partialEveryMs || partialEveryMs) || partialEveryMs;
    quietAfterMs = Number(metadata.audio?.quietAfterMs || quietAfterMs) || quietAfterMs;
    maxSegmentMs = Number(metadata.audio?.maxSegmentMs || maxSegmentMs) || maxSegmentMs;
    rmsThreshold = Number(metadata.audio?.vadRmsThreshold || rmsThreshold) || rmsThreshold;
    const pipelineResult = await createPipeline(metadata);
    pipelineInstance = pipelineResult.instance;
    post("state", {
      state: "ready",
      engine: "transformers.js",
      metadata: {
        id: metadata.id,
        version: metadata.version,
        model: metadata.model?.id || "",
        device: pipelineResult.device,
      },
    });
    return pipelineInstance;
  })();
  try {
    return await loadingPipeline;
  } finally {
    loadingPipeline = null;
  }
}

function appendAudioChunk(audio, sampleRate, rms) {
  const chunk = audio instanceof Float32Array ? audio : new Float32Array(audio || []);
  if (!chunk.length) return;
  segmentChunks.push(chunk);
  segmentSampleRate = sampleRate || segmentSampleRate || DEFAULT_TARGET_SAMPLE_RATE;
  const chunkMs = (chunk.length / segmentSampleRate) * 1000;
  segmentMs += chunkMs;
  quietMs = rms < rmsThreshold ? quietMs + chunkMs : 0;
  const bufferedSamples = segmentChunks.reduce((sum, item) => sum + item.length, 0);
  const maxSamples = Math.ceil((segmentSampleRate * maxSegmentMs) / 1000);
  if (bufferedSamples > maxSamples) {
    let drop = bufferedSamples - maxSamples;
    while (drop > 0 && segmentChunks.length > 1) {
      const first = segmentChunks[0];
      if (first.length <= drop) {
        segmentChunks.shift();
        drop -= first.length;
      } else {
        segmentChunks[0] = first.slice(drop);
        drop = 0;
      }
    }
    segmentMs = Math.min(segmentMs, maxSegmentMs);
  }
}

function concatChunks(chunks = []) {
  const length = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const merged = new Float32Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  return merged;
}

function resampleLinear(input, sourceRate, outputRate) {
  if (!input.length || sourceRate === outputRate) return input;
  const ratio = sourceRate / outputRate;
  const outputLength = Math.max(1, Math.round(input.length / ratio));
  const output = new Float32Array(outputLength);
  for (let index = 0; index < outputLength; index += 1) {
    const sourceIndex = index * ratio;
    const before = Math.floor(sourceIndex);
    const after = Math.min(input.length - 1, before + 1);
    const weight = sourceIndex - before;
    output[index] = input[before] * (1 - weight) + input[after] * weight;
  }
  return output;
}

function resetSegment() {
  segmentChunks = [];
  segmentMs = 0;
  quietMs = 0;
  lastPartialSegmentMs = 0;
  lastPartialText = "";
  lastPartialCoveredMs = 0;
  nextPartialAllowedAt = 0;
}

async function transcribeChunks(chunks, sourceRate, durationMs, reason = "quiet", final = true) {
  if (busy) return activeTranscription;
  if (!chunks.length || durationMs < minSegmentMs) return null;
  busy = true;
  activeTranscription = (async () => {
    post("state", { state: "transcribing", reason });
    try {
      const pipeline = await ensurePipeline();
      const merged = concatChunks(chunks);
      const audio = resampleLinear(merged, sourceRate, targetSampleRate);
      const transcribeOptions = {
        sampling_rate: targetSampleRate,
        chunk_length_s: metadata?.engine?.chunkLengthSec || 30,
        stride_length_s: metadata?.engine?.strideLengthSec || 5,
        return_timestamps: false,
      };
      if (metadata?.engine?.multilingual === true) {
        transcribeOptions.language = language;
        transcribeOptions.task = "transcribe";
      }
      const result = await pipeline(audio, transcribeOptions);
      const text = normalizeTranscriptText(result?.text || result?.chunks?.map((chunk) => chunk.text).join(" ") || "");
      if (text) {
        post("transcript", { text, final, language });
        if (final) {
          lastPartialText = "";
          lastPartialCoveredMs = 0;
        } else {
          lastPartialText = text;
          lastPartialCoveredMs = durationMs;
        }
      }
      diagnostic({ event: "segment_transcribed", reason, durationMs: Math.round((audio.length / targetSampleRate) * 1000), textLength: text.length });
    } catch (error) {
      post("error", { context: "transcribe", error: error?.message || String(error) });
    } finally {
      if (!final) {
        lastPartialSegmentMs = Math.max(lastPartialSegmentMs, segmentMs);
        nextPartialAllowedAt = nowMs() + 1200;
      }
      busy = false;
      post("state", { state: "quiet" });
    }
  })();
  try {
    return await activeTranscription;
  } finally {
    activeTranscription = null;
  }
}

async function transcribeBufferedSegment(reason = "quiet", options = {}) {
  if (busy) return;
  if (!options.force && nowMs() < nextPartialAllowedAt) return;
  if (!segmentChunks.length || segmentMs < minSegmentMs) return;
  const chunks = segmentChunks;
  const sourceRate = segmentSampleRate;
  const durationMs = segmentMs;
  resetSegment();
  await transcribeChunks(chunks, sourceRate, durationMs, reason, true);
}

async function transcribePartialSegment(reason = "partial") {
  if (busy) return;
  if (nowMs() < nextPartialAllowedAt) return;
  if (!segmentChunks.length || segmentMs < Math.max(minSegmentMs, partialEveryMs)) return;
  if (segmentMs - lastPartialSegmentMs < partialEveryMs) return;
  lastPartialSegmentMs = segmentMs;
  await transcribeChunks(segmentChunks.slice(), segmentSampleRate, segmentMs, reason, false);
}

function dropBufferedPrefix(coveredMs = 0) {
  const coveredSamples = Math.max(0, Math.floor((segmentSampleRate * coveredMs) / 1000));
  if (!coveredSamples) return;
  let remainingDrop = coveredSamples;
  const nextChunks = [];
  for (const chunk of segmentChunks) {
    if (remainingDrop >= chunk.length) {
      remainingDrop -= chunk.length;
      continue;
    }
    if (remainingDrop > 0) {
      nextChunks.push(chunk.slice(remainingDrop));
      remainingDrop = 0;
      continue;
    }
    nextChunks.push(chunk);
  }
  segmentChunks = nextChunks;
  const remainingSamples = segmentChunks.reduce((sum, chunk) => sum + chunk.length, 0);
  segmentMs = segmentSampleRate ? (remainingSamples / segmentSampleRate) * 1000 : 0;
  quietMs = 0;
  lastPartialSegmentMs = 0;
}

function promotePartialToFinal(reason = "stop") {
  if (!lastPartialText) return false;
  const text = lastPartialText;
  const coveredMs = lastPartialCoveredMs;
  post("transcript", { text: lastPartialText, final: true, language });
  diagnostic({
    event: "partial_promoted_to_final",
    reason,
    durationMs: Math.round(coveredMs),
    textLength: text.length,
    tailDurationMs: Math.round(Math.max(0, segmentMs - coveredMs)),
  });
  lastPartialText = "";
  lastPartialCoveredMs = 0;
  nextPartialAllowedAt = 0;
  dropBufferedPrefix(coveredMs);
  return true;
}

async function handleInit(data = {}) {
  language = data.language || "en";
  const vad = data.vad || {};
  rmsThreshold = Number(vad.rmsThreshold || rmsThreshold) || rmsThreshold;
  minSegmentMs = Number(vad.minSegmentMs || DEFAULT_MIN_SEGMENT_MS) || DEFAULT_MIN_SEGMENT_MS;
  partialEveryMs = Number(vad.partialEveryMs || DEFAULT_PARTIAL_EVERY_MS) || DEFAULT_PARTIAL_EVERY_MS;
  quietAfterMs = Number(vad.quietAfterMs || DEFAULT_QUIET_AFTER_MS) || DEFAULT_QUIET_AFTER_MS;
  maxSegmentMs = Number(vad.maxSegmentMs || DEFAULT_MAX_SEGMENT_MS) || DEFAULT_MAX_SEGMENT_MS;
  try {
    await ensurePipeline(data.metadataUrl || DEFAULT_METADATA_URL);
  } catch (error) {
    post("error", { context: "load_model", error: error?.message || String(error) });
  }
}

async function handleStop(data = {}) {
  if (activeTranscription) await activeTranscription;
  if (data.flush !== false) {
    const reason = data.reason || "stop";
    promotePartialToFinal(reason);
    await transcribeBufferedSegment(reason, { force: true });
  } else {
    resetSegment();
  }
  if (activeTranscription) await activeTranscription;
  post("state", { state: "idle" });
}

self.onmessage = (event) => {
  const data = event.data || {};
  if (data.type === "init") {
    void handleInit(data);
    return;
  }
  if (data.type === "start") {
    language = data.language || language || "en";
    post("state", { state: pipelineInstance ? "quiet" : "loading-model" });
    return;
  }
  if (data.type === "audio") {
    appendAudioChunk(data.audio, Number(data.sampleRate || DEFAULT_TARGET_SAMPLE_RATE), Number(data.rms || 0));
    if (pipelineInstance && (quietMs >= quietAfterMs || segmentMs >= maxSegmentMs)) {
      void transcribeBufferedSegment(quietMs >= quietAfterMs ? "quiet" : "max_segment");
    } else if (pipelineInstance) {
      void transcribePartialSegment("partial");
    }
    return;
  }
  if (data.type === "stop") {
    void handleStop(data);
    return;
  }
  if (data.type === "destroy") {
    resetSegment();
    self.close?.();
  }
};
