import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const context = vm.createContext({ globalThis: {} });
const parsed = new vm.SourceTextModule(fs.readFileSync(new URL("./module-release.js", import.meta.url), "utf8"), { context });
await parsed.link(() => { throw new Error("unexpected import"); });
await parsed.evaluate();
const api = parsed.namespace;
const manifest = { schema: "hermes.wasm_agent.module_release.v1", release_id: "a".repeat(64), entry: { web: "app.js", android: "android-app.js" } };
assert.equal(api.validModuleRelease(manifest), true);
assert.equal(api.validModuleRelease({ ...manifest, release_id: "manual-version" }), false);
assert.equal(api.moduleEntryUrl(manifest, false), `/app.js?v=${"a".repeat(64)}`);
assert.equal(api.moduleEntryUrl(manifest, true), `/android-app.js?v=${"a".repeat(64)}`);
assert.equal((await api.fetchModuleRelease(async () => ({ ok: true, json: async () => manifest }))).release_id, manifest.release_id);
assert.equal(await api.fetchModuleRelease(async () => ({ ok: true, json: async () => ({}) })), null);
console.log("module release tests passed");
