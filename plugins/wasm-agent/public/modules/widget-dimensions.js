function normalizedDimension(value, fallback, min, max) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.round(Math.min(max, Math.max(min, number)));
}

export function widgetDimensionLimits(meta = {}, defaults = {}, surfaceRect = null) {
  const maxSurfaceWidth = Math.max(240, Math.round((surfaceRect?.width || 1800) - 16));
  const maxSurfaceHeight = Math.max(180, Math.round((surfaceRect?.height || 1200) - 16));
  const defaultMinWidth = normalizedDimension(defaults.minWidth, 320, 180, maxSurfaceWidth);
  const defaultMinHeight = normalizedDimension(defaults.minHeight, 220, 120, maxSurfaceHeight);
  const minWidth = normalizedDimension(meta.minWidth, defaultMinWidth, 180, maxSurfaceWidth);
  const minHeight = normalizedDimension(meta.minHeight, defaultMinHeight, 120, maxSurfaceHeight);
  const maxWidth = Math.max(minWidth, normalizedDimension(meta.maxWidth, maxSurfaceWidth, minWidth, Math.max(minWidth, 4000)));
  const maxHeight = Math.max(minHeight, normalizedDimension(meta.maxHeight, maxSurfaceHeight, minHeight, Math.max(minHeight, 3000)));
  return {
    minWidth,
    minHeight,
    maxWidth: Math.min(maxWidth, maxSurfaceWidth),
    maxHeight: Math.min(maxHeight, maxSurfaceHeight),
  };
}
