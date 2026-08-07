const MODEL_SIZE = 512;
const OBJECT_PADDING_RATIO = 0.18;
const OBJECT_FOOTPRINT_RATIO = 0.12;
const WATERMARK_PADDING_RATIO = 0.06;

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

export function planQualitySceneCrop(detections, imageSize, options = {}) {
  if (!detections.length) {
    const side = Math.min(imageSize.width, imageSize.height);
    return {
      x: Math.floor((imageSize.width - side) / 2),
      y: Math.floor((imageSize.height - side) / 2),
      width: side,
      height: side
    };
  }
  const left = Math.min(...detections.map(({ box }) => box.x));
  const top = Math.min(...detections.map(({ box }) => box.y));
  const right = Math.max(...detections.map(({ box }) => box.x + box.width));
  const bottom = Math.max(...detections.map(({ box }) => box.y + box.height));
  const maximumSide = Math.min(imageSize.width, imageSize.height);
  const contextScale = options.contextScale ?? 2.4;
  const side = Math.min(
    maximumSide,
    Math.max(options.minimumSide ?? 384, Math.ceil(Math.max(right - left, bottom - top) * contextScale))
  );
  const centerX = (left + right) / 2;
  const centerY = (top + bottom) / 2;
  return {
    x: Math.round(clamp(centerX - side / 2, 0, imageSize.width - side)),
    y: Math.round(clamp(centerY - side / 2, 0, imageSize.height - side)),
    width: side,
    height: side
  };
}

export function planQualityMaskRegions(detections, crop, options = {}) {
  const scale = MODEL_SIZE / crop.width;
  return detections.map((detection) => {
    const watermark = detection.label === "watermark logo";
    const paddingRatio = watermark
      ? (options.watermarkPaddingRatio ?? WATERMARK_PADDING_RATIO)
      : (options.paddingRatio ?? OBJECT_PADDING_RATIO);
    const padding = Math.max(
      4,
      Math.round(Math.min(detection.box.width, detection.box.height) * paddingRatio * scale)
    );
    const footprint = watermark
      ? 0
      : Math.round(detection.box.height * (options.footprintRatio ?? OBJECT_FOOTPRINT_RATIO) * scale);
    return {
      x: (detection.box.x - crop.x) * scale - padding,
      y: (detection.box.y - crop.y) * scale - padding,
      width: detection.box.width * scale + padding * 2,
      height: detection.box.height * scale + padding * 2 + footprint
    };
  });
}

export function createQualitySceneFrame(sourceCanvas, detections, options = {}) {
  const crop = planQualitySceneCrop(detections, sourceCanvas, options);
  const image = document.createElement("canvas");
  image.width = image.height = MODEL_SIZE;
  image.getContext("2d", { alpha: false }).drawImage(
    sourceCanvas,
    crop.x, crop.y, crop.width, crop.height,
    0, 0, MODEL_SIZE, MODEL_SIZE
  );

  const mask = document.createElement("canvas");
  mask.width = mask.height = MODEL_SIZE;
  const context = mask.getContext("2d");
  context.fillStyle = "#fff";
  for (const region of planQualityMaskRegions(detections, crop, options)) {
    context.fillRect(region.x, region.y, region.width, region.height);
  }
  return { image, mask, crop };
}

export function compositeQualityScene(sourceCanvas, generatedCanvas, frame) {
  const { crop, mask } = frame;
  const output = document.createElement("canvas");
  output.width = sourceCanvas.width;
  output.height = sourceCanvas.height;
  const context = output.getContext("2d", { alpha: false });
  context.drawImage(sourceCanvas, 0, 0);

  const patch = document.createElement("canvas");
  patch.width = crop.width;
  patch.height = crop.height;
  const patchContext = patch.getContext("2d");
  patchContext.drawImage(
    generatedCanvas,
    0, 0, MODEL_SIZE, MODEL_SIZE,
    0, 0, crop.width, crop.height
  );
  patchContext.globalCompositeOperation = "destination-in";
  patchContext.filter = `blur(${Math.max(1, Math.round(crop.width / 256))}px)`;
  patchContext.drawImage(mask, 0, 0, MODEL_SIZE, MODEL_SIZE, 0, 0, crop.width, crop.height);
  patchContext.filter = "none";
  context.drawImage(patch, crop.x, crop.y);
  return output;
}
