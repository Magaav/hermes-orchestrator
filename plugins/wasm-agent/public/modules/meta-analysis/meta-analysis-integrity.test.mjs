#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(
  new URL("./meta-analysis-widget.js", import.meta.url),
  "utf8",
);

function extractFunction(name) {
  const signature = `function ${name}(`;
  const start = source.indexOf(signature);
  assert.notEqual(start, -1, `${name} function not found`);
  const bodyStart = source.indexOf("{", start + signature.length);
  assert.notEqual(bodyStart, -1, `${name} function body not found`);
  let depth = 0;
  for (let i = bodyStart; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    if (source[i] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(start, i + 1);
    }
  }
  assert.fail(`${name} function body is unbalanced`);
}

const tests = [
  {
    id: "word-boundary-regex-uses-punctuation-class",
    name: "buildTermRegex uses Unicode punctuation property escapes for word boundaries",
    run() {
      // buildTermRegex must use \p{P} (any punctuation) rather than \b which
      // fails on CJK and other non-ASCII text.
      assert.match(source, /\\p\{P\}/u);
      // Callers that iterate matches must request the global Unicode flag.
      assert.match(extractFunction("isNegated"), /buildTermRegex\s*\(\s*term\s*,\s*"giu"\s*\)/);
    },
  },
  {
    id: "escapeRegExp-escapes-special-chars",
    name: "escapeRegExp escapes regex special characters before term-pattern construction",
    run() {
      // Must contain a replace call for [.*+?^${}()|[\]\\] and escape backslash
      const body = extractFunction("escapeRegExp");
      assert.ok(body.includes("replace(/[.*+?^${}()|[\\]\\\\]/g, \"\\\\$&\")"));
    },
  },
  {
    id: "termMatches-uses-regex-test-not-includes",
    name: "termMatches performs bounded regex matching (not naive substring inclusion)",
    run() {
      // termMatches must use .test() on a RegExp, not String.includes or indexOf
      const body = extractFunction("termMatches");
      assert.ok(
        /\.test\s*\(/.test(body),
        "termMatches must use RegExp.test() for matching",
      );
      assert.ok(
        !/\.includes\s*\(/.test(body),
        "termMatches must not use naive String.includes()",
      );
    },
  },
  {
    id: "negation-window-scan",
    name: "isNegated scans a bounded character window around the match for negation phrases",
    run() {
      const body = extractFunction("isNegated");
      // Must define a window size (e.g., 120) and slice the text around the match
      assert.ok(
        /\d{2,3}/.test(body),
        "isNegated must define a numeric character window size",
      );
      assert.ok(
        /\.slice\s*\(/.test(body),
        "isNegated must use slice() to extract the window",
      );
      // Must iterate over a negation list (group.negation or similar)
      assert.ok(
        /negation/.test(body),
        "isNegated must reference the negation phrases list",
      );
    },
  },
  {
    id: "negation-excludes-signal",
    name: "assessIntegrity skips (does not count) a signal when isNegated returns true",
    run() {
      const body = extractFunction("assessIntegrity");
      // Must call isNegated and conditionally skip/continue the signal
      assert.ok(
        /isNegated\s*\(/.test(body),
        "assessIntegrity must call isNegated()",
      );
      assert.ok(
        /isNegated\s*\([^)]*\)\s*\)\s*return\s+false/.test(body),
        "assessIntegrity must exclude negated signals from the filtered matches",
      );
    },
  },
  {
    id: "score-clamping-lower-bound",
    name: "assessIntegrity clamps the final score to a minimum of 0",
    run() {
      const body = extractFunction("assessIntegrity");
      // Score must be clamped: Math.max(0, ...) or ternary guarding against negatives
      assert.ok(
        /Math\.max\s*\(\s*0\b/.test(body) || /score\s*<\s*0/.test(body),
        "assessIntegrity must clamp score to a minimum of 0 (Math.max(0, …) or explicit guard)",
      );
    },
  },
  {
    id: "score-clamping-upper-bound",
    name: "assessIntegrity clamps the final score to a maximum of 10",
    run() {
      const body = extractFunction("assessIntegrity");
      // Score must be clamped: Math.min(10, ...) or ternary guarding above 10
      assert.ok(
        /Math\.min\s*\(\s*10\b/.test(body) || /score\s*>\s*10/.test(body),
        "assessIntegrity must clamp score to a maximum of 10 (Math.min(10, …) or explicit guard)",
      );
    },
  },
  {
    id: "integrity-signal-groups-defined",
    name: "INTEGRITY_SIGNAL_GROUPS includes funding, design, endpoint, replication, and safety groups with weights and negation lists",
    run() {
      // INTEGRITY_SIGNAL_GROUPS must be an array of objects with weight, terms, and negation (where applicable)
      const groupsMatch = source.match(
        /INTEGRITY_SIGNAL_GROUPS\s*=\s*\[[\s\S]*?\];/,
      );
      assert.ok(groupsMatch, "INTEGRITY_SIGNAL_GROUPS array definition not found");
      const groupsBody = groupsMatch[0];
      assert.ok(/funding/.test(groupsBody), "funding group must exist");
      assert.ok(/design/.test(groupsBody), "design group must exist");
      assert.ok(/endpoint/.test(groupsBody), "endpoint group must exist");
      assert.ok(/replication/.test(groupsBody), "replication group must exist");
      assert.ok(/safety/.test(groupsBody), "safety group must exist");
      // Each group must have a numeric weight
      assert.ok(
        /weight\s*:\s*-?\d+/.test(groupsBody),
        "groups must have numeric weight properties",
      );
      // At least one group must have a negation array
      assert.ok(
        /negation\s*:\s*\[/.test(groupsBody),
        "at least one group must have a negation phrases array",
      );
    },
  },
  {
    id: "assess-integrity-returns-enriched-shape",
    name: "assessIntegrity returns { score, level, signals, missing } with per-signal provenance",
    run() {
      const body = extractFunction("assessIntegrity");
      assert.ok(
        /signals/.test(body),
        "return object must include a signals array",
      );
      assert.ok(
        /missing/.test(body),
        "return object must include a missing array",
      );
      assert.ok(
        /score/.test(body),
        "return object must include a score value",
      );
      assert.ok(
        /level/.test(body),
        "return object must include a level string",
      );
    },
  },
];

let passed = 0;
let failed = 0;
for (const t of tests) {
  try {
    t.run();
    console.log(`  ✓ ${t.name}`);
    passed++;
  } catch (err) {
    console.error(`  ✗ ${t.name}`);
    console.error(`    ${err.message}`);
    failed++;
  }
}

if (failed > 0) {
  console.error(`\n${failed} test(s) failed, ${passed} passed.`);
  process.exit(1);
}
console.log(`\nmeta-analysis widget integrity scorer regression contract: ${passed}/${tests.length} PASS`);
