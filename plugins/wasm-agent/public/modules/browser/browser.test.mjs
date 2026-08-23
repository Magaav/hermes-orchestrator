import assert from "node:assert/strict";
import fs from "node:fs/promises";

const source = await fs.readFile(new URL("./browser-contract.js", import.meta.url), "utf8");
const entrySource = await fs.readFile(new URL("./browser.entry.js", import.meta.url), "utf8");
const contract = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const { BROWSER_PORTAL_CAPABILITIES, browserPortalCommand, browserSurfaceIntersectsOverlay, normalizeBrowserAddress } = contract;

assert.equal(normalizeBrowserAddress("github.com"), "https://github.com/");
assert.equal(normalizeBrowserAddress("https://web.whatsapp.com/"), "https://web.whatsapp.com/");
assert.throws(() => normalizeBrowserAddress("http://example.com"), /secure HTTPS/);
assert.throws(() => normalizeBrowserAddress("javascript:alert(1)"), /secure HTTPS/);
assert.deepEqual(BROWSER_PORTAL_CAPABILITIES, [
  "browser.session.status",
  "browser.navigate",
  "browser.history",
  "browser.native.surface",
  "browser.prove",
]);
const command = browserPortalCommand("browser.navigate", { url: "https://example.com/" });
assert.equal(command.schema, "wasm-agent.browser-portal.v1");
assert.equal(command.operation, "browser.navigate");
assert.equal(command.args.url, "https://example.com/");
assert.ok(command.requested_at);
assert.equal(browserSurfaceIntersectsOverlay(
  { left: 0, top: 0, right: 100, bottom: 100 },
  { left: 110, top: 0, right: 150, bottom: 100, width: 40, height: 100 },
), false);
assert.equal(browserSurfaceIntersectsOverlay(
  { left: 0, top: 0, right: 100, bottom: 100 },
  { left: 80, top: 0, right: 150, bottom: 100, width: 70, height: 100 },
), true);
assert.match(entrySource, /geometryBusy = true;[\s\S]*geometryQueued = false;[\s\S]*await syncLatestGeometry\(\)/);
assert.match(entrySource, /wasm-agent:widget-resize-frame/);
assert.match(entrySource, /shellOverlayOpen = document\.querySelector\("#agentOverlay"\)\?\.dataset\.open === "true"/);
assert.match(entrySource, /const snapshot = await invoke\("snapshot"\)/);
assert.match(entrySource, /snapshotImage\.src = snapshot\.dataUrl/);
assert.match(entrySource, /browserOverlayMode = "live-nonoverlap"/);
assert.match(entrySource, /"frozen-chat-overlap" : "frozen-avatar-overlap"/);
assert.match(entrySource, /browserOverlayMode = "fallback-hidden"/);
assert.match(entrySource, /setNativeVisibility\(inViewport && !overlayFrozen\)/);
assert.match(entrySource, /addEventListener\(SHELL_OVERLAY_EVENT,[\s\S]*syncOverlaySurface\(\)/);
assert.match(entrySource, /visibilityQueue = visibilityQueue/);

console.log("native browser portal contract tests passed");
