export function correctionValues(input = {}) {
  return {
    brightness: Number(input.brightness ?? 6),
    contrast: Number(input.contrast ?? 8),
    warmth: Number(input.warmth ?? 2),
    rotation: Number(input.rotation ?? 0)
  };
}

export async function correctImage(bitmap, values, signal) {
  if (signal?.aborted) throw new DOMException("Cancelled", "AbortError");
  const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
  const context = canvas.getContext("2d", { alpha: false, willReadFrequently: false });
  const v = correctionValues(values);
  context.filter = `brightness(${100 + v.brightness}%) contrast(${100 + v.contrast}%) sepia(${Math.max(0, v.warmth)}%)`;
  context.translate(canvas.width / 2, canvas.height / 2);
  context.rotate(v.rotation * Math.PI / 180);
  context.drawImage(bitmap, -bitmap.width / 2, -bitmap.height / 2);
  return canvas.convertToBlob({ type: "image/jpeg", quality: 0.9 });
}
