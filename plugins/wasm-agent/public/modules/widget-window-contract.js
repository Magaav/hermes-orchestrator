export const WIDGET_RESIZE_DIRECTIONS = Object.freeze(["n", "ne", "e", "se", "s", "sw", "w", "nw"]);

export function ensureWidgetResizeHandles(widget) {
  if (!widget) return [];
  widget.dataset.widgetResizeContract = "screen-anchor-v2";
  const existing = Array.from(widget.querySelectorAll(".widget-resize-handle"));
  const byDirection = new Map(existing.map((handle) => [handle.dataset.resizeDirection || "se", handle]));
  return WIDGET_RESIZE_DIRECTIONS.map((direction) => {
    let handle = byDirection.get(direction);
    if (!handle) {
      handle = document.createElement("div");
      handle.className = "widget-resize-handle";
      handle.setAttribute("aria-hidden", "true");
      widget.append(handle);
    }
    handle.dataset.resizeDirection = direction;
    handle.dataset.widgetResize = widget.dataset.widgetId || "";
    handle.title = `Resize ${direction}`;
    return handle;
  });
}

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

export function resizedWidgetRect(start, direction, deltaX, deltaY, limits = {}, surface = {}) {
  const minWidth = Number(limits.minWidth || 1);
  const minHeight = Number(limits.minHeight || 1);
  const surfaceWidth = Math.max(minWidth, Number(surface.width || Infinity));
  const surfaceHeight = Math.max(minHeight, Number(surface.height || Infinity));
  const startRight = Number(start.left) + Number(start.width);
  const startBottom = Number(start.top) + Number(start.height);
  let left = Number(start.left);
  let top = Number(start.top);
  let right = startRight;
  let bottom = startBottom;

  if (direction.includes("w")) left = clamp(left + deltaX, 0, startRight - minWidth);
  if (direction.includes("e")) right = clamp(right + deltaX, left + minWidth, surfaceWidth);
  if (direction.includes("n")) top = clamp(top + deltaY, 0, startBottom - minHeight);
  if (direction.includes("s")) bottom = clamp(bottom + deltaY, top + minHeight, surfaceHeight);

  const maxWidth = Math.max(minWidth, Number(limits.maxWidth || surfaceWidth));
  const maxHeight = Math.max(minHeight, Number(limits.maxHeight || surfaceHeight));
  if (right - left > maxWidth) {
    if (direction.includes("w")) left = right - maxWidth;
    else right = left + maxWidth;
  }
  if (bottom - top > maxHeight) {
    if (direction.includes("n")) top = bottom - maxHeight;
    else bottom = top + maxHeight;
  }
  return { left, top, width: right - left, height: bottom - top };
}
