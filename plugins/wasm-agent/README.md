# wasm-agent

`plugins/wasm-agent` owns the active WASM Agent PWA, backend, account state,
native bridge, native release feed, Frontier controls, and product UI surfaces.
It is the default place for workspace, browser, account, relay, native
download/update, and bridge work.

## Current Contract

| Capability | Status | Proof / verifier | Notes |
| --- | --- | --- | --- |
| Local PWA development on `http://127.0.0.1:8877` | implemented-unverified | `horc simulate web` | Dev-only. Never use as production native claim. |
| Production native backend target | verified | Root guards; native defaults; release feed | `https://wa.colmeio.com` only. |
| Client-first workspace state | implemented-unverified | focused tests under `tests/` | Server is for auth, presence/relay, sync, backup, provisioning, diagnostics, release metadata. |
| Omni-device feature default | verified | Root/context/agent docs | Ship shared PWA/runtime behavior first. Prefer browser APIs, WASM, WebGPU/WebNN, downloaded model/runtime artifacts, version/SHA metadata, browser cache, and IndexedDB before native shell code. |
| LLM-native context default | proposal | docs only | Embedded-agent/model-facing context should become a tiny text envelope plus on-demand lookup tools, with expanded human diagnostics kept separate from prompt input. |
| Cheap autonomous agent architecture | implemented-unverified first slice | `LLM_NATIVE_AGENT_ARCHITECTURE.md`; focused server tests | wasm-agent resolves declarative route contracts before direct-head/provider work. The Agent Kernel layer exposes generic `kernel.capabilities`, `kernel.resolve`, `kernel.inspect`, `kernel.act`, and `kernel.prove` primitives over route, map, lookup, bounded read, scoped patch, focused test, diff, proof, cost, and bounded Hermes capability/dispatch tools. Hermes remains a bounded skill/bridge executor, not the owner of product routing or broad workspace search. |
| Account auth allowlist | implemented-unverified | auth tests; `conf/README.md` | `ADMIN_EMAIL` and optional `USER_EMAILS`; empty allowlists reject all Google accounts. |
| Native release feed | implemented-unverified | `plugins/wasm-agent/public/native/releases/latest.json`; `reports/windows/latest/windows-release-feed-check.json` | Current local Windows feed guard fails without `native/windows/release/VERIFY.json`; feed publication is not installed runtime proof. |
| Downloaded native runtime feed | implemented-unverified | `artifacts.runtime.launcher` in release feed; `node plugins/wasm-agent/tests/native_release_feed.test.js` | Requires installed native shells with downloaded-runtime sync before runtime IDs/SHAs are installed evidence. |
| Windows trusted hot-op feed | implemented-unverified | `artifacts.hotOps.android.hermesWakeProof` in release feed; `node plugins/wasm-agent/tests/native_release_feed.test.js`; `npm run test:windows-hot-ops` | Requires an installed Windows shell with downloaded-hot-op sync before proof can report `hotOpSource=downloaded`. |
| Frontier operator loop | implemented-unverified | focused server/control tests or gated curl proof | Commands must remain authenticated, audited, bounded, and operation-based. |
| Dev HMR | implemented-unverified | `horc simulate web`; JS smoke tests | Local developer convenience, not production sync contract. |
| Hermes Wake data/model loop | implemented-unverified | Android bridge/model tests and device proof | Prefer dataset/model iteration over APK rebuilds. |
| Wake Word dashboard | implemented-unverified | `WasmAgentNative.getWakeWordState()`; `apply_wake_word_policy`; `GET /native/android/wake-word-state`; focused UI/native smoke checks | Single control center and guided live-tuning loop over the Android foreground wake service, with Train Hermes Wake nested inside and avatar wake feedback from live state. |
| Embedded-chat speech transcription | implemented-unverified | `node --experimental-vm-modules tests/speech_transcription_module.test.mjs`; `node tests/wasm_agent_smoke.test.js`; browser/device proof still required | Shared PWA/runtime mic button and worker-owned local ASR boundary with versioned Transformers.js 4.2.0, ONNX Runtime WASM, Whisper tiny English fp16 assets, frame-batched AudioWorklet capture with ScriptProcessor fallback, click-time worker/model warmup, same-SHA cache reuse with SHA cache markers, speech-gated pre-roll buffering, noise-adaptive VAD threshold diagnostics, enforced adaptive rolling partials, partial token streaming, duration-capped decode, ONNX graph optimization, and deterministic beam final decode. No native dictation bridge and no remote STT; production runtime proof still requires browser/device mic validation. |
| Host Browser/CDP | implemented-unverified | security-loop/browser tests | Disabled by default on public HTTPS unless explicitly reviewed. |
| Windows installed-app behavior | implemented-unverified | Windows verifier in `native/windows` | Do not claim fixed from PWA/source tests. |
| Android runtime behavior | implemented-unverified | `horc simulate android` | Report must name the behavior proven. |

