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
| False-wake capture | Android stores at most 50 local false-wake samples under app-private storage; successful bridge/server acknowledgement deletes confirmed samples |
| Wake Word state | `files/native-diagnostics/voice-wake.json`, `WasmAgentNative.getWakeWorldState()`, downloaded operation `fetch_wake_world_state`, and live policy operation `apply_wake_word_policy` expose/tune the foreground-service wake lane packet |
| Copilot fast path | Android implementation of the generic live-introspection rule: prefer native control `get_runtime_snapshot`, Wake World state, and live `apply_wake_word_policy` before asking the user to describe state or proposing another APK rebuild |

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
| Latest Hermes Wake model export | implemented-unverified | `build/voice/hermes.onnx` was trained from `hermes-dataset-20260616T215020Z.zip`, served by `/native/android/hermes-wake-model/latest` with SHA `2abbebf21610f91f8d1fcfc12ac92f8ec19dc1191f3c90dbda4cba46e71027b2`, and installed through the Android bridge request. Calibration remains below the production acceptance gate; installed runtime restart/debug proof is still required. |
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

Voice tuning silence samples should capture ordinary ambient room/mic noise, not
near-digital silence. The Android quality gate rejects silence only when
sustained RMS or the loud sample ratio is too high, and the user-facing error
should guide the user toward a quieter spot or lower mic gain.

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
SHA-256 `2abbebf21610f91f8d1fcfc12ac92f8ec19dc1191f3c90dbda4cba46e71027b2`,
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

False-wake capture is bounded and best-effort. After wake detection, if command
capture produces no usable transcript, Android asynchronously writes a short
PCM16 mono 16 kHz WAV window plus metadata to `files/voice/false-wakes/`.
Metadata includes wake confidence, threshold, timestamp, model SHA, transcript
result when available, rejection reason, providers, and build ID. The directory
is capped at 50 samples and deletes the oldest sample before accepting sample
51. Storage write failures are logged and do not block the wake service.

The Android bridge exposes `getFalseWakeBatch()` and
`confirmFalseWakeBatchUploaded(idsJson)`, and downloaded operations may call
`get_android_false_wake_batch` / `confirm_android_false_wake_batch_uploaded`.
The backend accepts pushed batches at `/native/android/false-wake-batch` and
returns acknowledged IDs with `deleteLocal: true`; Android deletes confirmed
local samples only after that fetch/upload acknowledgement. Voice wake
diagnostics expose `false_wake_buffer_count`, `false_wake_buffer_max`,
`false_wake_last_uploaded_at`, `false_wake_last_deleted_count`, and
`false_wake_storage_bytes`.

Wake Word is the dashboard/control surface over the same Android foreground
wake service. The service remains the canonical listener for AudioRecord, ONNX
inference, wake counters, false-wake capture, diagnostics, recent lifecycle
events, and app event delivery. Do not start an independent in-app
AudioRecord/ONNX loop while this lane is active. The Wake Word packet is
available from `files/native-diagnostics/voice-wake.json`, bridge method
`WasmAgentNative.getWakeWorldState()`, downloaded operation
`fetch_wake_world_state`, and backend view
`GET /native/android/wake-world-state` after diagnostics upload.
`getWakeWorldState()` is a lightweight UI/status read and must not initialize
ONNX or perform full model diagnostics; explicit proof/debug operations own
heavy model checks. `recent_events` is capped at 50. Guided live tuning uses downloaded operation
`apply_wake_word_policy` to update `wakeThreshold`, `vadRmsThreshold`,
`vadPeakThreshold`, and `tuningSessionId` in app preferences; the service
refreshes its provider set without stopping the listener. A 2026-06-17
installed run at threshold `0.58` produced `wake_hit_count: 910` and
`false_wake_count: 909`; the native default is now a conservative `0.92` with a
short cooldown to prevent repeated hits from one noisy condition.
The same policy path also owns the post-Hermes command-capture handoff:
`transcriptTimeoutMs`, `transcriptMinLengthMs`,
`transcriptCompleteSilenceMs`, `transcriptPossibleSilenceMs`, and
`transcriptAcceptPartial` are persisted by Android, applied to
`SpeechRecognizer`, and echoed in Wake Word diagnostics. Prefer live policy
tuning through server control/downloaded operations before rebuilding the APK.
The cloud Wake World state also exposes server-side diagnosis labels and
experiment presets. Presets include `fast_transcript`, `forgiving_transcript`,
`partial_first`, and `final_only_probe`; diagnosis labels include
`wake_threshold_not_crossed`, `wake_heard_no_transcript`,
`transcript_rejected_unknown_command`, and `command_capture_active`. Agents
should use these labels and preset payloads to choose the next live policy
before requesting another rebuild.

Post-wake command transcription now has a local ASR lane. Android can select
`transcriptEngine=vosk`, `android_speech`, or `auto` through the same
`apply_wake_word_policy` bridge. The Vosk lane records a bounded PCM16 16 kHz
command window after Hermes fires, recognizes against a short command grammar,
and reports `local_asr_vosk_ready`, `local_asr_vosk_model_path`,
`local_asr_vosk_error`, `last_asr_engine`, `last_asr_latency_ms`, and
`last_asr_audio_captured_ms` in Wake World state. The expected model directory
is app-private `files/asr/vosk-model`; if it is missing, `vosk` reports
`vosk_model_missing`, while `auto` falls back to Android SpeechRecognizer.
Cloud presets include `local_vosk_command` and `android_speech_fallback` for
live A/B proof after install.

When voice wake is enabled, the Android foreground microphone service is the
only supported background listener. On a detected Hermes wake, it requests
`MainActivity` in Wake Word mode and starts command capture. The service
preserves the enabled preference across non-user service destruction, schedules
a short self-restart after task removal, and restores after boot, user unlock,
or app package replacement. A user force-stop remains an Android OS boundary:
the app cannot keep listening or auto-launch again until the user opens it.

Android WebView bootstrap must keep first touch responsive. Renderer diagnostic
bridge calls append quickly, while full `latest.json` snapshots and uploads are
debounced off the JavaScript bridge call path. The PWA compacts queued startup
diagnostics before flushing them to native, defers admin bridge refresh/render
work while Android Home is active, delays nonessential Home module/message DOM
work until after the shell is visible, and caches Wake Word state briefly so
opening the Wake Word modal performs one lightweight bridge read instead of
repeated synchronous reads.
Remote-control access must follow the same rule. Polling is compact and may be
skipped while the user is touching, typing, scrolling, or when input is pending.
Heavy work such as diagnostics export, screenshots, UI tree captures, or log
bundles must be command-triggered, idle-scheduled, bounded, and allowed to
return a skipped result instead of competing with app rendering or wake capture.
The default copilot sync command is `get_runtime_snapshot`: it returns active
panel, open modals, Wake World state, capability flags, recent redacted events,
recent interaction trace, and at most 30 visible controls with compact rects.
It does not capture pixels by default; screenshots remain explicit heavy
commands.

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
