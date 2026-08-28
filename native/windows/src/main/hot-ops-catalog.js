"use strict";

const SCHEMA = "hermes.wasm_agent.windows_hot_ops_catalog.v1";

function operationName(operation = {}) {
  return String(operation.name || operation.operationId || "").trim();
}

function compactOperation(operation = {}) {
  return {
    name: operationName(operation),
    operationId: String(operation.operationId || operationName(operation)),
    version: String(operation.version || ""),
    loadedFrom: String(operation.loadedFrom || ""),
    detailAvailable: true,
  };
}

function detailedOperation(operation = {}) {
  return {
    name: operationName(operation),
    version: operation.version,
    entry: operation.entry,
    manifest: operation.manifest,
    loadedFrom: operation.loadedFrom,
    sha256: operation.sha256,
    capabilities: operation.capabilities,
    requiredNativeCapabilities: operation.requiredNativeCapabilities,
    operationId: operation.operationId,
    inputsSchema: operation.inputsSchema,
    outputsSchema: operation.outputsSchema,
    safetyLimits: operation.safetyLimits,
    rollback: operation.rollback,
    timeoutMs: operation.timeoutMs,
  };
}

function compactSyncResult(result = {}) {
  return {
    ok: result.ok === true,
    changed: result.changed === true,
    attemptedAt: String(result.attemptedAt || ""),
    syncedAt: String(result.syncedAt || ""),
    error: String(result.error || ""),
    feedBundleId: String(result.feedBundleId || ""),
    cachedBundleId: String(result.cachedBundleId || ""),
    moduleSha: String(result.moduleSha || ""),
    manifestSha: String(result.manifestSha || ""),
    bundleCount: Array.isArray(result.bundles) ? result.bundles.length : 0,
  };
}

function projectHotOpsCatalog(operations = [], options = {}) {
  const reference = String(options.operationName || options.operation_name || "").trim();
  const includeDetails = options.includeDetails === true || options.include_details === true || Boolean(reference);
  if (includeDetails && !reference) {
    return { ok: false, failureClassification: "hot_operation_reference_required", catalog: { schema: SCHEMA, mode: "detail", count: operations.length, requested: "", found: false }, availableHotOps: [] };
  }
  if (reference) {
    const found = operations.find((operation) => operationName(operation) === reference || String(operation.operationId || "") === reference);
    if (!found) return { ok: false, failureClassification: "hot_operation_missing", catalog: { schema: SCHEMA, mode: "detail", count: operations.length, requested: reference, found: false }, availableHotOps: [] };
    return { ok: true, failureClassification: null, catalog: { schema: SCHEMA, mode: "detail", count: operations.length, requested: reference, found: true }, availableHotOps: [detailedOperation(found)] };
  }
  return { ok: true, failureClassification: null, catalog: { schema: SCHEMA, mode: "summary", count: operations.length, requested: "", found: null }, availableHotOps: operations.map(compactOperation) };
}

module.exports = { SCHEMA, compactOperation, compactSyncResult, detailedOperation, projectHotOpsCatalog };
