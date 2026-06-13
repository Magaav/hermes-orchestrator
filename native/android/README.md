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

`horc build all` also publishes APKs into
`plugins/wasm-agent/public/native/releases/android/`.

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

Repo-side automation lives at `tools/voice/ship-hermes-wake.sh`. With
`WASM_AGENT_NATIVE_CONTROL_KEY` set, it queues `export_hermes_wake_dataset` for
the polling Win11 native bridge, waits for the backend upload, imports the zip,
trains `build/voice/hermes.onnx`, validates the production candidate, and prints
the `/native/android/hermes-wake-model/latest.json` SHA for Android bridge
installation.

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

Ship `android-universal-20260612T201043Z` only with the paired release feed
entry that points at SHA
`15d49526bf556368597796a8ac4c6991376088b4dbd709d36a25f47cb753ad06` and
runtime proof status `installed-windows-bridge-hermes-wake-verified`. Android
OAuth native return remains a separate installed-app proof lane.
