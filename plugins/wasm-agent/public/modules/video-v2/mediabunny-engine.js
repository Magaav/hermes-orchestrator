const MEDIABUNNY_URL = "https://cdn.jsdelivr.net/npm/mediabunny@1.52.3/+esm";
let runtimePromise;

export const loadMediabunny = () => (runtimePromise ||= import(MEDIABUNNY_URL));

const populatedTags = (tags) => Object.values(tags || {}).filter((value) => (
  Array.isArray(value) ? value.length > 0 : value !== undefined && value !== null && value !== ""
)).length;

export async function inspectMedia(blob, targetPacketCount = 90) {
  const media = await loadMediabunny();
  const input = new media.Input({ formats: media.ALL_FORMATS, source: new media.BlobSource(blob) });
  try {
    if (!await input.canRead()) throw new Error("Mediabunny cannot read this container.");
    const [videoTracks, audioTracks, duration, mimeType, tags] = await Promise.all([
      input.getVideoTracks(), input.getAudioTracks(), input.computeDuration(), input.getMimeType(), input.getMetadataTags(),
    ]);
    const video = await input.getPrimaryVideoTrack();
    const audio = await input.getPrimaryAudioTrack();
    if (!video) throw new Error("A primary video track is required.");
    const [width, height, videoCodec, hdr, videoStats, audioCodec, audioStats] = await Promise.all([
      video.getDisplayWidth(), video.getDisplayHeight(), video.getCodec(), video.hasHighDynamicRange(),
      video.computePacketStats(targetPacketCount), audio?.getCodec() || null,
      audio?.computePacketStats(targetPacketCount) || null,
    ]);
    return {
      duration, width, height, mimeType, videoCodec, audioCodec,
      videoTracks: videoTracks.length, audioTracks: audioTracks.length,
      fps: videoStats.averagePacketRate, videoBitrate: videoStats.averageBitrate,
      audioBitrate: audioStats?.averageBitrate || 0, hdr, metadataFields: populatedTags(tags), bytes: blob.size,
    };
  } finally {
    input.dispose();
  }
}

export async function convertMedia({ file, start, end, dimensions, videoBitrate, onProgress }) {
  const media = await loadMediabunny();
  const input = new media.Input({ formats: media.ALL_FORMATS, source: new media.BlobSource(file) });
  const target = new media.BufferTarget();
  const output = new media.Output({ format: new media.WebMOutputFormat(), target });
  try {
    const conversion = await media.Conversion.init({
      input, output, tracks: "primary", trim: { start, end }, tags: {}, showWarnings: false,
      video: {
        codec: "av1", width: dimensions.width, height: dimensions.height, fit: "fill",
        frameRate: 30, bitrate: videoBitrate, alpha: "discard", keyFrameInterval: 2,
        hardwareAcceleration: "no-preference", allowRotationMetadata: false, forceTranscode: true,
      },
      audio: { codec: "opus", bitrate: 64_000, forceTranscode: true },
    });
    if (!conversion.isValid) {
      const reasons = conversion.discardedTracks.map((item) => item.reason).join(", ") || "unsupported conversion";
      throw new Error(`Mediabunny conversion is unavailable: ${reasons}.`);
    }
    conversion.onProgress = (value) => onProgress?.(value);
    await conversion.execute();
    if (!target.buffer) throw new Error("Mediabunny produced no output buffer.");
    return new Blob([target.buffer], { type: "video/webm;codecs=av01,opus" });
  } finally {
    input.dispose();
  }
}

export { MEDIABUNNY_URL };
