import assert from "node:assert/strict";
import fs from "node:fs/promises";

const root = new URL("../public/modules/browser/", import.meta.url);
const entry = await fs.readFile(new URL("browser.entry.js", root), "utf8");
const descriptor = await fs.readFile(new URL("module.js", root), "utf8");
const preload = await fs.readFile(new URL("../../../native/windows/src/preload.js", import.meta.url), "utf8");
const manager = await fs.readFile(new URL("../../../native/windows/src/main/web-surfaces/manager.js", import.meta.url), "utf8");
const builder = JSON.parse(await fs.readFile(new URL("../../../native/windows/src/electron-builder.json", import.meta.url), "utf8"));

assert.match(entry, /wasmAgentNative\?\.webSurfaces/);
assert.match(entry, /Native Chromium is available in the Electron build only/);
assert.doesNotMatch(entry, /iframe|transferControlToOffscreen|engine\.worker|extension-network/);
assert.match(descriptor, /browser\.native\.surface/);
assert.match(preload, /wasm-agent:web-surface/);
assert.match(manager, /chromeLikeUserAgent\(view\.webContents\.getUserAgent\(\)\)/);
assert.ok(builder.files.includes("main/web-surfaces/manager.js"));
assert.ok(builder.files.includes("main/web-surfaces/capability-manifest.json"));

console.log("native browser widget wiring tests passed");
