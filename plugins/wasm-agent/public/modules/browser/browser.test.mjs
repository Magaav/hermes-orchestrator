import assert from "node:assert/strict";
import fs from "node:fs/promises";

const source = await fs.readFile(new URL("./browser-contract.js", import.meta.url), "utf8");
const entrySource = await fs.readFile(new URL("./browser.entry.js", import.meta.url), "utf8");
const contract = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const { BROWSER_PORTAL_CAPABILITIES, browserPortalCommand, normalizeBrowserAddress } = contract;

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
assert.match(entrySource, /geometryBusy = true;[\s\S]*geometryQueued = false;[\s\S]*await syncLatestGeometry\(\)/);
assert.match(entrySource, /wasm-agent:widget-resize-frame/);
assert.match(entrySource, /shellOverlayOpen = document\.querySelector\("#agentOverlay"\)\?\.dataset\.open === "true"/);
assert.match(entrySource, /addEventListener\(SHELL_OVERLAY_EVENT,[\s\S]*nativeSurfaceSuppressed[\s\S]*scheduleGeometry\(\)/);
assert.match(entrySource, /visible = !shellOverlayOpen/);

console.log("native browser portal contract tests passed");
