import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const context = vm.createContext({ URL, Date, Promise, globalThis: {} });
const parsed = new vm.SourceTextModule(fs.readFileSync(new URL("./runtime-refresh.js", import.meta.url), "utf8"), { context });
await parsed.link(() => { throw new Error("unexpected import"); });
await parsed.evaluate();
const { prepareRuntimeRefresh, refreshTarget } = parsed.namespace;

const locationRef = { href: "https://wa.colmeio.com/home?native=electron", protocol: "https:", hostname: "wa.colmeio.com", replaced: "", replace(value) { this.replaced = value; } };
assert.equal(refreshTarget(locationRef, 42), "https://wa.colmeio.com/home?native=electron&module_refresh=42");
let scheduled;
const result = await prepareRuntimeRefresh({
  locationRef,
  navigatorRef: { serviceWorker: { getRegistrations: async () => [{ update: async () => {} }] } },
  schedule: (callback, delay) => { scheduled = { callback, delay }; },
  nonce: 43,
});
assert.equal(result.ok, true);
assert.equal(result.mode, "cloud_module_reload");
assert.deepEqual(JSON.parse(JSON.stringify(result.service_workers)), { checked: 1, updated: 1 });
assert.equal(scheduled.delay, 1000);
scheduled.callback();
assert.equal(locationRef.replaced, "https://wa.colmeio.com/home?native=electron&module_refresh=43");
assert.equal((await prepareRuntimeRefresh({ locationRef: { href: "http://localhost/home", protocol: "http:", hostname: "localhost" } })).error, "production_origin_required");
console.log("runtime refresh tests passed");