## Production Security

| Rule | Source |
| --- | --- |
| Public origin terminates at `https://wa.colmeio.com`; raw app port stays loopback/private. | `PUBLIC_LAUNCH_SECURITY.md`; `LAUNCH.md` |
| `conf/wa.env` is machine-local and untracked. | `conf/README.md` |
| Protected routes return `401 auth_required` until a signed allowed-account session exists. | backend auth tests |
| Host Browser WebSocket streams reject missing or cross-origin `Origin` headers. | security tests |
| Frontier/control routes require admin session, localhost operator access, or `X-Wasm-Agent-Native-Control-Key`. | server routes |
| Destructive Frontier commands require an explicit destructive gate. | server routes |
| No arbitrary shell execution through PWA, Frontier, or native bridge. | `AGENTS.md`; native contracts |

## Read Map

| Path | Owns | Read / verify |
| --- | --- | --- |
| `AGENTS.md` | Local binding contract | Read before any plugin edit. |
| `LLM_NATIVE_AGENT_ARCHITECTURE.md` | Cheap autonomous embedded-agent architecture | Read before embedded-agent, avatar-chat routing, Hermes dispatch, context budget, or token accounting work. |
| `LLM_NATIVE_AGENT_MANIFEST_PLAN.md` | Implementation plan, critique loop, acceptance gates, and frontier prompt for the cheap autonomous agent | Read before implementing route contracts, provider adapters, token ledgers, or run timelines. |
| `LLM_NATIVE_AGENT_SOURCE_HARVEST.md` | Source-harvested acceptance gates for map, recall, receipts, and token economics | Read before changing the wasm-agent kernel path or adding new route/proof/token contracts. |
| `DESIGN.md` | Frontend shell and visual regression contract | Read before UI/CSS/HTML work. |
| `conf/README.md` | Configuration defaults and private env handling | Read before auth/env/deployment changes. |
| `server/README.md` | Python backend ownership and runtime notes | Read before server/API/auth/Frontier edits. |
| `state/README.md` | Gitignored runtime state layout | Read before touching state paths. |
| `public/modules/README.md` | PWA module boundary | Read before module registry/module work. |
| `public/native/releases/latest.json` | Generated native release feed | Treat as generated release metadata. |
| `tests/` | Focused regression checks | Add/update fast test for behavior changes. |

## Commands

| Need | Command |
| --- | --- |
| Start workspace | `horc space start` |
| Start PWA only | `/local/plugins/wasm-agent/scripts/start_wasm_agent.sh` |
| Stop PWA | `/local/plugins/wasm-agent/scripts/stop_wasm_agent.sh` |
| Doctor | `/local/plugins/wasm-agent/scripts/doctor.sh` |
| Android lite performance budget | `node plugins/wasm-agent/tests/android_lite_performance_budget.test.js` |
| Web simulation | `horc simulate web` |
| Avatar-chat route/token quest simulation | `horc simulate web --avatar-quest` |
| Android simulation | `horc simulate android` |
| Native feed build | `horc build all` |
| Windows feed guard | `python3 tools/windows/check-windows-release-feed.py` |
| Hermes Wake proof | `python3 tools/voice/run-hermes-wake-proof.py --dry-run`; `python3 tools/voice/run-hermes-wake-proof.py --debug` |

