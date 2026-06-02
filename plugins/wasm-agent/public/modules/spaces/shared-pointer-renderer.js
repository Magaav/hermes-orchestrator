export const SHARED_POINTER_RENDER_DEFAULTS = Object.freeze({
  historyLimit: 28,
  historyMaxAgeMs: 420,
  historyMinDistancePx: 1.25,
  historyMinIntervalMs: 8,
  smoothingMs: 18,
  fastSmoothingMs: 10,
  fastDistancePx: 72,
  snapDistancePx: 1200,
  settlePx: 0.18,
  maxSpeedPxPerSecond: 24000,
  replayLowLatencyMinMs: 16,
  replayLowLatencyMaxMs: 40,
  replayLowLatencyCatchup: 0.78,
  replayStableMinMs: 32,
  replayStableMaxMs: 72,
  replayStableCatchup: 1.35,
  replayDroppedFrameCooldownMs: 420,
  replayHealthyMinFps: 28,
  predictionMaxLeadMs: 22,
  predictionMaxDistancePx: 44,
  predictionStaleMs: 140,
  realtimeSampleLimit: 32,
  realtimeBufferLimit: 64,
  realtimeBufferDelayMs: 12,
  realtimeMaxAgeMs: 240,
  realtimePredictionMaxMs: 30,
  realtimePredictionMaxDistancePx: 56,
  realtimeStaleMs: 120,
  realtimeClockOffsetAlpha: 0.18,
  realtimeClockOffsetMaxAbsMs: 24 * 60 * 60 * 1000,
});

export const SHARED_POINTER_BINARY_MAGIC = 0x42504157; // "WAPB", little-endian.
export const SHARED_POINTER_BINARY_VERSION = 1;
export const SHARED_POINTER_BINARY_TYPE_MOVE = 1;
export const SHARED_POINTER_BINARY_HEADER_BYTES = 36;
export const SHARED_POINTER_BINARY_SAMPLE_BYTES = 10;

function finiteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function clampNumber(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

export function snapSharedPointerPixel(value, devicePixelRatio = 1) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  const dpr = Math.max(1, Number(devicePixelRatio) || 1);
  return Math.round(number * dpr) / dpr;
}

export function pushSharedPointerSample(samples, sample, options = {}) {
  const target = Array.isArray(samples) ? samples : [];
  const limit = Math.max(1, Number(options.limit || SHARED_POINTER_RENDER_DEFAULTS.historyLimit));
  const at = Number(sample?.at);
  const x = Number(sample?.x);
  const y = Number(sample?.y);
  if (!Number.isFinite(at) || !Number.isFinite(x) || !Number.isFinite(y)) return target;
  const last = target[target.length - 1] || null;
  const minDistance = Math.max(0, Number(options.minDistancePx ?? SHARED_POINTER_RENDER_DEFAULTS.historyMinDistancePx));
  const minInterval = Math.max(0, Number(options.minIntervalMs ?? SHARED_POINTER_RENDER_DEFAULTS.historyMinIntervalMs));
  if (
    last
    && (
      at - Number(last.at || 0) < minInterval
      || Math.hypot(x - Number(last.x || 0), y - Number(last.y || 0)) < minDistance
    )
  ) {
    return target;
  }
  target.push({ x, y, at });
  if (target.length > limit) target.splice(0, target.length - limit);
  return target;
}

export function pruneSharedPointerSamples(samples, nowMs, options = {}) {
  if (!Array.isArray(samples)) return [];
  const limit = Math.max(1, Number(options.limit || SHARED_POINTER_RENDER_DEFAULTS.historyLimit));
  const maxAge = Math.max(1, Number(options.maxAgeMs || SHARED_POINTER_RENDER_DEFAULTS.historyMaxAgeMs));
  const now = Number(nowMs);
  const fresh = samples.filter((sample) => Number.isFinite(Number(sample?.at)) && now - Number(sample.at) <= maxAge);
  return fresh.slice(-limit);
}

