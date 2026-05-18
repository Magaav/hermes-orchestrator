export const WIS_CAMERA_ARTIFACT_SCHEMA = "hermes.wasm_agent.wis.camera_artifact.v1";
export const WIS_CAMERA_FOCUS_SCHEMA = "hermes.wasm_agent.wis.camera_focus.v1";
export const WIS_CAMERA_CONTROLLER_SCHEMA = "hermes.wasm_agent.wis.camera_controller.v1";
export const WIS_CAMERA_CONFIGS_STORAGE_KEY = "wasmAgent.wisCameraConfigs.v1";
export const WIS_CAMERA_DEFAULT_SLOT = "cam-1";
export const WIS_CAMERA_NODE_TYPE = "webcam_placeholder";
export const WIS_CAMERA_PUSH_MEDIA_MODE = "rtmp-push-ingest";
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
const CAMERA_DEBUG = true;
const mediaWriters = new WeakMap();

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
    wisCameraTimeline: {
      streamId: "",
      mode: "live",
      day: "",
      frames: [],
      range: null,
      availableRange: null,
      loadedAt: 0,
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
  mediaWriters.set(image, nextOwner);
  image.dataset.wisMediaOwner = nextOwner.kind;
  image.dataset.wisMediaGeneration = String(nextOwner.generation);
  image.dataset.wisMediaStreamId = nextOwner.streamId;
  return true;
}

export function isMediaWriterCurrent(image, owner = {}) {
  const current = image ? mediaWriters.get(image) : null;
  const generation = Math.max(0, Math.round(Number(owner.generation || 0)));
  const kind = cleanText(owner.kind, "unknown");
  return Boolean(
    current
    && current.kind === kind
    && Number(current.generation || 0) === generation
    && image?.dataset?.wisMediaOwner === kind
    && image?.dataset?.wisMediaGeneration === String(generation)
  );
}

export function mediaWriterData(image) {
  return image ? mediaWriters.get(image) || null : null;
}

function waitForImageLoad(image) {
  return new Promise((resolve, reject) => {
    image.addEventListener("load", resolve, { once: true });
    image.addEventListener("error", reject, { once: true });
  });
}