## LLM-Native Embedded Assistant Direction

The durable architecture is specified in
`LLM_NATIVE_AGENT_ARCHITECTURE.md`. It replaces reactive routing by code
heuristic with declarative route contracts: surface, owner, workspace root,
allowed roots, capabilities, proof, and token budget must be resolved before
Hermes or any other provider is invoked.

Do not add product strings, CSS selectors, DOM classes, filenames, or feature
labels to `server/static_server.py` to fix routing. That is a regression. Add
or fix the route contract, then make runtime code load/enforce it.

The embedded assistant should evolve toward an LLM-native context ABI. The
production target is not "more JSON in the prompt"; it is a tiny baseline
envelope that names the active space, viewport, selected node, recent event
codes, transcript summary handle, and available lookup handles. The model should
pull expanded observation, files, logs, screenshots, Timeline state, or
diagnostics only when the next decision needs them.

Model-facing protocols optimize for tokenizer cost and reasoning quality. Use
short stable text codes, shared dictionaries, fixed field order, redaction, and
measured byte/token budgets. Keep human-readable observation inspectors and
debug JSON available for operators, but do not make those expanded structures
the default model input. Binary protocols, base64 payloads, protobuf, gRPC, raw
screenshots, full logs, and full client snapshots are not prompt defaults.

Production-grade proof for this direction must show the old and new baseline
context bytes/tokens, preserve answer/action quality on representative
avatar-chat turns, keep context preview inspectable, and keep connection-drop
resume behavior intact.
Avatar-chat also exposes a compact `agentNodeSelect` diagnostic snapshot so
native/PWA selector parity can be proven without scraping the dropdown.
Use `horc simulate web --avatar-quest` as the local behavioral gate for a
two-turn avatar-chat UI quest: it verifies route contract resolution before
provider dispatch on each turn, exact token ledger persistence by
quest/turn/provider call, summed quest totals, no broad Hermes fallback, and
contained timeline/token-ledger UI.

The first Agent Kernel slice is exposed under `POST /agent/tools/*` and is
MCP-compatible by shape rather than a separate MCP server. The LLM-facing
kernel primitives are `kernel.capabilities`, `kernel.resolve`,
`kernel.inspect`, `kernel.act`, and `kernel.prove`. They sit above the route
tools: `route.resolve`, `map.summary`, `lookup.files`, `lookup.symbol`,
`file.read_bounded`, `patch.apply_scoped`, `test.run_focused`,
`git.diff_summary`, `proof.collect`, `cost.status`, `hermes.capabilities`, and
`hermes.dispatch_bounded`.

MCP/tool policy belongs in `server/master_frontier/`, not in the
`server/static_server.py` monolith. `static_server.py` may authenticate,
resolve route contracts, record run events, and execute side effects, but new
tool vocabularies, action schemas, repair prompts, code-memory query policy,
and token-budget behavior must be implemented as Master:frontier modules with
focused tests.

The code-memory slice exposes route-scoped `code.memory.index`,
`code.memory.status`, `code.memory.search`, and `code.memory.impact` wrappers
around `codebase-memory-mcp`. Use these before broad file reads or Hermes
dispatch when a task needs repository structure, symbol lookup, or change blast
radius. Results must stay compact by default: symbol/file/risk summaries first,
bounded source reads only after the graph narrows the target.

The direct-head envelope exposes a compact generic kernel projection instead
of a growing product map. If an answer depends on unknown runtime, entity,
workspace, file, timeline, cost, or proof state, the head should call
`kernel.resolve`, `kernel.inspect`, or `kernel.prove` before answering.
Runtime/entity inspection is a bounded route-contract primitive: it reports
declared route identity, `runtime.inspect` capability status, lookup/proof
handles, scoped or recent run evidence, and separates entity text mentions from
actual entity matches. A node or product name appearing in a model decision is
not proof that the runtime entity was resolved.
Route-bound tools enforce the resolved contract's read/write roots; focused
tests must be declared in `server/agent_route_contracts.json`; Hermes dispatch
requires an explicit last-resort escalation reason plus capability need before
using the bridge. Observed node/product/entity misses are fixtures for the
generic contract, not prompt-affordance design inputs.

