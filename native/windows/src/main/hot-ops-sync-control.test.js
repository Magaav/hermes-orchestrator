"use strict";
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { createHotOpsSyncControl } = require("./hot-ops-sync-control");

const mainSource = fs.readFileSync(path.join(__dirname, "..", "main.js"), "utf8");
const buildConfig = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "electron-builder.json"), "utf8"));
assert(mainSource.includes("hotOpsSyncControl.handle"));
assert(buildConfig.files.includes("main/hot-ops-sync-control.js"));

(async () => {
  let resolveSync; let calls = 0; let clock = Date.parse("2026-08-28T14:00:00Z");
  const control = createHotOpsSyncControl({
    now: () => clock, stuckMs: 1000, list: (payload) => ({ ok: true, requested: payload.operationName || "", availableHotOps: [{ name: "canary" }] }),
    sync: () => { calls += 1; return new Promise((resolve) => { resolveSync = resolve; }); },
  });
  const started = control.handle("sync_downloaded_hot_ops", {});
  assert.strictEqual(started.result.accepted, true); assert.strictEqual(started.result.completed, false);
  await Promise.resolve();
  const duplicate = control.handle("refresh_downloaded_hot_ops", {});
  assert.strictEqual(duplicate.result.deduplicated, true); assert.strictEqual(calls, 1);
  const listed = control.handle("list_hot_operations", {});
  assert.strictEqual(listed.result.availableHotOps[0].name, "canary"); assert.strictEqual(listed.result.syncLifecycle.phase, "running");
  assert.strictEqual(control.handle("list_hot_operations", { operationName: "canary" }).result.requested, "canary");
  clock += 1500; assert.strictEqual(control.snapshot().stuck, true);
  resolveSync({ ok: true, changed: true, feedBundleId: "bundle-current", bundles: [{ files: ["x".repeat(100_000)] }] }); await new Promise((resolve) => setImmediate(resolve));
  assert.strictEqual(control.snapshot().phase, "completed"); assert.strictEqual(control.snapshot().changed, true);
  assert.strictEqual(control.snapshot().feedBundleId, "bundle-current"); assert.strictEqual(control.snapshot().bundleCount, 1);
  assert.strictEqual(Object.hasOwn(control.snapshot(), "result"), false); assert(JSON.stringify(control.snapshot()).length < 1000);
  const unrelated = control.handle("run_hot_operation", {}); assert.strictEqual(unrelated.handled, false);
  console.log("hot ops sync control tests passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
