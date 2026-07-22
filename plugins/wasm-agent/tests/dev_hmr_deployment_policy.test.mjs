#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(new URL("../public/modules/hmr/dev-hmr.js", import.meta.url), "utf8");

assert.match(source, /fetch\("\/config\.json", \{ cache: "no-store", credentials: "same-origin" \}\)/);
assert.match(source, /config\?\.features\?\.devHmr\?\.enabled === true/);
assert.match(source, /if \(!await enabledByDeployment\(\)\) return;/);
console.log("dev HMR deployment policy: PASS");