## Native Release Feed

The feed is the native evolution control point. It publishes installer/APK
artifacts plus server-downloadable runtime and operation bundles:

| Feed key | URL prefix | Purpose |
| --- | --- | --- |
| `artifacts.runtime.launcher` | `/native/releases/runtime/launcher/` | Downloaded launcher/runtime UI, diagnostics schema, runtime config, model metadata, and operation routing. |
| `artifacts.hotOps.android.hermesWakeProof` | `/native/releases/hot-ops/android/` | Hermes wake proof/debug operation with server-controlled `wakeThreshold` policy. |
| `artifacts.hotOps.diagnostics.nativeDiagnosticsClassifier` | `/native/releases/hot-ops/diagnostics/` | Non-Hermes diagnostics classifier proving the generic hot-op path. |

New product features should not start here. Use the shared PWA/runtime lane
first, with on-demand WASM/WebGPU/model artifacts cached by immutable
version/SHA metadata. Add native feed, shell, APK, or installer work only for a
documented OS/browser constraint. Wake-word background listening is a native
exception; local chat transcription must first prove or disprove a local
WASM/WebGPU path.

| Platform | Current local feed/evidence | Status | Missing proof |
| --- | --- | --- | --- |
| Windows | Local feed build `win-x64-20260614T003930Z`, shell SHA `b978a1eae03d409cf891aacd36e11f0c2521a855388df02e3faa3b35f9632195`, installer `WASM-Agent-Setup-x64-0.1.0-20260614T003930Z.exe` | implemented-unverified | Recreate `native/windows/release/VERIFY.json`, rerun feed guard, install/restart, then installed hot-shell runtime proof |
| Android | Local feed build `android-universal-20260614T141259Z`, SHA `2757cfcb3c300eb7875065bd1558e9f08eb381d14dfed4c51d913259c3bceca6` | implemented-unverified | Package signer/string proof and OAuth runtime proof |
| Downloaded runtime | `native-runtime/launcher` bundle under `/native/releases/runtime/launcher/` | implemented-unverified | Install/prove a shell containing downloaded-runtime sync and report active runtime ID/SHA |
| Windows hot ops | Hermes and diagnostics bundles under `/native/releases/hot-ops/` | implemented-unverified | Install/prove a Windows shell containing downloaded-hot-op sync; current installed proof may still be bundled |
| Web | `web-20260612T131334Z` in feed | implemented-unverified | `horc simulate web` |

## Durable Next Step

Current next action: trigger Go Native / Check Update, install/restart the
feed-published Windows hot-op shell, then run the canonical proof sequence:
`python3 tools/windows/prove-hot-shell.py`,
`python3 tools/doctor/wasm-agent-doctor.py`,
`python3 tools/voice/run-hermes-wake-proof.py --dry-run`, and
`python3 tools/voice/run-hermes-wake-proof.py --debug`.

Do not claim installed Windows shell proof from source tests, build success,
`win-unpacked`, or feed presence. The installed local bridge must pass
`prove-hot-shell.py` before Hermes wake proof/debug results are treated as
Android wake evidence.

The active Hermes wake debug question is whether spoken "Hermes" fails because
the wake threshold is not crossed, the wake event is not emitted, or command
capture/UI routing does not start.

Wake Word is the PWA control center for device-aware wake behavior. It reads the
same Android foreground-service state packet used by Frontier:
`files/native-diagnostics/voice-wake.json`,
`WasmAgentNative.getWakeWordState()`, downloaded operation
`fetch_wake_word_state`, and backend endpoint
`GET /native/android/wake-word-state` after native diagnostics upload. The
Wake Word state endpoint is an idempotent public native-diagnostics read that
returns redacted summary state only. It selects the newest uploaded diagnostics
record that contains Android `voice_wake` state, so later boot-trace uploads do
not hide the latest wake packet. It also merges newer non-null
native-control command result overlays, such as `refresh_wake_word_state`
counters and `apply_wake_word_policy` results, so agent views do not lag behind
fresh command proof. Its compact state includes the configured wake phrase,
proof-session flag, model source, ONNX/runtime readiness, service/audio-read
counters, wake/false-wake counts, transcript plan, and live policy thresholds
so agents and hot ops can classify the wake loop without fetching the full
native diagnostics blob. Train Hermes Wake remains the existing sample wizard
and is launched from inside Wake Word. On Android native, opening Wake Word
auto-requests/starts the listener when it is not already active, while the
explicit Stop control remains available.

