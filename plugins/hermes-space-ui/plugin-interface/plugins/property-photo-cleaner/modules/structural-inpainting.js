function toBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("Could not encode the reconstructed image.")), "image/jpeg", 0.94);
  });
}

function colorDistance(data, leftOffset, rightOffset) {
  return Math.abs(data[leftOffset] - data[rightOffset])
    + Math.abs(data[leftOffset + 1] - data[rightOffset + 1])
    + Math.abs(data[leftOffset + 2] - data[rightOffset + 2]);
}

export async function inpaintStructure(frame) {
  const { source, mask, bounds } = frame;
  const output = new ImageData(new Uint8ClampedArray(source.data), source.width, source.height);
  const leftX = Math.max(0, bounds.x - 1);
  const rightX = Math.min(source.width - 1, bounds.x + bounds.width);
  const topY = Math.max(0, bounds.y - 1);
  const bottomY = Math.min(source.height - 1, bounds.y + bounds.height);
  for (let y = bounds.y; y < bounds.y + bounds.height; y += 1) {
    for (let x = bounds.x; x < bounds.x + bounds.width; x += 1) {
      const offset = (y * source.width + x) * 4;
      if (mask.data[offset + 3] <= 8) continue;
      const leftOffset = (y * source.width + leftX) * 4;
      const rightOffset = (y * source.width + rightX) * 4;
      const topOffset = (topY * source.width + x) * 4;
      const bottomOffset = (bottomY * source.width + x) * 4;
      const horizontalDistance = colorDistance(source.data, leftOffset, rightOffset);
      const verticalDistance = colorDistance(source.data, topOffset, bottomOffset);
      const horizontalRatio = bounds.width <= 1 ? 0.5 : (x - bounds.x) / (bounds.width - 1);
      const verticalRatio = bounds.height <= 1 ? 0.5 : (y - bounds.y) / (bounds.height - 1);
      const useHorizontal = horizontalDistance <= verticalDistance;
      for (let channel = 0; channel < 3; channel += 1) {
        output.data[offset + channel] = useHorizontal
          ? source.data[leftOffset + channel] * (1 - horizontalRatio)
            + source.data[rightOffset + channel] * horizontalRatio
          : source.data[topOffset + channel] * (1 - verticalRatio)
            + source.data[bottomOffset + channel] * verticalRatio;
      }
      output.data[offset + 3] = 255;
    }
  }
  const canvas = document.createElement("canvas");
  canvas.width = source.width;
  canvas.height = source.height;
  canvas.getContext("2d", { alpha: false }).putImageData(output, 0, 0);
  return toBlob(canvas);
}
