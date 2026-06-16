"use strict";

function text(value) {
  return String(value || "").trim();
}

function classifyDiagnostics(diagnostics = {}, args = {}) {
  const kernel = diagnostics.kernel || diagnostics.nativeKernel || diagnostics;
  const runtime = kernel.downloadedRuntime || diagnostics.downloadedRuntime || {};
  const expectedRuntimeBundleId = text(args.expectedRuntimeBundleId || args.expected_runtime_bundle_id);
  const activeRuntimeId = text(kernel.activeDownloadedRuntimeId || runtime.activeRuntimeId || runtime.bundleId);
  const activeRuntimeSha = text(kernel.activeDownloadedRuntimeSha || runtime.activeRuntimeSha || runtime.bundleSha);
  const missingCapabilities = Array.isArray(kernel.missingCapabilities) ? kernel.missingCapabilities : [];
  const staleReason = text(kernel.staleReason || runtime.staleReason || runtime.mismatchReason);

  if (missingCapabilities.length) {
    return {
      ok: false,
      stable: false,
      failureClassification: "runtime_missing_capability",
      nextAction: `Native shell is missing ${missingCapabilities.join(", ")}.`,
    };
  }
  if (!activeRuntimeId || !activeRuntimeSha) {
    return {
      ok: false,
      stable: false,
      failureClassification: "runtime_bundle_missing",
      nextAction: "Force-sync the downloaded runtime bundle from the release feed.",
    };
  }
  if (expectedRuntimeBundleId && activeRuntimeId !== expectedRuntimeBundleId) {
    return {
      ok: false,
      stable: false,
      failureClassification: "runtime_bundle_stale",
      nextAction: "Open or ping the native shell so it activates the latest runtime bundle.",
    };
  }
  if (staleReason) {
    return {
      ok: false,
      stable: false,
      failureClassification: staleReason,
      nextAction: "Inspect release-feed metadata, cached bundle metadata, and last-known-good fallback.",
    };
  }
  return {
    ok: true,
    stable: true,
    failureClassification: "pass",
    nextAction: "Runtime, capabilities, and hot-op metadata are current.",
  };
}

async function run(context) {
  const args = context.args || {};
  const diagnostics = args.diagnostics && typeof args.diagnostics === "object" ? args.diagnostics : {};
  const result = classifyDiagnostics(diagnostics, args);
  return {
    ...result,
    operation: "classify_native_diagnostics",
    source: "hot_operation",
    classifierVersion: "20260614T0000",
    activeDownloadedRuntimeId: text(diagnostics.activeDownloadedRuntimeId || diagnostics.downloadedRuntime?.activeRuntimeId),
    activeDownloadedRuntimeSha: text(diagnostics.activeDownloadedRuntimeSha || diagnostics.downloadedRuntime?.activeRuntimeSha),
  };
}

module.exports = { run, classifyDiagnostics };
