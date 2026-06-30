import { validateSpeechModelMetadata } from "./speech-transcription.js";
import { mergeOverlappingTranscriptText, repairTranscriptText } from "./transcript-draft.js";

const DEFAULT_TARGET_SAMPLE_RATE = 16000;
const DEFAULT_MIN_SEGMENT_MS = 900;
const DEFAULT_PARTIAL_EVERY_MS = 3500;
const DEFAULT_QUIET_AFTER_MS = 700;
const DEFAULT_MAX_SEGMENT_MS = 28000;
const DEFAULT_PRE_ROLL_MS = 320;
const DEFAULT_PARTIAL_WINDOW_MS = 4200;
const DEFAULT_PARTIAL_OVERLAP_MS = 450;
const DEFAULT_PARTIAL_COOLDOWN_MS = 350;
const DEFAULT_MIN_PARTIAL_WINDOW_MS = 2400;
const DEFAULT_PARTIAL_WINDOW_STEP_MS = 600;
const DEFAULT_PARTIAL_BACKPRESSURE_RTF = 0.85;
const DEFAULT_PARTIAL_RECOVERY_RTF = 0.45;
const DEFAULT_PARTIAL_COOLDOWN_MAX_MS = 1200;
const DEFAULT_VAD_ADAPTIVE_NOISE = true;
const DEFAULT_VAD_NOISE_FLOOR_RMS = 0.004;
const DEFAULT_VAD_NOISE_FLOOR_ALPHA = 0.035;
const DEFAULT_VAD_START_RATIO = 2.7;
const DEFAULT_VAD_HOLD_RATIO = 1.55;
const DEFAULT_VAD_MIN_START_RMS = 0.0105;
const DEFAULT_VAD_MIN_HOLD_RMS = 0.007;
const DEFAULT_VAD_HANGOVER_MS = 180;
const DEFAULT_METADATA_URL = "/modules/speech-transcription/models/english-v1/metadata.json";

let metadata = null;
let pipelineInstance = null;
let runtimeExports = null;
let loadingPipeline = null;
let language = "en";
let targetSampleRate = DEFAULT_TARGET_SAMPLE_RATE;
let minSegmentMs = DEFAULT_MIN_SEGMENT_MS;
let partialEveryMs = DEFAULT_PARTIAL_EVERY_MS;
let quietAfterMs = DEFAULT_QUIET_AFTER_MS;
let maxSegmentMs = DEFAULT_MAX_SEGMENT_MS;
let preRollMs = DEFAULT_PRE_ROLL_MS;
let partialWindowMs = DEFAULT_PARTIAL_WINDOW_MS;
let partialOverlapMs = DEFAULT_PARTIAL_OVERLAP_MS;
let partialCooldownMs = DEFAULT_PARTIAL_COOLDOWN_MS;
let minPartialWindowMs = DEFAULT_MIN_PARTIAL_WINDOW_MS;
let partialWindowStepMs = DEFAULT_PARTIAL_WINDOW_STEP_MS;
let partialBackpressureRtf = DEFAULT_PARTIAL_BACKPRESSURE_RTF;
let partialRecoveryRtf = DEFAULT_PARTIAL_RECOVERY_RTF;
let partialCooldownMaxMs = DEFAULT_PARTIAL_COOLDOWN_MAX_MS;
let effectivePartialWindowMs = DEFAULT_PARTIAL_WINDOW_MS;
let partialDecodeRtfEma = 0;
let partialBackpressureLevel = 0;
let rmsThreshold = 0.015;
let vadAdaptiveNoise = DEFAULT_VAD_ADAPTIVE_NOISE;
let vadNoiseFloorRms = DEFAULT_VAD_NOISE_FLOOR_RMS;
let vadNoiseFloorAlpha = DEFAULT_VAD_NOISE_FLOOR_ALPHA;
let vadStartRatio = DEFAULT_VAD_START_RATIO;
let vadHoldRatio = DEFAULT_VAD_HOLD_RATIO;
let vadMinStartRms = DEFAULT_VAD_MIN_START_RMS;
let vadMinHoldRms = DEFAULT_VAD_MIN_HOLD_RMS;
let vadHangoverMs = DEFAULT_VAD_HANGOVER_MS;
let segmentChunks = [];
let preSpeechChunks = [];
let segmentSampleRate = DEFAULT_TARGET_SAMPLE_RATE;
let segmentSamples = 0;
let preSpeechSamples = 0;
let segmentMs = 0;
let quietMs = 0;
let speechDetected = false;
let speechMs = 0;
let peakRms = 0;
let busy = false;
let activeTranscription = null;
let lastPartialSegmentMs = 0;
let lastPartialText = "";
let lastPartialStartMs = 0;
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

