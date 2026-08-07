import { recognizeCenteredWatermark } from "./watermark-recognizer.js";

let detectorPromise = null;
const detectionMasks = new Map();

function absolute(path) {
  return new URL(path, import.meta.url).href;
}

export function normalizeDetections(results, { width, height }) {
  return results
    .map((result, index) => {
      const box = result.box || {};
      const x1 = Math.max(0, Math.min(width, Number(box.xmin)));
      const y1 = Math.max(0, Math.min(height, Number(box.ymin)));
      const x2 = Math.max(x1, Math.min(width, Number(box.xmax)));
      const y2 = Math.max(y1, Math.min(height, Number(box.ymax)));
      return {
        id: `object-${index + 1}`,
        label: String(result.label || "object"),
        rawLabel: String(result.rawLabel || result.label || "object"),
        score: Math.round(Number(result.score || 0) * 1000) / 1000,
        source: result.source || "full",
        recovery: Boolean(result.recovery),
        maskDescriptor: result.maskDescriptor || null,
        instanceMask: result.instanceMask || null,
        box: { x: x1, y: y1, width: x2 - x1, height: y2 - y1 }
      };
    })
    .filter((result) => result.box.width >= 2 && result.box.height >= 2);
}

function intersectionOverUnion(a, b) {
  const left = Math.max(a.x, b.x);
  const top = Math.max(a.y, b.y);
  const right = Math.min(a.x + a.width, b.x + b.width);
  const bottom = Math.min(a.y + a.height, b.y + b.height);
  const intersection = Math.max(0, right - left) * Math.max(0, bottom - top);
  const union = a.width * a.height + b.width * b.height - intersection;
  return union > 0 ? intersection / union : 0;
}

function intersectionOverSmaller(a, b) {
  const left = Math.max(a.x, b.x);
  const top = Math.max(a.y, b.y);
  const right = Math.min(a.x + a.width, b.x + b.width);
  const bottom = Math.min(a.y + a.height, b.y + b.height);
  const intersection = Math.max(0, right - left) * Math.max(0, bottom - top);
  return intersection / Math.min(a.width * a.height, b.width * b.height);
}

export function suppressOverlaps(detections, threshold, lowConfidenceThreshold = 0.06) {
  const kept = [];
  for (const detection of [...detections].sort((a, b) => {
    const sourceDifference = Number(b.source === "full") - Number(a.source === "full");
    return sourceDifference || b.score - a.score;
  })) {
    if (kept.some((candidate) => intersectionOverUnion(candidate.box, detection.box) >= threshold
      || (candidate.label === detection.label
        && intersectionOverSmaller(candidate.box, detection.box) >= 0.75)
      || (!detection.recovery && detection.score < lowConfidenceThreshold
        && intersectionOverSmaller(candidate.box, detection.box) >= 0.75))) continue;
    kept.push(detection);
  }
  return kept.map((detection, index) => ({ ...detection, id: `object-${index + 1}` }));
}

async function createDetector(manifest, onProgress) {
  const runtime = await import(absolute(manifest.runtime.url));
  runtime.env.wasm.wasmPaths = absolute(manifest.runtime.wasmBase);
  runtime.env.wasm.numThreads = Math.max(1, Math.min(4, Math.floor((navigator.hardwareConcurrency || 2) / 2)));
  const modelUrl = new URL(`../models/${manifest.model.url.replace("./", "")}`, import.meta.url).href;
  onProgress({ status: "loading", file: manifest.model.url, progress: 0 });
  const session = await runtime.InferenceSession.create(modelUrl, {
    executionProviders: ["wasm"],
    graphOptimizationLevel: "all"
  });
  onProgress({ status: "ready", file: manifest.model.url, progress: 100 });
  return {
    async detect(blob, labels, profile, imageSize) {
      const bitmap = await createImageBitmap(blob);
      const views = planDetectionViews(bitmap.width, bitmap.height, profile);
      const results = [];
      try {
        for (let index = 0; index < views.length; index += 1) {
          onProgress({ status: "detecting", current: index + 1, total: views.length });
          const { tensor, transform } = imageTensor(runtime, bitmap, manifest.model.inputSize, views[index]);
          const outputs = await session.run({ images: tensor });
          results.push(...decodeYoloEOutputs(
            outputs.output0,
            labels,
            profile,
            imageSize,
            transform,
            views[index].kind,
            outputs.output1,
            manifest.model.inputSize
          ));
        }
        results.push(...recognizeCenteredWatermark(bitmap, profile));
      } finally {
        bitmap.close?.();
      }
      return { results, viewCount: views.length };
    },
    dispose() {
      session.release?.();
    }
  };
}

