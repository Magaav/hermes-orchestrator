export const WIS_CAMERA_ARTIFACT_SCHEMA = "hermes.wasm_agent.wis.camera_artifact.v1";
export const WIS_CAMERA_FOCUS_SCHEMA = "hermes.wasm_agent.wis.camera_focus.v1";
export const WIS_CAMERA_CONTROLLER_SCHEMA = "hermes.wasm_agent.wis.camera_controller.v1";
export const WIS_CAMERA_CONFIGS_STORAGE_KEY = "wasmAgent.wisCameraConfigs.v1";
export const WIS_CAMERA_DEFAULT_SLOT = "cam-1";
export const WIS_CAMERA_NODE_TYPE = "webcam_placeholder";
export const WIS_CAMERA_PUSH_MEDIA_MODE = "rtmp-push-ingest";
export const WIS_CAMERA_ARTIFACT_BUILD = "PLAYPAUSE_TRACE_20260519_002";
export const WIS_SPACE_SCHEMA = "hermes.wasm_agent.wis.space.v1";
export const WIS_CAMERA_PUSH_ENDPOINTS = Object.freeze({
  status: "/camera/push/status",
  frame: "/camera/push-frame",
  stream: "/camera/push-stream",
  replay: "/camera/push-replay",
  playback: "/camera/push-playback",
  timeline: "/camera/push-timeline",
  archiveFrame: "/camera/push-archive-frame",
});
const CAMERA_DEBUG = (() => {
  try {
    return Boolean(
      globalThis?.WASM_AGENT_CAMERA_DEBUG
      || globalThis?.localStorage?.getItem?.("wasmAgent.cameraDebug") === "1"
    );
  } catch {
    return false;
  }
})();
const mediaWriters = new WeakMap();
const mediaStreamWriters = new Map();
const mediaImageBuffers = new WeakMap();
const mediaVisualSamples = new WeakMap();
const WIS_CAMERA_PERF_SAMPLE_MS = 1000;
let mediaImageBufferSeq = 0;

function traceText(value = "", fallback = "") {
  const text = String(value ?? "").trim();
  return text || String(fallback ?? "").trim();
}

function traceNumber(value, fallback = null) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function deepCloneWisCameraTracePayload(value) {
  try {
    if (typeof structuredClone === "function") return structuredClone(value);
  } catch {
    // Fall through to JSON cloning.
  }
  try {
    return JSON.parse(JSON.stringify(value ?? null));
  } catch {
    return value == null ? value : String(value);
  }
}

function serializeWisCameraTraceValue(value, depth = 0) {
  if (value == null || ["string", "number", "boolean"].includes(typeof value)) return value;
  if (depth > 2) return String(value);
  if (Array.isArray(value)) return value.slice(0, 12).map((item) => serializeWisCameraTraceValue(item, depth + 1));
  if (typeof value === "object") {
    if (typeof Element !== "undefined" && value instanceof Element) {
      return {
        tagName: traceText(value.tagName, ""),
        id: traceText(value.id, ""),
        className: traceText(value.className, ""),
        dataset: value.dataset ? { ...value.dataset } : {},
      };
    }
    return Object.fromEntries(Object.entries(value).slice(0, 40).map(([key, item]) => [key, serializeWisCameraTraceValue(item, depth + 1)]));
  }
  return String(value);
}

export function traceWisCameraBoundary(event, detail = {}, options = {}) {
  const traceEvent = String(event || "camera.trace");
  const serializedDetail = serializeWisCameraTraceValue(detail);
  const wallTimestamp = Date.now();
  const monotonicTimestamp = typeof globalThis.performance?.now === "function"
    ? Math.round(globalThis.performance.now() * 1000) / 1000
    : wallTimestamp;
  const streamId = traceText(
    serializedDetail.streamId
      || serializedDetail.cameraId
      || serializedDetail.artifactId
      || serializedDetail.mediaStreamId
      || serializedDetail.visibleImageStreamId,
    ""
  );
  const owner = traceText(
    serializedDetail.owner
      || serializedDetail.ownerState
      || serializedDetail.currentOwner
      || serializedDetail.nextOwner
      || serializedDetail.ownerKind
      || serializedDetail.frameLayerOwner
      || serializedDetail.visibleLayerOwner,
    ""
  );
  const mode = traceText(
    serializedDetail.mode
      || serializedDetail.currentMode
      || serializedDetail.controllerMode
      || serializedDetail.toMode
      || serializedDetail.fromMode,
    ""
  );
  const generation = traceNumber(
    serializedDetail.generation
      ?? serializedDetail.activeGeneration
      ?? serializedDetail.playbackGeneration
      ?? serializedDetail.mediaGeneration,
    0
  );
  const frameTimestampMs = traceNumber(
    serializedDetail.frameTimestampMs
      ?? serializedDetail.visibleFrameMs
      ?? serializedDetail.resolvedFrameTimestampMs
      ?? serializedDetail.resolvedTimestampMs
      ?? serializedDetail.targetTimestampMs
      ?? serializedDetail.requestedTimestampMs,
    null
  );
  const payload = {
    ...serializedDetail,
    cameraArtifactBuild: WIS_CAMERA_ARTIFACT_BUILD,
    timestamp: wallTimestamp,
    timestampIso: new Date(wallTimestamp).toISOString(),
    t: monotonicTimestamp,
    event: traceEvent,
    streamId,
    owner,
    mode,
    generation,
    frameTimestampMs,
    reason: traceText(serializedDetail.reason || serializedDetail.handler || ""),
    decision: traceText(serializedDetail.decision || ""),
  };
  if (options.stack) {
    try {
      payload.stack = new Error(traceEvent).stack?.split("\n").slice(1, 7).join("\n") || "";
    } catch {
      payload.stack = "";
    }
  }
  const storedPayload = deepCloneWisCameraTracePayload(payload);
  try {
    globalThis.cameraArtifactBuild = WIS_CAMERA_ARTIFACT_BUILD;
    globalThis.__WIS_CAMERA_ARTIFACT_BUILD__ = WIS_CAMERA_ARTIFACT_BUILD;
    if (!Array.isArray(globalThis.__WIS_CAMERA_TRACE__)) globalThis.__WIS_CAMERA_TRACE__ = [];
    globalThis.__WIS_CAMERA_TRACE__.push(storedPayload);
    while (globalThis.__WIS_CAMERA_TRACE__.length > 1000) globalThis.__WIS_CAMERA_TRACE__.shift();
    if (!Array.isArray(globalThis.__WIS_CAMERA_TRACE_ALL__)) globalThis.__WIS_CAMERA_TRACE_ALL__ = [];
    globalThis.__WIS_CAMERA_TRACE_ALL__.push(deepCloneWisCameraTracePayload(storedPayload));
    while (globalThis.__WIS_CAMERA_TRACE_ALL__.length > 5000) globalThis.__WIS_CAMERA_TRACE_ALL__.shift();
  } catch {
    // Trace storage must not affect playback.
  }
  try {
    globalThis.console?.info?.("[wis-camera-trace]", traceEvent, storedPayload);
  } catch {
    // Console diagnostics are best effort.
  }
  return deepCloneWisCameraTracePayload(storedPayload);
}

traceWisCameraBoundary("cameraArtifactBuild", {
  module: "modules/wis/artifacts/camera.js",
  cameraArtifactBuild: WIS_CAMERA_ARTIFACT_BUILD,
});

export const WIS_CAMERA_PERFORMANCE_POLICY = Object.freeze({
  focusedRecordedFps: 12,
  visibleRecordedFps: 4,
  backgroundRecordedFps: 0,
  offscreenRecordedFps: 0,
  focusedLiveFps: 8,
  visibleLiveFps: 3,
  backgroundLiveFps: 0.2,
  offscreenLiveFps: 0,
  focusedTimelineFps: 4,
  visibleTimelineFps: 1,
  backgroundTimelineFps: 0,
  offscreenTimelineFps: 0,
  hiddenRetryMs: 2500,
  backgroundRetryMs: 5000,
  minimumVisualIntervalMs: 67,
  maximumVisibleIntervalMs: 1000,
  maximumIdleIntervalMs: 5000,
});

export const WIS_CAMERA_TIMELINE_OWNER_STATES = Object.freeze({
  LIVE: "LIVE",
  RECORDED_SEEKING: "RECORDED_SEEKING",
  RECORDED_PLAYING: "RECORDED_PLAYING",
  RECORDED_PAUSED: "RECORDED_PAUSED",
});

function cleanText(value = "", fallback = "") {
  const text = String(value ?? "").trim();
  return text || String(fallback ?? "").trim();
}

function clone(value) {
  if (value === undefined) return undefined;
  return JSON.parse(JSON.stringify(value));
}

function nowIso() {
  return new Date().toISOString();
}

function clamp(value, min, max) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return min;
  return Math.min(max, Math.max(min, numeric));
}

export function normalizeWisCameraStoredConfigs(configs = {}) {
  if (!configs || typeof configs !== "object" || Array.isArray(configs)) return {};
  return Object.fromEntries(
    Object.entries(configs)
      .filter(([key, config]) => key && config && typeof config === "object")
      .map(([key, config]) => [key, {
        kind: cleanText(config.kind, ""),
        url: cleanText(config.url, ""),
        label: cleanText(config.label, ""),
        mediaMode: cleanText(config.mediaMode, ""),
        element: cleanText(config.element, ""),
        browserPlayable: Boolean(config.browserPlayable || config.browser_playable),
        vendor: cleanText(config.vendor, ""),
        mode: cleanText(config.mode, ""),
        preferredMode: cleanText(config.preferredMode || config.preferred_mode, ""),
        credentialProfile: Boolean(config.credentialProfile || config.credential_profile),
        relayMode: cleanText(config.relayMode || config.relay_mode, ""),
        channel: cleanText(config.channel, ""),
        subtype: cleanText(config.subtype, ""),
        host: cleanText(config.host, ""),
        port: cleanText(config.port, ""),
        rtspPort: cleanText(config.rtspPort || config.rtsp_port, ""),
        streamId: cleanText(config.streamId || config.stream_id, ""),
        ingestUrl: cleanText(config.ingestUrl || config.ingest_url, ""),
        statusUrl: cleanText(config.statusUrl || config.status_url, ""),
        frameUrl: cleanText(config.frameUrl || config.frame_url, ""),
        streamUrl: cleanText(config.streamUrl || config.stream_url, ""),
        replayUrl: cleanText(config.replayUrl || config.replay_url, ""),
        fps: Number.isFinite(Number(config.fps)) ? Number(config.fps) : 0,
        quality: Number.isFinite(Number(config.quality)) ? Number(config.quality) : 0,
        portalUrl: cleanText(config.portalUrl || config.portal_url, ""),
        accessScope: cleanText(config.accessScope || config.access_scope, ""),
        secretPolicy: cleanText(config.secretPolicy || config.secret_policy, ""),
        shareable: Boolean(config.shareable),
        updatedAt: cleanText(config.updatedAt, ""),
      }])
  );
}

export function readWisCameraConfigs(storage = globalThis.localStorage) {
  try {
    const raw = JSON.parse(storage?.getItem?.(WIS_CAMERA_CONFIGS_STORAGE_KEY) || "{}");
    return normalizeWisCameraStoredConfigs(raw);
  } catch {
    return {};
  }
}

export function saveWisCameraConfigs(configs = {}, storage = globalThis.localStorage) {
  try {
    storage?.setItem?.(WIS_CAMERA_CONFIGS_STORAGE_KEY, JSON.stringify(configs || {}));
  } catch {
    // Camera config persistence is a convenience; rendering can continue without it.
  }
}

export function createWisCameraArtifactState(configs = readWisCameraConfigs()) {
  const playbackStates = new Map();
  return {
    wisCameraConfigs: configs && typeof configs === "object" && !Array.isArray(configs) ? configs : {},
    wisCameraStreams: new Map(),
    wisCameraTimers: new Map(),
    wisCameraDebugEvents: new Map(),
    wisCameraRtspRetryAfter: new Map(),
    wisCameraTimelineModes: new Map(),
    wisCameraTimelineOwnerStates: new Map(),
    wisCameraZoomSelections: new Map(),
    wisCameraAudioMuted: new Map(),
    wisCameraQualityModes: new Map(),
    wisCameraQualityPrimed: new Set(),
    wisCameraNotices: new Map(),
    wisCameraRecordedSessions: playbackStates,
    wisCameraPlaybackStates: playbackStates,
    wisCameraPlaybackGenerations: new Map(),
    wisCameraArtifactControllers: new Map(),
    wisCameraRecordedTickTimers: new Map(),
    wisCameraPlaybackRenderTimers: new Map(),
    wisCameraPlaybackAbortControllers: new Map(),
    wisCameraPlaybackObjectUrls: new Map(),
    wisCameraPlaybackLoops: new Map(),
    wisCameraPlaybackPerf: new Map(),
    wisCameraVisibility: new Map(),
    wisCameraVisualScheduler: null,
    wisCameraLastGoodFrames: new Map(),
    wisCameraTimeline: {
      streamId: "",
      mode: "live",
      day: "",
      frames: [],
      range: null,
      availableRange: null,
      loadedAt: 0,
      loadingStartedAt: 0,
      loading: false,
      error: "",
    },
    wisCameraTimelinePendingSeeks: new Map(),
    wisCameraTimelineSelections: new Map(),
  };
}

function endpointPath(endpoints = {}, primaryKey, ...aliases) {
  for (const key of [primaryKey, ...aliases]) {
    const value = cleanText(endpoints?.[key], "");
    if (value) return value;
  }
  return WIS_CAMERA_PUSH_ENDPOINTS[primaryKey] || "";
}

function endpointWithQuery(endpoint = "", params = {}) {
  const path = cleanText(endpoint, "");
  if (!path) return "";
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    const text = cleanText(value, "");
    if (text) query.set(key, text);
  });
  const suffix = query.toString();
  if (!suffix) return path;
  return `${path}${path.includes("?") ? "&" : "?"}${suffix}`;
}

export function wisDefaultPushStreamIdForSlot(slot = "") {
  const cleanSlot = cleanText(slot, "").toLowerCase();
  const numbered = cleanSlot.match(/^cam(?:era)?-?(\d+)$/);
  if (numbered) return `cam-${numbered[1]}`;
  if (["camera", "cam", "dvr", "intelbras"].includes(cleanSlot)) return WIS_CAMERA_DEFAULT_SLOT;
  return "";
}

export function normalizeWisCameraSlot(slot = "", fallback = WIS_CAMERA_DEFAULT_SLOT) {
  const raw = cleanText(slot, "").toLowerCase();
  if (!raw) return cleanText(fallback, WIS_CAMERA_DEFAULT_SLOT);
  const numeric = raw.match(/^\d+$/);
  if (numeric) return `cam-${numeric[0]}`;
  return wisDefaultPushStreamIdForSlot(raw) || raw.replace(/\s+/g, "-");
}

export function cameraSlotFromNode(node = {}, fallback = "camera") {
  const props = node?.props && typeof node.props === "object" ? node.props : {};
  const direct = cleanText(props.slot || props.data?.slot || node?.slot, "");
  if (direct) return direct;
  const id = cleanText(node?.id, "");
  const numbered = id.match(/^cam(?:era)?-?(\d+)/i);
  if (numbered) return `cam-${numbered[1]}`;
  return id.replace(/-(preview|config|button)$/i, "") || fallback;
}

export function cameraFocusFromSurface(surface = null) {
  const state = surface?.state && typeof surface.state === "object" ? surface.state : {};
  const focus = state.cameraFocus || state.camerafocus || state.camera_focus;
  return focus && typeof focus === "object" ? focus : null;
}

export function isWisFocusedCameraSurface(surface = null) {
  if (!surface || typeof surface !== "object") return false;
  const focus = cameraFocusFromSurface(surface);
  if (focus && cleanText(focus.slot, "")) return true;
  const cameras = surface.state?.cameras;
  if (!cameras || typeof cameras !== "object") return false;
  const cameraSlots = Object.keys(cameras).filter(Boolean);
  if (cameraSlots.length !== 1) return false;
  return Boolean(surface.nodes?.some((node) => node?.type === WIS_CAMERA_NODE_TYPE));
}

export function focusedWisCameraSlot(surface = null, fallback = WIS_CAMERA_DEFAULT_SLOT) {
  if (!surface || typeof surface !== "object") return "";
  const focus = cameraFocusFromSurface(surface);
  if (focus && cleanText(focus.slot, "")) return normalizeWisCameraSlot(focus.slot, fallback);
  const cameras = surface.state?.cameras;
  if (cameras && typeof cameras === "object") {
    const cameraSlots = Object.keys(cameras).filter(Boolean);
    if (cameraSlots.length === 1) return normalizeWisCameraSlot(cameraSlots[0], fallback);
  }
  const cameraNode = surface.nodes?.find((node) => node?.type === WIS_CAMERA_NODE_TYPE);
  return cameraNode ? normalizeWisCameraSlot(cameraSlotFromNode(cameraNode), fallback) : "";
}

export function isWisCameraPushConfig(camera = {}) {
  if (!camera || typeof camera !== "object") return false;
  const rawUrl = cleanText(camera.url || camera.ingestUrl || camera.ingest_url, "").toLowerCase();
  return camera.kind === "push"
    || camera.element === "push-frame"
    || camera.mediaMode === WIS_CAMERA_PUSH_MEDIA_MODE
    || camera.mode === "rtmp-push"
    || rawUrl.startsWith("rtmp://");
}

export function createWisCameraPushEndpoints(streamId = WIS_CAMERA_DEFAULT_SLOT, endpoints = {}, options = {}) {
  const cleanStreamId = cleanText(streamId, WIS_CAMERA_DEFAULT_SLOT);
  const replaySeconds = Math.max(1, Math.round(Number(options.replaySeconds || options.seconds || 300) || 300));
  const hasTimelineSeconds = options.timelineSeconds !== undefined || options.seconds !== undefined;
  const timelineSeconds = hasTimelineSeconds
    ? Math.max(60, Math.round(Number(options.timelineSeconds || options.seconds || 600) || 600))
    : "";
  const timelineMode = cleanText(options.mode, "");
  const frameId = cleanText(options.frame || options.frameId || options.id, "");
  const fromMs = cleanText(options.fromMs || options.from_ms || options.timestampMs || options.timestamp_ms, "");
  const playbackFps = cleanText(options.fps || options.playbackFps || options.playback_fps, "");
  const playbackFollow = options.follow === undefined ? "" : (options.follow ? "1" : "0");
  return {
    statusUrl: endpointWithQuery(endpointPath(endpoints, "status", "pushStatus", "statusUrl"), { stream_id: cleanStreamId }),
    frameUrl: endpointWithQuery(endpointPath(endpoints, "frame", "pushFrame", "frameUrl"), { stream_id: cleanStreamId }),
    streamUrl: endpointWithQuery(endpointPath(endpoints, "stream", "pushStream", "streamUrl"), { stream_id: cleanStreamId }),
    replayUrl: endpointWithQuery(endpointPath(endpoints, "replay", "pushReplay", "replayUrl"), { stream_id: cleanStreamId, seconds: replaySeconds }),
    playbackUrl: endpointWithQuery(endpointPath(endpoints, "playback", "pushPlayback", "playbackUrl"), {
      stream_id: cleanStreamId,
      from_ms: fromMs,
      frame: frameId,
      fps: playbackFps,
      follow: playbackFollow,
    }),
    timelineUrl: endpointWithQuery(endpointPath(endpoints, "timeline", "pushTimeline", "timelineUrl"), {
      stream_id: cleanStreamId,
      mode: timelineMode,
      seconds: timelineSeconds,
    }),
    archiveFrameUrl: endpointWithQuery(endpointPath(endpoints, "archiveFrame", "pushArchiveFrame", "archiveFrameUrl"), {
      stream_id: cleanStreamId,
      frame: frameId,
    }),
  };
}

export function createWisCameraPushConfig({
  slot = WIS_CAMERA_DEFAULT_SLOT,
  streamId = "",
  label = "DVR RTMP push",
  vendor = "intelbras",
  channel = "",
  ingestUrl = "",
  urls = {},
  fps = 0,
  quality = 0,
  updatedAt = "",
  accessScope = "dvr-outbound-push",
  secretPolicy = "rtmp-stream-key",
  shareable = false,
} = {}) {
  const cleanSlot = normalizeWisCameraSlot(slot, WIS_CAMERA_DEFAULT_SLOT);
  const actualStreamId = cleanText(streamId, wisDefaultPushStreamIdForSlot(cleanSlot) || cleanSlot);
  const urlConfig = urls && typeof urls === "object" ? urls : {};
  const endpointUrls = createWisCameraPushEndpoints(actualStreamId, urlConfig.endpoints || {});
  return {
    kind: "push",
    label: cleanText(label, "DVR RTMP push"),
    mediaMode: WIS_CAMERA_PUSH_MEDIA_MODE,
    element: "push-frame",
    browserPlayable: true,
    vendor: cleanText(vendor, ""),
    mode: "rtmp-push",
    channel: cleanText(channel, ""),
    streamId: actualStreamId,
    ingestUrl: cleanText(ingestUrl, ""),
    statusUrl: cleanText(urlConfig.statusUrl || urlConfig.status || "", endpointUrls.statusUrl),
    frameUrl: cleanText(urlConfig.frameUrl || urlConfig.frame || "", endpointUrls.frameUrl),
    streamUrl: cleanText(urlConfig.streamUrl || urlConfig.stream || "", endpointUrls.streamUrl),
    replayUrl: cleanText(urlConfig.replayUrl || urlConfig.replay || "", endpointUrls.replayUrl),
    fps: Number.isFinite(Number(fps)) ? Number(fps) : 0,
    quality: Number.isFinite(Number(quality)) ? Number(quality) : 0,
    accessScope: cleanText(accessScope, ""),
    secretPolicy: cleanText(secretPolicy, ""),
    shareable: Boolean(shareable),
    updatedAt: cleanText(updatedAt, ""),
  };
}

export function createWisDefaultPushCameraConfigForSlot(slot = "", options = {}) {
  const cleanSlot = normalizeWisCameraSlot(slot, WIS_CAMERA_DEFAULT_SLOT);
  const defaultStreamId = wisDefaultPushStreamIdForSlot(cleanSlot);
  const streamId = cleanText(options.streamId || options.stream_id, defaultStreamId);
  if (!streamId) return {};
  return createWisCameraPushConfig({
    slot: cleanSlot,
    streamId,
    label: cleanText(options.label, "DVR RTMP push"),
    vendor: cleanText(options.vendor, "intelbras"),
    channel: cleanText(options.channel, ""),
    ingestUrl: cleanText(options.ingestUrl || options.ingest_url, ""),
    urls: {
      endpoints: options.endpoints || {},
      ...((options.urls && typeof options.urls === "object") ? options.urls : {}),
    },
    fps: Number.isFinite(Number(options.fps)) ? Number(options.fps) : 0,
    quality: Number.isFinite(Number(options.quality)) ? Number(options.quality) : 0,
    updatedAt: cleanText(options.updatedAt || options.updated_at, ""),
    accessScope: cleanText(options.accessScope || options.access_scope, "dvr-outbound-push"),
    secretPolicy: cleanText(options.secretPolicy || options.secret_policy, "rtmp-stream-key"),
    shareable: Boolean(options.shareable),
  });
}

export function normalizeWisCameraConfigForSlot(slot, camera = {}, options = {}) {
  if (!camera || typeof camera !== "object") return {};
  const cleanSlot = normalizeWisCameraSlot(slot, WIS_CAMERA_DEFAULT_SLOT);
  const streamId = cleanText(camera.streamId || camera.stream_id, "") || wisDefaultPushStreamIdForSlot(cleanSlot);
  const rawUrl = cleanText(camera.url || camera.ingestUrl || camera.ingest_url, "");
  const isPush = isWisCameraPushConfig(camera);
  const isIntelbrasCam1Portal = streamId === WIS_CAMERA_DEFAULT_SLOT
    && cleanText(camera.vendor, "").toLowerCase() === "intelbras"
    && ["1", "01", ""].includes(cleanText(camera.channel, ""))
    && ["portal", "dvr-portal", "url"].includes(cleanText(camera.mode || camera.mediaMode || camera.kind, "").toLowerCase());
  if (isIntelbrasCam1Portal) {
    return {
      ...createWisDefaultPushCameraConfigForSlot(WIS_CAMERA_DEFAULT_SLOT, { endpoints: options.endpoints || {} }),
      label: "Intelbras CAM 1 RTMP push",
    };
  }
  if (!isPush) return camera;
  const actualStreamId = streamId || WIS_CAMERA_DEFAULT_SLOT;
  const endpointUrls = createWisCameraPushEndpoints(actualStreamId, options.endpoints || {});
  return {
    ...camera,
    kind: "push",
    label: cleanText(camera.label, "DVR RTMP push"),
    mediaMode: WIS_CAMERA_PUSH_MEDIA_MODE,
    element: "push-frame",
    browserPlayable: true,
    streamId: actualStreamId,
    ingestUrl: cleanText(camera.ingestUrl || camera.ingest_url, rawUrl),
    statusUrl: cleanText(camera.statusUrl || camera.status_url, endpointUrls.statusUrl),
    frameUrl: cleanText(camera.frameUrl || camera.frame_url, endpointUrls.frameUrl),
    streamUrl: cleanText(camera.streamUrl || camera.stream_url, endpointUrls.streamUrl),
    replayUrl: cleanText(camera.replayUrl || camera.replay_url, endpointUrls.replayUrl),
  };
}

export function wisCameraBaseStreamId(slot, camera = {}) {
  return cleanText(camera.streamId || camera.stream_id || slot, WIS_CAMERA_DEFAULT_SLOT);
}

export function wisCameraQualityStreamId(slot, camera = {}, qualityMode = "primary") {
  const base = wisCameraBaseStreamId(slot, camera);
  const mode = cleanText(qualityMode, "primary");
  if (mode === "extra") {
    return cleanText(camera.extraStreamId || camera.extra_stream_id || camera.subStreamId || camera.sub_stream_id, `${base}-extra`);
  }
  return cleanText(camera.primaryStreamId || camera.primary_stream_id, base);
}

export function wisCameraPushFramePollMs(camera = {}, options = {}) {
  const fps = Number(camera.fps || camera.frameFps || camera.frame_fps || options.defaultFps || 5);
  const minFps = Number(options.minFps || 2);
  const maxFps = Number(options.maxFps || 15);
  const safeFps = clamp(Number.isFinite(fps) && fps > 0 ? fps : 5, minFps, maxFps);
  return Math.round(1000 / safeFps);
}

export function wisCameraTimelineFrameAtRatio(frames = [], ratio = 1) {
  if (!Array.isArray(frames) || !frames.length) return null;
  const boundedRatio = clamp(Number(ratio), 0, 1);
  const maxIndex = Math.max(0, frames.length - 1);
  return frames[Math.round(boundedRatio * maxIndex)] || null;
}

function timelineRangeMs(range = null) {
  if (!range || typeof range !== "object") return null;
  const start = Number(range.start_ms ?? range.startMs);
  const end = Number(range.end_ms ?? range.endMs);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start === end) return null;
  return {
    start: Math.min(start, end),
    end: Math.max(start, end),
  };
}

function timelineFrameTimestampMs(frame = null) {
  if (!frame || typeof frame !== "object") return null;
  const timestampMs = Number(frame.timestamp_ms ?? frame.timestampMs);
  return Number.isFinite(timestampMs) ? timestampMs : null;
}

function defaultAnimationFrameEnv(env = globalThis) {
  const request = typeof env.requestAnimationFrame === "function"
    ? env.requestAnimationFrame.bind(env)
    : ((callback) => env.setTimeout?.(() => callback(wisCameraMonotonicNow()), 16));
  const cancel = typeof env.cancelAnimationFrame === "function"
    ? env.cancelAnimationFrame.bind(env)
    : ((id) => env.clearTimeout?.(id));
  return { request, cancel };
}

export function claimMediaWriter(image, owner = {}) {
  if (!image) return false;
  const generation = Math.max(0, Math.round(Number(owner.generation || 0)));
  const nextOwner = {
    kind: cleanText(owner.kind, "unknown"),
    streamId: cleanText(owner.streamId, ""),
    sessionId: cleanText(owner.sessionId, ""),
    generation,
  };
  const previous = mediaWriters.get(image);
  if (previous && Number(previous.generation || 0) > nextOwner.generation) return false;
  if (
    previous
    && previous.kind === nextOwner.kind
    && previous.streamId === nextOwner.streamId
    && previous.sessionId === nextOwner.sessionId
    && Number(previous.generation || 0) === nextOwner.generation
    && image.dataset?.wisMediaOwner === nextOwner.kind
    && image.dataset?.wisMediaGeneration === String(nextOwner.generation)
  ) {
    return true;
  }
  const previousStreamOwner = nextOwner.streamId ? mediaStreamWriters.get(nextOwner.streamId) : null;
  if (previousStreamOwner) {
    const previousGeneration = Number(previousStreamOwner.generation || 0);
    const previousKind = cleanText(previousStreamOwner.kind, "");
    const nextKind = cleanText(nextOwner.kind, "");
    if (previousGeneration > nextOwner.generation) return false;
    if (previousGeneration === nextOwner.generation && previousKind !== nextKind && previousKind.startsWith("recorded") && nextKind === "live") {
      return false;
    }
  }
  mediaWriters.set(image, nextOwner);
  if (nextOwner.streamId) mediaStreamWriters.set(nextOwner.streamId, nextOwner);
  image.dataset.wisMediaOwner = nextOwner.kind;
  image.dataset.wisMediaGeneration = String(nextOwner.generation);
  image.dataset.wisMediaStreamId = nextOwner.streamId;
  return true;
}

export function isMediaWriterCurrent(image, owner = {}) {
  const current = image ? mediaWriters.get(image) : null;
  const generation = Math.max(0, Math.round(Number(owner.generation || 0)));
  const kind = cleanText(owner.kind, "unknown");
  const streamId = cleanText(owner.streamId, "");
  const streamOwner = streamId ? mediaStreamWriters.get(streamId) : null;
  return Boolean(
    current
    && current.kind === kind
    && Number(current.generation || 0) === generation
    && (!streamId || (
      streamOwner
      && streamOwner.kind === kind
      && Number(streamOwner.generation || 0) === generation
    ))
    && image?.dataset?.wisMediaOwner === kind
    && image?.dataset?.wisMediaGeneration === String(generation)
  );
}

export function mediaWriterData(image) {
  return image ? mediaWriters.get(image) || null : null;
}

export function mediaStreamWriterData(streamId = "") {
  const key = cleanText(streamId, "");
  return key ? mediaStreamWriters.get(key) || null : null;
}

export function releaseMediaStreamWriter(streamId = "", owner = {}) {
  const key = cleanText(streamId, "");
  if (!key) return false;
  const current = mediaStreamWriters.get(key);
  if (!current) return false;
  const kind = cleanText(owner.kind, "");
  const generation = Number(owner.generation ?? owner.playbackGeneration ?? owner.seekToken);
  if (kind && current.kind !== kind) return false;
  if (Number.isFinite(generation) && generation > 0 && Number(current.generation || 0) !== Math.round(generation)) return false;
  mediaStreamWriters.delete(key);
  return true;
}

function setClassToken(element, token = "", enabled = true) {
  if (!element || !token) return;
  try {
    element.classList?.[enabled ? "add" : "remove"]?.(token);
  } catch {
    // Some tests provide a small classList shim; className is updated below.
  }
  const tokens = new Set(String(element.className || "").split(/\s+/).filter(Boolean));
  if (enabled) tokens.add(token);
  else tokens.delete(token);
  element.className = Array.from(tokens).join(" ");
}

function copyWisCameraDataset(target = null, source = null) {
  if (!target?.dataset || !source?.dataset) return;
  Object.keys(target.dataset).forEach((key) => {
    if (key.startsWith("wis") && !["wisBufferId", "wisBufferRole"].includes(key)) {
      delete target.dataset[key];
    }
  });
  Object.entries(source.dataset).forEach(([key, value]) => {
    if (key.startsWith("wis") && !["wisBufferId", "wisBufferRole"].includes(key)) {
      target.dataset[key] = value;
    }
  });
}

function copyWisCameraImagePresentation(target = null, source = null) {
  if (!target || !source) return;
  target.className = source.className || target.className || "wis-camera-image";
  target.alt = source.alt || target.alt || "";
  target.decoding = source.decoding || "async";
  target.loading = source.loading || "eager";
  target.fetchPriority = source.fetchPriority || "high";
}

function setWisCameraBufferRole(image = null, role = "back") {
  if (!image) return;
  if (!image.dataset) image.dataset = {};
  image.dataset.wisBufferRole = role;
  setClassToken(image, "wis-camera-buffer", true);
  setClassToken(image, "is-buffer-front", role === "front");
  setClassToken(image, "is-buffer-back", role === "back");
  try {
    image.setAttribute?.("aria-hidden", role === "back" ? "true" : "false");
  } catch {
    // Optional DOM nicety only.
  }
}

function wisCameraImageBufferState(image = null) {
  return image ? mediaImageBuffers.get(image) || null : null;
}

function visibleWisCameraImage(image = null) {
  const state = wisCameraImageBufferState(image);
  return state?.front || image;
}

function ensureWisCameraImageBuffer(element = null, image = null, owner = {}, options = {}) {
  const front = visibleWisCameraImage(image);
  const documentRef = options.document || element?.ownerDocument || globalThis.document;
  if (!element || !front || !documentRef?.createElement) return null;
  let state = wisCameraImageBufferState(front) || wisCameraImageBufferState(image);
  if (!state) {
    state = {
      id: `wis-camera-buffer-${++mediaImageBufferSeq}`,
      element,
      front,
      back: null,
      lastSrcChangeAtMs: 0,
      lastDecodeAtMs: 0,
      lastActivatedAtMs: 0,
    };
  }
  state.element = element;
  state.front = visibleWisCameraImage(state.front || front);
  if (!state.back || state.back === state.front || state.back.isConnected === false) {
    const existingBack = Array.from(element.querySelectorAll?.(".wis-camera-image, .wis-camera-video") || [])
      .find((candidate) => candidate?.tagName === "IMG" && candidate !== state.front && wisCameraImageBufferState(candidate) === state);
    state.back = existingBack || documentRef.createElement("img");
  }
  copyWisCameraImagePresentation(state.back, state.front);
  [state.front, state.back].forEach((bufferImage) => {
    if (!bufferImage) return;
    if (!bufferImage.dataset) bufferImage.dataset = {};
    bufferImage.dataset.wisBufferId = state.id;
    mediaImageBuffers.set(bufferImage, state);
    claimMediaWriter(bufferImage, owner);
  });
  setWisCameraBufferRole(state.front, "front");
  setWisCameraBufferRole(state.back, "back");
  try {
    element.append?.(state.front, state.back);
  } catch {
    // Detached test doubles may not implement append fully.
  }
  return state;
}

function activateWisCameraImageBuffer(state = null, nextFront = null, owner = {}) {
  if (!state || !nextFront || nextFront !== state.back) return visibleWisCameraImage(nextFront || state?.front);
  const previousFront = state.front;
  state.front = nextFront;
  state.back = previousFront;
  copyWisCameraDataset(state.back, state.front);
  [state.front, state.back].forEach((bufferImage) => {
    if (!bufferImage) return;
    mediaImageBuffers.set(bufferImage, state);
    claimMediaWriter(bufferImage, owner);
  });
  setWisCameraBufferRole(state.front, "front");
  setWisCameraBufferRole(state.back, "back");
  state.lastActivatedAtMs = wisCameraMonotonicNow();
  try {
    state.element?.append?.(state.front, state.back);
  } catch {
    // Keeping z-index roles is enough if append is unavailable.
  }
  return state.front;
}

function waitForImageLoad(image) {
  return new Promise((resolve, reject) => {
    image.addEventListener("load", resolve, { once: true });
    image.addEventListener("error", reject, { once: true });
  });
}

function wisCameraSrcKind(src = "") {
  const value = cleanText(src, "");
  if (!value) return "empty";
  if (value.startsWith("blob:")) return "blob";
  if (value.startsWith("data:image/")) return "data";
  if (/^https?:\/\//i.test(value)) return "remote";
  if (value.startsWith("/")) return "same-origin";
  return "relative";
}

function parseCssRgb(value = "") {
  const match = String(value || "").match(/rgba?\(([^)]+)\)/i);
  if (!match) return null;
  const parts = match[1].split(",").map((part) => Number(part.trim()));
  if (parts.length < 3 || parts.slice(0, 3).some((part) => !Number.isFinite(part))) return null;
  return {
    r: clamp(parts[0], 0, 255),
    g: clamp(parts[1], 0, 255),
    b: clamp(parts[2], 0, 255),
    a: Number.isFinite(parts[3]) ? clamp(parts[3], 0, 1) : 1,
  };
}

