export const REALITY_ENHANCEMENT_PROFILE = Object.freeze({
  id: "property-reality-v1",
  upscale: 1.25,
  maximumPixels: 12_000_000,
  shadowPercentile: 0.015,
  highlightPercentile: 0.992,
  maximumToneGain: 1.12,
  localContrast: 0.16,
  detailStrength: 0.22,
  vibrance: 0.08,
  whiteBalance: 0.08
});

const clamp = (value, minimum = 0, maximum = 255) =>
  Math.min(maximum, Math.max(minimum, value));

function luminance(red, green, blue) {
  return red * 0.2126 + green * 0.7152 + blue * 0.0722;
}

function percentile(histogram, total, fraction) {
  const target = total * fraction;
  let count = 0;
  for (let index = 0; index < histogram.length; index += 1) {
    count += histogram[index];
    if (count >= target) return index;
  }
  return 255;
}

function boxBlur(values, width, height, radius) {
  const horizontal = new Float32Array(values.length);
  const output = new Float32Array(values.length);
  for (let y = 0; y < height; y += 1) {
    let sum = 0;
    const row = y * width;
    for (let x = -radius; x <= radius; x += 1) {
      sum += values[row + Math.min(width - 1, Math.max(0, x))];
    }
    for (let x = 0; x < width; x += 1) {
      horizontal[row + x] = sum / (radius * 2 + 1);
      sum -= values[row + Math.max(0, x - radius)];
      sum += values[row + Math.min(width - 1, x + radius + 1)];
    }
  }
  for (let x = 0; x < width; x += 1) {
    let sum = 0;
    for (let y = -radius; y <= radius; y += 1) {
      sum += horizontal[Math.min(height - 1, Math.max(0, y)) * width + x];
    }
    for (let y = 0; y < height; y += 1) {
      output[y * width + x] = sum / (radius * 2 + 1);
      sum -= horizontal[Math.max(0, y - radius) * width + x];
      sum += horizontal[Math.min(height - 1, y + radius + 1) * width + x];
    }
  }
  return output;
}

export function enhancementDimensions(width, height, profile = REALITY_ENHANCEMENT_PROFILE) {
  const requestedScale = Math.max(1, Number(profile.upscale) || 1);
  const pixelScale = Math.sqrt(profile.maximumPixels / Math.max(1, width * height));
  const scale = Math.min(requestedScale, Math.max(1, pixelScale));
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
    scale
  };
}

export function enhanceRealityPixels(input, width, height, profile = REALITY_ENHANCEMENT_PROFILE) {
  const pixels = new Uint8ClampedArray(input);
  const count = width * height;
  if (!count || pixels.length !== count * 4) throw new Error("Enhancement pixels do not match their dimensions.");

  const light = new Float32Array(count);
  const histogram = new Uint32Array(256);
  let redMean = 0;
  let greenMean = 0;
  let blueMean = 0;
  for (let index = 0, pixel = 0; pixel < count; pixel += 1, index += 4) {
    const value = luminance(pixels[index], pixels[index + 1], pixels[index + 2]);
    light[pixel] = value;
    histogram[Math.round(value)] += 1;
    redMean += pixels[index];
    greenMean += pixels[index + 1];
    blueMean += pixels[index + 2];
  }

  redMean /= count;
  greenMean /= count;
  blueMean /= count;
  const neutral = (redMean + greenMean + blueMean) / 3;
  const balance = [redMean, greenMean, blueMean].map((mean) =>
    1 + ((neutral / Math.max(1, mean)) - 1) * profile.whiteBalance);
  const black = percentile(histogram, count, profile.shadowPercentile);
  const white = Math.max(black + 32, percentile(histogram, count, profile.highlightPercentile));
  const toneGain = Math.min(profile.maximumToneGain, 255 / (white - black));
  const radius = Math.max(2, Math.min(12, Math.round(Math.min(width, height) / 180)));
  const localMean = boxBlur(light, width, height, radius);

  for (let index = 0, pixel = 0; pixel < count; pixel += 1, index += 4) {
    const originalLight = light[pixel];
    const preservedBlack = black * 0.82;
    const normalizedLight = clamp(preservedBlack + (originalLight - black) * toneGain);
    const localDetail = originalLight - localMean[pixel];
    const edgeLimit = 10 + originalLight * 0.055;
    const detail = clamp(localDetail, -edgeLimit, edgeLimit)
      * (profile.localContrast + profile.detailStrength);
    const targetLight = clamp(normalizedLight + detail);
    const lightScale = targetLight / Math.max(8, originalLight);
    let red = clamp(pixels[index] * balance[0] * lightScale);
    let green = clamp(pixels[index + 1] * balance[1] * lightScale);
    let blue = clamp(pixels[index + 2] * balance[2] * lightScale);
    const average = (red + green + blue) / 3;
    const saturation = Math.max(red, green, blue) - Math.min(red, green, blue);
    const vibrance = profile.vibrance * (1 - saturation / 255);
    red = clamp(average + (red - average) * (1 + vibrance));
    green = clamp(average + (green - average) * (1 + vibrance));
    blue = clamp(average + (blue - average) * (1 + vibrance));
    pixels[index] = red;
    pixels[index + 1] = green;
    pixels[index + 2] = blue;
  }
  return pixels;
}