function clampNumber(value, min, max, fallback = min) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(min, Math.min(max, number));
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

function assetMarkerRequest(asset) {
  const sha = String(asset.sha256 || "").toLowerCase();
  const key = encodeURIComponent(`${asset.url || ""}:${sha}`);
  return new Request(`/modules/speech-transcription/.sha-cache/${key}.json`);
}

async function markAssetShaRecorded(cache, asset, sizeBytes = 0) {
  await cache.put(assetMarkerRequest(asset), new Response(JSON.stringify({
    url: asset.url,
    sha256: String(asset.sha256 || "").toLowerCase(),
    sizeBytes,
    recordedAt: new Date().toISOString(),
  }), {
    headers: { "content-type": "application/json" },
  }));
}

async function cachedShaMatches(cache, asset) {
  const cached = await cache.match(asset.url);
  if (!cached) return false;
  const marker = await cache.match(assetMarkerRequest(asset));
  if (marker) {
    diagnostic({ event: "asset_cache_marker_hit", url: asset.url, sha256: String(asset.sha256 || "").toLowerCase() });
    return true;
  }
  const buffer = await cached.arrayBuffer();
  const digest = await sha256(buffer);
  if (digest.toLowerCase() !== String(asset.sha256).toLowerCase()) {
    await cache.delete(asset.url);
    await cache.delete(assetMarkerRequest(asset));
    diagnostic({ event: "cached_asset_sha_mismatch", url: asset.url, sha256: digest });
    return false;
  }
  await markAssetShaRecorded(cache, asset, buffer.byteLength);
  diagnostic({ event: "asset_cache_hit", url: asset.url, sizeBytes: buffer.byteLength, sha256: digest });
  return true;
}

async function reuseCachedAssetFromAnyCache(targetCache, targetCacheName, asset) {
  if (!self.caches) return false;
  const cacheNames = await self.caches.keys();
  for (const cacheName of cacheNames) {
    if (cacheName === targetCacheName) continue;
    const sourceCache = await self.caches.open(cacheName);
    const cached = await sourceCache.match(asset.url);
    if (!cached) continue;
    const sourceMarker = await sourceCache.match(assetMarkerRequest(asset));
    if (sourceMarker) {
      await targetCache.put(asset.url, cached.clone());
      await markAssetShaRecorded(targetCache, asset, Number(asset.sizeBytes || 0));
      diagnostic({ event: "asset_cache_reused_marker", url: asset.url, fromCache: cacheName, sha256: String(asset.sha256 || "").toLowerCase() });
      return true;
    }
    const buffer = await cached.arrayBuffer();
    const digest = await sha256(buffer);
    if (digest.toLowerCase() !== String(asset.sha256).toLowerCase()) {
      diagnostic({ event: "asset_cache_reuse_sha_mismatch", url: asset.url, fromCache: cacheName, sha256: digest });
      continue;
    }
    await targetCache.put(asset.url, new Response(buffer, {
      status: cached.status,
      statusText: cached.statusText,
      headers: cached.headers,
    }));
    await markAssetShaRecorded(targetCache, asset, buffer.byteLength);
    diagnostic({ event: "asset_cache_reused_after_sha", url: asset.url, fromCache: cacheName, sizeBytes: buffer.byteLength, sha256: digest });
    return true;
  }
  return false;
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
    if (await reuseCachedAssetFromAnyCache(cache, cacheName, asset)) continue;
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
    await markAssetShaRecorded(cache, asset, buffer.byteLength);
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
  return {
    pipeline,
    WhisperTextStreamer: runtime.WhisperTextStreamer || null,
  };
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
      const configuredRuntime = configureRuntime(runtime, modelMetadata);
      const instance = await configuredRuntime.pipeline(modelMetadata.engine.task || "automatic-speech-recognition", modelId, {
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
      return { instance, device: options.device, runtime: configuredRuntime };
    } catch (error) {
      lastError = error;
      diagnostic({ event: "pipeline_init_failed", device: options.device, error: error?.message || String(error), runtime });
    }
  }
  throw lastError || new Error("pipeline_init_failed");
}