function cssDistance(left = null, right = null) {
  if (!left || !right) return Infinity;
  return Math.sqrt(
    ((left.r - right.r) ** 2)
    + ((left.g - right.g) ** 2)
    + ((left.b - right.b) ** 2)
  );
}

function computedWisCameraStyle(env = globalThis, element = null) {
  try {
    return env.getComputedStyle?.(element) || globalThis.getComputedStyle?.(element) || null;
  } catch {
    return null;
  }
}

function wisCameraLayerSummary(env = globalThis, media = null) {
  const style = computedWisCameraStyle(env, media);
  return {
    tagName: cleanText(media?.tagName, ""),
    owner: cleanText(media?.dataset?.wisMediaOwner, ""),
    role: cleanText(media?.dataset?.wisBufferRole, ""),
    srcKind: wisCameraSrcKind(media?.currentSrc || media?.src || media?.dataset?.wisLastGoodSrc),
    timestamp: Number(media?.dataset?.wisPlaybackFrameMs || 0) || null,
    complete: media?.tagName === "IMG" ? media.complete !== false : null,
    naturalWidth: Number(media?.naturalWidth || media?.videoWidth || 0),
    naturalHeight: Number(media?.naturalHeight || media?.videoHeight || 0),
    opacity: cleanText(style?.opacity, ""),
    display: cleanText(style?.display, ""),
    visibility: cleanText(style?.visibility, ""),
    filter: cleanText(style?.filter, ""),
    transform: cleanText(style?.transform, ""),
    zIndex: cleanText(style?.zIndex, ""),
  };
}

function sampleWisCameraImageCrop(env = globalThis, image = null) {
  const documentRef = env.document || globalThis.document;
  if (!documentRef?.createElement || !image || image.complete === false) return null;
  const width = Number(image.naturalWidth || image.videoWidth || 0);
  const height = Number(image.naturalHeight || image.videoHeight || 0);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return null;
  const canvas = documentRef.createElement("canvas");
  canvas.width = 12;
  canvas.height = 12;
  const context = canvas.getContext?.("2d", { willReadFrequently: true });
  if (!context) return null;
  try {
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let alphaTotal = 0;
    let lumaTotal = 0;
    let redTotal = 0;
    let greenTotal = 0;
    let blueTotal = 0;
    const count = Math.max(1, pixels.length / 4);
    for (let index = 0; index < pixels.length; index += 4) {
      const red = pixels[index];
      const green = pixels[index + 1];
      const blue = pixels[index + 2];
      const alpha = pixels[index + 3];
      redTotal += red;
      greenTotal += green;
      blueTotal += blue;
      alphaTotal += alpha;
      lumaTotal += (red * 0.2126) + (green * 0.7152) + (blue * 0.0722);
    }
    return {
      alpha: alphaTotal / count,
      luma: lumaTotal / count,
      rgb: {
        r: redTotal / count,
        g: greenTotal / count,
        b: blueTotal / count,
        a: (alphaTotal / count) / 255,
      },
    };
  } catch {
    return null;
  }
}

function detectWisCameraVisualBlink(image = null, owner = {}, options = {}) {
  const env = options.env || globalThis;
  const state = wisCameraImageBufferState(image);
  const visible = visibleWisCameraImage(image);
  const element = options.element || state?.element || visible?.parentElement || null;
  if (!visible || visible.isConnected === false) return null;
  const style = computedWisCameraStyle(env, visible);
  const backgroundStyle = computedWisCameraStyle(env, element);
  const backgroundColor = cleanText(backgroundStyle?.backgroundColor, "");
  const naturalWidth = Number(visible.naturalWidth || 0);
  const naturalHeight = Number(visible.naturalHeight || 0);
  const imgComplete = visible?.tagName === "IMG" ? visible.complete !== false : true;
  const opacity = cleanText(style?.opacity, "1");
  const display = cleanText(style?.display, "block");
  const visibility = cleanText(style?.visibility, "visible");
  const filter = cleanText(style?.filter, "none");
  const transform = cleanText(style?.transform, "none");
  const styleSignature = [opacity, display, visibility, filter, transform].join("|");
  const sampleKey = state || visible;
  const previousSample = mediaVisualSamples.get(sampleKey);
  mediaVisualSamples.set(sampleKey, {
    styleSignature,
    timestamp: Number(visible.dataset?.wisPlaybackFrameMs || 0),
    sampledAtMs: wisCameraMonotonicNow(),
  });
  const crop = sampleWisCameraImageCrop(env, visible);
  const backgroundRgb = parseCssRgb(backgroundColor);
  const blackCrop = Boolean(crop && crop.alpha > 220 && crop.luma < 8);
  const transparentCrop = Boolean(crop && crop.alpha < 12);
  const backgroundColoredCrop = Boolean(crop && backgroundRgb?.a > 0 && crop.alpha > 220 && cssDistance(crop.rgb, backgroundRgb) < 8);
  const hiddenStyle = Number(opacity) < 0.05 || display === "none" || visibility === "hidden" || visibility === "collapse";
  const invalidImage = visible?.tagName === "IMG" && (!imgComplete || naturalWidth <= 0 || naturalHeight <= 0);
  const blinkLike = blackCrop || transparentCrop || backgroundColoredCrop || hiddenStyle || invalidImage;
  if (!blinkLike) return null;
  const nowMs = wisCameraMonotonicNow();
  const layers = Array.from(element?.querySelectorAll?.(".wis-camera-image, .wis-camera-video") || [])
    .map((layer) => wisCameraLayerSummary(env, layer));
  return {
    cameraId: cleanText(options.cameraId || options.streamId || owner.streamId, ""),
    mode: cleanText(options.mode, "recorded"),
    generation: Number(owner.generation || options.generation || 0),
    visibleOwner: cleanText(visible.dataset?.wisMediaOwner, ""),
    visibleSrcKind: wisCameraSrcKind(mediaElementRenderedSrc(visible)),
    visibleTimestamp: Number(visible.dataset?.wisPlaybackFrameMs || 0) || null,
    imgComplete,
    naturalWidth,
    naturalHeight,
    opacity,
    display,
    visibility,
    filter,
    transform,
    backgroundColor,
    lastSrcChangeAgeMs: state?.lastSrcChangeAtMs ? Math.max(0, Math.round(nowMs - state.lastSrcChangeAtMs)) : null,
    lastDecodeAgeMs: state?.lastDecodeAtMs ? Math.max(0, Math.round(nowMs - state.lastDecodeAtMs)) : null,
    layers,
    phase: cleanText(options.phase, ""),
    blackCrop,
    transparentCrop,
    backgroundColoredCrop,
    cssChanged: Boolean(previousSample && previousSample.styleSignature !== styleSignature),
    previousVisibleTimestamp: Number(previousSample?.timestamp || 0) || null,
    hasLiveAndRecordedLayers: layers.some((layer) => layer.owner === "live") && layers.some((layer) => layer.owner === "recorded-playback"),
  };
}

function emitWisCameraVisualBlinkIfDetected(image = null, owner = {}, options = {}) {
  const payload = detectWisCameraVisualBlink(image, owner, options);
  if (!payload) return;
  try {
    options.onVisualBlink?.(payload);
  } catch {
    // Visual diagnostics should never affect playback.
  }
}

export async function decodeAndSwapImage(image, sourceUrl, owner = {}, options = {}) {
  const env = options.env || globalThis;
  const url = cleanText(sourceUrl, "");
  if (!image || !url) return false;
  const element = options.element || image.parentElement || null;
  const bufferState = ensureWisCameraImageBuffer(element, image, owner, {
    document: options.document || env.document,
  });
  if (!bufferState) return false;
  const currentImage = visibleWisCameraImage(image);
  if (!isMediaWriterCurrent(image, owner) && !isMediaWriterCurrent(currentImage, owner)) {
    traceWisCameraBoundary("recorded.commit.rejected", {
      functionName: "decodeAndSwapImage",
      streamId: options.streamId || owner.streamId || "",
      generation: Number(options.generation ?? owner.generation ?? 0),
      ownerKind: owner.kind || "",
      sourceUrl: url,
      reason: "stale-before-decode",
      imageOwner: image.dataset?.wisMediaOwner || "",
      visibleLayerOwner: currentImage?.dataset?.wisMediaOwner || "",
    });
    options.onStale?.();
    return false;
  }
  const targetImage = bufferState.back;
  if (!targetImage) return false;
  copyWisCameraImagePresentation(targetImage, currentImage || image);
  mediaImageBuffers.set(targetImage, bufferState);
  claimMediaWriter(targetImage, owner);
  setWisCameraBufferRole(targetImage, "back");
  const loadPromise = waitForImageLoad(targetImage);
  options.beforeSwap?.(targetImage);
  traceWisCameraBoundary("decode.started", {
    functionName: "decodeAndSwapImage",
    streamId: options.streamId || owner.streamId || "",
    generation: Number(options.generation ?? owner.generation ?? 0),
    mode: options.mode || "",
    ownerKind: owner.kind || "",
    sourceUrl: url,
    domLayer: targetImage.dataset?.wisBufferRole || "back",
    imageElement: {
      tagName: targetImage.tagName,
      className: targetImage.className,
      owner: targetImage.dataset?.wisMediaOwner || "",
    },
  });
  const srcAssignedAtMs = wisCameraMonotonicNow();
  targetImage.dataset.wisLastSrcChangeAtMs = String(Math.round(srcAssignedAtMs));
  bufferState.lastSrcChangeAtMs = srcAssignedAtMs;
  targetImage.src = url;
  emitWisCameraVisualBlinkIfDetected(image, owner, {
    ...options,
    element,
    phase: "src-assigned",
  });
  try {
    if (typeof targetImage.decode === "function") await targetImage.decode();
    else await loadPromise;
  } catch (error) {
    traceWisCameraBoundary("decode.fail", {
      functionName: "decodeAndSwapImage",
      streamId: options.streamId || owner.streamId || "",
      generation: Number(options.generation ?? owner.generation ?? 0),
      ownerKind: owner.kind || "",
      sourceUrl: url,
      error: error?.message || String(error),
      recoveredByLoadEvent: targetImage.complete !== false && Number(targetImage.naturalWidth || 0) > 0,
    });
    if (targetImage.complete === false || Number(targetImage.naturalWidth || 0) <= 0) await loadPromise;
  }
  if (targetImage.tagName === "IMG" && (targetImage.complete === false || Number(targetImage.naturalWidth || 0) <= 0 || Number(targetImage.naturalHeight || 0) <= 0)) {
    traceWisCameraBoundary("decode.fail", {
      functionName: "decodeAndSwapImage",
      streamId: options.streamId || owner.streamId || "",
      generation: Number(options.generation ?? owner.generation ?? 0),
      ownerKind: owner.kind || "",
      sourceUrl: url,
      error: "Decoded camera frame has no visible dimensions",
      naturalWidth: Number(targetImage.naturalWidth || 0),
      naturalHeight: Number(targetImage.naturalHeight || 0),
    });
    throw new Error("Decoded camera frame has no visible dimensions");
  }
  traceWisCameraBoundary("decode.success", {
    functionName: "decodeAndSwapImage",
    streamId: options.streamId || owner.streamId || "",
    generation: Number(options.generation ?? owner.generation ?? 0),
    mode: options.mode || "",
    ownerKind: owner.kind || "",
    sourceUrl: url,
    fetchResult: "non-empty",
    naturalWidth: Number(targetImage.naturalWidth || 0),
    naturalHeight: Number(targetImage.naturalHeight || 0),
    domLayer: targetImage.dataset?.wisBufferRole || "back",
  });
  const decodeCompletedAtMs = wisCameraMonotonicNow();
  targetImage.dataset.wisLastDecodeAtMs = String(Math.round(decodeCompletedAtMs));
  bufferState.lastDecodeAtMs = decodeCompletedAtMs;
  emitWisCameraVisualBlinkIfDetected(image, owner, {
    ...options,
    element,
    phase: "decoded",
  });
  if (typeof options.isCurrent === "function" && !options.isCurrent()) {
    traceWisCameraBoundary("recorded.commit.rejected", {
      functionName: "decodeAndSwapImage",
      streamId: options.streamId || owner.streamId || "",
      generation: Number(options.generation ?? owner.generation ?? 0),
      ownerKind: owner.kind || "",
      sourceUrl: url,
      reason: "isCurrent-false-after-decode",
      visibleLayerOwner: visibleWisCameraImage(image)?.dataset?.wisMediaOwner || image.dataset?.wisMediaOwner || "",
    });
    options.onStale?.();
    if (options.revokeOnStale) {
      try {
        (env.URL || globalThis.URL)?.revokeObjectURL?.(url);
      } catch {
        // Best effort.
      }
    }
    return false;
  }
  if (!isMediaWriterCurrent(image, owner) && !isMediaWriterCurrent(currentImage, owner) && !isMediaWriterCurrent(targetImage, owner)) {
    traceWisCameraBoundary("recorded.commit.rejected", {
      functionName: "decodeAndSwapImage",
      streamId: options.streamId || owner.streamId || "",
      generation: Number(options.generation ?? owner.generation ?? 0),
      ownerKind: owner.kind || "",
      sourceUrl: url,
      reason: "stale-writer-after-decode",
      visibleLayerOwner: visibleWisCameraImage(image)?.dataset?.wisMediaOwner || image.dataset?.wisMediaOwner || "",
      targetOwner: targetImage.dataset?.wisMediaOwner || "",
    });
    options.onStale?.();
    if (options.revokeOnStale) {
      try {
        (env.URL || globalThis.URL)?.revokeObjectURL?.(url);
      } catch {
        // Best effort.
      }
    }
    return false;
  }
  traceWisCameraBoundary("recorded.commit.attempted", {
    functionName: "decodeAndSwapImage",
    streamId: options.streamId || owner.streamId || "",
    generation: Number(options.generation ?? owner.generation ?? 0),
    ownerKind: owner.kind || "",
    sourceUrl: url,
    domLayer: targetImage.dataset?.wisBufferRole || "back",
    imageElement: {
      tagName: targetImage.tagName,
      className: targetImage.className,
      owner: targetImage.dataset?.wisMediaOwner || "",
    },
  });
  activateWisCameraImageBuffer(bufferState, targetImage, owner);
  options.onSwap?.(visibleWisCameraImage(image));
  traceWisCameraBoundary("recorded.commit.accepted", {
    functionName: "decodeAndSwapImage",
    streamId: options.streamId || owner.streamId || "",
    generation: Number(options.generation ?? owner.generation ?? 0),
    ownerKind: owner.kind || "",
    sourceUrl: url,
    visibleLayerOwner: visibleWisCameraImage(image)?.dataset?.wisMediaOwner || image.dataset?.wisMediaOwner || "",
    visibleFrameMs: visibleWisCameraImage(image)?.dataset?.wisPlaybackFrameMs || image.dataset?.wisPlaybackFrameMs || "",
    domLayer: visibleWisCameraImage(image)?.dataset?.wisBufferRole || "",
  });
  emitWisCameraVisualBlinkIfDetected(image, owner, {
    ...options,
    element,
    phase: "swapped",
  });
  return true;
}