export function planDetectionViews(width, height, profile) {
  const views = [{ x: 0, y: 0, width, height, kind: "full" }];
  if (!profile.detailViews || Math.max(width, height) / Math.min(width, height) < profile.detailViewAspectRatio) {
    return views;
  }
  const side = Math.min(width, height);
  if (width > height) {
    views.push(
      { x: 0, y: 0, width: side, height: side, kind: "detail" },
      { x: width - side, y: 0, width: side, height: side, kind: "detail" }
    );
  } else {
    views.push(
      { x: 0, y: 0, width: side, height: side, kind: "detail" },
      { x: 0, y: height - side, width: side, height: side, kind: "detail" }
    );
  }
  return views;
}

function imageTensor(runtime, bitmap, size, view) {
  const scale = Math.min(size / view.width, size / view.height);
  const drawWidth = Math.round(view.width * scale);
  const drawHeight = Math.round(view.height * scale);
  const offsetX = Math.floor((size - drawWidth) / 2);
  const offsetY = Math.floor((size - drawHeight) / 2);
  const canvas = new OffscreenCanvas(size, size);
  const context = canvas.getContext("2d", { willReadFrequently: true });
  context.fillStyle = "rgb(114, 114, 114)";
  context.fillRect(0, 0, size, size);
  context.drawImage(bitmap, view.x, view.y, view.width, view.height, offsetX, offsetY, drawWidth, drawHeight);
  const pixels = context.getImageData(0, 0, size, size).data;
  const plane = size * size;
  const data = new Float32Array(plane * 3);
  for (let pixel = 0; pixel < plane; pixel += 1) {
    data[pixel] = pixels[pixel * 4] / 255;
    data[plane + pixel] = pixels[pixel * 4 + 1] / 255;
    data[plane * 2 + pixel] = pixels[pixel * 4 + 2] / 255;
  }
  return {
    tensor: new runtime.Tensor("float32", data, [1, 3, size, size]),
    transform: { scale, offsetX, offsetY, originX: view.x, originY: view.y }
  };
}

export function decodeYoloEOutputs(
  output,
  labels,
  profile,
  { width, height },
  transform,
  source = "full",
  prototypes = null,
  inputSize = 640
) {
  const rows = output.dims[1];
  const fields = output.dims[2];
  if (fields < 6) {
    throw new Error(`Unexpected YOLO-World output shape: ${output.dims.join("x")}`);
  }
  const candidates = [];
  const originX = transform.originX || 0;
  const originY = transform.originY || 0;
  for (let row = 0; row < rows; row += 1) {
    const offset = row * fields;
    const score = Number(output.data[offset + 4]);
    const threshold = source === "detail" ? profile.detailThreshold : profile.threshold;
    if (score < threshold) continue;
    const labelIndex = Math.round(Number(output.data[offset + 5]));
    if (labelIndex < 0 || labelIndex >= labels.length) continue;
    const xmin = Math.max(0, (Number(output.data[offset]) - transform.offsetX) / transform.scale + originX);
    const ymin = Math.max(0, (Number(output.data[offset + 1]) - transform.offsetY) / transform.scale + originY);
    const xmax = Math.min(width, (Number(output.data[offset + 2]) - transform.offsetX) / transform.scale + originX);
    const ymax = Math.min(height, (Number(output.data[offset + 3]) - transform.offsetY) / transform.scale + originY);
    const boxWidth = xmax - xmin;
    const boxHeight = ymax - ymin;
    if (boxWidth <= 0 || boxHeight <= 0) continue;
    const areaRatio = (boxWidth * boxHeight) / (width * height);
    const widthHeightRatio = boxWidth / boxHeight;
    if (areaRatio > profile.maxSceneAreaRatio) continue;
    if (widthHeightRatio > profile.maxWidthHeightRatio) continue;
    let uncertainFullObject = false;
    if (source === "full" && score < profile.fullSmallStrongThreshold) {
      if (areaRatio < profile.fullSmallMinAreaRatio) continue;
      if (score < profile.fullLowConfidenceThreshold) {
        if (areaRatio > profile.fullLowConfidenceMaxAreaRatio
          || widthHeightRatio > profile.fullLowConfidenceMaxWidthHeightRatio
          || (ymin + ymax) / 2 < height * profile.fullLowConfidenceMinCenterYRatio) continue;
        uncertainFullObject = true;
      }
    }
    let uncertainDetailObject = false;
    if (source === "detail" && score < profile.detailStrongThreshold) {
      const smallCandidate = areaRatio >= profile.detailMinAreaRatio && areaRatio <= profile.detailMaxAreaRatio;
      const moderateVerticalCandidate = score >= profile.detailModerateThreshold
        && areaRatio >= profile.detailModerateMinAreaRatio
        && areaRatio <= profile.detailModerateMaxAreaRatio
        && widthHeightRatio <= profile.detailModerateMaxWidthHeightRatio;
      if (!smallCandidate && !moderateVerticalCandidate) continue;
      uncertainDetailObject = moderateVerticalCandidate;
    }
    const boundaryMargin = Math.min(width, height) * profile.boundaryMarginRatio;
    const touchesBoundary = xmin <= boundaryMargin || ymin <= boundaryMargin
      || xmax >= width - boundaryMargin || ymax >= height - boundaryMargin;
    if (touchesBoundary && areaRatio > profile.maxBoundaryPartialAreaRatio) continue;
    candidates.push({
      score,
      label: uncertainDetailObject || uncertainFullObject ? "object" : labels[labelIndex],
      rawLabel: labels[labelIndex],
      source,
      recovery: uncertainFullObject,
      partial: touchesBoundary,
      maskDescriptor: prototypes && fields >= 38 ? {
        coefficients: Float32Array.from(output.data.slice(offset + 6, offset + 38)),
        prototypes: prototypes.data,
        prototypeWidth: prototypes.dims[3],
        prototypeHeight: prototypes.dims[2],
        inputSize,
        transform
      } : null,
      box: { xmin, ymin, xmax, ymax }
    });
  }
  return candidates.sort((a, b) => b.score - a.score).slice(0, profile.topK);
}

