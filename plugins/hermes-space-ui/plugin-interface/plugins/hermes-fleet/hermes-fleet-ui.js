const RUNTIME_KEY = "__hermesFleetUiRuntime";
const CARD_SELECTOR = ".spaces-widget-card[data-widget-id]";
const GRID_SELECTOR = ".spaces-widget-grid";
const LAYER_CLASS = "hermes-fleet-space-layer";
const APP_BUTTON_LAYER_CLASS = "hermes-fleet-app-button-layer";
const WIDGET_LAYER_CLASS = "hermes-fleet-widget-layer";
const RESTORE_BUTTON_LABEL = "Restore widget";
const RELOAD_BUTTON_LABEL = "Reload widget";
const RESTORING_WIDGET_IDS = new Set();
const FALLBACK_RESTORE_BUTTONS = new WeakSet();
const RESOLVING_SPACE_ROUTE_IDS = new Set();
const SPACE_ALIAS_STORAGE_KEY = "hermesFleet.spaceAliases.v1";
const SPACES_ROUTE_PATH = "/spaces";
const SPACE_URL_SYNC_DELAY_MS = 80;
const SPACE_ID_ALIASES = Object.freeze({
  "hermes-fleet": "hermes-os"
});
const APP_ICON_DRAG_THRESHOLD_PX = 6;
const APP_ICON_RECENT_DRAG_MS = 260;
const APP_ICON_DRAG_RELEASE_POSITION_MS = 1400;
const APP_ICON_SETTLE_MS = 240;
const APP_ICON_LAYOUT_SYNC_DELAY_MS = 180;
const APP_ICON_ORIGINAL_SIZES_KEY = "hermesFleet.appIconOriginalSizes.v1";
const APP_ICON_POSITIONS_KEY = "hermesFleet.appIconPositions.v1";
const APP_ICON_LAYOUT_SIZE = Object.freeze({ cols: 1, rows: 1 });
const ICON_BY_WIDGET_ID = {
  "drop-to-copy": "auto_awesome_motion",
  "hermes-os": "monitor_heart",
  "hermes-topology": "hub"
};
const APP_ICON_LAYOUT_SYNC_TIMERS = new Map();
const APP_ICON_LAYOUT_SYNCING = new Set();
const APP_ICON_LAYOUT_KNOWN_COMPACT = new Set();
const APP_ICON_POSITION_STORAGE_SEEDED = new Set();
const APP_ICON_GRID_ORIGINS = new WeakMap();
const APP_ICON_DRAG_RELEASES = new Map();
const APP_ICON_SETTLE_TIMERS = new WeakMap();
const APP_ICON_SETTLE_TIMER_IDS = new Set();
const APP_ICON_MINIMIZED_STATE = new WeakMap();
let appIconLayoutWritePromise = Promise.resolve();

function iconForWidget(widgetId) {
  const id = String(widgetId || "");
  if (ICON_BY_WIDGET_ID[id]) return ICON_BY_WIDGET_ID[id];
  if (id.startsWith("drop-copy-build")) return "construction";
  if (id.startsWith("drop-copy-result")) return "article";
  return "widgets";
}

function titleForCard(card) {
  return String(card?.querySelector?.(".spaces-widget-card-title")?.textContent || card?.dataset?.widgetId || "Widget").trim();
}

function normalizePositiveInteger(value, fallback = 0) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < 1) return fallback;
  return Math.min(24, parsed);
}

function normalizeWidgetSizeValue(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;

  const cols = normalizePositiveInteger(value.cols ?? value.columns ?? value.width, 0);
  const rows = normalizePositiveInteger(value.rows ?? value.height, 0);
  if (!cols || !rows) return null;

  return { cols, rows };
}

function normalizeWidgetPositionValue(value) {
  if (typeof value === "string") {
    const match = value.trim().match(/^(-?\d+)\s*,\s*(-?\d+)$/u);
    if (match) {
      return {
        col: Number.parseInt(match[1], 10),
        row: Number.parseInt(match[2], 10)
      };
    }
  }

  if (Array.isArray(value) && value.length >= 2) {
    value = { col: value[0], row: value[1] };
  }

  if (!value || typeof value !== "object") return null;

  const col = Number.parseInt(value.col ?? value.x, 10);
  const row = Number.parseInt(value.row ?? value.y, 10);
  if (!Number.isFinite(col) || !Number.isFinite(row)) return null;

  return {
    col: Math.max(-500, Math.min(500, col)),
    row: Math.max(-500, Math.min(500, row))
  };
}

function widgetSizesMatch(left, right) {
  const leftSize = normalizeWidgetSizeValue(left);
  const rightSize = normalizeWidgetSizeValue(right);
  return Boolean(leftSize && rightSize && leftSize.cols === rightSize.cols && leftSize.rows === rightSize.rows);
}

function widgetPositionsMatch(left, right) {
  const leftPosition = normalizeWidgetPositionValue(left);
  const rightPosition = normalizeWidgetPositionValue(right);
  return Boolean(leftPosition && rightPosition && leftPosition.col === rightPosition.col && leftPosition.row === rightPosition.row);
}

function isAppIconLayoutSize(size) {
  return widgetSizesMatch(size, APP_ICON_LAYOUT_SIZE);
}

function widgetSizeStorageKey(spaceId, widgetId) {
  return `${spaceId || ""}::${widgetId || ""}`;
}

function widgetPositionStorageKey(spaceId, widgetId) {
  return `${spaceId || ""}::${widgetId || ""}`;
}

function monotonicNow() {
  return globalThis.performance?.now?.() ?? Date.now();
}

function markAppIconDragRelease(spaceId, widgetId, position = null) {
  const key = widgetPositionStorageKey(spaceId, widgetId);
  if (!spaceId || !widgetId || !key) return;

  APP_ICON_DRAG_RELEASES.set(key, {
    expiresAt: monotonicNow() + APP_ICON_DRAG_RELEASE_POSITION_MS,
    position: normalizeWidgetPositionValue(position)
  });
}

function getAppIconDragRelease(spaceId, widgetId) {
  const key = widgetPositionStorageKey(spaceId, widgetId);
  const release = APP_ICON_DRAG_RELEASES.get(key);
  if (!release) return null;

  const expiresAt = typeof release === "number" ? release : release.expiresAt;
  if (!Number.isFinite(expiresAt)) {
    APP_ICON_DRAG_RELEASES.delete(key);
    return null;
  }

  if (expiresAt < monotonicNow()) {
    APP_ICON_DRAG_RELEASES.delete(key);
    return null;
  }

  return {
    expiresAt,
    position: normalizeWidgetPositionValue(release.position)
  };
}

