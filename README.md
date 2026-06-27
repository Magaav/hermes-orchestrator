# Hermes Orchestrator Context Control Map

This repository is the host-level control plane for fleets of Hermes Agent
nodes. The active product surface is `plugins/wasm-agent`: a PWA/backend/native
bridge lane for WASM Agent Native and Space OS evolution.

## Identity

| Field | Value |
| --- | --- |
| Project | Hermes Orchestrator |
| Primary role | Fleet lifecycle, host automation, plugin propagation, observability, and runtime guardrails |
| Active product boundary | `plugins/wasm-agent` |
| Native shells | `native/windows`, `native/android`, plus shared native contract in `native/` |
| Context engine | `AGENTS.md` plus `docs/context/` plus nearest child `AGENTS.md`/`README.md` |

## Production Guards

| Guard | Binding rule |
| --- | --- |
| Production backend | `https://wa.colmeio.com` |
| Production Windows native app URL | `https://wa.colmeio.com/home?native=electron` |
| Dev origins | `127.0.0.1:8877`, `localhost`, `0.0.0.0`, emulator origins, and local PWA ports are dev-only and forbidden in production claims. |
| Windows proof | Never claim the installer or login persistence is fixed from source tests, build success, or `win-unpacked`. |
| Required Windows package proof | Final extracted NSIS installer and installed `app.asar` verification. |
| Required Windows login proof | Installed app, Google login, full close/reopen, `https://wa.colmeio.com/home?native=electron`, `authCookie.hasWaUid: true`, durable cookie expiration metadata, and authenticated `/auth/session`. |
| Android proof | APK package proof is not OAuth/runtime proof; `horc simulate android` or copied `--local-report` evidence must name the behavior proven. |
| Roadmap truth | Future/proposal docs never override runtime docs, code, or proof artifacts. |
| Dirty worktree | Do not remove unrelated user work or dirty changes. |

## Context Routing

| Need | Read first |
| --- | --- |
| Global rules and area map | `AGENTS.md`, this file, `docs/context/README.md`, `docs/context/MAP.md` |
| Claim status and proof | `docs/context/CLAIMS.md`, `docs/context/VERIFY.md` |
| Context review loop | `docs/context/REVIEW.md` |
| Active PWA/backend/native bridge | `plugins/wasm-agent/AGENTS.md`, then `plugins/wasm-agent/README.md` |
| Windows Electron/NSIS work | `native/AGENTS.md`, `native/NATIVE_SHELL_CONTRACT.md`, `native/windows/AGENTS.md`, `native/windows/README.md` |
| Android APK/WebView/voice work | `native/AGENTS.md`, `native/NATIVE_SHELL_CONTRACT.md`, `native/android/AGENTS.md`, `native/android/README.md` |
| Long-running plans | `docs/roadmap/AGENTS.md`, `docs/roadmap/README.md`, relevant track README |
| Public host automation | `scripts/public/AGENTS.md`, `scripts/public/README.md`, `docs/commands/horc.md` |

Read the nearest child `AGENTS.md` before editing a durable boundary. Closest
child context owns local details; root context owns production safety, claim
status rules, verification standards, and routing.

## Area Map

Canonical route table: `docs/context/MAP.md`.

| Area | Owns | Read first | Status | Verify |
| --- | --- | --- | --- | --- |
| `/local` | Repo-wide safety, routing, lifecycle, docs-sync rules | `AGENTS.md`, `README.md`, `docs/context/README.md` | verified | `rg -n "Production backend|Context Routing|Claim Status" README.md AGENTS.md docs/context` |
| `docs/context` | Context protocol, route map, claims, verification, review loop, self-improving harness | `docs/context/README.md`, `docs/context/HARNESS.md` | verified | docs smell scan and `python3 tools/context/check-harness-promises.py` |
| `plugins/wasm-agent` | PWA, backend, account state, native bridge, release feed, Frontier | `plugins/wasm-agent/AGENTS.md` | implemented-unverified | `horc simulate web`; focused tests under `plugins/wasm-agent/tests` |
| `native` | Shared native shell policy across platforms | `native/AGENTS.md`, `native/NATIVE_SHELL_CONTRACT.md` | implemented-unverified | platform-specific package/runtime proof |
| `native/windows` | Electron shell, NSIS installer, installed-app verification | `native/windows/AGENTS.md` | implemented-unverified | `cd native/windows/src && npm run verify:win-installer -- <installer>` plus installed-app PowerShell proof |
| `native/android` | APK shell, WebView/native bridge, voice wake, sideload/update metadata | `native/android/AGENTS.md` | implemented-unverified | `apksigner verify --verbose <apk>` plus `horc simulate android` |
| `docs/roadmap` | Future/proposal/staged work | `docs/roadmap/AGENTS.md` | verified | docs consistency pass |
| `scripts/public` | Git-tracked host automation and `horc` helpers | `scripts/public/AGENTS.md` | implemented-unverified | focused `horc` smoke command |
| `plugins` | Plugin package root | `plugins/README.md` | verified | read owning plugin docs |
| `scripts` | Public/private script split | `scripts/README.md` | verified | read `scripts/public` or `scripts/private` docs |
| `hermes-agent` | Upstream Hermes Agent checkout | `hermes-agent/AGENTS.md` | unknown | prefer extension layers before core edits |