async function warmupPipeline(instance) {
  const decode = metadata?.engine?.decode || {};
  if (decode.warmupOnLoad !== true || typeof instance !== "function") return;
  const warmupAudioMs = clampNumber(decode.warmupAudioMs, 80, 1000, 320);
  const warmupMaxNewTokens = Math.round(clampNumber(decode.warmupMaxNewTokens, 1, 12, 4));
  const audio = new Float32Array(Math.max(1, Math.round((targetSampleRate * warmupAudioMs) / 1000)));
  const startedAt = nowMs();
  try {
    await instance(audio, {
      sampling_rate: targetSampleRate,
      chunk_length_s: 0,
      return_timestamps: false,
      num_beams: 1,
      do_sample: false,
      temperature: 0,
      max_new_tokens: warmupMaxNewTokens,
    });
    diagnostic({
      event: "pipeline_warmed",
      durationMs: Math.round(warmupAudioMs),
      elapsedMs: Math.round(nowMs() - startedAt),
      max_new_tokens: warmupMaxNewTokens,
    });
  } catch (error) {
    diagnostic({ event: "pipeline_warmup_failed", error: error?.message || String(error) });
  }
}

function resetAdaptivePartialPolicy() {
  effectivePartialWindowMs = clampNumber(effectivePartialWindowMs, minPartialWindowMs, partialWindowMs, partialWindowMs);
  partialDecodeRtfEma = 0;
  partialBackpressureLevel = 0;
}

function currentVadThresholds() {
  if (!vadAdaptiveNoise) {
    return { start: rmsThreshold, hold: rmsThreshold };
  }
  const floor = Math.max(0.0005, vadNoiseFloorRms || DEFAULT_VAD_NOISE_FLOOR_RMS);
  const start = Math.max(vadMinStartRms, floor * vadStartRatio, rmsThreshold * 0.75);
  const hold = Math.min(start, Math.max(vadMinHoldRms, floor * vadHoldRatio, rmsThreshold * 0.5));
  return { start, hold };
}

