function canvasFromImageData(imageData) {
  const canvas = document.createElement("canvas");
  canvas.width = imageData.width;
  canvas.height = imageData.height;
  canvas.getContext("2d").putImageData(imageData, 0, 0);
  return canvas;
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

function resizedPixels(canvas, modelSize) {
  const resized = document.createElement("canvas");
  resized.width = resized.height = modelSize;
  resized.getContext("2d").drawImage(canvas, 0, 0, modelSize, modelSize);
  return resized.getContext("2d").getImageData(0, 0, modelSize, modelSize).data;
}

export function canvasToBlob(canvas, type = "image/png", quality) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error("Could not encode the inpainted image.")),
      type,
      quality
    );
  });
}

export function planLamaCrop(bounds, imageSize, options = {}) {
  const contextScale = options.contextScale || 3;
  const minimumSide = Math.min(options.minimumSide || 256, imageSize.width, imageSize.height);
  const desiredSide = Math.max(minimumSide, Math.ceil(Math.max(bounds.width, bounds.height) * contextScale));
  const side = Math.min(desiredSide, imageSize.width, imageSize.height);
  const centerX = bounds.x + bounds.width / 2;
  const centerY = bounds.y + bounds.height / 2;
  const x = Math.max(0, Math.min(imageSize.width - side, Math.round(centerX - side / 2)));
  const y = Math.max(0, Math.min(imageSize.height - side, Math.round(centerY - side / 2)));
  return { x, y, width: side, height: side };
}

export async function inpaintLamaCanvas(session, frame, diagnostics = null) {
  const modelSize = session.modelSize || 512;
  const crop = planLamaCrop(frame.bounds, frame.source);
  const sourceCrop = cropCanvas(frame.source, crop);
  const maskCrop = cropCanvas(frame.mask, crop);
  const rgba = resizedPixels(sourceCrop, modelSize);
  const maskRgba = resizedPixels(maskCrop, modelSize);
  const plane = modelSize * modelSize;
  const image = new Float32Array(plane * 3);
  const mask = new Float32Array(plane);
  for (let pixel = 0; pixel < plane; pixel += 1) {
    const rgbaIndex = pixel * 4;
    image[pixel] = rgba[rgbaIndex] / 255;
    image[plane + pixel] = rgba[rgbaIndex + 1] / 255;
    image[plane * 2 + pixel] = rgba[rgbaIndex + 2] / 255;
    mask[pixel] = maskRgba[rgbaIndex + 3] > 8 ? 1 : 0;
  }
  const imageTensor = session.tensor(image, [1, 3, modelSize, modelSize]);
  const maskTensor = session.tensor(mask, [1, 1, modelSize, modelSize]);
  let outputs;
  try {
    outputs = await session.run({ image: imageTensor, mask: maskTensor });
    const output = outputs.output || Object.values(outputs)[0];
    const values = await output.toTypedArray();
    if (diagnostics) {
      let minimum = Infinity;
      let maximum = -Infinity;
      for (let index = 0; index < values.length; index += 1) {
        minimum = Math.min(minimum, values[index]);
        maximum = Math.max(maximum, values[index]);
      }
      diagnostics.output = {
        constructor: values.constructor.name,
        shape: output.shape || null,
        length: values.length,
        minimum,
        maximum,
        samples: Array.from(values.slice(0, 8))
      };
    }
    const generated = new ImageData(modelSize, modelSize);
    for (let pixel = 0; pixel < plane; pixel += 1) {
      const rgbaIndex = pixel * 4;
      generated.data[rgbaIndex] = values[pixel];
      generated.data[rgbaIndex + 1] = values[plane + pixel];
      generated.data[rgbaIndex + 2] = values[plane * 2 + pixel];
      generated.data[rgbaIndex + 3] = 255;
    }
    const result = canvasFromImageData(frame.source);
    const patch = document.createElement("canvas");
    patch.width = crop.width;
    patch.height = crop.height;
    const patchContext = patch.getContext("2d");
    patchContext.drawImage(canvasFromImageData(generated), 0, 0, crop.width, crop.height);
    patchContext.globalCompositeOperation = "destination-in";
    patchContext.filter = `blur(${Math.max(1, Math.round(crop.width / 180))}px)`;
    patchContext.drawImage(maskCrop, 0, 0);
    result.getContext("2d").drawImage(patch, crop.x, crop.y);
    return result;
  } finally {
    for (const tensor of Object.values(outputs || {})) tensor.delete?.();
    imageTensor.delete?.();
    maskTensor.delete?.();
  }
}

export async function inpaintLama(session, frame, diagnostics = null) {
  return canvasToBlob(await inpaintLamaCanvas(session, frame, diagnostics));
}
