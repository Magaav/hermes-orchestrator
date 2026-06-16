# wasm-agent Android Native

`native/android` owns the Android APK shell, WebView/native bridge, foreground
service, voice wake pipeline, sideload/update metadata, and Android runtime
proof lane for WASM Agent Native.

## Contract

| Rule | Value |
| --- | --- |
| Production backend | `https://wa.colmeio.com` |
| Release local origins | Forbidden in production APKs: `127.0.0.1:8877`, `localhost:8877`, `0.0.0.0:8877`, `10.0.2.2:8877` |
| Debug origins | Debug-only through BuildConfig/dev settings |
| Secrets | No account secrets or pre-minted device tokens in downloadable APKs |
| OAuth success | Must return to installed app and authenticate WebView/session |
| Voice wake iteration | Prefer dataset/model loop over rebuilding APK for every model |
| Dataset export bridge | Use the installed Win11 wasm-agent bridge command `export_hermes_wake_dataset`; terminal ADB from this workspace is not a valid path for this workflow |

Read first: `/local/AGENTS.md`, `/local/README.md`, `docs/context/MAP.md`,
`native/AGENTS.md`, `native/NATIVE_SHELL_CONTRACT.md`, this directory's
`AGENTS.md`, then this file.

## Current Evidence

| Evidence | Status | Notes |
| --- | --- | --- |
| Release manifest `android-universal-20260612T201043Z` | verified | `native/android/release/release-manifest.json`; SHA `15d49526bf556368597796a8ac4c6991376088b4dbd709d36a25f47cb753ad06`. |
| Sidecar defaults | verified | `native/android/release/WASM-Agent-arm64.native-defaults.json` uses `https://wa.colmeio.com`, `allowLocalDev: false`. |
| APK signature proof | implemented-unverified | `assembleRelease` passed; Docker `apksigner verify` timed out under emulation after 600s on 2026-06-12. |
| Forbidden-origin APK scan | implemented-unverified | Raw compressed APK `strings` scan did not expose definitive literals; run proper package scan with Android tooling. |
| Hermes Wake installed proof | verified | Windows bridge installed `android-universal-20260612T201043Z` on Xiaomi Mi 9 SE and uploaded live diagnostics at `2026-06-12T20:47:00Z`: `status_source=live_service`, `proof_session_active=true`, `audio_record_started=true`, model SHA match, ONNX ready, wake engine ready, `inference_count=10`. |
| Latest Android simulation report | verified | `reports/sim/android/latest/summary.md` PASS for voice wake fixture, run `android-20260608T154817920Z`; separate from current installed proof. |
| Android OAuth native return | implemented-unverified | Requires connected-device/emulator report proving native return and authenticated WebView/session. |

## Build

```bash
HORC_ANDROID_BUILD_MODE=auto horc build android-apk
```

Direct release script:

```bash
cd native/android
node scripts/release-android.js
```

The release script builds and promotes:

```text
native/android/release/WASM-Agent-universal.apk
native/android/release/WASM-Agent-arm64.apk
native/android/release/release-manifest.json
```

`horc build android` clears inherited Android build identity by default so each
release-promotion rebuild publishes a fresh update identity in the native feed.
On ARM hosts using the linux/amd64 Docker builder, container-side
`apksigner verify` is skipped to avoid QEMU hangs; host-side verification still
runs when `apksigner` is available. The native release feed generator also
promotes a newer signed Gradle `app-release.apk` into `native/android/release/`
before publishing `/native/releases/latest.json`, so the Go Native Android
download resolves to the newest built APK.

`horc build all` also publishes APKs into
`plugins/wasm-agent/public/native/releases/android/`. When
`HORC_ANDROID_RUN_UNIT_TESTS=1`, the release script submits unit tests and
release assembly to one parallel-capable Gradle invocation to avoid repeated
startup/configuration cost.

## Verification

Package proof:

```bash
apksigner verify --verbose native/android/release/WASM-Agent-arm64.apk
sha256sum native/android/release/WASM-Agent-arm64.apk
unzip -p native/android/release/WASM-Agent-arm64.apk assets/wa.colmeio.com.android-native-shell.txt
```

Runtime proof:

```bash
horc simulate android
```

After installing a newly trained `files/voice/hermes.onnx`, Android proof mode
must show `model_sha_match=true`, `wake_engine_ready=true`,
`inference_count>0`, a Hermes `max_observed_confidence`, `threshold_crossed=true`,
`wake_detection_count>0`, `wake_detected_event_emitted=true`, and
`command_capture_started=true`. A silence/normal-speech proof pass must not
trigger wake detection. Do not globally lower the production threshold as the
model fix; temporary proof threshold overrides are only for downstream command
capture testing.

## Native Evolution Layer

Android exposes the native capability kernel through the WebView bridge objects
`window.wasmAgentNative` and `window.WasmAgentNativeVoiceTuning`. Stable generic
methods are:

```text
getKernelStatus()
syncDownloadedRuntime(manifestJson)
forceSyncDownloadedRuntime(manifestJson)
rollbackDownloadedRuntime()
runDownloadedOperation(operationManifestJson, inputsJson)
```