export function smoothSharedPointerPosition(current, target, dtMs, options = {}) {
  const fromX = Number(current?.x);
  const fromY = Number(current?.y);
  const toX = Number(target?.x);
  const toY = Number(target?.y);
  if (![fromX, fromY, toX, toY].every(Number.isFinite)) {
    return { x: Number.isFinite(toX) ? toX : 0, y: Number.isFinite(toY) ? toY : 0, mode: "reset", snapped: true };
  }
  const dt = Math.max(0, Math.min(96, Number(dtMs) || 0));
  const dx = toX - fromX;
  const dy = toY - fromY;
  const distance = Math.hypot(dx, dy);
  const settle = Math.max(0, Number(options.settlePx ?? SHARED_POINTER_RENDER_DEFAULTS.settlePx));
  if (distance <= settle) return { x: toX, y: toY, mode: "settled", snapped: false };
  const snapDistance = Math.max(1, Number(options.snapDistancePx ?? SHARED_POINTER_RENDER_DEFAULTS.snapDistancePx));
  if (distance >= snapDistance) return { x: toX, y: toY, mode: "snap", snapped: true };
  const fastDistance = Math.max(1, Number(options.fastDistancePx ?? SHARED_POINTER_RENDER_DEFAULTS.fastDistancePx));
  const smoothing = distance >= fastDistance
    ? Math.max(1, Number(options.fastSmoothingMs ?? SHARED_POINTER_RENDER_DEFAULTS.fastSmoothingMs))
    : Math.max(1, Number(options.smoothingMs ?? SHARED_POINTER_RENDER_DEFAULTS.smoothingMs));
  const alpha = 1 - Math.exp(-dt / smoothing);
  let stepX = dx * alpha;
  let stepY = dy * alpha;
  const maxSpeed = Math.max(1, Number(options.maxSpeedPxPerSecond ?? SHARED_POINTER_RENDER_DEFAULTS.maxSpeedPxPerSecond));
  const maxStep = maxSpeed * (dt / 1000);
  const stepDistance = Math.hypot(stepX, stepY);
  if (maxStep > 0 && stepDistance > maxStep) {
    const scale = maxStep / stepDistance;
    stepX *= scale;
    stepY *= scale;
  }
  return {
    x: fromX + stepX,
    y: fromY + stepY,
    mode: distance >= fastDistance ? "fast" : "smooth",
    snapped: false,
  };
}

export function adaptiveSharedPointerReplayDuration(arrivalIntervalMs, frame = {}, options = {}) {
  const interval = Math.max(1, finiteNumber(arrivalIntervalMs, 1));
  const fps = finiteNumber(frame.fps, 0);
  const droppedAge = finiteNumber(frame.droppedFrameAgeMs, Number.POSITIVE_INFINITY);
  const minHealthyFps = Math.max(1, finiteNumber(options.healthyMinFps, SHARED_POINTER_RENDER_DEFAULTS.replayHealthyMinFps));
  const cooldownMs = Math.max(0, finiteNumber(options.droppedFrameCooldownMs, SHARED_POINTER_RENDER_DEFAULTS.replayDroppedFrameCooldownMs));
  const stable = (fps > 0 && fps < minHealthyFps) || droppedAge < cooldownMs;
  const minMs = stable
    ? Math.max(1, finiteNumber(options.stableMinMs, SHARED_POINTER_RENDER_DEFAULTS.replayStableMinMs))
    : Math.max(1, finiteNumber(options.lowLatencyMinMs, SHARED_POINTER_RENDER_DEFAULTS.replayLowLatencyMinMs));
  const maxMs = stable
    ? Math.max(minMs, finiteNumber(options.stableMaxMs, SHARED_POINTER_RENDER_DEFAULTS.replayStableMaxMs))
    : Math.max(minMs, finiteNumber(options.lowLatencyMaxMs, SHARED_POINTER_RENDER_DEFAULTS.replayLowLatencyMaxMs));
  const catchup = stable
    ? Math.max(0.1, finiteNumber(options.stableCatchup, SHARED_POINTER_RENDER_DEFAULTS.replayStableCatchup))
    : Math.max(0.1, finiteNumber(options.lowLatencyCatchup, SHARED_POINTER_RENDER_DEFAULTS.replayLowLatencyCatchup));
  return {
    durationMs: clampNumber(interval * catchup, minMs, maxMs),
    mode: stable ? "stable" : "low-latency",
  };
}