The Wake Word modal is also the live lab. It shows a compact stage/prompt panel,
tracks the configured wake phrase, and lights the embedded `wasm-chat-avatar`
when `last_wake_at`, `wake_hit_count`, or `command_capture_active` indicates
the device heard the wake phrase. Existing open-source wake phrases are valid
first-test candidates when their model satisfies the Android raw-PCM ONNX
contract; the endpoint name `/native/android/hermes-wake-model/latest` remains
for bridge compatibility. This is UI feedback only until Android runtime proof
shows a functional packaged/installed model, wake hit, avatar shine, and bounded
transcription handoff.

The current fast-path lab flow uses WAO-backed live evidence: the modal's
Install model action reads `/native/android/hermes-wake-model/latest.json`,
installs the staged bundle through the Android bridge, applies live
`wakePhrase`/`wakeThreshold` policy, and starts the listener. The compact agent
view in the modal reads `/native/obs/agent-view` and WAO socket snapshots so
Codex can follow ordered wake/command evidence without dumping the full native
JSON packet. The staged openWakeWord first-test bundle is currently metadata
`wakePhrase: alexa`; the Android classifier filename may still be
`hey_jarvis.onnx` because that is the engine contract path, not the spoken
phrase claim. The lab default threshold is `0.92`; lower it only as a temporary
proof policy when confidence evidence shows the wake phrase is below threshold.

Stage a compatible candidate for the install queue with:

```bash
tools/voice/stage-wake-model-candidate.py \
  --model path/to/model.onnx \
  --wake-phrase "hey jarvis" \
  --model-name "open-source hey jarvis"
```

The staging script writes the current candidate and metadata under
`state/native-diagnostics/android-hermes-wake-models/latest/`; the install
request includes that phrase metadata so the Android-hosted PWA can install the
model and apply the wake phrase policy without another APK rebuild.

For the open-source openWakeWord lane, stage the full Android bundle instead of
only the wake classifier:

```bash
tools/voice/stage-openwakeword-bundle.py \
  --source-dir path/to/openwakeword-onnx-files \
  --wake-phrase "hey jarvis" \
  --model-name "openWakeWord hey jarvis"
```

The bundle must contain `melspectrogram.onnx`, `embedding_model.onnx`, and
`hey_jarvis.onnx`. When `openwakeword.zip` is staged, the install request uses
`engineContract: openwakeword_bundle` and the Android bridge installs it into
`files/voice/openwakeword`.

Android native app steering is server-core and bounded through
`/native/control/*`. The Android-hosted PWA polls `/native/control/poll` with
its native device id, executes Wake Word commands through the existing bridge
methods, and posts `/native/control/result`. Initial server-controlled commands
are `open_wake_word`, `start_voice_wake`, `stop_voice_wake`,
`refresh_wake_word_state`, and `apply_wake_word_policy`; this lets an operator
open Wake Word and start the listener without relying on local taps.
Native voice events also normalize post-Hermes command transcripts before UI
routing: Vosk `[unk]` markers and filler words are stripped, grammar aliases
such as `wake word`, `start listener`, `stop listener`, and clipped `listener`
map to canonical commands, and backend artifacts keep both raw and normalized
transcript fields.