function updateVadNoiseFloor(rms, chunkMs = 32) {
  if (!vadAdaptiveNoise) return;
  const sample = clampNumber(rms, 0, 0.2, 0);
  const frameFactor = Math.max(1, Number(chunkMs || 0) / 32);
  const alpha = 1 - Math.pow(1 - vadNoiseFloorAlpha, frameFactor);
  vadNoiseFloorRms = vadNoiseFloorRms > 0
    ? vadNoiseFloorRms * (1 - alpha) + sample * alpha
    : sample;
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
    preRollMs = Number(metadata.audio?.preRollMs || preRollMs) || preRollMs;
    partialWindowMs = Number(metadata.audio?.partialWindowMs || partialWindowMs) || partialWindowMs;
    partialOverlapMs = Number(metadata.audio?.partialOverlapMs || partialOverlapMs) || partialOverlapMs;
    partialCooldownMs = Number(metadata.audio?.partialCooldownMs || partialCooldownMs) || partialCooldownMs;
    minPartialWindowMs = Number(metadata.audio?.minPartialWindowMs || minPartialWindowMs) || minPartialWindowMs;
    partialWindowStepMs = Number(metadata.audio?.partialWindowStepMs || partialWindowStepMs) || partialWindowStepMs;
    partialBackpressureRtf = Number(metadata.audio?.partialBackpressureRtf || partialBackpressureRtf) || partialBackpressureRtf;
    partialRecoveryRtf = Number(metadata.audio?.partialRecoveryRtf || partialRecoveryRtf) || partialRecoveryRtf;
    partialCooldownMaxMs = Number(metadata.audio?.partialCooldownMaxMs || partialCooldownMaxMs) || partialCooldownMaxMs;
    resetAdaptivePartialPolicy();
    rmsThreshold = Number(metadata.audio?.vadRmsThreshold || rmsThreshold) || rmsThreshold;
    vadAdaptiveNoise = metadata.audio?.vadAdaptiveNoise !== false;
    vadNoiseFloorRms = clampNumber(metadata.audio?.vadNoiseFloorRms, 0, 0.2, vadNoiseFloorRms);
    vadNoiseFloorAlpha = clampNumber(metadata.audio?.vadNoiseFloorAlpha, 0.001, 1, vadNoiseFloorAlpha);
    vadStartRatio = clampNumber(metadata.audio?.vadStartRatio, 1, 10, vadStartRatio);
    vadHoldRatio = clampNumber(metadata.audio?.vadHoldRatio, 1, 10, vadHoldRatio);
    vadMinStartRms = clampNumber(metadata.audio?.vadMinStartRms, 0, 0.2, vadMinStartRms);
    vadMinHoldRms = clampNumber(metadata.audio?.vadMinHoldRms, 0, 0.2, vadMinHoldRms);
    vadHangoverMs = clampNumber(metadata.audio?.vadHangoverMs, 0, quietAfterMs, vadHangoverMs);
    const pipelineResult = await createPipeline(metadata);
    pipelineInstance = pipelineResult.instance;
    runtimeExports = pipelineResult.runtime || null;
    await warmupPipeline(pipelineInstance);
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
  segmentSampleRate = sampleRate || segmentSampleRate || DEFAULT_TARGET_SAMPLE_RATE;
  const chunkMs = (chunk.length / segmentSampleRate) * 1000;
  const safeRms = Math.max(0, Number.isFinite(Number(rms)) ? Number(rms) : 0);
  const thresholds = currentVadThresholds();
  const startVoiced = safeRms >= thresholds.start;
  const holdVoiced = safeRms >= thresholds.hold;
  if (!speechDetected && !startVoiced) {
    updateVadNoiseFloor(safeRms, chunkMs);
    pushPreSpeechChunk(chunk);
    return;
  }
  if (!speechDetected) {
    const appliedPreRollMs = (preSpeechSamples / segmentSampleRate) * 1000;
    drainPreSpeechChunks();
    speechDetected = true;
    speechMs = 0;
    peakRms = 0;
    diagnostic({
      event: "speech_segment_started",
      preRollMs: Math.round(appliedPreRollMs),
      rms: Number(safeRms.toFixed(5)),
      noiseFloorRms: Number(vadNoiseFloorRms.toFixed(5)),
      vadStartThreshold: Number(thresholds.start.toFixed(5)),
      vadHoldThreshold: Number(thresholds.hold.toFixed(5)),
    });
  }
  appendSegmentChunk(chunk);
  if (holdVoiced) {
    quietMs = 0;
    speechMs += chunkMs;
    peakRms = Math.max(peakRms, safeRms);
  } else {
    quietMs += chunkMs;
    if (quietMs > vadHangoverMs) updateVadNoiseFloor(safeRms, chunkMs);
  }
}

function appendSegmentChunk(chunk) {
  segmentChunks.push(chunk);
  segmentSamples += chunk.length;
  segmentMs = (segmentSamples / segmentSampleRate) * 1000;
  const maxSamples = Math.ceil((segmentSampleRate * maxSegmentMs) / 1000);
  if (segmentSamples > maxSamples) {
    let drop = segmentSamples - maxSamples;
    while (drop > 0 && segmentChunks.length > 1) {
      const first = segmentChunks[0];
      if (first.length <= drop) {
        segmentChunks.shift();
        segmentSamples -= first.length;
        drop -= first.length;
      } else {
        segmentChunks[0] = first.slice(drop);
        segmentSamples -= drop;
        drop = 0;
      }
    }
    segmentMs = (segmentSamples / segmentSampleRate) * 1000;
    speechMs = Math.min(speechMs, segmentMs);
  }
}