export function predictSharedPointerPosition(point, velocity, options = {}) {
  const x = Number(point?.x);
  const y = Number(point?.y);
  const vx = Number(velocity?.x ?? velocity?.vx ?? 0);
  const vy = Number(velocity?.y ?? velocity?.vy ?? 0);
  if (![x, y, vx, vy].every(Number.isFinite)) {
    return { x: Number.isFinite(x) ? x : 0, y: Number.isFinite(y) ? y : 0, leadMs: 0, distancePx: 0, predicted: false };
  }
  const staleMs = Math.max(1, finiteNumber(options.staleMs, SHARED_POINTER_RENDER_DEFAULTS.predictionStaleMs));
  const targetAgeMs = clampNumber(finiteNumber(options.targetAgeMs, 0), 0, staleMs);
  const leadCeiling = Math.max(0, finiteNumber(options.maxLeadMs, SHARED_POINTER_RENDER_DEFAULTS.predictionMaxLeadMs));
  const leadMs = leadCeiling * (1 - targetAgeMs / staleMs);
  if (leadMs <= 0) return { x, y, leadMs: 0, distancePx: 0, predicted: false };
  let dx = vx * leadMs;
  let dy = vy * leadMs;
  const maxDistance = Math.max(0, finiteNumber(options.maxDistancePx, SHARED_POINTER_RENDER_DEFAULTS.predictionMaxDistancePx));
  const distance = Math.hypot(dx, dy);
  if (maxDistance > 0 && distance > maxDistance) {
    const scale = maxDistance / distance;
    dx *= scale;
    dy *= scale;
  }
  const projectedDistance = Math.hypot(dx, dy);
  return {
    x: x + dx,
    y: y + dy,
    leadMs,
    distancePx: projectedDistance,
    predicted: projectedDistance > 0.01,
  };
}

function roundRealtimeValue(value, precision = 10) {
  return Math.round(value * precision) / precision;
}

export function hashSharedPointerString(value = "") {
  let hash = 0x811c9dc5;
  const text = String(value ?? "");
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index) & 0xff;
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash >>> 0;
}

export function numericSharedPointerId(value = "") {
  const number = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(number) && number >= 0 && number <= 0xffffffff
    ? number >>> 0
    : hashSharedPointerString(value);
}

export function encodeSharedPointerRealtimeSamples(samples = [], sentPerfMs = 0, options = {}) {
  if (!Array.isArray(samples) || !samples.length) return [];
  const limit = Math.max(1, finiteNumber(options.limit, SHARED_POINTER_RENDER_DEFAULTS.realtimeSampleLimit));
  const clean = samples
    .map((sample) => ({
      x: Number(sample?.x),
      y: Number(sample?.y),
      at: Number(sample?.at),
    }))
    .filter((sample) => [sample.x, sample.y, sample.at].every(Number.isFinite))
    .slice(-limit);
  const fallbackSentAt = clean.length ? clean[clean.length - 1].at : 0;
  const sentAt = Number.isFinite(Number(sentPerfMs)) ? Number(sentPerfMs) : fallbackSentAt;
  return clean.map((sample) => [
    roundRealtimeValue(sample.at - sentAt, 10),
    roundRealtimeValue(sample.x, 100),
    roundRealtimeValue(sample.y, 100),
  ]);
}

export function encodeSharedPointerBinaryPacket(packet = {}, options = {}) {
  const sentPerfMs = finiteNumber(packet.sentPerfMs ?? packet.sent_perf_ms, 0);
  const sentEpochMs = finiteNumber(packet.sentEpochMs ?? packet.sent_at_ms, 0);
  const samples = (Array.isArray(packet.samples) ? packet.samples : [])
    .map((sample) => ({
      x: Number(sample?.x),
      y: Number(sample?.y),
      at: Number(sample?.at),
    }))
    .filter((sample) => [sample.x, sample.y, sample.at].every(Number.isFinite))
    .slice(-Math.max(1, finiteNumber(options.limit, SHARED_POINTER_RENDER_DEFAULTS.realtimeSampleLimit)));
  const count = Math.min(255, samples.length);
  if (!count) return null;
  const buffer = new ArrayBuffer(SHARED_POINTER_BINARY_HEADER_BYTES + count * SHARED_POINTER_BINARY_SAMPLE_BYTES);
  const view = new DataView(buffer);
  view.setUint32(0, SHARED_POINTER_BINARY_MAGIC, true);
  view.setUint8(4, SHARED_POINTER_BINARY_VERSION);
  view.setUint8(5, SHARED_POINTER_BINARY_TYPE_MOVE);
  view.setUint8(6, Number(packet.flags || 0) & 0xff);
  view.setUint8(7, count);
  view.setUint32(8, numericSharedPointerId(packet.userId ?? packet.user_id ?? ""), true);
  view.setUint32(12, hashSharedPointerString(packet.deviceId ?? packet.device_id ?? ""), true);
  view.setUint32(16, finiteNumber(packet.seq, 0) >>> 0, true);
  view.setFloat64(20, sentPerfMs, true);
  view.setFloat64(28, sentEpochMs, true);
  for (let index = 0; index < count; index += 1) {
    const sample = samples[index];
    const offset = SHARED_POINTER_BINARY_HEADER_BYTES + index * SHARED_POINTER_BINARY_SAMPLE_BYTES;
    view.setInt16(offset, clampNumber(Math.round((sample.at - sentPerfMs) * 10), -32768, 32767), true);
    view.setFloat32(offset + 2, sample.x, true);
    view.setFloat32(offset + 6, sample.y, true);
  }
  return buffer;
}

