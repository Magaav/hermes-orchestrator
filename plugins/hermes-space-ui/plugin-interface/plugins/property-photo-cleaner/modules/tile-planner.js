export function planTiles(bounds, options = {}) {
  const maxTile = Math.max(128, Math.min(options.maxTile || 512, options.lowMemory ? 256 : 512));
  const overlap = Math.max(0, Math.min(options.overlap ?? 32, maxTile / 4));
  const step = maxTile - overlap;
  const tiles = [];
  for (let y = bounds.y; y < bounds.y + bounds.height; y += step) {
    for (let x = bounds.x; x < bounds.x + bounds.width; x += step) {
      tiles.push({
        x, y,
        width: Math.min(maxTile, bounds.x + bounds.width - x),
        height: Math.min(maxTile, bounds.y + bounds.height - y)
      });
    }
  }
  return tiles;
}
