export const VIDEO_V1_LIMITS = Object.freeze({
  minDurationSec: 1,
  durationSec: 20,
  fps: 30,
  pixels: 921_600,
  maxEdge: 1280,
  videoBitrateMin: 700_000,
  videoBitrateMax: 1_000_000,
  audioBitrateMin: 48_000,
  audioBitrateMax: 64_000,
  outputBytes: 3 * 1024 * 1024,
});

const even = (value) => Math.max(2, Math.floor(value / 2) * 2);

export function encodedDimensions(width, height) {
  if (!(width > 0 && height > 0)) throw new TypeError("Source dimensions are unavailable.");
  const squareEdge = width === height ? 720 : VIDEO_V1_LIMITS.maxEdge;
  const scale = Math.min(
    1,
    squareEdge / width,
    squareEdge / height,
    Math.sqrt(VIDEO_V1_LIMITS.pixels / (width * height)),
  );
  return { width: even(width * scale), height: even(height * scale) };
}

export function normalizeRange(start, end, sourceDuration) {
  const safeDuration = Number.isFinite(sourceDuration) ? Math.max(0, sourceDuration) : 0;
  const safeStart = Math.min(Math.max(0, Number(start) || 0), safeDuration);
  const minimumEnd = Math.min(safeDuration, safeStart + VIDEO_V1_LIMITS.minDurationSec);
  const safeEnd = Math.min(Math.max(minimumEnd, Number(end) || 0), safeDuration, safeStart + VIDEO_V1_LIMITS.durationSec);
  return { start: safeStart, end: safeEnd, duration: safeEnd - safeStart };
}

export function bitratePlan(durationSec, hasAudio, attempt = 0) {
  const audioBits = hasAudio ? (attempt ? VIDEO_V1_LIMITS.audioBitrateMin : VIDEO_V1_LIMITS.audioBitrateMax) : 0;
  const containerReserve = 96 * 1024;
  const sizeBudget = Math.floor(((VIDEO_V1_LIMITS.outputBytes - containerReserve) * 8) / Math.max(durationSec, 0.25)) - audioBits;
  const preferred = attempt ? 700_000 : 900_000;
  return {
    videoBitsPerSecond: Math.max(VIDEO_V1_LIMITS.videoBitrateMin, Math.min(VIDEO_V1_LIMITS.videoBitrateMax, preferred, sizeBudget)),
    audioBitsPerSecond: audioBits,
  };
}

export function resolvedOutputDuration(containerDuration, selectedDuration) {
  return Number.isFinite(containerDuration) && containerDuration > 0
    ? containerDuration
    : selectedDuration;
}

export function sourceVideoSupport(file, canPlayType) {
  const type = String(file?.type || "").trim().toLowerCase();
  if (type && !type.startsWith("video/")) return { accepted: false, reason: "not-video" };
  if (!type) return { accepted: true, reason: "decode-probe" };
  const support = String(canPlayType?.(type) || "");
  return { accepted: support === "maybe" || support === "probably", reason: support || "unsupported-codec" };
}

export function validateOutput({ bytes, duration, width, height, fps, videoTracks, audioTracks, mimeType, posterType }) {
  const failures = [];
  if (!(duration > 0 && duration <= VIDEO_V1_LIMITS.durationSec + 0.05)) failures.push("duration");
  if (bytes > VIDEO_V1_LIMITS.outputBytes) failures.push("size");
  // Container timestamps can measure a 30 fps encode a few hundredths high.
  if (fps > VIDEO_V1_LIMITS.fps + 0.1) failures.push("fps");
  if (width > VIDEO_V1_LIMITS.maxEdge || height > VIDEO_V1_LIMITS.maxEdge || width * height > VIDEO_V1_LIMITS.pixels) failures.push("dimensions");
  if (videoTracks !== 1 || audioTracks > 1) failures.push("tracks");
  if (!/video\/webm/i.test(mimeType || "") || !/av01/i.test(mimeType || "")) failures.push("codec");
  if (audioTracks && !/opus/i.test(mimeType || "")) failures.push("audio-codec");
  if (posterType !== "image/avif") failures.push("poster");
  return { valid: failures.length === 0, failures };
}
