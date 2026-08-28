"use strict";

const assert = require("node:assert");
const { compactSyncResult, projectHotOpsCatalog } = require("./hot-ops-catalog");

const operations = Array.from({ length: 30 }, (_, index) => ({
  name: `operation_${index}`,
  operationId: `operation_${index}`,
  version: "1",
  loadedFrom: "downloaded",
  inputsSchema: { type: "object", properties: { payload: { type: "string", description: "x".repeat(10_000) } } },
  outputsSchema: { type: "object" },
  safetyLimits: { note: "y".repeat(10_000) },
  timeoutMs: 20_000,
}));

const summary = projectHotOpsCatalog(operations);
assert.strictEqual(summary.ok, true);
assert.strictEqual(summary.catalog.mode, "summary");
assert.strictEqual(summary.availableHotOps.length, 30);
assert.strictEqual(Object.hasOwn(summary.availableHotOps[0], "inputsSchema"), false);
assert(JSON.stringify(summary).length < 8_000, "summary must stay bounded when detail schemas are huge");

const detail = projectHotOpsCatalog(operations, { operationName: "operation_7" });
assert.strictEqual(detail.ok, true);
assert.strictEqual(detail.catalog.mode, "detail");
assert.strictEqual(detail.availableHotOps.length, 1);
assert.strictEqual(detail.availableHotOps[0].inputsSchema.properties.payload.description.length, 10_000);

const missing = projectHotOpsCatalog(operations, { operationName: "missing" });
assert.strictEqual(missing.ok, false);
assert.strictEqual(missing.failureClassification, "hot_operation_missing");

const unbounded = projectHotOpsCatalog(operations, { includeDetails: true });
assert.strictEqual(unbounded.ok, false);
assert.strictEqual(unbounded.failureClassification, "hot_operation_reference_required");

const sync = compactSyncResult({ ok: true, changed: true, feedBundleId: "current", bundles: [{ files: ["x".repeat(100_000)] }] });
assert.strictEqual(sync.bundleCount, 1);
assert.strictEqual(Object.hasOwn(sync, "bundles"), false);
assert(JSON.stringify(sync).length < 500);

console.log("hot ops catalog tests passed");
