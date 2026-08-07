import {
  enhancementDimensions,
  enhanceRealityPixels,
  REALITY_ENHANCEMENT_PROFILE
} from "../modules/reality-enhancement.js";

async function remaster(blob, profile) {
  const bitmap = await createImageBitmap(blob);
  const dimensions = enhancementDimensions(bitmap.width, bitmap.height, profile);
  const canvas = new OffscreenCanvas(dimensions.width, dimensions.height);
  const context = canvas.getContext("2d", { alpha: false, willReadFrequently: true });
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.drawImage(bitmap, 0, 0, dimensions.width, dimensions.height);
  bitmap.close();
  const frame = context.getImageData(0, 0, dimensions.width, dimensions.height);
  frame.data.set(enhanceRealityPixels(frame.data, frame.width, frame.height, profile));
  context.putImageData(frame, 0, 0);
  return {
    blob: await canvas.convertToBlob({ type: "image/png" }),
    width: dimensions.width,
    height: dimensions.height,
    scale: dimensions.scale,
    profileId: profile.id
  };
}

self.addEventListener("message", async (event) => {
  const { id, blob, profile = REALITY_ENHANCEMENT_PROFILE } = event.data || {};
  try {
    const result = await remaster(blob, profile);
    self.postMessage({ id, ok: true, result });
  } catch (error) {
    self.postMessage({ id, ok: false, error: String(error?.message || error) });
  }
});
