function expandedBounds(box, width, height, paddingRatio) {
  const padding = Math.max(3, Math.round(Math.min(box.width, box.height) * paddingRatio));
  const x = Math.max(0, Math.floor(box.x - padding));
  const y = Math.max(0, Math.floor(box.y - padding));
  const right = Math.min(width, Math.ceil(box.x + box.width + padding));
  const bottom = Math.min(height, Math.ceil(box.y + box.height + padding));
  return { x, y, width: right - x, height: bottom - y };
}

function footprintBounds(detection, width, height, options = {}) {
  const isWatermark = detection.label === "watermark logo";
  const bounds = expandedBounds(
    detection.box,
    width,
    height,
    isWatermark
      ? (options.watermarkPaddingRatio ?? 0.06)
      : (options.objectPaddingRatio ?? 0.16)
  );
  if (isWatermark) return bounds;
  const extraFloor = Math.round(detection.box.height * (options.footprintRatio ?? 0.18));
  const bottom = Math.min(height, bounds.y + bounds.height + extraFloor);
  return { ...bounds, height: bottom - bounds.y };
}

function paintDetectionMask(context, detection, bounds) {
  context.fillStyle = "#fff";
  if (detection.label === "watermark logo") {
    context.fillRect(bounds.x, bounds.y, bounds.width, bounds.height);
    return;
  }
  const radius = Math.max(2, Math.min(bounds.width, bounds.height) * 0.04);
  context.beginPath();
  context.roundRect(bounds.x, bounds.y, bounds.width, bounds.height, radius);
  context.fill();
}

export function createDetectionMaskFrame(canvas, detection, options = {}) {
  const context = canvas.getContext("2d", { alpha: false, willReadFrequently: true });
  const source = context.getImageData(0, 0, canvas.width, canvas.height);
  const maskCanvas = document.createElement("canvas");
  maskCanvas.width = canvas.width;
  maskCanvas.height = canvas.height;
  const maskContext = maskCanvas.getContext("2d");
  const bounds = expandedBounds(
    detection.box,
    canvas.width,
    canvas.height,
    detection.label === "watermark logo"
      ? (options.watermarkPaddingRatio ?? 0.06)
      : (options.objectPaddingRatio ?? 0.16)
  );
  if (detection.label !== "watermark logo" && options.instanceMask) {
    const instance = options.instanceMask;
    const maskImage = maskContext.createImageData(instance.width, instance.height);
    for (let index = 0; index < instance.data.length; index += 1) {
      if (!instance.data[index]) continue;
      const offset = index * 4;
      maskImage.data[offset] = 255;
      maskImage.data[offset + 1] = 255;
      maskImage.data[offset + 2] = 255;
      maskImage.data[offset + 3] = 255;
    }
    const instanceCanvas = document.createElement("canvas");
    instanceCanvas.width = instance.width;
    instanceCanvas.height = instance.height;
    instanceCanvas.getContext("2d").putImageData(maskImage, 0, 0);
    const dilation = options.instanceDilation
      ?? Math.max(4, Math.round(Math.min(instance.width, instance.height) * 0.1));
    maskContext.filter = `blur(${dilation}px)`;
    maskContext.drawImage(instanceCanvas, Math.round(instance.x), Math.round(instance.y));
    maskContext.filter = "none";
  } else {
    paintDetectionMask(maskContext, detection, bounds);
  }
  return {
    source,
    mask: maskContext.getImageData(0, 0, canvas.width, canvas.height),
    bounds,
    detectionId: detection.id
  };
}

export function createCombinedDetectionMaskFrame(canvas, detections, options = {}) {
  const context = canvas.getContext("2d", { alpha: false, willReadFrequently: true });
  const source = context.getImageData(0, 0, canvas.width, canvas.height);
  const maskCanvas = document.createElement("canvas");
  maskCanvas.width = canvas.width;
  maskCanvas.height = canvas.height;
  const maskContext = maskCanvas.getContext("2d");
  const regions = detections.map((detection) => {
    const bounds = footprintBounds(detection, canvas.width, canvas.height, options);
    paintDetectionMask(maskContext, detection, bounds);
    return bounds;
  });
  const left = Math.min(...regions.map((bounds) => bounds.x));
  const top = Math.min(...regions.map((bounds) => bounds.y));
  const right = Math.max(...regions.map((bounds) => bounds.x + bounds.width));
  const bottom = Math.max(...regions.map((bounds) => bounds.y + bounds.height));
  return {
    source,
    mask: maskContext.getImageData(0, 0, canvas.width, canvas.height),
    bounds: { x: left, y: top, width: right - left, height: bottom - top },
    detectionIds: detections.map((detection) => detection.id)
  };
}

export function orderDetectionsForCleaning(detections) {
  return [...detections].sort((left, right) => {
    const leftArea = left.box.width * left.box.height;
    const rightArea = right.box.width * right.box.height;
    return leftArea - rightArea;
  });
}

export function planDetectionCleanPasses(detection, options = {}) {
  const maximumSpan = options.maximumSpan || 64;
  const overlap = options.overlap ?? 10;
  const step = maximumSpan - overlap;
  if (detection.box.width <= maximumSpan && detection.box.height <= maximumSpan) return [detection];
  const passes = [];
  const columns = Math.max(1, Math.ceil((detection.box.width - overlap) / step));
  const rows = Math.max(1, Math.ceil((detection.box.height - overlap) / step));
  const tileWidth = Math.min(maximumSpan, detection.box.width);
  const tileHeight = Math.min(maximumSpan, detection.box.height);
  for (let row = 0; row < rows; row += 1) {
    const y = rows === 1
      ? detection.box.y
      : detection.box.y + row * (detection.box.height - tileHeight) / (rows - 1);
    for (let column = 0; column < columns; column += 1) {
      const x = columns === 1
        ? detection.box.x
        : detection.box.x + column * (detection.box.width - tileWidth) / (columns - 1);
      passes.push({
        ...detection,
        id: `${detection.id}-pass-${passes.length + 1}`,
        box: {
          x,
          y,
          width: tileWidth,
          height: tileHeight
        }
      });
    }
  }
  return passes;
}
