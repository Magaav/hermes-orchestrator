function chromaEvidence(red, green, blue, minimumChroma) {
  const maximum = Math.max(red, green, blue);
  const minimum = Math.min(red, green, blue);
  if (maximum - minimum < minimumChroma) return null;
  if (red > green * 1.08 && red > blue * 1.08) return "warm";
  if (blue > red * 1.06 && green > red * 1.04) return "cool";
  return null;
}

export function hasWatermarkChromaEvidence(pixels, sampleArea, watermark) {
  let warm = 0;
  let cool = 0;
  for (let index = 0; index < pixels.length; index += 4) {
    const evidence = chromaEvidence(
      pixels[index],
      pixels[index + 1],
      pixels[index + 2],
      watermark.minimumChroma
    );
    if (evidence === "warm") warm += 1;
    if (evidence === "cool") cool += 1;
  }
  const warmRatio = warm / sampleArea;
  const coolRatio = cool / sampleArea;
  return {
    matched: warmRatio >= watermark.minimumWarmRatio && coolRatio >= watermark.minimumCoolRatio,
    warmRatio,
    coolRatio
  };
}

export function recognizeCenteredWatermark(bitmap, profile) {
  const watermark = profile.watermarkRecognition;
  if (!watermark?.enabled) return [];
  const [leftRatio, topRatio, rightRatio, bottomRatio] = watermark.region;
  const x = Math.round(bitmap.width * leftRatio);
  const y = Math.round(bitmap.height * topRatio);
  const width = Math.max(1, Math.round(bitmap.width * (rightRatio - leftRatio)));
  const height = Math.max(1, Math.round(bitmap.height * (bottomRatio - topRatio)));
  const sampleWidth = Math.min(watermark.sampleSize || 192, width);
  const sampleHeight = Math.max(1, Math.round(height * sampleWidth / width));
  const canvas = new OffscreenCanvas(sampleWidth, sampleHeight);
  const context = canvas.getContext("2d", { willReadFrequently: true });
  context.drawImage(bitmap, x, y, width, height, 0, 0, sampleWidth, sampleHeight);
  const pixels = context.getImageData(0, 0, sampleWidth, sampleHeight).data;
  const sampleArea = sampleWidth * sampleHeight;
  const evidence = hasWatermarkChromaEvidence(pixels, sampleArea, watermark);
  if (!evidence.matched) return [];
  return [{
    label: "watermark logo",
    rawLabel: "watermark logo",
    score: Math.min(0.99, watermark.baseScore + evidence.warmRatio + evidence.coolRatio),
    source: "watermark",
    box: { xmin: x, ymin: y, xmax: x + width, ymax: y + height }
  }];
}
