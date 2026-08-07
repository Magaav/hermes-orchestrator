import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const context = vm.createContext({ console });
const source = fs.readFileSync(new URL("./module.js", import.meta.url), "utf8");
const parsed = new vm.SourceTextModule(source, { context });
await parsed.link(() => { throw new Error("unexpected import"); });
await parsed.evaluate();
const { latestObservationEvents, observationBrowserProjection, observationBrowserSummary, observationEventCounts } = parsed.namespace;

const plain = (value) => JSON.parse(JSON.stringify(value));
assert.deepEqual(plain(observationEventCounts([{ type: "click" }, { type: "click" }, { type: "error" }])), { click: 2, error: 1 });
assert.deepEqual(plain(latestObservationEvents([{ type: "a" }, { type: "b" }], 1)), [{ type: "b" }]);
assert.deepEqual(plain(observationBrowserProjection({ locationRef: { hostname: "wa.colmeio.com", origin: "https://wa.colmeio.com", pathname: "/home" }, nativeRuntime: "electron" })), {
  domain: "wa.colmeio.com", origin: "https://wa.colmeio.com", path: "/home", stream_mode: "electron-webcontents",
});
assert.deepEqual(plain(observationBrowserSummary({})), { domain: "-", stream_mode: "unknown" });
console.log("observation module tests passed");
