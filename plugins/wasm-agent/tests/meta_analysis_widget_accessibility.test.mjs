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

// --- Static contract assertions for integrity-scoring ---

// 1. Function signatures must be present in source
assert.match(source, /function escapeRegExp\(term\)\s*\{/);
assert.match(source, /function buildTermRegex\(term,\s*flags\)\s*\{/);
assert.match(source, /function isNegated\(cleanText,\s*term,\s*negationTerms\)\s*\{/);

// 2. escapeRegExp must escape regex special characters
assert.match(source, /escapeRegExp[\s\S]*?replace[\s\S]*?\\\$&/);

// 3. buildTermRegex must use word-boundary patterns
assert.match(source, /buildTermRegex[\s\S]*?(?:\\b|\\p\{)/);

// 4. isNegated must scan negation terms
assert.match(source, /isNegated[\s\S]*?negationTerms/);

// 5. assessIntegrity must invoke isNegated
assert.match(source, /assessIntegrity[\s\S]*?isNegated/);

// 6. Score clamping to 0..10
assert.match(source, /riskScore\s*=\s*Math\.max\s*\(\s*0\s*,\s*Math\.min\s*\(\s*10\s*,\s*risk\s*\)\s*\)/);

// 7. termMatches must delegate matching to buildTermRegex (substantive: extract function body, verify call)
const termMatchesBody = source.match(/function termMatches\([^)]*\)\s*\{([\s\S]*?)\n\}/)?.[1] || "";
assert.match(termMatchesBody, /buildTermRegex\s*\(/);

console.log("meta-analysis widget integrity scoring contract: PASS");
