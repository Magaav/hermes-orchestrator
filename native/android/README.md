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
| Voice wake iteration | Prefer existing compatible wake models, model install, and live policy over rebuilding APK for every model |
| Active device ADB lane | The physical Android device is reachable only through the installed Windows bridge in the current setup; Codex/cloud-local `adb devices` is expected to be empty and is not Android-disconnected evidence |
| Dataset export bridge | Use the installed Win11 wasm-agent bridge command `export_hermes_wake_dataset`; terminal ADB from this workspace is not a valid path for this workflow |
| False-wake capture | Android stores at most 50 local false-wake samples under app-private storage; successful bridge/server acknowledgement deletes confirmed samples |
| Wake Word state | `files/native-diagnostics/voice-wake.json`, `WasmAgentNative.getWakeWordState()`, downloaded operation `fetch_wake_word_state`, and live policy operation `apply_wake_word_policy` expose/tune the foreground-service wake lane packet |
| Copilot fast path | Android implementation of the generic live-introspection rule: prefer native control `get_runtime_snapshot`, Wake Word state, and live `apply_wake_word_policy` before asking the user to describe state or proposing another APK rebuild |

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
| Latest Wake model export | implemented-unverified | `/native/android/hermes-wake-model/latest` is the compatibility endpoint for the app-private `files/voice/hermes.onnx` install bridge. A model may target any configured wake phrase if it satisfies the Android raw-PCM ONNX contract. The previous Hermes-trained SHA remains calibration evidence, not a generic readiness gate. Installed runtime restart/debug proof is still required. |
| Latest Android simulation report | verified | `reports/sim/android/latest/summary.md` PASS for voice wake fixture, run `android-20260608T154817920Z`; separate from current installed proof. |
| Android OAuth native return | implemented-unverified | Requires connected-device/emulator report proving native return and authenticated WebView/session. |
| Alexa wake baseline | implemented-unverified | 2026-06-20 Windows-bridge proof on Xiaomi Mi 9 SE with build `android-universal-20260620T115820Z` routed `alexa. open wake word` to `open_wake_word` from timeline evidence. Confirmation-2 hot-op policy reached service diagnostics, and the latest `open settings` negative produced no timeline wake, but the positive confirmation-2 room loop still produced duplicate wake events. Direct ADB service start is rejected because `HermesVoiceWakeService` is non-exported; app-mediated WAO/native-control policy now clears proof mode and applies confirmation/cooldown, but installed service status still reports threshold `0.92` after requesting `0.999`. Baseline is not accepted: fresh `app.responsiveness` WAO/native-event evidence shows the Android WebView overloaded with multi-second frame gaps/event-loop lag/long tasks, so wake tuning must pause until responsiveness is healthy. |

## Build

```bash
HORC_ANDROID_BUILD_MODE=auto horc build android-apk
```

Before choosing a rebuild, run a short loop reflection:

1. Architecture: can the change move behind server/native control policy,
   downloaded model/runtime metadata, hot-op, HMR, or another live-updatable
   surface so future iterations avoid APK rebuilds?
2. Hot path: can this particular change be made through live policy,
   native-control commands, PWA/server HMR, downloaded runtime/hot-op, model
   install, diagnostics upload, or another faster path?
3. Observability: would a flattened state field, watcher script, command result,
   diagnostic event, or accessibility affordance make the next proof obvious and
   prevent another blind rebuild? Add the smallest useful probe first when it
   materially shortens the loop.

After each rebuild, run a matching loop review:

1. Check `reports/build/android/build-benchmarks.jsonl` for selected mode,
   duration, tasks, cache behavior, artifact sizes, and storage counters.
2. Verify package/feed proof separately from runtime proof.
3. Decide whether more speed work is practical, or whether the loop is already
   limited by fresh update identity, signing, APK size, guided install, or
   installed runtime proof.

Direct release script:

```bash
cd native/android
node scripts/release-android.js
```

Fast inner-loop build:

```bash
horc build android-fast
```

For wake/transcript debugging, flatten the latest installed Android
native-control state with:

```bash
native/android/scripts/watch-wake-state.sh
native/android/scripts/watch-wake-state.sh --watch
```

The watcher highlights listener readiness, live audio, inference movement, wake
count, ASR engine, transcript result, and compact SpeechRecognizer/Vosk
diagnostics.

`android-fast` uses the same local-vs-Docker Android toolchain selection but
stops at the debug APK under `app/build/outputs/apk`. It does not sign release
artifacts, promote `release/`, publish the native release feed, or prove package
or runtime behavior. Use `HORC_ANDROID_FAST_TASKS` to narrow Gradle tasks, and
lab `HORC_ANDROID_GRADLE_DAEMON=1` or `HORC_ANDROID_CONFIGURATION_CACHE=1` there
before considering them for the release lane.

Both `horc build android` and `horc build android-fast` append benchmark JSONL
records to `reports/build/android/build-benchmarks.jsonl`. Track duration,
status, selected build mode, tasks, output sizes, and storage counters there
when evaluating whether the fast lane is improving over time.

