import assert from "node:assert/strict";
import fs from "node:fs/promises";

async function load(name) {
  const source = await fs.readFile(new URL(name, import.meta.url), "utf8");
  return import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
}

const { WIDGET_RESIZE_DIRECTIONS, resizedWidgetRect } = await load("./widget-window-contract.js");
const { homeCleanWidgetLayout, initialVisibleWidgetPosition } = await load("./space-widget-policy.js");
const { widgetIconDataUri } = await load("./widget-icons.js");
const limits = { minWidth: 100, minHeight: 80, maxWidth: 500, maxHeight: 400 };
const surface = { width: 800, height: 600 };
const start = { left: 200, top: 150, width: 300, height: 200 };

assert.deepEqual(WIDGET_RESIZE_DIRECTIONS, ["n", "ne", "e", "se", "s", "sw", "w", "nw"]);
assert.deepEqual(resizedWidgetRect(start, "se", 40, 30, limits, surface), { left: 200, top: 150, width: 340, height: 230 });
assert.deepEqual(resizedWidgetRect(start, "nw", 40, 30, limits, surface), { left: 240, top: 180, width: 260, height: 170 });
assert.deepEqual(resizedWidgetRect(start, "w", -500, 0, limits, surface), { left: 0, top: 150, width: 500, height: 200 });
assert.deepEqual(resizedWidgetRect(start, "n", 0, 500, limits, surface), { left: 200, top: 270, width: 300, height: 80 });

const screenStart = { left: 320, top: 240, width: 480, height: 320 };
const screenLimits = { minWidth: 160, minHeight: 128, maxWidth: 800, maxHeight: 640 };
const east = resizedWidgetRect(screenStart, "e", 73, 0, screenLimits, { width: 1280, height: 960 });
assert.equal(east.left, screenStart.left, "east resize must anchor the west edge");
assert.equal(east.left + east.width, screenStart.left + screenStart.width + 73, "east edge must follow the pointer delta");
const west = resizedWidgetRect(screenStart, "w", 73, 0, screenLimits, { width: 1280, height: 960 });
assert.equal(west.left, screenStart.left + 73, "west edge must follow the pointer delta");
assert.equal(west.left + west.width, screenStart.left + screenStart.width, "west resize must anchor the east edge");
const north = resizedWidgetRect(screenStart, "n", 0, 61, screenLimits, { width: 1280, height: 960 });
assert.equal(north.top, screenStart.top + 61, "north edge must follow the pointer delta");
assert.equal(north.top + north.height, screenStart.top + screenStart.height, "north resize must anchor the south edge");
const south = resizedWidgetRect(screenStart, "s", 0, 61, screenLimits, { width: 1280, height: 960 });
assert.equal(south.top, screenStart.top, "south resize must anchor the north edge");
assert.equal(south.top + south.height, screenStart.top + screenStart.height + 61, "south edge must follow the pointer delta");

const cleanHome = homeCleanWidgetLayout({ timeline: { minimized: false, maximized: true }, stale: { minimized: false } }, "home");
assert.deepEqual(cleanHome.timeline, { minimized: true, maximized: false });
assert.deepEqual(homeCleanWidgetLayout(cleanHome, "space-user"), cleanHome);
assert.deepEqual(initialVisibleWidgetPosition({
  visibleRect: { left: 72, top: 0, width: 928, height: 700 },
  boardRect: { left: 72, top: 0, width: 1400, height: 900 },
  widgetRect: { width: 680, height: 500 },
}), { left: 124, top: 100 });
assert.match(widgetIconDataUri("browser"), /^data:image\/svg\+xml,/);
assert.doesNotMatch(decodeURIComponent(widgetIconDataUri("browser")), />[A-Za-z]{2}<\//);

console.log("Windows-style widget contract tests passed");