Android native bootstrap favors first-touch responsiveness over eager admin
hydration. The Android WebView loader defaults to the lean Android runtime and
keeps the full shared PWA bundle as an explicit `android_runtime=full` /
`android_shell=full` diagnostic opt-in. On Android Home, cached config/auth is applied synchronously by a
tiny pre-module shell in `index.html`, then the PWA paints one minimal
authenticated Home surface before full event wiring. The
authoritative startup read is `GET /app/bootstrap`, which returns config,
session/user, spaces, devices, fleet, credits, readiness, and models in one
JSON payload with per-section errors. Android boot no longer starts
`/auth/session`; bootstrap owns session reconciliation, and service-worker
fallbacks must bypass `/app/bootstrap` so a production HTML response is treated
as a routing/deploy failure. The Android lite runtime is a bootstrap adapter,
not a parallel product fork: it may attach first-input-safe handlers to the
shared Home DOM and native bridge, but Home feature behavior must remain
bootstrap-backed and reusable by the shared PWA mainframe so future product
features are not implemented twice. The cached-auth shell visible mark is emitted from
the pre-module after-paint boundary when available, with `app.js` ingesting that
historical timestamp before bootstrap reconciliation; the cached path skips the
pre-shell anonymous auth-gate render. Renderer diagnostics are compacted/chunk-flushed to native,
full native `latest.json` snapshots are debounced off the synchronous bridge
path, admin bridge refresh/render work is deferred until an admin panel or
manual refresh needs it, nonessential Home module/message DOM work waits until
after the shell is visible, and the heavy WIS camera artifact runtime is loaded
with a dynamic import after bootstrap instead of as a startup dependency.
Android touch-first mode now extends the first-input quiet window, backs off
native-control polling and `/health` RTT sampling while the renderer is busy,
postpones deferred Home hydration when responsiveness is overloaded, starts
wake telemetry in a light background mode, and uses cached Wake Word state for
background budget checks instead of synchronous bridge reads. Wake Word state
reads use a short cache over a lightweight native status packet. Android
lite runtime snapshots and diagnostics include compact architecture metrics for
render counts, listener ownership, repeated fetch paths, and same-window render
bursts so duplicate work is visible before another rebuild loop. Android
native-control exposes `probe_input_latency`, `probe_canvas_pan_latency`, and
`get_android_native_ux_report` as commandable probes. Boot traces embed
`android_native_ux_report`, including first-load timing, bridge/console
diagnostic counts, long-task/frame-gap summaries, touch/pan counters, and
minimap requested/executed/skipped counts. `perfSafeMode=1` carries
`wake=off`, `bridgeDiagnostics=off`, and post-paint health probing so wake,
bridge diagnostics, and `/health` can be isolated from first paint. Real touch
proof still requires native/ADB tap or swipe evidence through the Windows
bridge or Android native-control.
Heavy ONNX/model diagnostics remain explicit proof/debug work rather than
tab-open work. This is implemented-unverified until Android native-control
reload evidence proves the cached shell, bootstrap, long-task, input-delay, and
authenticated-home budgets.

