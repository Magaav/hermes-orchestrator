import { createDetectionMaskFrame } from "./detection-mask.js?v=20260727-lossless1";
import { canvasToBlob, inpaintLamaCanvas } from "./lama-pipeline.js?v=20260727-lossless1";
import { createLamaWorkerSession } from "./onnx-inpainting-runtime.js";

const MODEL_ID = "big-lama-256-places2";
const MODEL_SIZE = 256;
const MODEL_URL = new URL("../models/lama-256-places2.onnx", import.meta.url).href;
let sessionPromise = null;

function yieldForPaint() {
  return new Promise((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)));
}

async function decodeCanvas(blob) {
  const bitmap = await createImageBitmap(blob);
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  canvas.getContext("2d", { alpha: false }).drawImage(bitmap, 0, 0);
  bitmap.close();
  return canvas;
}

async function getSession(onProgress) {
  if (!sessionPromise) {
    onProgress?.({ stage: "loading-model", current: 0, total: 1 });
    sessionPromise = createLamaWorkerSession(MODEL_URL, MODEL_SIZE);
  }
  const session = await sessionPromise;
  onProgress?.({ stage: "model-ready", current: 0, total: 1 });
  return session;
}

export async function cleanSelectedObjects(sourceBlob, detections, options = {}) {
  const session = await getSession(options.onProgress);
  if (!detections.length) {
    options.onProgress?.({ stage: "complete", current: 0, total: 0 });
    return { blob: sourceBlob, model: MODEL_ID, accelerator: session.accelerator };
  }
  let cleaned = await decodeCanvas(sourceBlob);
  for (let index = 0; index < detections.length; index += 1) {
    if (options.signal?.aborted) throw new DOMException("Cleaning cancelled.", "AbortError");
    options.onProgress?.({
      stage: "reconstructing",
      current: index,
      total: detections.length,
      detectionId: detections[index].id
    });
    await yieldForPaint();
    cleaned = await inpaintLamaCanvas(
      session,
      createDetectionMaskFrame(cleaned, detections[index])
    );
  }
  options.onProgress?.({ stage: "complete", current: detections.length, total: detections.length });
  return {
    blob: await canvasToBlob(cleaned),
    model: MODEL_ID,
    accelerator: session.accelerator,
    encoding: "image/png",
    intermediateEncodingCount: 0
  };
}

export async function disposeObjectCleaner() {
  if (!sessionPromise) return;
  const session = await sessionPromise.catch(() => null);
  await session?.dispose();
  sessionPromise = null;
}
