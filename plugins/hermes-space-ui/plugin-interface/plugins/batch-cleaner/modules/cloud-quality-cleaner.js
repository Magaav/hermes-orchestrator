import { createCombinedDetectionMaskFrame } from "../../property-photo-cleaner/modules/detection-mask.js";
import { canvasToBlob } from "../../property-photo-cleaner/modules/lama-pipeline.js";

async function decodeCanvas(blob) {
  const bitmap = await createImageBitmap(blob);
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  canvas.getContext("2d", { alpha: false }).drawImage(bitmap, 0, 0);
  bitmap.close();
  return canvas;
}

function maskCanvas(frame) {
  const canvas = document.createElement("canvas");
  canvas.width = frame.mask.width;
  canvas.height = frame.mask.height;
  const context = canvas.getContext("2d");
  const output = context.createImageData(canvas.width, canvas.height);
  for (let pixel = 0; pixel < canvas.width * canvas.height; pixel += 1) {
    const offset = pixel * 4;
    output.data[offset] = 0;
    output.data[offset + 1] = 0;
    output.data[offset + 2] = 0;
    output.data[offset + 3] = frame.mask.data[offset + 3] > 8 ? 0 : 255;
  }
  context.putImageData(output, 0, 0);
  return canvas;
}

function blobBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("Could not encode the quality-worker image."));
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.readAsDataURL(blob);
  });
}

export async function cleanWithCloudQuality(sourceBlob, detections, options = {}) {
  if (!detections.length) return { blob: sourceBlob, model: "none", maskApplied: false };
  options.onProgress?.({ stage: "cloud-preparing", current: 0, total: 1 });
  const sourceCanvas = await decodeCanvas(sourceBlob);
  const frame = createCombinedDetectionMaskFrame(sourceCanvas, detections);
  const [sourcePng, maskPng] = await Promise.all([
    canvasToBlob(sourceCanvas, "image/png"),
    canvasToBlob(maskCanvas(frame), "image/png")
  ]);
  const [imageBase64, maskBase64] = await Promise.all([
    blobBase64(sourcePng),
    blobBase64(maskPng)
  ]);
  options.onProgress?.({ stage: "cloud-editing", current: 0, total: 1 });
  const response = await fetch("/property-photo-cleaner/edit", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      cloud_consent: true,
      media_type: "image/png",
      image_base64: imageBase64,
      mask_base64: maskBase64,
      objects: detections.map((detection) => detection.label)
    }),
    signal: options.signal
  });
  const result = await response.json().catch(() => null);
  if (!response.ok || !result?.ok || !result.image_base64) {
    const message = result?.error?.message || `Quality worker failed with HTTP ${response.status}.`;
    throw new Error(message);
  }
  const bytes = Uint8Array.from(atob(result.image_base64), (character) => character.charCodeAt(0));
  options.onProgress?.({ stage: "complete", current: 1, total: 1 });
  return {
    blob: new Blob([bytes], { type: result.media_type || "image/jpeg" }),
    model: result.model,
    accelerator: "remote-quality-worker",
    maskApplied: result.mask_applied === true,
    photoPersisted: result.photo_persisted === true
  };
}
