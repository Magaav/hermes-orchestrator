import { canvasToBlob } from "./lama-pipeline.js?v=20260727-lossless1";
import {
  compositeQualityScene,
  createQualitySceneFrame
} from "./quality-scene-crop.js";

const MANIFEST_URL = new URL("../models/moebius-manifest.json?v=5bf1ef5-local1", import.meta.url);
const VENDOR_URL = new URL("../vendor/moebius-080be6e/moebius-pipeline.js", import.meta.url);
const ORT_BASE = new URL("../vendor/onnxruntime-web/1.27.0/", import.meta.url).href;
let pipelinePromise = null;

async function decodeCanvas(blob) {
  const bitmap = await createImageBitmap(blob);
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  canvas.getContext("2d", { alpha: false }).drawImage(bitmap, 0, 0);
  bitmap.close();
  return canvas;
}

async function loadManifest() {
  const response = await fetch(MANIFEST_URL);
  if (!response.ok) throw new Error("Quality reconstruction manifest is unavailable.");
  const manifest = await response.json();
  if (manifest.status !== "browser_product_verified_candidate") {
    throw new Error("Quality reconstruction model is not admitted for browser evaluation.");
  }
  return manifest;
}

async function loadPipeline(onProgress) {
  if (!navigator.gpu) throw new Error("Quality reconstruction requires WebGPU.");
  if (!await navigator.gpu.requestAdapter()) {
    throw new Error("No WebGPU adapter is available for quality reconstruction.");
  }
  if (!pipelinePromise) {
    pipelinePromise = (async () => {
      const [manifest, vendor] = await Promise.all([
        loadManifest(),
        import(VENDOR_URL.href)
      ]);
      vendor.MoebiusPipeline.configureRuntime(ORT_BASE);
      const pipeline = new vendor.MoebiusPipeline();
      const modelBase = new URL(manifest.modelBase, MANIFEST_URL).href.replace(/\/$/, "");
      await pipeline.load(modelBase, (stage, current, total) => {
        onProgress?.({ stage: "quality-model", label: stage, current, total });
      });
      return { pipeline, manifest };
    })().catch((error) => {
      pipelinePromise = null;
      throw error;
    });
  }
  return pipelinePromise;
}

export async function reconstructSelectedObjects(sourceBlob, detections, options = {}) {
  if (!detections.length) {
    return {
      blob: sourceBlob,
      model: "none",
      accelerator: "webgpu",
      intermediateEncodingCount: 0
    };
  }
  const { pipeline, manifest } = await loadPipeline(options.onProgress);
  if (options.signal?.aborted) throw new DOMException("Cleaning cancelled.", "AbortError");
  const sourceCanvas = await decodeCanvas(sourceBlob);
  const frame = createQualitySceneFrame(sourceCanvas, detections, options.crop);
  const generated = await pipeline.run(frame.image, frame.mask, {
    steps: options.steps ?? manifest.runtime.steps,
    guidance: options.guidance ?? manifest.runtime.guidance,
    seed: options.seed ?? 0,
    paste: true,
    onProgress(stage, current, total) {
      if (options.signal?.aborted) throw new DOMException("Cleaning cancelled.", "AbortError");
      options.onProgress?.({
        stage: stage === "Denoising" ? "quality-denoising" : "quality-reconstructing",
        label: stage,
        current,
        total
      });
    }
  });
  const output = compositeQualityScene(sourceCanvas, generated, frame);
  options.onProgress?.({ stage: "complete", current: 1, total: 1 });
  return {
    blob: await canvasToBlob(output),
    model: manifest.id,
    accelerator: pipeline.backend,
    encoding: "image/png",
    intermediateEncodingCount: 0,
    crop: frame.crop
  };
}

export async function disposeQualityCleaner() {
  if (!pipelinePromise) return;
  const loaded = await pipelinePromise.catch(() => null);
  loaded?.pipeline?.dispose?.();
  pipelinePromise = null;
}