export function decodeSharedPointerBinaryPacket(data, options = {}) {
  const buffer = data instanceof ArrayBuffer
    ? data
    : ArrayBuffer.isView(data)
      ? data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength)
      : null;
  if (!buffer || buffer.byteLength < SHARED_POINTER_BINARY_HEADER_BYTES) return null;
  const view = new DataView(buffer);
  if (view.getUint32(0, true) !== SHARED_POINTER_BINARY_MAGIC) return null;
  const version = view.getUint8(4);
  const type = view.getUint8(5);
  const flags = view.getUint8(6);
  const count = view.getUint8(7);
  if (version !== SHARED_POINTER_BINARY_VERSION || type !== SHARED_POINTER_BINARY_TYPE_MOVE) return null;
  if (buffer.byteLength !== SHARED_POINTER_BINARY_HEADER_BYTES + count * SHARED_POINTER_BINARY_SAMPLE_BYTES) return null;
  const sentPerfMs = view.getFloat64(20, true);
  const sentEpochMs = view.getFloat64(28, true);
  const receivedAt = Number(options.receivedAtMs);
  const receiverEpochMs = Number(options.receiverEpochMs);
  const previousOffset = finiteNumber(options.previousClockOffsetMs, 0);
  const clockOffsetMs = estimateSharedPointerClockOffset({
    senderEpochMs: sentEpochMs,
    senderPerfMs: sentPerfMs,
    receiverEpochMs,
    receiverPerfMs: receivedAt,
  }, previousOffset, options);
  const fallbackBaseMs = Number.isFinite(receivedAt) && Number.isFinite(receiverEpochMs) && Number.isFinite(sentEpochMs)
    ? receivedAt - Math.max(0, receiverEpochMs - sentEpochMs)
    : receivedAt;
  const baseAt = sentPerfMs + clockOffsetMs;
  const maxFuture = Math.max(0, finiteNumber(options.maxFutureMs, 60));
  const maxPast = Math.max(1, finiteNumber(options.maxPastMs, 2000));
  const samples = [];
  for (let index = 0; index < count; index += 1) {
    const offset = SHARED_POINTER_BINARY_HEADER_BYTES + index * SHARED_POINTER_BINARY_SAMPLE_BYTES;
    const deltaMs = view.getInt16(offset, true) / 10;
    const x = view.getFloat32(offset + 2, true);
    const y = view.getFloat32(offset + 6, true);
    let at = baseAt + deltaMs;
    if (Number.isFinite(receivedAt) && (at > receivedAt + maxFuture || at < receivedAt - maxPast)) {
      at = fallbackBaseMs + deltaMs;
    }
    samples.push({ x, y, at });
  }
  return {
    version,
    type,
    flags,
    count,
    userId: view.getUint32(8, true),
    deviceHash: view.getUint32(12, true),
    seq: view.getUint32(16, true),
    sentPerfMs,
    sentEpochMs,
    clockOffsetMs,
    byteLength: buffer.byteLength,
    samples,
  };
}

