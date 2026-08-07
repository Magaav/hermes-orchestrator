import encodeAvif, { init as initAvif } from "../vendor/jsquash-avif-2.1.1/encode.js";

const CODEC_ROOT = new URL("../vendor/jsquash-avif-2.1.1/codec/enc/", import.meta.url);
let initialized;

function initialize() {
  if (!initialized) {
    initialized = initAvif({
      locateFile(path) {
        return new URL(path, CODEC_ROOT).href;
      }
    });
  }
  return initialized;
}

async function pixelsFromBlob(blob) {
  const bitmap = await createImageBitmap(blob);
  try {
    const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
    const context = canvas.getContext("2d", { alpha: false, willReadFrequently: true });
    context.drawImage(bitmap, 0, 0);
    return context.getImageData(0, 0, bitmap.width, bitmap.height);
  } finally {
    bitmap.close();
  }
}

export async function transcodeToAvif(blob, options = {}) {
  const startedAt = performance.now();
  await initialize();
  const pixels = await pixelsFromBlob(blob);
  const encoded = await encodeAvif(pixels, {
    lossless: options.lossless === true,
    quality: options.quality ?? 92,
    qualityAlpha: -1,
    speed: options.speed ?? 8,
    subsample: options.lossless === true ? 3 : 1,
    tune: 0
  });
  const output = new Blob([encoded], { type: "image/avif" });
  return {
    blob: output,
    inputBytes: blob.size,
    outputBytes: output.size,
    elapsedMs: Math.round(performance.now() - startedAt),
    ratio: output.size / Math.max(1, blob.size)
  };
}
