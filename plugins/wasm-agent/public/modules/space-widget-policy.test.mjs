import assert from "node:assert/strict";
import fs from "node:fs/promises";

const source = await fs.readFile(new URL("./space-widget-policy.js", import.meta.url), "utf8");
const { appRect, closeUnpositionedWidgets, nearestOpenAppPosition, organizedSpaceAppPositions } = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

const layout = organizedSpaceAppPositions({ count: 5, boardWidth: 620, boardHeight: 600, visibleWidth: 310, visibleHeight: 300, topInset: 35 });
assert.equal(layout.columns, 5);
assert.deepEqual(layout.positions, [
  { left: 0, top: 35 },
  { left: 62, top: 35 },
  { left: 124, top: 35 },
  { left: 186, top: 35 },
  { left: 248, top: 35 },
]);

const wrapped = organizedSpaceAppPositions({ count: 4, boardWidth: 124, boardHeight: 300, visibleWidth: 124, visibleHeight: 140, scrollTop: 10, topInset: 30 });
assert.equal(wrapped.columns, 2);
assert.deepEqual(wrapped.positions[2], { left: 0, top: 110 });
assert.deepEqual(closeUnpositionedWidgets({ browser: { minimized: false }, agent: { minimized: false, leftPx: 20, topPx: 30 } }, ["browser", "agent"]), {
  browser: { minimized: false },
  agent: { minimized: false, leftPx: 20, topPx: 30 },
});
assert.deepEqual(closeUnpositionedWidgets({ browser: {} }, ["browser"]), {
  browser: { minimized: true, maximized: false },
});
assert.deepEqual(nearestOpenAppPosition(62, 0, 62, 70, 200, 200, [appRect(0, 0, 62, 70)]), { left: 62, top: 0 });
const displaced = nearestOpenAppPosition(20, 0, 62, 70, 200, 200, [appRect(0, 0, 62, 70)]);
assert.notDeepEqual(displaced, { left: 20, top: 0 });
assert(displaced.left >= 0 && displaced.left <= 200 && displaced.top >= 0 && displaced.top <= 200);
console.log("space widget policy tests passed");
