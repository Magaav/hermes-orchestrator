"use strict";

const assert = require("node:assert");
const { compactHeartbeat, createBridgeStatus, createKernelStatus, createRuntimeSyncStatus } = require("./bridge-status-projection");

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
const kernelSummary = createKernelStatus(kernel, logs);
assert.strictEqual(kernelSummary.logsTail.length, 0); assert.strictEqual(kernelSummary.kernel.supportedCapabilities.length, 2); assert(JSON.stringify(kernelSummary).length < 3_000);
const kernelDetail = createKernelStatus(kernel, logs, { includeDetails: true, includeLogs: true });
assert.strictEqual(kernelDetail.kernel, kernel); assert.strictEqual(kernelDetail.logsTail.length, 20);
const sync = { ok: true, changed: true, activeRuntimeId: "runtime-1", files: [{ body: "z".repeat(100_000) }] };
const runtimeSummary = createRuntimeSyncStatus("sync_downloaded_runtime", sync, runtime, logs);
assert.strictEqual(runtimeSummary.downloadedRuntimeSync.fileCount, 1); assert.strictEqual(Object.hasOwn(runtimeSummary.downloadedRuntimeSync, "files"), false); assert.strictEqual(runtimeSummary.logsTail.length, 0); assert(JSON.stringify(runtimeSummary).length < 3_000);
const runtimeDetail = createRuntimeSyncStatus("sync_downloaded_runtime", sync, runtime, logs, { includeDetails: true });
assert.strictEqual(runtimeDetail.downloadedRuntimeSync, sync); assert.strictEqual(runtimeDetail.downloadedRuntime, runtime);
console.log("bridge status projection tests passed");