export function decodeSharedPointerRealtimeSamples(compact = [], sentPerfMs = 0, receiverOffsetMs = 0, options = {}) {
  if (!Array.isArray(compact) || !compact.length) return [];
  const limit = Math.max(1, finiteNumber(options.limit, SHARED_POINTER_RENDER_DEFAULTS.realtimeSampleLimit));
  const baseAt = finiteNumber(sentPerfMs, 0) + finiteNumber(receiverOffsetMs, 0);
  const fallbackBase = finiteNumber(options.fallbackBaseMs, baseAt);
  const receivedAt = Number(options.receivedAtMs);
  const maxFuture = Math.max(0, finiteNumber(options.maxFutureMs, 60));
  const maxPast = Math.max(1, finiteNumber(options.maxPastMs, 2000));
  return compact.slice(-limit).map((entry) => {
    const delta = Array.isArray(entry) ? Number(entry[0]) : Number(entry?.dt ?? entry?.delta_ms ?? entry?.deltaMs ?? 0);
    const x = Array.isArray(entry) ? Number(entry[1]) : Number(entry?.x);
    const y = Array.isArray(entry) ? Number(entry[2]) : Number(entry?.y);
    let at = baseAt + delta;
    if (Number.isFinite(receivedAt) && (at > receivedAt + maxFuture || at < receivedAt - maxPast)) {
      at = fallbackBase + delta;
    }
    return { x, y, at };
  }).filter((sample) => [sample.x, sample.y, sample.at].every(Number.isFinite));
}

export function appendSharedPointerRealtimeSamples(buffer, samples = [], options = {}) {
  const target = Array.isArray(buffer) ? buffer : [];
  const limit = Math.max(1, finiteNumber(options.limit, SHARED_POINTER_RENDER_DEFAULTS.realtimeBufferLimit));
  const maxAge = Math.max(1, finiteNumber(options.maxAgeMs, SHARED_POINTER_RENDER_DEFAULTS.realtimeMaxAgeMs));
  const now = Number(options.nowMs);
  const cutoff = Number.isFinite(now) ? now - maxAge : Number.NEGATIVE_INFINITY;
  let dropped = 0;
  for (const sample of Array.isArray(samples) ? samples : []) {
    const x = Number(sample?.x);
    const y = Number(sample?.y);
    const at = Number(sample?.at);
    if (![x, y, at].every(Number.isFinite) || at < cutoff) {
      dropped += 1;
      continue;
    }
    target.push({ x, y, at });
  }
  target.sort((first, second) => first.at - second.at);
  for (let index = target.length - 1; index > 0; index -= 1) {
    const current = target[index];
    const previous = target[index - 1];
    if (
      Math.abs(current.at - previous.at) <= 0.05
      && Math.abs(current.x - previous.x) <= 0.01
      && Math.abs(current.y - previous.y) <= 0.01
    ) {
      target.splice(index - 1, 1);
      dropped += 1;
    }
  }
  if (Number.isFinite(now)) {
    while (target.length && Number(target[0].at) < cutoff) {
      target.shift();
      dropped += 1;
    }
  }
  if (target.length > limit) {
    dropped += target.length - limit;
    target.splice(0, target.length - limit);
  }
  return { samples: target, dropped };
}

