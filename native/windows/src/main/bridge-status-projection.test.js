"use strict";

const assert = require("node:assert");
const { compactHeartbeat, createBridgeStatus } = require("./bridge-status-projection");

const logs = Array.from({ length: 80 }, (_, index) => `log-${index}-${"x".repeat(1_000)}`);
const runtime = { supported: true, protocol: 1, activeRuntimeId: "runtime-1", activeRuntimeSha: "a".repeat(64), syncStatus: "current", lastSync: { files: ["y".repeat(100_000)] } };
const kernel = { schema: "kernel.v1", kernelContractVersion: "1", installedNativeBuildId: "build-1", supportedCapabilities: ["a", "b"], downloadedRuntime: runtime, activeDownloadedRuntimeId: "runtime-1", activeHotOpBundleId: "ops-1" };
const hotOperations = { hotOpsProtocolVersion: 1, hotOpsMode: "downloaded", hotOpsRoot: "root", hotOpsCatalog: { schema: "catalog.v1", count: 17 }, downloadedHotOpsSync: { ok: true, bundleCount: 17, bundles: ["z".repeat(100_000)] }, availableHotOps: [{ inputsSchema: { description: "q".repeat(100_000) } }] };
const fields = { shellProtocolVersion: 2, hotOpsProtocolVersion: 1, minimumRunnerVersion: "1", capabilities: ["get_bridge_status"], buildId: "build-1", appVersion: "1", arch: "x64", platform: "win32", kernel, downloadedRuntime: runtime, hotOperations, logsTail: logs, logCount: logs.length };

const summary = createBridgeStatus(fields);
assert.strictEqual(summary.ok, true); assert.strictEqual(Object.hasOwn(summary, "kernel"), false); assert.strictEqual(summary.logsTail.length, 0); assert.strictEqual(summary.logCount, 80); assert(JSON.stringify(summary).length < 5_000);
const withLogs = createBridgeStatus(fields, { includeLogs: true });
assert.strictEqual(withLogs.logsTail.length, 20); assert(withLogs.logsTail[0].startsWith("log-60-"));
const detail = createBridgeStatus(fields, { includeDetails: true });
assert.strictEqual(detail.kernel, kernel); assert.strictEqual(detail.nativeKernel, kernel); assert.strictEqual(detail.logsTail.length, 0);
const heartbeat = compactHeartbeat({ nativeKernel: kernel, downloadedRuntime: runtime, hotOperations, logsTail: logs, logCount: 80 });
assert.strictEqual(heartbeat.logsTail.length, 0); assert(JSON.stringify(heartbeat).length < 5_000);
console.log("bridge status projection tests passed");