The Wake Word modal also starts a guided tuning session. During a session, the
PWA can apply live policy through downloaded operation `apply_wake_word_policy`
without rebuilding the APK. The first live knobs are `wakeThreshold`,
`wakeConfirmationFrames`, `wakeConfirmationWindowMs`, `vadRmsThreshold`,
`vadPeakThreshold`, and `tuningSessionId`; Android stores
them in app preferences, refreshes the foreground-service provider set, and
continues listening. The confirmation knobs distinguish raw model spikes from
accepted wake hits so background children, notifications, or video speech can be
recorded as hard negatives without immediately starting command capture. The
local closed-loop runner `tools/voice/run-wake-room-loop.py` can queue Windows
speech/system-sound stimuli and read Android wake deltas through
native-control/WAO state. A 2026-06-17 installed run showed threshold `0.58`
over-triggered (`wake_hit_count: 910`, `false_wake_count: 909`), so the
conservative baseline is a high threshold plus normal VAD/cooldown. A
2026-06-19 live recovery found proof mode latched on after acceptance testing;
proof mode bypasses VAD by design and made the listener appear to wake on
ordinary sound. Stop/start returned the installed service to
`proof_session_active: false`, `wake_hits: 0`, `false_wake_count: 0`; a short
ambient hold admitted only five VAD frames with max confidence `0.487` below
threshold `0.99`. Source now clears proof mode on any non-proof start/status,
but installed APK runtime proof is still required before claiming that fix is
deployed.
The same 2026-06-19 live loop proved the first normal-mode wake/transcript path:
spoken `alexa` peaked at `0.9993` against threshold `0.99`, command capture
started, and Android SpeechRecognizer returned `can you hear me`. The installed
APK still counted that nonblank freeform transcript as `unknown_command` and
false-wake evidence. Source now leaves blank transcripts as false wakes but
routes nonblank transcripts with no canonical command as active-session
freeform input; APK install/runtime proof remains required before treating that
behavior as deployed.
After the freeform patch was installed as
`android-universal-20260619T192505Z`, WAO evidence showed `can you hear me`
dispatched as active-session freeform input with `command: ""`, but lab/proof
mode also allowed duplicate wake hits from the same utterance tail. Source now
honors cooldown during proof/lab mode and adds a post-transcript cooldown before
standby so duplicate detections do not become false-wake samples. A later
`android-universal-20260619T194451Z` install proved freeform routing but also
showed ordinary room/video speech crossing the old `0.99` proof clamp with
confidence as high as `0.9997707605` and being dispatched as active-session
input. WAO live policy `wakeThreshold=0.999`, `vadRmsThreshold=0.04`, and
`vadPeakThreshold=5000` stopped new wake events during a 40 second
background-video hold at `20:01:50Z`. Source now exposes `wakeCooldownMs` as a
live policy, and the Windows proof helper no longer clamps requested threshold
to `0.99`. Install and real-device runtime proof are still required for the
cooldown patch and any two-stage verifier/model replacement.

## Claim Boundaries

- Build success is not runtime proof.
- Package verification is not feed publication.
- Release feed publication is not installed-app proof.
- Go Native / Check Update depends on `/native/releases/latest.json`; same-semver Windows updates compare `buildId`.
- Web simulation is not Android or Windows native proof.
- Android package proof is not OAuth proof.
- Roadmap claims stay in `docs/roadmap` until implemented and verified here.
- Generated reports, diagnostics, uploaded datasets, pid files, and mutable
  caches stay under `state/` or `reports/` unless a reviewed fixture is needed.

## Current Active Goal

<!-- BEGIN ACTIVE_STATE -->
<!-- This block is generated by tools/context/check-context-sync.py --fix. -->
**Active goal:** Use the installed Windows native-control bridge to tune the Android Alexa wake loop until wake, transcript, command routing, and avatar feedback are stable enough for phase-two hard-environment tests.

**Canonical proof order:**

1. `cd native/windows/src && npm run verify:win-installer -- /local/native/windows/release/WASM-Agent-Setup-x64-0.1.0-20260613T003310Z.exe`
2. `python3 tools/windows/check-windows-release-feed.py`
3. `python3 tools/windows/prove-hot-shell.py`
4. `python3 tools/doctor/wasm-agent-doctor.py`
5. `native/android/scripts/watch-wake-state.sh`
6. `python3 tools/voice/run-wake-room-loop.py --stimulus speech --phrase "alexa. open wake word" --observe-sec 24 --settle-sec 2 --state-source command --label alexa-command --volume 100 --rate -2`
7. `python3 tools/voice/run-wake-room-loop.py --stimulus speech --phrase "open settings" --observe-sec 18 --settle-sec 2 --state-source command --label alexa-negative --volume 100 --rate -2`

**Windows hot-op shell protocol:** `shellProtocolVersion: 2`, `hotOpsProtocolVersion: 1`

**Required shell capabilities:** `get_bridge_status`, `list_hot_operations`, `run_shell_self_test`, `run_hot_operation`, `canary_echo`

**Alexa wake question:** Can the installed OpenWakeWord Alexa loop fire promptly, start post-wake transcription without long linger, route `open wake word`, and trigger avatar shine at wake/capture time instead of waiting for the final transcript?

**Proof guards:**

