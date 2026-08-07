import assert from "node:assert/strict";
import fs from "node:fs/promises";

const source = await fs.readFile(new URL("./app-registry.js", import.meta.url), "utf8");
const windowStateSource = await fs.readFile(new URL("./widget-window-state.js", import.meta.url), "utf8");
const appSource = await fs.readFile(new URL("../app.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { SPACE_APP_DEFINITIONS, SPACE_APP_MAPPINGS, externalAppsToHydrate } = await import(moduleUrl);

assert.match(source, /data-external-app-close="\$\{app\.id\}"/);
assert.match(source, /aria-label="Close \$\{app\.label\}"/);
assert.match(source, /void closeExternalApp\(app\.id\)/);
assert.match(source, /export async function closeExternalApp\(appId\)/);
assert.match(source, /typeof api\?\.close === "function"/);
assert.match(source, /await api\.close\(\)/);
assert.match(source, /external-app-unmounted/);
assert.match(source, /document\.querySelector\("#spaceBoard"\)/);
assert.match(source, /surface\.append\(host\)/);
assert.doesNotMatch(source, /document\.body\.append\(host\)/);
assert.match(source, /export function externalAppsToHydrate\(apps = \[\], layout = \{\}\)/);
assert.match(source, /layout\?\.\[app\.id\]\?\.minimized === false/);
assert.match(source, /export async function hydrateOpenExternalApps\(apps = \[\], layout = \{\}\)/);
assert.match(source, /Promise\.allSettled/);
assert.match(windowStateSource, /external-app-unmounted/);
assert.match(appSource, /const routedPanel = panelFromPath\(\);[\s\S]*if \(routeReconciled\) setPanel\(routedPanel, \{ updateUrl: false \}\);/);
assert.deepEqual(SPACE_APP_MAPPINGS.home, []);
assert.ok(SPACE_APP_MAPPINGS.user.includes("anaminese"), "Anaminese must be registered for user-created Spaces");
assert.ok(SPACE_APP_DEFINITIONS.every((app) => app.icon), "every canvas app must declare a real icon");
assert.deepEqual(
  externalAppsToHydrate(
    [{ id: "batch-cleaner", entry: "/batch.js" }, { id: "plain" }],
    { "batch-cleaner": { minimized: false }, plain: { minimized: false } },
  ).map((app) => app.id),
  ["batch-cleaner"],
);
assert.deepEqual(
  externalAppsToHydrate(
    [{ id: "batch-cleaner", entry: "/batch.js" }],
    { "batch-cleaner": { minimized: true } },
  ),
  [],
);

console.log("external app registry lifecycle tests passed");
assert.match(source, /class="widget-head external-app-widget-header"/);