Keep Android build wiring shared: SDK/Gradle/Docker setup, generated assets,
dependencies, native libraries, and packaging guards belong in shared `horc`
helpers or Gradle configuration. The fast lane may differ only by variant,
selected tasks, and skipped release promotion/proof/feed work.

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
runs when `apksigner` is available. Docker builds prefer the repo-cached Android
SDK at `.android-sdk` when present, so repeated cloud builds do not reinstall
SDK build-tools inside each container. The native release feed generator also
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

Proof sessions are intentionally more permissive than production listening:
while `proof_session_active=true`, the service bypasses VAD so acceptance
tooling can observe raw model confidence. Cooldown is still honored, and source
starts a fresh post-transcript refractory window before returning to standby so
one spoken wake phrase cannot re-fire from its acoustic tail. The refractory
window is live-tunable as `wakeCooldownMs`/`wake_cooldown_ms` and defaults to
`12000`. Source also adds a second-stage wake confirmation gate: raw model
threshold spikes are recorded as `raw_wake_detection_count`, but command capture
starts only after `wakeConfirmationFrames`/`wake_confirmation_frames` detections
inside `wakeConfirmationWindowMs`/`wake_confirmation_window_ms`. The production
default is two frames in `700ms`; lab/proof can set one frame only when raw
model acceptance evidence is needed. Production standby must run with
`proof_session_active=false`. Source
also treats proof mode as non-sticky: any non-proof start/status clears
`proofSessionActive`, clears the proof threshold override, and reloads
providers before writing status. These source behaviors require APK
install/runtime proof before they can be claimed as deployed. On 2026-06-19,
the installed service was recovered without reinstall by stop/start; the
following ambient hold showed `wake_hits=0`, `false_wake_count=0`, and max
confidence `0.487` below threshold
`0.99`.

Wake status also distinguishes fresh capture from stale capture. The foreground
service writes `audio_capture_stale`, `audio_capture_stale_ms`,
`inference_stale`, `inference_stale_ms`, `audio_watchdog_active`,
`audio_loop_stall_count`, and `last_audio_loop_stall_at`; if `AudioRecord.read`
stops delivering frames for more than eight seconds while listening, the
watchdog records `audio_capture_stalled` and stops the active recorder so the
listener loop can create a fresh one. A missed wake word is not model evidence
unless audio freshness and inference counters are moving during the stimulus
window.

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
`WasmAgentNative.getWakeWordState()`, downloaded operation
`fetch_wake_word_state`, and backend view
`GET /native/android/wake-word-state` after diagnostics upload.
`getWakeWordState()` is a lightweight UI/status read and must not initialize
ONNX or perform full model diagnostics; explicit proof/debug operations own
heavy model checks. `recent_events` is capped at 50. Guided live tuning uses downloaded operation
`apply_wake_word_policy` to update `wakePhrase`, `wakeThreshold`,
`wakeCooldownMs`, `vadRmsThreshold`, `vadPeakThreshold`, and
`tuningSessionId` in app preferences; the service refreshes its provider set
without stopping the listener. Existing
open-source wake phrases are acceptable for first testing when their model is
compatible with the raw-PCM ONNX engine. A 2026-06-17
installed run at threshold `0.58` produced `wake_hit_count: 910` and
`false_wake_count: 909`; the native default is now a conservative `0.92` with a
short cooldown to prevent repeated hits from one noisy condition.

The Android-hosted Wake Word lab now exposes the fast first-device loop: its
Install model action fetches `/native/android/hermes-wake-model/latest.json`,
installs a staged `openwakeword_bundle` through `installOpenWakeWordBundle()`,
applies live policy, and starts the foreground listener. Its compact WAO agent
view uses `/native/obs/agent-view` plus socket snapshots to show ordered
wake/command evidence without requiring full JSON polling. The current staged
openWakeWord first-test metadata says `wakePhrase: alexa`; a bundle entry named
`hey_jarvis.onnx` is only the Android engine contract filename for the
classifier slot, not proof that the spoken phrase is "hey jarvis".
To stage a compatible open-source candidate for bridge install without an APK
rebuild:

```bash
tools/voice/stage-wake-model-candidate.py \
  --model path/to/model.onnx \
  --wake-phrase "hey jarvis" \
  --model-name "open-source hey jarvis" \
  --source "source URL or repo"
```

This writes
`plugins/wasm-agent/state/native-diagnostics/android-hermes-wake-models/latest/hermes.onnx`
plus `metadata.json`. Queue `/native/android/hermes-wake-install/request` after
staging; the Android-hosted PWA installs the model through
`installHermesWakeModel()` and applies the queued wake phrase policy.

For openWakeWord, stage the full three-model Android bundle:

```bash
tools/voice/stage-openwakeword-bundle.py \
  --source-dir path/to/openwakeword-onnx-files \
  --wake-phrase "hey jarvis" \
  --model-name "openWakeWord hey jarvis" \
  --source "https://github.com/dscripka/openWakeWord"
```

