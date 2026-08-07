import { assertGeneratedPatch } from "./reconstruction-quality-gate.js";

const MODEL_SIZE = 512;

function canvasFromImageData(imageData) {
  const canvas = document.createElement("canvas");
  canvas.width = imageData.width;
  canvas.height = imageData.height;
  canvas.getContext("2d").putImageData(imageData, 0, 0);
  return canvas;
}

function cropCanvas(imageData, bounds) {
  const canvas = document.createElement("canvas");
  canvas.width = bounds.width;
  canvas.height = bounds.height;
  canvas.getContext("2d").drawImage(
    canvasFromImageData(imageData),
    bounds.x, bounds.y, bounds.width, bounds.height,
    0, 0, bounds.width, bounds.height
  );
  return canvas;
}

function squareCrop(bounds, imageSize) {
  const desired = Math.max(256, Math.ceil(Math.max(bounds.width, bounds.height) * 2.6));
  const side = Math.min(desired, imageSize.width, imageSize.height);
  const centerX = bounds.x + bounds.width / 2;
  const centerY = bounds.y + bounds.height / 2;
  return {
    x: Math.max(0, Math.min(imageSize.width - side, Math.round(centerX - side / 2))),
    y: Math.max(0, Math.min(imageSize.height - side, Math.round(centerY - side / 2))),
    width: side,
    height: side
  };
}

function resizedRgba(imageData) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = MODEL_SIZE;
  canvas.getContext("2d").drawImage(canvasFromImageData(imageData), 0, 0, MODEL_SIZE, MODEL_SIZE);
  return canvas.getContext("2d").getImageData(0, 0, MODEL_SIZE, MODEL_SIZE).data;
}

export async function inpaintMiganCommunity(session, frame, diagnostics = null) {
  const crop = squareCrop(frame.bounds, frame.source);
  const sourceCrop = cropCanvas(frame.source, crop);
  const maskCrop = cropCanvas(frame.mask, crop);
  const rgba = resizedRgba(sourceCrop.getContext("2d").getImageData(0, 0, crop.width, crop.height));
  const maskRgba = resizedRgba(maskCrop.getContext("2d").getImageData(0, 0, crop.width, crop.height));
  const plane = MODEL_SIZE * MODEL_SIZE;
  const input = new Float32Array(plane * 4);
  for (let pixel = 0; pixel < plane; pixel += 1) {
    const rgbaOffset = pixel * 4;
    const keep = maskRgba[rgbaOffset + 3] > 8 ? 0 : 1;
    input[pixel] = keep - 0.5;
    input[plane + pixel] = (rgba[rgbaOffset] / 127.5 - 1) * keep;
    input[plane * 2 + pixel] = (rgba[rgbaOffset + 1] / 127.5 - 1) * keep;
    input[plane * 3 + pixel] = (rgba[rgbaOffset + 2] / 127.5 - 1) * keep;
  }

  const inputTensor = session.tensor(input, [1, 4, MODEL_SIZE, MODEL_SIZE]);
  let outputs;
  try {
    const startedAt = performance.now();
    outputs = await session.run({ args_0: inputTensor });
    const output = outputs.output_0 || Object.values(outputs)[0];
    const generatedValues = await output.toTypedArray();
    const generated = new ImageData(MODEL_SIZE, MODEL_SIZE);
    for (let pixel = 0; pixel < plane; pixel += 1) {
      const rgbaOffset = pixel * 4;
      const keep = maskRgba[rgbaOffset + 3] > 8 ? 0 : 1;
      for (let channel = 0; channel < 3; channel += 1) {
        const source = rgba[rgbaOffset + channel] / 127.5 - 1;
        const value = source * keep + generatedValues[channel * plane + pixel] * (1 - keep);
        generated.data[rgbaOffset + channel] = Math.max(0, Math.min(255, Math.round((value + 1) * 127.5)));
      }
      generated.data[rgbaOffset + 3] = 255;
    }
    const quality = assertGeneratedPatch(generated.data, maskRgba);
    if (diagnostics) {
      diagnostics.inferenceMs = Math.round(performance.now() - startedAt);
      diagnostics.quality = quality;
    }

    const result = canvasFromImageData(frame.source);
    const patch = document.createElement("canvas");
    patch.width = crop.width;
    patch.height = crop.height;
    const patchContext = patch.getContext("2d");
    patchContext.drawImage(canvasFromImageData(generated), 0, 0, crop.width, crop.height);
    patchContext.globalCompositeOperation = "destination-in";
    patchContext.filter = `blur(${Math.max(1, Math.round(crop.width / 160))}px)`;
    patchContext.drawImage(maskCrop, 0, 0);
    result.getContext("2d").drawImage(patch, crop.x, crop.y);
    return result;
  } finally {
    if (outputs) for (const tensor of Object.values(outputs)) tensor.delete?.();
    inputTensor.delete?.();
  }
}
