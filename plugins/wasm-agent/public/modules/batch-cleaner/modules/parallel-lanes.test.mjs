import assert from "node:assert/strict";
import fs from "node:fs/promises";

const source = await fs.readFile(new URL("./parallel-lanes.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { partitionIntoLanes, runIndependentLanes } = await import(moduleUrl);

const lanes = partitionIntoLanes(Array.from({ length: 30 }, (_, index) => index), 10);
assert.equal(lanes.length, 10);
assert.deepEqual(lanes.map((lane) => lane.map(({ item }) => item)), [
  [0, 10, 20], [1, 11, 21], [2, 12, 22], [3, 13, 23], [4, 14, 24],
  [5, 15, 25], [6, 16, 26], [7, 17, 27], [8, 18, 28], [9, 19, 29]
]);

const releases = new Map();
const started = [];
const execution = runIndependentLanes(["a", "b", "c", "d"], 2, async ({ item, laneIndex }) => {
  started.push(`${laneIndex}:${item}`);
  await new Promise((resolve) => releases.set(item, resolve));
});
await new Promise((resolve) => setTimeout(resolve, 0));
assert.deepEqual(started, ["0:a", "1:b"]);
releases.get("a")();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.deepEqual(started, ["0:a", "1:b", "0:c"]);
assert.equal(started.includes("1:d"), false);
releases.get("c")();
releases.get("b")();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(started.includes("1:d"), true);
releases.get("d")();
await execution;

console.log("batch cleaner independent lane tests passed");