Use the claim statuses defined in `docs/context/README.md`: `verified`,
`implemented-unverified`, `proposal`, `future`, `stale`, and `unknown`.

## Claim Status Summary

Detailed registry: `docs/context/CLAIMS.md`.

| Claim | Status | Proof or missing proof |
| --- | --- | --- |
| Configured production native target is cloud-only at `https://wa.colmeio.com` | verified | Root guard, native defaults, Android sidecar, release feed; config evidence only |
| Self-improving harness contract exists for repeated inference | verified | `docs/context/HARNESS.md`; `docs/context/HARNESS_PROMISES.json`; `python3 tools/context/check-harness-promises.py` |
| Windows release feed points at `win-x64-20260613T003310Z` | verified feed | `plugins/wasm-agent/public/native/releases/latest.json`; `https://wa.colmeio.com/native/releases/latest.json`; `reports/windows/latest/windows-release-feed-check.json`; package/runtime proof still required |
| Windows login persistence fix status | implemented-unverified | Must not be claimed fixed until installed-app proof passes |
| Android build `android-universal-20260612T131155Z` exists | implemented-unverified | `native/android/release/release-manifest.json` and SHA; `apksigner` unavailable in this session |
| Latest Android simulation report proves voice wake fixture behavior | verified | `reports/sim/android/latest/summary.md`; does not prove current APK OAuth |
| Roadmap current-software claims | unknown | Roadmap docs are proposal/future/status unless reconciled with code and product docs |

## Verification Matrix

| Behavior | Command or proof |
| --- | --- |
| Context sync, harness registry, and smell scan | `python3 tools/context/check-context-sync.py`; `python3 tools/context/check-harness-promises.py`; see `docs/context/VERIFY.md` |
| Fresh-agent structured test | See `docs/context/REVIEW.md` |
| PWA/browser behavior | `horc simulate web` |
| wasm-agent focused checks | `/local/plugins/wasm-agent/scripts/doctor.sh` or focused tests under `plugins/wasm-agent/tests` |
| Windows final installer extraction | `cd native/windows/src && npm run verify:win-installer -- <final-nsis-installer>` |
| Windows release feed consistency | `python3 tools/windows/check-windows-release-feed.py` |
| Native evolution source/feed checks | `node plugins/wasm-agent/tests/native_release_feed.test.js`; `cd native/windows/src && npm run test:windows-hot-ops`; `python3 tools/context/check-context-sync.py` |
| Windows installed login persistence | `native\windows\scripts\verify-installed-app.ps1 -Launch -InteractiveLogin` on Windows |
| Windows hot-op shell preflight | `python3 tools/windows/prove-hot-shell.py`; then `python3 tools/doctor/wasm-agent-doctor.py`; then Hermes dry-run/debug proof. |
| Android package | `apksigner verify --verbose native/android/release/WASM-Agent-arm64.apk` plus forbidden-origin scan |
| Android runtime | `horc simulate android` or `horc simulate android --local-report <path>` |
| Public script smoke | `horc status`, `horc build doctor`, or the script's focused doctor/help mode |

Build success is not runtime proof. Missing proof demotes the claim.

## Architecture Performance Law

Before code changes, agents must reflect on whether the same correct observable
result can be reached with fewer phases, listeners, renders, reflows,
recalculations, bridge calls, polling loops, rebuilds, or runtime cycles. The
shortest correct path is the default architecture.

If that reflection finds duplicated state, avoidable lifecycle work, redundant
event listeners, layout thrash, unnecessary abstraction, bloated control flow,
or delayed feedback, simplify it before editing or include the simplification
in the edit. Extra work must be justified by correctness, safety,
compatibility, or observability that shortens future proof/debug loops.

The product target is a fluid, native, game-like app feel across devices. Code
that works but adds avoidable latency, jitter, duplicate rendering, late UI
feedback, or unnecessary runtime work is incomplete until the waste is removed
or explicitly justified.

## Omni-Device Feature Law

Default new product features to the shared PWA/runtime layer first. Prefer
browser APIs, WASM, WebGPU/WebNN where available, downloadable model/runtime
artifacts, service-worker/browser cache, IndexedDB, and static metadata with
version and SHA validation before adding native shell code.

