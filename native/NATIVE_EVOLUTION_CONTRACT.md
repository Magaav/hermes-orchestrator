# Native Evolution Contract

WASM Agent Native shells are stable capability kernels. Product behavior,
proof policy, diagnostics classifiers, launcher UI, model metadata, and lab
experiments must ship through release-feed runtime or hot-op bundles whenever
the native OS capability surface does not change.

## Kernel Contract

| Field | Meaning |
| --- | --- |
| `native.kernel.version` | Versioned native capability contract. |
| `installedNativeBuildId` | Native shell build installed on the device. |
| `supportedCapabilities` | Stable primitives exposed by that shell. |
| `missingCapabilities` | Required contract capabilities not present. |
| `activeDownloadedRuntimeId` / `activeDownloadedRuntimeSha` | Current server-published runtime bundle. |
| `activeHotOpBundleId` / `activeHotOpSha` | Current server-published operation bundle. |
| `syncStatus` | Last runtime and hot-op sync status. |
| `staleReason` | Precise mismatch reason when the shell is not current. |

Windows advertised native capabilities:

```text
native.capabilities.runtimeLoader.v1
native.capabilities.hotOps.v1
native.capabilities.statusBus.v1
native.capabilities.diagnostics.v1
native.capabilities.fileStore.v1
native.capabilities.downloadedRuntime.v1
native.capabilities.downloadedOperations.v1
native.capabilities.deviceControl.v1
native.capabilities.webViewBridge.v1
native.capabilities.boundedCommand.v1
native.capabilities.auditLog.v1
native.capabilities.releaseFeedValidation.v1
native.capabilities.nativeControlPolling.v1
native.capabilities.crashSafeStatus.v1
native.capabilities.capabilityManifest.v1
native.capabilities.observabilityLease.v1
native.capabilities.unrestrictedExecution.v1
native.capabilities.companionOverlay.v1
native.capabilities.windowsUiAutomation.v1
```

Android advertised native capabilities:

```text
native.capabilities.runtimeLoader.v1
native.capabilities.hotOps.v1
native.capabilities.statusBus.v1
native.capabilities.diagnostics.v1
native.capabilities.fileStore.v1
native.capabilities.downloadedRuntime.v1
native.capabilities.downloadedOperations.v1
native.capabilities.audioCapture.v1
native.capabilities.modelRuntime.v1
native.capabilities.foregroundSession.v1
native.capabilities.webViewBridge.v1
native.capabilities.boundedCommand.v1
native.capabilities.auditLog.v1
native.capabilities.releaseFeedValidation.v1
native.capabilities.crashSafeStatus.v1
native.capabilities.capabilityManifest.v1
native.capabilities.observabilityLease.v1
```

Control-plane commands:

```text
get_native_kernel_status
sync_downloaded_runtime
refresh_downloaded_runtime
rollback_downloaded_runtime
sync_downloaded_hot_ops
refresh_downloaded_hot_ops
list_hot_operations
run_shell_self_test
run_hot_operation
observability_enable
observability_collect
observability_status
observability_disable
```

`observabilityLease.v1` is off by default. `observability_enable` grants a
5–120 second lease, `observability_collect` returns bounded aggregate analytics
and performance fields, and expiry or `observability_disable` detaches the
debugger immediately. Electron uses `webContents.debugger` without a TCP debug
port; Android enables the WebView DevTools socket only for the lease. A plain
PWA reports `observe.cdp.external_on_demand` because browser CDP must be supplied
by an authorized external browser controller.

Windows release evolution is unattended after the first installation: the
login-persistent supervisor owns Electron, the client validates the HTTPS feed,
build ordering, artifact type, byte size, origin/path, and SHA-256, then invokes
NSIS silently and relaunches through the supervisor. Normal checks occur once
at startup and every six hours; observability remains disabled throughout.

Use three evolution lanes instead of rebuilding every change:

| Change | Lane | Windows reinstall |
| --- | --- | --- |
| Avatar/chat visuals, layout, transcript, or composer in the cloud PWA | Cloud PWA reload/deploy | No |
| Downloaded runtime or trusted hot-op behavior on an existing primitive | Atomic runtime/hot-op feed | No |
| New Electron IPC, OS permission, UIA primitive, supervisor, preload, or installer behavior | `horc build win` plus feed/supervisor update | Once per shell change |

