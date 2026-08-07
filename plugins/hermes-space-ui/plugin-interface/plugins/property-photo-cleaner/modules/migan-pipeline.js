const MODEL_SIZE = 256;

function canvasFromImageData(imageData) {
  const canvas = document.createElement("canvas");
  canvas.width = imageData.width;
  canvas.height = imageData.height;
  canvas.getContext("2d").putImageData(imageData, 0, 0);
  return canvas;
}

function resizedPixels(imageData) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = MODEL_SIZE;
  canvas.getContext("2d").drawImage(canvasFromImageData(imageData), 0, 0, MODEL_SIZE, MODEL_SIZE);
  return canvas.getContext("2d").getImageData(0, 0, MODEL_SIZE, MODEL_SIZE).data;
}

function cropCanvas(imageData, bounds) {
  const source = canvasFromImageData(imageData);
  const canvas = document.createElement("canvas");
  canvas.width = bounds.width;
  canvas.height = bounds.height;
  canvas.getContext("2d").drawImage(
    source,
    bounds.x, bounds.y, bounds.width, bounds.height,
    0, 0, bounds.width, bounds.height
  );
  return canvas;
}

export function planInpaintingCrop(bounds, imageSize, options = {}) {
  const contextScale = options.contextScale || 2.6;
  const minimumSide = Math.min(options.minimumSide || 192, imageSize.width, imageSize.height);
  const desiredSide = Math.max(minimumSide, Math.ceil(Math.max(bounds.width, bounds.height) * contextScale));
  const side = Math.min(desiredSide, imageSize.width, imageSize.height);
  const centerX = bounds.x + bounds.width / 2;
  const centerY = bounds.y + bounds.height / 2;
  const x = Math.max(0, Math.min(imageSize.width - side, Math.round(centerX - side / 2)));
  const y = Math.max(0, Math.min(imageSize.height - side, Math.round(centerY - side / 2)));
  return { x, y, width: side, height: side };
}

function toBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("Could not encode the inpainted image.")), "image/jpeg", 0.92);
  });
}

export async function inpaintMigan(session, frame, diagnostics = null) {
  const crop = planInpaintingCrop(frame.bounds, frame.source);
  const sourceCrop = cropCanvas(frame.source, crop);
  const maskCrop = cropCanvas(frame.mask, crop);
  const rgba = resizedPixels(sourceCrop.getContext("2d").getImageData(0, 0, crop.width, crop.height));
  const maskRgba = resizedPixels(maskCrop.getContext("2d").getImageData(0, 0, crop.width, crop.height));
  const rgb = new Uint8Array(MODEL_SIZE * MODEL_SIZE * 3);
  const mask = new Uint8Array(MODEL_SIZE * MODEL_SIZE);
  for (let pixel = 0, rgbIndex = 0; pixel < mask.length; pixel += 1, rgbIndex += 3) {
    const rgbaIndex = pixel * 4;
    rgb[rgbIndex] = rgba[rgbaIndex];
    rgb[rgbIndex + 1] = rgba[rgbaIndex + 1];
    rgb[rgbIndex + 2] = rgba[rgbaIndex + 2];
    mask[pixel] = maskRgba[rgbaIndex + 3] > 8 ? 0 : 255;
  }

  const imageTensor = session.tensor(rgb, [1, MODEL_SIZE, MODEL_SIZE, 3]);
  const maskTensor = session.tensor(mask, [1, MODEL_SIZE, MODEL_SIZE, 1]);
  let outputs;
  try {
    outputs = await session.run({ image: imageTensor, mask: maskTensor });
    const output = outputs.result || Object.values(outputs)[0];
    const nchw = await output.toTypedArray();
    if (diagnostics) {
      let minimum = Infinity;
      let maximum = -Infinity;
      for (let index = 0; index < nchw.length; index += 1) {
        minimum = Math.min(minimum, nchw[index]);
        maximum = Math.max(maximum, nchw[index]);
      }
      diagnostics.output = {
        constructor: nchw.constructor.name,
        shape: output.shape || output.dims || null,
        length: nchw.length,
        minimum,
        maximum,
        samples: Array.from(nchw.slice(0, 8))
      };
    }
    const generated = new ImageData(MODEL_SIZE, MODEL_SIZE);
    const plane = MODEL_SIZE * MODEL_SIZE;
    for (let pixel = 0; pixel < plane; pixel += 1) {
      const rgbaIndex = pixel * 4;
      generated.data[rgbaIndex] = nchw[pixel];
      generated.data[rgbaIndex + 1] = nchw[plane + pixel];
      generated.data[rgbaIndex + 2] = nchw[plane * 2 + pixel];
      generated.data[rgbaIndex + 3] = 255;
    }

    const result = canvasFromImageData(frame.source);
    const patch = document.createElement("canvas");
    patch.width = crop.width;
    patch.height = crop.height;
    const patchContext = patch.getContext("2d");
    patchContext.drawImage(canvasFromImageData(generated), 0, 0, patch.width, patch.height);
    patchContext.globalCompositeOperation = "destination-in";
    patchContext.filter = `blur(${Math.max(1, Math.round(crop.width / 160))}px)`;
    patchContext.drawImage(maskCrop, 0, 0);
    result.getContext("2d").drawImage(patch, crop.x, crop.y);
    return toBlob(result);
  } finally {
    if (outputs) {
      for (const tensor of Object.values(outputs)) tensor.delete?.();
    }
    imageTensor.delete?.();
    maskTensor.delete?.();
  }
}