function pushPreSpeechChunk(chunk) {
  if (preRollMs <= 0) return;
  preSpeechChunks.push(chunk);
  preSpeechSamples += chunk.length;
  const maxPreRollSamples = Math.ceil((segmentSampleRate * preRollMs) / 1000);
  while (preSpeechSamples > maxPreRollSamples && preSpeechChunks.length) {
    const first = preSpeechChunks[0];
    const drop = Math.min(first.length, preSpeechSamples - maxPreRollSamples);
    if (drop >= first.length) {
      preSpeechChunks.shift();
    } else {
      preSpeechChunks[0] = first.slice(drop);
    }
    preSpeechSamples -= drop;
  }
}

function drainPreSpeechChunks() {
  for (const chunk of preSpeechChunks) appendSegmentChunk(chunk);
  preSpeechChunks = [];
  preSpeechSamples = 0;
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

function sliceChunksBySampleRange(chunks = [], startSample = 0, endSample = Infinity) {
  const result = [];
  let cursor = 0;
  for (const chunk of chunks) {
    const chunkStart = cursor;
    const chunkEnd = cursor + chunk.length;
    cursor = chunkEnd;
    if (chunkEnd <= startSample) continue;
    if (chunkStart >= endSample) break;
    const from = Math.max(0, startSample - chunkStart);
    const to = Math.min(chunk.length, endSample - chunkStart);
    if (to > from) result.push(chunk.slice(from, to));
  }
  return result;
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
  preSpeechChunks = [];
  segmentSamples = 0;
  preSpeechSamples = 0;
  segmentMs = 0;
  quietMs = 0;
  speechDetected = false;
  speechMs = 0;
  peakRms = 0;
  lastPartialSegmentMs = 0;
  lastPartialText = "";
  lastPartialStartMs = 0;
  lastPartialCoveredMs = 0;
  nextPartialAllowedAt = 0;
  resetAdaptivePartialPolicy();
}

function applyDecodeOptions(transcribeOptions, final = true, durationMs = 0) {
  const decode = metadata?.engine?.decode || {};
  const beams = Number(final ? (decode.finalNumBeams ?? decode.numBeams) : (decode.partialNumBeams ?? 1));
  if (Number.isFinite(beams) && beams >= 1) transcribeOptions.num_beams = Math.max(1, Math.min(8, Math.round(beams)));
  const temperature = Number(decode.temperature);
  if (Number.isFinite(temperature) && temperature >= 0) transcribeOptions.temperature = temperature;
  if (typeof decode.doSample === "boolean") transcribeOptions.do_sample = decode.doSample;
  const maxTokensPerSecond = Number(decode.maxTokensPerSecond);
  const tokenBase = Number(decode.maxNewTokensBase);
  const tokenCap = Number(final ? decode.finalMaxNewTokens : decode.partialMaxNewTokens);
  if (Number.isFinite(maxTokensPerSecond) && maxTokensPerSecond > 0 && Number.isFinite(tokenCap) && tokenCap > 0) {
    const seconds = Math.max(0.25, Number(durationMs || 0) / 1000);
    const computed = Math.ceil((Number.isFinite(tokenBase) ? Math.max(0, tokenBase) : 12) + seconds * maxTokensPerSecond);
    transcribeOptions.max_new_tokens = Math.max(8, Math.min(Math.round(tokenCap), computed));
  }
  return transcribeOptions;
}

function createPartialStreamer(pipeline, metrics = {}) {
  const decode = metadata?.engine?.decode || {};
  const Streamer = runtimeExports?.WhisperTextStreamer;
  const emitEveryMs = Number(decode.streamEmitEveryMs || 120);
  if (decode.streamPartialText !== true || typeof Streamer !== "function" || !pipeline?.tokenizer) return null;
  let rawText = "";
  let lastPostedText = "";
  let lastPostedAt = 0;
  const emit = (force = false) => {
    const text = repairTranscriptText(rawText);
    if (!text || text === lastPostedText) return;
    const elapsedMs = nowMs();
    if (!force && Number.isFinite(emitEveryMs) && emitEveryMs > 0 && elapsedMs - lastPostedAt < emitEveryMs) return;
    lastPostedText = text;
    lastPostedAt = elapsedMs;
    const transcriptText = metrics.mergeWithPrevious
      ? mergeOverlappingTranscriptText(lastPartialText, text)
      : text;
    post("transcript", { text: transcriptText, final: false, language, streaming: true });
  };
  return new Streamer(pipeline.tokenizer, {
    skip_prompt: true,
    skip_special_tokens: true,
    callback_function(piece = "") {
      rawText += String(piece || "");
      emit(false);
    },
    on_finalize() {
      emit(true);
    },
  });
}

function updatePartialBackpressure(elapsedMs, windowMs, metrics = {}) {
  const realtimeFactor = windowMs > 0 ? elapsedMs / windowMs : 0;
  if (!Number.isFinite(realtimeFactor) || realtimeFactor <= 0) return 0;
  partialDecodeRtfEma = partialDecodeRtfEma > 0
    ? partialDecodeRtfEma * 0.65 + realtimeFactor * 0.35
    : realtimeFactor;
  const backlogMs = Number(metrics.backlogMs || 0);
  const skippedBacklogMs = Number(metrics.skippedBacklogMs || 0);
  const congested = partialDecodeRtfEma >= partialBackpressureRtf || backlogMs > 0 || skippedBacklogMs > 0;
  const recovered = partialDecodeRtfEma <= partialRecoveryRtf && backlogMs <= 0 && skippedBacklogMs <= 0;
  if (congested) {
    partialBackpressureLevel = Math.min(4, partialBackpressureLevel + 1);
    effectivePartialWindowMs = Math.max(minPartialWindowMs, effectivePartialWindowMs - partialWindowStepMs);
  } else if (recovered) {
    partialBackpressureLevel = Math.max(0, partialBackpressureLevel - 1);
    effectivePartialWindowMs = Math.min(partialWindowMs, effectivePartialWindowMs + partialWindowStepMs);
  }
  return realtimeFactor;
}

function currentPartialCooldownMs() {
  return Math.min(partialCooldownMaxMs, partialCooldownMs + partialBackpressureLevel * 200);
}

async function transcribeChunks(chunks, sourceRate, durationMs, reason = "quiet", final = true, metrics = {}) {
  if (busy) return activeTranscription;
  if (!chunks.length || durationMs < minSegmentMs) return null;
  busy = true;
  activeTranscription = (async () => {
    post("state", { state: "transcribing", reason });
    const startedAt = nowMs();
    let elapsedMs = 0;
    let realtimeFactor = 0;
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
      applyDecodeOptions(transcribeOptions, final, durationMs);
      if (!final) {
        const streamer = createPartialStreamer(pipeline, metrics);
        if (streamer) transcribeOptions.streamer = streamer;
      }
      if (metadata?.engine?.multilingual === true) {
        transcribeOptions.language = language;
        transcribeOptions.task = "transcribe";
      }
      const result = await pipeline(audio, transcribeOptions);
      elapsedMs = Math.max(0, nowMs() - startedAt);
      if (!final) realtimeFactor = updatePartialBackpressure(elapsedMs, durationMs, metrics);
      const text = repairTranscriptText(result?.text || result?.chunks?.map((chunk) => chunk.text).join(" ") || "");
      if (text) {
        const transcriptText = final || !metrics.mergeWithPrevious
          ? text
          : mergeOverlappingTranscriptText(lastPartialText, text);
        post("transcript", { text: transcriptText, final, language });
        if (final) {
          lastPartialText = "";
          lastPartialStartMs = 0;
          lastPartialCoveredMs = 0;
        } else {
          lastPartialText = transcriptText;
          lastPartialStartMs = Number(metrics.windowStartMs || 0);
          lastPartialCoveredMs = Number(metrics.coveredMs || durationMs);
        }
      }
      const vadThresholds = currentVadThresholds();
      diagnostic({
        event: "segment_transcribed",
        reason,
        durationMs: Math.round((audio.length / targetSampleRate) * 1000),
        speechMs: Math.round(metrics.speechMs || 0),
        windowMs: Math.round(durationMs),
        coveredMs: Math.round(metrics.coveredMs || durationMs),
        windowStartMs: Math.round(metrics.windowStartMs || 0),
        backlogMs: Math.round(metrics.backlogMs || 0),
        skippedBacklogMs: Math.round(metrics.skippedBacklogMs || 0),
        elapsedMs: Math.round(elapsedMs),
        realtimeFactor: Number(realtimeFactor.toFixed?.(3) || 0),
        partialDecodeRtfEma: Number(partialDecodeRtfEma.toFixed?.(3) || 0),
        effectivePartialWindowMs: Math.round(effectivePartialWindowMs),
        partialBackpressureLevel,
        noiseFloorRms: Number(vadNoiseFloorRms.toFixed(5)),
        vadStartThreshold: Number(vadThresholds.start.toFixed(5)),
        vadHoldThreshold: Number(vadThresholds.hold.toFixed(5)),
        peakRms: Number((metrics.peakRms || 0).toFixed?.(5) || 0),
        decode: {
          num_beams: transcribeOptions.num_beams || 1,
          do_sample: transcribeOptions.do_sample === true,
          temperature: transcribeOptions.temperature ?? null,
          max_new_tokens: transcribeOptions.max_new_tokens || null,
          streamer: Boolean(transcribeOptions.streamer),
        },
        textLength: text.length,
      });
    } catch (error) {
      post("error", { context: "transcribe", error: error?.message || String(error) });
    } finally {
      if (!final) {
        lastPartialSegmentMs = Math.max(lastPartialSegmentMs, segmentMs);
        nextPartialAllowedAt = nowMs() + currentPartialCooldownMs();
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
  if (!speechDetected || speechMs <= 0) {
    if (options.force) resetSegment();
    return null;
  }
  if (!segmentChunks.length || segmentMs < minSegmentMs) {
    if (options.force) resetSegment();
    return null;
  }
  const chunks = segmentChunks;
  const sourceRate = segmentSampleRate;
  const durationMs = segmentMs;
  const metrics = { speechMs, peakRms };
  resetSegment();
  await transcribeChunks(chunks, sourceRate, durationMs, reason, true, metrics);
}

async function transcribePartialSegment(reason = "partial") {
  if (busy) return;
  if (nowMs() < nextPartialAllowedAt) return;
  if (!speechDetected || speechMs <= 0) return;
  if (!segmentChunks.length || segmentMs < Math.max(minSegmentMs, partialEveryMs)) return;
  if (segmentMs - lastPartialSegmentMs < partialEveryMs) return;
  lastPartialSegmentMs = segmentMs;
  const overlapMs = lastPartialText ? partialOverlapMs : 0;
  const activePartialWindowMs = clampNumber(effectivePartialWindowMs, minPartialWindowMs, partialWindowMs, partialWindowMs);
  const contiguousStartMs = Math.max(0, lastPartialCoveredMs - overlapMs);
  const windowStartMs = Math.max(contiguousStartMs, segmentMs - activePartialWindowMs);
  const backlogMs = Math.max(0, segmentMs - contiguousStartMs - activePartialWindowMs);
  const skippedBacklogMs = Math.max(0, windowStartMs - contiguousStartMs);
  const startSample = Math.max(0, Math.floor((segmentSampleRate * windowStartMs) / 1000));
  const chunks = sliceChunksBySampleRange(segmentChunks, startSample, segmentSamples);
  const windowMs = segmentSampleRate
    ? (chunks.reduce((sum, chunk) => sum + chunk.length, 0) / segmentSampleRate) * 1000
    : 0;
  if (!chunks.length || windowMs < minSegmentMs) return;
  await transcribeChunks(chunks, segmentSampleRate, windowMs, reason, false, {
    speechMs,
    peakRms,
    coveredMs: segmentMs,
    windowStartMs,
    backlogMs,
    skippedBacklogMs,
    mergeWithPrevious: true,
  });
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
  segmentSamples = segmentChunks.reduce((sum, chunk) => sum + chunk.length, 0);
  segmentMs = segmentSampleRate ? (segmentSamples / segmentSampleRate) * 1000 : 0;
  quietMs = 0;
  speechMs = Math.max(0, speechMs - coveredMs);
  speechDetected = speechMs > 0;
  if (!speechDetected) peakRms = 0;
  lastPartialSegmentMs = 0;
}

function promotePartialToFinal(reason = "stop") {
  if (!lastPartialText) return false;
  if (lastPartialStartMs > 0) {
    diagnostic({
      event: "partial_promotion_skipped",
      reason,
      startMs: Math.round(lastPartialStartMs),
      coveredMs: Math.round(lastPartialCoveredMs),
      tailDurationMs: Math.round(Math.max(0, segmentMs - lastPartialCoveredMs)),
    });
    return false;
  }
  const text = repairTranscriptText(lastPartialText);
  const coveredMs = lastPartialCoveredMs;
  post("transcript", { text, final: true, language });
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
  vadAdaptiveNoise = typeof vad.vadAdaptiveNoise === "boolean" ? vad.vadAdaptiveNoise : DEFAULT_VAD_ADAPTIVE_NOISE;
  vadNoiseFloorRms = clampNumber(vad.vadNoiseFloorRms, 0, 0.2, DEFAULT_VAD_NOISE_FLOOR_RMS);
  vadNoiseFloorAlpha = clampNumber(vad.vadNoiseFloorAlpha, 0.001, 1, DEFAULT_VAD_NOISE_FLOOR_ALPHA);
  vadStartRatio = clampNumber(vad.vadStartRatio, 1, 10, DEFAULT_VAD_START_RATIO);
  vadHoldRatio = clampNumber(vad.vadHoldRatio, 1, 10, DEFAULT_VAD_HOLD_RATIO);
  vadMinStartRms = clampNumber(vad.vadMinStartRms, 0, 0.2, DEFAULT_VAD_MIN_START_RMS);
  vadMinHoldRms = clampNumber(vad.vadMinHoldRms, 0, 0.2, DEFAULT_VAD_MIN_HOLD_RMS);
  vadHangoverMs = clampNumber(vad.vadHangoverMs, 0, DEFAULT_QUIET_AFTER_MS, DEFAULT_VAD_HANGOVER_MS);
  minSegmentMs = Number(vad.minSegmentMs || DEFAULT_MIN_SEGMENT_MS) || DEFAULT_MIN_SEGMENT_MS;
  partialEveryMs = Number(vad.partialEveryMs || DEFAULT_PARTIAL_EVERY_MS) || DEFAULT_PARTIAL_EVERY_MS;
  quietAfterMs = Number(vad.quietAfterMs || DEFAULT_QUIET_AFTER_MS) || DEFAULT_QUIET_AFTER_MS;
  maxSegmentMs = Number(vad.maxSegmentMs || DEFAULT_MAX_SEGMENT_MS) || DEFAULT_MAX_SEGMENT_MS;
  preRollMs = Number(vad.preRollMs || DEFAULT_PRE_ROLL_MS) || DEFAULT_PRE_ROLL_MS;
  partialWindowMs = Number(vad.partialWindowMs || DEFAULT_PARTIAL_WINDOW_MS) || DEFAULT_PARTIAL_WINDOW_MS;
  partialOverlapMs = Number(vad.partialOverlapMs || DEFAULT_PARTIAL_OVERLAP_MS) || DEFAULT_PARTIAL_OVERLAP_MS;
  partialCooldownMs = Number(vad.partialCooldownMs || DEFAULT_PARTIAL_COOLDOWN_MS) || DEFAULT_PARTIAL_COOLDOWN_MS;
  minPartialWindowMs = Number(vad.minPartialWindowMs || DEFAULT_MIN_PARTIAL_WINDOW_MS) || DEFAULT_MIN_PARTIAL_WINDOW_MS;
  partialWindowStepMs = Number(vad.partialWindowStepMs || DEFAULT_PARTIAL_WINDOW_STEP_MS) || DEFAULT_PARTIAL_WINDOW_STEP_MS;
  partialBackpressureRtf = Number(vad.partialBackpressureRtf || DEFAULT_PARTIAL_BACKPRESSURE_RTF) || DEFAULT_PARTIAL_BACKPRESSURE_RTF;
  partialRecoveryRtf = Number(vad.partialRecoveryRtf || DEFAULT_PARTIAL_RECOVERY_RTF) || DEFAULT_PARTIAL_RECOVERY_RTF;
  partialCooldownMaxMs = Number(vad.partialCooldownMaxMs || DEFAULT_PARTIAL_COOLDOWN_MAX_MS) || DEFAULT_PARTIAL_COOLDOWN_MAX_MS;
  effectivePartialWindowMs = partialWindowMs;
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
