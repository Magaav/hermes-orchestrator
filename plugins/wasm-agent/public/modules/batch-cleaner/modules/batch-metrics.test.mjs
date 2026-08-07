import assert from "node:assert/strict";
import fs from "node:fs/promises";

const source = await fs.readFile(new URL("./batch-metrics.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { EMPTY_METRICS, nextMetrics } = await import(moduleUrl);

assert.deepEqual(nextMetrics(EMPTY_METRICS, { totalTokens: 125 }), {
  cleanedPhotos: 1,
  reportedTokens: 125
});
assert.deepEqual(nextMetrics({ cleanedPhotos: 4, reportedTokens: 900 }, { totalTokens: 100 }), {
  cleanedPhotos: 5,
  reportedTokens: 1000
});
assert.deepEqual(nextMetrics({ cleanedPhotos: -2 }, { totalTokens: "invalid" }), {
  cleanedPhotos: 1,
  reportedTokens: 0
});

console.log("batch cleaner metrics tests passed");
