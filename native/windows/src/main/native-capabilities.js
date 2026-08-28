"use strict";

const ALL_NATIVE_KERNEL_CAPABILITIES = [
  "runtimeLoader", "hotOps", "statusBus", "diagnostics", "fileStore", "downloadedRuntime",
  "downloadedOperations", "deviceControl", "audioCapture", "modelRuntime", "foregroundSession",
  "webViewBridge", "boundedCommand", "auditLog", "releaseFeedValidation", "nativeControlPolling",
  "speaker", "crashSafeStatus", "capabilityManifest", "observabilityLease", "unrestrictedExecution",
  "companionOverlay", "windowsUiAutomation",
].map((name) => `native.capabilities.${name}.v1`);

const WINDOWS_NATIVE_KERNEL_CAPABILITIES = ALL_NATIVE_KERNEL_CAPABILITIES.filter((capability) => ![
  "native.capabilities.audioCapture.v1",
  "native.capabilities.modelRuntime.v1",
  "native.capabilities.foregroundSession.v1",
  "native.capabilities.speaker.v1",
].includes(capability));

const BRIDGE_PROTOCOL_CAPABILITIES = [
  "get_bridge_status", "get_native_kernel_status", "list_hot_operations", "refresh_downloaded_runtime",
  "sync_downloaded_runtime", "rollback_downloaded_runtime", "refresh_downloaded_hot_ops",
  "sync_downloaded_hot_ops", "run_shell_self_test", "run_hot_operation", "observability_enable",
  "observability_collect", "observability_disable", "observability_status",
  "windows_shell_execute_unrestricted", "windows.shell.execute.unrestricted",
  "companion.overlay.show", "windows.desktop.notepad_uia_canary",
  "windows.desktop.describe", "windows.desktop.inspect", "windows.desktop.act", "windows.desktop.prove",
];

module.exports = { ALL_NATIVE_KERNEL_CAPABILITIES, BRIDGE_PROTOCOL_CAPABILITIES, WINDOWS_NATIVE_KERNEL_CAPABILITIES };