export function rasterizeInstanceMask(detection) {
  const descriptor = detection.maskDescriptor;
  if (!descriptor) return null;
  const width = Math.max(1, Math.round(detection.box.width));
  const height = Math.max(1, Math.round(detection.box.height));
  const data = new Uint8Array(width * height);
  const { coefficients, prototypes, prototypeWidth, prototypeHeight, inputSize, transform } = descriptor;
  const plane = prototypeWidth * prototypeHeight;
  for (let y = 0; y < height; y += 1) {
    const sourceY = detection.box.y + (y + 0.5) * detection.box.height / height;
    const modelY = (sourceY - (transform.originY || 0)) * transform.scale + transform.offsetY;
    const prototypeY = Math.max(0, Math.min(
      prototypeHeight - 1,
      Math.floor(modelY * prototypeHeight / inputSize)
    ));
    for (let x = 0; x < width; x += 1) {
      const sourceX = detection.box.x + (x + 0.5) * detection.box.width / width;
      const modelX = (sourceX - (transform.originX || 0)) * transform.scale + transform.offsetX;
      const prototypeX = Math.max(0, Math.min(
        prototypeWidth - 1,
        Math.floor(modelX * prototypeWidth / inputSize)
      ));
      const prototypeOffset = prototypeY * prototypeWidth + prototypeX;
      let logit = 0;
      for (let channel = 0; channel < coefficients.length; channel += 1) {
        logit += coefficients[channel] * prototypes[channel * plane + prototypeOffset];
      }
      if (logit > 0) data[y * width + x] = 255;
    }
  }
  return { x: detection.box.x, y: detection.box.y, width, height, data };
}

export async function findObjects(blob, imageSize, onProgress = () => {}) {
  const manifest = await fetch(new URL("../models/detection-manifest.json", import.meta.url)).then((response) => {
    if (!response.ok) throw new Error("Object detection manifest is unavailable.");
    return response.json();
  });
  const profile = await fetch(new URL(`../models/${manifest.model.profile.replace("./", "")}`, import.meta.url)).then((response) => {
    if (!response.ok) throw new Error("Property recognition profile is unavailable.");
    return response.json();
  });
  detectorPromise ||= createDetector(manifest, onProgress);
  const detector = await detectorPromise;
  const result = await detector.detect(blob, profile.labels, profile, imageSize);
  const detections = suppressOverlaps(
    normalizeDetections(result.results, imageSize),
    profile.overlapThreshold,
    profile.lowConfidenceContainmentThreshold
  ).slice(0, profile.topK);
  detectionMasks.clear();
  for (const detection of detections) {
    const mask = detection.instanceMask || rasterizeInstanceMask(detection);
    if (mask) detectionMasks.set(detection.id, mask);
  }
  return {
    schema: "hermes.property_photo_cleaner.detections.v1",
    model: manifest.model.id,
    vocabulary: manifest.model.vocabulary,
    profile: profile.id,
    cleaningPolicy: profile.cleaningPolicy || { protectedLabels: [] },
    viewCount: result.viewCount,
    detections: detections.map(({ maskDescriptor, instanceMask, ...detection }) => detection)
  };
}

export function getDetectionMask(detectionId) {
  return detectionMasks.get(detectionId) || null;
}

export async function disposeDetector() {
  const detector = await detectorPromise?.catch?.(() => null);
  detector?.dispose?.();
  detectorPromise = null;
  detectionMasks.clear();
}
