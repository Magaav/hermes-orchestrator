export function homeCleanWidgetLayout(layout = {}, panel = "home") {
  if (panel !== "home") return layout;
  const timeline = layout.timeline && typeof layout.timeline === "object" ? layout.timeline : {};
  return {
    ...layout,
    timeline: { ...timeline, minimized: true, maximized: false },
  };
}

const SPACE_LAYOUT_META_KEYS = new Set(["__canvas", "__apps"]);

export function cloneSpaceWidgetLayout(layout = {}) {
  if (!layout || typeof layout !== "object" || Array.isArray(layout)) return {};
  return Object.fromEntries(Object.entries(layout).map(([key, value]) => [
    key,
    value && typeof value === "object" && !Array.isArray(value) ? { ...value } : value,
  ]));
}

export function mappedWidgetIdsForSpace(layout = {}, availableIds = []) {
  const available = new Set(availableIds);
  if (!layout || typeof layout !== "object" || Array.isArray(layout)) return new Set();
  if (Array.isArray(layout.__apps)) {
    return new Set(layout.__apps.filter((id) => available.has(id)));
  }
  return new Set(Object.entries(layout)
    .filter(([id, value]) => {
      if (SPACE_LAYOUT_META_KEYS.has(id) || !available.has(id)) return false;
      if (!value || typeof value !== "object" || Array.isArray(value)) return false;
      return value.minimized === false
        || value.appOrganized === true
        || value.appOrganized === false
        || ["leftPx", "topPx", "widthPx", "heightPx", "z", "meta"]
          .some((key) => value[key] !== undefined);
    })
    .map(([id]) => id));
}

export function initialVisibleWidgetPosition({ visibleRect, boardRect, widgetRect, distance = 1, inset = 0 } = {}) {
  const scale = Math.max(Number(distance) || 1, 0.01);
  const width = Math.max(0, Number(widgetRect?.width) || 0) / scale;
  const height = Math.max(0, Number(widgetRect?.height) || 0) / scale;
  const visibleLeft = (Number(visibleRect?.left) - Number(boardRect?.left)) / scale;
  const visibleTop = (Number(visibleRect?.top) - Number(boardRect?.top)) / scale;
  const visibleWidth = Math.max(0, Number(visibleRect?.width) || 0) / scale;
  const visibleHeight = Math.max(0, Number(visibleRect?.height) || 0) / scale;
  const boardWidth = Math.max(width, Number(boardRect?.width) / scale || 0);
  const boardHeight = Math.max(height, Number(boardRect?.height) / scale || 0);
  const edge = Math.max(0, Number(inset) || 0);
  return {
    left: Math.round(Math.min(Math.max(edge, visibleLeft + (visibleWidth - width) / 2), Math.max(edge, boardWidth - width - edge))),
    top: Math.round(Math.min(Math.max(edge, visibleTop + (visibleHeight - height) / 2), Math.max(edge, boardHeight - height - edge))),
  };
}

export function appRect(left, top, width, height) {
  return { left, top, right: left + width, bottom: top + height };
}

function appRectsOverlap(a, b, tolerance) {
  const gap = 0;
  return a.left < b.right + gap - tolerance
    && a.right + gap > b.left + tolerance
    && a.top < b.bottom + gap - tolerance
    && a.bottom + gap > b.top + tolerance;
}

export function nearestOpenAppPosition(desiredLeft, desiredTop, width, height, maxLeft, maxTop, occupied = [], { grid = 5, inset = 0, collisionTolerance = Math.ceil(grid / 2) } = {}) {
  const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
  const snap = (value) => Math.round((Number(value) || 0) / grid) * grid;
  const fits = (left, top) => !occupied.some((item) => appRectsOverlap(appRect(left, top, width, height), item, collisionTolerance));
  const startLeft = clamp(Math.round(Number(desiredLeft || 0)), inset, maxLeft);
  const startTop = clamp(Math.round(Number(desiredTop || 0)), inset, maxTop);
  if (fits(startLeft, startTop)) return { left: startLeft, top: startTop };
  const maxRadius = Math.max(maxLeft, maxTop) + width + height;
  for (let radius = grid; radius <= maxRadius; radius += grid) {
    for (let dx = -radius; dx <= radius; dx += grid) {
      for (const dy of [-radius, radius]) {
        const left = clamp(snap(startLeft + dx), inset, maxLeft);
        const top = clamp(snap(startTop + dy), inset, maxTop);
        if (fits(left, top)) return { left, top };
      }
    }
    for (let dy = -radius + grid; dy <= radius - grid; dy += grid) {
      for (const dx of [-radius, radius]) {
        const left = clamp(snap(startLeft + dx), inset, maxLeft);
        const top = clamp(snap(startTop + dy), inset, maxTop);
        if (fits(left, top)) return { left, top };
      }
    }
  }
  return { left: startLeft, top: startTop };
}

export function organizedSpaceAppPositions({ count = 0, boardWidth = 0, boardHeight = 0, visibleWidth = 0, visibleHeight = 0, scrollLeft = 0, scrollTop = 0, topInset = 0, buttonWidth = 62, buttonHeight = 70, grid = 5 } = {}) {
  const total = Math.max(0, Math.floor(Number(count) || 0));
  if (!total) return { positions: [], columns: 0, rows: 0, overflowRows: 0 };
  const width = Math.max(buttonWidth, Number(boardWidth) || 0);
  const height = Math.max(buttonHeight, Number(boardHeight) || 0);
  const viewportWidth = Math.max(1, Number(visibleWidth) || width);
  const viewportHeight = Math.max(1, Number(visibleHeight) || height);
  const columns = Math.min(total, Math.max(1, Math.floor(viewportWidth / buttonWidth)), Math.max(1, Math.floor(width / buttonWidth)));
  const rows = Math.ceil(total / columns);
  const blockWidth = columns * buttonWidth;
  const blockHeight = rows * buttonHeight;
  const snap = (value) => Math.round((Number(value) || 0) / grid) * grid;
  const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
  const startLeft = clamp(snap(scrollLeft), 0, Math.max(0, width - blockWidth));
  const startTop = clamp(snap(Number(scrollTop) + Number(topInset)), 0, Math.max(0, height - blockHeight));
  const positions = Array.from({ length: total }, (_, index) => ({
    left: Math.round(startLeft + (index % columns) * buttonWidth),
    top: Math.round(startTop + Math.floor(index / columns) * buttonHeight),
  }));
  const visibleRows = Math.max(1, Math.floor((viewportHeight - Number(topInset) || viewportHeight) / buttonHeight));
  return { positions, columns, rows, overflowRows: Math.max(0, rows - visibleRows) };
}

export function closeUnpositionedWidgets(layout = {}, widgetIds = []) {
  const next = cloneSpaceWidgetLayout(layout);
  for (const id of widgetIds) {
    const item = next[id] && typeof next[id] === "object" ? { ...next[id] } : {};
    const explicitlyOpen = item.minimized === false;
    if (!explicitlyOpen && (!Number.isFinite(item.leftPx) || !Number.isFinite(item.topPx))) {
      item.minimized = true;
      item.maximized = false;
    }
    next[id] = item;
  }
  return next;
}