export function createCameraArtifactController({
  artifactId = WIS_CAMERA_DEFAULT_SLOT,
  documentId = "main",
  canvas = null,
  timelineElement = null,
  dispatchWisPatch = null,
  recordEvent = null,
  env = globalThis,
  diagnostics = true,
  getTimelineModel = null,
  getPlaybackState = null,
  findSegmentForTime = null,
  loadSegment = null,
  drawFrameAt = null,
  updateTimelineVisualOnly = null,
  previewTimelineTarget = null,
  resetTimelinePreview = null,
  onTimelineLoadNeeded = null,
  advanceSegmentIfNeeded = null,
  onSeekPending = null,
} = {}) {
  let currentArtifactId = cleanText(artifactId, WIS_CAMERA_DEFAULT_SLOT);
  let currentDocumentId = cleanText(documentId, "main");
  let currentCanvas = canvas || null;
  let currentTimelineElement = timelineElement || null;
  let currentTimeline = null;
  let currentFrames = [];
  let currentMode = "live";
  let playbackGeneration = 0;
  let activeSeek = null;
  let currentSegment = null;
  let renderLoopId = null;
  let renderLoopCancel = null;
  let clockLoopId = null;
  let clockLoopCancel = null;
  let activeAbortController = null;
  let isSyncingTimelineFromPlayback = false;
  let userScrubbing = {
    active: false,
    pointerId: 0,
    target: null,
  };
  let scrubOwner = null;
  let pendingTimelineElement = null;
  let suppressClickUntil = 0;
  let lastRealUserCommitAt = 0;
  let persistedSeekTimestampMs = 0;
  const recentSeekEvents = [];
  const recentDebugEvents = [];
  const lastDebugLogAt = new Map();
  let lastPlaybackPatchSignature = "";
  let emergencyStopped = false;
  const removeTimelineListeners = [];
  const cleanupStack = [];
  const playbackClock = {
    mode: "live",
    source: "synthetic",
    anchorWallTimeMs: 0,
    anchorRecordingTimeMs: 0,
    displayedRecordingTimeMs: 0,
    rate: 1,
    targetTimeMs: 0,
    generation: 0,
  };
  const raf = defaultAnimationFrameEnv(env);

  function contextForLog(detail = {}) {
    return {
      artifactId: currentArtifactId,
      documentId: currentDocumentId,
      generation: Number(detail.generation ?? playbackGeneration),
      source: cleanText(detail.source || activeSeek?.source, ""),
      reason: cleanText(detail.reason || activeSeek?.reason, ""),
      timestampMs: Number.isFinite(Number(detail.timestampMs)) ? Number(detail.timestampMs) : Number(playbackClock.targetTimeMs || 0),
      renderLoopId: renderLoopId ?? null,
      activeSeekToken: activeSeek?.generation ?? null,
      mode: cleanText(detail.mode || playbackClock.mode, "live"),
      ...detail,
    };
  }

  function emergencyStopCameraRuntime(reason = "camera-emergency-stop") {
    if (emergencyStopped) return;
    emergencyStopped = true;
    stopRenderLoop(reason);
    stopClockLoop(reason);
    abortPreviousLoads(reason);
    activeSeek = null;
    currentSegment = null;
    playbackClock.mode = "error";
  }

  function logCamera(type, detail = {}, options = {}) {
    const payload = contextForLog(detail);
    const now = typeof env.performance?.now === "function" ? env.performance.now() : wisCameraMonotonicNow();
    const sampleMs = Number(options.sampleMs || 0);
    if (sampleMs > 0) {
      const lastAt = Number(lastDebugLogAt.get(type) || 0);
      if (lastAt > 0 && now - lastAt < sampleMs) return payload;
      lastDebugLogAt.set(type, now);
    }
    const entry = {
      t: now,
      event: type,
      artifactId: payload.artifactId,
      generation: payload.generation,
      source: payload.source,
      reason: payload.reason,
      mode: payload.mode,
      renderLoopId: payload.renderLoopId,
      seekTargetTimeMs: payload.seekTargetTimeMs ?? payload.targetTimeMs ?? payload.target ?? payload.timestampMs,
      computedPlaybackTimeMs: payload.computedPlaybackTimeMs ?? payload.timestampMs,
    };
    recentDebugEvents.push(entry);
    while (recentDebugEvents.length > 200) recentDebugEvents.shift();
    const sameRecent = recentDebugEvents.filter((event) => event.event === type && now - event.t < 1000);
    if (sameRecent.length > 20) {
      try {
        env.console?.error?.("camera infinite loop suspected", {
          event: type,
          countLastSecond: sameRecent.length,
          recentDebugEvents: recentDebugEvents.slice(-40),
        });
      } catch {
        // Diagnostics must never affect playback.
      }
      emergencyStopCameraRuntime("debug-loop-detector");
      return payload;
    }
    if (CAMERA_DEBUG && diagnostics) {
      try {
        const method = type.includes("suspected") || type.includes("error") ? "error" : "debug";
        env.console?.[method]?.("[camera]", type, entry);
      } catch {
        // Diagnostics must never affect playback.
      }
    }
    if (!options.skipRecordEvent) {
      try {
        recordEvent?.(type, payload);
      } catch {
        // Artifact diagnostics are best effort.
      }
    }
    return payload;
  }

  function playbackTraceSnapshot(extra = {}) {
    const { timeline, frames } = timelineModel();
    const windowModel = wisCameraTimelineTimeWindow(timeline, frames, {
      playbackPosition: Number(playbackClock.anchorRecordingTimeMs || playbackClock.targetTimeMs || 0),
    });
    const nowMs = Number.isFinite(Number(extra.nowMs)) ? Number(extra.nowMs) : wisCameraMonotonicNow();
    const playbackClockMs = Number.isFinite(Number(extra.playbackClockMs))
      ? Number(extra.playbackClockMs)
      : (Number(playbackClock.anchorRecordingTimeMs || 0) > 0
        ? getCurrentPlaybackTimeMs(nowMs)
        : Number(playbackClock.targetTimeMs || 0));
    const visibleFrameMs = Number(
      extra.visibleFrameMs
      ?? playbackClock.displayedRecordingTimeMs
      ?? playbackClock.anchorRecordingTimeMs
      ?? 0
    );
    return {
      owner: cameraPlaybackOwnerState(playbackClock.mode),
      requestedTimestampMs: Number(extra.requestedTimestampMs ?? playbackClock.targetTimeMs ?? persistedSeekTimestampMs ?? 0),
      persistedSeekTimestampMs: Number(extra.persistedSeekTimestampMs ?? persistedSeekTimestampMs ?? playbackClock.targetTimeMs ?? 0),
      mediaAnchorMs: Number(extra.mediaAnchorMs ?? playbackClock.anchorRecordingTimeMs ?? 0),
      wallAnchorMs: Number(extra.wallAnchorMs ?? playbackClock.anchorWallTimeMs ?? 0),
      playbackClockMs,
      visibleFrameMs: Number.isFinite(visibleFrameMs) ? visibleFrameMs : 0,
      archiveWindowStartMs: Number(extra.archiveWindowStartMs ?? timeline?.availableRange?.start_ms ?? timeline?.available_range?.start_ms ?? timeline?.range?.start_ms ?? windowModel.visibleStart ?? 0),
      archiveWindowEndMs: Number(extra.archiveWindowEndMs ?? timeline?.availableRange?.end_ms ?? timeline?.available_range?.end_ms ?? timeline?.range?.end_ms ?? windowModel.visibleEnd ?? 0),
      generation: Number(extra.generation ?? playbackGeneration),
      paused: Boolean(extra.paused ?? ["paused", "error"].includes(playbackClock.mode)),
      playbackRate: Number(extra.playbackRate ?? playbackClock.rate ?? 1),
      mode: playbackClock.mode,
      source: cleanText(extra.source || activeSeek?.source, ""),
      reason: cleanText(extra.reason || activeSeek?.reason, ""),
      ...extra,
    };
  }

  function tracePlaybackEvent(event, detail = {}, options = {}) {
    const payload = playbackTraceSnapshot(detail);
    traceWisCameraBoundary(event, payload);
    if (!options.traceOnly) {
      logCamera(event, payload, {
        sampleMs: Number(options.sampleMs || 0),
        skipRecordEvent: Boolean(options.skipRecordEvent),
      });
    }
    return payload;
  }

  function dispatchPlaybackPatch(reason = "", extra = {}) {
    if (typeof dispatchWisPatch !== "function") return;
    const signature = JSON.stringify({
      reason: cleanText(reason, ""),
      generation: playbackGeneration,
      mode: playbackClock.mode,
      source: cleanText(extra.source, ""),
      targetTimeMs: Math.round(Number(extra.targetTimeMs ?? playbackClock.targetTimeMs ?? 0)),
      firstFrameTimeMs: Math.round(Number(extra.firstFrameTimeMs ?? 0)),
      segmentId: cleanText(extra.segmentId, ""),
    });
    if (signature === lastPlaybackPatchSignature) return;
    lastPlaybackPatchSignature = signature;
    const patch = {
      schema: "hermes.wasm_agent.wis.camera_playback_patch.v1",
      artifactId: currentArtifactId,
      documentId: currentDocumentId,
      reason: cleanText(reason, ""),
      playbackClock: { ...playbackClock },
      generation: playbackGeneration,
      mode: playbackClock.mode,
      ...extra,
    };
    logCamera("camera.wis.patch", {
      reason,
      generation: playbackGeneration,
      timestampMs: playbackClock.targetTimeMs,
    });
    try {
      dispatchWisPatch(patch);
    } catch (error) {
      logCamera("camera.stale.callback.ignored", {
        reason: "dispatchWisPatch failed",
        error: error?.message || String(error),
      });
    }
  }

  function timelineModel() {
    const fromCallback = typeof getTimelineModel === "function" ? getTimelineModel() : null;
    const model = fromCallback && typeof fromCallback === "object" ? fromCallback : currentTimeline;
    const frames = Array.isArray(model?.frames) ? model.frames : currentFrames;
    return {
      timeline: model && typeof model === "object" ? model : {},
      frames: Array.isArray(frames) ? frames : [],
      mode: cleanText(model?.mode, currentMode),
    };
  }

  function cameraPlaybackOwnerMode(mode = "live") {
    const cleanMode = cleanText(mode, "live");
    if (cleanMode === "live") return "live";
    if (cleanMode === "error") return "error";
    if (["seeking", "buffering", "loading"].includes(cleanMode)) return "seeking";
    return "recorded";
  }

  function cameraPlaybackOwnerState(mode = "live") {
    const cleanMode = cleanText(mode, "live");
    if (cleanMode === "live") return WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE;
    if (["seeking", "buffering", "loading"].includes(cleanMode)) return WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_SEEKING;
    if (["paused", "ended", "gap", "stalled", "error"].includes(cleanMode)) return WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PAUSED;
    return WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PLAYING;
  }

  function setPlaybackMode(mode, detail = {}) {
    const nextMode = cleanText(mode, "live");
    const detailGeneration = Number(detail.generation ?? playbackGeneration);
    if (Number.isFinite(detailGeneration) && detailGeneration > 0 && detailGeneration !== playbackGeneration) {
      logCamera("camera.stale.playback_mode.ignored", {
        ...detail,
        mode: nextMode,
        generation: detailGeneration,
        currentGeneration: playbackGeneration,
      }, { sampleMs: 1000, skipRecordEvent: true });
      return;
    }
    if (playbackClock.mode === nextMode) return;
	    const previousMode = playbackClock.mode;
	    playbackClock.mode = nextMode;
	    traceWisCameraBoundary("ownerMutation", {
	      streamId: currentTimelineElement?.dataset?.streamId || currentArtifactId,
	      artifactId: currentArtifactId,
	      previousOwner: cameraPlaybackOwnerState(previousMode),
	      nextOwner: cameraPlaybackOwnerState(nextMode),
	      transition: `${cameraPlaybackOwnerState(previousMode)} -> ${cameraPlaybackOwnerState(nextMode)}`,
	      reason: cleanText(detail.reason, "setPlaybackMode"),
	      caller: cleanText(detail.caller || detail.source, "camera.setPlaybackMode"),
	      generation: playbackGeneration,
	      frameLayerOwner: cameraPlaybackOwnerState(nextMode) === WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE ? "live" : "recorded",
	      previousMode,
	      nextMode,
	    }, { stack: true });
	    logCamera("camera.playback.transition", {
      ...detail,
      fromMode: cameraPlaybackOwnerMode(previousMode),
      toMode: cameraPlaybackOwnerMode(nextMode),
      fromOwnerState: cameraPlaybackOwnerState(previousMode),
      toOwnerState: cameraPlaybackOwnerState(nextMode),
      ownerStateTransition: `${cameraPlaybackOwnerState(previousMode)} -> ${cameraPlaybackOwnerState(nextMode)}`,
      frameLayerOwner: cameraPlaybackOwnerState(nextMode) === WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE ? "live" : "recorded",
      fromDetailedMode: previousMode,
      toDetailedMode: nextMode,
      timestampMs: detail.timestampMs ?? playbackClock.targetTimeMs,
      generation: playbackGeneration,
    });
    logCamera("camera.playback.mode", {
      ...detail,
      mode: nextMode,
      generation: playbackGeneration,
    });
    if (!detail.skipPatch) dispatchPlaybackPatch(`mode:${nextMode}`, detail);
  }

  function normalizeSeekTarget(timestampMs = 0) {
    const { timeline, frames } = timelineModel();
    const raw = Number(timestampMs);
    const fallback = Number(playbackClock.targetTimeMs || playbackClock.anchorRecordingTimeMs || Date.now());
    const requested = Number.isFinite(raw) ? raw : fallback;
    const windowModel = wisCameraTimelineTimeWindow(timeline, frames, { playbackPosition: getCurrentPlaybackTimeMs() || requested });
    const hasVisibleWindow = windowModel.visibleEnd > windowModel.visibleStart;
    return Math.round(hasVisibleWindow
      ? clamp(requested, windowModel.visibleStart, windowModel.visibleEnd)
      : requested);
  }

  function noteSeekForFuse(source, targetTimeMs, detail = {}) {
    const now = Date.now();
    if (source === "user") lastRealUserCommitAt = now;
    recentSeekEvents.push({
      at: now,
      source,
      targetTimeMs,
      generation: playbackGeneration,
      reason: cleanText(detail.reason, ""),
      userCommitAt: lastRealUserCommitAt,
    });
    while (recentSeekEvents.length && now - recentSeekEvents[0].at > 1000) recentSeekEvents.shift();
    const nonUserSeekCount = recentSeekEvents.filter((event) => event.userCommitAt === lastRealUserCommitAt && event.source !== "user").length;
    if (source !== "user" && nonUserSeekCount > 3) {
      stopRenderLoop("seek-recursion-fuse");
      setPlaybackMode("error", { source, reason: "seek-recursion-fuse", timestampMs: targetTimeMs, skipPatch: true });
      try {
        env.console?.error?.("camera seek recursion suspected", recentSeekEvents.slice());
      } catch {
        // Console diagnostics are optional.
      }
      logCamera("camera.seek.recursion_suspected", { source, timestampMs: targetTimeMs, recentSeekEvents: recentSeekEvents.slice() });
      return false;
    }
    return true;
  }

  function abortPreviousLoads(reason = "abort") {
    if (!activeAbortController) return;
    logCamera("camera.seek.cancel.previous_generation", {
      reason,
      generation: playbackGeneration,
    });
    try {
      activeAbortController.abort();
    } catch {
      // Already aborted.
    }
    activeAbortController = null;
  }

  function stopRenderLoop(reason = "stop") {
    if (renderLoopId == null) return;
    const id = renderLoopId;
    renderLoopId = null;
    try {
      (renderLoopCancel || raf.cancel)(id);
    } catch {
      // Animation frame cleanup is best effort.
    }
    renderLoopCancel = null;
    logCamera("camera.render.stop", {
      reason,
      generation: playbackGeneration,
      renderLoopId: id,
    });
  }

  function stopClockLoop(reason = "stop") {
    if (clockLoopId == null) return;
    const id = clockLoopId;
    clockLoopId = null;
    try {
      (clockLoopCancel || raf.cancel)(id);
    } catch {
      // Animation frame cleanup is best effort.
    }
    clockLoopCancel = null;
    logCamera("camera.clock.loop.stop", {
      reason,
      generation: playbackGeneration,
      clockLoopId: id,
    }, { sampleMs: 1000 });
  }

  function getCurrentPlaybackTimeMs(nowMs = wisCameraMonotonicNow()) {
    const anchorRecordingTimeMs = Number(playbackClock.anchorRecordingTimeMs || 0);
    if (Number.isFinite(anchorRecordingTimeMs) && anchorRecordingTimeMs > 0) {
      if (["seeking", "buffering", "paused", "error"].includes(playbackClock.mode)) return anchorRecordingTimeMs;
      const anchorWallTimeMs = Number(playbackClock.anchorWallTimeMs || nowMs);
      const rate = Number.isFinite(Number(playbackClock.rate)) && Number(playbackClock.rate) > 0 ? Number(playbackClock.rate) : 1;
      return anchorRecordingTimeMs + (Math.max(0, Number(nowMs) - anchorWallTimeMs) * rate);
    }
    const fromState = typeof getPlaybackState === "function" ? getPlaybackState() : null;
    if (fromState && typeof fromState === "object") {
      const stateTime = wisCameraPlaybackClockMs(fromState, nowMs);
      if (Number.isFinite(stateTime) && stateTime > 0) return stateTime;
    }
    return Number(playbackClock.targetTimeMs || 0);
  }

  function startPlaybackClock(targetTimeMs, rate = 1, detail = {}) {
    const generation = Number(detail.generation || playbackGeneration);
    playbackClock.source = "synthetic";
    playbackClock.anchorWallTimeMs = wisCameraMonotonicNow();
    playbackClock.anchorRecordingTimeMs = Number(targetTimeMs);
    playbackClock.displayedRecordingTimeMs = 0;
    playbackClock.targetTimeMs = Number(targetTimeMs);
    playbackClock.rate = Number.isFinite(Number(rate)) && Number(rate) > 0 ? Number(rate) : 1;
    playbackClock.generation = generation;
    logCamera("camera.clock.start", {
      ...detail,
      generation,
      timestampMs: targetTimeMs,
      rate: playbackClock.rate,
    });
    tracePlaybackEvent("playback.timebase.anchored", {
      ...detail,
      generation,
      requestedTimestampMs: persistedSeekTimestampMs || Number(targetTimeMs),
      persistedSeekTimestampMs: persistedSeekTimestampMs || Number(targetTimeMs),
      mediaAnchorMs: playbackClock.anchorRecordingTimeMs,
      wallAnchorMs: playbackClock.anchorWallTimeMs,
      playbackRate: playbackClock.rate,
      paused: false,
      visibleFrameMs: playbackClock.displayedRecordingTimeMs || playbackClock.anchorRecordingTimeMs,
    });
    tracePlaybackEvent("playback.autoplay.started", {
      ...detail,
      generation,
      requestedTimestampMs: persistedSeekTimestampMs || Number(targetTimeMs),
      persistedSeekTimestampMs: persistedSeekTimestampMs || Number(targetTimeMs),
      mediaAnchorMs: playbackClock.anchorRecordingTimeMs,
      wallAnchorMs: playbackClock.anchorWallTimeMs,
      playbackRate: playbackClock.rate,
      paused: false,
    });
  }

  function startClockLoop(detail = {}) {
    const generation = Number(detail.generation || playbackGeneration);
    stopClockLoop("before-start");
    const tick = () => {
      if (generation !== playbackGeneration) {
        logCamera("camera.clock.loop.stale_tick.ignored", {
          generation,
          currentGeneration: playbackGeneration,
        });
        clockLoopId = null;
        clockLoopCancel = null;
        return;
      }
      const timestampMs = getCurrentPlaybackTimeMs();
      tracePlaybackEvent("playback.clock.tick", {
        ...detail,
        generation,
        playbackClockMs: timestampMs,
        visibleFrameMs: playbackClock.displayedRecordingTimeMs || playbackClock.anchorRecordingTimeMs,
      }, { traceOnly: true });
      syncTimelineFromPlayback(timestampMs);
      try {
        advanceSegmentIfNeeded?.(timestampMs, {
          generation,
          segment: currentSegment,
          activeSeek,
          mode: playbackClock.mode,
          clockOnly: true,
        });
      } catch (error) {
        logCamera("camera.stale.callback.ignored", {
          generation,
          reason: "advanceSegmentIfNeeded failed",
          error: error?.message || String(error),
        });
      }
      clockLoopCancel = raf.cancel;
      clockLoopId = raf.request(tick);
    };
    logCamera("camera.clock.loop.start", {
      ...detail,
      generation,
    });
    clockLoopCancel = raf.cancel;
    clockLoopId = raf.request(tick);
  }

  function displayedFrameTimeMs(frame = null, detail = {}) {
    const timestampMs = Number(
      detail.timestampMs
        ?? detail.firstFrameTimeMs
        ?? frame?.timestamp_ms
        ?? frame?.timestampMs
        ?? frame?.seek_target_ms
        ?? frame?.seekTargetMs
        ?? playbackClock.targetTimeMs
        ?? playbackClock.anchorRecordingTimeMs
        ?? 0
    );
    return Number.isFinite(timestampMs) && timestampMs > 0
      ? wisCameraTimelinePlaybackStartMs(frame || {}, timestampMs)
      : 0;
  }

  function syncDisplayedPlaybackFrame(frame = null, detail = {}) {
    const timestampMs = displayedFrameTimeMs(frame, detail);
    if (!timestampMs) return 0;
    const generation = Number(detail.generation || playbackGeneration);
    if (generation !== playbackGeneration) {
      logCamera("camera.stale.media_frame.ignored", {
        ...detail,
        generation,
        currentGeneration: playbackGeneration,
        timestampMs,
      }, { sampleMs: 1000 });
      return 0;
    }
    const nowMs = wisCameraMonotonicNow();
    const waitingForFirstFrame = !playbackClock.anchorWallTimeMs || ["seeking", "buffering"].includes(playbackClock.mode);
    const requestedTimeMs = Number(persistedSeekTimestampMs || playbackClock.targetTimeMs || playbackClock.anchorRecordingTimeMs || timestampMs);
    const firstFrameOffsetMs = timestampMs - requestedTimeMs;
    playbackClock.source = "media";
    playbackClock.displayedRecordingTimeMs = timestampMs;
    if (waitingForFirstFrame) {
      playbackClock.anchorWallTimeMs = nowMs;
      playbackClock.anchorRecordingTimeMs = timestampMs;
      playbackClock.targetTimeMs = requestedTimeMs;
    }
    playbackClock.rate = 1;
    playbackClock.generation = generation;
    if (playbackClock.mode !== "recordedPlaying") {
      setPlaybackMode("recordedPlaying", {
        ...detail,
        timestampMs,
        generation,
        skipPatch: true,
      });
    }
    if (waitingForFirstFrame) {
      tracePlaybackEvent("playback.timebase.anchored", {
        ...detail,
        generation,
        requestedTimestampMs: requestedTimeMs,
        persistedSeekTimestampMs: requestedTimeMs,
        mediaAnchorMs: playbackClock.anchorRecordingTimeMs,
        wallAnchorMs: playbackClock.anchorWallTimeMs,
        playbackClockMs: getCurrentPlaybackTimeMs(nowMs),
        visibleFrameMs: timestampMs,
        paused: false,
        playbackRate: playbackClock.rate,
      });
      tracePlaybackEvent("playback.autoplay.started", {
        ...detail,
        generation,
        requestedTimestampMs: requestedTimeMs,
        persistedSeekTimestampMs: requestedTimeMs,
        mediaAnchorMs: playbackClock.anchorRecordingTimeMs,
        wallAnchorMs: playbackClock.anchorWallTimeMs,
        playbackClockMs: getCurrentPlaybackTimeMs(nowMs),
        visibleFrameMs: timestampMs,
        paused: false,
        playbackRate: playbackClock.rate,
      });
    }
    logCamera("camera.clock.media_frame", {
      ...detail,
      generation,
      timestampMs,
      source: detail.source || "media",
    }, { sampleMs: 1000, skipRecordEvent: true });
    if (waitingForFirstFrame && Number.isFinite(firstFrameOffsetMs)) {
      logCamera("camera.server.first_frame.offset_from_seek", {
        ...detail,
        generation,
        requestedTimeMs,
        firstFrameTimeMs: timestampMs,
        offsetMs: firstFrameOffsetMs,
      });
      if (Math.abs(firstFrameOffsetMs) > WIS_CAMERA_PLAYBACK_HARD_CATCHUP_LAG_MS) {
        logCamera("camera.server.stream.gap_suspected", {
          ...detail,
          generation,
          requestedTimeMs,
          firstFrameTimeMs: timestampMs,
          offsetMs: firstFrameOffsetMs,
        });
      }
    }
    if (playbackClock.source === "media" && clockLoopId == null && playbackClock.mode === "recordedPlaying") {
      startClockLoop({ ...detail, generation, reason: detail.reason || "media-clock" });
    }
    if (detail.syncTimeline !== false) syncTimelineFromPlayback(getCurrentPlaybackTimeMs());
    return timestampMs;
  }

  function syncTimelineFromPlayback(timestampMs) {
    if (isTimelineScrubActive()) {
      logCamera("camera.timeline.scrub.programmatic_sync_skipped", {
        generation: playbackGeneration,
        timestampMs,
        source: "playback",
        elementConnected: currentTimelineElement?.isConnected !== false,
      }, { sampleMs: 1000, skipRecordEvent: true });
      return;
    }
    if (isSyncingTimelineFromPlayback) return;
    isSyncingTimelineFromPlayback = true;
    try {
      const progress = updateTimelineVisualOnlyFromTimestamp(timestampMs);
      logCamera("camera.timeline.programmatic.sync", {
        generation: playbackGeneration,
        timestampMs,
        computedPlaybackTimeMs: timestampMs,
        progress,
        source: "playback",
      }, { sampleMs: 1000, skipRecordEvent: true });
    } finally {
      isSyncingTimelineFromPlayback = false;
    }
  }

  function updateTimelineVisualOnlyFromTimestamp(timestampMs) {
    if (typeof updateTimelineVisualOnly === "function") {
      return updateTimelineVisualOnly(timestampMs, {
        generation: playbackGeneration,
        mode: playbackClock.mode,
        isSyncingTimelineFromPlayback,
      });
    }
    const element = currentTimelineElement;
    if (!element?.style) return null;
    const { timeline, frames } = timelineModel();
    const { visibleStart, visibleEnd } = wisCameraTimelineTimeWindow(timeline, frames, { playbackPosition: timestampMs });
    if (visibleEnd <= visibleStart) return null;
    const progress = clamp(((Number(timestampMs) - visibleStart) / (visibleEnd - visibleStart)) * 100, 0, 100);
    element.style.setProperty("--wis-camera-timeline-progress", `${progress}%`);
    tracePlaybackEvent("timeline.progress.updated", {
      timestampMs,
      playbackClockMs: timestampMs,
      progress,
    }, { traceOnly: true });
    return progress;
  }

  function startRenderLoop(detail = {}) {
    const generation = Number(detail.generation || playbackGeneration);
    stopRenderLoop("before-start");
    if (renderLoopId != null) {
      env.console?.warn?.("camera render loop already active; refusing duplicate", {
        artifactId: currentArtifactId,
        renderLoopId,
        generation,
      });
      return;
    }
    const tick = () => {
      if (generation !== playbackGeneration) {
        logCamera("camera.render.stale_tick.ignored", {
          generation,
          currentGeneration: playbackGeneration,
        });
        renderLoopId = null;
        renderLoopCancel = null;
        return;
      }
      const timestampMs = getCurrentPlaybackTimeMs();
      try {
        drawFrameAt?.(timestampMs, {
          generation,
          canvas: currentCanvas,
          segment: currentSegment,
          mode: playbackClock.mode,
        });
      } catch (error) {
        logCamera("camera.stale.callback.ignored", {
          generation,
          reason: "drawFrameAt failed",
          error: error?.message || String(error),
        });
      }
      syncTimelineFromPlayback(timestampMs);
      try {
        advanceSegmentIfNeeded?.(timestampMs, {
          generation,
          segment: currentSegment,
          activeSeek,
          mode: playbackClock.mode,
        });
      } catch (error) {
        logCamera("camera.stale.callback.ignored", {
          generation,
          reason: "advanceSegmentIfNeeded failed",
          error: error?.message || String(error),
        });
      }
      renderLoopCancel = raf.cancel;
      renderLoopId = raf.request(tick);
    };
    logCamera("camera.render.start", {
      ...detail,
      generation,
    });
    renderLoopCancel = raf.cancel;
    renderLoopId = raf.request(tick);
  }

  async function defaultFindSegmentForTime(targetTimeMs, detail = {}) {
    if (typeof findSegmentForTime === "function") {
      return findSegmentForTime(targetTimeMs, detail);
    }
    const { timeline, frames } = timelineModel();
    const windowModel = wisCameraTimelineTimeWindow(timeline, frames, { playbackPosition: targetTimeMs });
    const frame = wisCameraTimelineFrameClosestToTime(frames, targetTimeMs, windowModel);
    if (!frame) return null;
    const snappedTimestampMs = timelineFrameTimestampMs(frame) ?? Number(targetTimeMs);
    return {
      ...frame,
      timestamp_ms: snappedTimestampMs,
      seek_target_ms: targetTimeMs,
      snapped_timestamp_ms: snappedTimestampMs,
    };
  }

  async function defaultLoadSegment(segment, detail = {}) {
    if (typeof loadSegment === "function") return loadSegment(segment, detail);
    return segment;
  }

  function segmentUsesMediaClock(segment = null) {
    const clockSource = cleanText(
      segment?.playbackClockSource
        || segment?.playback_clock_source
        || segment?.clockSource
        || segment?.clock_source,
      ""
    );
    return ["media", "displayed-frame", "displayed_frame"].includes(clockSource);
  }

	  async function seekTo(timestampMs, options = {}) {
	    const source = cleanText(options.source, "programmatic");
	    const reason = cleanText(options.reason, "");
	    const target = normalizeSeekTarget(timestampMs);
	    const requestedTimestampMs = Number(timestampMs);
	    const seekTimelineModel = timelineModel();
	    const seekWindow = wisCameraTimelineTimeWindow(seekTimelineModel.timeline, seekTimelineModel.frames, {
	      playbackPosition: target,
	    });
	    if (source === "playback") {
	      logCamera("camera.seek.blocked.playback_source", { target, timestampMs: target, source, reason });
	      return null;
    }
    if (isSyncingTimelineFromPlayback) {
      logCamera("camera.wis.render_skip_frame_state", { target, timestampMs: target, source, reason });
      return null;
    }
    if (activeSeek?.status === "running" && activeSeek.targetTimeMs === target) {
      logCamera("camera.seek.ignored.same_target", {
        target,
        timestampMs: target,
        source,
        reason,
        generation: activeSeek.generation,
      });
      return activeSeek;
    }
    if (
      currentSegment
      && Math.round(Number(playbackClock.targetTimeMs || playbackClock.anchorRecordingTimeMs || 0)) === Math.round(target)
      && ["seeking", "buffering", "recordedPlaying"].includes(playbackClock.mode)
    ) {
      logCamera("camera.seek.ignored.same_frame", {
        target,
        timestampMs: target,
        source,
        reason,
        generation: playbackGeneration,
      }, { sampleMs: 1000, skipRecordEvent: true });
      return currentSegment;
    }
    if (!noteSeekForFuse(source, target, { reason })) return null;

	    const generation = ++playbackGeneration;
	    if (Number.isFinite(requestedTimestampMs) && Math.round(requestedTimestampMs) !== Math.round(target)) {
	      tracePlaybackEvent("timeline.seek.overwritten", {
	        source,
	        reason,
	        generation,
	        requestedTimestampMs,
	        persistedSeekTimestampMs: target,
	        attemptedTimestampMs: requestedTimestampMs,
	        overwrittenByTimestampMs: target,
	        archiveWindowStartMs: Number(seekTimelineModel.timeline?.availableRange?.start_ms ?? seekTimelineModel.timeline?.available_range?.start_ms ?? seekTimelineModel.timeline?.range?.start_ms ?? seekWindow.visibleStart ?? 0),
	        archiveWindowEndMs: Number(seekTimelineModel.timeline?.availableRange?.end_ms ?? seekTimelineModel.timeline?.available_range?.end_ms ?? seekWindow.visibleEnd ?? 0),
	      });
	    }
	    persistedSeekTimestampMs = target;
	    traceWisCameraBoundary("camera.seekRequested", {
	      functionName: "seekTo",
	      cameraId: currentTimelineElement?.dataset?.streamId || currentArtifactId,
	      requestedTimestampMs: Number.isFinite(requestedTimestampMs) ? requestedTimestampMs : null,
	      archiveWindowStartMs: Number(seekTimelineModel.timeline?.availableRange?.start_ms ?? seekTimelineModel.timeline?.available_range?.start_ms ?? seekTimelineModel.timeline?.range?.start_ms ?? seekWindow.visibleStart ?? 0),
	      archiveWindowEndMs: Number(seekTimelineModel.timeline?.availableRange?.end_ms ?? seekTimelineModel.timeline?.available_range?.end_ms ?? seekTimelineModel.timeline?.range?.end_ms ?? seekWindow.visibleEnd ?? 0),
	      resolvedTimestampMs: target,
	      recordedPlaybackPossible: Boolean(seekTimelineModel.frames.length),
	      currentOwnerBeforeSeek: cameraPlaybackOwnerState(playbackClock.mode),
	      currentModeBeforeSeek: playbackClock.mode,
	      generation,
	      source,
	      reason,
	    });
	    tracePlaybackEvent("timeline.seek.persisted", {
	      source,
	      reason,
	      generation,
	      requestedTimestampMs: Number.isFinite(requestedTimestampMs) ? requestedTimestampMs : target,
	      persistedSeekTimestampMs,
	      mediaAnchorMs: target,
	      wallAnchorMs: 0,
	      playbackClockMs: target,
	      visibleFrameMs: playbackClock.displayedRecordingTimeMs || 0,
	      archiveWindowStartMs: Number(seekTimelineModel.timeline?.availableRange?.start_ms ?? seekTimelineModel.timeline?.available_range?.start_ms ?? seekTimelineModel.timeline?.range?.start_ms ?? seekWindow.visibleStart ?? 0),
	      archiveWindowEndMs: Number(seekTimelineModel.timeline?.availableRange?.end_ms ?? seekTimelineModel.timeline?.available_range?.end_ms ?? seekWindow.visibleEnd ?? 0),
	      paused: false,
	      playbackRate: 1,
	    });
	    activeSeek = {
      generation,
      targetTimeMs: target,
      source,
      reason,
      status: "running",
    };
    logCamera("camera.seek.start", {
      generation,
      source,
      reason,
      timestampMs: target,
    });
    stopRenderLoop("seek-start");
    stopClockLoop("seek-start");
    abortPreviousLoads("seek-start");
    if (typeof env.AbortController === "function") activeAbortController = new env.AbortController();
    playbackClock.source = "media";
    playbackClock.anchorWallTimeMs = 0;
    playbackClock.anchorRecordingTimeMs = target;
    playbackClock.displayedRecordingTimeMs = 0;
    playbackClock.targetTimeMs = target;
    playbackClock.rate = 1;
    playbackClock.generation = generation;
    setPlaybackMode("seeking", { source, reason, timestampMs: target, generation, skipPatch: true });
    try {
      onSeekPending?.({
        generation,
        source,
        reason,
        timestampMs: target,
        targetTimeMs: target,
        signal: activeAbortController?.signal,
        requestedFrame: options.frame || null,
        target: options.target || null,
      });
    } catch (error) {
      logCamera("camera.stale.callback.ignored", {
        generation,
        source,
        reason: "onSeekPending failed",
        timestampMs: target,
        error: error?.message || String(error),
      });
    }

    let segment = null;
    try {
      segment = await defaultFindSegmentForTime(target, {
        generation,
        source,
        reason,
        signal: activeAbortController?.signal,
        targetTimeMs: target,
        requestedFrame: options.frame || null,
        target: options.target || null,
      });
    } catch (error) {
      if (generation !== playbackGeneration) {
        logCamera("camera.stale.callback.ignored", { generation, source, reason, timestampMs: target });
        return null;
      }
      setPlaybackMode("error", { source, reason, timestampMs: target, generation });
      activeSeek.status = "error";
      throw error;
    }
    if (generation !== playbackGeneration) {
      logCamera("camera.stale.segment_lookup.ignored", { generation, target, timestampMs: target, source, reason });
      return null;
    }
	    if (!segment) {
	      traceWisCameraBoundary("archive.frame.resolved", {
	        functionName: "seekTo",
	        cameraId: currentTimelineElement?.dataset?.streamId || currentArtifactId,
	        generation,
	        requestedTimestampMs: target,
	        resolvedTimestampMs: null,
	        fetchResult: "empty",
	        recordedPlaybackPossible: false,
	        reason,
	      });
	      setPlaybackMode("error", { source, reason, timestampMs: target, generation });
	      activeSeek.status = "error";
	      return null;
    }
    logCamera("camera.timeline.seek", {
      generation,
      source,
      reason,
      targetTimestampMs: target,
      resolvedTimestampMs: wisCameraTimelinePlaybackStartMs(segment, timelineFrameTimestampMs(segment) || target),
      ratio: Number(options.target?.ratio),
      segmentId: cleanText(segment.id, ""),
	      segmentUrl: cleanText(segment.url, ""),
	      available: Boolean(segment.id && segment.url),
	    });
	    traceWisCameraBoundary("archive.frame.resolved", {
	      functionName: "seekTo",
	      cameraId: currentTimelineElement?.dataset?.streamId || currentArtifactId,
	      generation,
	      requestedTimestampMs: target,
	      resolvedTimestampMs: wisCameraTimelinePlaybackStartMs(segment, timelineFrameTimestampMs(segment) || target),
	      fetchResult: segment.id && segment.url ? "non-empty" : "empty",
	      recordedPlaybackPossible: Boolean(segment.id && segment.url),
	      segmentId: cleanText(segment.id, ""),
	      segmentUrl: cleanText(segment.url, ""),
	      reason,
	    });

    setPlaybackMode("buffering", { source, reason, timestampMs: target, generation, skipPatch: true });
    logCamera("camera.segment.load.start", {
      generation,
      source,
      reason,
      timestampMs: target,
      segmentId: cleanText(segment.id, ""),
    });
    let loadedSegment = null;
    try {
      loadedSegment = await defaultLoadSegment(segment, {
        generation,
        source,
        reason,
        signal: activeAbortController?.signal,
        targetTimeMs: target,
      });
    } catch (error) {
      if (generation !== playbackGeneration || activeAbortController?.signal?.aborted) {
        logCamera("camera.stale.callback.ignored", { generation, source, reason, timestampMs: target });
        return null;
      }
      setPlaybackMode("error", { source, reason, timestampMs: target, generation });
      activeSeek.status = "error";
      throw error;
    }
    if (generation !== playbackGeneration) {
      logCamera("camera.stale.segment_load.ignored", { generation, target, timestampMs: target, source, reason });
      return null;
    }
    currentSegment = loadedSegment || segment;
    logCamera("camera.segment.load.done", {
      generation,
      source,
      reason,
      timestampMs: target,
      segmentId: cleanText(currentSegment?.id || segment?.id, ""),
    });
    if (segmentUsesMediaClock(currentSegment)) {
      playbackClock.source = "media";
      playbackClock.anchorWallTimeMs = 0;
      playbackClock.anchorRecordingTimeMs = target;
      playbackClock.displayedRecordingTimeMs = 0;
      playbackClock.targetTimeMs = target;
      playbackClock.rate = 1;
      playbackClock.generation = generation;
      stopRenderLoop("media-clock-segment");
      stopClockLoop("media-clock-segment-waiting");
      logCamera("camera.clock.media_wait", {
        generation,
        source,
        reason,
        timestampMs: target,
      });
    } else {
      startPlaybackClock(target, 1, { generation, source, reason });
      startRenderLoop({ generation, source, reason });
      setPlaybackMode("recordedPlaying", { source, reason, timestampMs: target, generation, skipPatch: true });
    }
    if (activeSeek?.generation === generation) activeSeek.status = "done";
    return currentSegment;
  }

	  function pointerTimelineTarget(event) {
	    const element = currentTimelineElement;
	    const rect = element?.getBoundingClientRect?.() || { left: 0, width: 0 };
    const x = Number(event?.clientX || 0) - Number(rect.left || 0);
    const ratio = Number(rect.width || 0) > 0 ? clamp(x / rect.width, 0, 1) : 1;
    const { timeline, frames } = timelineModel();
    const target = wisCameraTimelineTargetAtRatio(timeline, frames, ratio, {
      playbackPosition: getCurrentPlaybackTimeMs(),
    });
    return {
      ...target,
      x,
      ratio,
      timestampMs: Number(target.targetTime || target.snappedTargetTime || 0),
	      snappedFrame: target.snappedFrame || wisCameraTimelineFrameClosestToTime(frames, target.targetTime, target),
	    };
	  }

	  function traceTimelinePointer(handlerName, event, target = null) {
	    const externalPlaybackState = typeof getPlaybackState === "function" ? getPlaybackState() : null;
	    const timelineStreamId = currentTimelineElement?.dataset?.streamId || currentArtifactId;
	    traceWisCameraBoundary("timeline.pointer", {
	      handler: handlerName,
	      streamId: timelineStreamId,
	      cameraId: timelineStreamId,
	      artifactId: currentArtifactId,
	      clientX: Number(event?.clientX || 0),
	      computedRatio: Number(target?.ratio),
	      requestedTimestampMs: Number(target?.targetTime ?? target?.timestampMs ?? target?.snappedTargetTime ?? 0),
	      currentModeBeforeSeek: playbackClock.mode,
	      currentOwnerBeforeSeek: cleanText(externalPlaybackState?.ownerState || externalPlaybackState?.timelineOwnerState, cameraPlaybackOwnerState(playbackClock.mode)),
	      owner: cleanText(externalPlaybackState?.ownerState || externalPlaybackState?.timelineOwnerState, cameraPlaybackOwnerState(playbackClock.mode)),
	      mode: playbackClock.mode,
	      generation: playbackGeneration,
	      activeSeekGeneration: activeSeek?.generation || 0,
	      isSyncingTimelineFromPlayback,
	      timelineElement: currentTimelineElement,
	      eventTarget: event?.target || null,
	      reason: handlerName,
	    });
	  }

	  function isTimelineScrubActive(event = null) {
    if (!scrubOwner || !userScrubbing.active) return false;
    if (!event) return true;
    return !scrubOwner.pointerId || scrubOwner.pointerId === event.pointerId;
  }

  function updateTimelinePreviewVisualOnly(target) {
    const element = currentTimelineElement;
    if (!element?.style || !target) return;
    const ratio = clamp(Number(target.ratio), 0, 1);
    element.style.setProperty("--wis-camera-timeline-preview", `${ratio * 100}%`);
    element.dataset.wisTimelinePreviewing = "1";
    previewTimelineTarget?.(target, {
      generation: playbackGeneration,
      source: "user-preview",
      visualOnly: true,
      noPatch: true,
      mode: playbackClock.mode,
    });
  }

  function clearTimelinePreviewVisualOnly() {
    const element = currentTimelineElement;
    if (element?.style) {
      element.style.removeProperty("--wis-camera-timeline-preview");
      delete element.dataset.wisTimelinePreviewing;
    }
  }

  function previewTarget(target) {
    userScrubbing.target = target;
    try {
      updateTimelinePreviewVisualOnly(target);
    } catch (error) {
      logCamera("camera.stale.callback.ignored", {
        reason: "previewTimelineTarget failed",
        error: error?.message || String(error),
      });
    }
  }

	  function commitTimelineTarget(target, reason = "timeline-pointerup") {
	    const timestampMs = Number(target?.targetTime ?? target?.timestampMs ?? target?.snappedTargetTime);
	    if (!Number.isFinite(timestampMs)) return;
	    lastRealUserCommitAt = Date.now();
	    const timelineStreamId = currentTimelineElement?.dataset?.streamId || currentArtifactId;
	    traceWisCameraBoundary("timeline.commit", {
	      streamId: timelineStreamId,
	      cameraId: timelineStreamId,
	      handler: "commitTimelineTarget",
	      requestedTimestampMs: timestampMs,
	      computedRatio: Number(target?.ratio),
	      currentModeBeforeSeek: playbackClock.mode,
	      currentOwnerBeforeSeek: cameraPlaybackOwnerState(playbackClock.mode),
	      owner: cameraPlaybackOwnerState(playbackClock.mode),
	      mode: playbackClock.mode,
	      generation: playbackGeneration,
	      timelineElement: currentTimelineElement,
	      reason,
	    });
	    void seekTo(timestampMs, {
      source: "user",
      reason,
      target,
      frame: target?.snappedFrame || null,
    }).catch((error) => {
      logCamera("camera.stale.callback.ignored", {
        reason: "timeline seek failed",
        error: error?.message || String(error),
      });
    });
  }

  function requestTimelineLoad(target, reason) {
    try {
      onTimelineLoadNeeded?.(target, {
        source: "user",
        reason,
        mode: currentMode,
      });
    } catch (error) {
      logCamera("camera.stale.callback.ignored", {
        reason: "onTimelineLoadNeeded failed",
        error: error?.message || String(error),
      });
    }
  }

  function stopTimelineWindowCapture() {
    env.removeEventListener?.("pointermove", moveTimelinePointer, true);
    env.removeEventListener?.("pointerup", endTimelinePointer, true);
    env.removeEventListener?.("pointercancel", cancelTimelinePointer, true);
  }

  function shouldHandleTimelinePointer(event) {
    return isTimelineScrubActive(event);
  }

  function beginTimelineScrub(event, target) {
    scrubOwner = {
      kind: "user-scrub",
      pointerId: event.pointerId || 0,
      startedAt: wisCameraMonotonicNow(),
      generation: playbackGeneration,
    };
    userScrubbing.active = true;
    userScrubbing.pointerId = scrubOwner.pointerId;
    userScrubbing.target = target;
    currentTimelineElement?.classList?.add("is-scrubbing");
    logCamera("camera.timeline.scrub.begin", {
      generation: playbackGeneration,
      pointerId: scrubOwner.pointerId,
      timestampMs: target?.timestampMs,
      ratio: target?.ratio,
      elementConnected: currentTimelineElement?.isConnected !== false,
    });
  }

  function endTimelineScrub(reason = "timeline-scrub-end") {
    currentTimelineElement?.classList?.remove("is-scrubbing");
    clearTimelinePreviewVisualOnly();
    logCamera("camera.timeline.scrub.end", {
      generation: playbackGeneration,
      pointerId: scrubOwner?.pointerId || 0,
      timestampMs: userScrubbing.target?.timestampMs,
      ratio: userScrubbing.target?.ratio,
      reason,
      elementConnected: currentTimelineElement?.isConnected !== false,
    });
    scrubOwner = null;
    userScrubbing.active = false;
    userScrubbing.pointerId = 0;
    if (pendingTimelineElement) {
      const nextElement = pendingTimelineElement;
      pendingTimelineElement = null;
      attachTimelineElement(nextElement);
    }
  }

  function moveTimelinePointer(event) {
    if (!isTimelineScrubActive(event)) return;
    event.preventDefault?.();
    event.stopPropagation?.();
    const target = pointerTimelineTarget(event);
    userScrubbing.target = target;
    updateTimelinePreviewVisualOnly(target);
    logCamera("camera.timeline.scrub.preview.sample", {
      source: "user",
      reason: "timeline-pointermove",
      timestampMs: target.timestampMs,
      ratio: target.ratio,
      generation: playbackGeneration,
    }, { sampleMs: 250, skipRecordEvent: true });
  }

  function cancelTimelinePointer(event) {
    if (!isTimelineScrubActive(event)) return;
    stopTimelineWindowCapture();
    endTimelineScrub("timeline-pointercancel");
    resetTimelinePreview?.();
  }

  function endTimelinePointer(event) {
    if (!isTimelineScrubActive(event)) return;
    event.preventDefault?.();
    event.stopPropagation?.();
	    const target = event.type === "lostpointercapture" ? userScrubbing.target : pointerTimelineTarget(event);
	    if (target) previewTarget(target);
	    traceTimelinePointer("endTimelinePointer", event, target);
	    stopTimelineWindowCapture();
    try {
      currentTimelineElement?.releasePointerCapture?.(event.pointerId);
    } catch {
      // Capture may already be gone.
    }
    suppressClickUntil = Date.now() + 400;
    logCamera("camera.timeline.scrub.commit_seek", {
      source: "user",
      reason: "timeline-pointerup",
      timestampMs: Number(target?.timestampMs || target?.targetTime || 0),
      ratio: target?.ratio,
    });
    endTimelineScrub("timeline-pointerup");
    commitTimelineTarget(target, "timeline-pointerup");
  }

  function startTimelinePointer(event) {
    if (isSyncingTimelineFromPlayback) return;
    event.preventDefault?.();
    event.stopPropagation?.();
	    const { frames } = timelineModel();
	    const target = pointerTimelineTarget(event);
	    traceTimelinePointer("startTimelinePointer", event, target);
	    logCamera("camera.timeline.user.pointerdown", {
      source: "user",
      reason: "timeline-pointerdown",
      timestampMs: target.timestampMs,
      ratio: target.ratio,
    });
    currentTimelineElement?.focus?.({ preventScroll: true });
    if (!frames.length) {
      suppressClickUntil = Date.now() + 400;
      requestTimelineLoad(target, "timeline-pointerdown");
      return;
    }
    beginTimelineScrub(event, target);
    previewTarget(target);
    try {
      currentTimelineElement?.setPointerCapture?.(event.pointerId);
    } catch {
      // Pointer capture can be unavailable in some test/browser paths.
    }
    env.addEventListener?.("pointermove", moveTimelinePointer, true);
    env.addEventListener?.("pointerup", endTimelinePointer, true);
    env.addEventListener?.("pointercancel", cancelTimelinePointer, true);
  }

  function clickTimeline(event) {
    if (isTimelineScrubActive(event) || isSyncingTimelineFromPlayback) return;
    event.preventDefault?.();
    event.stopPropagation?.();
    if (Date.now() < suppressClickUntil) {
      logCamera("camera.timeline.click.suppressed_after_drag", {
        generation: playbackGeneration,
        pointerId: event.pointerId || 0,
      }, { skipRecordEvent: true });
      return;
	    }
	    const { frames } = timelineModel();
	    const target = pointerTimelineTarget(event);
	    traceTimelinePointer("clickTimeline", event, target);
	    if (!frames.length) {
      requestTimelineLoad(target, "timeline-click");
      return;
    }
    previewTarget(target);
    logCamera("camera.timeline.user.pointerup", {
      source: "user",
      reason: "timeline-click",
      timestampMs: target.timestampMs,
      ratio: target.ratio,
    });
    commitTimelineTarget(target, "timeline-click");
  }

  function keyTimeline(event) {
    if (isSyncingTimelineFromPlayback) return;
    const { frames } = timelineModel();
    if (!frames.length) return;
    const deltas = {
      ArrowLeft: -1,
      ArrowDown: -1,
      ArrowRight: 1,
      ArrowUp: 1,
      PageDown: -10,
      PageUp: 10,
      Home: -Number.MAX_SAFE_INTEGER,
      End: Number.MAX_SAFE_INTEGER,
    };
    if (!(event.key in deltas) && event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault?.();
    event.stopPropagation?.();
    const currentMs = getCurrentPlaybackTimeMs();
    const currentFrame = wisCameraTimelineFrameClosestToTime(frames, currentMs) || frames[frames.length - 1];
    const currentIndex = Math.max(0, frames.indexOf(currentFrame));
    let nextIndex = currentIndex;
    if (event.key in deltas) {
      const delta = deltas[event.key];
      nextIndex = delta === -Number.MAX_SAFE_INTEGER ? 0 : (delta === Number.MAX_SAFE_INTEGER ? frames.length - 1 : clamp(currentIndex + delta, 0, frames.length - 1));
    }
    const frame = frames[nextIndex] || currentFrame;
    const timestampMs = wisCameraTimelinePlaybackStartMs(frame, timelineFrameTimestampMs(frame) || currentMs);
    const target = {
      ...wisCameraTimelineTargetAtRatio(currentTimeline || {}, frames, frames.length > 1 ? nextIndex / (frames.length - 1) : 1),
      timestampMs,
      targetTime: timestampMs,
      snappedFrame: frame,
    };
    previewTarget(target);
    commitTimelineTarget(target, event.key === "Enter" || event.key === " " ? "timeline-key-commit" : "timeline-key-step");
  }

  function pausePlayback(detail = {}) {
    if (cameraPlaybackOwnerState(playbackClock.mode) === WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE) return false;
    const nowMs = wisCameraMonotonicNow();
    const currentMs = getCurrentPlaybackTimeMs(nowMs) || playbackClock.displayedRecordingTimeMs || playbackClock.anchorRecordingTimeMs || playbackClock.targetTimeMs;
    playbackClock.anchorWallTimeMs = nowMs;
    playbackClock.anchorRecordingTimeMs = Number(currentMs || 0);
    playbackClock.displayedRecordingTimeMs = Number(playbackClock.displayedRecordingTimeMs || currentMs || 0);
    playbackClock.rate = 1;
    stopClockLoop("pause");
    setPlaybackMode("paused", {
      ...detail,
      source: detail.source || "control",
      reason: detail.reason || "pause",
      timestampMs: currentMs,
      generation: playbackGeneration,
      skipPatch: true,
    });
    tracePlaybackEvent("playback.pause", {
      ...detail,
      source: detail.source || "control",
      reason: detail.reason || "pause",
      generation: playbackGeneration,
      requestedTimestampMs: persistedSeekTimestampMs || playbackClock.targetTimeMs || currentMs,
      persistedSeekTimestampMs: persistedSeekTimestampMs || playbackClock.targetTimeMs || currentMs,
      mediaAnchorMs: playbackClock.anchorRecordingTimeMs,
      wallAnchorMs: playbackClock.anchorWallTimeMs,
      playbackClockMs: currentMs,
      visibleFrameMs: playbackClock.displayedRecordingTimeMs || currentMs,
      paused: true,
      playbackRate: 1,
    });
    syncTimelineFromPlayback(currentMs);
    return true;
  }

  function resumePlayback(detail = {}) {
    if (cameraPlaybackOwnerState(playbackClock.mode) === WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE) return false;
    const nowMs = wisCameraMonotonicNow();
    const resumeMs = Number(playbackClock.anchorRecordingTimeMs || playbackClock.displayedRecordingTimeMs || playbackClock.targetTimeMs || persistedSeekTimestampMs || 0);
    if (!Number.isFinite(resumeMs) || resumeMs <= 0) return false;
    playbackClock.anchorWallTimeMs = nowMs;
    playbackClock.anchorRecordingTimeMs = resumeMs;
    playbackClock.rate = 1;
    setPlaybackMode("recordedPlaying", {
      ...detail,
      source: detail.source || "control",
      reason: detail.reason || "resume",
      timestampMs: resumeMs,
      generation: playbackGeneration,
      skipPatch: true,
    });
    tracePlaybackEvent("playback.resume", {
      ...detail,
      source: detail.source || "control",
      reason: detail.reason || "resume",
      generation: playbackGeneration,
      requestedTimestampMs: persistedSeekTimestampMs || playbackClock.targetTimeMs || resumeMs,
      persistedSeekTimestampMs: persistedSeekTimestampMs || playbackClock.targetTimeMs || resumeMs,
      mediaAnchorMs: playbackClock.anchorRecordingTimeMs,
      wallAnchorMs: playbackClock.anchorWallTimeMs,
      playbackClockMs: resumeMs,
      visibleFrameMs: playbackClock.displayedRecordingTimeMs || resumeMs,
      paused: false,
      playbackRate: 1,
    });
    tracePlaybackEvent("playback.timebase.anchored", {
      ...detail,
      source: detail.source || "control",
      reason: detail.reason || "resume",
      generation: playbackGeneration,
      requestedTimestampMs: persistedSeekTimestampMs || playbackClock.targetTimeMs || resumeMs,
      persistedSeekTimestampMs: persistedSeekTimestampMs || playbackClock.targetTimeMs || resumeMs,
      mediaAnchorMs: playbackClock.anchorRecordingTimeMs,
      wallAnchorMs: playbackClock.anchorWallTimeMs,
      playbackClockMs: resumeMs,
      visibleFrameMs: playbackClock.displayedRecordingTimeMs || resumeMs,
      paused: false,
      playbackRate: 1,
    });
    if (clockLoopId == null) startClockLoop({ ...detail, source: detail.source || "control", reason: detail.reason || "resume", generation: playbackGeneration });
    syncTimelineFromPlayback(resumeMs);
    return true;
  }

  function togglePlayback(detail = {}) {
    return playbackClock.mode === "paused" ? resumePlayback(detail) : pausePlayback(detail);
  }

  function detachTimelineElement() {
    while (removeTimelineListeners.length) {
      const cleanup = removeTimelineListeners.pop();
      try {
        cleanup();
      } catch {
        // Listener cleanup is best effort.
      }
    }
    stopTimelineWindowCapture();
  }

  function attachTimelineElement(element = currentTimelineElement) {
    if (!element) return null;
    if (element === currentTimelineElement && removeTimelineListeners.length) return element;
    if (isTimelineScrubActive() && currentTimelineElement?.isConnected) {
      pendingTimelineElement = element;
      logCamera("camera.timeline.attach.deferred_during_scrub", {
        generation: playbackGeneration,
        elementConnected: currentTimelineElement?.isConnected !== false,
      }, { sampleMs: 1000, skipRecordEvent: true });
      return currentTimelineElement;
    }
    detachTimelineElement();
    currentTimelineElement = element;
    const listeners = [
      ["pointerdown", startTimelinePointer],
      ["pointermove", moveTimelinePointer],
      ["pointerup", endTimelinePointer],
      ["pointercancel", cancelTimelinePointer],
      ["lostpointercapture", endTimelinePointer],
      ["click", clickTimeline],
      ["keydown", keyTimeline],
    ];
    listeners.forEach(([type, handler]) => {
      element.addEventListener?.(type, handler);
      removeTimelineListeners.push(() => element.removeEventListener?.(type, handler));
    });
    return element;
  }

  function setTimelineModel(timeline = {}, frames = null, mode = "") {
    currentTimeline = timeline && typeof timeline === "object" ? timeline : {};
    currentFrames = Array.isArray(frames) ? frames : (Array.isArray(currentTimeline.frames) ? currentTimeline.frames : []);
    currentMode = cleanText(mode || currentTimeline.mode, currentMode);
  }

  function configure(next = {}) {
    if (next.artifactId !== undefined) currentArtifactId = cleanText(next.artifactId, currentArtifactId);
    if (next.documentId !== undefined) currentDocumentId = cleanText(next.documentId, currentDocumentId);
    if (next.canvas !== undefined) currentCanvas = next.canvas || null;
    if (next.timeline !== undefined || next.frames !== undefined || next.mode !== undefined) {
      setTimelineModel(next.timeline ?? currentTimeline ?? {}, next.frames ?? currentFrames, next.mode ?? currentMode);
    }
    if (next.timelineElement !== undefined && next.timelineElement !== currentTimelineElement) {
      if (next.timelineElement) attachTimelineElement(next.timelineElement);
      else detachTimelineElement();
    } else if (next.timelineElement && !removeTimelineListeners.length) {
      attachTimelineElement(next.timelineElement);
    }
    return api;
  }

  function cleanup(reason = "cleanup") {
    stopRenderLoop(reason);
    stopClockLoop(reason);
    abortPreviousLoads(reason);
    detachTimelineElement();
    while (cleanupStack.length) {
      try {
        cleanupStack.pop()?.();
      } catch {
        // Cleanup should be idempotent.
      }
    }
    activeSeek = null;
    currentSegment = null;
    clearTimelinePreviewVisualOnly();
    scrubOwner = null;
    userScrubbing = { active: false, pointerId: 0, target: null };
    playbackClock.source = "synthetic";
    playbackClock.anchorWallTimeMs = 0;
    playbackClock.anchorRecordingTimeMs = 0;
    playbackClock.displayedRecordingTimeMs = 0;
    playbackClock.targetTimeMs = 0;
    playbackClock.rate = 1;
    persistedSeekTimestampMs = 0;
    setPlaybackMode("live", { reason, skipPatch: true });
  }

  const api = {
    configure,
    cleanup,
    unmount: cleanup,
    seekTo,
    startRenderLoop,
    stopRenderLoop,
    pausePlayback,
    resumePlayback,
    togglePlayback,
    syncTimelineFromPlayback,
    markRecordedFrameDisplayed(frame = null, detail = {}) {
      return syncDisplayedPlaybackFrame(frame, {
        source: detail.source || "media",
        reason: detail.reason || "recorded-frame-displayed",
        generation: detail.generation,
        timestampMs: detail.timestampMs,
        syncTimeline: detail.syncTimeline,
      });
    },
    markFirstRecordedFrameDisplayed(frame = null, detail = {}) {
      const generation = Number(detail.generation || playbackGeneration);
      if (generation !== playbackGeneration) {
        logCamera("camera.stale.first_frame.ignored", {
          ...detail,
          generation,
          currentGeneration: playbackGeneration,
        }, { sampleMs: 1000 });
        return;
      }
      const timestampMs = syncDisplayedPlaybackFrame(frame, {
        ...detail,
        source: detail.source || activeSeek?.source || "media",
        reason: detail.reason || activeSeek?.reason || "recorded-first-frame-displayed",
        generation,
        timestampMs: detail.firstFrameTimeMs ?? detail.timestampMs,
      });
      if (!timestampMs) return;
      dispatchPlaybackPatch("recorded-first-frame-displayed", {
        source: detail.source || activeSeek?.source || "",
        reason: detail.reason || activeSeek?.reason || "",
        targetTimeMs: playbackClock.targetTimeMs,
        firstFrameTimeMs: Number.isFinite(timestampMs) ? timestampMs : playbackClock.targetTimeMs,
        segmentId: cleanText(detail.segmentId || currentSegment?.id || frame?.id, ""),
      });
    },
    recordTimelineUserEvent(kind = "pointerup", detail = {}) {
      return logCamera(`camera.timeline.user.${cleanText(kind, "pointerup")}`, {
        source: "user",
        ...detail,
      }, cleanText(kind, "") === "pointermove" ? { sampleMs: 250 } : {});
    },
    attachTimelineElement,
    detachTimelineElement,
    setTimelineModel,
    getCurrentPlaybackTimeMs,
    getState() {
      return {
        artifactId: currentArtifactId,
        documentId: currentDocumentId,
        generation: playbackGeneration,
        activeSeek: activeSeek ? { ...activeSeek } : null,
        currentSegment: currentSegment ? clone(currentSegment) : null,
        renderLoopId,
        clockLoopId,
        playbackClock: { ...playbackClock },
        userScrubbing: { ...userScrubbing },
        isSyncingTimelineFromPlayback,
      };
    },
  };

  configure({
    artifactId: currentArtifactId,
    documentId: currentDocumentId,
    canvas: currentCanvas,
    timelineElement: currentTimelineElement,
  });

  return api;
}

export function wisCameraTimelinePlaybackStartMs(frame = null, fallback = 0) {
  if (!frame || typeof frame !== "object") {
    const fallbackMs = Number(fallback);
    return Number.isFinite(fallbackMs) ? fallbackMs : 0;
  }
  const seekTargetMs = Number(frame.seek_target_ms ?? frame.seekTargetMs);
  if (Number.isFinite(seekTargetMs) && seekTargetMs > 0) return seekTargetMs;
  const snappedTimestampMs = Number(frame.snapped_timestamp_ms ?? frame.snappedTimestampMs);
  if (Number.isFinite(snappedTimestampMs) && snappedTimestampMs > 0) return snappedTimestampMs;
  const timestampMs = timelineFrameTimestampMs(frame);
  if (timestampMs !== null && timestampMs > 0) return timestampMs;
  const fallbackMs = Number(fallback);
  return Number.isFinite(fallbackMs) ? fallbackMs : 0;
}

export function wisCameraTimelineFramePlaybackKey(frame = null) {
  if (!frame || typeof frame !== "object") return "";
  const frameId = cleanText(frame.id, "");
  const timestampMs = wisCameraTimelinePlaybackStartMs(frame, timelineFrameTimestampMs(frame) || 0);
  return frameId ? `${frameId}|${Math.round(timestampMs)}` : "";
}

export function wisCameraMonotonicNow() {
  return typeof performance === "object" && typeof performance.now === "function" ? performance.now() : Date.now();
}

function playbackStateMap(runtimeState = {}) {
  if (runtimeState.wisCameraPlaybackStates instanceof Map) return runtimeState.wisCameraPlaybackStates;
  if (runtimeState.wisCameraRecordedSessions instanceof Map) return runtimeState.wisCameraRecordedSessions;
  const map = new Map();
  runtimeState.wisCameraPlaybackStates = map;
  runtimeState.wisCameraRecordedSessions = map;
  return map;
}

function playbackGenerationMap(runtimeState = {}) {
  if (runtimeState.wisCameraPlaybackGenerations instanceof Map) return runtimeState.wisCameraPlaybackGenerations;
  const map = new Map();
  runtimeState.wisCameraPlaybackGenerations = map;
  return map;
}

function timelineOwnerStateMap(runtimeState = {}) {
  if (runtimeState.wisCameraTimelineOwnerStates instanceof Map) return runtimeState.wisCameraTimelineOwnerStates;
  const map = new Map();
  runtimeState.wisCameraTimelineOwnerStates = map;
  return map;
}

function normalizeWisCameraTimelineOwnerState(ownerState = WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE) {
  const cleanState = cleanText(ownerState, WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE).toUpperCase();
  if (cleanState === WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_SEEKING) return WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_SEEKING;
  if (cleanState === WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PLAYING) return WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PLAYING;
  if (cleanState === WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PAUSED) return WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PAUSED;
  return WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE;
}

function wisCameraTimelineOwnerStateFromSession(session = null) {
  if (!session || session.mode !== "recorded") return WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE;
  const explicit = normalizeWisCameraTimelineOwnerState(session.ownerState || session.timelineOwnerState);
  if (explicit !== WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE) return explicit;
  const status = cleanText(session.status || session.state, "");
  if (["seeking", "buffering", "loading"].includes(status)) return WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_SEEKING;
  if (["paused", "ended", "gap", "stalled", "error"].includes(status)) return WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PAUSED;
  return WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PLAYING;
}

export function setWisCameraTimelineOwnerState(runtimeState = {}, streamId = "", ownerState = WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE, detail = {}) {
  const key = cleanText(streamId, "");
  if (!key) return null;
  const normalized = normalizeWisCameraTimelineOwnerState(ownerState);
  const map = timelineOwnerStateMap(runtimeState);
  const previousRecord = map.get(key) || null;
  const previousSession = wisCameraPlaybackState(runtimeState, key);
  const previousOwner = previousRecord?.ownerState || wisCameraTimelineOwnerStateFromSession(previousSession);
  const existingLoop = playbackLoopMap(runtimeState).get(key);
  const record = {
    streamId: key,
    ownerState: normalized,
    frameOwner: normalized === WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE ? "live" : "recorded",
    timelineOwner: normalized === WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE ? "live" : "recorded",
    generation: Number(detail.generation ?? detail.playbackGeneration ?? detail.seekToken ?? 0) || 0,
    sessionId: cleanText(detail.sessionId, ""),
    reason: cleanText(detail.reason, ""),
    updatedAt: Date.now(),
  };
  if (normalized === WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE) {
    map.delete(key);
  } else {
    map.set(key, record);
  }
  traceWisCameraBoundary("ownerMutation", {
    streamId: key,
    previousOwner,
    nextOwner: normalized,
    transition: `${previousOwner} -> ${normalized}`,
    frameLayerOwner: record.frameOwner,
    reason: record.reason,
    caller: cleanText(detail.caller || detail.source || detail.reason, "setWisCameraTimelineOwnerState"),
    generation: record.generation,
    sessionId: record.sessionId,
    activeRecordedPlaybackLoops: existingLoop && !existingLoop.disposed ? 1 : 0,
    activeReaders: existingLoop?.readerActive ? 1 : 0,
  }, { stack: true });
  return record;
}

export function wisCameraTimelineOwnerState(runtimeState = {}, streamId = "") {
  const key = cleanText(streamId, "");
  if (!key) return WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE;
  const session = wisCameraPlaybackState(runtimeState, key);
  const fromSession = wisCameraTimelineOwnerStateFromSession(session);
  if (fromSession !== WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE) return fromSession;
  return timelineOwnerStateMap(runtimeState).get(key)?.ownerState || WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE;
}

export function wisCameraRecordedOwnsTimeline(runtimeState = {}, streamId = "") {
  return wisCameraTimelineOwnerState(runtimeState, streamId) !== WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE;
}

function playbackTimerMap(runtimeState = {}) {
  if (runtimeState.wisCameraPlaybackRenderTimers instanceof Map) return runtimeState.wisCameraPlaybackRenderTimers;
  const map = new Map();
  runtimeState.wisCameraPlaybackRenderTimers = map;
  return map;
}

function playbackControllerMap(runtimeState = {}) {
  if (runtimeState.wisCameraPlaybackAbortControllers instanceof Map) return runtimeState.wisCameraPlaybackAbortControllers;
  const map = new Map();
  runtimeState.wisCameraPlaybackAbortControllers = map;
  return map;
}

function playbackObjectUrlMap(runtimeState = {}) {
  if (runtimeState.wisCameraPlaybackObjectUrls instanceof Map) return runtimeState.wisCameraPlaybackObjectUrls;
  const map = new Map();
  runtimeState.wisCameraPlaybackObjectUrls = map;
  return map;
}

function playbackLoopMap(runtimeState = {}) {
  if (runtimeState.wisCameraPlaybackLoops instanceof Map) return runtimeState.wisCameraPlaybackLoops;
  const map = new Map();
  runtimeState.wisCameraPlaybackLoops = map;
  return map;
}

function playbackPerfMap(runtimeState = {}) {
  if (runtimeState.wisCameraPlaybackPerf instanceof Map) return runtimeState.wisCameraPlaybackPerf;
  const map = new Map();
  runtimeState.wisCameraPlaybackPerf = map;
  return map;
}

function cameraVisibilityMap(runtimeState = {}) {
  if (runtimeState.wisCameraVisibility instanceof Map) return runtimeState.wisCameraVisibility;
  const map = new Map();
  runtimeState.wisCameraVisibility = map;
  return map;
}

function cameraSchedulerState(runtimeState = {}, env = globalThis) {
  const existing = runtimeState.wisCameraVisualScheduler;
  if (existing && typeof existing === "object") {
    if (env) existing.env = env;
    return existing;
  }
  const scheduler = {
    env,
    timer: 0,
    tasks: new Map(),
  };
  runtimeState.wisCameraVisualScheduler = scheduler;
  return scheduler;
}

function cameraSchedulerNow(env = globalThis) {
  return typeof env?.performance?.now === "function" ? env.performance.now() : wisCameraMonotonicNow();
}

function armWisCameraVisualScheduler(runtimeState = {}, env = globalThis) {
  const scheduler = cameraSchedulerState(runtimeState, env);
  if (scheduler.timer || !scheduler.tasks.size || typeof scheduler.env?.setTimeout !== "function") return;
  const nowMs = cameraSchedulerNow(scheduler.env);
  let nextAt = Infinity;
  scheduler.tasks.forEach((task) => {
    nextAt = Math.min(nextAt, Number(task.runAtMs || nowMs));
  });
  if (!Number.isFinite(nextAt)) return;
  const delayMs = Math.max(0, Math.round(nextAt - nowMs));
  scheduler.timer = scheduler.env.setTimeout(() => {
    scheduler.timer = 0;
    const runNowMs = cameraSchedulerNow(scheduler.env);
    const due = [];
    scheduler.tasks.forEach((task, key) => {
      if (Number(task.runAtMs || 0) <= runNowMs + 1) {
        scheduler.tasks.delete(key);
        due.push(task);
      }
    });
    due.forEach((task) => {
      try {
        task.callback?.(task.reason || "scheduler");
      } catch {
        // Camera scheduler tasks must not poison the shared loop.
      }
    });
    armWisCameraVisualScheduler(runtimeState, scheduler.env);
  }, delayMs);
}

function scheduleWisCameraVisualTask(runtimeState = {}, streamId = "", taskId = "visual", callback = null, delayMs = 0, env = globalThis, reason = "schedule") {
  const key = cleanText(streamId, "");
  if (!key || typeof callback !== "function") return "";
  const scheduler = cameraSchedulerState(runtimeState, env);
  const taskKey = `${key}:${cleanText(taskId, "visual")}`;
  const nowMs = cameraSchedulerNow(scheduler.env);
  scheduler.tasks.set(taskKey, {
    streamId: key,
    taskId: cleanText(taskId, "visual"),
    callback,
    reason: cleanText(reason, "schedule"),
    runAtMs: nowMs + Math.max(0, Number(delayMs) || 0),
  });
  if (scheduler.timer && typeof scheduler.env?.clearTimeout === "function") {
    try {
      scheduler.env.clearTimeout(scheduler.timer);
    } catch {
      // Timer cleanup is best effort.
    }
    scheduler.timer = 0;
  }
  armWisCameraVisualScheduler(runtimeState, scheduler.env);
  return taskKey;
}

function cancelWisCameraVisualTask(runtimeState = {}, streamId = "", taskId = "visual") {
  const scheduler = runtimeState.wisCameraVisualScheduler;
  const key = cleanText(streamId, "");
  if (!scheduler?.tasks || !key) return false;
  return scheduler.tasks.delete(`${key}:${cleanText(taskId, "visual")}`);
}

export function wisCameraVisibilityState(runtimeState = {}, streamId = "") {
  const key = cleanText(streamId, "");
  return key ? cameraVisibilityMap(runtimeState).get(key) || null : null;
}

export function setWisCameraVisibilityState(runtimeState = {}, streamId = "", visibility = {}) {
  const key = cleanText(streamId, "");
  if (!key) return null;
  const map = cameraVisibilityMap(runtimeState);
  const previous = map.get(key) || {};
  const nowMs = Number.isFinite(Number(visibility.nowMs)) ? Number(visibility.nowMs) : wisCameraMonotonicNow();
  const visible = visibility.visible !== undefined
    ? Boolean(visibility.visible)
    : (visibility.isIntersecting !== undefined ? Boolean(visibility.isIntersecting) : (previous.visible !== false));
  const ratio = Number(visibility.ratio ?? visibility.intersectionRatio ?? previous.ratio ?? (visible ? 1 : 0));
  const next = {
    streamId: key,
    slot: cleanText(visibility.slot || previous.slot, ""),
    visible,
    ratio: Number.isFinite(ratio) ? clamp(ratio, 0, 1) : (visible ? 1 : 0),
    focused: visibility.focused !== undefined ? Boolean(visibility.focused) : Boolean(previous.focused),
    active: visibility.active !== undefined ? Boolean(visibility.active) : Boolean(previous.active),
    hidden: visibility.hidden !== undefined ? Boolean(visibility.hidden) : Boolean(previous.hidden),
    collapsed: visibility.collapsed !== undefined ? Boolean(visibility.collapsed) : Boolean(previous.collapsed),
    pageHidden: visibility.pageHidden !== undefined ? Boolean(visibility.pageHidden) : Boolean(previous.pageHidden),
    lastVisibleAt: visible ? nowMs : Number(previous.lastVisibleAt || 0),
    updatedAt: nowMs,
  };
  map.set(key, next);
  return next;
}

function cameraDocumentHidden(env = globalThis) {
  try {
    return Boolean(env?.document?.hidden);
  } catch {
    return false;
  }
}

function cameraPolicyFps(policy = {}, key = "", fallback = 0) {
  const value = Number(policy[key]);
  return Number.isFinite(value) ? Math.max(0, value) : fallback;
}

function cameraIntervalForFps(fps = 0, policy = WIS_CAMERA_PERFORMANCE_POLICY) {
  const safeFps = Number(fps);
  if (!Number.isFinite(safeFps) || safeFps <= 0) return Math.max(1000, Number(policy.hiddenRetryMs || 2500));
  const interval = 1000 / safeFps;
  return Math.round(clamp(interval, Number(policy.minimumVisualIntervalMs || 67), Number(policy.maximumIdleIntervalMs || 5000)));
}

export function wisCameraPerformanceBudget(runtimeState = {}, streamId = "", options = {}) {
  const key = cleanText(streamId, "");
  const policy = {
    ...WIS_CAMERA_PERFORMANCE_POLICY,
    ...(options.policy && typeof options.policy === "object" ? options.policy : {}),
  };
  const visibility = key ? wisCameraVisibilityState(runtimeState, key) : null;
  const pageHidden = Boolean(options.pageHidden ?? visibility?.pageHidden ?? cameraDocumentHidden(options.env || globalThis));
  const explicitlyVisible = options.visible !== undefined ? Boolean(options.visible) : visibility?.visible;
  const ratio = Number(options.ratio ?? visibility?.ratio ?? (explicitlyVisible === false ? 0 : 1));
  const hidden = Boolean(options.hidden ?? visibility?.hidden);
  const collapsed = Boolean(options.collapsed ?? visibility?.collapsed);
  const visible = !hidden && !collapsed && explicitlyVisible !== false && (Number.isFinite(ratio) ? ratio > 0.01 : true);
  const focused = Boolean(options.focused ?? visibility?.focused);
  const active = Boolean(options.active ?? visibility?.active ?? focused);
  const interacting = Boolean(options.interacting ?? options.userInteracting);
  const mode = cleanText(options.mode, "live");
  const tier = pageHidden
    ? "background"
    : (!visible ? "offscreen" : ((focused || active || interacting) ? "focused" : "visible"));
  const recordedFps = tier === "focused"
    ? cameraPolicyFps(policy, "focusedRecordedFps", 12)
    : (tier === "visible"
      ? cameraPolicyFps(policy, "visibleRecordedFps", 4)
      : (tier === "background"
        ? cameraPolicyFps(policy, "backgroundRecordedFps", 0)
        : cameraPolicyFps(policy, "offscreenRecordedFps", 0)));
  const liveFps = tier === "focused"
    ? cameraPolicyFps(policy, "focusedLiveFps", 8)
    : (tier === "visible"
      ? cameraPolicyFps(policy, "visibleLiveFps", 3)
      : (tier === "background"
        ? cameraPolicyFps(policy, "backgroundLiveFps", 0.2)
        : cameraPolicyFps(policy, "offscreenLiveFps", 0)));
  const timelineFps = tier === "focused"
    ? cameraPolicyFps(policy, "focusedTimelineFps", 4)
    : (tier === "visible"
      ? cameraPolicyFps(policy, "visibleTimelineFps", 1)
      : (tier === "background"
        ? cameraPolicyFps(policy, "backgroundTimelineFps", 0)
        : cameraPolicyFps(policy, "offscreenTimelineFps", 0)));
  const modeFps = mode === "recorded" || mode === "recorded-playback"
    ? recordedFps
    : (mode === "timeline" || mode === "recorded-timeline" ? timelineFps : liveFps);
  const visualMinIntervalMs = cameraIntervalForFps(modeFps, policy);
  const retryMs = tier === "background"
    ? Math.max(Number(policy.backgroundRetryMs || 5000), visualMinIntervalMs)
    : (tier === "offscreen" ? Math.max(Number(policy.hiddenRetryMs || 2500), visualMinIntervalMs) : visualMinIntervalMs);
  return {
    streamId: key,
    tier,
    mode,
    focused,
    active,
    visible,
    ratio: Number.isFinite(ratio) ? clamp(ratio, 0, 1) : (visible ? 1 : 0),
    pageHidden,
    hidden,
    collapsed,
    recordedVisualFps: recordedFps,
    liveVisualFps: liveFps,
    timelineFps,
    visualFps: modeFps,
    allowVisualWork: modeFps > 0 && visible && !pageHidden,
    allowNetworkWork: (mode === "recorded" || mode === "recorded-playback") ? (modeFps > 0 && visible && !pageHidden) : (liveFps > 0 && visible && !pageHidden),
    allowTimelineWork: timelineFps > 0 && visible && !pageHidden,
    diagnosticsVerbose: Boolean(options.diagnosticsVerbose || CAMERA_DEBUG),
    visualMinIntervalMs,
    timelineMinIntervalMs: cameraIntervalForFps(timelineFps, policy),
    retryMs,
  };
}

function lastGoodFrameMap(runtimeState = {}) {
  if (runtimeState.wisCameraLastGoodFrames instanceof Map) return runtimeState.wisCameraLastGoodFrames;
  const map = new Map();
  runtimeState.wisCameraLastGoodFrames = map;
  return map;
}

function createPlaybackPerfBucket(streamId = "") {
  return {
    streamId: cleanText(streamId, ""),
    lastSampleAt: wisCameraMonotonicNow(),
    counters: {
      renders: 0,
      srcChanges: 0,
      frameSelections: 0,
      domReplacements: 0,
      imageLoads: 0,
      imageErrors: 0,
      statusPatches: 0,
      timelinePatches: 0,
      duplicateFrameSkips: 0,
    },
    active: {
      timers: 0,
      intervals: 0,
      rafLoops: 0,
      listeners: 0,
      readers: 0,
      playbackLoops: 0,
      schedulerTasks: 0,
      pendingDecodes: 0,
      objectUrls: 0,
    },
  };
}

function playbackPerfBucket(runtimeState = {}, streamId = "") {
  const key = cleanText(streamId, "");
  if (!key) return null;
  const map = playbackPerfMap(runtimeState);
  let bucket = map.get(key);
  if (!bucket) {
    bucket = createPlaybackPerfBucket(key);
    map.set(key, bucket);
  }
  return bucket;
}

export function noteWisCameraPerf(runtimeState = {}, streamId = "", counter = "", delta = 1) {
  const bucket = playbackPerfBucket(runtimeState, streamId);
  const key = cleanText(counter, "");
  if (!bucket || !key || !(key in bucket.counters)) return null;
  bucket.counters[key] += Number.isFinite(Number(delta)) ? Number(delta) : 1;
  return bucket;
}

export function setWisCameraPerfActive(runtimeState = {}, streamId = "", values = {}) {
  const bucket = playbackPerfBucket(runtimeState, streamId);
  if (!bucket || !values || typeof values !== "object") return null;
  Object.entries(values).forEach(([key, value]) => {
    if (key in bucket.active) bucket.active[key] = Math.max(0, Math.round(Number(value) || 0));
  });
  return bucket;
}

export function wisCameraActivePlaybackLoop(runtimeState = {}, streamId = "") {
  const key = cleanText(streamId, "");
  return key ? playbackLoopMap(runtimeState).get(key) || null : null;
}

export function sampleWisCameraPerf(runtimeState = {}, streamId = "", detail = {}, emitSample = null, options = {}) {
  const bucket = playbackPerfBucket(runtimeState, streamId);
  if (!bucket) return null;
  const nowMs = wisCameraMonotonicNow();
  if (!options.force && nowMs - Number(bucket.lastSampleAt || 0) < WIS_CAMERA_PERF_SAMPLE_MS) return null;
  const session = wisCameraPlaybackState(runtimeState, streamId);
  const loop = wisCameraActivePlaybackLoop(runtimeState, streamId);
  const clockTimeMs = wisCameraPlaybackClockMs(session, nowMs);
  const lastDisplayedFrameTimeMs = Number(session?.lastDisplayedFrameTimeMs || 0);
  const driftMs = lastDisplayedFrameTimeMs > 0 && Number.isFinite(clockTimeMs)
    ? Math.round(lastDisplayedFrameTimeMs - clockTimeMs)
    : null;
  const budget = wisCameraPerformanceBudget(runtimeState, streamId, { mode: session?.mode === "recorded" ? "recorded" : "live" });
  const active = {
    ...bucket.active,
    playbackLoops: loop && !loop.disposed ? 1 : 0,
    readers: loop?.readerActive ? 1 : 0,
  };
  const counters = { ...bucket.counters };
  const payload = {
    cameraId: cleanText(streamId, ""),
    mode: cleanText(session?.mode, "live"),
    ownerState: wisCameraTimelineOwnerState(runtimeState, streamId),
    frameLayerOwner: cleanText(session?.frameOwner, session?.mode === "recorded" ? "recorded" : "live"),
    timelineOwner: cleanText(session?.timelineOwner, session?.mode === "recorded" ? "recorded" : "live"),
    status: cleanText(session?.status, ""),
    generation: Number(session?.generation || detail.generation || 0),
    rendersPerSec: counters.renders,
    srcChangesPerSec: counters.srcChanges,
    frameSelectionsPerSec: counters.frameSelections,
    domReplacementsPerSec: counters.domReplacements,
    imageLoadEventsPerSec: counters.imageLoads,
    imageErrorEventsPerSec: counters.imageErrors,
    statusPatchesPerSec: counters.statusPatches,
    timelineUiPatchesPerSec: counters.timelinePatches,
	    duplicateFrameSkipsPerSec: counters.duplicateFrameSkips,
	    playbackReaderCreatedCount: Number(session?.playbackReaderCreatedCount || loop?.playbackReaderCreatedCount || 0),
	    playbackReaderDoneCount: Number(session?.playbackReaderDoneCount || loop?.playbackReaderDoneCount || 0),
	    playbackReaderAbortCount: Number(session?.playbackReaderAbortCount || loop?.playbackReaderAbortCount || 0),
	    playbackReaderErrorCount: Number(session?.playbackReaderErrorCount || loop?.playbackReaderErrorCount || 0),
	    playbackChunksReceived: Number(session?.playbackChunksReceived || loop?.playbackChunksReceived || 0),
	    playbackFramesParsed: Number(session?.playbackFramesParsed || loop?.playbackFramesParsed || 0),
	    playbackFramesCommitted: Number(session?.playbackFramesCommitted || loop?.playbackFramesCommitted || 0),
	    playbackReaderLastDoneReason: cleanText(session?.playbackReaderLastDoneReason || loop?.playbackReaderLastDoneReason, ""),
	    playbackReaderLifetimeMs: Number(session?.playbackReaderLifetimeMs || loop?.playbackReaderLifetimeMs || 0),
	    activeTimers: active.timers,
    activeIntervals: active.intervals,
    activeRafLoops: active.rafLoops,
    activeListeners: active.listeners,
    activeReaders: active.readers,
    activePlaybackLoops: active.playbackLoops,
    activeSchedulerTasks: active.schedulerTasks,
    pendingDecodesPerCamera: active.pendingDecodes,
    objectUrlsPerCamera: active.objectUrls,
    performanceTier: budget.tier,
    visualBudgetFps: budget.visualFps,
    visualBudgetIntervalMs: budget.visualMinIntervalMs,
    visualSuspended: !budget.allowVisualWork,
    queueLength: Number(session?.playbackQueueLength || detail.queueLength || 0),
    driftMs,
    ...detail,
  };
  Object.keys(bucket.counters).forEach((key) => {
    bucket.counters[key] = 0;
  });
  bucket.lastSampleAt = nowMs;
  if (typeof emitSample === "function") emitSample("camera.perf.sample", payload, { always: true });
  return payload;
}

function mediaElementRenderedSrc(media = null) {
  const visible = visibleWisCameraImage(media);
  return cleanText(visible?.currentSrc || visible?.src || visible?.dataset?.wisLastGoodSrc || media?.dataset?.wisLastGoodSrc, "");
}

export function rememberWisCameraLastGoodFrame(runtimeState = {}, streamId = "", frame = {}) {
  const key = cleanText(streamId, "");
  const src = cleanText(frame.src || frame.url || frame.currentSrc, "");
  if (!key || !src) return null;
  const timestampMs = Number(frame.timestampMs ?? frame.timestamp_ms ?? frame.frameTimestampMs);
  const generation = Number(frame.generation ?? frame.playbackGeneration ?? frame.seekToken);
  const record = {
    streamId: key,
    src,
    url: src,
    frameId: cleanText(frame.frameId || frame.id, ""),
    timestampMs: Number.isFinite(timestampMs) ? timestampMs : 0,
    playbackStream: cleanText(frame.playbackStream, ""),
    ownerKind: cleanText(frame.ownerKind || frame.kind, ""),
    sessionId: cleanText(frame.sessionId, ""),
    generation: Number.isFinite(generation) ? Math.max(0, Math.round(generation)) : 0,
    alt: cleanText(frame.alt, ""),
    updatedAt: Date.now(),
  };
  lastGoodFrameMap(runtimeState).set(key, record);
  return record;
}

export function rememberWisCameraLastGoodFrameFromImage(runtimeState = {}, streamId = "", image = null, fallbackFrame = null, options = {}) {
  const visible = visibleWisCameraImage(image);
  const src = mediaElementRenderedSrc(visible || image);
  if (!src) return null;
  const frameTimestampMs = Number(
    visible?.dataset?.wisPlaybackFrameMs
    || image?.dataset?.wisPlaybackFrameMs
    || fallbackFrame?.timestamp_ms
    || fallbackFrame?.timestampMs
    || fallbackFrame?.seek_target_ms
    || fallbackFrame?.seekTargetMs
  );
  return rememberWisCameraLastGoodFrame(runtimeState, streamId, {
    src,
    frameId: visible?.dataset?.wisPlaybackFrameId || image?.dataset?.wisPlaybackFrameId || fallbackFrame?.id,
    timestampMs: Number.isFinite(frameTimestampMs) ? frameTimestampMs : undefined,
    playbackStream: visible?.dataset?.wisPlaybackStream || image?.dataset?.wisPlaybackStream,
    ownerKind: visible?.dataset?.wisMediaOwner || image?.dataset?.wisMediaOwner || options.ownerKind,
    sessionId: visible?.dataset?.wisRecordedSessionId || image?.dataset?.wisRecordedSessionId || options.sessionId,
    generation: visible?.dataset?.wisMediaGeneration || image?.dataset?.wisMediaGeneration || options.generation,
    alt: visible?.alt || image?.alt,
  });
}

export function wisCameraLastGoodFrame(runtimeState = {}, streamId = "") {
  const key = cleanText(streamId, "");
  return key ? lastGoodFrameMap(runtimeState).get(key) || null : null;
}

export function wisCameraPlaybackState(runtimeState = {}, streamId = "") {
  const key = cleanText(streamId, "");
  return key ? playbackStateMap(runtimeState).get(key) || null : null;
}

export function wisCameraPlaybackClockMs(playbackState = null, nowMs = wisCameraMonotonicNow()) {
  if (!playbackState || typeof playbackState !== "object") return 0;
  const anchorRecordingTimeMs = Number(playbackState.anchorRecordingTimeMs ?? playbackState.recordedStartWallTime ?? playbackState.currentWallTime ?? 0);
  if (!Number.isFinite(anchorRecordingTimeMs) || anchorRecordingTimeMs <= 0) return 0;
  if (playbackState.clockPaused || playbackState.status === "seeking" || playbackState.status === "buffering") {
    const pausedTime = Number(playbackState.currentWallTime || anchorRecordingTimeMs);
    return Number.isFinite(pausedTime) && pausedTime > 0 ? pausedTime : anchorRecordingTimeMs;
  }
  const anchorWallTimeMs = Number(playbackState.anchorWallTimeMs ?? playbackState.playbackStartedAtMonotonic ?? Number(nowMs));
  const rate = Number(playbackState.rate ?? playbackState.playbackRate ?? 1);
  const safeRate = Number.isFinite(rate) && rate > 0 ? rate : 1;
  return anchorRecordingTimeMs + (Math.max(0, Number(nowMs) - anchorWallTimeMs) * safeRate);
}

function wisCameraRuntimeTracePayload(runtimeState = {}, streamId = "", extra = {}) {
  const key = cleanText(streamId, "");
  const session = wisCameraPlaybackState(runtimeState, key);
  const timeline = runtimeState?.wisCameraTimeline?.streamId === key ? runtimeState.wisCameraTimeline : {};
  const frames = Array.isArray(timeline?.frames) ? timeline.frames : [];
  const nowMs = Number.isFinite(Number(extra.nowMs)) ? Number(extra.nowMs) : wisCameraMonotonicNow();
  const playbackClockMs = Number.isFinite(Number(extra.playbackClockMs))
    ? Number(extra.playbackClockMs)
    : wisCameraPlaybackClockMs(session, nowMs);
  const requestedTimestampMs = Number(
    extra.requestedTimestampMs
    ?? session?.requestedSeekTimestampMs
    ?? session?.persistedSeekTimestampMs
    ?? session?.requestedRecordingTimeMs
    ?? session?.anchorRecordingTimeMs
    ?? 0
  );
  const persistedSeekTimestampMs = Number(
    extra.persistedSeekTimestampMs
    ?? session?.persistedSeekTimestampMs
    ?? session?.requestedSeekTimestampMs
    ?? session?.requestedRecordingTimeMs
    ?? requestedTimestampMs
    ?? 0
  );
  const windowModel = wisCameraTimelineTimeWindow(timeline, frames, {
    playbackPosition: playbackClockMs || persistedSeekTimestampMs,
  });
  return {
    owner: wisCameraTimelineOwnerState(runtimeState, key),
    requestedTimestampMs: Number.isFinite(requestedTimestampMs) ? requestedTimestampMs : 0,
    persistedSeekTimestampMs: Number.isFinite(persistedSeekTimestampMs) ? persistedSeekTimestampMs : 0,
    mediaAnchorMs: Number(extra.mediaAnchorMs ?? session?.anchorRecordingTimeMs ?? 0),
    wallAnchorMs: Number(extra.wallAnchorMs ?? session?.anchorWallTimeMs ?? 0),
    playbackClockMs: Number.isFinite(playbackClockMs) ? playbackClockMs : 0,
    visibleFrameMs: Number(extra.visibleFrameMs ?? session?.lastDisplayedFrameTimeMs ?? session?.currentWallTime ?? 0),
    archiveWindowStartMs: Number(extra.archiveWindowStartMs ?? timeline?.availableRange?.start_ms ?? timeline?.available_range?.start_ms ?? timeline?.range?.start_ms ?? windowModel.visibleStart ?? 0),
    archiveWindowEndMs: Number(extra.archiveWindowEndMs ?? timeline?.availableRange?.end_ms ?? timeline?.available_range?.end_ms ?? timeline?.range?.end_ms ?? windowModel.visibleEnd ?? 0),
    generation: Number(extra.generation ?? session?.generation ?? 0),
    paused: Boolean(extra.paused ?? session?.clockPaused ?? session?.status === "paused"),
    playbackRate: Number(extra.playbackRate ?? session?.playbackRate ?? session?.rate ?? 1),
    ...extra,
  };
}

function traceWisCameraRuntimePlayback(event = "", runtimeState = {}, streamId = "", extra = {}) {
  return traceWisCameraBoundary(event, wisCameraRuntimeTracePayload(runtimeState, streamId, extra));
}

export function pauseWisCameraPlaybackState(runtimeState = {}, streamId = "", options = {}) {
  const key = cleanText(streamId, "");
  if (!wisCameraPlaybackMatches(runtimeState, key, options)) return null;
  const session = wisCameraPlaybackState(runtimeState, key);
  if (!session?.mode || session.mode !== "recorded") return null;
  const nowMs = Number.isFinite(Number(options.nowMs)) ? Number(options.nowMs) : wisCameraMonotonicNow();
  const currentMs = wisCameraPlaybackClockMs(session, nowMs) || session.currentWallTime || session.anchorRecordingTimeMs;
  session.currentWallTime = currentMs;
  session.anchorRecordingTimeMs = currentMs;
  session.recordedStartWallTime = currentMs;
  session.anchorWallTimeMs = nowMs;
  session.playbackStartedAtMonotonic = nowMs;
  session.clockPaused = true;
  session.userPaused = true;
  session.state = "paused";
  session.status = "paused";
  session.rate = 1;
  session.playbackRate = 1;
  session.ownerState = WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PAUSED;
  session.timelineOwnerState = WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PAUSED;
  session.frameOwner = "recorded";
  session.timelineOwner = "recorded";
  session.updatedAt = Date.now();
  setWisCameraTimelineOwnerState(runtimeState, key, WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PAUSED, {
    generation: session.generation,
    sessionId: session.id,
    reason: cleanText(options.reason, "pause"),
  });
  traceWisCameraRuntimePlayback("playback.pause", runtimeState, key, {
    generation: session.generation,
    requestedTimestampMs: session.requestedSeekTimestampMs,
    persistedSeekTimestampMs: session.persistedSeekTimestampMs,
    mediaAnchorMs: session.anchorRecordingTimeMs,
    wallAnchorMs: session.anchorWallTimeMs,
    playbackClockMs: currentMs,
    visibleFrameMs: session.lastDisplayedFrameTimeMs || currentMs,
    paused: true,
    playbackRate: 1,
    reason: cleanText(options.reason, "pause"),
  });
  return session;
}

export function resumeWisCameraPlaybackState(runtimeState = {}, streamId = "", options = {}) {
  const key = cleanText(streamId, "");
  if (!wisCameraPlaybackMatches(runtimeState, key, options)) return null;
  const session = wisCameraPlaybackState(runtimeState, key);
  if (!session?.mode || session.mode !== "recorded") return null;
  const nowMs = Number.isFinite(Number(options.nowMs)) ? Number(options.nowMs) : wisCameraMonotonicNow();
  const resumeMs = Number(session.currentWallTime || session.anchorRecordingTimeMs || session.lastDisplayedFrameTimeMs || session.requestedSeekTimestampMs || 0);
  if (!Number.isFinite(resumeMs) || resumeMs <= 0) return null;
  session.currentWallTime = resumeMs;
  session.anchorRecordingTimeMs = resumeMs;
  session.recordedStartWallTime = resumeMs;
  session.anchorWallTimeMs = nowMs;
  session.playbackStartedAtMonotonic = nowMs;
  session.clockPaused = false;
  session.userPaused = false;
  session.state = "recordedPlaying";
  session.status = "recordedPlaying";
  session.rate = 1;
  session.playbackRate = 1;
  session.ownerState = WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PLAYING;
  session.timelineOwnerState = WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PLAYING;
  session.frameOwner = "recorded";
  session.timelineOwner = "recorded";
  session.updatedAt = Date.now();
  setWisCameraTimelineOwnerState(runtimeState, key, WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PLAYING, {
    generation: session.generation,
    sessionId: session.id,
    reason: cleanText(options.reason, "resume"),
  });
  traceWisCameraRuntimePlayback("playback.resume", runtimeState, key, {
    generation: session.generation,
    requestedTimestampMs: session.requestedSeekTimestampMs,
    persistedSeekTimestampMs: session.persistedSeekTimestampMs,
    mediaAnchorMs: session.anchorRecordingTimeMs,
    wallAnchorMs: session.anchorWallTimeMs,
    playbackClockMs: resumeMs,
    visibleFrameMs: session.lastDisplayedFrameTimeMs || resumeMs,
    paused: false,
    playbackRate: 1,
    reason: cleanText(options.reason, "resume"),
  });
  traceWisCameraRuntimePlayback("playback.timebase.anchored", runtimeState, key, {
    generation: session.generation,
    requestedTimestampMs: session.requestedSeekTimestampMs,
    persistedSeekTimestampMs: session.persistedSeekTimestampMs,
    mediaAnchorMs: session.anchorRecordingTimeMs,
    wallAnchorMs: session.anchorWallTimeMs,
    playbackClockMs: resumeMs,
    visibleFrameMs: session.lastDisplayedFrameTimeMs || resumeMs,
    paused: false,
    playbackRate: 1,
    reason: cleanText(options.reason, "resume"),
  });
  const loop = wisCameraActivePlaybackLoop(runtimeState, key);
  try {
    loop?.resume?.(cleanText(options.reason, "resume"));
  } catch {
    // Active playback loop resume is best effort; the state clock is authoritative.
  }
  return session;
}

export function stopWisCameraPlaybackState(runtimeState = {}, streamId = "", options = {}) {
  const key = cleanText(streamId, "");
  if (!key) return;
  cancelWisCameraVisualTask(runtimeState, key, "playback-start");
  cancelWisCameraVisualTask(runtimeState, key, "playback-display");
  cancelWisCameraVisualTask(runtimeState, key, "playback-health");
  const loop = playbackLoopMap(runtimeState).get(key);
  if (loop) {
    try {
      loop.abort?.("playback-state-stop");
    } catch {
      // Loop cleanup is best-effort across browser/test runtimes.
    }
    playbackLoopMap(runtimeState).delete(key);
  }
  const timer = playbackTimerMap(runtimeState).get(key);
  if (timer) {
    try {
      globalThis.clearTimeout?.(timer);
      globalThis.clearInterval?.(timer);
    } catch {
      // Timer cleanup is best-effort across browser/test runtimes.
    }
    playbackTimerMap(runtimeState).delete(key);
  }
  const controller = playbackControllerMap(runtimeState).get(key);
  if (controller) {
    try {
      controller.abort();
    } catch {
      // Already closed.
    }
    playbackControllerMap(runtimeState).delete(key);
  }
  const objectUrl = playbackObjectUrlMap(runtimeState).get(key);
  if (objectUrl && !options.keepState) {
    try {
      globalThis.URL?.revokeObjectURL?.(objectUrl);
    } catch {
      // Object URL may already have been released.
    }
    playbackObjectUrlMap(runtimeState).delete(key);
  }
	  if (!options.keepState) playbackStateMap(runtimeState).delete(key);
	  if (!options.keepState) {
	    traceWisCameraBoundary("fallback.live", {
	      functionName: "stopWisCameraPlaybackState",
	      streamId: key,
	      reason: cleanText(options.reason, "playback-state-stop"),
	      explicit: Boolean(options.explicitLive),
	      previousOwner: wisCameraTimelineOwnerState(runtimeState, key),
	      nextOwner: WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE,
	    }, { stack: true });
	    setWisCameraTimelineOwnerState(runtimeState, key, WIS_CAMERA_TIMELINE_OWNER_STATES.LIVE, {
	      reason: cleanText(options.reason, "playback-state-stop"),
	      caller: "stopWisCameraPlaybackState",
	    });
	  }
}

export function startWisCameraPlaybackSeek(runtimeState = {}, streamId = "", frame = null, options = {}) {
  const key = cleanText(streamId, "");
  if (!key || !frame?.id) return null;
  const states = playbackStateMap(runtimeState);
  const existing = states.get(key);
  if (
    existing?.mode === "recorded"
    && !options.restart
    && !options.force
    && wisCameraTimelineFramePlaybackKey(existing?.requestedFrame || existing?.frame) === wisCameraTimelineFramePlaybackKey(frame)
    && !["error", "gap", "stalled"].includes(cleanText(existing.status, ""))
  ) {
    return existing;
  }
  const generations = playbackGenerationMap(runtimeState);
  const requestedGeneration = Number(options.generation ?? options.playbackGeneration ?? options.seekToken);
  const currentGeneration = Number(generations.get(key) || 0);
  if (Number.isFinite(requestedGeneration) && requestedGeneration > 0 && currentGeneration > Math.round(requestedGeneration)) {
    return existing?.mode === "recorded" ? existing : null;
  }
	  const generation = Number.isFinite(requestedGeneration) && requestedGeneration > 0
	    ? Math.round(requestedGeneration)
	    : currentGeneration + 1;
	  generations.set(key, generation);
	  traceWisCameraBoundary("camera.seekRequested.state", {
	    functionName: "startWisCameraPlaybackSeek",
	    streamId: key,
	    requestedTimestampMs: wisCameraTimelinePlaybackStartMs(frame, timelineFrameTimestampMs(frame) || Date.now()),
	    generation,
	    previousGeneration: currentGeneration,
	    previousSessionId: cleanText(existing?.id, ""),
	    previousStatus: cleanText(existing?.status, ""),
	    recordedPlaybackPossible: Boolean(frame?.id && frame?.url),
	    activeRecordedPlaybackLoops: playbackLoopMap(runtimeState).get(key) && !playbackLoopMap(runtimeState).get(key)?.disposed ? 1 : 0,
	  });
	  stopWisCameraPlaybackState(runtimeState, key, { keepState: true });
  const nowMs = Number.isFinite(Number(options.nowMs)) ? Number(options.nowMs) : wisCameraMonotonicNow();
  const recordingTimeMs = wisCameraTimelinePlaybackStartMs(frame, timelineFrameTimestampMs(frame) || Date.now());
  const userPaused = Boolean(options.paused || options.userPaused);
  const session = {
    id: `${key}-${cleanText(frame.id, "frame")}-${generation}`,
    mode: "recorded",
    ownerState: WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_SEEKING,
    timelineOwnerState: WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_SEEKING,
    frameOwner: "recorded",
    timelineOwner: "recorded",
    state: "seeking",
    status: "seeking",
    streamId: key,
    generation,
    playbackGeneration: generation,
    seekToken: generation,
    frame: clone(frame),
    requestedFrame: clone(frame),
    renderedFrame: null,
    requestedRecordingTimeMs: recordingTimeMs,
    requestedSeekTimestampMs: recordingTimeMs,
    persistedSeekTimestampMs: recordingTimeMs,
    anchorWallTimeMs: nowMs,
    anchorRecordingTimeMs: recordingTimeMs,
    recordedStartWallTime: recordingTimeMs,
    playbackStartedAtMonotonic: nowMs,
    rate: 1,
    playbackRate: 1,
    currentWallTime: recordingTimeMs,
    clockPaused: true,
    userPaused,
    firstRecordedFrameDisplayed: false,
    firstFrameDisplayedAtMonotonic: 0,
    bufferingStartedAtMonotonic: nowMs,
    rebufferingStartedAtMonotonic: 0,
    catchingUpStartedAtMonotonic: 0,
    lastPacketTimestampMs: 0,
    lastPacketArrivalMonotonicMs: 0,
    lastPacketIntervalMs: 0,
    lastPacketTimestampIntervalMs: 0,
    lastDisplayedFrameTimeMs: 0,
    lastDisplayedAtMonotonic: 0,
    playbackDriftMs: 0,
    streamEnded: false,
    readerActive: false,
    playbackQueueLength: 0,
	    playbackRestartCount: 0,
	    playbackReaderCreatedCount: 0,
	    playbackReaderDoneCount: 0,
	    playbackReaderAbortCount: 0,
	    playbackReaderErrorCount: 0,
	    playbackChunksReceived: 0,
	    playbackFramesParsed: 0,
	    playbackFramesCommitted: 0,
	    playbackReaderLastDoneReason: "",
	    playbackReaderLifetimeMs: 0,
	    createdAt: Date.now(),
	    updatedAt: Date.now(),
	    explicitSeek: Boolean(options.explicitSeek),
	  };
  states.set(key, session);
  setWisCameraTimelineOwnerState(runtimeState, key, WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_SEEKING, {
    generation,
    sessionId: session.id,
    reason: cleanText(options.reason, "recorded-seek"),
  });
  traceWisCameraRuntimePlayback("timeline.seek.persisted", runtimeState, key, {
    generation,
    requestedTimestampMs: recordingTimeMs,
    persistedSeekTimestampMs: recordingTimeMs,
    mediaAnchorMs: recordingTimeMs,
    wallAnchorMs: nowMs,
    playbackClockMs: recordingTimeMs,
    visibleFrameMs: 0,
    paused: true,
    playbackRate: 1,
    reason: cleanText(options.reason, "recorded-seek"),
  });
  return session;
}

export function wisCameraPlaybackMatches(runtimeState = {}, streamId = "", token = {}) {
  const key = cleanText(streamId, "");
  const session = wisCameraPlaybackState(runtimeState, key);
  if (!session) return false;
  const sessionId = cleanText(token.sessionId, "");
  if (sessionId && session.id !== sessionId) return false;
  const generation = Number(token.generation ?? token.playbackGeneration ?? token.seekToken);
  if (Number.isFinite(generation) && generation > 0 && Number(session.generation || 0) !== generation) return false;
  return true;
}

export function setWisCameraPlaybackBuffering(runtimeState = {}, streamId = "", token = {}) {
  const key = cleanText(streamId, "");
  if (!wisCameraPlaybackMatches(runtimeState, key, token)) return null;
  const session = wisCameraPlaybackState(runtimeState, key);
  const nowMs = Number.isFinite(Number(token.nowMs)) ? Number(token.nowMs) : wisCameraMonotonicNow();
  const previousStatus = cleanText(session.status, "");
  const nextStatus = session.firstRecordedFrameDisplayed || session.lastDisplayedFrameTimeMs
    ? cleanText(token.status || token.state, "rebuffering")
    : cleanText(token.status || token.state, "buffering");
  if (previousStatus === nextStatus) return session;
  session.currentWallTime = wisCameraPlaybackClockMs(session, nowMs) || session.currentWallTime;
  session.bufferingStartedAtMonotonic = nowMs;
  if (session.firstRecordedFrameDisplayed || session.lastDisplayedFrameTimeMs) {
    session.state = nextStatus;
    session.status = nextStatus;
    session.rebufferingStartedAtMonotonic = session.rebufferingStartedAtMonotonic || nowMs;
    session.clockPaused = false;
    session.ownerState = WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PLAYING;
    session.timelineOwnerState = WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PLAYING;
  } else {
    session.state = nextStatus;
    session.status = nextStatus;
    session.clockPaused = true;
    session.ownerState = WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_SEEKING;
    session.timelineOwnerState = WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_SEEKING;
  }
  session.frameOwner = "recorded";
  session.timelineOwner = "recorded";
  setWisCameraTimelineOwnerState(runtimeState, key, session.ownerState, {
    generation: session.generation,
    sessionId: session.id,
    reason: nextStatus,
  });
  noteWisCameraPerf(runtimeState, key, "statusPatches");
  session.updatedAt = Date.now();
  return session;
}

export function setWisCameraPlaybackFrame(runtimeState = {}, streamId = "", frame = null, options = {}) {
  const key = cleanText(streamId, "");
  if (!wisCameraPlaybackMatches(runtimeState, key, options)) return null;
  const session = wisCameraPlaybackState(runtimeState, key);
  const timestampMs = wisCameraTimelinePlaybackStartMs(frame || session.frame, session.currentWallTime || session.anchorRecordingTimeMs || Date.now());
  const nowMs = Number.isFinite(Number(options.nowMs)) ? Number(options.nowMs) : wisCameraMonotonicNow();
  const renderedFrame = { ...(session.frame || {}), ...(frame || {}), timestamp_ms: timestampMs };
  const nextStatus = cleanText(options.status || "recordedPlaying", "recordedPlaying");
  const previousStatus = cleanText(session.status, "");
  const currentFrameId = cleanText(session.renderedFrame?.id || session.frame?.id, "");
  const nextFrameId = cleanText(renderedFrame.id, "");
  const sameRenderedFrame = Math.round(Number(session.lastDisplayedFrameTimeMs || 0)) === Math.round(timestampMs)
    && (!currentFrameId || !nextFrameId || currentFrameId === nextFrameId);
  if (
    sameRenderedFrame
    && previousStatus === nextStatus
    && !options.firstFrameDisplayed
    && options.updateClockAnchor !== false
  ) {
    noteWisCameraPerf(runtimeState, key, "duplicateFrameSkips");
    return session;
  }
  const wasFirstRecordedFrame = !session.firstRecordedFrameDisplayed || options.firstFrameDisplayed;
  session.renderedFrame = renderedFrame;
  session.lastDisplayedFrameTimeMs = timestampMs;
  session.lastDisplayedAtMonotonic = nowMs;
  if (wasFirstRecordedFrame) {
    session.firstRecordedFrameDisplayed = true;
    session.firstFrameDisplayedAtMonotonic = session.firstFrameDisplayedAtMonotonic || nowMs;
  }
  if (options.updateClockAnchor !== false) {
    session.frame = renderedFrame;
    session.anchorWallTimeMs = nowMs;
    session.anchorRecordingTimeMs = timestampMs;
    session.recordedStartWallTime = timestampMs;
    session.playbackStartedAtMonotonic = nowMs;
    session.currentWallTime = timestampMs;
    session.rate = Number.isFinite(Number(options.rate)) && Number(options.rate) > 0 ? Number(options.rate) : 1;
    session.playbackRate = session.rate;
  }
  session.clockPaused = options.paused === undefined ? false : Boolean(options.paused);
  if (options.paused !== undefined) session.userPaused = Boolean(options.paused);
  session.state = cleanText(options.state || nextStatus, "recordedPlaying");
  session.status = nextStatus;
  session.ownerState = session.clockPaused
    ? WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PAUSED
    : WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PLAYING;
  session.timelineOwnerState = session.ownerState;
  session.frameOwner = "recorded";
  session.timelineOwner = "recorded";
  setWisCameraTimelineOwnerState(runtimeState, key, session.ownerState, {
    generation: session.generation,
    sessionId: session.id,
    reason: nextStatus,
  });
  if (previousStatus !== nextStatus) noteWisCameraPerf(runtimeState, key, "statusPatches");
  session.pendingPlaybackStatus = "";
  session.pendingPlaybackStatusSinceMonotonic = 0;
  session.bufferingStartedAtMonotonic = 0;
  session.rebufferingStartedAtMonotonic = 0;
  session.updatedAt = Date.now();
  if (wasFirstRecordedFrame && !session.clockPaused) {
    traceWisCameraRuntimePlayback("playback.timebase.anchored", runtimeState, key, {
      generation: session.generation,
      requestedTimestampMs: session.requestedSeekTimestampMs,
      persistedSeekTimestampMs: session.persistedSeekTimestampMs,
      mediaAnchorMs: session.anchorRecordingTimeMs,
      wallAnchorMs: session.anchorWallTimeMs,
      playbackClockMs: wisCameraPlaybackClockMs(session, nowMs),
      visibleFrameMs: timestampMs,
      paused: false,
      playbackRate: session.playbackRate,
      reason: options.reason || nextStatus,
    });
    traceWisCameraRuntimePlayback("playback.autoplay.started", runtimeState, key, {
      generation: session.generation,
      requestedTimestampMs: session.requestedSeekTimestampMs,
      persistedSeekTimestampMs: session.persistedSeekTimestampMs,
      mediaAnchorMs: session.anchorRecordingTimeMs,
      wallAnchorMs: session.anchorWallTimeMs,
      playbackClockMs: wisCameraPlaybackClockMs(session, nowMs),
      visibleFrameMs: timestampMs,
      paused: false,
      playbackRate: session.playbackRate,
      reason: options.reason || nextStatus,
    });
  }
  return session;
}

export function setWisCameraPlaybackEnded(runtimeState = {}, streamId = "", options = {}) {
  const key = cleanText(streamId, "");
  if (!wisCameraPlaybackMatches(runtimeState, key, options)) return null;
  const session = wisCameraPlaybackState(runtimeState, key);
  const nowMs = Number.isFinite(Number(options.nowMs)) ? Number(options.nowMs) : wisCameraMonotonicNow();
  const previousStatus = cleanText(session.status, "");
  const nextStatus = cleanText(options.status || "ended", "ended");
  if (previousStatus === nextStatus) return session;
  session.currentWallTime = wisCameraPlaybackClockMs(session, nowMs) || session.currentWallTime;
  session.clockPaused = true;
  session.state = options.state || "paused";
  session.status = nextStatus;
  session.ownerState = WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PAUSED;
  session.timelineOwnerState = WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PAUSED;
  session.frameOwner = "recorded";
  session.timelineOwner = "recorded";
  setWisCameraTimelineOwnerState(runtimeState, key, WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PAUSED, {
    generation: session.generation,
    sessionId: session.id,
    reason: nextStatus,
  });
  noteWisCameraPerf(runtimeState, key, "statusPatches");
  session.updatedAt = Date.now();
  return session;
}

export function setWisCameraPlaybackError(runtimeState = {}, streamId = "", error = "", options = {}) {
  const key = cleanText(streamId, "");
  if (!wisCameraPlaybackMatches(runtimeState, key, options)) return null;
  const session = wisCameraPlaybackState(runtimeState, key);
  if (cleanText(session.status, "") === "error" && cleanText(session.error, "") === cleanText(error, "Playback failed")) return session;
  session.currentWallTime = wisCameraPlaybackClockMs(session) || session.currentWallTime;
  session.clockPaused = true;
  session.state = "error";
  session.status = "error";
  session.error = cleanText(error, "Playback failed");
  session.ownerState = WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PAUSED;
  session.timelineOwnerState = WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PAUSED;
  session.frameOwner = "recorded";
  session.timelineOwner = "recorded";
  setWisCameraTimelineOwnerState(runtimeState, key, WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PAUSED, {
    generation: session.generation,
    sessionId: session.id,
    reason: "error",
  });
  noteWisCameraPerf(runtimeState, key, "statusPatches");
  session.updatedAt = Date.now();
  return session;
}

function timelineFramesRangeMs(frames = []) {
  if (!Array.isArray(frames) || !frames.length) return null;
  let start = Infinity;
  let end = -Infinity;
  frames.forEach((frame) => {
    const timestampMs = timelineFrameTimestampMs(frame);
    if (timestampMs === null) return;
    start = Math.min(start, timestampMs);
    end = Math.max(end, timestampMs);
  });
  if (!Number.isFinite(start) || !Number.isFinite(end) || start === end) return null;
  return { start, end };
}

export function wisCameraTimelineTimeWindow(timeline = {}, frames = [], options = {}) {
  const frameRange = timelineFramesRangeMs(frames);
  const retentionRange = timelineRangeMs(timeline?.availableRange || timeline?.available_range || timeline?.retentionRange || timeline?.retention_range) || frameRange;
  const visibleRange = timelineRangeMs(timeline?.visibleRange || timeline?.visible_range || timeline?.range) || retentionRange || frameRange;
  const retentionStart = retentionRange?.start ?? visibleRange?.start ?? 0;
  const retentionEnd = retentionRange?.end ?? visibleRange?.end ?? 0;
  const visibleStart = visibleRange?.start ?? retentionStart;
  const visibleEnd = visibleRange?.end ?? retentionEnd;
  const rawPlaybackPosition = Number(
    options.playbackPosition
      ?? options.playback_position
      ?? timeline?.playbackPosition
      ?? timeline?.playback_position
      ?? 0
  );
  const playbackPosition = Number.isFinite(rawPlaybackPosition) && visibleEnd > visibleStart
    ? clamp(rawPlaybackPosition, visibleStart, visibleEnd)
    : (Number.isFinite(rawPlaybackPosition) ? rawPlaybackPosition : 0);
  return {
    retentionStart,
    retentionEnd,
    visibleStart,
    visibleEnd,
    playbackPosition,
  };
}

export function wisCameraTimelineFrameClosestToTime(frames = [], targetTimeMs = 0, options = {}) {
  if (!Array.isArray(frames) || !frames.length) return null;
  const targetTime = Number(targetTimeMs);
  if (!Number.isFinite(targetTime)) return null;
  const visibleStart = Number(options.visibleStart ?? options.visible_start);
  const visibleEnd = Number(options.visibleEnd ?? options.visible_end);
  const hasVisibleWindow = Number.isFinite(visibleStart) && Number.isFinite(visibleEnd) && visibleEnd > visibleStart;
  const nearest = (useVisibleWindow) => {
    let bestFrame = null;
    let bestDistance = Infinity;
    frames.forEach((frame) => {
      const timestampMs = timelineFrameTimestampMs(frame);
      if (timestampMs === null) return;
      if (useVisibleWindow && (timestampMs < visibleStart || timestampMs > visibleEnd)) return;
      const distance = Math.abs(timestampMs - targetTime);
      if (distance < bestDistance) {
        bestDistance = distance;
        bestFrame = frame;
      }
    });
    return bestFrame;
  };
  return (hasVisibleWindow ? nearest(true) : null) || nearest(false);
}

export function wisCameraTimelineTargetAtRatio(timeline = {}, frames = [], ratio = 1, options = {}) {
  const boundedRatio = clamp(Number(ratio), 0, 1);
  const windowModel = wisCameraTimelineTimeWindow(timeline, frames, options);
  const hasVisibleWindow = windowModel.visibleEnd > windowModel.visibleStart;
  const rawTargetTime = hasVisibleWindow
    ? windowModel.visibleStart + (boundedRatio * (windowModel.visibleEnd - windowModel.visibleStart))
    : (windowModel.visibleEnd || windowModel.visibleStart || 0);
  const targetTime = hasVisibleWindow
    ? clamp(rawTargetTime, windowModel.visibleStart, windowModel.visibleEnd)
    : rawTargetTime;
  const snappedFrame = wisCameraTimelineFrameClosestToTime(frames, targetTime, windowModel);
  const snappedFrameTime = timelineFrameTimestampMs(snappedFrame);
  return {
    ...windowModel,
    ratio: boundedRatio,
    targetTime,
    snappedTargetTime: snappedFrameTime === null ? targetTime : snappedFrameTime,
    snappedFrame,
  };
}

export function wisCameraNextTimelineFrame(frames = [], frame = null) {
  if (!Array.isArray(frames) || !frames.length || !frame) return null;
  const frameId = cleanText(frame?.id, "");
  if (frameId) {
    const index = frames.findIndex((candidate) => cleanText(candidate?.id, "") === frameId);
    if (index >= 0) return frames[index + 1] || null;
  }
  const timestampMs = Number(frame?.timestamp_ms || 0);
  if (!Number.isFinite(timestampMs) || timestampMs <= 0) return null;
  return frames.find((candidate) => Number(candidate?.timestamp_ms || 0) > timestampMs) || null;
}

export function wisCameraTimelinePlaybackDelayMs(currentFrame = null, nextFrame = null, options = {}) {
  const minMs = Math.max(100, Number(options.minMs || 800));
  const maxMs = Math.max(minMs, Number(options.maxMs || 1200));
  const fallbackMs = clamp(Number(options.fallbackMs || 1000), minMs, maxMs);
  const currentMs = Number(currentFrame?.timestamp_ms || 0);
  const nextMs = Number(nextFrame?.timestamp_ms || 0);
  if (!Number.isFinite(currentMs) || !Number.isFinite(nextMs) || currentMs <= 0 || nextMs <= currentMs) {
    return Math.round(fallbackMs);
  }
  return Math.round(clamp(nextMs - currentMs, minMs, maxMs));
}

export function createWisCameraPendingTimelineSeek(streamId, seek = 1, mode = "live", nowMs = Date.now()) {
  const key = cleanText(streamId, "");
  if (!key) return null;
  const seekConfig = seek && typeof seek === "object" ? seek : { ratio: seek };
  const pending = {
    streamId: key,
    ratio: clamp(Number(seekConfig.ratio), 0, 1),
    mode: cleanText(mode, "live"),
    requestedAt: Number.isFinite(Number(nowMs)) ? Number(nowMs) : Date.now(),
  };
  ["targetTime", "visibleStart", "visibleEnd", "retentionStart", "retentionEnd", "playbackPosition"].forEach((keyName) => {
    const snakeName = keyName.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
    const value = Number(seekConfig[keyName] ?? seekConfig[snakeName]);
    if (Number.isFinite(value)) pending[keyName] = value;
  });
  return pending;
}

export function resolveWisCameraPendingTimelineSeek(pending = null, frames = [], mode = "live", timeline = null) {
  if (!pending || !Array.isArray(frames) || !frames.length) return null;
  const timelineMode = cleanText(mode, "live");
  if (pending.mode && pending.mode !== timelineMode) return null;
  const visibleStart = Number(pending.visibleStart ?? pending.visible_start);
  const visibleEnd = Number(pending.visibleEnd ?? pending.visible_end);
  const hasPendingVisibleWindow = Number.isFinite(visibleStart) && Number.isFinite(visibleEnd) && visibleEnd > visibleStart;
  const targetTime = Number(pending.targetTime ?? pending.target_time);
  if (Number.isFinite(targetTime)) {
    const frame = wisCameraTimelineFrameClosestToTime(frames, targetTime, { visibleStart, visibleEnd });
    if (frame) return frame;
  }
  const timelineContext = timeline && typeof timeline === "object" ? { ...timeline } : {};
  if (hasPendingVisibleWindow) {
    timelineContext.range = { start_ms: visibleStart, end_ms: visibleEnd };
  }
  const target = wisCameraTimelineTargetAtRatio(timelineContext, frames, pending.ratio);
  return target.snappedFrame || wisCameraTimelineFrameAtRatio(frames, pending.ratio);
}

export function shouldLoadWisCameraTimeline(timeline = {}, streamId = "", mode = "live", nowMs = Date.now(), ttlMs = 30000) {
  const key = cleanText(streamId, "");
  if (!key) return false;
  const timelineMode = cleanText(mode, "live");
  const loadedAt = Number(timeline?.loadedAt ?? timeline?.loaded_at ?? 0);
  const loadingStartedAt = Number(timeline?.loadingStartedAt ?? timeline?.loading_started_at ?? 0);
  const staleLoadingMs = Math.max(1000, Number(ttlMs || 0) || 30000);
  const loadingFresh = Boolean(
    timeline?.loading
    && loadingStartedAt > 0
    && Number(nowMs) - loadingStartedAt < staleLoadingMs
  );
  return !(
    timeline?.streamId === key
    && timeline?.mode === timelineMode
    && (loadingFresh || (loadedAt && Number(nowMs) - loadedAt < Number(ttlMs || 0)))
  );
}

export function wisCameraTimelineFrameLabel(frame = {}, locales = []) {
  const date = new Date(Number(frame?.timestamp_ms || 0));
  if (Number.isFinite(date.getTime())) {
    return date.toLocaleTimeString(locales, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }
  return cleanText(frame?.updated_at, "timeline point").replace("T", " ").replace("Z", "");
}

export function wisCameraRecordedSessionMatches(session = null, sessionId = "") {
  const cleanSessionId = cleanText(sessionId, "");
  return Boolean(cleanSessionId && cleanText(session?.id, "") === cleanSessionId && session?.mode === "recorded");
}

export function wisCameraRecordedTimelineTitle(session = null, currentMs = 0, locales = []) {
  if (!session || typeof session !== "object") return "";
  const timestampMs = Number(
    currentMs
      || session.currentWallTime
      || session.anchorRecordingTimeMs
      || session.recordedStartWallTime
      || session.recorded_start_wall_time
      || session.frame?.timestamp_ms
      || session.frame?.timestampMs
      || 0
  );
  const labelFrame = Number.isFinite(timestampMs) && timestampMs > 0
    ? { ...(session.frame || {}), timestamp_ms: timestampMs }
    : (session.frame || {});
  if (["seeking", "buffering", "loading"].includes(session.status)) return `Seeking recording: ${wisCameraTimelineFrameLabel(session.frame || labelFrame, locales)}`;
  if (session.status === "catching-up") return `Catching up recording: ${wisCameraTimelineFrameLabel(labelFrame, locales)}`;
  if (session.status === "rebuffering") return `Rebuffering recording from ${wisCameraTimelineFrameLabel(labelFrame, locales)}`;
	  if (session.status === "restarting") return `Restarting recording from ${wisCameraTimelineFrameLabel(labelFrame, locales)}`;
	  if (session.status === "stalled") return `Recording stalled near ${wisCameraTimelineFrameLabel(labelFrame, locales)}`;
	  if (session.status === "gap") return `No recording at ${wisCameraTimelineFrameLabel(labelFrame, locales)}`;
	  if (session.status === "ended") return `End of recording near ${wisCameraTimelineFrameLabel(labelFrame, locales)}`;
	  if (session.gapSuspected) return `Nearest recording: ${wisCameraTimelineFrameLabel(labelFrame, locales)}`;
  return `Viewing recording: ${wisCameraTimelineFrameLabel(labelFrame, locales)}`;
}

function appendBytes(left, right) {
  if (!left?.length) return right || new Uint8Array();
  if (!right?.length) return left;
  const merged = new Uint8Array(left.length + right.length);
  merged.set(left, 0);
  merged.set(right, left.length);
  return merged;
}

function indexOfBytes(buffer, needle, start = 0) {
  if (!buffer?.length || !needle?.length || needle.length > buffer.length) return -1;
  const last = buffer.length - needle.length;
  for (let index = Math.max(0, start); index <= last; index += 1) {
    let matched = true;
    for (let offset = 0; offset < needle.length; offset += 1) {
      if (buffer[index + offset] !== needle[offset]) {
        matched = false;
        break;
      }
    }
    if (matched) return index;
  }
  return -1;
}

function parseMjpegHeaders(text = "") {
  const headers = {};
  String(text || "").split(/\r?\n/).forEach((line) => {
    const index = line.indexOf(":");
    if (index <= 0) return;
    headers[line.slice(0, index).trim().toLowerCase()] = line.slice(index + 1).trim();
  });
  return headers;
}

export function wisCameraDisplayedFrameFromImage(image, fallbackFrame = null) {
  const visible = visibleWisCameraImage(image);
  const timestampMs = Number(visible?.dataset?.wisPlaybackFrameMs || image?.dataset?.wisPlaybackFrameMs || 0);
  const frameId = cleanText(visible?.dataset?.wisPlaybackFrameId || image?.dataset?.wisPlaybackFrameId, "");
  if (!Number.isFinite(timestampMs) || timestampMs <= 0) return fallbackFrame;
  return {
    ...(fallbackFrame || {}),
    id: frameId || cleanText(fallbackFrame?.id, ""),
    timestamp_ms: timestampMs,
  };
}

function wisCameraPlaybackFrameLabel(frame = {}, locales = []) {
  const timestampMs = wisCameraTimelinePlaybackStartMs(frame, timelineFrameTimestampMs(frame) || 0);
  const labelFrame = Number.isFinite(timestampMs) && timestampMs > 0
    ? { ...(frame || {}), timestamp_ms: timestampMs }
    : frame;
  return wisCameraTimelineFrameLabel(labelFrame, locales);
}

const WIS_CAMERA_PLAYBACK_HEALTHY_BEHIND_MS = 300;
const WIS_CAMERA_PLAYBACK_HEALTHY_AHEAD_MS = 150;
const WIS_CAMERA_PLAYBACK_MAX_LAG_MS = 600;
const WIS_CAMERA_PLAYBACK_MAX_FUTURE_WAIT_MS = 250;
const WIS_CAMERA_PLAYBACK_REBUFFER_MS = 2000;
const WIS_CAMERA_PLAYBACK_HARD_STALL_MS = 4000;
const WIS_CAMERA_PLAYBACK_DECODE_TIMEOUT_MS = 1200;
const WIS_CAMERA_PLAYBACK_HEALTH_SAMPLE_MS = 1000;
const WIS_CAMERA_PLAYBACK_HARD_CATCHUP_LAG_MS = 1500;
const WIS_CAMERA_PLAYBACK_NO_DISPLAY_REBUFFER_MS = 2000;
const WIS_CAMERA_PLAYBACK_RESTART_LIMIT = 2;
const WIS_CAMERA_PLAYBACK_STATUS_DEBOUNCE_MS = 650;

export const WIS_CAMERA_PLAYBACK_DRIFT_POLICY = Object.freeze({
  healthyBehindMs: WIS_CAMERA_PLAYBACK_HEALTHY_BEHIND_MS,
  healthyAheadMs: WIS_CAMERA_PLAYBACK_HEALTHY_AHEAD_MS,
  catchUpBehindMs: WIS_CAMERA_PLAYBACK_MAX_LAG_MS,
  hardCatchUpBehindMs: WIS_CAMERA_PLAYBACK_HARD_CATCHUP_LAG_MS,
  noDisplayRebufferMs: WIS_CAMERA_PLAYBACK_NO_DISPLAY_REBUFFER_MS,
  noPacketStallMs: WIS_CAMERA_PLAYBACK_HARD_STALL_MS,
  restartLimit: WIS_CAMERA_PLAYBACK_RESTART_LIMIT,
});

export function selectWisCameraPlaybackFrame(frameQueue = [], clockTimeMs = 0, options = {}) {
  if (!Array.isArray(frameQueue) || !frameQueue.length) {
    return { action: "empty", index: -1, dropCount: 0, waitMs: 0, status: "", driftMs: null, reason: "queue-empty" };
  }
  const clock = Number(clockTimeMs);
  const safeClock = Number.isFinite(clock) && clock > 0 ? clock : 0;
  const healthyBehindMs = Math.max(0, Number(options.healthyBehindMs ?? WIS_CAMERA_PLAYBACK_HEALTHY_BEHIND_MS));
  const healthyAheadMs = Math.max(0, Number(options.healthyAheadMs ?? WIS_CAMERA_PLAYBACK_HEALTHY_AHEAD_MS));
  const catchUpBehindMs = Math.max(healthyBehindMs, Number(options.catchUpBehindMs ?? WIS_CAMERA_PLAYBACK_MAX_LAG_MS));
  const hardCatchUpBehindMs = Math.max(catchUpBehindMs, Number(options.hardCatchUpBehindMs ?? WIS_CAMERA_PLAYBACK_HARD_CATCHUP_LAG_MS));
  const maxFutureWaitMs = Math.max(0, Number(options.maxFutureWaitMs ?? WIS_CAMERA_PLAYBACK_MAX_FUTURE_WAIT_MS));
  const targetFrameMs = Math.max(1, Number(options.targetFrameMs ?? 67));
  const frames = frameQueue
    .map((packet, index) => {
      const timestampMs = Number(packet?.timestampMs ?? packet?.timestamp_ms ?? 0);
      return {
        packet,
        index,
        timestampMs,
        driftMs: Number.isFinite(timestampMs) && timestampMs > 0 && safeClock > 0 ? timestampMs - safeClock : 0,
      };
    })
    .filter((item) => Number.isFinite(item.timestampMs) && item.timestampMs > 0);
  if (!frames.length) {
    return { action: "empty", index: -1, dropCount: frameQueue.length, waitMs: 0, status: "rebuffering", driftMs: null, reason: "timestamp-unusable" };
  }
  if (!safeClock) {
    return { action: "display", index: frames[0].index, dropCount: frames[0].index, waitMs: 0, status: "recordedPlaying", driftMs: frames[0].driftMs, reason: "clock-unavailable" };
  }
  const healthy = frames.filter((item) => item.driftMs >= -healthyBehindMs && item.driftMs <= healthyAheadMs);
  if (healthy.length) {
    const best = healthy.reduce((winner, item) => {
      const winnerDistance = Math.abs(winner.driftMs);
      const itemDistance = Math.abs(item.driftMs);
      if (itemDistance < winnerDistance) return item;
      if (itemDistance === winnerDistance && item.timestampMs > winner.timestampMs) return item;
      return winner;
    }, healthy[0]);
    return {
      action: "display",
      index: best.index,
      dropCount: best.index,
      waitMs: 0,
      status: "recordedPlaying",
      driftMs: best.driftMs,
      reason: "closest-healthy-frame",
    };
  }
  const eligible = frames.filter((item) => item.driftMs <= healthyAheadMs);
  if (eligible.length) {
    const best = eligible.reduce((winner, item) => (item.timestampMs > winner.timestampMs ? item : winner), eligible[0]);
    const behindMs = Math.max(0, -best.driftMs);
    return {
      action: "display",
      index: best.index,
      dropCount: best.index,
      waitMs: 0,
      status: behindMs > catchUpBehindMs ? "catching-up" : "recordedPlaying",
      driftMs: best.driftMs,
      reason: behindMs > hardCatchUpBehindMs ? "hard-catch-up" : (behindMs > catchUpBehindMs ? "catch-up" : "newest-eligible-frame"),
    };
  }
  const next = frames[0];
  const waitMs = Math.min(
    maxFutureWaitMs,
    Math.max(25, next.driftMs - healthyAheadMs, targetFrameMs)
  );
  return {
    action: "hold",
    index: next.index,
    dropCount: next.index,
    waitMs,
    status: "",
    driftMs: next.driftMs,
    reason: "future-frame",
  };
}

function playbackRestartUrl(url = "", targetTimeMs = 0, env = globalThis) {
  const rawUrl = cleanText(url, "");
  if (!rawUrl) return "";
  try {
    const base = env.location?.href || "http://localhost/";
    const parsed = new URL(rawUrl, base);
    parsed.searchParams.set("from_ms", String(Math.max(0, Math.round(Number(targetTimeMs) || 0))));
    parsed.searchParams.delete("frame");
    const isRelative = rawUrl.startsWith("/") || !/^[a-z][a-z0-9+.-]*:/i.test(rawUrl);
    return isRelative ? `${parsed.pathname}${parsed.search}${parsed.hash}` : parsed.toString();
  } catch {
    return rawUrl;
  }
}

function playbackRequestedSeekTimestampMs(url = "", baseFrame = null, env = globalThis) {
  try {
    const parsed = new URL(cleanText(url, ""), env.location?.href || "http://localhost/");
    const fromMs = Number(parsed.searchParams.get("from_ms") || parsed.searchParams.get("timestamp_ms") || parsed.searchParams.get("timestampMs"));
    if (Number.isFinite(fromMs) && fromMs > 0) return fromMs;
  } catch {
    // Fall through to the frame-derived target.
  }
  return wisCameraTimelinePlaybackStartMs(baseFrame, timelineFrameTimestampMs(baseFrame) || 0);
}

export function renderWisCameraPushArchiveFrame(runtimeState = {}, options = {}) {
  const env = options.env || globalThis;
  const documentRef = options.document || env.document || globalThis.document;
  const element = options.element || null;
  const streamId = cleanText(options.streamId, "");
  const slot = cleanText(options.slot, streamId || WIS_CAMERA_DEFAULT_SLOT);
  const camera = options.camera && typeof options.camera === "object" ? options.camera : {};
  const frame = options.frame || null;
  const forceSync = Boolean(options.force);
  const showCameraIssue = typeof options.showCameraIssue === "function" ? options.showCameraIssue : (() => {});
  const emitMediaEvent = (event, payload = {}, detail = {}) => {
    try {
      options.onMediaEvent?.(event, payload, detail);
    } catch {
      // Camera diagnostics are best effort.
    }
  };

	  if (!element || !streamId || !documentRef?.createElement) return null;
	  if (!frame?.id || !frame?.url) {
	    traceWisCameraBoundary("recorded.render.rejected", {
	      functionName: "renderWisCameraPushArchiveFrame",
	      streamId,
	      slot,
	      generation: Number(options.generation || 0),
	      reason: "frame-missing",
	      frameId: cleanText(frame?.id, ""),
	      frameUrl: cleanText(frame?.url, ""),
	      ownerState: wisCameraTimelineOwnerState(runtimeState, streamId),
	    });
	    showCameraIssue("No recording for this period.", "push-timeline-frame-missing");
	    return null;
	  }

  let session = wisCameraPlaybackState(runtimeState, streamId);
  if (!session?.mode || session.mode !== "recorded" || wisCameraTimelineFramePlaybackKey(session.frame) !== wisCameraTimelineFramePlaybackKey(frame)) {
    session = startWisCameraPlaybackSeek(runtimeState, streamId, frame, {
      explicitSeek: forceSync,
      restart: forceSync,
      generation: options.generation,
    });
  }
  if (!session) return null;
  const sessionId = cleanText(session?.id, "");
  const mediaOwner = options.mediaOwner || {
    kind: "recorded-playback",
    streamId,
    sessionId,
    generation: Number(session?.generation || 0),
  };
  const currentSession = () => wisCameraPlaybackState(runtimeState, streamId);
  const currentSessionMatches = () => wisCameraRecordedSessionMatches(wisCameraPlaybackState(runtimeState, streamId), sessionId);
  const playbackStatus = (status = "playing") => (status === "playing" ? "recordedPlaying" : status);
  const playbackController = () => (typeof options.playbackController === "function"
    ? options.playbackController()
    : options.playbackController);
  const notifyDisplayedFrame = (displayedSession, displayedFrame, detail = {}) => {
    if (detail.firstFrame) {
      markFirstRecordedFrameDisplayed(displayedFrame);
    } else {
      playbackController()?.markRecordedFrameDisplayed?.(displayedFrame, {
        source: detail.source || "media",
        reason: detail.reason || "recorded-frame-displayed",
        generation: Number(displayedSession?.generation || session?.generation || 0),
        syncTimeline: detail.syncTimeline,
      });
    }
    options.onFrameDisplayed?.(displayedSession, displayedFrame, detail);
  };
  const syncDisplayedFrame = (displayedFrame, nextStatus = "playing", syncOptions = {}) => {
    if (!currentSessionMatches()) return null;
    const status = playbackStatus(nextStatus);
    const keepPaused = Boolean(syncOptions.paused ?? currentSession()?.userPaused);
    const displayedSession = setWisCameraPlaybackFrame(runtimeState, streamId, displayedFrame, {
      sessionId,
      generation: session?.generation,
      status: keepPaused ? "paused" : status,
      state: keepPaused ? "paused" : status,
      paused: keepPaused,
      updateClockAnchor: syncOptions.updateClockAnchor !== false,
    });
    if (displayedSession) {
      notifyDisplayedFrame(displayedSession, displayedFrame, {
        source: syncOptions.source || "media",
        reason: syncOptions.reason || "recorded-frame-displayed",
        syncTimeline: syncOptions.syncTimeline,
      });
    }
    return displayedSession;
  };

  const previousMedia = Array.from(element.querySelectorAll?.(".wis-camera-image, .wis-camera-video") || []);
  const reusableImage = previousMedia.find((media) => media?.tagName === "IMG" && media.dataset?.wisBufferRole === "front" && media.isConnected !== false)
    || previousMedia.find((media) => media?.tagName === "IMG" && media.dataset?.wisBufferRole !== "back" && media.isConnected !== false)
    || previousMedia.find((media) => media?.tagName === "IMG" && media.isConnected !== false)
    || null;
  const activeLoop = wisCameraActivePlaybackLoop(runtimeState, streamId);
  const sameActiveLoop = activeLoop
    && !activeLoop.disposed
    && activeLoop.sessionId === sessionId
    && Number(activeLoop.generation || 0) === Number(session?.generation || 0);
  if (sameActiveLoop && reusableImage && element.dataset?.wisRecordedSessionId === sessionId) {
    emitMediaEvent("camera.media.playback_stream.duplicate_ignored", {
      reason: "same-session-render",
      sessionId,
      queueLength: Number(session?.playbackQueueLength || 0),
      activeReaders: activeLoop.readerActive ? 1 : 0,
    }, { sampleMs: 1000 });
    sampleWisCameraPerf(runtimeState, streamId, {
      generation: Number(session?.generation || 0),
      queueLength: Number(session?.playbackQueueLength || 0),
    }, emitMediaEvent);
    return {
      image: reusableImage,
      status: element.querySelector?.(".wis-camera-sync-status") || null,
      session,
      mediaOwner,
      startPlaybackStream: () => {},
      displayArchiveFrame: async () => false,
      duplicate: true,
    };
  }
  const frozenFrame = reusableImage ? null : wisCameraLastGoodFrame(runtimeState, streamId);
  previousMedia.forEach((media) => {
    rememberWisCameraLastGoodFrameFromImage(runtimeState, streamId, media, frame, {
      ownerKind: media?.dataset?.wisMediaOwner,
      sessionId,
      generation: mediaOwner.generation,
    });
    if (media?.dataset) {
      media.dataset.wisMediaPlaceholder = "stale";
      media.dataset.wisMediaPlaceholderForGeneration = String(mediaOwner.generation);
    }
    media?.classList?.add?.("is-placeholder");
    if (media?.tagName === "IMG" && media !== reusableImage) claimMediaWriter(media, mediaOwner);
  });
  element.querySelectorAll?.(".wis-camera-message, .wis-camera-fallback")?.forEach((node) => node.remove?.());

  let image = reusableImage || documentRef.createElement("img");
  if (!reusableImage) noteWisCameraPerf(runtimeState, streamId, "domReplacements");
  let frozenPlaceholderSrc = reusableImage ? mediaElementRenderedSrc(reusableImage) : cleanText(frozenFrame?.src, "");
  image.className = "wis-camera-image wis-camera-stream wis-camera-push is-timeline-frame";
  image.alt = `${camera.label || slot} playback from ${wisCameraPlaybackFrameLabel(frame, options.locales)}`;
  image.decoding = "async";
  image.loading = "eager";
  image.fetchPriority = "high";
  if (!image.dataset) image.dataset = {};
  image.dataset.wisRecordedSessionId = sessionId;
  if (sessionId && element.dataset) element.dataset.wisRecordedSessionId = sessionId;
  if (!claimMediaWriter(image, mediaOwner)) {
    emitMediaEvent("camera.media.stale_writer.ignored", {
      reason: "recorded-owner-claim-rejected",
      sessionId,
      frameTimestampMs: wisCameraTimelinePlaybackStartMs(frame, timelineFrameTimestampMs(frame)),
    }, { sampleMs: 1000 });
    return null;
  }
  const imageBuffer = ensureWisCameraImageBuffer(element, image, mediaOwner, { document: documentRef });
  image = imageBuffer?.front || image;
  const bufferMedia = new Set([image, imageBuffer?.back].filter(Boolean));
  const keepPreviousUntilReady = previousMedia.some((media) => !bufferMedia.has(media));
  if (!reusableImage && frozenPlaceholderSrc) {
    noteWisCameraPerf(runtimeState, streamId, "srcChanges");
    image.src = frozenPlaceholderSrc;
    image.dataset.wisLastGoodSrc = frozenPlaceholderSrc;
    image.dataset.wisPlaybackStream = cleanText(frozenFrame?.playbackStream, "");
    image.dataset.wisPlaybackFrameMs = cleanText(frozenFrame?.timestampMs, "");
    image.dataset.wisPlaybackFrameId = cleanText(frozenFrame?.frameId, "");
    image.dataset.wisMediaPlaceholder = "frozen";
    image.dataset.wisMediaPlaceholderForGeneration = String(mediaOwner.generation);
  }

  const status = documentRef.createElement("span");
  status.className = "wis-camera-message warn wis-camera-sync-status";
  status.textContent = `Seeking recording: ${wisCameraPlaybackFrameLabel(frame, options.locales)}`;
  element.classList?.add?.("has-camera");
  element.append?.(...Array.from(bufferMedia), status);

  const archiveFrameUrl = cleanText(options.archiveFrameUrl || frame.url, "");
  const framePlaybackStartMs = wisCameraTimelinePlaybackStartMs(frame, timelineFrameTimestampMs(frame));
  const playbackUrl = cleanText(options.playbackUrl || archiveFrameUrl, "");
  let imageLoaded = false;
  let playbackStarted = false;
  let playbackFallbackActive = false;
  let streamFrameDisplayed = false;
  let firstFramePatchSent = false;
  let assumedPlayingTimer = 0;
  let revealTimer = 0;

  const reveal = () => {
    if (!imageLoaded) return;
    const visibleImage = visibleWisCameraImage(image);
    delete visibleImage?.dataset?.wisMediaPlaceholder;
    delete visibleImage?.dataset?.wisMediaPlaceholderForGeneration;
    delete image.dataset.wisMediaPlaceholder;
    delete image.dataset.wisMediaPlaceholderForGeneration;
    previousMedia.forEach((media) => {
      if (!bufferMedia.has(media) && media.isConnected) {
        noteWisCameraPerf(runtimeState, streamId, "domReplacements");
        media.remove?.();
      }
    });
    rememberWisCameraLastGoodFrameFromImage(runtimeState, streamId, visibleImage || image, frame, {
      ownerKind: mediaOwner.kind,
      sessionId,
      generation: mediaOwner.generation,
    });
  };
  if (keepPreviousUntilReady && typeof env.setTimeout === "function") {
    revealTimer = env.setTimeout(() => {
      if (currentSessionMatches()) reveal();
    }, 550);
  }

  const markFirstRecordedFrameDisplayed = (displayedFrame) => {
    if (firstFramePatchSent) return;
    firstFramePatchSent = true;
    playbackController()?.markFirstRecordedFrameDisplayed?.(displayedFrame, {
      source: forceSync ? "user" : "restore",
      reason: forceSync ? "timeline-seek-first-frame" : "recorded-restore-first-frame",
      firstFrameTimeMs: wisCameraTimelinePlaybackStartMs(displayedFrame, timelineFrameTimestampMs(displayedFrame) || Date.now()),
      segmentId: cleanText(frame.id, ""),
      syncTimeline: false,
    });
  };

  const displayArchiveFrame = async (reason = "first-frame", displayOptions = {}) => {
    if (!image.isConnected || !currentSessionMatches() || !isMediaWriterCurrent(image, mediaOwner)) return false;
    if (displayOptions.onlyBeforeFirstFrame && (streamFrameDisplayed || currentSession()?.firstRecordedFrameDisplayed)) return false;
    const visibleImage = visibleWisCameraImage(image);
    if (
      Math.round(Number(visibleImage?.dataset?.wisPlaybackFrameMs || 0)) === Math.round(framePlaybackStartMs)
      && mediaElementRenderedSrc(visibleImage)
      && !visibleImage?.dataset?.wisMediaPlaceholder
    ) {
      noteWisCameraPerf(runtimeState, streamId, "duplicateFrameSkips");
      return true;
    }
    emitMediaEvent("camera.media.first_frame.fetch.start", {
      streamId,
      generation: Number(session?.generation || 0),
      ownerKind: mediaOwner.kind,
      imageOwner: image.dataset?.wisMediaOwner,
      frameTimestampMs: framePlaybackStartMs,
        reason,
      });
	    image.dataset.wisPendingPlaybackStream = "";
	    image.dataset.wisPendingPlaybackFrameMs = String(framePlaybackStartMs);
	    image.dataset.wisPendingPlaybackFrameId = cleanText(frame.id, "");
	    traceWisCameraBoundary("archive.fetch.started", {
	      functionName: "displayArchiveFrame",
	      streamId,
	      generation: Number(session?.generation || 0),
	      ownerKind: mediaOwner.kind,
	      frameTimestampMs: framePlaybackStartMs,
	      archiveFrameUrl,
	      reason,
	      domLayer: visibleImage?.dataset?.wisBufferRole || image.dataset?.wisBufferRole || "",
	    });
	    try {
	      const swapped = await decodeAndSwapImage(image, archiveFrameUrl, mediaOwner, {
        env,
        document: documentRef,
        element,
        streamId,
        mode: "recorded",
        generation: Number(session?.generation || 0),
        onVisualBlink: (payload) => emitMediaEvent("camera.visual.blink_detected", payload, { always: true }),
        isCurrent: () => !displayOptions.onlyBeforeFirstFrame || (!streamFrameDisplayed && !currentSession()?.firstRecordedFrameDisplayed),
        onStale: () => emitMediaEvent("camera.media.stale_writer.ignored", {
          streamId,
          generation: Number(session?.generation || 0),
          ownerKind: mediaOwner.kind,
          imageOwner: image.dataset?.wisMediaOwner,
          frameTimestampMs: framePlaybackStartMs,
          reason,
        }, { sampleMs: 1000 }),
        beforeSwap: (targetImage = image) => {
          frozenPlaceholderSrc = "";
          targetImage.dataset.wisPlaybackStream = "";
          targetImage.dataset.wisPlaybackFrameMs = String(framePlaybackStartMs);
          targetImage.dataset.wisPlaybackFrameId = cleanText(frame.id, "");
          targetImage.dataset.wisMediaPlaceholder = "decoding";
          targetImage.dataset.wisMediaPlaceholderForGeneration = String(mediaOwner.generation);
        },
        onSwap: (visibleTarget = visibleWisCameraImage(image)) => emitMediaEvent("camera.media.src.swap", {
          streamId,
          generation: Number(session?.generation || 0),
          ownerKind: mediaOwner.kind,
          imageOwner: visibleTarget?.dataset?.wisMediaOwner,
          frameTimestampMs: framePlaybackStartMs,
          reason,
        }),
      });
      if (swapped) noteWisCameraPerf(runtimeState, streamId, "srcChanges");
      if (!swapped || !currentSessionMatches()) {
        emitMediaEvent("camera.visual.frame_commit", {
          mode: "recorded",
          decodedOk: false,
          frameTimestampMs: framePlaybackStartMs,
          visibleLayerOwner: visibleWisCameraImage(image)?.dataset?.wisMediaOwner || image.dataset?.wisMediaOwner,
          reason,
        });
        return false;
      }
      if (displayOptions.onlyBeforeFirstFrame && streamFrameDisplayed) return false;
      imageLoaded = true;
      const displayedFrame = wisCameraDisplayedFrameFromImage(image, frame);
      syncDisplayedFrame(displayedFrame, "playing", {
        updateClockAnchor: displayOptions.updateClockAnchor !== false,
        source: forceSync ? "user" : "restore",
        reason,
      });
      rememberWisCameraLastGoodFrameFromImage(runtimeState, streamId, image, displayedFrame, {
        ownerKind: mediaOwner.kind,
        sessionId,
        generation: mediaOwner.generation,
      });
      markFirstRecordedFrameDisplayed(displayedFrame);
      emitMediaEvent("camera.media.first_frame.displayed", {
        streamId,
        generation: Number(session?.generation || 0),
        ownerKind: mediaOwner.kind,
        imageOwner: image.dataset?.wisMediaOwner,
        frameTimestampMs: wisCameraTimelinePlaybackStartMs(displayedFrame, timelineFrameTimestampMs(displayedFrame) || 0),
        reason,
      });
      emitMediaEvent("camera.visual.frame_commit", {
        mode: "recorded",
        decodedOk: true,
        frameTimestampMs: wisCameraTimelinePlaybackStartMs(displayedFrame, timelineFrameTimestampMs(displayedFrame) || 0),
        visibleLayerOwner: visibleWisCameraImage(image)?.dataset?.wisMediaOwner || image.dataset?.wisMediaOwner,
        reason,
      });
      if (revealTimer) env.clearTimeout?.(revealTimer);
      if (assumedPlayingTimer) env.clearTimeout?.(assumedPlayingTimer);
      reveal();
      options.syncAspect?.(element, visibleWisCameraImage(image));
      status.remove?.();
      options.applyZoom?.(element, streamId, visibleWisCameraImage(image));
      return true;
    } catch (error) {
      emitMediaEvent("camera.media.first_frame.error", {
        streamId,
        generation: Number(session?.generation || 0),
        ownerKind: mediaOwner.kind,
        imageOwner: image.dataset?.wisMediaOwner,
        reason,
        error: error?.message || String(error),
      });
      return false;
    }
  };

	  const fallbackToImageSrc = () => {
	    if (!image.isConnected || !currentSessionMatches() || !isMediaWriterCurrent(image, mediaOwner)) return;
	    playbackFallbackActive = true;
	    traceWisCameraBoundary("recorded.fallback.still_frame", {
	      functionName: "fallbackToImageSrc",
	      streamId,
	      generation: Number(session?.generation || 0),
	      sessionId,
	      frameTimestampMs: framePlaybackStartMs,
	      reason: "playback-stream-fallback",
	      ownerKind: mediaOwner.kind,
	    });
	    void displayArchiveFrame("playback-stream-fallback", { updateClockAnchor: false });
	  };
  const startPlaybackStream = (reason = "start") => {
    if (playbackStarted || !currentSessionMatches()) return;
    const budget = wisCameraPerformanceBudget(runtimeState, streamId, {
      env,
      mode: "recorded",
    });
    if (!budget.allowNetworkWork) {
      scheduleWisCameraVisualTask(runtimeState, streamId, "playback-start", startPlaybackStream, budget.retryMs, env, `${budget.tier}-playback-start-deferred`);
      sampleWisCameraPerf(runtimeState, streamId, {
        generation: Number(session?.generation || 0),
        performanceTier: budget.tier,
        visualSuspended: true,
        reason,
      }, emitMediaEvent);
      return;
    }
    cancelWisCameraVisualTask(runtimeState, streamId, "playback-start");
    playbackStarted = true;
    void streamWisCameraPushPlaybackFrames(runtimeState, {
      streamId,
      image,
      playbackUrl,
      baseFrame: frame,
      sessionId,
      generation: session?.generation,
      mediaOwner,
      env,
      playbackController: options.playbackController,
      fallbackToImageSrc,
      onFrameDisplayed: (displayedSession, displayedFrame) => {
        streamFrameDisplayed = true;
        imageLoaded = true;
        if (revealTimer) env.clearTimeout?.(revealTimer);
        if (assumedPlayingTimer) env.clearTimeout?.(assumedPlayingTimer);
        reveal();
        status.remove?.();
        notifyDisplayedFrame(displayedSession, displayedFrame, {
          source: "media",
          reason: "playback-frame-displayed",
          firstFrame: !firstFramePatchSent,
        });
      },
      onEnded: (...args) => options.onEnded?.(...args),
      onError: (...args) => options.onError?.(...args),
      onMediaEvent: (event, payload = {}) => emitMediaEvent(event, payload, {
        sampleMs: event.includes(".sample") ? 1000 : 0,
      }),
    });
  };
  const startPlaybackStreamAfterPaint = async () => {
    startPlaybackStream("after-paint");
  };

  if (typeof env.setTimeout === "function") {
    assumedPlayingTimer = env.setTimeout(() => {
      if (!currentSessionMatches()) {
        status.remove?.();
        return;
      }
    if (!imageLoaded || !playbackFallbackActive) return;
      const displayedFrame = wisCameraDisplayedFrameFromImage(image, frame);
      syncDisplayedFrame(displayedFrame, "playing", {
        updateClockAnchor: !firstFramePatchSent,
        source: "media",
        reason: "assumed-playing-fallback",
      });
      reveal();
      status.remove?.();
    }, keepPreviousUntilReady ? 2200 : 1800);
  }

  image.addEventListener?.("load", () => {
    noteWisCameraPerf(runtimeState, streamId, "imageLoads");
    if (frozenPlaceholderSrc && mediaElementRenderedSrc(image) === frozenPlaceholderSrc) {
      return;
    }
    if (!currentSessionMatches()) {
      if (revealTimer) env.clearTimeout?.(revealTimer);
      if (assumedPlayingTimer) env.clearTimeout?.(assumedPlayingTimer);
      status.remove?.();
      return;
    }
    imageLoaded = true;
    const isStreamFrame = image.dataset?.wisPlaybackStream === "1";
    if (isStreamFrame) streamFrameDisplayed = true;
    if (!isStreamFrame && playbackFallbackActive) {
      const displayedFrame = wisCameraDisplayedFrameFromImage(image, frame);
      syncDisplayedFrame(displayedFrame, "playing", {
        updateClockAnchor: !firstFramePatchSent,
        source: "media",
        reason: "fallback-image-load",
      });
    }
    if (revealTimer) env.clearTimeout?.(revealTimer);
    if (isStreamFrame || playbackFallbackActive) env.clearTimeout?.(assumedPlayingTimer);
    reveal();
    options.syncAspect?.(element, visibleWisCameraImage(image));
    if (isStreamFrame || playbackFallbackActive) status.remove?.();
    options.applyZoom?.(element, streamId, visibleWisCameraImage(image));
  });
  image.addEventListener?.("error", () => {
    noteWisCameraPerf(runtimeState, streamId, "imageErrors");
    if (frozenPlaceholderSrc && mediaElementRenderedSrc(image) === frozenPlaceholderSrc) {
      return;
    }
    if (revealTimer) env.clearTimeout?.(revealTimer);
    if (assumedPlayingTimer) env.clearTimeout?.(assumedPlayingTimer);
    if (!currentSessionMatches()) {
      status.remove?.();
      return;
    }
    options.onMissingFrame?.(streamId, frame);
    if (session) {
      setWisCameraPlaybackFrame(runtimeState, streamId, frame, {
        sessionId,
        generation: session.generation,
        status: "gap",
        state: "error",
        paused: true,
      });
    }
    if (previousMedia.some((media) => media.isConnected)) {
      image.remove?.();
      status.textContent = "No recording for this period.";
      element.classList?.add?.("has-camera");
      return;
    }
    showCameraIssue("No recording for this period.", "push-timeline-frame-error");
  }, { once: true });
  setWisCameraPerfActive(runtimeState, streamId, { listeners: 2 });

  image.dataset.wisPendingPlaybackStream = "";
  image.dataset.wisPendingPlaybackFrameMs = String(framePlaybackStartMs);
  image.dataset.wisPendingPlaybackFrameId = cleanText(frame.id, "");
  image.dataset.wisMediaPlaceholder = "pending";
  image.dataset.wisMediaPlaceholderForGeneration = String(mediaOwner.generation);
  if (typeof env.requestAnimationFrame === "function") {
    env.requestAnimationFrame(startPlaybackStreamAfterPaint);
  } else if (typeof env.setTimeout === "function") {
    env.setTimeout(startPlaybackStreamAfterPaint, 0);
  }

  return {
    image,
    status,
    session,
    mediaOwner,
    startPlaybackStream,
    displayArchiveFrame,
  };
}

export async function streamWisCameraPushPlaybackFrames(runtimeState = {}, options = {}) {
  const key = cleanText(options.streamId, "");
  const image = options.image || null;
  const playbackUrl = cleanText(options.playbackUrl, "");
  const baseFrame = options.baseFrame || null;
  const token = {
    sessionId: options.sessionId,
    generation: options.generation,
  };
  const env = options.env || globalThis;
	  if (!key || !image || !playbackUrl || typeof env.fetch !== "function" || typeof env.AbortController !== "function") {
	    traceWisCameraBoundary("archive.fetch.result", {
	      functionName: "streamWisCameraPushPlaybackFrames",
	      streamId: key,
	      generation: Number(token.generation || 0),
	      playbackUrl,
	      fetchResult: "empty",
	      reason: "playback-stream-ineligible",
	      hasImage: Boolean(image),
	      hasFetch: typeof env.fetch === "function",
	      hasAbortController: typeof env.AbortController === "function",
	    });
	    options.fallbackToImageSrc?.();
	    return;
	  }
  if (!wisCameraPlaybackMatches(runtimeState, key, token)) return;
  const mediaOwner = options.mediaOwner || {
    kind: "recorded-playback",
    streamId: key,
    sessionId: cleanText(options.sessionId, ""),
    generation: Number(options.generation || 0),
  };
  const lastMediaLogAt = new Map();
  const emitMediaEvent = (event, data = {}, detail = {}) => {
    const now = wisCameraMonotonicNow();
    const sampleMs = Number(detail.sampleMs || 0);
    if (sampleMs > 0) {
      const lastAt = Number(lastMediaLogAt.get(event) || 0);
      if (lastAt > 0 && now - lastAt < sampleMs) return;
      lastMediaLogAt.set(event, now);
    }
    const payload = {
      streamId: key,
      generation: Number(token.generation || 0),
      ownerKind: mediaOwner.kind,
      imageOwner: image?.dataset?.wisMediaOwner,
      ...data,
    };
    try {
      options.onMediaEvent?.(event, payload, detail);
      options.recordEvent?.(event, payload);
    } catch {
      // Diagnostics should never affect playback.
    }
    if (CAMERA_DEBUG && options.diagnostics !== false) {
      try {
        const method = event.includes("error") || event.includes("stale") ? "warn" : "debug";
        if (!options.onMediaEvent) env.console?.[method]?.("[camera]", event, payload);
      } catch {
        // Console diagnostics are optional.
      }
    }
  };
  if (!claimMediaWriter(image, mediaOwner)) {
    emitMediaEvent("camera.media.stale_writer.ignored", {
      reason: "recorded-owner-claim-rejected",
    });
    return;
  }
  emitMediaEvent("camera.media.owner.claim", {
    sessionId: mediaOwner.sessionId,
  });
  setWisCameraPlaybackBuffering(runtimeState, key, token);
  let fellBackToImageSrc = false;
  let playbackFps = 15;
  try {
    playbackFps = clamp(Number(new URL(playbackUrl, env.location?.href || "http://localhost/").searchParams.get("fps") || 15), 1, 15);
  } catch {
    playbackFps = 15;
  }
  const sourceFrameMs = 1000 / playbackFps;
  const playbackBudget = () => wisCameraPerformanceBudget(runtimeState, key, {
    env,
    mode: "recorded",
    requestedFps: playbackFps,
  });
  const playbackVisualFrameMs = () => Math.max(sourceFrameMs, Number(playbackBudget().visualMinIntervalMs || sourceFrameMs));
  const playbackRetryMs = () => Math.max(250, Number(playbackBudget().retryMs || playbackVisualFrameMs()));
  const maxBufferFramesForBudget = () => {
    const budget = playbackBudget();
    if (!budget.allowVisualWork) return 1;
    return Math.max(2, Math.min(12, Math.round((budget.visualFps || playbackFps) * 2)));
  };
  const requestedSeekTimestampMs = playbackRequestedSeekTimestampMs(playbackUrl, baseFrame, env);
  const requestedSession = wisCameraPlaybackState(runtimeState, key);
  if (requestedSession) {
    requestedSession.requestedSeekTimestampMs = requestedSeekTimestampMs;
    requestedSession.updatedAt = Date.now();
  }
  emitMediaEvent("camera.server.seek.requested", {
    requestedSeekTimestampMs,
    playbackUrl,
    playbackFps,
  });
  const frameQueue = [];
  let displayTimer = 0;
  let displayTimerStartedAtMs = 0;
  let displayInProgress = false;
  let displayStartedAtMs = 0;
  let activeDisplayAttemptSeq = 0;
  let streamEnded = false;
  let displaySeq = 0;
  let healthTimer = 0;
  let disposed = false;
  let activeController = null;
	  let activeReaderSeq = 0;
	  let readerActive = false;
	  let readerStartedAtMs = 0;
	  let activeReaderAbortCounted = false;
  let currentPlaybackUrl = playbackUrl;
  let restartRequestedUrl = "";
  let restartRequestedReason = "";
  let restartCount = Number(wisCameraPlaybackState(runtimeState, key)?.playbackRestartCount || 0);
  let firstFrameReceived = false;
  let firstFrameTimestampMs = 0;
  let firstFrameArrivalLatencyMs = 0;
  let lastPacketTimestampMs = 0;
  let lastRawPacketTimestampMs = 0;
  let lastPacketArrivalMs = 0;
  let lastPacketIntervalMs = 0;
  let lastPacketTimestampIntervalMs = 0;
  let lastPacketSeq = 0;
  let lastDisplayedPacketSeq = 0;
  let lastDisplayedMonotonicMs = 0;
  let lastSchedulerRunMs = 0;
  let lastVisualSelectionAtMs = 0;
  const activeDisplayObjectUrls = new Map();
  const loopKey = `${cleanText(token.sessionId, "")}|${Number(token.generation || 0)}`;
  const loops = playbackLoopMap(runtimeState);
  const existingLoop = loops.get(key);
  if (existingLoop && !existingLoop.disposed && existingLoop.loopKey === loopKey) {
    emitMediaEvent("camera.media.playback_stream.duplicate_ignored", {
      reason: "same-generation-loop-active",
      sessionId: token.sessionId,
      activeReaders: existingLoop.readerActive ? 1 : 0,
      activeTimers: existingLoop.displayTimerActive || existingLoop.healthTimerActive ? 1 : 0,
    }, { sampleMs: 1000 });
    sampleWisCameraPerf(runtimeState, key, {
      generation: Number(token.generation || 0),
      queueLength: Number(wisCameraPlaybackState(runtimeState, key)?.playbackQueueLength || 0),
    }, emitMediaEvent, { force: true });
    return;
  }
  if (existingLoop && !existingLoop.disposed) {
    try {
      existingLoop.abort?.("replaced-by-new-generation");
    } catch {
      // Previous playback loop cleanup is best-effort.
    }
  }
  const loopRecord = {
    loopKey,
    streamId: key,
    sessionId: cleanText(token.sessionId, ""),
    generation: Number(token.generation || 0),
    startedAt: Date.now(),
	    disposed: false,
	    readerActive: false,
	    displayTimerActive: false,
	    healthTimerActive: false,
	    playbackReaderCreatedCount: 0,
	    playbackReaderDoneCount: 0,
	    playbackReaderAbortCount: 0,
	    playbackReaderErrorCount: 0,
	    playbackChunksReceived: 0,
	    playbackFramesParsed: 0,
	    playbackFramesCommitted: 0,
	    playbackReaderLastDoneReason: "",
	    playbackReaderLifetimeMs: 0,
	    abort: null,
    resume: null,
    schedule: null,
  };
  loops.set(key, loopRecord);
  setWisCameraPerfActive(runtimeState, key, { playbackLoops: 1, readers: 0, timers: 0, intervals: 0, schedulerTasks: 0, pendingDecodes: 0, objectUrls: 0 });
  const isCurrent = () => (
    !disposed
    && image.isConnected !== false
    && wisCameraPlaybackMatches(runtimeState, key, token)
    && isMediaWriterCurrent(image, mediaOwner)
  );
	  const currentSession = () => wisCameraPlaybackState(runtimeState, key);
	  const isPlaybackPaused = () => Boolean(currentSession()?.userPaused || cleanText(currentSession()?.status, "") === "paused");
	  const currentClockMs = (nowMs = wisCameraMonotonicNow()) => wisCameraPlaybackClockMs(currentSession(), nowMs);
	  const updatePlaybackReaderStats = (updates = {}) => {
	    const session = currentSession();
	    if (!session || !wisCameraPlaybackMatches(runtimeState, key, token)) return null;
	    Object.entries(updates).forEach(([field, value]) => {
	      if (field === "playbackReaderLifetimeMs") {
	        session[field] = Math.max(0, Math.round(Number(value) || 0));
	      } else if (typeof value === "number") {
	        session[field] = Math.max(0, Math.round(Number(session[field] || 0) + value));
	      } else {
	        session[field] = value;
	      }
	    });
	    session.updatedAt = Date.now();
	    return session;
	  };
	  const notePlaybackReaderAbort = (reason = "abort") => {
	    if (activeReaderAbortCounted) return;
	    activeReaderAbortCounted = true;
	    loopRecord.playbackReaderAbortCount += 1;
	    loopRecord.playbackReaderLastDoneReason = cleanText(reason, "abort");
	    updatePlaybackReaderStats({
	      playbackReaderAbortCount: 1,
	      playbackReaderLastDoneReason: loopRecord.playbackReaderLastDoneReason,
	    });
	    traceWisCameraBoundary("camera.media.playback_reader.abort", {
	      functionName: "runPlaybackReader",
	      streamId: key,
	      generation: Number(token.generation || 0),
	      sessionId: cleanText(token.sessionId, ""),
	      reason: loopRecord.playbackReaderLastDoneReason,
	      readerSeq: activeReaderSeq,
	      playbackReaderAbortCount: loopRecord.playbackReaderAbortCount,
	    });
	  };
	  const syncLoopPerfActive = () => {
    setWisCameraPerfActive(runtimeState, key, {
      timers: 0,
      intervals: 0,
      schedulerTasks: (loopRecord.displayTimerActive ? 1 : 0) + (loopRecord.healthTimerActive ? 1 : 0),
      readers: loopRecord.readerActive ? 1 : 0,
      playbackLoops: loopRecord.disposed ? 0 : 1,
      pendingDecodes: displayInProgress ? 1 : 0,
      objectUrls: activeDisplayObjectUrls.size + (playbackObjectUrlMap(runtimeState).get(key) ? 1 : 0),
    });
  };
  const displayedPacketStatus = (status = "", fallback = "recordedPlaying") => {
    const nextStatus = cleanText(status, fallback);
    return ["seeking", "buffering", "loading"].includes(nextStatus)
      ? cleanText(fallback, "recordedPlaying")
      : nextStatus;
  };
  const clearDisplayTimer = () => {
    if (!displayTimer) return;
    try {
      cancelWisCameraVisualTask(runtimeState, key, "playback-display");
    } catch {
      // Timer may belong to another runtime.
    }
    if (playbackTimerMap(runtimeState).get(key) === displayTimer) playbackTimerMap(runtimeState).delete(key);
    displayTimer = 0;
    displayTimerStartedAtMs = 0;
    loopRecord.displayTimerActive = false;
    syncLoopPerfActive();
  };
  const clearHealthTimer = () => {
    if (!healthTimer) return;
    try {
      cancelWisCameraVisualTask(runtimeState, key, "playback-health");
    } catch {
      // Timer may belong to another runtime.
    }
    healthTimer = 0;
    loopRecord.healthTimerActive = false;
    syncLoopPerfActive();
  };
  const cleanupPlaybackController = (endSession = false) => {
    if (disposed) return;
    disposed = true;
    loopRecord.disposed = true;
    clearDisplayTimer();
    clearHealthTimer();
	    if (readerActive && activeController && !activeController.signal?.aborted) {
	      try {
	        activeController.abort();
	      } catch {
	        // Reader may already be closed.
	      }
	    }
    if (playbackControllerMap(runtimeState).get(key) === activeController) playbackControllerMap(runtimeState).delete(key);
    if (playbackLoopMap(runtimeState).get(key) === loopRecord) playbackLoopMap(runtimeState).delete(key);
    syncLoopPerfActive();
    setWisCameraPerfActive(runtimeState, key, { listeners: 0, pendingDecodes: 0, schedulerTasks: 0, objectUrls: 0 });
    if (endSession && !fellBackToImageSrc) {
      const session = setWisCameraPlaybackEnded(runtimeState, key, token);
      if (session) options.onEnded?.(session);
    }
  };
	  loopRecord.abort = (reason = "abort") => {
	    if (disposed) return;
	    notePlaybackReaderAbort(reason);
	    emitMediaEvent("camera.media.playback_stream.abort", { reason }, { sampleMs: 1000 });
    try {
      activeController?.abort?.();
    } catch {
      // Reader may already be closed.
    }
    cleanupPlaybackController(false);
  };
  loopRecord.resume = (reason = "resume") => {
    if (disposed || !isCurrent()) return false;
    frameQueue.length = 0;
    const restarted = requestPlaybackRestart(reason);
    schedulePlaybackFrame(reason);
    return restarted;
  };
  const markPlaybackStatus = (status = "recordedPlaying", reason = "") => {
    const session = currentSession();
    if (!session || !wisCameraPlaybackMatches(runtimeState, key, token)) return null;
    const nowMs = wisCameraMonotonicNow();
    const previousStatus = cleanText(session.status, "");
    if (status === "recordedPlaying") {
      session.pendingPlaybackStatus = "";
      session.pendingPlaybackStatusSinceMonotonic = 0;
    }
    if (previousStatus === status) return session;
    if (previousStatus !== status && ["catching-up", "rebuffering"].includes(status)) {
      if (session.pendingPlaybackStatus !== status) {
        session.pendingPlaybackStatus = status;
        session.pendingPlaybackStatusSinceMonotonic = nowMs;
        session.updatedAt = Date.now();
        return session;
      }
      if (nowMs - Number(session.pendingPlaybackStatusSinceMonotonic || nowMs) < WIS_CAMERA_PLAYBACK_STATUS_DEBOUNCE_MS) {
        return session;
      }
    }
    if (previousStatus !== status) {
      session.pendingPlaybackStatus = "";
      session.pendingPlaybackStatusSinceMonotonic = 0;
    }
    session.currentWallTime = wisCameraPlaybackClockMs(session, nowMs) || session.currentWallTime;
    session.state = status;
    session.status = status;
    session.clockPaused = ["gap", "stalled", "ended", "paused"].includes(status);
    session.ownerState = session.clockPaused
      ? WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PAUSED
      : WIS_CAMERA_TIMELINE_OWNER_STATES.RECORDED_PLAYING;
    session.timelineOwnerState = session.ownerState;
    session.frameOwner = "recorded";
    session.timelineOwner = "recorded";
    setWisCameraTimelineOwnerState(runtimeState, key, session.ownerState, {
      generation: session.generation,
      sessionId: session.id,
      reason: status,
    });
    if (status === "rebuffering") session.rebufferingStartedAtMonotonic = session.rebufferingStartedAtMonotonic || nowMs;
    if (status === "catching-up") session.catchingUpStartedAtMonotonic = session.catchingUpStartedAtMonotonic || nowMs;
    if (status === "restarting") session.restartingStartedAtMonotonic = nowMs;
    if (status === "recordedPlaying") {
      session.rebufferingStartedAtMonotonic = 0;
      session.catchingUpStartedAtMonotonic = 0;
      session.restartingStartedAtMonotonic = 0;
    }
    session.updatedAt = Date.now();
    if (previousStatus !== status) {
      noteWisCameraPerf(runtimeState, key, "statusPatches");
      emitMediaEvent("camera.media.playback_status", {
        reason,
        sessionStatus: status,
        clockPaused: session.clockPaused,
        clockTimeMs: session.currentWallTime,
      });
      if (status === "catching-up") emitMediaEvent("camera.media.catching_up", { reason, clockTimeMs: session.currentWallTime, queueLength: frameQueue.length });
      if (status === "rebuffering") emitMediaEvent("camera.media.rebuffering", { reason, clockTimeMs: session.currentWallTime, queueLength: frameQueue.length });
      options.onFrameDisplayed?.(session, session.renderedFrame || session.frame);
    }
    return session;
  };
  const emitPlaybackHealth = (reason = "sample") => {
    const session = currentSession();
    const nowMs = wisCameraMonotonicNow();
    const clockTimeMs = wisCameraPlaybackClockMs(session, nowMs);
    const lastDisplayedFrameTimeMs = Number(session?.lastDisplayedFrameTimeMs || 0);
    const driftMs = lastDisplayedFrameTimeMs > 0 && Number.isFinite(clockTimeMs)
      ? lastDisplayedFrameTimeMs - clockTimeMs
      : null;
    emitMediaEvent("camera.media.playback_health.sample", {
      reason,
      sessionStatus: cleanText(session?.status, ""),
      clockPaused: Boolean(session?.clockPaused),
      clockTimeMs,
      requestedSeekTimestampMs,
      firstFrameTimestampMs,
      firstFrameArrivalLatencyMs,
      lastDisplayedFrameTimeMs,
      driftMs,
      queueLength: frameQueue.length,
      displayTimerActive: Boolean(displayTimer),
      displayInProgress,
      streamEnded,
      readerActive,
      lastPacketTimestampMs,
      lastPacketArrivalMs,
      lastPacketIntervalMs,
      lastPacketTimestampIntervalMs,
      lastPacketSeq,
      lastDisplayedPacketSeq,
      lastDisplayedMonotonicMs,
      lastSchedulerRunMs,
    }, { sampleMs: WIS_CAMERA_PLAYBACK_HEALTH_SAMPLE_MS });
    let rafLoops = 0;
    try {
      const controller = typeof options.playbackController === "function" ? options.playbackController() : options.playbackController;
      const controllerState = controller?.getState?.();
      rafLoops = (controllerState?.renderLoopId != null ? 1 : 0) + (controllerState?.clockLoopId != null ? 1 : 0);
    } catch {
      rafLoops = 0;
    }
    setWisCameraPerfActive(runtimeState, key, {
      rafLoops,
      readers: readerActive ? 1 : 0,
      playbackLoops: disposed ? 0 : 1,
      timers: 0,
      intervals: 0,
      schedulerTasks: (displayTimer ? 1 : 0) + (healthTimer ? 1 : 0),
      pendingDecodes: displayInProgress ? 1 : 0,
      objectUrls: activeDisplayObjectUrls.size + (playbackObjectUrlMap(runtimeState).get(key) ? 1 : 0),
    });
    sampleWisCameraPerf(runtimeState, key, {
      generation: Number(token.generation || 0),
      queueLength: frameQueue.length,
    }, emitMediaEvent);
  };
  const startHealthTimer = () => {
    if (healthTimer) return;
    const healthTick = () => {
      if (!isCurrent()) {
        clearHealthTimer();
        return;
      }
      emitPlaybackHealth("interval");
      schedulePlaybackFrame("health-interval");
      healthTimer = scheduleWisCameraVisualTask(runtimeState, key, "playback-health", healthTick, WIS_CAMERA_PLAYBACK_HEALTH_SAMPLE_MS, env, "health-interval");
      loopRecord.healthTimerActive = Boolean(healthTimer);
      syncLoopPerfActive();
    };
    healthTimer = scheduleWisCameraVisualTask(runtimeState, key, "playback-health", healthTick, WIS_CAMERA_PLAYBACK_HEALTH_SAMPLE_MS, env, "health-start");
    loopRecord.healthTimerActive = true;
    syncLoopPerfActive();
  };
  const finishPlaybackStreamWhenDrained = () => {
    if (!streamEnded || readerActive || displayTimer || displayInProgress || frameQueue.length) return false;
    const session = currentSession();
    if (session && !session.firstRecordedFrameDisplayed) {
      emitMediaEvent("camera.server.stream.gap_suspected", {
        reason: "stream-ended-before-first-display",
        requestedSeekTimestampMs,
        firstFrameTimestampMs,
        firstFrameArrivalLatencyMs,
      });
      markPlaybackStatus("gap", "stream-ended-before-first-display");
      cleanupPlaybackController(false);
      return true;
    }
    cleanupPlaybackController(isCurrent());
    return true;
  };
  const displayPlaybackFrame = async (packet, attemptSeq) => {
    if (!isCurrent() || isPlaybackPaused()) return false;
    const displayedFrame = {
      ...(baseFrame || {}),
      id: packet.frameId || cleanText(baseFrame?.id, ""),
      timestamp_ms: Number(packet.timestampMs || wisCameraTimelinePlaybackStartMs(baseFrame)),
    };
    delete displayedFrame.seek_target_ms;
    delete displayedFrame.seekTargetMs;
    delete displayedFrame.snapped_timestamp_ms;
    delete displayedFrame.snappedTimestampMs;
    const activeSession = currentSession();
    const visibleImage = visibleWisCameraImage(image);
    const previousFrameMs = Math.round(Number(activeSession?.lastDisplayedFrameTimeMs || visibleImage?.dataset?.wisPlaybackFrameMs || image.dataset?.wisPlaybackFrameMs || 0));
    if (previousFrameMs > 0 && previousFrameMs === Math.round(Number(displayedFrame.timestamp_ms || 0))) {
      noteWisCameraPerf(runtimeState, key, "duplicateFrameSkips");
      emitMediaEvent("camera.media.playback_frame.duplicate_skipped", {
        frameTimestampMs: displayedFrame.timestamp_ms,
        packetSeq: packet.packetSeq,
        queueLength: frameQueue.length,
      }, { sampleMs: 1000 });
      return false;
    }
    const BlobCtor = env.Blob || globalThis.Blob;
    const URLApi = env.URL || globalThis.URL;
    if (!BlobCtor || !URLApi?.createObjectURL) return false;
    const objectUrl = URLApi.createObjectURL(new BlobCtor([packet.frameBytes], { type: packet.contentType || "image/jpeg" }));
    activeDisplayObjectUrls.set(attemptSeq, objectUrl);
    syncLoopPerfActive();
    const previousUrl = playbackObjectUrlMap(runtimeState).get(key);
    const clockTimeMs = currentClockMs();
    const swapped = await decodeAndSwapImage(image, objectUrl, mediaOwner, {
      env,
      element: image.parentElement,
      streamId: key,
      mode: "recorded",
      generation: Number(token.generation || 0),
      revokeOnStale: true,
      isCurrent: () => isCurrent() && !isPlaybackPaused() && displaySeq === attemptSeq,
      onVisualBlink: (payload) => emitMediaEvent("camera.visual.blink_detected", payload, { always: true }),
      onStale: () => emitMediaEvent("camera.media.stale_writer.ignored", {
        frameTimestampMs: displayedFrame.timestamp_ms,
        clockTimeMs,
      }, { sampleMs: 1000 }),
      beforeSwap: (targetImage = image) => {
        targetImage.dataset.wisMediaPlaceholder = "decoding";
        targetImage.dataset.wisMediaPlaceholderForGeneration = String(mediaOwner.generation);
        targetImage.dataset.wisPlaybackStream = "1";
        targetImage.dataset.wisPlaybackFrameMs = String(displayedFrame.timestamp_ms);
        targetImage.dataset.wisPlaybackFrameId = displayedFrame.id;
        playbackObjectUrlMap(runtimeState).set(key, objectUrl);
      },
      onSwap: (visibleTarget = visibleWisCameraImage(image)) => {
        noteWisCameraPerf(runtimeState, key, "srcChanges");
        emitMediaEvent("camera.media.src.swap", {
          frameTimestampMs: displayedFrame.timestamp_ms,
          clockTimeMs,
          driftMs: Number(displayedFrame.timestamp_ms || 0) - Number(clockTimeMs || 0),
          queueLength: frameQueue.length,
          packetSeq: packet.packetSeq,
          imageOwner: visibleTarget?.dataset?.wisMediaOwner,
        }, { sampleMs: 1000 });
      },
    });
    activeDisplayObjectUrls.delete(attemptSeq);
    syncLoopPerfActive();
    if (!swapped || !isCurrent() || isPlaybackPaused() || attemptSeq !== displaySeq) {
      emitMediaEvent("camera.visual.frame_commit", {
        mode: "recorded",
        decodedOk: false,
        frameTimestampMs: displayedFrame.timestamp_ms,
        visibleLayerOwner: visibleWisCameraImage(image)?.dataset?.wisMediaOwner || image.dataset?.wisMediaOwner,
        packetSeq: packet.packetSeq,
      });
      if (playbackObjectUrlMap(runtimeState).get(key) === objectUrl) playbackObjectUrlMap(runtimeState).delete(key);
      try {
        URLApi.revokeObjectURL?.(objectUrl);
      } catch {
        // Best effort cleanup for stale decoded frames.
      }
      return false;
    }
    const beforeFrameSession = currentSession();
    const isFirstDisplayedFrame = !beforeFrameSession?.firstRecordedFrameDisplayed;
    const keepPaused = Boolean(beforeFrameSession?.userPaused);
    const displayStatus = displayedPacketStatus(packet.playbackStatus, "recordedPlaying");
    const session = setWisCameraPlaybackFrame(runtimeState, key, displayedFrame, {
      ...token,
      status: keepPaused ? "paused" : displayStatus,
      state: keepPaused ? "paused" : displayStatus,
      paused: keepPaused,
      firstFrameDisplayed: isFirstDisplayedFrame,
      updateClockAnchor: isFirstDisplayedFrame,
    });
	    lastDisplayedPacketSeq = Number(packet.packetSeq || lastDisplayedPacketSeq);
	    lastDisplayedMonotonicMs = wisCameraMonotonicNow();
	    if (session) {
	      loopRecord.playbackFramesCommitted += 1;
	      updatePlaybackReaderStats({ playbackFramesCommitted: 1 });
	      const displayClockTimeMs = currentClockMs();
	      session.playbackQueueLength = frameQueue.length;
      session.playbackDriftMs = Number(displayedFrame.timestamp_ms || 0) - Number(displayClockTimeMs || 0);
      session.lastPacketTimestampMs = lastPacketTimestampMs;
      session.lastPacketArrivalMonotonicMs = lastPacketArrivalMs;
      session.lastPacketIntervalMs = lastPacketIntervalMs;
      session.lastPacketTimestampIntervalMs = lastPacketTimestampIntervalMs;
      session.readerActive = readerActive;
      session.streamEnded = streamEnded;
      rememberWisCameraLastGoodFrameFromImage(runtimeState, key, image, displayedFrame, {
        ownerKind: mediaOwner.kind,
        sessionId: mediaOwner.sessionId,
        generation: mediaOwner.generation,
      });
      options.onFrameDisplayed?.(session, displayedFrame);
      emitMediaEvent("camera.visual.frame_commit", {
        mode: "recorded",
        decodedOk: true,
        frameTimestampMs: displayedFrame.timestamp_ms,
        visibleLayerOwner: visibleWisCameraImage(image)?.dataset?.wisMediaOwner || image.dataset?.wisMediaOwner,
        packetSeq: packet.packetSeq,
      });
      emitMediaEvent("camera.media.drift.sample", {
        frameTimestampMs: displayedFrame.timestamp_ms,
        clockTimeMs: displayClockTimeMs,
        driftMs: session.playbackDriftMs,
        queueLength: frameQueue.length,
        packetSeq: packet.packetSeq,
      }, { sampleMs: WIS_CAMERA_PLAYBACK_HEALTH_SAMPLE_MS });
    }
    emitMediaEvent("camera.media.playback_frame.displayed.sample", {
      frameTimestampMs: displayedFrame.timestamp_ms,
      clockTimeMs: currentClockMs(),
      driftMs: Number(displayedFrame.timestamp_ms || 0) - Number(currentClockMs() || 0),
      queueLength: frameQueue.length,
      packetSeq: packet.packetSeq,
    }, { sampleMs: 1000 });
    if (previousUrl && previousUrl !== objectUrl) {
      env.setTimeout?.(() => {
        try {
          URLApi.revokeObjectURL?.(previousUrl);
        } catch {
          // Best effort cleanup for frame object URLs.
        }
      }, 1000);
    }
    return Boolean(session);
  };
  const displayPlaybackFrameWithTimeout = (packet, attemptSeq) => new Promise((resolve) => {
    let settled = false;
    const URLApi = env.URL || globalThis.URL;
    const timeout = env.setTimeout?.(() => {
      if (settled) return;
      settled = true;
      if (displaySeq === attemptSeq) displaySeq += 1;
      const objectUrl = activeDisplayObjectUrls.get(attemptSeq);
      activeDisplayObjectUrls.delete(attemptSeq);
      syncLoopPerfActive();
      if (objectUrl) {
        try {
          URLApi?.revokeObjectURL?.(objectUrl);
        } catch {
          // Best effort cleanup for timed-out frame URLs.
        }
      }
      emitMediaEvent("camera.media.playback_frame.decode_timeout", {
        packetSeq: packet.packetSeq,
        frameTimestampMs: Number(packet.timestampMs || 0),
        clockTimeMs: currentClockMs(),
        queueLength: frameQueue.length,
      });
      resolve(false);
    }, WIS_CAMERA_PLAYBACK_DECODE_TIMEOUT_MS);
    void displayPlaybackFrame(packet, attemptSeq).then((result) => {
      if (settled) return;
      settled = true;
      if (timeout) env.clearTimeout?.(timeout);
      resolve(result);
    }).catch((error) => {
      if (settled) return;
      settled = true;
      if (timeout) env.clearTimeout?.(timeout);
      emitMediaEvent("camera.media.playback_frame.decode_error", {
        packetSeq: packet.packetSeq,
        frameTimestampMs: Number(packet.timestampMs || 0),
        error: error?.message || String(error),
      });
      resolve(false);
    });
  });
  const scheduleTimer = (delayMs = 0, reason = "timer") => {
    if (!isCurrent() || displayTimer) return;
    const delay = Math.max(0, Math.round(Number(delayMs) || 0));
    displayTimerStartedAtMs = wisCameraMonotonicNow();
    displayTimer = scheduleWisCameraVisualTask(runtimeState, key, "playback-display", () => {
      displayTimer = 0;
      displayTimerStartedAtMs = 0;
      loopRecord.displayTimerActive = false;
      syncLoopPerfActive();
      playbackTimerMap(runtimeState).delete(key);
      schedulePlaybackFrame(reason);
    }, delay, env, reason);
    if (displayTimer) {
      loopRecord.displayTimerActive = true;
      syncLoopPerfActive();
      playbackTimerMap(runtimeState).set(key, displayTimer);
    }
  };
  const requestPlaybackRestart = (reason = "hard-stall") => {
    if (restartRequestedUrl || streamEnded || !isCurrent()) return false;
    if (restartCount >= WIS_CAMERA_PLAYBACK_RESTART_LIMIT) {
      emitMediaEvent("camera.server.stream.gap_suspected", {
        reason: "restart-budget-exhausted",
        restartCount,
        clockTimeMs: currentClockMs(),
        lastPacketTimestampMs,
        lastPacketArrivalMs,
      });
	      markPlaybackStatus("stalled", reason);
	      frameQueue.length = 0;
	      notePlaybackReaderAbort(reason);
	      try {
	        activeController?.abort?.();
	      } catch {
        // Reader may already be closed.
      }
      cleanupPlaybackController(false);
      return false;
    }
    const targetTimeMs = currentClockMs();
    restartCount += 1;
    restartRequestedReason = reason;
    restartRequestedUrl = playbackRestartUrl(currentPlaybackUrl || playbackUrl, targetTimeMs, env);
    const session = currentSession();
    if (session) {
      session.playbackRestartCount = restartCount;
      session.updatedAt = Date.now();
    }
    frameQueue.length = 0;
    streamEnded = false;
    markPlaybackStatus("restarting", reason);
    emitMediaEvent("camera.server.stream.restart", {
      reason,
      restartCount,
      targetTimeMs,
      playbackUrl: restartRequestedUrl,
      readerActive,
    });
	    emitMediaEvent("camera.media.playback_stream.restart", {
	      reason,
	      restartCount,
	      targetTimeMs,
	      playbackUrl: restartRequestedUrl,
	      readerActive,
	    });
	    notePlaybackReaderAbort(reason);
	    try {
	      activeController?.abort?.();
	    } catch {
      // Reader may already be closed.
    }
    scheduleTimer(0, "restart-requested");
    return true;
  };
	  function schedulePlaybackFrame(reason = "schedule") {
	    if (!isCurrent()) {
	      frameQueue.length = 0;
	      cleanupPlaybackController(false);
	      return;
	    }
	    const nowMs = wisCameraMonotonicNow();
	    lastSchedulerRunMs = nowMs;
	    traceWisCameraBoundary("recorded.loop.tick", {
	      functionName: "schedulePlaybackFrame",
	      streamId: key,
	      generation: Number(token.generation || 0),
	      sessionId: cleanText(token.sessionId, ""),
	      reason,
	      queueLength: frameQueue.length,
	      activeLoops: loopRecord.disposed ? 0 : 1,
	      activeReaders: loopRecord.readerActive ? 1 : 0,
	      displayTimerActive: loopRecord.displayTimerActive ? 1 : 0,
	      healthTimerActive: loopRecord.healthTimerActive ? 1 : 0,
	      frameTimestampMs: Number(frameQueue[0]?.timestampMs || 0),
	    });
	    traceWisCameraRuntimePlayback("playback.clock.tick", runtimeState, key, {
	      generation: Number(token.generation || 0),
	      playbackClockMs: currentClockMs(nowMs),
	      visibleFrameMs: Number(currentSession()?.lastDisplayedFrameTimeMs || image?.dataset?.wisPlaybackFrameMs || 0),
	      paused: Boolean(currentSession()?.clockPaused),
	      reason,
	    });
	    const budget = playbackBudget();
    const sessionForBudget = currentSession();
    if (sessionForBudget) {
      sessionForBudget.performanceTier = budget.tier;
      sessionForBudget.visualBudgetFps = budget.visualFps;
      sessionForBudget.visualSuspended = !budget.allowVisualWork;
      sessionForBudget.updatedAt = Date.now();
    }
    if (displayTimer) {
      const staleTimerMs = nowMs - displayTimerStartedAtMs;
      if (staleTimerMs <= WIS_CAMERA_PLAYBACK_MAX_FUTURE_WAIT_MS + WIS_CAMERA_PLAYBACK_DECODE_TIMEOUT_MS) return;
      clearDisplayTimer();
    }
    if (displayInProgress) {
      const displayAgeMs = nowMs - displayStartedAtMs;
      const newestQueuedMs = Math.max(0, ...frameQueue.map((packet) => Number(packet?.timestampMs || 0)).filter(Number.isFinite));
      const visibleImage = visibleWisCameraImage(image);
      const lastRenderedMs = Math.round(Number(currentSession()?.lastDisplayedFrameTimeMs || visibleImage?.dataset?.wisPlaybackFrameMs || image.dataset?.wisPlaybackFrameMs || 0));
      const canIgnorePendingDecode = frameQueue.length > 1 && newestQueuedMs > lastRenderedMs && displayAgeMs > Math.min(250, Math.max(100, budget.visualMinIntervalMs));
      if (displayAgeMs <= WIS_CAMERA_PLAYBACK_DECODE_TIMEOUT_MS + 250 && !canIgnorePendingDecode) return;
      displaySeq += 1;
      displayInProgress = false;
      activeDisplayAttemptSeq = 0;
      emitMediaEvent("camera.media.playback_frame.decode_timeout", {
        reason: canIgnorePendingDecode ? "decode-superseded-by-newer-frame" : "display-in-progress-fuse",
        displayAgeMs,
        clockTimeMs: currentClockMs(nowMs),
        queueLength: frameQueue.length,
      }, { sampleMs: 1000 });
      syncLoopPerfActive();
    }
    emitPlaybackHealth(reason);
    const activeSession = currentSession();
    const sinceLastDisplayMs = lastDisplayedMonotonicMs > 0 ? nowMs - lastDisplayedMonotonicMs : 0;
    if (activeSession?.userPaused || cleanText(activeSession?.status, "") === "paused") {
      if (frameQueue.length > maxBufferFramesForBudget()) {
        frameQueue.splice(0, frameQueue.length - maxBufferFramesForBudget());
      }
      scheduleTimer(Math.min(250, playbackVisualFrameMs()), "paused");
      return;
    }
    if (!budget.allowVisualWork) {
      while (frameQueue.length > 1) {
        const dropped = frameQueue.shift();
        emitMediaEvent("camera.media.playback_frame.dropped_stale.sample", {
          reason: `${budget.tier}-visual-suspended`,
          frameTimestampMs: Number(dropped?.timestampMs || 0),
          clockTimeMs: currentClockMs(nowMs),
          queueLength: frameQueue.length,
          packetSeq: dropped?.packetSeq,
        }, { sampleMs: 1000 });
      }
      if (activeSession) {
        activeSession.playbackQueueLength = frameQueue.length;
        activeSession.readerActive = readerActive;
        activeSession.streamEnded = streamEnded;
        activeSession.updatedAt = Date.now();
      }
      scheduleTimer(playbackRetryMs(), `${budget.tier}-visual-suspended`);
      return;
    }
    const sinceSelectionMs = lastVisualSelectionAtMs > 0 ? nowMs - lastVisualSelectionAtMs : Infinity;
    if (sinceSelectionMs < budget.visualMinIntervalMs) {
      scheduleTimer(budget.visualMinIntervalMs - sinceSelectionMs, "visual-fps-budget");
      return;
    }
    if (
      activeSession?.firstRecordedFrameDisplayed
      && sinceLastDisplayMs >= WIS_CAMERA_PLAYBACK_NO_DISPLAY_REBUFFER_MS
      && (readerActive || frameQueue.length)
      && !["rebuffering", "stalled", "gap"].includes(activeSession.status)
    ) {
      markPlaybackStatus("rebuffering", "no-new-display");
    }
    if (!frameQueue.length) {
      if (finishPlaybackStreamWhenDrained()) return;
      if (readerActive || !streamEnded) {
        const sincePacketMs = lastPacketArrivalMs > 0 ? nowMs - lastPacketArrivalMs : nowMs - (readerStartedAtMs || nowMs);
        if (activeSession?.firstRecordedFrameDisplayed && (sincePacketMs >= WIS_CAMERA_PLAYBACK_REBUFFER_MS || sinceLastDisplayMs >= WIS_CAMERA_PLAYBACK_NO_DISPLAY_REBUFFER_MS)) {
          markPlaybackStatus("rebuffering", "queue-empty");
        }
        if (!streamEnded && sincePacketMs >= WIS_CAMERA_PLAYBACK_HARD_STALL_MS) {
          const stallPayload = {
            reason: "no-packets",
            sincePacketMs,
            restartCount,
            readerActive,
            clockTimeMs: currentClockMs(nowMs),
          };
          emitMediaEvent("camera.server.stream.stall_suspected", stallPayload, { sampleMs: WIS_CAMERA_PLAYBACK_HEALTH_SAMPLE_MS });
          emitMediaEvent("camera.media.playback_stream.stall_suspected", stallPayload, { sampleMs: WIS_CAMERA_PLAYBACK_HEALTH_SAMPLE_MS });
          if (!requestPlaybackRestart("no-packets-hard-stall") && !restartRequestedUrl) markPlaybackStatus("stalled", "no-packets-hard-stall");
        }
        scheduleTimer(Math.min(250, playbackVisualFrameMs()), "queue-empty");
      }
      return;
    }
    const clockTimeMs = currentClockMs(nowMs);
	    let decision = selectWisCameraPlaybackFrame(frameQueue, clockTimeMs, {
	      targetFrameMs: playbackVisualFrameMs(),
	      maxFutureWaitMs: WIS_CAMERA_PLAYBACK_MAX_FUTURE_WAIT_MS,
	    });
	    if (decision.action === "hold" && !activeSession?.firstRecordedFrameDisplayed) {
	      traceWisCameraBoundary("recorded.first_frame.future.accepted", {
	        functionName: "schedulePlaybackFrame",
	        streamId: key,
	        generation: Number(token.generation || 0),
	        sessionId: cleanText(token.sessionId, ""),
	        reason: decision.reason,
	        previousAction: decision.action,
	        frameTimestampMs: Number(frameQueue[decision.index]?.timestampMs || frameQueue[0]?.timestampMs || 0),
	        clockTimeMs,
	        driftMs: decision.driftMs,
	        queueLength: frameQueue.length,
	      });
	      decision = {
	        ...decision,
	        action: "display",
	        waitMs: 0,
	        status: "recordedPlaying",
	        reason: "first-frame-after-seek",
	      };
	    }
	    if (decision.action === "empty") {
      while (decision.dropCount > 0 && frameQueue.length) {
        const dropped = frameQueue.shift();
        decision.dropCount -= 1;
        emitMediaEvent("camera.media.playback_frame.dropped_stale.sample", {
          reason: decision.reason,
          frameTimestampMs: Number(dropped?.timestampMs || 0),
          clockTimeMs,
          queueLength: frameQueue.length,
          packetSeq: dropped?.packetSeq,
        }, { sampleMs: 1000 });
      }
      markPlaybackStatus("rebuffering", decision.reason);
      scheduleTimer(Math.min(250, playbackVisualFrameMs()), decision.reason);
      return;
    }
    if (decision.action === "hold") {
      while (decision.dropCount > 0 && frameQueue.length > 1) {
        const dropped = frameQueue.shift();
        decision.dropCount -= 1;
        emitMediaEvent("camera.media.playback_frame.dropped_stale.sample", {
          reason: decision.reason,
          frameTimestampMs: Number(dropped?.timestampMs || 0),
          clockTimeMs,
          queueLength: frameQueue.length,
          packetSeq: dropped?.packetSeq,
        }, { sampleMs: 1000 });
      }
      scheduleTimer(decision.waitMs, "hold-ahead-frame");
      return;
    }
    while (decision.dropCount > 0 && frameQueue.length > 1) {
      const dropped = frameQueue.shift();
      decision.dropCount -= 1;
      emitMediaEvent("camera.media.playback_frame.dropped_stale.sample", {
        reason: decision.reason,
        frameTimestampMs: Number(dropped?.timestampMs || 0),
        clockTimeMs,
        driftMs: Number(dropped?.timestampMs || 0) - Number(clockTimeMs || 0),
        queueLength: frameQueue.length,
        packetSeq: dropped?.packetSeq,
      }, { sampleMs: 1000 });
    }
    if (decision.status === "catching-up") {
      markPlaybackStatus("catching-up", decision.reason);
    } else if (["catching-up", "rebuffering"].includes(cleanText(activeSession?.status, ""))) {
      markPlaybackStatus("recordedPlaying", decision.reason);
    }
    const packet = frameQueue.shift();
    if (!packet) {
      scheduleTimer(Math.min(250, playbackVisualFrameMs()), "missing-packet");
      return;
    }
    noteWisCameraPerf(runtimeState, key, "frameSelections");
    lastVisualSelectionAtMs = nowMs;
    const visibleImage = visibleWisCameraImage(image);
    const lastRenderedMs = Math.round(Number(currentSession()?.lastDisplayedFrameTimeMs || visibleImage?.dataset?.wisPlaybackFrameMs || image.dataset?.wisPlaybackFrameMs || 0));
    const selectedPacketMs = Math.round(Number(packet.timestampMs || 0));
    if (lastRenderedMs > 0 && selectedPacketMs > 0 && lastRenderedMs === selectedPacketMs) {
      noteWisCameraPerf(runtimeState, key, "duplicateFrameSkips");
      emitMediaEvent("camera.media.playback_frame.duplicate_skipped", {
        reason: decision.reason,
        frameTimestampMs: selectedPacketMs,
        clockTimeMs,
        queueLength: frameQueue.length,
        packetSeq: packet.packetSeq,
      }, { sampleMs: 1000 });
      scheduleTimer(Math.min(250, Math.max(25, playbackVisualFrameMs())), "duplicate-frame-skipped");
      return;
    }
    emitMediaEvent("camera.media.best_frame_selected", {
      reason: decision.reason,
      action: decision.action,
      frameTimestampMs: Number(packet.timestampMs || 0),
      rawTimestampMs: Number.isFinite(Number(packet.rawTimestampMs)) ? Number(packet.rawTimestampMs) : null,
      clockTimeMs,
      driftMs: decision.driftMs,
      queueLength: frameQueue.length,
      packetSeq: packet.packetSeq,
      timestampQuality: packet.timestampQuality || "server",
    }, { sampleMs: WIS_CAMERA_PLAYBACK_HEALTH_SAMPLE_MS });
    packet.playbackStatus = displayedPacketStatus(currentSession()?.status, decision.status || "recordedPlaying");
    const attemptSeq = ++displaySeq;
    displayInProgress = true;
    displayStartedAtMs = nowMs;
    activeDisplayAttemptSeq = attemptSeq;
    syncLoopPerfActive();
    void displayPlaybackFrameWithTimeout(packet, attemptSeq).finally(() => {
      if (activeDisplayAttemptSeq === attemptSeq) {
        displayInProgress = false;
        displayStartedAtMs = 0;
        activeDisplayAttemptSeq = 0;
        syncLoopPerfActive();
      }
      schedulePlaybackFrame("display-complete");
    });
  }
  loopRecord.schedule = schedulePlaybackFrame;
  const normalizePacketTimestamp = (rawTimestampMs) => {
    const raw = Number(rawTimestampMs);
    const hasValidRaw = Number.isFinite(raw) && raw > 0;
    let timestampMs = hasValidRaw ? raw : 0;
    let reason = "";
    if (!hasValidRaw) {
      reason = "missing";
      emitMediaEvent("camera.server.packet.timestamp_missing", {
        requestedSeekTimestampMs,
        previousPacketTimestampMs: lastPacketTimestampMs,
      }, { sampleMs: 1000 });
    } else if (lastRawPacketTimestampMs > 0 && raw === lastRawPacketTimestampMs) {
      reason = "repeated";
      emitMediaEvent("camera.server.packet.timestamp_repeated", {
        rawTimestampMs: raw,
        previousRawTimestampMs: lastRawPacketTimestampMs,
        previousPacketTimestampMs: lastPacketTimestampMs,
      }, { sampleMs: 1000 });
    } else if (lastRawPacketTimestampMs > 0 && raw < lastRawPacketTimestampMs) {
      reason = "backwards";
      emitMediaEvent("camera.server.packet.timestamp_backwards", {
        rawTimestampMs: raw,
        previousRawTimestampMs: lastRawPacketTimestampMs,
        previousPacketTimestampMs: lastPacketTimestampMs,
      }, { sampleMs: 1000 });
    } else if (lastPacketTimestampMs > 0 && raw <= lastPacketTimestampMs) {
      reason = "normalized-backwards";
      emitMediaEvent("camera.server.packet.timestamp_backwards", {
        rawTimestampMs: raw,
        previousRawTimestampMs: lastRawPacketTimestampMs,
        previousPacketTimestampMs: lastPacketTimestampMs,
      }, { sampleMs: 1000 });
    }
    if (reason) {
      const syntheticBaseMs = lastPacketTimestampMs > 0
        ? lastPacketTimestampMs
        : (currentClockMs() || requestedSeekTimestampMs || wisCameraTimelinePlaybackStartMs(baseFrame) || Date.now());
      timestampMs = syntheticBaseMs + sourceFrameMs;
      emitMediaEvent("camera.media.playback_frame.timestamp_normalized.sample", {
        reason,
        rawTimestampMs: hasValidRaw ? raw : null,
        normalizedTimestampMs: timestampMs,
        previousPacketTimestampMs: lastPacketTimestampMs,
        targetFrameMs: sourceFrameMs,
      }, { sampleMs: 1000 });
    }
    if (hasValidRaw) lastRawPacketTimestampMs = raw;
    return {
      rawTimestampMs: hasValidRaw ? raw : null,
      timestampMs,
      timestampQuality: reason ? `normalized-${reason}` : "server",
    };
  };
  const enqueuePlaybackFrame = (packet) => {
    if (!isCurrent()) return;
    const nowMs = wisCameraMonotonicNow();
    const previousPacketArrivalMs = lastPacketArrivalMs;
    const previousPacketTimestampMs = lastPacketTimestampMs;
    const normalized = normalizePacketTimestamp(packet.timestampMs);
    const timestampMs = normalized.timestampMs;
    lastPacketSeq += 1;
    lastPacketTimestampMs = timestampMs;
    lastPacketArrivalMs = nowMs;
    const packetIntervalMs = previousPacketArrivalMs > 0 ? nowMs - previousPacketArrivalMs : 0;
    const packetTimestampIntervalMs = previousPacketTimestampMs > 0 ? timestampMs - previousPacketTimestampMs : 0;
    lastPacketIntervalMs = packetIntervalMs;
    lastPacketTimestampIntervalMs = packetTimestampIntervalMs;
    if (packetIntervalMs > sourceFrameMs * 2.5) {
      const slowPayload = {
        packetIntervalMs,
        packetTimestampIntervalMs,
        expectedFrameIntervalMs: sourceFrameMs,
        playbackFps,
        lastPacketTimestampMs,
        queueLength: frameQueue.length,
      };
      emitMediaEvent("camera.server.packet.slow", slowPayload, { sampleMs: 1000 });
      emitMediaEvent("camera.media.playback_stream.slow_packets.sample", slowPayload, { sampleMs: 1000 });
      if (currentSession()?.firstRecordedFrameDisplayed) markPlaybackStatus("rebuffering", "slow-packets");
    } else if (packetIntervalMs > 0 && packetIntervalMs < sourceFrameMs * 0.5) {
      emitMediaEvent("camera.server.packet.burst", {
        packetIntervalMs,
        packetTimestampIntervalMs,
        expectedFrameIntervalMs: sourceFrameMs,
        queueLength: frameQueue.length,
      }, { sampleMs: 1000 });
    }
    if (!firstFrameReceived) {
      firstFrameReceived = true;
      firstFrameTimestampMs = timestampMs;
      firstFrameArrivalLatencyMs = nowMs - (readerStartedAtMs || nowMs);
      const offsetFromSeekMs = Number.isFinite(requestedSeekTimestampMs) && requestedSeekTimestampMs > 0
        ? timestampMs - requestedSeekTimestampMs
        : null;
      emitMediaEvent("camera.server.first_frame.received", {
        requestedSeekTimestampMs,
        firstFrameTimestampMs,
        rawTimestampMs: normalized.rawTimestampMs,
        firstFrameArrivalLatencyMs,
        offsetFromSeekMs,
        timestampQuality: normalized.timestampQuality,
      });
      emitMediaEvent("camera.server.first_frame.offset_from_seek", {
        requestedSeekTimestampMs,
        firstFrameTimestampMs,
        offsetFromSeekMs,
      });
      if (Number.isFinite(offsetFromSeekMs) && Math.abs(offsetFromSeekMs) > WIS_CAMERA_PLAYBACK_HARD_CATCHUP_LAG_MS) {
        emitMediaEvent("camera.server.stream.gap_suspected", {
          reason: "first-frame-offset",
          requestedSeekTimestampMs,
          firstFrameTimestampMs,
          offsetFromSeekMs,
        });
      }
      const session = currentSession();
      if (session) {
        session.firstFrameTimestampMs = firstFrameTimestampMs;
        session.firstFrameArrivalLatencyMs = firstFrameArrivalLatencyMs;
        session.firstFrameOffsetFromSeekMs = offsetFromSeekMs;
        session.gapSuspected = Number.isFinite(offsetFromSeekMs) && Math.abs(offsetFromSeekMs) > WIS_CAMERA_PLAYBACK_HARD_CATCHUP_LAG_MS;
        session.updatedAt = Date.now();
      }
    }
    frameQueue.push({
      ...packet,
      rawTimestampMs: normalized.rawTimestampMs,
      timestampMs,
      timestampQuality: normalized.timestampQuality,
      packetSeq: lastPacketSeq,
      arrivalMonotonicMs: nowMs,
    });
    const session = currentSession();
    if (session) {
      session.lastPacketTimestampMs = lastPacketTimestampMs;
      session.lastPacketArrivalMonotonicMs = lastPacketArrivalMs;
      session.lastPacketIntervalMs = lastPacketIntervalMs;
      session.lastPacketTimestampIntervalMs = lastPacketTimestampIntervalMs;
      session.playbackQueueLength = frameQueue.length;
      session.readerActive = readerActive;
      session.streamEnded = streamEnded;
      session.updatedAt = Date.now();
    }
    while (frameQueue.length > maxBufferFramesForBudget()) {
      const dropped = frameQueue.shift();
      emitMediaEvent("camera.media.playback_frame.dropped_stale.sample", {
        reason: "max-buffer",
        frameTimestampMs: Number(dropped?.timestampMs || 0),
        clockTimeMs: currentClockMs(),
        driftMs: Number(dropped?.timestampMs || 0) - Number(currentClockMs() || 0),
        queueLength: frameQueue.length,
        packetSeq: dropped?.packetSeq,
      }, { sampleMs: 1000 });
    }
    schedulePlaybackFrame("packet-enqueued");
  };
	  const runPlaybackReader = async (readerUrl = playbackUrl, reason = "initial") => {
	    const readerSeq = activeReaderSeq + 1;
	    activeReaderSeq = readerSeq;
	    currentPlaybackUrl = readerUrl;
	    const controller = new env.AbortController();
	    activeController = controller;
	    activeReaderAbortCounted = false;
	    playbackControllerMap(runtimeState).set(key, controller);
	    readerActive = true;
	    loopRecord.readerActive = true;
	    syncLoopPerfActive();
	    streamEnded = false;
	    readerStartedAtMs = wisCameraMonotonicNow();
	    let readerDoneNoted = false;
	    const noteReaderLifetime = () => Math.max(0, Math.round(wisCameraMonotonicNow() - (readerStartedAtMs || wisCameraMonotonicNow())));
	    const noteReaderDone = (doneReason = "reader-done", extra = {}) => {
	      if (readerDoneNoted) return;
	      readerDoneNoted = true;
	      const lifetimeMs = noteReaderLifetime();
	      loopRecord.playbackReaderDoneCount += 1;
	      loopRecord.playbackReaderLastDoneReason = cleanText(doneReason, "reader-done");
	      loopRecord.playbackReaderLifetimeMs = lifetimeMs;
	      updatePlaybackReaderStats({
	        playbackReaderDoneCount: 1,
	        playbackReaderLastDoneReason: loopRecord.playbackReaderLastDoneReason,
	        playbackReaderLifetimeMs: lifetimeMs,
	      });
	      traceWisCameraBoundary("camera.media.playback_reader.done", {
	        functionName: "runPlaybackReader",
	        streamId: key,
	        generation: Number(token.generation || 0),
	        sessionId: cleanText(token.sessionId, ""),
	        playbackUrl: readerUrl,
	        reason: loopRecord.playbackReaderLastDoneReason,
	        readerSeq,
	        playbackReaderLifetimeMs: lifetimeMs,
	        playbackChunksReceived: loopRecord.playbackChunksReceived,
	        playbackFramesParsed: loopRecord.playbackFramesParsed,
	        playbackFramesCommitted: loopRecord.playbackFramesCommitted,
	        ...extra,
	      });
	    };
	    const session = currentSession();
	    if (session) {
	      session.readerActive = true;
	      session.streamEnded = false;
      session.playbackQueueLength = frameQueue.length;
      session.updatedAt = Date.now();
    }
	    emitMediaEvent("camera.media.playback_stream.start", {
	      playbackUrl: readerUrl,
	      reason,
	      restartCount,
	    });
	    traceWisCameraBoundary("archive.fetch.started", {
	      functionName: "runPlaybackReader",
	      streamId: key,
	      generation: Number(token.generation || 0),
	      sessionId: cleanText(token.sessionId, ""),
	      playbackUrl: readerUrl,
	      reason,
	      activeLoops: loopRecord.disposed ? 0 : 1,
	      activeReaders: loopRecord.readerActive ? 1 : 0,
	      ownerKind: mediaOwner.kind,
	    });
	    try {
	      const response = await env.fetch(readerUrl, { cache: "no-store", signal: controller.signal });
	      if (!response.ok || !response.body?.getReader) throw new Error(`Playback stream unavailable (${response.status})`);
	      const contentType = response.headers.get("Content-Type") || "";
	      const boundary = contentType.match(/boundary="?([^";]+)"?/i)?.[1];
	      if (!boundary) throw new Error("Playback stream boundary missing");
	      traceWisCameraBoundary("archive.fetch.result", {
	        functionName: "runPlaybackReader",
	        streamId: key,
	        generation: Number(token.generation || 0),
	        sessionId: cleanText(token.sessionId, ""),
	        playbackUrl: readerUrl,
	        fetchResult: "non-empty",
	        status: response.status,
	        contentType,
	        boundary,
	        ownerKind: mediaOwner.kind,
	      });
      const TextEncoderCtor = env.TextEncoder || globalThis.TextEncoder;
      const TextDecoderCtor = env.TextDecoder || globalThis.TextDecoder;
      if (!TextEncoderCtor || !TextDecoderCtor) throw new Error("Playback stream text codec unavailable");
      const boundaryBytes = new TextEncoderCtor().encode(`--${boundary}`);
      const headerEndBytes = new Uint8Array([13, 10, 13, 10]);
      const crlfBytes = new Uint8Array([13, 10]);
	      const decoder = new TextDecoderCtor("utf-8");
	      const reader = response.body.getReader();
	      loopRecord.playbackReaderCreatedCount += 1;
	      updatePlaybackReaderStats({ playbackReaderCreatedCount: 1 });
	      traceWisCameraBoundary("camera.media.playback_reader.created", {
	        functionName: "runPlaybackReader",
	        streamId: key,
	        generation: Number(token.generation || 0),
	        sessionId: cleanText(token.sessionId, ""),
	        playbackUrl: readerUrl,
	        readerSeq,
	        playbackReaderCreatedCount: loopRecord.playbackReaderCreatedCount,
	        ownerState: wisCameraTimelineOwnerState(runtimeState, key),
	        paused: isPlaybackPaused(),
	      });
	      let buffer = new Uint8Array();
	      let needBoundary = true;
	      let currentHeaders = null;
	      let sawFirstPacket = false;
	      while (isCurrent() && activeReaderSeq === readerSeq && !controller.signal.aborted) {
	        traceWisCameraBoundary("camera.media.playback_reader.read_started", {
	          functionName: "runPlaybackReader",
	          streamId: key,
	          generation: Number(token.generation || 0),
	          sessionId: cleanText(token.sessionId, ""),
	          readerSeq,
	          playbackUrl: readerUrl,
	        });
	        const { value, done } = await reader.read();
	        if (done) {
	          noteReaderDone(
	            controller.signal.aborted
	              ? "abort-signal"
	              : (sawFirstPacket ? "end-of-archive" : "reader-done-empty"),
	            { done: true },
	          );
	          break;
	        }
	        loopRecord.playbackChunksReceived += 1;
	        updatePlaybackReaderStats({ playbackChunksReceived: 1 });
	        traceWisCameraBoundary("camera.media.playback_reader.read_result", {
	          functionName: "runPlaybackReader",
	          streamId: key,
	          generation: Number(token.generation || 0),
	          sessionId: cleanText(token.sessionId, ""),
	          readerSeq,
	          done: false,
	          chunkBytes: Number(value?.length || value?.byteLength || 0),
	          playbackChunksReceived: loopRecord.playbackChunksReceived,
	        });
	        buffer = appendBytes(buffer, value);
        while (buffer.length && isCurrent() && activeReaderSeq === readerSeq && !controller.signal.aborted) {
          if (needBoundary) {
            const boundaryIndex = indexOfBytes(buffer, boundaryBytes);
            if (boundaryIndex < 0) {
              buffer = buffer.slice(Math.max(0, buffer.length - boundaryBytes.length - 4));
              break;
	            }
	            buffer = buffer.slice(boundaryIndex + boundaryBytes.length);
	            if (buffer[0] === 45 && buffer[1] === 45) {
	              noteReaderDone(sawFirstPacket ? "end-of-archive" : "multipart-terminator-empty", { done: true });
	              return;
	            }
            if (buffer[0] === crlfBytes[0] && buffer[1] === crlfBytes[1]) buffer = buffer.slice(2);
            needBoundary = false;
          }
          if (!currentHeaders) {
            const headerEndIndex = indexOfBytes(buffer, headerEndBytes);
            if (headerEndIndex < 0) break;
            currentHeaders = parseMjpegHeaders(decoder.decode(buffer.slice(0, headerEndIndex)));
            buffer = buffer.slice(headerEndIndex + headerEndBytes.length);
          }
          const contentLength = Math.max(0, Number(currentHeaders["content-length"] || 0));
          if (!contentLength || buffer.length < contentLength) break;
          const frameBytes = buffer.slice(0, contentLength);
          buffer = buffer.slice(contentLength);
          if (buffer[0] === crlfBytes[0] && buffer[1] === crlfBytes[1]) buffer = buffer.slice(2);
	          const timestampMs = Number(currentHeaders["x-frame-timestamp-ms"] || Date.parse(currentHeaders["x-frame-updated-at"] || ""));
	          const frameId = cleanText(currentHeaders["x-frame-id"], cleanText(baseFrame?.id, ""));
	          loopRecord.playbackFramesParsed += 1;
	          updatePlaybackReaderStats({ playbackFramesParsed: 1 });
	          traceWisCameraBoundary("camera.media.playback_frame.parsed", {
	            functionName: "runPlaybackReader",
	            streamId: key,
	            generation: Number(token.generation || 0),
	            sessionId: cleanText(token.sessionId, ""),
	            readerSeq,
	            frameTimestampMs: Number.isFinite(timestampMs) ? timestampMs : 0,
	            frameId,
	            frameBytes: frameBytes.length,
	            playbackFramesParsed: loopRecord.playbackFramesParsed,
	          });
	          if (!sawFirstPacket) {
            sawFirstPacket = true;
            emitMediaEvent("camera.media.playback_stream.first_packet", {
              frameTimestampMs: Number.isFinite(timestampMs) && timestampMs > 0 ? timestampMs : wisCameraTimelinePlaybackStartMs(baseFrame),
            });
          }
          enqueuePlaybackFrame({
            frameBytes,
            contentType: currentHeaders["content-type"] || "image/jpeg",
            timestampMs,
            frameId,
          });
          currentHeaders = null;
          needBoundary = true;
        }
      }
		    } catch (error) {
		      if (error?.name === "AbortError") {
		        notePlaybackReaderAbort("abort-error");
		        loopRecord.playbackReaderLastDoneReason = "abort-error";
		        updatePlaybackReaderStats({ playbackReaderLastDoneReason: "abort-error", playbackReaderLifetimeMs: noteReaderLifetime() });
		      } else {
		        loopRecord.playbackReaderErrorCount += 1;
		        loopRecord.playbackReaderLastDoneReason = cleanText(error?.message || String(error), "reader-error");
		        loopRecord.playbackReaderLifetimeMs = noteReaderLifetime();
		        updatePlaybackReaderStats({
		          playbackReaderErrorCount: 1,
		          playbackReaderLastDoneReason: loopRecord.playbackReaderLastDoneReason,
		          playbackReaderLifetimeMs: loopRecord.playbackReaderLifetimeMs,
		        });
		        traceWisCameraBoundary("camera.media.playback_reader.error", {
		          functionName: "runPlaybackReader",
		          streamId: key,
		          generation: Number(token.generation || 0),
		          sessionId: cleanText(token.sessionId, ""),
		          playbackUrl: readerUrl,
		          readerSeq,
		          error: loopRecord.playbackReaderLastDoneReason,
		          playbackReaderErrorCount: loopRecord.playbackReaderErrorCount,
		          playbackReaderLifetimeMs: loopRecord.playbackReaderLifetimeMs,
		        });
		      }
		      if (error?.name !== "AbortError" && isCurrent()) {
	        traceWisCameraBoundary("archive.fetch.result", {
	          functionName: "runPlaybackReader",
	          streamId: key,
	          generation: Number(token.generation || 0),
	          sessionId: cleanText(token.sessionId, ""),
	          playbackUrl: readerUrl,
	          fetchResult: "empty",
	          error: error?.message || String(error),
	          ownerKind: mediaOwner.kind,
	        });
	        fellBackToImageSrc = true;
        setWisCameraPlaybackError(runtimeState, key, error.message || String(error), token);
        options.onError?.(error);
        options.fallbackToImageSrc?.();
      }
	    } finally {
	      if (activeReaderSeq === readerSeq) {
	        if (!readerDoneNoted) {
	          const finalReason = controller.signal.aborted
	            ? "abort-signal"
	            : (!isCurrent() ? "generation-cancelled" : "reader-exited");
	          if (controller.signal.aborted) notePlaybackReaderAbort(finalReason);
	          loopRecord.playbackReaderLastDoneReason = finalReason;
	          loopRecord.playbackReaderLifetimeMs = noteReaderLifetime();
	          updatePlaybackReaderStats({
	            playbackReaderLastDoneReason: finalReason,
	            playbackReaderLifetimeMs: loopRecord.playbackReaderLifetimeMs,
	          });
	          traceWisCameraBoundary("camera.media.playback_reader.done", {
	            functionName: "runPlaybackReader",
	            streamId: key,
	            generation: Number(token.generation || 0),
	            sessionId: cleanText(token.sessionId, ""),
	            playbackUrl: readerUrl,
	            reason: finalReason,
	            readerSeq,
	            playbackReaderLifetimeMs: loopRecord.playbackReaderLifetimeMs,
	            playbackChunksReceived: loopRecord.playbackChunksReceived,
	            playbackFramesParsed: loopRecord.playbackFramesParsed,
	            playbackFramesCommitted: loopRecord.playbackFramesCommitted,
	          });
	        }
	        readerActive = false;
        loopRecord.readerActive = false;
        syncLoopPerfActive();
        if (!restartRequestedUrl) streamEnded = true;
        const session = currentSession();
        if (session) {
          session.readerActive = false;
          session.streamEnded = streamEnded;
          session.playbackQueueLength = frameQueue.length;
          session.updatedAt = Date.now();
        }
        schedulePlaybackFrame("reader-finished");
      }
    }
  };
  startHealthTimer();
  try {
    let nextReaderUrl = playbackUrl;
    let nextReaderReason = "initial";
    while (isCurrent() && nextReaderUrl && !fellBackToImageSrc) {
      restartRequestedUrl = "";
      restartRequestedReason = "";
      await runPlaybackReader(nextReaderUrl, nextReaderReason);
      if (restartRequestedUrl && isCurrent() && !fellBackToImageSrc) {
        nextReaderUrl = restartRequestedUrl;
        nextReaderReason = restartRequestedReason || "restart";
        restartRequestedUrl = "";
        restartRequestedReason = "";
        continue;
      }
      break;
    }
  } finally {
    streamEnded = true;
    if (fellBackToImageSrc || !isCurrent()) {
      frameQueue.length = 0;
      clearDisplayTimer();
      cleanupPlaybackController(false);
      return;
    }
    schedulePlaybackFrame("stream-finally");
  }
}

export function formatWisCameraTimelineRange(range = null, mode = "live", locales = []) {
  const startMs = Number(range?.start_ms || 0);
  const endMs = Number(range?.end_ms || 0);
  if (!startMs || !endMs) return mode === "recorded" ? "No recordings detected" : "Waiting for retained frames";
  const start = new Date(startMs);
  const end = new Date(endMs);
  const sameDay = start.toDateString() === end.toDateString();
  const timeOptions = { hour: "2-digit", minute: "2-digit" };
  const startText = sameDay
    ? start.toLocaleTimeString(locales, timeOptions)
    : `${start.toLocaleDateString(locales, { month: "short", day: "numeric" })} ${start.toLocaleTimeString(locales, timeOptions)}`;
  const endText = sameDay
    ? end.toLocaleTimeString(locales, timeOptions)
    : `${end.toLocaleDateString(locales, { month: "short", day: "numeric" })} ${end.toLocaleTimeString(locales, timeOptions)}`;
  return `${startText} - ${endText}`;
}

const WIS_CAMERA_TOOL_ICON_PATHS = Object.freeze({
  play: ["M8 5v14l11-7z"],
  pause: ["M7 5h4v14H7z", "M15 5h4v14h-4z"],
  zoom: ["M10.5 5a5.5 5.5 0 0 1 4.35 8.86l4.15 4.14-1.5 1.5-4.14-4.15A5.5 5.5 0 1 1 10.5 5zm0 2a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z"],
  snapshot: ["M7 7l1.4-2h7.2L17 7h3v12H4V7h3zm5 3.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6z"],
  audio: ["M4 10v4h4l5 4V6l-5 4H4zm12.2-1.8a5 5 0 0 1 0 7.6l1.4 1.4a7 7 0 0 0 0-10.4l-1.4 1.4z"],
  muted: ["M4 10v4h4l5 4V6l-5 4H4zm12.3-.3 1.4-1.4 2.3 2.3 2.3-2.3 1.4 1.4-2.3 2.3 2.3 2.3-1.4 1.4-2.3-2.3-2.3 2.3-1.4-1.4 2.3-2.3-2.3-2.3z"],
  quality: ["M5 7h14v3H5V7zm0 5h10v3H5v-3zm0 5h6v3H5v-3z"],
  live: ["M12 5a7 7 0 1 1 0 14 7 7 0 0 1 0-14zm0 3.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6z"],
  recorded: ["M6 5h12v3H6V5zm-1 5h14v9H5v-9zm3 2v5h8v-5H8z"],
  config: ["M12 8.5a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7zm8 3.5-2.1-.7-.5-1.2 1-2-2.4-2.4-2 .9-1.2-.5L12 4H8.6l-.7 2.1-1.2.5-2-.9-2.4 2.4.9 2-.5 1.2L1 12v3.4l2.1.7.5 1.2-.9 2 2.4 2.4 2-.9 1.2.5.7 2.1H12l.7-2.1 1.2-.5 2 .9 2.4-2.4-.9-2 .5-1.2 2.1-.7V12z"],
  trace: ["M5 5h14v3H5V5zm0 5h14v3H5v-3zm0 5h9v3H5v-3zm12.6.2 1.4 1.4-4.2 4.2-2.4-2.4 1.4-1.4 1 1 2.8-2.8z"],
});

function appendWisCameraToolIcon(documentRef, button, iconName = "", label = "", iconOnly = true) {
  const cleanIcon = cleanText(iconName, "");
  const paths = WIS_CAMERA_TOOL_ICON_PATHS[cleanIcon];
  if (!paths || !documentRef?.createElementNS) {
    button.textContent = label;
    return;
  }
  const svg = documentRef.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.classList?.add?.("wis-camera-tool-icon");
  paths.forEach((pathData) => {
    const path = documentRef.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", pathData);
    svg.append(path);
  });
  button.append(svg);
  if (!button.dataset) button.dataset = {};
  button.dataset.icon = cleanIcon;
  if (label && !iconOnly) {
    const span = documentRef.createElement("span");
    span.className = "wis-camera-tool-label";
    span.textContent = label;
    button.append(span);
  }
}

function wisCameraControlTraceName(control = "") {
  const compact = cleanText(control, "button").toLowerCase().replace(/[^a-z0-9]+/g, "");
  return compact || "button";
}

function traceWisCameraToolButtonEvent(kind = "click", button = null, event = null, options = {}) {
  const control = cleanText(options.control || button?.dataset?.wisCameraControl, "button");
  const rect = button?.getBoundingClientRect?.();
  const documentRef = button?.ownerDocument || globalThis.document;
  const topElement = Number.isFinite(Number(event?.clientX)) && Number.isFinite(Number(event?.clientY))
    ? documentRef?.elementFromPoint?.(Number(event.clientX), Number(event.clientY))
    : null;
  traceWisCameraBoundary(`controls.${wisCameraControlTraceName(control)}.${cleanText(kind, "event")}`, {
    functionName: "createWisCameraToolButton",
    control,
    streamId: cleanText(options.streamId || button?.dataset?.wisCameraStreamId, ""),
    slot: cleanText(options.slot || button?.dataset?.wisCameraSlot, ""),
    action: cleanText(options.action || button?.dataset?.wisCameraAction, ""),
    disabled: Boolean(button?.disabled),
    ariaDisabled: cleanText(button?.getAttribute?.("aria-disabled"), ""),
    ariaPressed: cleanText(button?.getAttribute?.("aria-pressed"), ""),
    label: cleanText(button?.getAttribute?.("aria-label") || button?.textContent, ""),
    pointerType: cleanText(event?.pointerType, ""),
    clientX: Number(event?.clientX || 0),
    clientY: Number(event?.clientY || 0),
    buttonRect: rect ? {
      left: Math.round(Number(rect.left || 0)),
      top: Math.round(Number(rect.top || 0)),
      width: Math.round(Number(rect.width || 0)),
      height: Math.round(Number(rect.height || 0)),
    } : null,
    eventTarget: {
      tagName: cleanText(event?.target?.tagName, ""),
      className: cleanText(event?.target?.className, ""),
      control: cleanText(event?.target?.dataset?.wisCameraControl, ""),
    },
    elementFromPoint: topElement ? {
      tagName: cleanText(topElement.tagName, ""),
      className: cleanText(topElement.className, ""),
      control: cleanText(topElement.dataset?.wisCameraControl, ""),
    } : null,
  });
}

export function createWisCameraToolButton(documentRef, label, title, onClick, options = {}) {
  const button = documentRef.createElement("button");
  button.type = "button";
  button.className = `wis-camera-tool-button${options.active ? " active" : ""}`;
  if (options.icon) {
    button.className += " is-icon";
    if (options.iconOnly !== false) button.className += " is-icon-only";
    appendWisCameraToolIcon(documentRef, button, options.icon, label, options.iconOnly !== false);
  } else {
    button.textContent = label;
  }
  if (button.dataset) {
    if (options.control) button.dataset.wisCameraControl = cleanText(options.control, "");
    if (options.streamId) button.dataset.wisCameraStreamId = cleanText(options.streamId, "");
    if (options.slot) button.dataset.wisCameraSlot = cleanText(options.slot, "");
    if (options.action) button.dataset.wisCameraAction = cleanText(options.action, "");
  }
  button.title = title;
  button.setAttribute("aria-label", title);
  if (options.pressed !== undefined) button.setAttribute("aria-pressed", options.pressed ? "true" : "false");
  if (options.disabled) {
    button.disabled = true;
    button.setAttribute("aria-disabled", "true");
  }
  button.addEventListener("pointerdown", (event) => {
    traceWisCameraToolButtonEvent("pointerdown", button, event, options);
  });
  button.addEventListener("click", (event) => {
    traceWisCameraToolButtonEvent("click", button, event, options);
    event.preventDefault();
    event.stopPropagation();
    if (button.disabled) return;
    onClick?.(event);
  });
  return button;
}

export function renderWisCameraArtifactHeader({
  documentRef = globalThis.document,
  actionsElement = null,
  beforeElement = null,
  configButton = null,
  camera = null,
  slot = WIS_CAMERA_DEFAULT_SLOT,
  streamId = WIS_CAMERA_DEFAULT_SLOT,
  baseStreamId = WIS_CAMERA_DEFAULT_SLOT,
  isPush = false,
  zoom = null,
  notice = null,
  muted = true,
  audioAvailable = false,
  qualityMode = "primary",
  onConfigure = null,
  onToggleZoom = null,
  onCopySnapshot = null,
  onToggleAudio = null,
  onToggleQuality = null,
  controlsInTimeline = false,
} = {}) {
  if (!actionsElement || !documentRef) return null;
  let controls = actionsElement.querySelector(".wis-camera-header-controls");
  if (!camera) {
    controls?.remove();
    if (configButton) configButton.hidden = true;
    return null;
  }
  if (configButton) {
    configButton.hidden = true;
    configButton.dataset.wisCameraSlot = cleanText(slot, WIS_CAMERA_DEFAULT_SLOT);
  }
  if (!controls) {
    controls = documentRef.createElement("span");
    controls.className = "wis-camera-header-controls";
    const before = beforeElement || actionsElement.querySelector?.("[data-widget-control='minimize']") || actionsElement.firstElementChild;
    actionsElement.insertBefore(controls, before);
    ["pointerdown", "click", "dblclick", "wheel", "keydown"].forEach((type) => {
      controls.addEventListener(type, (event) => event.stopPropagation());
    });
  }
  const noticeEl = documentRef.createElement("span");
  const currentNotice = notice && typeof notice === "object" ? notice : null;
  noticeEl.className = `wis-camera-header-notice${currentNotice ? ` ${cleanText(currentNotice.tone, "info")}` : ""}`;
  noticeEl.textContent = cleanText(currentNotice?.message, "");
  const activeZoom = Boolean(zoom?.rect || zoom?.selecting);
  if (controlsInTimeline) {
    controls.replaceChildren(
      noticeEl,
      createWisCameraToolButton(documentRef, "Config", `Configure ${cleanText(slot, WIS_CAMERA_DEFAULT_SLOT)}`, () => onConfigure?.(camera), { icon: "config", control: "config" })
    );
    controls.dataset.wisCameraSlot = cleanText(slot, WIS_CAMERA_DEFAULT_SLOT);
    controls.dataset.wisCameraStreamId = cleanText(streamId, baseStreamId);
    controls.dataset.wisCameraBaseStreamId = cleanText(baseStreamId, streamId);
    return controls;
  }
  controls.replaceChildren(
    noticeEl,
    createWisCameraToolButton(documentRef, "Config", `Configure ${cleanText(slot, WIS_CAMERA_DEFAULT_SLOT)}`, () => onConfigure?.(camera)),
    createWisCameraToolButton(documentRef, activeZoom ? "Reset" : "Zoom", activeZoom ? "Reset zoom" : "Select zoom area", () => onToggleZoom?.(camera), { active: activeZoom, pressed: activeZoom }),
    createWisCameraToolButton(documentRef, "Snap", "Copy snapshot", () => onCopySnapshot?.(camera)),
    createWisCameraToolButton(documentRef, muted ? "Muted" : "Audio", audioAvailable ? (muted ? "Turn audio on" : "Mute audio") : "No audio available", () => onToggleAudio?.(camera), { disabled: !audioAvailable, active: audioAvailable && !muted, pressed: audioAvailable && !muted }),
    createWisCameraToolButton(documentRef, qualityMode === "extra" ? "Extra" : "Main", isPush ? "Toggle principal/extra stream quality" : "Quality toggle unavailable for this source", () => onToggleQuality?.(camera), { active: isPush, disabled: !isPush })
  );
  controls.dataset.wisCameraSlot = cleanText(slot, WIS_CAMERA_DEFAULT_SLOT);
  controls.dataset.wisCameraStreamId = cleanText(streamId, baseStreamId);
  controls.dataset.wisCameraBaseStreamId = cleanText(baseStreamId, streamId);
  return controls;
}

export function createWisFocusedCameraArtifact({
  id = "camera-dashboard",
  title = "CAM 1",
  slot = WIS_CAMERA_DEFAULT_SLOT,
  camera = null,
  cameraAccess = null,
  updatedAt = "",
  version = 1,
} = {}) {
  const cleanSlot = normalizeWisCameraSlot(slot, WIS_CAMERA_DEFAULT_SLOT);
  const cleanTitle = cleanText(title, cleanSlot.toUpperCase());
  const stamp = cleanText(updatedAt, nowIso());
  const state = {
    camera_focus: {
      schema: WIS_CAMERA_FOCUS_SCHEMA,
      layout: "single-camera",
      slot: cleanSlot,
      title: cleanTitle,
      updatedAt: stamp,
    },
    cameras: {},
  };
  if (cameraAccess && typeof cameraAccess === "object") state.cameraAccess = clone(cameraAccess);
  if (camera && typeof camera === "object") state.cameras[cleanSlot] = clone(camera);
  return {
    schema: WIS_SPACE_SCHEMA,
    id: cleanText(id, "camera-dashboard"),
    title: cleanTitle,
    version: Number.isFinite(Number(version)) ? Number(version) : 1,
    entryDocumentId: "main",
    updated_at: stamp,
    sandbox: {
      network: false,
      iframe: false,
      backend: false,
      externalScripts: false,
    },
    documents: [
      {
        id: "main",
        url: `wis://local/${cleanText(id, "camera-dashboard")}`,
        title: cleanTitle,
        updated_at: stamp,
        state,
        tree: {
          id: "doc",
          type: "document",
          role: "document",
          props: { className: "wis-camera-focus-document" },
          children: [
            {
              id: `${cleanSlot}-frame`,
              type: "section",
              role: "",
              props: { className: "wis-camera-focus-frame" },
              children: [
                {
                  id: `${cleanSlot.replace(/-/g, "")}-preview`,
                  type: WIS_CAMERA_NODE_TYPE,
                  role: "",
                  text: "",
                  props: {
                    slot: cleanSlot,
                    label: cleanTitle,
                  },
                  children: [],
                },
              ],
            },
          ],
        },
      },
    ],
  };
}

export function createWisCameraControllerContract({
  endpoints = WIS_CAMERA_PUSH_ENDPOINTS,
  controls = ["zoom", "snapshot", "audio", "quality", "timeline"],
  modes = ["live-last-10-minutes", "recorded-retained-range"],
} = {}) {
  return {
    schema: WIS_CAMERA_CONTROLLER_SCHEMA,
    artifactSchema: WIS_CAMERA_ARTIFACT_SCHEMA,
    nodeType: WIS_CAMERA_NODE_TYPE,
    focusSchema: WIS_CAMERA_FOCUS_SCHEMA,
    pushMediaMode: WIS_CAMERA_PUSH_MEDIA_MODE,
    controls: controls.map((control) => cleanText(control, "")).filter(Boolean),
    modes: modes.map((mode) => cleanText(mode, "")).filter(Boolean),
    endpoints: {
      ...WIS_CAMERA_PUSH_ENDPOINTS,
      ...(clone(endpoints || {}) || {}),
    },
  };
}
