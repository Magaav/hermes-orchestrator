import assert from "node:assert/strict";
import fs from "node:fs/promises";

const source = await fs.readFile(new URL("./widget-dimensions.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { widgetDimensionLimits } = await import(moduleUrl);

assert.deepEqual(
  widgetDimensionLimits({}, { minWidth: 250, minHeight: 250 }, { width: 900, height: 700 }),
  { minWidth: 250, minHeight: 250, maxWidth: 884, maxHeight: 684 },
);
assert.equal(widgetDimensionLimits({ minWidth: 300 }, { minWidth: 250 }).minWidth, 300);
assert.equal(widgetDimensionLimits({}, {}).minWidth, 320);

console.log("widget dimension tests passed");