The staged `openwakeword.zip` contains `melspectrogram.onnx`,
`embedding_model.onnx`, and `hey_jarvis.onnx`; the same install queue serves it
as `engineContract: openwakeword_bundle`, and Android installs it into
`files/voice/openwakeword` with `installOpenWakeWordBundle()`.
The same policy path also owns the post-Hermes command-capture handoff:
`transcriptTimeoutMs`, `transcriptMinLengthMs`,
`transcriptCompleteSilenceMs`, `transcriptPossibleSilenceMs`, and
`transcriptAcceptPartial` are persisted by Android, applied to
`SpeechRecognizer`, and echoed in Wake Word diagnostics. Prefer live policy
tuning through server control/downloaded operations before rebuilding the APK.
The cloud Wake Word state also exposes server-side diagnosis labels and
experiment presets. Presets include `fast_transcript`, `forgiving_transcript`,
`partial_first`, and `final_only_probe`; diagnosis labels include
`wake_threshold_not_crossed`, `wake_heard_no_transcript`,
`transcript_rejected_unknown_command`, and `command_capture_active`. Agents
should use these labels and preset payloads to choose the next live policy
before requesting another rebuild.

Post-wake command transcription now has two ASR lanes. Android can
select `transcriptEngine=vosk`, `android_speech`, or `auto` through the same
`apply_wake_word_policy` bridge. The Android SpeechRecognizer lane tries
English, device locale, language-only locale, and provider-default recognition
within the transcript timeout, preserving per-attempt diagnostics so
`ERROR_NO_MATCH`, missing beginning-of-speech, locale mismatch, and partial
fallback are distinguishable. The Vosk lane records a bounded PCM16 16 kHz
command window after Hermes fires, decodes in chunks against a short command
grammar, then retries free recognition if grammar decoding is empty; diagnostics
include partial, intermediate, and final Vosk JSON. Wake Word state reports
`local_asr_vosk_ready`, `local_asr_vosk_model_path`, `local_asr_vosk_error`,
`last_asr_engine`, `last_asr_latency_ms`, and `last_asr_audio_captured_ms`.
The expected model directory is app-private `files/asr/vosk-model`; the APK may
bundle `assets/asr/vosk-model`, which the voice wake service copies into
app-private storage on start. Build-time model input is
`WASM_AGENT_ANDROID_VOSK_MODEL_DIR` or
`native/android/build/generated/asr/vosk-model`. If no bundled or installed
model is present, `vosk` reports `vosk_model_missing`, while `auto` falls back
to Android SpeechRecognizer.
The post-ASR command gate normalizes local transcripts before routing: Vosk
unknown markers such as `[unk]` are stripped, filler words are ignored, and the
bundled grammar aliases `wake word`, `start listener`, `stop listener`, and
clipped `listener` map to canonical Wake Word commands. Wake Word state echoes
`last_normalized_transcript` and `last_voice_command` so a live refresh can
separate ASR quality from command routing quality.
Blank ASR results remain false-wake evidence, but a nonblank transcript with no
canonical command must be dispatched as freeform active-session input. The
2026-06-19 real-device proof crossed the `alexa` wake threshold and transcribed
`can you hear me`; installed runtime still classified that as `unknown_command`,
so source now records `freeform_transcript` and posts the voice event instead of
incrementing false-wake counters for understood speech.
The 2026-06-20 Alexa command loop proved `alexa. open wake word` can transcribe
`open wake word`, route `open_wake_word`, and dispatch HTTP 200, but the latest
balanced faster transcript policy fell back to Vosk, returned only `word`, and
took about 10.5s. Treat that plan as rejected for baseline until a fresh policy
keeps the full command while reducing post-command linger.
`transcriptPlan`/`transcript_attempt_plan` is the hot-swappable transcript
strategy primitive: a downloaded operation or native-control command can send
an ordered `attempts` array such as Android Speech `en-US`, Android Speech
device locale, Vosk grammar, then Vosk free recognition. After an APK with this
primitive is installed, changing attempt order, language tags, Vosk grammar, and
grammar-vs-free mode should be a live policy update, not another APK rebuild.
Cloud presets include `local_vosk_command`, `android_speech_fallback`, and
`planned_transcript_probe` for live A/B proof after install.

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
panel, open modals, Wake Word state, capability flags, recent redacted events,
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

Treat Android WebView responsiveness as the next gate before further wake
tuning. Inspect `app.responsiveness` native events and the `responsiveness`
section emitted by `tools/voice/run-wake-room-loop.py`; do not accept wake-word
policy while the app reports multi-second frame gaps, event-loop lag, long
tasks, or slow native-control polling. Also fix/prove threshold propagation
through the app-mediated `apply_wake_word_policy` path: production mode is now
cleared with `proof_session_active=false`, but the installed service still
reports `wake_threshold=0.92` after a `0.999` request. Once responsiveness and
policy state are healthy, rerun the Alexa positive/negative room proofs from
the wasm-agent README resume block, then continue avatar-shine and
transcript-linger tuning. Hermes/custom wake words and
music/noise/hard-environment tests remain later phases. Android OAuth native
return remains a separate installed-app proof lane.
