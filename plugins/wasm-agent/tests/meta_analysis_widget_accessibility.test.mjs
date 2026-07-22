#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(new URL("../public/modules/meta-analysis/meta-analysis-widget.js", import.meta.url), "utf8");
const statusFunction = source.match(/function setStatus\(text, mode = ""\) \{([\s\S]*?)\n  \}/)?.[1] || "";

assert.match(statusFunction, /setAttribute\("role", mode === "error" \? "alert" : "status"\)/);
assert.match(statusFunction, /setAttribute\("aria-live", mode === "error" \? "assertive" : "polite"\)/);
assert.match(statusFunction, /statusEl\.textContent = text/);
assert.match(statusFunction, /statusEl\.dataset\.mode = mode/);
assert.match(source, /data-action="remove"[^>]*aria-label="Remove \$\{escapeHtml\(item\.subject\)\}"/);
assert.match(source, /data-action="toggle"[^>]*aria-expanded="\$\{item\.collapsed \? "false" : "true"\}"/);
console.log("meta-analysis widget accessibility contract: PASS");