Native shell branching is an exception, not the default. It is allowed only when
an OS/browser constraint makes the feature impossible or unreliable in the PWA
lane, such as background wake-word listeners, OS services, native permissions,
package identity, signing, foreground services, accessibility, media projection,
or hardware/OS primitives that the browser cannot provide. When native is used,
keep it as a minimal primitive and keep product behavior, model selection,
diagnostics, and UI policy in the shared runtime whenever possible.

For AI/audio/model features, the first production design must ask whether an
on-demand WASM/WebGPU path can run locally across web, Android WebView, Windows
Electron, and future shells. Load it only after user intent, cache by immutable
version/SHA, and invalidate through metadata, not a native rebuild.

Hermes-Relay v0.3.0 is the reference release pattern: version-tagged artifacts,
SHA verification, and channel/flavor splits only where platform policy or
capability boundaries require them. Do not use flavor/native splits for features
that can ship as shared web/runtime/model artifacts.

## LLM-Native Architecture Law

Every durable feature should be shaped so an LLM can operate it well: inspect
current state, understand available capabilities, choose bounded actions, and
verify proof with the smallest correct context. The repo should be LLM-native
by architecture, not merely LLM-connected at the chat surface.

For state, telemetry, observations, logs, tool results, snapshots, transcripts,
protocol payloads, diagnostics, release evidence, and control surfaces, the
default contract is a tiny always-on summary plus on-demand lookup tools.
Human-readable expanded views may exist, and machine APIs should remain
structured, but prompt input must be optimized for LLM token economics and
reasoning quality.

Prefer short, stable, repetitive text codes and shared dictionaries that models
can parse cheaply, such as `s=home|v=360x710|n=orchestrator`, over verbose
field names, nested prompt JSON, raw logs, screenshots, binary blobs, base64,
protobuf, or gRPC payloads inside prompts. Expose explicit capability reports,
action schemas, status fields, counters, error classes, and proof artifacts so
agents do not need to infer state from human-only output.

Before adding a new implementation, measure or estimate baseline context
pressure, state the minimum information required for the next decision, and ask
whether detail can be fetched only when needed. Production-grade observability
is LLM-first: compact, redacted, provider-aware, replayable, and precise enough
to let the model decide which bounded tool or proof to call next.

## Self-Improving Harness

Use `docs/context/HARNESS.md` after intent/context routing and before slow
investigation, rebuilds, runtime control, or source edits. Repeated uncertainty
should prefer a deterministic promise from
`docs/context/HARNESS_PROMISES.json`; novel uncertainty can stay in the
exploration lane until it repeats.

The second repeated manual inference needs a promise candidate or a named reason
it cannot be deterministic yet. The third repeat must be promoted or blocked on
a missing primitive, access, or observability field. Validate the promise
registry with `python3 tools/context/check-harness-promises.py`.

## Verified Loop-Aware Engineering

For meaningful native, bridge, wake-word, hot-op, runtime-control, release, or
rebuild-heavy work, use Rule-of-Three Prime Checkpoints:

| Role | Owns |
| --- | --- |
| Builder | Patch, shortcut, hot-op, HMR path, diagnostics, or validation approach. |
| Watcher | Independent truth checks from tests, logs, runtime state, diagnostics, counters, app/device state, or reproducible proof. |
| Gatekeeper | Authorization: accept shortcut, require rebuild, rollback, block, or escalate. |

The same Codex/Frontier instance may perform all three roles, but the report
must keep Builder intent, Watcher evidence, and Gatekeeper decision separate.
Prefer three evidence classes for rebuild-heavy/native/runtime work: static
evidence, runtime evidence, and behavioral evidence.

Prime checkpoints must be atomic, independent, falsifiable, observable, and
non-redundant. Examples: service running, permission granted, model SHA matches,
hot-op returned success, recent wake event visible, false-wake counter stable,
or simulator smoke passed. Do not treat "looks good" or build success as proof.

## Durable Next Actions

Canonical current next actions live in `docs/context/MAP.md` and the nearest
owning child README. Update both together when a next action changes.

| Area | Canonical source |
| --- | --- |
| `plugins/wasm-agent` | `docs/context/MAP.md`; `plugins/wasm-agent/README.md` |
| `native/windows` | `docs/context/MAP.md`; `native/windows/README.md` |
| `native/android` | `docs/context/MAP.md`; `native/android/README.md` |
| `docs/context` | `docs/context/MAP.md`; `docs/context/REVIEW.md` |

## Docs Sync Contract

| Trigger | Required docs action |
| --- | --- |
| Behavior, workflow, API, command, artifact, ownership, or durable next action changes | Update the closest owning `README.md` or `AGENTS.md`. |
| Parent route, global guard, or claim status changes | Update this file and `docs/context/*`. |
| Runtime evidence disproves or fails to prove a claim | Demote the claim in `docs/context/CLAIMS.md`; do not leave optimistic wording elsewhere. |
| Roadmap item ships | Move current behavior to product/runtime docs and shrink or retire roadmap text. |
| Generated/runtime state changes | Do not document it as source unless the task explicitly concerns that artifact. |