export async function decodeAndSwapImage(image, sourceUrl, owner = {}, options = {}) {
  const env = options.env || globalThis;
  const url = cleanText(sourceUrl, "");
  if (!image || !url) return false;
  if (!isMediaWriterCurrent(image, owner)) {
    options.onStale?.();
    return false;
  }
  const ImageCtor = env.Image || globalThis.Image;
  if (!ImageCtor) return false;
  const preloader = new ImageCtor();
  preloader.decoding = "async";
  preloader.src = url;
  try {
    if (typeof preloader.decode === "function") await preloader.decode();
  } catch {
    if (!preloader.complete) await waitForImageLoad(preloader);
  }
  if (!isMediaWriterCurrent(image, owner)) {
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
  options.beforeSwap?.();
  image.src = url;
  options.onSwap?.();
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
  const recentSeekEvents = [];
  const recentDebugEvents = [];
  const lastDebugLogAt = new Map();
  let emergencyStopped = false;
  const removeTimelineListeners = [];
  const cleanupStack = [];
  const playbackClock = {
    mode: "live",
    anchorWallTimeMs: 0,
    anchorRecordingTimeMs: 0,
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
    abortPreviousLoads(reason);
    activeSeek = null;
    currentSegment = null;
    playbackClock.mode = "error";
  }

  function logCamera(type, detail = {}, options = {}) {
    if (!CAMERA_DEBUG) return contextForLog(detail);
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
    if (diagnostics) {
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

  function dispatchPlaybackPatch(reason = "", extra = {}) {
    if (typeof dispatchWisPatch !== "function") return;
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

  function setPlaybackMode(mode, detail = {}) {
    const nextMode = cleanText(mode, "live");
    if (playbackClock.mode === nextMode) return;
    playbackClock.mode = nextMode;
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
    playbackClock.anchorWallTimeMs = wisCameraMonotonicNow();
    playbackClock.anchorRecordingTimeMs = Number(targetTimeMs);
    playbackClock.targetTimeMs = Number(targetTimeMs);
    playbackClock.rate = Number.isFinite(Number(rate)) && Number(rate) > 0 ? Number(rate) : 1;
    playbackClock.generation = generation;
    logCamera("camera.clock.start", {
      ...detail,
      generation,
      timestampMs: targetTimeMs,
      rate: playbackClock.rate,
    });
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

  async function seekTo(timestampMs, options = {}) {
    const source = cleanText(options.source, "programmatic");
    const reason = cleanText(options.reason, "");
    const target = normalizeSeekTarget(timestampMs);
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
    if (!noteSeekForFuse(source, target, { reason })) return null;

    const generation = ++playbackGeneration;
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
    abortPreviousLoads("seek-start");
    if (typeof env.AbortController === "function") activeAbortController = new env.AbortController();
    setPlaybackMode("seeking", { source, reason, timestampMs: target, generation, skipPatch: true });

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
      setPlaybackMode("error", { source, reason, timestampMs: target, generation });
      activeSeek.status = "error";
      return null;
    }

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
    startPlaybackClock(target, 1, { generation, source, reason });
    startRenderLoop({ generation, source, reason });
    setPlaybackMode("recordedPlaying", { source, reason, timestampMs: target, generation, skipPatch: true });
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
    setPlaybackMode("live", { reason, skipPatch: true });
  }

  const api = {
    configure,
    cleanup,
    unmount: cleanup,
    seekTo,
    startRenderLoop,
    stopRenderLoop,
    syncTimelineFromPlayback,
    markFirstRecordedFrameDisplayed(frame = null, detail = {}) {
      const timestampMs = Number(detail.firstFrameTimeMs ?? frame?.timestamp_ms ?? frame?.timestampMs ?? playbackClock.targetTimeMs);
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

export function stopWisCameraPlaybackState(runtimeState = {}, streamId = "", options = {}) {
  const key = cleanText(streamId, "");
  if (!key) return;
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
  if (objectUrl) {
    try {
      globalThis.URL?.revokeObjectURL?.(objectUrl);
    } catch {
      // Object URL may already have been released.
    }
    playbackObjectUrlMap(runtimeState).delete(key);
  }
  if (!options.keepState) playbackStateMap(runtimeState).delete(key);
}

export function startWisCameraPlaybackSeek(runtimeState = {}, streamId = "", frame = null, options = {}) {
  const key = cleanText(streamId, "");
  if (!key || !frame?.id) return null;
  const states = playbackStateMap(runtimeState);
  const existing = states.get(key);
  if (!options.restart && wisCameraTimelineFramePlaybackKey(existing?.frame) === wisCameraTimelineFramePlaybackKey(frame)) {
    return existing;
  }
  const generations = playbackGenerationMap(runtimeState);
  const requestedGeneration = Number(options.generation ?? options.playbackGeneration ?? options.seekToken);
  const generation = Number.isFinite(requestedGeneration) && requestedGeneration > 0
    ? Math.round(requestedGeneration)
    : Number(generations.get(key) || 0) + 1;
  generations.set(key, generation);
  stopWisCameraPlaybackState(runtimeState, key, { keepState: true });
  const nowMs = Number.isFinite(Number(options.nowMs)) ? Number(options.nowMs) : wisCameraMonotonicNow();
  const recordingTimeMs = wisCameraTimelinePlaybackStartMs(frame, timelineFrameTimestampMs(frame) || Date.now());
  const session = {
    id: `${key}-${cleanText(frame.id, "frame")}-${generation}`,
    mode: "recorded",
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
    anchorWallTimeMs: nowMs,
    anchorRecordingTimeMs: recordingTimeMs,
    recordedStartWallTime: recordingTimeMs,
    playbackStartedAtMonotonic: nowMs,
    rate: 1,
    playbackRate: 1,
    currentWallTime: recordingTimeMs,
    clockPaused: true,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    explicitSeek: Boolean(options.explicitSeek),
  };
  states.set(key, session);
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
  session.state = "buffering";
  session.status = "buffering";
  session.currentWallTime = wisCameraPlaybackClockMs(session, nowMs) || session.currentWallTime;
  session.clockPaused = true;
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
  session.renderedFrame = renderedFrame;
  session.lastDisplayedFrameTimeMs = timestampMs;
  session.lastDisplayedAtMonotonic = nowMs;
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
  session.clockPaused = Boolean(options.paused);
  session.state = options.state || "recordedPlaying";
  session.status = options.status || "recordedPlaying";
  session.updatedAt = Date.now();
  return session;
}

export function setWisCameraPlaybackEnded(runtimeState = {}, streamId = "", options = {}) {
  const key = cleanText(streamId, "");
  if (!wisCameraPlaybackMatches(runtimeState, key, options)) return null;
  const session = wisCameraPlaybackState(runtimeState, key);
  const nowMs = Number.isFinite(Number(options.nowMs)) ? Number(options.nowMs) : wisCameraMonotonicNow();
  session.currentWallTime = wisCameraPlaybackClockMs(session, nowMs) || session.currentWallTime;
  session.clockPaused = true;
  session.state = options.state || "paused";
  session.status = options.status || "ended";
  session.updatedAt = Date.now();
  return session;
}

export function setWisCameraPlaybackError(runtimeState = {}, streamId = "", error = "", options = {}) {
  const key = cleanText(streamId, "");
  if (!wisCameraPlaybackMatches(runtimeState, key, options)) return null;
  const session = wisCameraPlaybackState(runtimeState, key);
  session.currentWallTime = wisCameraPlaybackClockMs(session) || session.currentWallTime;
  session.clockPaused = true;
  session.state = "error";
  session.status = "error";
  session.error = cleanText(error, "Playback failed");
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
  return !(
    timeline?.streamId === key
    && timeline?.mode === timelineMode
    && (timeline?.loading || (timeline?.loadedAt && Number(nowMs) - Number(timeline.loadedAt) < Number(ttlMs || 0)))
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
  if (["seeking", "buffering", "loading"].includes(session.status)) return `Syncing recording from ${wisCameraTimelineFrameLabel(session.frame || labelFrame, locales)}`;
  if (session.status === "gap") return `No recording at ${wisCameraTimelineFrameLabel(labelFrame, locales)}`;
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
  const timestampMs = Number(image?.dataset?.wisPlaybackFrameMs || 0);
  const frameId = cleanText(image?.dataset?.wisPlaybackFrameId, "");
  if (!Number.isFinite(timestampMs) || timestampMs <= 0) return fallbackFrame;
  return {
    ...(fallbackFrame || {}),
    id: frameId || cleanText(fallbackFrame?.id, ""),
    timestamp_ms: timestampMs,
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
      options.onMediaEvent?.(event, payload);
      options.recordEvent?.(event, payload);
    } catch {
      // Diagnostics should never affect playback.
    }
    if (CAMERA_DEBUG && options.diagnostics !== false) {
      try {
        const method = event.includes("error") || event.includes("stale") ? "warn" : "debug";
        env.console?.[method]?.("[camera]", event, payload);
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
  const controller = new env.AbortController();
  playbackControllerMap(runtimeState).set(key, controller);
  let fellBackToImageSrc = false;
  let playbackFps = 15;
  try {
    playbackFps = clamp(Number(new URL(playbackUrl, env.location?.href || "http://localhost/").searchParams.get("fps") || 15), 1, 15);
  } catch {
    playbackFps = 15;
  }
  const targetFrameMs = 1000 / playbackFps;
  const maxBufferFrames = Math.max(12, Math.round(playbackFps * 2));
  const frameQueue = [];
  let displayTimer = 0;
  let displayInProgress = false;
  let streamEnded = false;
  let displaySeq = 0;
  const isCurrent = () => (
    !controller.signal.aborted
    && image.isConnected !== false
    && wisCameraPlaybackMatches(runtimeState, key, token)
    && isMediaWriterCurrent(image, mediaOwner)
  );
  const clearDisplayTimer = () => {
    if (!displayTimer) return;
    try {
      env.clearTimeout?.(displayTimer);
    } catch {
      // Timer may belong to another runtime.
    }
    if (playbackTimerMap(runtimeState).get(key) === displayTimer) playbackTimerMap(runtimeState).delete(key);
    displayTimer = 0;
  };
  const cleanupPlaybackController = (endSession = false) => {
    clearDisplayTimer();
    if (playbackControllerMap(runtimeState).get(key) === controller) playbackControllerMap(runtimeState).delete(key);
    if (endSession && !fellBackToImageSrc) {
      const session = setWisCameraPlaybackEnded(runtimeState, key, token);
      if (session) options.onEnded?.(session);
    }
  };
  const finishPlaybackStreamWhenDrained = () => {
    if (!streamEnded || displayTimer || frameQueue.length) return;
    cleanupPlaybackController(isCurrent());
  };
  const displayPlaybackFrame = async (packet) => {
    if (!isCurrent()) return false;
    const seq = ++displaySeq;
    const BlobCtor = env.Blob || globalThis.Blob;
    const URLApi = env.URL || globalThis.URL;
    if (!BlobCtor || !URLApi?.createObjectURL) return false;
    const objectUrl = URLApi.createObjectURL(new BlobCtor([packet.frameBytes], { type: packet.contentType || "image/jpeg" }));
    const previousUrl = playbackObjectUrlMap(runtimeState).get(key);
    const displayedFrame = {
      ...(baseFrame || {}),
      id: packet.frameId || cleanText(baseFrame?.id, ""),
      timestamp_ms: Number(packet.timestampMs || wisCameraTimelinePlaybackStartMs(baseFrame)),
    };
    delete displayedFrame.seek_target_ms;
    delete displayedFrame.seekTargetMs;
    delete displayedFrame.snapped_timestamp_ms;
    delete displayedFrame.snappedTimestampMs;
    const clockTimeMs = wisCameraPlaybackClockMs(wisCameraPlaybackState(runtimeState, key));
    const swapped = await decodeAndSwapImage(image, objectUrl, mediaOwner, {
      env,
      revokeOnStale: true,
      onStale: () => emitMediaEvent("camera.media.stale_writer.ignored", {
        frameTimestampMs: displayedFrame.timestamp_ms,
        clockTimeMs,
      }, { sampleMs: 1000 }),
      beforeSwap: () => {
        image.dataset.wisPlaybackStream = "1";
        image.dataset.wisPlaybackFrameMs = String(displayedFrame.timestamp_ms);
        image.dataset.wisPlaybackFrameId = displayedFrame.id;
        playbackObjectUrlMap(runtimeState).set(key, objectUrl);
      },
      onSwap: () => emitMediaEvent("camera.media.src.swap", {
        frameTimestampMs: displayedFrame.timestamp_ms,
        clockTimeMs,
        driftMs: Number(displayedFrame.timestamp_ms || 0) - Number(clockTimeMs || 0),
        queueLength: frameQueue.length,
      }, { sampleMs: 1000 }),
    });
    if (!swapped || !isCurrent() || seq !== displaySeq) {
      if (playbackObjectUrlMap(runtimeState).get(key) === objectUrl) playbackObjectUrlMap(runtimeState).delete(key);
      try {
        URLApi.revokeObjectURL?.(objectUrl);
      } catch {
        // Best effort cleanup for stale decoded frames.
      }
      return false;
    }
    const session = setWisCameraPlaybackFrame(runtimeState, key, displayedFrame, {
      ...token,
      status: "recordedPlaying",
      state: "recordedPlaying",
      paused: false,
      updateClockAnchor: false,
    });
    if (session) options.onFrameDisplayed?.(session, displayedFrame);
    emitMediaEvent("camera.media.playback_frame.displayed.sample", {
      frameTimestampMs: displayedFrame.timestamp_ms,
      clockTimeMs,
      driftMs: Number(displayedFrame.timestamp_ms || 0) - Number(clockTimeMs || 0),
      queueLength: frameQueue.length,
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
  const schedulePlaybackFrame = () => {
    if (displayTimer || displayInProgress || !isCurrent()) return;
    if (!frameQueue.length) {
      finishPlaybackStreamWhenDrained();
      return;
    }
    const clockTimeMs = wisCameraPlaybackClockMs(wisCameraPlaybackState(runtimeState, key));
    while (frameQueue.length > 1 && Number(frameQueue[0]?.timestampMs || 0) < clockTimeMs - 500) {
      const dropped = frameQueue.shift();
      emitMediaEvent("camera.media.playback_frame.dropped_stale.sample", {
        frameTimestampMs: Number(dropped?.timestampMs || 0),
        clockTimeMs,
        driftMs: Number(dropped?.timestampMs || 0) - Number(clockTimeMs || 0),
        queueLength: frameQueue.length,
      }, { sampleMs: 1000 });
    }
    const next = frameQueue[0];
    const nextTimestampMs = Number(next?.timestampMs || 0);
    const delayMs = nextTimestampMs > clockTimeMs + 150
      ? Math.min(targetFrameMs, Math.max(25, nextTimestampMs - clockTimeMs - 100))
      : 0;
    displayTimer = env.setTimeout?.(() => {
      displayTimer = 0;
      playbackTimerMap(runtimeState).delete(key);
      if (!isCurrent()) {
        frameQueue.length = 0;
        cleanupPlaybackController(false);
        return;
      }
      const packet = delayMs > 0 ? null : frameQueue.shift();
      if (!packet) {
        schedulePlaybackFrame();
        return;
      }
      displayInProgress = true;
      void displayPlaybackFrame(packet).finally(() => {
        displayInProgress = false;
        schedulePlaybackFrame();
      });
    }, delayMs);
    if (displayTimer) playbackTimerMap(runtimeState).set(key, displayTimer);
  };
  const enqueuePlaybackFrame = (packet) => {
    if (!isCurrent()) return;
    frameQueue.push(packet);
    if (frameQueue.length > maxBufferFrames) frameQueue.splice(0, frameQueue.length - maxBufferFrames);
    schedulePlaybackFrame();
  };
  try {
    emitMediaEvent("camera.media.playback_stream.start", {
      playbackUrl,
    });
    const response = await env.fetch(playbackUrl, { cache: "no-store", signal: controller.signal });
    if (!response.ok || !response.body?.getReader) throw new Error(`Playback stream unavailable (${response.status})`);
    const contentType = response.headers.get("Content-Type") || "";
    const boundary = contentType.match(/boundary="?([^";]+)"?/i)?.[1];
    if (!boundary) throw new Error("Playback stream boundary missing");
    const TextEncoderCtor = env.TextEncoder || globalThis.TextEncoder;
    const TextDecoderCtor = env.TextDecoder || globalThis.TextDecoder;
    if (!TextEncoderCtor || !TextDecoderCtor) throw new Error("Playback stream text codec unavailable");
    const boundaryBytes = new TextEncoderCtor().encode(`--${boundary}`);
    const headerEndBytes = new Uint8Array([13, 10, 13, 10]);
    const crlfBytes = new Uint8Array([13, 10]);
    const decoder = new TextDecoderCtor("utf-8");
    const reader = response.body.getReader();
    let buffer = new Uint8Array();
    let needBoundary = true;
    let currentHeaders = null;
    let sawFirstPacket = false;
    while (isCurrent()) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer = appendBytes(buffer, value);
      while (buffer.length && isCurrent()) {
        if (needBoundary) {
          const boundaryIndex = indexOfBytes(buffer, boundaryBytes);
          if (boundaryIndex < 0) {
            buffer = buffer.slice(Math.max(0, buffer.length - boundaryBytes.length - 4));
            break;
          }
          buffer = buffer.slice(boundaryIndex + boundaryBytes.length);
          if (buffer[0] === 45 && buffer[1] === 45) return;
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
        if (!sawFirstPacket) {
          sawFirstPacket = true;
          emitMediaEvent("camera.media.playback_stream.first_packet", {
            frameTimestampMs: Number.isFinite(timestampMs) && timestampMs > 0 ? timestampMs : wisCameraTimelinePlaybackStartMs(baseFrame),
          });
        }
        enqueuePlaybackFrame({
          frameBytes,
          contentType: currentHeaders["content-type"] || "image/jpeg",
          timestampMs: Number.isFinite(timestampMs) && timestampMs > 0 ? timestampMs : wisCameraTimelinePlaybackStartMs(baseFrame),
          frameId,
        });
        currentHeaders = null;
        needBoundary = true;
      }
    }
  } catch (error) {
    if (error?.name !== "AbortError" && isCurrent()) {
      fellBackToImageSrc = true;
      setWisCameraPlaybackError(runtimeState, key, error.message || String(error), token);
      options.onError?.(error);
      options.fallbackToImageSrc?.();
    }
  } finally {
    streamEnded = true;
    if (fellBackToImageSrc || controller.signal.aborted || !isCurrent()) {
      frameQueue.length = 0;
      clearDisplayTimer();
      cleanupPlaybackController(false);
      return;
    }
    if (!frameQueue.length && !displayTimer) cleanupPlaybackController(true);
    else schedulePlaybackFrame();
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

export function createWisCameraToolButton(documentRef, label, title, onClick, options = {}) {
  const button = documentRef.createElement("button");
  button.type = "button";
  button.className = `wis-camera-tool-button${options.active ? " active" : ""}`;
  button.textContent = label;
  button.title = title;
  button.setAttribute("aria-label", title);
  if (options.pressed !== undefined) button.setAttribute("aria-pressed", options.pressed ? "true" : "false");
  if (options.disabled) {
    button.disabled = true;
    button.setAttribute("aria-disabled", "true");
  }
  button.addEventListener("click", (event) => {
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