Android stores downloaded runtime metadata in app shared preferences and reports
`downloadedRuntime`, `nativeKernel`, and `hotOperations` from shell config and
native diagnostics. It does not silently replace the installed APK. It can,
however, accept server-published runtime/operation manifests, compare required
native capabilities, expose active bundle IDs/SHAs, and route product logic to
stable native primitives without an APK rebuild.

Android advertised capabilities:

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
```

The first downloaded-operation proof path is `run_android_hermes_wake_proof`.
Its operation inputs may set `wakeThreshold` or `wake_threshold`; the Android
foreground service persists that value as `voice_wake_threshold`, reloads the
wake engine with the new threshold, and reports `wake_threshold`,
`threshold_policy_source`, and `policy_source` in
`files/native-diagnostics/voice-wake.json`. Changing this threshold, proof
timeout, classifier logic, diagnostics schema, launcher UI, config, or model
metadata should not require an APK rebuild as long as the installed capability
kernel already exposes the required native primitives.

An APK rebuild is still required for new Android permissions, manifest service
declarations, native libraries such as ONNX Runtime changes, package identity,
signing/update behavior, notification/foreground-service categories, or a new
native primitive that cannot be expressed through the generic bridge.

Hermes Wake acceptance must pass a readiness preflight before listening for the
spoken wake word. The report must show microphone permission granted,
foreground service running, `AudioRecord` started, ONNX Runtime available in
the installed APK/runtime, personalized `files/voice/hermes.onnx` present with
SHA-256 `23aee3f94d9499c7809b413037a59e3e6f8668767a49e077017e743dd959e58c`,
WakeEngine initialized, `voice_wake.enabled: true`, `wake_engine_ready: true`,
and `inference_count > 0`. Real-device wake acceptance then has eight separate
stages: service alive, audio capture alive, ONNX model ready, inference running,
wake confidence observed, wake threshold crossed, wake event emitted, and
command capture/UI action started. `voice-wake.json` must expose per-window
confidence diagnostics (`confidence`, max confidence, threshold, detection
count, last detection timestamp, and rejection reason) so a positive spoken
Hermes utterance can be classified as below-threshold versus routed into command
capture. A failed preflight must include hard fields such as
`disabled_reason`, `onnx_runtime_error`, `wake_engine_error`, `model_path`,
`model_exists`, `model_sha`, and `model_sha_match`; do not rerun wake acceptance
as-is while `onnx_runtime_available` is false.

Windows-bridge real-device wake proof uses the installed Win11 generic bridge
operation `run_hot_operation` with the hot-op manifest
`android/hermes-wake-proof.manifest.json` resolving
`android/hermes-wake-proof.js`. The repo helper
`tools/voice/run-hermes-wake-proof.py` defaults to the local bridge at
`http://127.0.0.1:8877`, reads heartbeat hot-op capabilities, prints the active
root/mode, verifies the Hermes wake manifest is visible when the bridge reports
available ops, then queues compact manifest-based `run_hot_operation` through
local-state/cloud control. The hot op launches the Android app with
`native_screen=hermes-wake-proof`, waits while the operator speaks "Hermes",
uses the shell diagnostics fallback primitive for
`files/native-diagnostics/voice-wake.json`, and reports the eight acceptance
stages without treating readiness alone as wake detection. If the installed
Windows shell lacks the generic hot-op/list/protocol contract, the helper
classifies `bridge_update_required`; if the manifest is not visible it
classifies `hot_operation_missing`. Old command-specific fallback is opt-in with
`--allow-stale-command-fallback`.

Hermes Wake dataset export is a Win11 installed-app bridge workflow. Do not
attempt to pull `files/voice/exports/hermes-dataset.zip` with terminal ADB from
this Linux workspace; that path is unavailable here and wastes the shipping
loop. Use the Windows wasm-agent app Diagnostics/Frontier bridge operation
`export_hermes_wake_dataset`, or fetch the protected uploaded dataset from the
cloud with an admin session or native control key.

Historical superseded repo-side automation used `tools/voice/ship-hermes-wake.sh`
for the dataset/model loop. The current wake debug path depends on installed
Windows hot-op shell proof first, then
`tools/voice/run-hermes-wake-proof.py --dry-run` and
`tools/voice/run-hermes-wake-proof.py --debug`.

Copied-report validation:

```bash
horc simulate android --local-report <path>
```

The report must name the behavior proven. A voice wake PASS does not prove
Google OAuth. A browser/PWA callback does not prove Android native success.

Launcher icon proof after artwork changes:

```bash
python3 native/android/scripts/verify-launcher-icon.py
```

## Update Flow

Android sideload updates are guided installs:

1. Download APK.
2. Verify SHA-256.
3. Refuse package-name mismatch.
4. Refuse `versionCode` that is not greater than installed.
5. Launch Android package installer and let the user confirm.

Silent replacement is not implemented outside device-owner/root/store-managed
install paths.

## Durable Next Step

After installed Windows hot-op shell proof passes, run Hermes wake dry-run and
debug proof through `run_hot_operation`. The next proof must classify spoken
"Hermes" doing nothing as `wake_threshold_not_crossed`,
`wake_event_not_emitted`, or `command_capture_ui_not_started`. Android OAuth
native return remains a separate installed-app proof lane.