function readJsonRecord(storageKey) {
  try {
    const parsed = JSON.parse(globalThis.localStorage?.getItem(storageKey) || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function writeJsonRecord(storageKey, record) {
  try {
    globalThis.localStorage?.setItem(storageKey, JSON.stringify(record));
  } catch {
    // Browser storage is best-effort; persisted Space Agent layout remains the fallback.
  }
}

function readAppIconOriginalSizes() {
  return readJsonRecord(APP_ICON_ORIGINAL_SIZES_KEY);
}

function writeAppIconOriginalSizes(sizes) {
  writeJsonRecord(APP_ICON_ORIGINAL_SIZES_KEY, sizes);
}

function rememberOriginalWidgetSize(spaceId, widgetId, size) {
  const normalizedSize = normalizeWidgetSizeValue(size);
  const normalizedSpaceId = String(spaceId || "").trim();
  const normalizedWidgetId = String(widgetId || "").trim();
  if (!normalizedSpaceId || !normalizedWidgetId || !normalizedSize) return;

  const sizes = readAppIconOriginalSizes();
  sizes[widgetSizeStorageKey(normalizedSpaceId, normalizedWidgetId)] = normalizedSize;
  writeAppIconOriginalSizes(sizes);
}

function getRememberedOriginalWidgetSize(spaceId, widgetId) {
  return normalizeWidgetSizeValue(readAppIconOriginalSizes()[widgetSizeStorageKey(spaceId, widgetId)]);
}

function readAppIconPositions() {
  return readJsonRecord(APP_ICON_POSITIONS_KEY);
}

function writeAppIconPositions(positions) {
  writeJsonRecord(APP_ICON_POSITIONS_KEY, positions);
}

function rememberAppIconPosition(spaceId, widgetId, position, options = {}) {
  const normalizedPosition = normalizeWidgetPositionValue(position);
  const normalizedSpaceId = String(spaceId || "").trim();
  const normalizedWidgetId = String(widgetId || "").trim();
  if (!normalizedSpaceId || !normalizedWidgetId || !normalizedPosition) return;

  const positions = readAppIconPositions();
  const key = widgetPositionStorageKey(normalizedSpaceId, normalizedWidgetId);
  const previousPosition = normalizeWidgetPositionValue(positions[key]);
  if (!options.force && previousPosition) return;

  positions[key] = normalizedPosition;
  writeAppIconPositions(positions);
  if (options.force || !widgetPositionsMatch(previousPosition, normalizedPosition)) {
    APP_ICON_LAYOUT_KNOWN_COMPACT.delete(appIconLayoutSyncKey(normalizedSpaceId, normalizedWidgetId));
  }
}

function getRememberedAppIconPosition(spaceId, widgetId) {
  return normalizeWidgetPositionValue(readAppIconPositions()[widgetPositionStorageKey(spaceId, widgetId)]);
}

function cloneRecordMap(map) {
  return map && typeof map === "object" && !Array.isArray(map) ? { ...map } : {};
}

function cloneRecordList(list) {
  return Array.isArray(list) ? [...list] : [];
}

function findDirectLayer(grid, layerClass) {
  return Array.from(grid?.children || []).find((child) => child.classList?.contains(layerClass)) || null;
}

function roundFrameValue(value) {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) return 0;
  return Math.round(parsed * 100) / 100;
}

function frameSignature(frame) {
  if (!frame) return "";
  return [
    roundFrameValue(frame.left),
    roundFrameValue(frame.top),
    roundFrameValue(frame.width),
    roundFrameValue(frame.height)
  ].join(",");
}

function getInlineCardFrame(card) {
  const left = parsePixelValue(card?.style?.left, NaN);
  const top = parsePixelValue(card?.style?.top, NaN);
  const width = parsePixelValue(card?.style?.width, NaN);
  const height = parsePixelValue(card?.style?.height, NaN);
  if (![left, top, width, height].every(Number.isFinite)) return null;

  return { height, left, top, width };
}

function cardHasAppliedPreferredFrame(card) {
  const appliedFrame = String(card?.dataset?.hermesFleetAppliedFrame || "");
  if (!appliedFrame) return false;
  return frameSignature(getInlineCardFrame(card)) === appliedFrame;
}

function setStylePixelIfChanged(element, propertyName, value) {
  if (!element?.style) return false;

  const nextValue = roundFrameValue(value);
  const currentValue = parsePixelValue(element.style[propertyName], NaN);
  if (Number.isFinite(currentValue) && Math.abs(currentValue - nextValue) < 0.01) {
    return false;
  }

  element.style[propertyName] = `${nextValue}px`;
  return true;
}

function applyPreferredFrame(card, frame) {
  if (!card || !frame) return false;

  const nextFrame = {
    height: roundFrameValue(frame.height),
    left: roundFrameValue(frame.left),
    top: roundFrameValue(frame.top),
    width: roundFrameValue(frame.width)
  };
  let changed = false;
  changed = setStylePixelIfChanged(card, "left", nextFrame.left) || changed;
  changed = setStylePixelIfChanged(card, "top", nextFrame.top) || changed;
  changed = setStylePixelIfChanged(card, "width", nextFrame.width) || changed;
  changed = setStylePixelIfChanged(card, "height", nextFrame.height) || changed;
  card.dataset.hermesFleetAppliedFrame = frameSignature(nextFrame);
  return changed;
}

function ensureSpaceLayers(grid) {
  if (!(grid instanceof Element)) return null;

  let appButtonLayer = findDirectLayer(grid, APP_BUTTON_LAYER_CLASS);
  let widgetLayer = findDirectLayer(grid, WIDGET_LAYER_CLASS);

  if (!appButtonLayer) {
    appButtonLayer = document.createElement("div");
    appButtonLayer.className = `${LAYER_CLASS} ${APP_BUTTON_LAYER_CLASS}`;
    appButtonLayer.dataset.hermesFleetSpaceLayer = "app-buttons";
    grid.prepend(appButtonLayer);
  }

  if (!widgetLayer) {
    widgetLayer = document.createElement("div");
    widgetLayer.className = `${LAYER_CLASS} ${WIDGET_LAYER_CLASS}`;
    widgetLayer.dataset.hermesFleetSpaceLayer = "widgets";
    appButtonLayer.after(widgetLayer);
  }

  return { appButtonLayer, widgetLayer };
}

function moveCardToSpaceLayer(card, layerName) {
  const grid = card?.closest?.(GRID_SELECTOR);
  const layers = ensureSpaceLayers(grid);
  if (!layers) return;

  const targetLayer = layerName === "app-button" ? layers.appButtonLayer : layers.widgetLayer;
  if (card.parentElement !== targetLayer) {
    targetLayer.append(card);
  }
}

function removeWidgetReloadButtons(root = document) {
  if (root instanceof Element) {
    const label = `${root.getAttribute("title") || ""} ${root.getAttribute("aria-label") || ""}`;
    if (
      root.matches(".spaces-widget-reload-button") ||
      (root.matches("button") && label.toLowerCase().includes(RELOAD_BUTTON_LABEL.toLowerCase()))
    ) {
      root.remove();
      return;
    }
  }

  root.querySelectorAll?.(".spaces-widget-reload-button").forEach((button) => button.remove());
  root.querySelectorAll?.("button").forEach((button) => {
    const label = `${button.getAttribute("title") || ""} ${button.getAttribute("aria-label") || ""}`;
    if (label.toLowerCase().includes(RELOAD_BUTTON_LABEL.toLowerCase())) button.remove();
  });
}

function unwrapSpaceLayers() {
  document.querySelectorAll(`.${LAYER_CLASS}`).forEach((layer) => {
    const parent = layer.parentElement;
    if (!parent) {
      layer.remove();
      return;
    }

    while (layer.firstChild) {
      parent.insertBefore(layer.firstChild, layer);
    }
    layer.remove();
  });
}

function parsePixelValue(value, fallback = 0) {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function resolveCssLength(value, contextElement, fallback = 0) {
  const normalizedValue = String(value || "").trim();
  const numericValue = Number.parseFloat(normalizedValue);
  if (!Number.isFinite(numericValue)) return fallback;
  if (normalizedValue.endsWith("px") || /^-?\d+(?:\.\d+)?$/u.test(normalizedValue)) return numericValue;

  const rootFontSize = parsePixelValue(globalThis.getComputedStyle?.(document.documentElement)?.fontSize, 16);
  if (normalizedValue.endsWith("rem")) return numericValue * rootFontSize;

  if (normalizedValue.endsWith("em")) {
    const contextFontSize = parsePixelValue(globalThis.getComputedStyle?.(contextElement)?.fontSize, rootFontSize);
    return numericValue * contextFontSize;
  }

  return fallback;
}

function readGridMetrics(grid) {
  const style = globalThis.getComputedStyle?.(grid);
  const columnGap = resolveCssLength(style?.getPropertyValue("--spaces-grid-gap"), grid, 16);
  const rowHeight = resolveCssLength(style?.getPropertyValue("--spaces-grid-row-height"), grid, 74);
  const rect = grid.getBoundingClientRect();
  const viewportElement = grid.parentElement || grid;

  return {
    colStep: rowHeight + columnGap,
    colWidth: rowHeight,
    rect,
    rowHeight,
    rowStep: rowHeight + columnGap,
    viewportHeight: Math.max(1, viewportElement.clientHeight || rect.height),
    viewportWidth: Math.max(1, viewportElement.clientWidth || rect.width)
  };
}

function getCardFrame(card) {
  const left = parsePixelValue(card?.style?.left, NaN);
  const top = parsePixelValue(card?.style?.top, NaN);
  if (!Number.isFinite(left) || !Number.isFinite(top)) return null;

  return { left, top };
}

function resolveOriginFromCards(cards, metrics) {
  for (const card of cards) {
    const frame = getCardFrame(card);
    const position = getRuntimeWidgetPosition(widgetIdForCard(card));
    if (!frame || !position) continue;

    return {
      x: frame.left - (position.col * metrics.colStep),
      y: frame.top - (position.row * metrics.rowStep)
    };
  }

  return null;
}

function getRuntimeWidgetPosition(widgetId) {
  const descriptor = getRuntimeWidgetDescriptor(widgetId);
  return normalizeWidgetPositionValue(descriptor?.position || {
    col: descriptor?.col,
    row: descriptor?.row
  });
}

function resolveGridOrigin(grid, metrics) {
  const cards = Array.from(grid?.querySelectorAll?.(CARD_SELECTOR) || []);
  const runtimeAnchors = cards.filter((card) => !cardHasAppliedPreferredFrame(card));
  const orderedRuntimeAnchors = [
    ...runtimeAnchors.filter((card) => !card.classList.contains("is-minimized")),
    ...runtimeAnchors.filter((card) => card.classList.contains("is-minimized"))
  ];
  const runtimeOrigin = resolveOriginFromCards(orderedRuntimeAnchors, metrics);
  if (runtimeOrigin) {
    APP_ICON_GRID_ORIGINS.set(grid, runtimeOrigin);
    return runtimeOrigin;
  }

  const cachedOrigin = APP_ICON_GRID_ORIGINS.get(grid);
  if (cachedOrigin) return cachedOrigin;

  const fallbackOrigin = resolveOriginFromCards(
    [
      ...cards.filter((card) => !card.classList.contains("is-minimized")),
      ...cards.filter((card) => card.classList.contains("is-minimized"))
    ],
    metrics
  ) || {
    x: metrics.viewportWidth / 2,
    y: metrics.viewportHeight / 2
  };
  APP_ICON_GRID_ORIGINS.set(grid, fallbackOrigin);
  return fallbackOrigin;
}

function positionFromAppIconFrame(frame, origin, metrics) {
  if (!frame || !origin || !metrics) return null;

  const colStep = Math.max(1, Number(metrics.colStep) || 0);
  const rowStep = Math.max(1, Number(metrics.rowStep) || 0);
  return normalizeWidgetPositionValue({
    col: Math.round((frame.left - origin.x) / colStep),
    row: Math.round((frame.top - origin.y) / rowStep)
  });
}

function appIconFrameForPosition(position, origin, metrics) {
  const normalizedPosition = normalizeWidgetPositionValue(position);
  if (!normalizedPosition || !origin || !metrics) return null;

  return {
    height: metrics.rowHeight,
    left: origin.x + (normalizedPosition.col * metrics.colStep),
    top: origin.y + (normalizedPosition.row * metrics.rowStep),
    width: metrics.colWidth
  };
}

function getVisualAppIconPosition(card) {
  const frame = getInlineCardFrame(card);
  const grid = card?.closest?.(GRID_SELECTOR);
  if (!frame || !grid) return null;

  const metrics = readGridMetrics(grid);
  const origin = resolveGridOrigin(grid, metrics);
  return positionFromAppIconFrame(frame, origin, metrics);
}

async function seedAppIconPositionFromStorage(spaceId, widgetId) {
  const key = widgetPositionStorageKey(spaceId, widgetId);
  if (APP_ICON_POSITION_STORAGE_SEEDED.has(key)) return;
  APP_ICON_POSITION_STORAGE_SEEDED.add(key);

  const spaces = getSpacesRuntime();
  if (typeof spaces?.readSpace !== "function") return;

  try {
    const spaceRecord = await spaces.readSpace(spaceId);
    const storedPosition = normalizeWidgetPositionValue(spaceRecord?.widgetPositions?.[widgetId]);
    if (!storedPosition) return;

    rememberAppIconPosition(spaceId, widgetId, storedPosition, { force: true });
    globalThis.requestAnimationFrame?.(() => refreshIcons());
  } catch {
    // Runtime position seeding below is enough when the storage read is unavailable.
  }
}

function applyPreferredAppIconFrame(card, options = {}) {
  if (!card?.classList?.contains("is-minimized") || card.classList.contains("is-layout-active")) return;
  if (card.dataset?.hermesFleetDragging === "true") return;

  const widgetId = widgetIdForCard(card);
  const spaceId = getCurrentSpaceId();
  if (!spaceId || !widgetId) return;

  const runtimePosition = getRuntimeWidgetPosition(widgetId);
  const recentRelease = getAppIconDragRelease(spaceId, widgetId);
  const releasePosition = recentRelease?.position || null;
  const forceRuntimePosition = Boolean(options.forceRuntimePosition) || Boolean(recentRelease && !releasePosition);
  if (releasePosition) {
    rememberAppIconPosition(spaceId, widgetId, releasePosition, { force: true });
  } else {
    rememberAppIconPosition(spaceId, widgetId, runtimePosition, {
      force: forceRuntimePosition
    });
  }
  if (!forceRuntimePosition && !releasePosition) void seedAppIconPositionFromStorage(spaceId, widgetId);

  const preferredPosition =
    releasePosition ||
    (forceRuntimePosition && runtimePosition) ||
    getRememberedAppIconPosition(spaceId, widgetId);
  const grid = card.closest(GRID_SELECTOR);
  if (!preferredPosition || !grid) return;

  const metrics = readGridMetrics(grid);
  const origin = resolveGridOrigin(grid, metrics);
  const preferredFrame = {
    height: metrics.rowHeight,
    left: origin.x + (preferredPosition.col * metrics.colStep),
    top: origin.y + (preferredPosition.row * metrics.rowStep),
    width: metrics.colWidth
  };
  card.dataset.hermesFleetPositionSource = "app-icon-preferred";
  applyPreferredFrame(card, preferredFrame);
}

function ensureIcon(card) {
  removeWidgetReloadButtons(card);

  const widgetId = widgetIdForCard(card);
  const spaceId = getCurrentSpaceId();
  const isMinimized = Boolean(card?.classList?.contains("is-minimized"));
  const runtimeSize = normalizeWidgetSizeValue(getRuntimeWidgetDescriptor(widgetId)?.size);
  const minimizedWithExpandedRuntimeSize = Boolean(isMinimized && runtimeSize && !isAppIconLayoutSize(runtimeSize));
  const minimizedFromExpanded =
    isMinimized &&
    (APP_ICON_MINIMIZED_STATE.get(card) === false || minimizedWithExpandedRuntimeSize);

  if (card?.dataset) {
    const layerName = isMinimized ? "app-button" : "widget";
    card.dataset.hermesFleetCardLayer = layerName;
    moveCardToSpaceLayer(card, layerName);
    if (layerName === "widget") {
      card?.removeAttribute?.("data-hermes-fleet-position-source");
      card?.removeAttribute?.("data-hermes-fleet-applied-frame");
    }
  }

  if (!isMinimized) {
    APP_ICON_MINIMIZED_STATE.set(card, false);
    const wasAppIcon = card?.dataset?.hermesFleetAppIcon === "true";
    card?.removeAttribute?.("data-hermes-fleet-app-icon");
    card?.removeAttribute?.("data-hermes-fleet-restoring");
    card?.removeAttribute?.("data-hermes-fleet-dragging");
    card?.removeAttribute?.("data-hermes-fleet-pressed");
    clearAppIconSettling(card);
    if (wasAppIcon) {
      const widgetId = widgetIdForCard(card);
      if (widgetId) void restoreExpandedAppIconSize(widgetId);
      card?.removeAttribute?.("aria-label");
      card?.removeAttribute?.("role");
      card?.removeAttribute?.("tabindex");
      card?.removeAttribute?.("title");
    }
    card?.querySelector?.(".hermes-fleet-minimized-icon")?.remove();
    card?.querySelector?.(".hermes-fleet-drag-glyph")?.remove();
    return;
  }

  const controls = card.querySelector(".spaces-widget-card-controls");
  if (!controls) return;

  let icon = controls.querySelector(".hermes-fleet-minimized-icon");
  if (!icon) {
    icon = document.createElement("span");
    icon.className = "hermes-fleet-minimized-icon";
    icon.setAttribute("aria-hidden", "true");
    controls.append(icon);
  }

  const glyphName = iconForWidget(card.dataset.widgetId);
  let glyph = icon.querySelector("x-icon");
  if (!glyph) {
    glyph = document.createElement("x-icon");
    icon.append(glyph);
  }
  if (glyph.textContent !== glyphName) glyph.textContent = glyphName;

  const dragHandle = card.querySelector(".spaces-widget-drag-handle");
  if (dragHandle && !dragHandle.querySelector(".hermes-fleet-drag-glyph")) {
    const dragGlyph = document.createElement("span");
    dragGlyph.className = "hermes-fleet-drag-glyph";
    dragGlyph.setAttribute("aria-hidden", "true");

    const dragIcon = document.createElement("x-icon");
    dragIcon.textContent = "drag_indicator";
    dragGlyph.append(dragIcon);
    dragHandle.append(dragGlyph);
  }

  const title = titleForCard(card);
  card.dataset.hermesFleetAppIcon = "true";
  card.title = `Open ${title}`;
  card.setAttribute("aria-label", `Open ${title}`);
  card.setAttribute("role", "button");
  card.setAttribute("tabindex", "0");
  if (minimizedFromExpanded) {
    markAppIconDragRelease(spaceId, widgetId);
  }
  applyPreferredAppIconFrame(card, {
    forceRuntimePosition: minimizedFromExpanded
  });
  APP_ICON_MINIMIZED_STATE.set(card, true);
  scheduleAppIconLayoutSync(card);
  if (minimizedFromExpanded) {
    scheduleAppIconLayoutVerification(card, spaceId, widgetId, 700);
    scheduleAppIconLayoutVerification(card, spaceId, widgetId, 1400);
  }
}

function refreshIcons(root = document) {
  removeWidgetReloadButtons(root);
  root.querySelectorAll?.(CARD_SELECTOR).forEach(ensureIcon);
}

function minimizedCardFromTarget(target) {
  if (!(target instanceof Element)) return null;
  const card = target.closest(CARD_SELECTOR);
  if (!card?.classList?.contains("is-minimized")) return null;
  return card;
}

function widgetIdForCard(card) {
  return String(card?.dataset?.widgetId || "").trim();
}

function getSpacesRuntime() {
  const spaces = globalThis.space?.spaces;
  return spaces && typeof spaces === "object" ? spaces : null;
}

function getCurrentRuntime() {
  const current = globalThis.space?.current || globalThis.space?.spaces?.current;
  return current && typeof current === "object" ? current : null;
}

function getCurrentSpaceId() {
  const spaces = getSpacesRuntime();
  const current = getCurrentRuntime();
  return String(spaces?.currentId || current?.id || "").trim();
}

function getRuntimeWidgetDescriptor(widgetId) {
  const normalizedWidgetId = String(widgetId || "").trim();
  if (!normalizedWidgetId) return null;

  const current = getCurrentRuntime();
  return (
    current?.byId?.[normalizedWidgetId] ||
    (Array.isArray(current?.widgets) ? current.widgets.find((widget) => widget?.id === normalizedWidgetId) : null) ||
    null
  );
}

function getSpaceRecordWidgetSize(spaceRecord, widgetId) {
  const widgetRecord = spaceRecord?.widgets?.[widgetId];
  return (
    normalizeWidgetSizeValue(spaceRecord?.widgetSizes?.[widgetId]) ||
    normalizeWidgetSizeValue(widgetRecord?.defaultSize) ||
    normalizeWidgetSizeValue(widgetRecord) ||
    normalizeWidgetSizeValue(getRuntimeWidgetDescriptor(widgetId)?.size)
  );
}

function getSpaceRecordDefaultWidgetSize(spaceRecord, widgetId) {
  const widgetRecord = spaceRecord?.widgets?.[widgetId];
  return (
    normalizeWidgetSizeValue(widgetRecord?.defaultSize) ||
    normalizeWidgetSizeValue(widgetRecord) ||
    normalizeWidgetSizeValue(getRuntimeWidgetDescriptor(widgetId)?.size)
  );
}

function buildSaveLayoutPayload(spaceRecord, overrides = {}) {
  const payload = {
    id: String(overrides.id || spaceRecord?.id || getCurrentSpaceId()).trim()
  };

  const widgetIds = cloneRecordList(overrides.widgetIds ?? spaceRecord?.widgetIds);
  if (widgetIds.length) payload.widgetIds = widgetIds;

  const minimizedWidgetIds = cloneRecordList(overrides.minimizedWidgetIds ?? spaceRecord?.minimizedWidgetIds);
  if (Array.isArray(overrides.minimizedWidgetIds) || Array.isArray(spaceRecord?.minimizedWidgetIds)) {
    payload.minimizedWidgetIds = minimizedWidgetIds;
  }

  const widgetPositions = cloneRecordMap(overrides.widgetPositions ?? spaceRecord?.widgetPositions);
  if (overrides.widgetPositions || spaceRecord?.widgetPositions) payload.widgetPositions = widgetPositions;

  const widgetSizes = cloneRecordMap(overrides.widgetSizes ?? spaceRecord?.widgetSizes);
  if (overrides.widgetSizes || spaceRecord?.widgetSizes) payload.widgetSizes = widgetSizes;

  return payload;
}

function canSaveSpaceLayout(spaces) {
  return typeof spaces?.readSpace === "function" && typeof spaces?.saveSpaceLayout === "function";
}

function appIconLayoutSyncKey(spaceId, widgetId) {
  return `${spaceId || ""}:${widgetId || ""}`;
}

function enqueueAppIconLayoutWrite(task) {
  const nextWrite = appIconLayoutWritePromise.catch(() => {}).then(task);
  appIconLayoutWritePromise = nextWrite.catch(() => {});
  return nextWrite;
}

function scheduleAppIconLayoutSync(card) {
  const widgetId = widgetIdForCard(card);
  const spaceId = getCurrentSpaceId();
  if (!card?.isConnected || !widgetId || !spaceId) return;

  const key = appIconLayoutSyncKey(spaceId, widgetId);
  if (APP_ICON_LAYOUT_KNOWN_COMPACT.has(key)) return;

  clearTimeout(APP_ICON_LAYOUT_SYNC_TIMERS.get(key));
  APP_ICON_LAYOUT_SYNC_TIMERS.set(
    key,
    setTimeout(() => {
      APP_ICON_LAYOUT_SYNC_TIMERS.delete(key);
      void compactAppIconLayout(card, spaceId, widgetId);
    }, APP_ICON_LAYOUT_SYNC_DELAY_MS)
  );
}

function scheduleAppIconLayoutVerification(card, spaceId, widgetId, delayMs) {
  const key = appIconLayoutSyncKey(spaceId, widgetId);
  if (!card?.isConnected || !spaceId || !widgetId || !key) return;

  const timerKey = `${key}:verify:${delayMs}`;
  clearTimeout(APP_ICON_LAYOUT_SYNC_TIMERS.get(timerKey));
  APP_ICON_LAYOUT_SYNC_TIMERS.set(
    timerKey,
    setTimeout(() => {
      APP_ICON_LAYOUT_SYNC_TIMERS.delete(timerKey);
      APP_ICON_LAYOUT_KNOWN_COMPACT.delete(key);
      void compactAppIconLayout(card, spaceId, widgetId);
    }, delayMs)
  );
}

async function compactAppIconLayout(card, spaceId, widgetId, options = {}) {
  const key = appIconLayoutSyncKey(spaceId, widgetId);
  if ((APP_ICON_LAYOUT_SYNCING.has(key) && !options.force) || RESTORING_WIDGET_IDS.has(widgetId)) return false;
  if (!card?.isConnected || !card.classList.contains("is-minimized")) return false;
  if (card.dataset?.hermesFleetDragging === "true" && !options.force) return false;

  const spaces = getSpacesRuntime();
  if (!canSaveSpaceLayout(spaces)) return false;

  APP_ICON_LAYOUT_SYNCING.add(key);
  try {
    return await enqueueAppIconLayoutWrite(async () => {
      const spaceRecord = await spaces.readSpace(spaceId);
      if (!spaceRecord?.minimizedWidgetIds?.includes(widgetId)) return false;

      const currentSize = getSpaceRecordWidgetSize(spaceRecord, widgetId);
      const runtimePosition = getRuntimeWidgetPosition(widgetId);
      const storedPosition = normalizeWidgetPositionValue(spaceRecord?.widgetPositions?.[widgetId]);
      const targetPosition =
        normalizeWidgetPositionValue(options.position) ||
        getVisualAppIconPosition(card) ||
        getRememberedAppIconPosition(spaceId, widgetId) ||
        runtimePosition ||
        storedPosition;
      const shouldSaveTargetPosition = Boolean(targetPosition && !widgetPositionsMatch(targetPosition, storedPosition));
      if (!currentSize) return false;
      if (!isAppIconLayoutSize(currentSize)) {
        rememberOriginalWidgetSize(spaceId, widgetId, currentSize);
      }
      if (isAppIconLayoutSize(currentSize) && !shouldSaveTargetPosition) {
        APP_ICON_LAYOUT_KNOWN_COMPACT.add(key);
        return false;
      }

      const widgetSizes = {
        ...cloneRecordMap(spaceRecord.widgetSizes)
      };
      if (!isAppIconLayoutSize(currentSize)) {
        widgetSizes[widgetId] = { ...APP_ICON_LAYOUT_SIZE };
      }

      const widgetPositions = {
        ...cloneRecordMap(spaceRecord.widgetPositions)
      };
      if (targetPosition) {
        widgetPositions[widgetId] = targetPosition;
      }

      const payload = buildSaveLayoutPayload(spaceRecord, {
        widgetPositions,
        widgetSizes
      });
      if (options.refresh === false) payload.refresh = false;
      const savedSpace = await spaces.saveSpaceLayout(payload);
      const savedPosition = normalizeWidgetPositionValue(savedSpace?.widgetPositions?.[widgetId]);
      const persistedPosition = savedPosition || targetPosition;
      rememberAppIconPosition(spaceId, widgetId, persistedPosition, { force: true });
      if (options.position) markAppIconDragRelease(spaceId, widgetId, persistedPosition);
      APP_ICON_LAYOUT_KNOWN_COMPACT.add(key);
      return true;
    });
  } catch (error) {
    console.warn("[hermes-fleet] app icon layout compact failed.", error);
    return false;
  } finally {
    APP_ICON_LAYOUT_SYNCING.delete(key);
  }
}

async function restoreAppIconLayout(widgetId, options = {}) {
  const spaceId = getCurrentSpaceId();
  const spaces = getSpacesRuntime();
  if (!spaceId || !widgetId || !canSaveSpaceLayout(spaces)) return false;

  const key = appIconLayoutSyncKey(spaceId, widgetId);
  APP_ICON_LAYOUT_KNOWN_COMPACT.delete(key);
  clearTimeout(APP_ICON_LAYOUT_SYNC_TIMERS.get(key));
  APP_ICON_LAYOUT_SYNC_TIMERS.delete(key);

  try {
    return await enqueueAppIconLayoutWrite(async () => {
      const spaceRecord = await spaces.readSpace(spaceId);
      const minimizedWidgetIds = new Set(cloneRecordList(spaceRecord?.minimizedWidgetIds));
      if (!minimizedWidgetIds.has(widgetId)) return true;

      minimizedWidgetIds.delete(widgetId);

      const currentSize = getSpaceRecordWidgetSize(spaceRecord, widgetId);
      const defaultSize = getSpaceRecordDefaultWidgetSize(spaceRecord, widgetId);
      const restoredSize =
        getRememberedOriginalWidgetSize(spaceId, widgetId) ||
        (currentSize && !isAppIconLayoutSize(currentSize) ? currentSize : null) ||
        defaultSize;
      const widgetSizes = cloneRecordMap(spaceRecord.widgetSizes);

      if (restoredSize) {
        widgetSizes[widgetId] = restoredSize;
      }

      const restoredPosition =
        normalizeWidgetPositionValue(options.position) ||
        getRememberedAppIconPosition(spaceId, widgetId) ||
        getRuntimeWidgetPosition(widgetId) ||
        normalizeWidgetPositionValue(spaceRecord?.widgetPositions?.[widgetId]);
      const widgetPositions = cloneRecordMap(spaceRecord.widgetPositions);
      if (restoredPosition) {
        widgetPositions[widgetId] = restoredPosition;
      }

      await spaces.saveSpaceLayout(
        buildSaveLayoutPayload(spaceRecord, {
          minimizedWidgetIds: [...minimizedWidgetIds],
          widgetPositions,
          widgetSizes
        })
      );
      return true;
    });
  } catch (error) {
    console.warn("[hermes-fleet] app icon restore layout failed.", error);
    return false;
  }
}

async function restoreExpandedAppIconSize(widgetId) {
  const spaceId = getCurrentSpaceId();
  const spaces = getSpacesRuntime();
  if (!spaceId || !widgetId || !canSaveSpaceLayout(spaces)) return false;

  const key = appIconLayoutSyncKey(spaceId, widgetId);
  APP_ICON_LAYOUT_KNOWN_COMPACT.delete(key);
  clearTimeout(APP_ICON_LAYOUT_SYNC_TIMERS.get(key));
  APP_ICON_LAYOUT_SYNC_TIMERS.delete(key);

  try {
    return await enqueueAppIconLayoutWrite(async () => {
      const spaceRecord = await spaces.readSpace(spaceId);
      const minimizedWidgetIds = cloneRecordList(spaceRecord?.minimizedWidgetIds);
      if (minimizedWidgetIds.includes(widgetId)) return false;

      const currentSize = getSpaceRecordWidgetSize(spaceRecord, widgetId);
      if (!isAppIconLayoutSize(currentSize)) return false;

      const restoredSize =
        getRememberedOriginalWidgetSize(spaceId, widgetId) ||
        getSpaceRecordDefaultWidgetSize(spaceRecord, widgetId);
      if (!restoredSize || isAppIconLayoutSize(restoredSize)) return false;

      await spaces.saveSpaceLayout(
        buildSaveLayoutPayload(spaceRecord, {
          widgetSizes: {
            ...cloneRecordMap(spaceRecord.widgetSizes),
            [widgetId]: restoredSize
          }
        })
      );
      return true;
    });
  } catch (error) {
    console.warn("[hermes-fleet] app icon expanded-size restore failed.", error);
    return false;
  }
}

function isSpaceNameInput(target) {
  if (!(target instanceof HTMLInputElement) || !target.matches(".spaces-config-field-input")) return false;
  const field = target.closest(".spaces-config-field");
  const label = String(field?.querySelector?.(".spaces-config-field-label")?.textContent || "").trim();
  return label === "Space Name";
}

function getSpaceNameInput() {
  return Array.from(document.querySelectorAll("input.spaces-config-field-input")).find(isSpaceNameInput) || null;
}

function getCurrentSpaceTitle() {
  const formValue = String(getSpaceNameInput()?.value || "").trim();
  if (formValue) return formValue;

  const runtimeTitle = String(getCurrentRuntime()?.title || "").trim();
  if (runtimeTitle) return runtimeTitle;

  return String(document.querySelector(".spaces-config-toggle-title")?.textContent || "").trim();
}

function slugifySpaceName(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function readSpaceAliases() {
  try {
    const parsed = JSON.parse(globalThis.localStorage?.getItem(SPACE_ALIAS_STORAGE_KEY) || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function writeSpaceAliases(aliases) {
  try {
    globalThis.localStorage?.setItem(SPACE_ALIAS_STORAGE_KEY, JSON.stringify(aliases));
  } catch {
    // Best-effort URL aliases should not interrupt the space UI.
  }
}

function rememberSpaceAlias(alias, spaceId) {
  const normalizedAlias = String(alias || "").trim();
  const normalizedSpaceId = String(spaceId || "").trim();
  if (!normalizedAlias || !normalizedSpaceId) return;

  const aliases = readSpaceAliases();
  if (aliases[normalizedAlias] === normalizedSpaceId) return;

  aliases[normalizedAlias] = normalizedSpaceId;
  aliases[normalizedSpaceId] = normalizedSpaceId;
  writeSpaceAliases(aliases);
}

function readSpacesHashRoute() {
  const hash = String(globalThis.location?.hash || "");
  if (!hash.startsWith("#")) return null;

  const route = hash.slice(1) || "/";
  const queryIndex = route.indexOf("?");
  const path = queryIndex === -1 ? route : route.slice(0, queryIndex);
  if (path !== SPACES_ROUTE_PATH) return null;

  return {
    path,
    params: new URLSearchParams(queryIndex === -1 ? "" : route.slice(queryIndex + 1))
  };
}

function replaceSpacesHashId(route, nextId) {
  const normalizedNextId = String(nextId || "").trim();
  if (!route || !normalizedNextId) return false;

  const params = new URLSearchParams(route.params);
  params.set("id", normalizedNextId);

  const nextQuery = params.toString();
  const nextHash = `#${route.path}${nextQuery ? `?${nextQuery}` : ""}`;
  if (globalThis.location?.hash === nextHash) return false;

  const nextUrl = `${globalThis.location?.pathname || "/"}${globalThis.location?.search || ""}${nextHash}`;
  globalThis.history?.replaceState?.(globalThis.history.state, document.title, nextUrl);
  return true;
}

function canonicalizeLegacySpaceHash() {
  const route = readSpacesHashRoute();
  const routeId = String(route?.params?.get("id") || "").trim();
  const targetSpaceId = SPACE_ID_ALIASES[routeId];
  if (!targetSpaceId || targetSpaceId === routeId) return false;

  rememberSpaceAlias(routeId, targetSpaceId);
  return replaceSpacesHashId(route, targetSpaceId);
}

export function canonicalizeHermesFleetSpaceRoute() {
  return canonicalizeLegacySpaceHash();
}

function syncSpaceUrlToTitle() {
  const spaceId = getCurrentSpaceId();
  const nextSlug = slugifySpaceName(getCurrentSpaceTitle());
  if (!spaceId || !nextSlug) return false;

  rememberSpaceAlias(nextSlug, spaceId);
  return false;
}

function resolveSpaceIdByTitleSlug(alias) {
  const normalizedAlias = String(alias || "").trim();
  if (!normalizedAlias) return "";

  const spaces = getSpacesRuntime();
  const candidates = [
    ...(Array.isArray(spaces?.all) ? spaces.all : []),
    ...(Array.isArray(spaces?.items) ? spaces.items : [])
  ];
  const seen = new Set();

  for (const spaceRecord of candidates) {
    const id = String(spaceRecord?.id || "").trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);

    const titleSlug = slugifySpaceName(spaceRecord?.title || spaceRecord?.name || "");
    if (titleSlug === normalizedAlias) return id;
  }

  return "";
}

function resolveSpaceAliasFromHash() {
  if (canonicalizeLegacySpaceHash()) return true;

  const route = readSpacesHashRoute();
  const routeId = String(route?.params?.get("id") || "").trim();
  if (!routeId) return false;

  const spaces = getSpacesRuntime();
  if (!spaces || spaces.byId?.[routeId]) return false;

  const targetSpaceId = String(
    readSpaceAliases()[routeId] || SPACE_ID_ALIASES[routeId] || resolveSpaceIdByTitleSlug(routeId)
  ).trim();
  if (!targetSpaceId || targetSpaceId === routeId || typeof spaces.openSpace !== "function") return false;
  if (targetSpaceId === getCurrentSpaceId()) {
    rememberSpaceAlias(routeId, targetSpaceId);
    return false;
  }
  if (RESOLVING_SPACE_ROUTE_IDS.has(routeId)) return true;

  RESOLVING_SPACE_ROUTE_IDS.add(routeId);
  rememberSpaceAlias(routeId, targetSpaceId);
  Promise.resolve(spaces.openSpace(targetSpaceId, { replace: true }))
    .catch((error) => {
      console.warn("[hermes-fleet] could not resolve renamed space URL alias.", error);
    })
    .finally(() => {
      RESOLVING_SPACE_ROUTE_IDS.delete(routeId);
    });
  return true;
}

function widgetIsStillMinimized(card, widgetId) {
  const descriptor = getRuntimeWidgetDescriptor(widgetId);

  if (descriptor && Object.prototype.hasOwnProperty.call(descriptor, "minimized")) {
    return Boolean(descriptor.minimized);
  }

  return Boolean(card?.classList?.contains("is-minimized"));
}

async function restoreCardThroughRuntime(card, widgetId) {
  const spaces = getSpacesRuntime();
  const current = getCurrentRuntime();
  const spaceId = getCurrentSpaceId();

  if (!widgetId || !widgetIsStillMinimized(card, widgetId)) {
    return true;
  }

  if (await restoreAppIconLayout(widgetId, {
    position: getVisualAppIconPosition(card)
  })) {
    return true;
  }

  if (typeof spaces?.toggleWidgets === "function") {
    await spaces.toggleWidgets({
      ...(spaceId ? { spaceId } : {}),
      widgetIds: [widgetId]
    });
    return true;
  }

  if (typeof current?.toggleWidgets === "function") {
    await current.toggleWidgets([widgetId]);
    return true;
  }

  return false;
}

function findRestoreButton(card) {
  const button = Array.from(card.querySelectorAll("button")).find((item) => {
    const label = `${item.getAttribute("title") || ""} ${item.getAttribute("aria-label") || ""}`;
    return label.includes(RESTORE_BUTTON_LABEL);
  });
  return button || null;
}

function restoreCardThroughButton(card) {
  const button = findRestoreButton(card);
  if (!button) return false;

  FALLBACK_RESTORE_BUTTONS.add(button);
  try {
    button.click();
  } finally {
    queueMicrotask(() => FALLBACK_RESTORE_BUTTONS.delete(button));
  }
  return true;
}

async function restoreCard(card) {
  const widgetId = widgetIdForCard(card);
  if (!widgetId || RESTORING_WIDGET_IDS.has(widgetId)) return false;

  RESTORING_WIDGET_IDS.add(widgetId);
  card.dataset.hermesFleetRestoring = "true";

  try {
    try {
      if (await restoreCardThroughRuntime(card, widgetId)) {
        return true;
      }
    } catch (error) {
      console.warn("[hermes-fleet] widget restore through Space runtime failed; trying button fallback.", error);
    }

    return restoreCardThroughButton(card);
  } finally {
    RESTORING_WIDGET_IDS.delete(widgetId);
    card.removeAttribute("data-hermes-fleet-restoring");
  }
}

function shouldBypassFallbackClick(event) {
  if (!(event.target instanceof Element)) return false;
  const button = event.target.closest("button");
  return Boolean(button && FALLBACK_RESTORE_BUTTONS.has(button));
}

function clearAppIconSettling(card) {
  const timer = APP_ICON_SETTLE_TIMERS.get(card);
  if (timer) {
    clearTimeout(timer);
    APP_ICON_SETTLE_TIMERS.delete(card);
    APP_ICON_SETTLE_TIMER_IDS.delete(timer);
  }
  card?.removeAttribute?.("data-hermes-fleet-settling");
}

function markAppIconSettling(card, widgetId) {
  if (!card?.dataset || !widgetId) return;

  clearAppIconSettling(card);
  card.dataset.hermesFleetSettling = "true";
  const timer = setTimeout(() => {
    APP_ICON_SETTLE_TIMERS.delete(card);
    APP_ICON_SETTLE_TIMER_IDS.delete(timer);
    if (widgetIdForCard(card) === widgetId) {
      card.removeAttribute("data-hermes-fleet-settling");
    }
  }, APP_ICON_SETTLE_MS);
  APP_ICON_SETTLE_TIMERS.set(card, timer);
  APP_ICON_SETTLE_TIMER_IDS.add(timer);
}

export function installHermesFleetUi() {
  if (globalThis[RUNTIME_KEY]) return globalThis[RUNTIME_KEY];

  canonicalizeLegacySpaceHash();

  let spaceUrlSyncTimer = 0;
  let iconRefreshFrame = 0;
  let appIconPointer = null;
  let recentAppIconDrag = null;
  const pendingIconCards = new Set();
  const requestIconRefreshFrame =
    globalThis.requestAnimationFrame?.bind(globalThis) || ((callback) => setTimeout(callback, 16));
  const cancelIconRefreshFrame =
    globalThis.cancelAnimationFrame?.bind(globalThis) || ((frameId) => clearTimeout(frameId));
  const scheduleSpaceUrlSync = () => {
    clearTimeout(spaceUrlSyncTimer);
    spaceUrlSyncTimer = setTimeout(syncSpaceUrlToTitle, SPACE_URL_SYNC_DELAY_MS);
  };
  const flushQueuedIcons = () => {
    iconRefreshFrame = 0;
    const cards = [...pendingIconCards];
    pendingIconCards.clear();
    cards.forEach((card) => {
      if (card?.isConnected) ensureIcon(card);
    });
  };
  const queueEnsureIcon = (card) => {
    if (!(card instanceof Element)) return;
    pendingIconCards.add(card);
    if (!iconRefreshFrame) iconRefreshFrame = requestIconRefreshFrame(flushQueuedIcons);
  };
  const now = monotonicNow;
  const shouldSuppressAppIconClick = (card) => {
    const widgetId = widgetIdForCard(card);
    if (!widgetId) return false;
    if (appIconPointer?.widgetId === widgetId && appIconPointer.moved) return true;
    return Boolean(
      recentAppIconDrag?.widgetId === widgetId &&
        now() - recentAppIconDrag.finishedAt < APP_ICON_RECENT_DRAG_MS
    );
  };
  const trackAppIconPointerMove = (event) => {
    if (!appIconPointer || event.pointerId !== appIconPointer.pointerId) return;

    event.preventDefault();
    event.stopPropagation();

    const distance = Math.hypot(event.clientX - appIconPointer.startX, event.clientY - appIconPointer.startY);
    if (distance < APP_ICON_DRAG_THRESHOLD_PX) return;

    if (!appIconPointer.moved) {
      appIconPointer.moved = true;
      appIconPointer.card?.removeAttribute?.("data-hermes-fleet-pressed");
      clearAppIconSettling(appIconPointer.card);
    }
    if (!appIconPointer.card?.isConnected || !appIconPointer.startFrame) return;

    const deltaX = event.clientX - appIconPointer.startX;
    const deltaY = event.clientY - appIconPointer.startY;
    const previewFrame = {
      ...appIconPointer.startFrame,
      left: appIconPointer.startFrame.left + deltaX,
      top: appIconPointer.startFrame.top + deltaY
    };
    appIconPointer.previewPosition =
      positionFromAppIconFrame(previewFrame, appIconPointer.origin, appIconPointer.metrics) ||
      appIconPointer.startPosition;
    appIconPointer.card.dataset.hermesFleetDragging = "true";
    appIconPointer.card.style.transform = `translate(${roundFrameValue(deltaX)}px, ${roundFrameValue(deltaY)}px)`;
  };
  const finishAppIconPointer = (event) => {
    if (!appIconPointer || event.pointerId !== appIconPointer.pointerId) return;

    if (appIconPointer.moved) {
      event.preventDefault();
      event.stopPropagation();
    }

    const shouldCommitDrag = Boolean(appIconPointer.moved && event.type !== "pointercancel");
    if (shouldCommitDrag && appIconPointer.widgetId) {
      const movedWidgetId = appIconPointer.widgetId;
      const movedSpaceId = getCurrentSpaceId();
      const movedPosition =
        appIconPointer.previewPosition ||
        getVisualAppIconPosition(appIconPointer.card) ||
        appIconPointer.startPosition;

      appIconPointer.card?.style?.removeProperty?.("transform");
      if (movedPosition) {
        const finalFrame = appIconFrameForPosition(movedPosition, appIconPointer.origin, appIconPointer.metrics);
        if (finalFrame) applyPreferredFrame(appIconPointer.card, finalFrame);
        rememberAppIconPosition(movedSpaceId, movedWidgetId, movedPosition, { force: true });
        APP_ICON_LAYOUT_KNOWN_COMPACT.delete(appIconLayoutSyncKey(movedSpaceId, movedWidgetId));
        const persistAppIconLayout = compactAppIconLayout(appIconPointer.card, movedSpaceId, movedWidgetId, {
          force: true,
          position: movedPosition,
          refresh: false
        });
        void Promise.resolve(persistAppIconLayout).finally(() => refreshIcons());
      }
      markAppIconDragRelease(movedSpaceId, movedWidgetId, movedPosition);
      markAppIconSettling(appIconPointer.card, movedWidgetId);
      recentAppIconDrag = {
        finishedAt: now(),
        widgetId: movedWidgetId
      };
    } else {
      appIconPointer.card?.style?.removeProperty?.("transform");
    }

    appIconPointer.card?.releasePointerCapture?.(event.pointerId);
    appIconPointer.card?.removeAttribute?.("data-hermes-fleet-pressed");
    appIconPointer.card?.removeAttribute?.("data-hermes-fleet-dragging");
    appIconPointer = null;
  };

  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type === "attributes") {
        const target = mutation.target;
        if (target instanceof Element && target.matches(CARD_SELECTOR)) queueEnsureIcon(target);
      }
      mutation.addedNodes.forEach((node) => {
        if (!(node instanceof Element)) return;
        removeWidgetReloadButtons(node);
        if (node.matches(CARD_SELECTOR)) queueEnsureIcon(node);
        node.querySelectorAll?.(CARD_SELECTOR).forEach(queueEnsureIcon);
      });
    }
  });

  const onPointerDown = (event) => {
    const card = minimizedCardFromTarget(event.target);
    if (!card || event.button !== 0) return;

    const grid = card.closest(GRID_SELECTOR);
    const metrics = grid ? readGridMetrics(grid) : null;
    const origin = grid && metrics ? resolveGridOrigin(grid, metrics) : null;
    const startFrame = getInlineCardFrame(card);
    const startPosition =
      positionFromAppIconFrame(startFrame, origin, metrics) ||
      getRememberedAppIconPosition(getCurrentSpaceId(), widgetIdForCard(card)) ||
      getRuntimeWidgetPosition(widgetIdForCard(card));

    appIconPointer = {
      card,
      metrics,
      moved: false,
      origin,
      pointerId: event.pointerId,
      previewPosition: startPosition,
      startFrame,
      startPosition,
      startX: event.clientX,
      startY: event.clientY,
      widgetId: widgetIdForCard(card)
    };
    clearAppIconSettling(card);
    card.dataset.hermesFleetPressed = "true";
    card.setPointerCapture?.(event.pointerId);

    event.stopPropagation();
  };

  const onPointerMove = (event) => {
    trackAppIconPointerMove(event);
  };

  const onPointerUp = (event) => {
    finishAppIconPointer(event);
  };

  const onClick = (event) => {
    if (shouldBypassFallbackClick(event)) return;
    const card = minimizedCardFromTarget(event.target);
    if (!card) return;
    event.preventDefault();
    event.stopPropagation();
    if (shouldSuppressAppIconClick(card)) return;
    void restoreCard(card);
  };

  const onKeyDown = (event) => {
    const card = minimizedCardFromTarget(event.target);
    if (!card || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    event.stopPropagation();
    void restoreCard(card);
  };

  const onSpaceNameChange = (event) => {
    if (isSpaceNameInput(event.target)) scheduleSpaceUrlSync();
  };

  const onSpaceNameKeyDown = (event) => {
    if (!isSpaceNameInput(event.target) || event.key !== "Enter") return;
    setTimeout(scheduleSpaceUrlSync, 0);
  };

  const onHashChange = () => {
    if (canonicalizeLegacySpaceHash()) return;
    if (!resolveSpaceAliasFromHash()) scheduleSpaceUrlSync();
  };

  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["class", "data-widget-id", "style"]
  });
  document.addEventListener("pointerdown", onPointerDown, true);
  document.addEventListener("pointermove", onPointerMove, true);
  document.addEventListener("pointerup", onPointerUp, true);
  document.addEventListener("pointercancel", onPointerUp, true);
  document.addEventListener("click", onClick, true);
  document.addEventListener("keydown", onKeyDown, true);
  document.addEventListener("input", onSpaceNameChange, true);
  document.addEventListener("change", onSpaceNameChange, true);
  document.addEventListener("focusout", onSpaceNameChange, true);
  document.addEventListener("keydown", onSpaceNameKeyDown, true);
  globalThis.addEventListener?.("hashchange", onHashChange);
  refreshIcons();
  resolveSpaceAliasFromHash();
  setTimeout(resolveSpaceAliasFromHash, 250);
  setTimeout(resolveSpaceAliasFromHash, 1000);
  scheduleSpaceUrlSync();

  const runtime = {
    uninstall() {
      clearTimeout(spaceUrlSyncTimer);
      if (iconRefreshFrame) cancelIconRefreshFrame(iconRefreshFrame);
      iconRefreshFrame = 0;
      pendingIconCards.clear();
      APP_ICON_LAYOUT_SYNC_TIMERS.forEach((timer) => clearTimeout(timer));
      APP_ICON_LAYOUT_SYNC_TIMERS.clear();
      APP_ICON_LAYOUT_SYNCING.clear();
      APP_ICON_POSITION_STORAGE_SEEDED.clear();
      APP_ICON_DRAG_RELEASES.clear();
      APP_ICON_SETTLE_TIMER_IDS.forEach((timer) => clearTimeout(timer));
      APP_ICON_SETTLE_TIMER_IDS.clear();
      appIconLayoutWritePromise = Promise.resolve();
      observer.disconnect();
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("pointermove", onPointerMove, true);
      document.removeEventListener("pointerup", onPointerUp, true);
      document.removeEventListener("pointercancel", onPointerUp, true);
      document.removeEventListener("click", onClick, true);
      document.removeEventListener("keydown", onKeyDown, true);
      document.removeEventListener("input", onSpaceNameChange, true);
      document.removeEventListener("change", onSpaceNameChange, true);
      document.removeEventListener("focusout", onSpaceNameChange, true);
      document.removeEventListener("keydown", onSpaceNameKeyDown, true);
      globalThis.removeEventListener?.("hashchange", onHashChange);
      document.querySelectorAll("[data-hermes-fleet-card-layer]").forEach((card) => {
        card.removeAttribute("data-hermes-fleet-card-layer");
      });
      document.querySelectorAll("[data-hermes-fleet-app-icon]").forEach((card) => {
        card.removeAttribute("data-hermes-fleet-app-icon");
        card.removeAttribute("data-hermes-fleet-restoring");
        card.removeAttribute("data-hermes-fleet-dragging");
        card.removeAttribute("data-hermes-fleet-applied-frame");
        card.removeAttribute("data-hermes-fleet-pressed");
        clearAppIconSettling(card);
        card.removeAttribute("aria-label");
        card.removeAttribute("role");
        card.removeAttribute("tabindex");
        card.removeAttribute("title");
        card.querySelector(".hermes-fleet-minimized-icon")?.remove();
        card.querySelector(".hermes-fleet-drag-glyph")?.remove();
      });
      unwrapSpaceLayers();
      delete globalThis[RUNTIME_KEY];
    }
  };
  globalThis[RUNTIME_KEY] = runtime;
  return runtime;
}
