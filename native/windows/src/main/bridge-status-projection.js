"use strict";

const SCHEMA = "hermes.wasm_agent.windows_bridge_status.v1";
const MAX_LOGS = 20;

function compactDownloadedRuntime(runtime = {}) {
  return { supported: runtime.supported === true, protocol: Number(runtime.protocol || runtime.runtimeLoaderProtocolVersion || 0), activeRuntimeId: String(runtime.activeRuntimeId || runtime.activeDownloadedRuntimeId || ""), activeRuntimeSha: String(runtime.activeRuntimeSha || runtime.activeDownloadedRuntimeSha || ""), syncStatus: String(runtime.syncStatus || ""), stale: runtime.stale === true, staleReason: String(runtime.staleReason || "") };
}

function compactKernel(kernel = {}) {
  return { schema: String(kernel.schema || ""), kernelContractVersion: String(kernel.kernelContractVersion || kernel.nativeKernelVersion || kernel["native.kernel.version"] || ""), installedNativeBuildId: String(kernel.installedNativeBuildId || kernel.nativeBuildId || ""), installedNativeVersion: String(kernel.installedNativeVersion || kernel.appVersion || ""), supportedCapabilities: Array.isArray(kernel.supportedCapabilities) ? kernel.supportedCapabilities : [], missingCapabilities: Array.isArray(kernel.missingCapabilities) ? kernel.missingCapabilities : [], unsupportedCapabilities: Array.isArray(kernel.unsupportedCapabilities) ? kernel.unsupportedCapabilities : [], activeDownloadedRuntimeId: String(kernel.activeDownloadedRuntimeId || ""), activeDownloadedRuntimeSha: String(kernel.activeDownloadedRuntimeSha || ""), activeHotOpBundleId: String(kernel.activeHotOpBundleId || ""), activeHotOpSha: String(kernel.activeHotOpSha || ""), syncStatus: String(kernel.syncStatus || ""), stale: kernel.stale === true, staleReason: String(kernel.staleReason || "") };
}

function compactHotOperations(hot = {}) {
  const catalog = hot.hotOpsCatalog && typeof hot.hotOpsCatalog === "object" ? hot.hotOpsCatalog : {};
  const sync = hot.downloadedHotOpsSync && typeof hot.downloadedHotOpsSync === "object" ? hot.downloadedHotOpsSync : {};
  return { supported: true, protocol: Number(hot.hotOpsProtocolVersion || hot.supportedHotOpsProtocol || 0), mode: String(hot.hotOpsMode || ""), root: String(hot.hotOpsRoot || ""), devReload: hot.devReload === true, catalog: { schema: String(catalog.schema || ""), count: Number(catalog.count || 0), detailCommand: "list_hot_operations" }, sync: { ok: sync.ok === true, changed: sync.changed === true, bundleCount: Number(sync.bundleCount || 0), error: String(sync.error || "") } };
}

function requested(options = {}, camel, snake) { return options[camel] === true || options[snake] === true; }

function createBridgeStatus(fields = {}, options = {}) {
  const includeDetails = requested(options, "includeDetails", "include_details");
  const includeLogs = requested(options, "includeLogs", "include_logs");
  const logs = Array.isArray(fields.logsTail) ? fields.logsTail : [];
  const common = { schema: SCHEMA, ok: true, stable: true, operation: "get_bridge_status", source: "shell", shellProtocolVersion: fields.shellProtocolVersion, hotOpsProtocolVersion: fields.hotOpsProtocolVersion, minimumRunnerVersion: fields.minimumRunnerVersion, capabilities: Array.isArray(fields.capabilities) ? fields.capabilities : [], buildId: String(fields.buildId || ""), buildSha: String(fields.buildSha || ""), appVersion: String(fields.appVersion || ""), arch: String(fields.arch || ""), platform: String(fields.platform || ""), nativeKernel: includeDetails ? fields.kernel : compactKernel(fields.kernel), downloadedRuntime: includeDetails ? fields.downloadedRuntime : compactDownloadedRuntime(fields.downloadedRuntime), hotOperations: includeDetails ? fields.hotOperations : compactHotOperations(fields.hotOperations), activeDownloadedRuntimeId: String(fields.kernel?.activeDownloadedRuntimeId || ""), activeDownloadedRuntimeSha: String(fields.kernel?.activeDownloadedRuntimeSha || ""), activeHotOpBundleId: String(fields.kernel?.activeHotOpBundleId || ""), activeHotOpSha: String(fields.kernel?.activeHotOpSha || ""), syncStatus: String(fields.kernel?.syncStatus || ""), staleReason: String(fields.kernel?.staleReason || ""), logsTail: includeLogs ? logs.slice(-MAX_LOGS) : [], logCount: Number(fields.logCount || logs.length), detailAvailable: true, failureClassification: null, nextAction: "Run list_hot_operations, run_shell_self_test, then canary_echo." };
  if (includeDetails) common.kernel = fields.kernel;
  return common;
}

function compactHeartbeat(fields = {}) {
  const output = { ...fields, nativeKernel: compactKernel(fields.nativeKernel), downloadedRuntime: compactDownloadedRuntime(fields.downloadedRuntime), hotOperations: compactHotOperations(fields.hotOperations), logsTail: [], logCount: Number(fields.logCount || 0), diagnosticDetailCommand: "get_bridge_status" };
  delete output.kernel;
  return output;
}

module.exports = { MAX_LOGS, SCHEMA, compactDownloadedRuntime, compactHeartbeat, compactHotOperations, compactKernel, createBridgeStatus };