## Windows Hot-Op Shell

The Windows native app is a minimal bridge shell for live Android wake proof
iteration. It exposes stable primitives and manifest-scanned hot ops instead of
embedding workflow logic in the installed shell. With a verified installer
already present, run `python3 tools/windows/check-windows-release-feed.py`,
install/restart through Go Native / Check Update, and run
`python3 tools/windows/prove-hot-shell.py`,
`python3 tools/doctor/wasm-agent-doctor.py`,
`python3 tools/voice/run-hermes-wake-proof.py --dry-run`, and
`python3 tools/voice/run-hermes-wake-proof.py --debug`.

Do not claim installed Windows shell proof until the feed-published installer is
installed and the local bridge passes `prove-hot-shell.py`.

Do not treat `bridge_update_required`, `hot_operation_missing`,
`hot_operation_sha_mismatch`, `hot_operation_capability_denied`, or
`hot_operations_disabled` as runtime proof failures for Android itself; they are
Windows bridge/hot-op loading classifications to resolve before wake proof.

## Native Evolution Layer

The current implementation treats Windows and Android as stable native
capability kernels. The server release feed can publish downloaded runtime
bundles at `artifacts.runtime.launcher` and trusted operation bundles under
`artifacts.hotOps.*`; installed shells with the new kernel report active
runtime/hot-op bundle IDs and SHAs, sync status, and stale reason. Source/feed
tests can verify the contract shape, but installed runtime proof still requires
the Windows/Android commands above.

This layer can change launcher/runtime UI, diagnostics schemas/classifiers,
proof/debug scripts, config, model metadata, operation routing, and wake-word
threshold policy without a native rebuild when required capabilities already
exist. Native rebuilds are still required for new OS permissions, native
libraries, manifest/service declarations, installer/APK behavior, package
identity, signing, or a new hardware/OS primitive.

## Current Android Wake Loop

The current shortest production-candidate wake phrase is `alexa`, using the
installed OpenWakeWord bundle and Windows native-control bridge as the control
plane. `hey jarvis` did not fire with the installed model, and Hermes is a later
personalized/custom-word path rather than the active baseline target.

Physical device ADB is Windows-bridge-only in this setup. The Codex/cloud
workspace may have an `adb` binary, but `adb devices` from here is expected to
show no Android device and is not evidence that the USB Android device is gone.
Use Windows bridge hot ops/native-control for ADB-backed Android checks,
stimulus, app launch/recovery, reinstall, diagnostics, and wake proof.

Current live policy evidence on 2026-06-20 used `wakePhrase=alexa`,
`wakeThreshold=0.985`, `wakeConfirmationFrames=1`,
`wakeConfirmationWindowMs=700`, and `wakeCooldownMs=8000`. A real-device proof
on Xiaomi Mi 9 SE through the Windows bridge heard `alexa. open wake word`,
transcribed `open wake word`, routed `open_wake_word`, and dispatched HTTP 200
to the active session while `open settings` did not increment wake or false-wake
counters. Baseline is not accepted yet: the avatar shine is still too late
because the PWA currently reacts after post-transcript voice events, the faster
balanced ASR plan degraded to `word` after about 10.5s, and installed APK event
metadata still reports `wake_word: hermes` until the native metadata patch is
rebuilt/reinstalled. Hard-environment tests with music/noise are phase two after
the Alexa wake, transcript, and immediate avatar feedback loop is stable.

## Copilotability Fast Path

Use live app introspection/control before guessing. When a runtime exposes state
snapshots, capability reports, visible-action summaries, diagnostics, or policy
knobs, prefer those channels before asking the user to describe the screen or
before proposing rebuild/reinstall loops. Heavy access such as screenshots, log
bundles, or full diagnostics must be explicit, idle-gated, bounded, redacted,
and allowed to skip during active user interaction.

Observability and controlled accessibility are core engineering infrastructure:
they let agents understand live app state, validate hypotheses, reduce rebuild
dependency, and shorten slow loops without bypassing safety gates.

Every substantive reply should end with a concrete next-step phase: name the
next command/action, say whether it is live introspection/control, static check,
or runtime/package proof, and only suggest rebuilds when a missing primitive,
permission, manifest/service change, native library, signing, or package
identity requires it.

## Human Links

| Topic | Link |
| --- | --- |
| Command reference | `docs/commands/horc.md` |
| Feature docs | `docs/features/README.md` |
| Roadmap tracks | `docs/roadmap/README.md` |
| Plugin root | `plugins/README.md` |
| Script root | `scripts/README.md` |

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