`horc build win` and `horc build android-apk` run the declared-path selector in
`tools/windows/select-native-evolution-lane.py` before packaging. Cloud-only and
hot-bundle changes stop with the cheaper lane instead of producing an installer.
Hot-bundle eligibility is bound to the installed kernel capabilities recorded by
the latest successful hot-shell proof. Use `HORC_FORCE_NATIVE_REBUILD=1` only
when the caller intentionally needs a fresh installer from an otherwise mixed or
externally supplied source set.

After a cloud PWA release, `client.runtime.refresh` is the bounded autonomous
reload primitive. It is same-origin only, cache-busts the production renderer,
and returns `client.runtime.refresh.scheduled`; it does not claim the post-load
renderer healthy. Use the next live heartbeat plus `client.runtime.diagnose`
as independent post-load proof. Native runtime/hot-op activation continues to
use SHA-verified staging and last-known-good rollback.

For the companion/desktop surface, the focused source lane is
`HORC_WIN_FAST_PACK=0 HORC_WIN_FAST_TASKS=test:companion-desktop-source horc build win-fast`.
It measured 3.390 seconds on Linux aarch64 on 2026-08-26, versus 142.741 and
169.096 seconds for the two preceding full Windows release records. This is
source evidence only; it intentionally produces no installer, feed, or
installed-app proof.

The final lazy-startup companion/UIA release subsequently completed in 112.750
seconds. Thus the registered source loop is 33.3x faster than the current full
package lane; use the latter only at the native-shell promotion boundary.

## Bundle Formats

Downloaded runtime bundles use
`hermes.wasm_agent.downloaded_runtime.v1`: manifest plus HTML, CSS, JS,
diagnostic schema, config, and model metadata files. Native shells download
the changed files into a staging directory, verify SHA-256 metadata, activate
the staged bundle atomically, and preserve `last-known-good`.

Exact downloaded runtime feed shape:

```json
{
  "artifacts": {
    "runtime": {
      "launcher": {
        "kind": "native-runtime-bundle",
        "bundleId": "native-launcher-runtime-<sha-prefix>",
        "runtimeId": "native-launcher-runtime-<sha-prefix>",
        "bundleSha": "<sha256>",
        "manifestSha": "<sha256>",
        "updateMode": "downloaded-runtime-atomic",
        "fallback": "last-known-good",
        "files": [
          {
            "role": "manifest",
            "url": "/native/releases/runtime/launcher/runtime-manifest.json",
            "targetPath": "launcher/runtime-manifest.json",
            "sha256": "<sha256>",
            "sizeBytes": 0
          }
        ]
      }
    }
  }
}
```

Hot-op bundles use
`hermes.wasm_agent.hot_operation_manifest.v1`: manifest plus operation module.
Every operation declares `requiredNativeCapabilities`, `timeoutMs`,
`inputsSchema`, `outputsSchema`, `safetyLimits`, and rollback behavior. Missing
capabilities fail as `hot_operation_capability_denied` or
`runtime_missing_capability`; SHA mismatches fail as `hot_operation_sha_mismatch`.

Exact hot-op manifest shape:

```json
{
  "schema": "hermes.wasm_agent.hot_operation_manifest.v1",
  "name": "run_android_hermes_wake_proof",
  "operationId": "run_android_hermes_wake_proof",
  "entry": "hermes-wake-proof.js",
  "requiredNativeCapabilities": [
    "native.capabilities.deviceControl.v1",
    "native.capabilities.statusBus.v1",
    "native.capabilities.hotOps.v1"
  ],
  "capabilities": ["adb.device", "adb.shell", "diagnostics.read", "result.upload"],
  "timeoutMs": 180000,
  "inputsSchema": {"type": "object"},
  "outputsSchema": {"type": "object"},
  "safetyLimits": {"network": "native-diagnostics-upload-only"},
  "rollback": {"mode": "last-known-good", "fallbackOperation": "canary_echo"}
}
```

Non-Hermes proof that the architecture is general:
`classify_native_diagnostics` ships as
`artifacts.hotOps.diagnostics.nativeDiagnosticsClassifier` and classifies
runtime/kernel diagnostics without Android wake logic.

## No-Rebuild Rule

Rebuild native only for a new OS permission, manifest-level capability, native
library/runtime, hardware/OS primitive, security bootstrap change, or a broken
native capability contract that cannot be fixed remotely. Everything else
ships through downloaded runtime, hot-op, config, model metadata, or server UI.
