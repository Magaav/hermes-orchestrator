# Context Route Map

| Area | Owns | Read First | Status | Verify | Forbidden | Next |
| --- | --- | --- | --- | --- | --- | --- |
| `/local` | Repo-wide safety, routing, lifecycle, docs-sync rules | `AGENTS.md`; `README.md`; `docs/context/README.md` | verified | `rg -n "Production backend|Context Routing|Claim Status" README.md AGENTS.md docs/context`; `python3 tools/context/check-harness-promises.py` | Claiming runtime proof from docs only | None |
| `docs/context` | Context protocol, route map, claim registry, verification, review loop, self-improving harness | `docs/context/README.md`; `docs/context/HARNESS.md`; this file | verified | Smell scan in `VERIFY.md`; `python3 tools/context/check-harness-promises.py`; fresh-agent test in `REVIEW.md` | Narrative status dumps; unproved `verified` claims; repeated inference left unharvested | Rerun smell scan, harness registry validation, and fresh-agent test after context or behavior edits |
| `docs` | Versioned docs root and current/future split | `docs/README.md`; then nearest child docs | verified | Docs consistency pass | Roadmap text presented as current runtime | None |
| `docs/roadmap` | Multi-step plans, proposals, risks, durable track next actions | `docs/roadmap/AGENTS.md`; `docs/roadmap/README.md` | verified | Docs consistency pass | Roadmap overriding runtime/product docs | None unless a long track starts |
| `plugins` | Plugin package root | `plugins/README.md`; nearest plugin docs | verified | Read owning plugin docs | Editing generated plugin state as source | None |
| `plugins/wasm-agent` | Active PWA, backend, account state, native bridge, release feed, Frontier, product UI | `plugins/wasm-agent/AGENTS.md`; `plugins/wasm-agent/README.md`; `DESIGN.md` for frontend | implemented-unverified | `horc simulate web`; focused tests under `plugins/wasm-agent/tests`; `node plugins/wasm-agent/tests/native_release_feed.test.js`; `python3 tools/windows/check-windows-release-feed.py`; `python3 tools/windows/prove-hot-shell.py`; `python3 tools/doctor/wasm-agent-doctor.py`; `native/android/scripts/watch-wake-state.sh`; `python3 tools/voice/run-wake-room-loop.py --stimulus speech --phrase "alexa. open wake word" --observe-sec 24 --settle-sec 2 --state-source command --label alexa-command --volume 100 --rate -2` | Production claims using local/dev origins; unauthenticated Frontier/control routes; terminal ADB from this workspace for wake dataset export; source/feed tests claimed as installed runtime proof | Before asking the user what is on screen or proposing rebuilds, use available runtime introspection/control, capability reports, diagnostics, and live policy knobs; end replies with one concrete next-step phase |
| `plugins/wasm-agent/server` | Python backend, auth, bridge routes, Frontier APIs | `plugins/wasm-agent/AGENTS.md`; `plugins/wasm-agent/server/README.md` | implemented-unverified | Focused Python tests under `plugins/wasm-agent/tests` | Broad account access, arbitrary host command execution | None |
| `plugins/wasm-agent/public` | PWA shell, modules, HMR client, static assets | `plugins/wasm-agent/AGENTS.md`; `plugins/wasm-agent/README.md`; `plugins/wasm-agent/DESIGN.md` | implemented-unverified | `horc simulate web`; focused JS smoke tests | In-app text explaining features; production localhost claims | Preserve UX-budgeted native control: compact polling, idle heavy work, capped runtime snapshots, capability acks |
| `native` | Shared native shell policy across Windows, Android, macOS, Linux | `native/AGENTS.md`; `native/NATIVE_SHELL_CONTRACT.md`; `native/NATIVE_EVOLUTION_CONTRACT.md` | implemented-unverified | Platform-specific package/runtime proof; `cd native/windows/src && npm run test:windows-hot-ops` | Localhost production defaults; embedded secrets; downloaded runtime claims without active bundle proof | None |
| `native/windows` | Windows Electron shell, NSIS installer, app.asar, installed-app verification | `native/AGENTS.md`; `native/windows/AGENTS.md`; `native/windows/README.md` | implemented-unverified | `cd native/windows/src && npm run verify:win-installer -- <installer>`; `python3 tools/windows/check-windows-release-feed.py`; installed-app PowerShell proof; `python3 tools/windows/prove-hot-shell.py` | Calling build success, source tests, `win-unpacked`, or feed presence fixed | Trigger Go Native / Check Update, install/restart the feed-published shell, then run `python3 tools/windows/prove-hot-shell.py` against the installed local bridge before doctor or Hermes wake proof |
| `native/android` | Android APK, WebView/native bridge, foreground service, voice wake, sideload/update metadata | `native/AGENTS.md`; `native/android/AGENTS.md`; `native/android/README.md` | implemented-unverified | `python3 tools/android/check-android-ux-rebuild-gate.py`; `apksigner verify --verbose <apk>`; forbidden-origin scan; `horc simulate android`; `python3 tools/android/prove-android-native-ux-release-loop.py`; `native/android/scripts/watch-wake-state.sh`; Alexa positive/negative room-loop proof through the Windows bridge | Treating package proof as OAuth/runtime proof; using Codex/cloud-local ADB as device connectivity evidence; terminal ADB from this workspace for wake dataset export | Install once, then prefer live control and the Windows bridge ADB lane: `get_runtime_snapshot`, `/native/android/wake-word-state`, `open_wake_word`, `start_voice_wake`, and `apply_wake_word_policy`; for rebuild-heavy UX work, run the rebuild gate first and the deterministic UX release loop instead of repeating manual build/reinstall/proof commands |
| `scripts` | Script root and public/private split | `scripts/README.md` | verified | Read public/private child docs | Secrets in public scripts | None |
| `scripts/public` | Git-tracked host automation and `horc` helpers | `scripts/public/AGENTS.md`; `scripts/public/README.md`; `docs/commands/horc.md` | implemented-unverified | `horc status`; `horc build doctor`; focused script help/doctor | Mutable deployment state or secrets | None |
| `hermes-agent` | Upstream Hermes Agent checkout | `hermes-agent/AGENTS.md` | unknown | Inspect upstream docs/tests before editing | Local fork drift without extension-seam review | Prefer plugins/hooks/skills before core edits |
| `agents` | Runtime node worktrees and generated node state | Root README; node-local docs when intentionally editing | unknown | Node-specific smoke only when task targets node state | Treating generated/runtime state as source docs | Avoid unless task explicitly targets runtime node state |

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