export function sampleSharedPointerRealtimeBuffer(samples = [], nowMs = 0, options = {}) {
  const clean = (Array.isArray(samples) ? samples : [])
    .map((sample) => ({ x: Number(sample?.x), y: Number(sample?.y), at: Number(sample?.at) }))
    .filter((sample) => [sample.x, sample.y, sample.at].every(Number.isFinite))
    .sort((first, second) => first.at - second.at);
  if (!clean.length) return null;
  const now = finiteNumber(nowMs, 0);
  const bufferDelayMs = clampNumber(
    finiteNumber(options.bufferDelayMs, SHARED_POINTER_RENDER_DEFAULTS.realtimeBufferDelayMs),
    0,
    48
  );
  const renderAt = now - bufferDelayMs;
  const latest = clean[clean.length - 1];
  const netAgeMs = Math.max(0, now - latest.at);
  if (clean.length === 1 || renderAt <= clean[0].at) {
    return {
      x: clean[0].x,
      y: clean[0].y,
      mode: clean.length === 1 ? "net-single" : "net-wait",
      renderAt,
      bufferDelayMs,
      netAgeMs,
      predictionMs: 0,
      predictionPx: 0,
      sampleCount: clean.length,
    };
  }
  for (let index = 1; index < clean.length; index += 1) {
    const previous = clean[index - 1];
    const next = clean[index];
    if (renderAt <= next.at) {
      const span = Math.max(1, next.at - previous.at);
      const ratio = clampNumber((renderAt - previous.at) / span, 0, 1);
      return {
        x: previous.x + (next.x - previous.x) * ratio,
        y: previous.y + (next.y - previous.y) * ratio,
        mode: "net-buffer",
        renderAt,
        bufferDelayMs,
        netAgeMs,
        predictionMs: 0,
        predictionPx: 0,
        sampleCount: clean.length,
      };
    }
  }
  const previous = clean.length > 1 ? clean[clean.length - 2] : latest;
  const staleMs = Math.max(1, finiteNumber(options.staleMs, SHARED_POINTER_RENDER_DEFAULTS.realtimeStaleMs));
  const maxPredictionMs = Math.max(0, finiteNumber(options.maxPredictionMs, SHARED_POINTER_RENDER_DEFAULTS.realtimePredictionMaxMs));
  let predictionMs = netAgeMs > staleMs ? 0 : clampNumber(renderAt - latest.at, 0, maxPredictionMs);
  if (predictionMs > 0 && netAgeMs > maxPredictionMs) {
    predictionMs *= 1 - clampNumber((netAgeMs - maxPredictionMs) / Math.max(1, staleMs - maxPredictionMs), 0, 1);
  }
  const interval = Math.max(1, latest.at - previous.at);
  let dx = ((latest.x - previous.x) / interval) * predictionMs;
  let dy = ((latest.y - previous.y) / interval) * predictionMs;
  const maxDistance = Math.max(0, finiteNumber(options.maxPredictionDistancePx, SHARED_POINTER_RENDER_DEFAULTS.realtimePredictionMaxDistancePx));
  const distance = Math.hypot(dx, dy);
  if (maxDistance > 0 && distance > maxDistance) {
    const scale = maxDistance / distance;
    dx *= scale;
    dy *= scale;
  }
  const predictionPx = Math.hypot(dx, dy);
  return {
    x: latest.x + dx,
    y: latest.y + dy,
    mode: predictionPx > 0.01 ? "net-predict" : netAgeMs > staleMs ? "net-stale" : "net-latest",
    renderAt,
    bufferDelayMs,
    netAgeMs,
    predictionMs,
    predictionPx,
    sampleCount: clean.length,
  };
}

export function estimateSharedPointerClockOffset(timing = {}, previousOffsetMs = 0, options = {}) {
  const senderEpochMs = Number(timing.senderEpochMs ?? timing.sentAtMs ?? timing.sent_at_ms);
  const senderPerfMs = Number(timing.senderPerfMs ?? timing.sentPerfMs ?? timing.sent_perf_ms);
  const receiverEpochMs = Number(timing.receiverEpochMs ?? Date.now?.());
  const receiverPerfMs = Number(timing.receiverPerfMs ?? 0);
  const previous = finiteNumber(previousOffsetMs, 0);
  if (![senderEpochMs, senderPerfMs, receiverEpochMs, receiverPerfMs].every(Number.isFinite)) return previous;
  const rawOffset = (senderEpochMs - senderPerfMs) - (receiverEpochMs - receiverPerfMs);
  const maxAbs = Math.max(1, finiteNumber(options.maxAbsMs, SHARED_POINTER_RENDER_DEFAULTS.realtimeClockOffsetMaxAbsMs));
  if (!Number.isFinite(rawOffset) || Math.abs(rawOffset) > maxAbs) return previous;
  const alpha = clampNumber(finiteNumber(options.alpha, SHARED_POINTER_RENDER_DEFAULTS.realtimeClockOffsetAlpha), 0, 1);
  return previous ? previous * (1 - alpha) + rawOffset * alpha : rawOffset;
}

export function sampleSharedPointerPath(points = [], progress = 1) {
  if (!Array.isArray(points) || !points.length) return null;
  const clean = points
    .map((point) => ({ x: Number(point?.x), y: Number(point?.y) }))
    .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
  if (!clean.length) return null;
  if (clean.length === 1) return clean[0];
  const clamped = Math.max(0, Math.min(1, Number(progress) || 0));
  const scaled = clamped * (clean.length - 1);
  const index = Math.min(clean.length - 2, Math.floor(scaled));
  const ratio = scaled - index;
  const from = clean[index];
  const to = clean[index + 1];
  return {
    x: from.x + (to.x - from.x) * ratio,
    y: from.y + (to.y - from.y) * ratio,
  };
}
