const DEFAULT_LIMITS = Object.freeze({
  nearBlackLuma: 12,
  maximumNearBlackRatio: 0.75,
  minimumLumaRange: 18,
  minimumLumaDeviation: 8
});

export function inspectGeneratedPatch(generatedRgba, maskRgba, limits = {}) {
  const policy = { ...DEFAULT_LIMITS, ...limits };
  let count = 0;
  let nearBlack = 0;
  let minimum = 255;
  let maximum = 0;
  let sum = 0;
  let sumSquares = 0;
  for (let offset = 0; offset < maskRgba.length; offset += 4) {
    if (maskRgba[offset + 3] <= 8) continue;
    const luma = Math.round(
      generatedRgba[offset] * 0.2126
      + generatedRgba[offset + 1] * 0.7152
      + generatedRgba[offset + 2] * 0.0722
    );
    count += 1;
    nearBlack += Number(luma <= policy.nearBlackLuma);
    minimum = Math.min(minimum, luma);
    maximum = Math.max(maximum, luma);
    sum += luma;
    sumSquares += luma * luma;
  }
  if (!count) {
    return { accepted: false, failureClass: "empty_mask", maskedPixels: 0 };
  }
  const mean = sum / count;
  const deviation = Math.sqrt(Math.max(0, sumSquares / count - mean * mean));
  const nearBlackRatio = nearBlack / count;
  const lumaRange = maximum - minimum;
  const catastrophicBlack = nearBlackRatio > policy.maximumNearBlackRatio
    && (lumaRange < policy.minimumLumaRange || deviation < policy.minimumLumaDeviation);
  return {
    accepted: !catastrophicBlack,
    failureClass: catastrophicBlack ? "catastrophic_black_patch" : null,
    maskedPixels: count,
    nearBlackRatio,
    lumaRange,
    lumaDeviation: deviation
  };
}

export function assertGeneratedPatch(generatedRgba, maskRgba, limits) {
  const result = inspectGeneratedPatch(generatedRgba, maskRgba, limits);
  if (!result.accepted) {
    const error = new Error(`Generated reconstruction rejected: ${result.failureClass}.`);
    error.code = result.failureClass;
    error.metrics = result;
    throw error;
  }
  return result;
}