- Do not claim installed Windows shell proof from source tests, build success, or win-unpacked.
- Build success is not update availability; package verification is not feed publication.
- Go Native / Check Update depends on the Windows release feed, and same-semver Windows updates must compare buildId.
- Do not claim Android runtime proof from APK package proof alone.
- Do not treat bridge_update_required or hot_operation_missing as Android wake failures.
- Do not use old command-specific Windows bridge handlers as the canonical wake proof path.
- Do not treat Hermes as the active baseline phrase unless a new installed model/runtime proof makes it current again.
- Do not use Codex/cloud-local ADB as Android connectivity evidence; this setup reaches the device only through the installed Windows bridge.
- When manually dropping Windows native-control command files, set the command verb in top-level `type`, not only `command`; direct file commands bypass the backend normalizer and `command`-only files reach Electron as `unsupported_command:`.
<!-- END ACTIVE_STATE -->

**Current wake loop gate, 2026-06-20T12:46Z:** Android device control/ADB for
the physical phone is through the installed Windows bridge only; cloud-local
ADB is not authoritative. The active baseline is Alexa on
`android-universal-20260620T115820Z`, not Hermes/Hey Jarvis. Timeline-aware
room proof routed `alexa. open wake word` to `open_wake_word` with transcript
`open wake word`. A later confirmation-2 trial still routed the positive
utterance but produced duplicate wake events in the same room loop; the
`open settings` negative then produced no timeline wake. Direct ADB service
start from the hot-op is rejected by Android because `HermesVoiceWakeService`
is non-exported (`Requires permission not exported from uid 10130`), so
production policy must go through the Android app/WAO `apply_wake_word_policy`
control path. That app-mediated path now proves `proof_session_active=false`,
Alexa, confirmation frames `2`, confirmation window `700ms`, and cooldown
`8000ms`; however the installed service still reports `wake_threshold=0.92`
after requesting `0.999`, so threshold propagation remains unresolved. Do not
move to music/noise phase two yet: the Android WebView had fresh
`app.responsiveness` evidence showing multi-second frame gaps, event-loop lag,
long tasks, and `/health` RTT/timeouts around 2500ms. Source now applies a
touch-first Android budget in the shared PWA layer, but this remains
installed-runtime-unverified until Android native-control reload/tap evidence
shows healthy frame gaps, event-loop lag, long tasks, and input-delay budgets.
Wake tuning is gated on restoring fluid app responsiveness and then rerunning
positive/negative proofs with the `responsiveness` section from
`tools/voice/run-wake-room-loop.py` healthy.

**Resume commands for tomorrow:**

```bash
python3 tools/voice/run-shell-v2-wake-loop.py

# Legacy/manual fallback only when isolating a sub-step:
python3 tools/windows/prove-hot-shell.py --wait-sec 120
# Direct hot-op service start should classify as service_start_rejected until an app-mediated service control route replaces it.
python3 tools/voice/run-hermes-wake-proof.py --debug --production-listener --wake-phrase alexa --wake-threshold 0.999 --wake-confirmation-frames 2 --wake-confirmation-window-ms 700 --wake-cooldown-ms 8000 --wait-ms 5000
python3 tools/voice/run-wake-room-loop.py --android-device-id android-android-universal-20260620t115820z-35c236de2c2b3c67b1147c41 --stimulus speech --phrase "alexa. open wake word" --observe-sec 28 --settle-sec 2 --state-source endpoint --label alexa-responsiveness-gated-positive --volume 100 --rate -2
python3 tools/voice/run-wake-room-loop.py --android-device-id android-android-universal-20260620t115820z-35c236de2c2b3c67b1147c41 --stimulus speech --phrase "open settings" --observe-sec 18 --settle-sec 2 --state-source endpoint --label alexa-responsiveness-gated-negative-open-settings --volume 100 --rate -2
```

For the shell-v2 production loop, the canonical command is
`python3 tools/voice/run-shell-v2-wake-loop.py`. It requires Android build
`android-universal-20260622T193436Z` or newer, proves the shell-v2 launch path,
starts wake through `WasmAgentNative.enableVoiceWake`, applies
`apply_wake_word_policy`, and uses Windows synthesized speech for the positive
room trial. Do not claim shipped wake-word evidence from the legacy Hermes
proof command, old `MainActivity`, direct ADB service start, or source-only
checks.
