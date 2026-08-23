# wasm-agent Windows Native

Preferred Android OAuth proof path: Open wasm-agent Windows app -> Diagnostics -> Verify Android OAuth. CLI fallback: tools\windows\verify-android-oauth.ps1.

Shared shell contract: `../NATIVE_SHELL_CONTRACT.md`.

`native/windows` owns the Windows Electron shell, NSIS installer, packaged
`app.asar`, Windows diagnostics bridge, and installed-app verification lane for
WASM Agent Native.

## Contract

| Rule | Value |
| --- | --- |
| Production backend | `https://wa.colmeio.com` |
| Production app URL | `https://wa.colmeio.com/home?native=electron` |
| Production local origins | Forbidden: `127.0.0.1:8877`, `localhost`, `0.0.0.0`, source-tree assets, dev fallbacks |
| Installer secrets | No account secrets or pre-minted device tokens |
| Installer payload | Native kernel/launcher only; cloud PWA, models, and Android APKs are fetched on demand |
| Proof floor | Final extracted NSIS installer and installed `app.asar` verification |
| Runtime proof floor | Real installed app with Google login, close/reopen, route, cookie, expiration metadata, and `/auth/session` |

Read first: `/local/AGENTS.md`, `/local/README.md`, `docs/context/MAP.md`,
`native/AGENTS.md`, `native/NATIVE_SHELL_CONTRACT.md`, this directory's
`AGENTS.md`, then this file.

## Current Evidence

| Evidence | Status | Notes |
| --- | --- | --- |
| Local verified installer `WASM-Agent-Setup-x64-0.1.0-20260820T195241Z.exe` | verified | Final NSIS extraction passed. Installer SHA `08b46bf491a25f7652a6765e2e7f17add00998cb488bccf8519880ba75ddbed1`; `app.asar` SHA `9bda2adfbd2fbbcfc71be760ff0553e49884f71594840da01026127e82483dec`. |
| `native/windows/release/VERIFY.json` | verified | Build `win-x64-20260820T195241Z`; extracted receipt/pointer/full-power and installed-integrity modules, production defaults, and Google client ID are verified. Installed full-power runtime evidence is recorded in `reports/context/latest/master-frontier-full-power-client-runtime.json`. |
| Windows package size audit | implemented-unverified | Re-run after the final NSIS build; `win-unpacked` is not release proof. |
| Win11 staged update | implemented-unverified | Trigger Go Native / Check Update against the feed, install/restart, then prove the installed shell. |
| Installed-app login persistence | implemented-unverified | Required Windows host proof absent. |
| Android OAuth through Windows diagnostics | implemented-unverified | Requires installed Windows app plus local runner report PASS/PASSED. |

## Build

```bash
horc build
```

Direct Windows release lane:

```bash
cd native/windows/src
npm run release:win:x64:prod
```

Linux x86_64 with Wine/NSIS is a supported CI cross-build path. Linux ARM64
prefers Docker `linux/amd64` Wine builder; direct ARM64 Wine/NSIS is
experimental and still requires Windows smoke proof.

`horc build all` publishes generated release feed files under
`/local/plugins/wasm-agent/public/native/releases/`. Build success is not
update availability, package verification is not feed publication, and feed
publication is not installed runtime verification.

The Windows build verifies the final versioned NSIS installer after promotion.
It does not separately extract/verify the intermediate unversioned copy, because
the promoted installer bytes are copied from that artifact and the final
installer is the package that matters for release proof.

## Verification

Final NSIS/app.asar proof:

```bash
cd native/windows/src
npm run verify:win-installer -- /local/native/windows/release/WASM-Agent-Setup-x64-0.1.0-20260613T003310Z.exe
```

Expected proof artifact:

```text
native/windows/release/VERIFY.json
```

After package verification, prove the Windows release feed points to the same
verified installer before using Go Native / Check Update:

```bash
python3 tools/windows/check-windows-release-feed.py
```

The guard compares `VERIFY.json`, the feed buildId, SHA-256, installer
filename/URL, and local published installer bytes. Same app version with a
newer `buildId` must be update available; an older or equal `buildId` must not
hide a newer verified installer.

Installed Windows proof:

```powershell
native\windows\scripts\verify-installed-app.ps1 -Launch -InteractiveLogin
```

Required installed evidence:

| Check | Required |
| --- | --- |
| Google login | Passes in installed app |
| Close/reopen | Full app restart |
| Route | `https://wa.colmeio.com/home?native=electron` |
| Auth cookie | `authCookie.hasWaUid: true` |
| Cookie metadata | Durable expiration metadata present |
| Session | Authenticated `/auth/session` after reopen |

Do not claim fixed from source tests, build success, `win-unpacked`, or feed
presence.

## Native web surfaces

The installed Electron shell exposes `hermes.wasm_agent.native_web_surfaces.v1`
through `preload.js`. The owning implementation is `src/main/web-surfaces/manager.js`;
`main.js` contains bootstrap and disposal delegation only. The shared Browser
widget positions a real Chromium `WebContentsView` over its viewport and uses a
persistent, surface-isolated session. Remote content is sandboxed, receives no
Node.js API, accepts HTTPS navigation only, and has downloads and permissions
denied until a separate explicit grant contract is implemented.
Each surface strips Electron/product markers from its persistent session user
agent before constructing the `WebContentsView`, so the renderer and its first
request share one browser-compatible Chromium identity. Browser Reload bypasses
the isolated session cache so a compatibility response saved by an older shell
cannot survive an update.

The source manager also declares `web_surface.input_receipt`. Receipt capture is
disabled by default. The Browser Agent button explicitly invokes native
operation `input-receipt` with `{enabled: true|false}`; disabling the mode
clears its pending gesture, receipt, and expiry timer.

While enabled, Electron's `before-mouse-event` boundary accepts only a matching
left-button down/up gesture inside the current surface viewport and on the same
main document. Right/middle, incomplete, navigated, blurred, or out-of-bounds
input creates no receipt. The result is one redacted
`hermes.wasm_agent.native_web_surface_input_receipt.v1` object with action
`pointer.primary_gesture` and outcome `observed_pre_dispatch`. It proves only
that native Chromium observed the primary gesture before page dispatch; it does
not prove a click, DOM target, page handler, or page action succeeded.

The manager retains at most `inputReceiptMaxPerSurface: 1`. Every accepted
gesture replaces the prior receipt and arms a real, overwrite-safe expiry timer
for `inputReceiptTtlMs: 120000`; an older timer cannot clear a newer receipt.
Main-frame navigation or renderer loss clears the current receipt, and blur
clears an unfinished gesture.

Normal surface status omits receipt state. An on-demand request with
`includeInputReceipt: true` returns `inputReceiptEnabled` plus `inputReceipt` as
either `null` or the one fresh receipt. The bounded object contains receipt
identity/time, action/outcome, left button, current-document state, age,
redaction state, and validated `x`/`y`/viewport values. It contains no selector,
DOM target, page content, form value, raw Electron event, or other page-derived
data. Capture and disclosure use no page JavaScript, polling, renderer push, or
persistence.

Focused source proof:

```bash
npm --prefix native/windows/src run test:web-surfaces
node --experimental-vm-modules plugins/wasm-agent/public/modules/client-observability.test.mjs
node plugins/wasm-agent/tests/browser_widget_native_contract.test.mjs
```

These tests establish only the manager, explicit Browser Agent control,
redacted on-demand projection, and Browser wiring source contracts. They do not
establish packaged or installed runtime behavior. A final NSIS extraction and
installed-app enable/gesture/receipt proof are still required;
navigation/login/reopen remains a separate installed-app gate.

## Full-power Master:frontier authority

The installed Electron client deliberately exposes two unrestricted semantic
operations to authenticated Master:frontier control:

- `browser_javascript_execute_unrestricted` evaluates arbitrary JavaScript in
  the selected Browser surface's page main world through the existing native
  manager. It can inspect and change that page as the embedded browser session.
- `windows_shell_execute_unrestricted` runs arbitrary PowerShell or CMD under
  the Windows identity and integrity level already held by the installed app.
  It inherits that user's filesystem, process, network, and credential access;
  it does not silently elevate to Administrator or SYSTEM.

There is intentionally no command or JavaScript allowlist. Authentication,
exact live-client capability selection, command correlation, audit records,
payload/output ceilings, and execution timeouts remain in force because they
bound transport and make execution inspectable; they do not limit command
semantics. Browser authority is confined to the selected native page context.
Windows shell authority reaches everything available to the installed app's
Windows user token. These capabilities are not advertised by plain PWA or
Android clients.

Build `win-x64-20260820T195241Z` passed the final extracted NSIS verifier with
exact source-matching executor, manager, and manifest bytes. Installed runtime
then returned command-correlated harmless receipts from arbitrary JavaScript in
the WhatsApp page main world and PowerShell as Windows user `Victor`; see
`reports/context/latest/master-frontier-full-power-client-runtime.json`.

## Bundled Windows supervisor

The installer now bundles `resources/wasm-agent-launcher.exe` as the single
Start-menu/Desktop entry point. It is part of the same WASM Agent installation
but runs outside Electron so it can supervise `WASM Agent.exe` when Electron is
blocked, duplicated, restarting, or being replaced.

The supervisor exposes the compact
`hermes.wasm_agent.windows_supervisor.v1` contract through
`%LOCALAPPDATA%/WASM Agent Native/supervisor/`. Its initial bounded capability
set is `capabilities.describe`, `process.start`, `process.stop`,
`process.restart`, `process.status`, and `update.activate`. Update activation
accepts only `.exe` files inside the dedicated staged-update directory and
requires an exact SHA-256 match before stopping Electron and launching the
installer. The installer registers the supervisor under the current user's
Windows `Run` key. Updates copy a bounded runner outside the installation,
revalidate the staged SHA-256, exit the installed supervisor so its files are
replaceable, and invoke NSIS silently with an explicit `/currentuser` or
`/allusers` mode derived from the install root. The runner relaunches only after
the installed build metadata matches the expected build. Installer failure or
build mismatch records one bounded result and stays stopped instead of reopening
the old build into another elevation loop. Electron queues one check immediately on startup and
checks every six hours afterward through `main/automatic-updates.js`.
An all-users install also removes stale current-user Desktop and Start-menu
shortcuts before recreating the launcher in the all-users scope, preventing an
older parallel install root from becoming authoritative merely because its
shortcut was opened.
The supervisor persists `update-timeline.json` across the Electron-offline
handoff. `observability_status` exposes its bounded phase, command ID,
install mode, expected/observed build, installer exit/failure, and timestamps on
demand, so UAC wait, NSIS failure, wrong-root install, and relaunch failure are
distinguishable without continuous tracing.
Installer downloads stream into a unique temporary file and are atomically
renamed into the staged-update path only after the file handle closes; size and
SHA-256 validation then run against that complete staged file.
`WASM_AGENT_DISABLE_AUTOMATIC_UPDATES=1` is the recovery opt-out. Electron delegates through `src/main/supervisor-client.js`; direct
installer launch remains only as a compatibility fallback for apps started
outside the supervisor.

The supervisor is a stable native primitive, not a claim that every Windows
capability is downloadable today. Product workflows should continue moving to
signed runtime/hot-op bundles. Adding a genuinely new privileged OS primitive
or repairing the supervisor itself still requires an installer update.

Focused source and cross-compile proof:

```bash
cd native/windows/src
npm run test:windows-supervisor
```

Package verification rejects a final NSIS artifact that lacks the supervisor
executable, Electron client module, or installer delegation. Installed proof
still requires launching from the installed shortcut, observing supervisor
status and child PID, activating an update, and confirming the expected build
reconnects.

### Slim cloud-only package

Production Electron loads `https://wa.colmeio.com/home?native=electron`, so the
installer does not duplicate the cloud PWA tree, property-photo/speech models,
or Android APK. Models remain immutable, versioned web/runtime downloads;
Android diagnostics resolve the current APK through the release feed. The
installer retains only Electron, the supervisor, native kernel/preload,
fallback page, bridge-operation emergency modules, icons, and the bounded local
diagnostic runner.

Final NSIS verification must fail if `resources/public` or a bundled Android
APK reappears. This keeps every rebuild/update from redundantly compressing,
downloading, extracting, and scanning gigabytes of remotely owned assets.

Package size is recorded as telemetry and may warn on unusual growth, but size
alone is not a release failure. The build-breaking invariant is semantic
ownership: `resources/` may contain only `app.asar`, `bridge-ops`, `horc`, the
supervisor/default/icon files, and Electron's `elevate.exe`. Any other resource
owner must be deliberately reviewed and added to the contract. PWA trees,
Android APKs, ONNX/TFLite models, and old Windows release artifacts are always
rejected before promotion regardless of their size. Final NSIS verification
independently checks forbidden extracted paths and records installer bytes.

## Frontier Commands

The cloud backend exposes gated Frontier routes:

| Route | Purpose |
| --- | --- |
| `GET /native/frontier/status` | Compact app/auth/frontend/native/backend health and recommended next action |
| `POST /native/frontier/command` | Queue scoped command for one device or explicit test cohort |

Authorization requires admin session, localhost operator access, or
`X-Wasm-Agent-Native-Control-Key: $WASM_AGENT_NATIVE_CONTROL_KEY`. Destructive
commands such as cache clear or restart require an explicit destructive gate.
Unknown commands are refused. No global unauthenticated reload endpoint is
allowed.

Before declaring an open Windows app disconnected or selecting a target from
`plugins/wasm-agent/state/native-control/heartbeats`, run
`python3 tools/context/prove-production-native-control-authority.py`. The
authenticated production `/native/control/clients` registry is authoritative;
the repository-local heartbeat directory is only a potentially stale mirror.
Queue restart or install commands only to a production-live ID and verify the
receipt from that same production environment.

Create or rotate the shared operator key with
`python3 plugins/wasm-agent/scripts/ensure_native_control_key.py`. The private
value stays in gitignored `plugins/wasm-agent/conf/wa.env`; Windows proof tools
load it automatically and never print it. Restart the backend after rotation.

Android real-device Hermes Wake proof now uses the stable generic bridge
operation `run_hot_operation`. Windows is now treated as a hot-op shell: the
installed app keeps stable primitives for Electron startup, backend validation,
native-control polling, result upload, ADB, manifest scanning, and
capability-checked helper APIs; Android/Hermes workflow logic lives in hot
operations under `bridge-ops/`.

The shell resolves operation manifests in this order:

| Root | Purpose |
| --- | --- |
| `%USERPROFILE%/.wasm-agent/hot-ops` or `WASM_AGENT_HOT_OPS_OVERRIDE_DIR` | Local dev override; only active when `WASM_AGENT_ENABLE_HOT_OP_OVERRIDES=1` or `WASM_AGENT_ENABLE_LOCAL_HOT_OPS=1` is set before launching the installed app. Modules reload on every run. |
| `%APPDATA%/WASM-Agent/bridge-ops` | Downloaded/release-feed ops; manifests must be trusted before loading. Modules reload on every run. Shells that include the downloaded-hot-op sync fetch trusted bundles from `/native/releases/latest.json` before `get_bridge_status`, `list_hot_operations`, `run_shell_self_test`, or `run_hot_operation`. |
| Installed `bridge-ops/` resource | Bundled emergency/base ops. |

The native release feed publishes trusted hot-op bundles under
`artifacts.hotOps`. The Hermes bundle is served from
`/native/releases/hot-ops/android/`, carries per-file SHA-256 metadata plus a
relative `targetPath`, and is cached into `%APPDATA%/WASM-Agent/bridge-ops`.
This closes future Hermes hot-op-only edits without another Windows rebuild
after a shell with the downloaded-hot-op sync is installed. Older installed
shells that only know the downloaded root but do not know how to sync the feed
will continue to report `hotOpSource=bundled` until updated or given a local
override inside the Windows process.

The same release feed also publishes the downloaded native runtime under
`artifacts.runtime.launcher`. Files are served from
`/native/releases/runtime/launcher/`, staged under
`%APPDATA%/WASM-Agent/runtime/staging/<bundleId>`, activated into
`%APPDATA%/WASM-Agent/runtime/active`, and the previous active bundle is kept
under `%APPDATA%/WASM-Agent/runtime/last-known-good`. The shell compares
`bundleSha`, `manifestSha`, per-file SHA-256, and relative `targetPath`
metadata before activation. `rollback_downloaded_runtime` swaps the active and
last-known-good roots; if no previous bundle exists it returns
`last_known_good_missing`.

Native kernel/control commands:

| Command | Purpose |
| --- | --- |
| `get_native_kernel_status` | Report installed build, capability kernel, active downloaded runtime/hot-op IDs and SHAs, sync status, and stale reason. |
| `sync_downloaded_runtime` / `refresh_downloaded_runtime` | Force release-feed runtime sync from `/native/releases/latest.json`. |
| `rollback_downloaded_runtime` | Restore `%APPDATA%/WASM-Agent/runtime/last-known-good`. |
| `sync_downloaded_hot_ops` / `refresh_downloaded_hot_ops` | Force trusted hot-op bundle sync. |
| `list_hot_operations` | Inspect effective hot-op roots and manifests. |
| `run_shell_self_test` | Verify bridge, runtime, hot-op, path, SHA, capability, ADB, and upload primitives. |
| `run_hot_operation` | Execute a manifest-scanned operation such as `canary_echo`, `classify_native_diagnostics`, or `run_android_hermes_wake_proof`. |
| `play_wake_phrase_probe` | Fixed, bounded Windows SpeechSynthesizer playback for wake-word lab probes. |
| `play_audio_stimulus` | Fixed, bounded room-state stimuli: speech, system sound, beep, or silence. New source support still requires an installed shell update before runtime use. |

Native-control command handlers are wrapped by an executor watchdog in the
Windows shell. Every command receives a bounded timeout, timeout results are
reported as `handler_timeout`, result upload runs from the polling loop's
`finally` path, and polling state is cleared so later commands can still run.
The default `run_shell_self_test` path stays cheap and skips ADB recovery unless
`includeAdbDiscovery` or `requireAuthorizedAndroid` is explicitly set; Hermes
wake proof performs its own Android discovery before doing Android work. This
guard lives in bundled Electron `main.js`; if an installed app predates the
watchdog and is already wedged at `handler_never_resolved`, a hot op cannot
repair the queue loop. Install the verified shell, fully reopen the app, then
rerun `python3 tools/windows/prove-hot-shell.py --wait-sec 120` before Hermes
wake proof.

Manual command-file contract: command files dropped directly into
`plugins/wasm-agent/state/native-control/commands/<device-id>/` must use the
top-level `type` field. Do not use only `command`. The backend API normalizes
`command` into `type` when it creates the file, but a hand-written file bypasses
that normalizer; Electron reads `command.type`, so `command`-only files execute
as an empty verb and return `unsupported_command:`.

Correct ADB bridge probes:

```json
{
  "id": "cmd-check-android-connection",
  "deviceId": "win-desktop-...",
  "type": "check_android_connection",
  "status": "pending",
  "createdAt": "2026-06-18T20:00:20Z",
  "payload": {}
}
```

```json
{
  "id": "cmd-collect-adb-diagnostics",
  "deviceId": "win-desktop-...",
  "type": "collect_adb_diagnostics",
  "status": "pending",
  "reason": "after_wake_transcript_crash_bounded_logcat",
  "payload": {
    "reason": "after_wake_transcript_crash_bounded_logcat",
    "nativeControlTimeoutMs": 120000
  }
}
```

Correct Hermes proof probe:

```json
{
  "id": "cmd-hermes-proof",
  "deviceId": "win-desktop-...",
  "type": "run_android_hermes_wake_proof",
  "status": "pending",
  "reason": "wake_transcript_crash_repro",
  "payload": {
    "waitMs": 25000,
    "wakeThreshold": 0.58,
    "timeoutMs": 90000,
    "nativeControlTimeoutMs": 120000,
    "args": {
      "waitMs": 25000,
      "wakeThreshold": 0.58,
      "timeoutMs": 90000
    }
  }
}
```

If the result has `result.error: "unsupported_command:"`, first inspect the
queued command shape for missing `type` before concluding the installed bridge
lacks ADB or hot-op capability.

The downloaded runtime format is
`hermes.wasm_agent.downloaded_runtime.v1` with `runtime-manifest.json`,
`launcher.html`, `launcher.css`, `launcher.js`, `diagnostics-schema.json`,
`runtime-config.json`, and `model-metadata.json`. The hot-op manifest format is
`hermes.wasm_agent.hot_operation_manifest.v1` with `operationId`,
`requiredNativeCapabilities`, `inputsSchema`, `outputsSchema`, `safetyLimits`,
and `rollback`.

The bundled fallback module is
`native/windows/ops/android/hermes-wake-proof.js` with manifest
`native/windows/ops/android/hermes-wake-proof.manifest.json`. Prefer compact
manifest-based payloads:

```json
{"operationName":"run_android_hermes_wake_proof","args":{"waitForSpeech":true,"timeoutMs":30000}}
```

Explicit `modulePath` remains only for dev/debug. Hot ops receive only
capability-scoped helpers for ADB, safe files, artifacts, release/feed reads,
diagnostics, result upload, and logging. Absolute module paths, `..` traversal,
missing modules, SHA mismatches, denied capabilities, disabled hot ops,
timeouts, and exceptions return structured `hot_operation_*` errors wrapped in
a camelCase result envelope with `rawResult` preserved.

Use `list_hot_operations` to inspect the installed bridge view before a proof
run. It reports `supportedHotOpsProtocol`, `hotOpsMode`, `hotOpsRoot`,
`devReload`, every root, and `availableHotOps` with manifest path, entry,
version, SHA-256, capabilities, timeout, and loaded source.
`list_hot_operations` accepts `forceSync: true` to fetch the release feed and
compare trusted downloaded bundle metadata against the local cache. Shells with
the refresh capability also accept `refresh_downloaded_hot_ops` or
`sync_downloaded_hot_ops`, which force the same sync and report
`downloadedHotOpsSync.ok`, `changed`, `feedBundleId`, `cachedBundleId`,
`moduleSha`, `manifestSha`, `cachePath`, and `error`.

Use local overrides to patch Hermes wake proof without rebuilding the Windows
installer:

```bash
cd native/windows/src
npm run sync:hot-op -- android hermes-wake-proof
```

Then launch the installed Windows app with
`WASM_AGENT_ENABLE_HOT_OP_OVERRIDES=1`. The installed shell will load
`%USERPROFILE%\.wasm-agent\hot-ops\android\hermes-wake-proof.js` and its
manifest before downloaded or bundled ops. Edits limited to
`native/windows/ops/android/hermes-wake-proof.js` and
`native/windows/ops/android/hermes-wake-proof.manifest.json` can be tested by
rerunning the sync command and proof command; a Windows rebuild/reinstall is not
required for those hot-op-only changes.

`WASM_AGENT_BRIDGE_OPS_DIR` remains an explicit dev override root, but it is
ignored unless local overrides are enabled. `WASM_AGENT_HOT_OPS_DEV_RELOAD=1`
forces cache clearing on bundled ops,
`WASM_AGENT_DISABLE_HOT_OPS=1` returns `hot_operations_disabled`,
`WASM_AGENT_HOT_OPS_REQUIRE_SHA=1` requires SHA metadata for non-bundled ops,
and `WASM_AGENT_ENABLE_VERBOSE_BRIDGE_LOGS=1` includes verbose `logsTail`
details.

Every hot-op proof envelope includes `hotOpSource` (`local_override`,
`downloaded`, or `bundled`), `hotOpPath` or `bundleId`, `hotOpSha`,
`bundledHotOpSha`, `overrideEnabled`, and the manifest timeout as
`manifestTimeoutMs`.

Use `run_shell_self_test` before Hermes wake proof. It checks bridge liveness,
root readability, manifest scanning, path traversal/absolute-path rejection,
missing-op classification, SHA mismatch classification, capability denial, ADB
discovery, authorized-device presence when connected, and result-upload
availability or local-mode skip.

ADB discovery in the shell and hot-op helper now uses the exact configured
`adb.exe`, repairs cold/stale daemon state with bounded `kill-server`,
`start-server`, and `devices -l` retries for up to 30 seconds, then preserves
the stable blocker state: `adb_missing`, `adb_timeout`,
`adb_server_start_failed`, `no_device`, `unauthorized`, `offline`,
`multiple_devices`, or `one_authorized_device`. Hermes proof continues only
after `one_authorized_device`.

Use the canary hot operation before debugging Android/Hermes logic:

```json
{"operationName":"canary_echo","args":{"dryRun":true}}
```

The expected canary result is `ok: true`, `stable: true`,
`operation: "canary_echo"`, `source: "hot_operation"`, and
`message: "hot op loaded"`.

The shell protocol contract is:

```json
{
  "shellProtocolVersion": 2,
  "downloadedRuntimeProtocolVersion": 1,
  "hotOpsProtocolVersion": 1,
  "nativeKernelVersion": "2026.06.14",
  "minimumRunnerVersion": "20260612",
  "capabilities": [
    "get_bridge_status",
    "get_native_kernel_status",
    "sync_downloaded_runtime",
    "refresh_downloaded_runtime",
    "rollback_downloaded_runtime",
    "sync_downloaded_hot_ops",
    "refresh_downloaded_hot_ops",
    "list_hot_operations",
    "run_shell_self_test",
    "run_hot_operation"
  ],
  "supportedCapabilities": [
    "native.capabilities.runtimeLoader.v1",
    "native.capabilities.hotOps.v1",
    "native.capabilities.statusBus.v1",
    "native.capabilities.diagnostics.v1",
    "native.capabilities.fileStore.v1",
    "native.capabilities.downloadedRuntime.v1",
    "native.capabilities.downloadedOperations.v1",
    "native.capabilities.deviceControl.v1",
    "native.capabilities.webViewBridge.v1",
    "native.capabilities.boundedCommand.v1",
    "native.capabilities.auditLog.v1",
    "native.capabilities.releaseFeedValidation.v1",
    "native.capabilities.nativeControlPolling.v1",
    "native.capabilities.crashSafeStatus.v1",
    "native.capabilities.capabilityManifest.v1",
    "native.capabilities.observabilityLease.v1"
  ]
}
```

Fast proof/debug commands:

```bash
python3 tools/windows/prove-hot-shell.py
python3 tools/doctor/wasm-agent-doctor.py
python3 tools/voice/run-hermes-wake-proof.py --dry-run
python3 tools/voice/run-hermes-wake-proof.py --debug
```

Local proof scripts write latest artifacts under `reports/<area>/latest/` and
per-run artifacts under `reports/<area>/runs/<runId>/`. Each result envelope
includes `runId`, `failureClassification`, `nextAction`, and an `artifacts`
object with `result` and `logs`. Windows installed-app operation artifacts use
`%APPDATA%/WASM-Agent/runs/<runId>/` when produced by the shell.

Use `tools/voice/run-hermes-wake-proof.py` from the repo. It defaults to the
local bridge at `http://127.0.0.1:8877`, reads heartbeat hot-op capabilities,
prints the active root/mode, verifies `run_android_hermes_wake_proof` is
visible when the heartbeat lists ops, and queues compact manifest-based
`run_hot_operation`. It reports `bridge_update_required` only when the shell
lacks `run_hot_operation`, lacks `list_hot_operations`, or exposes an old/missing
hot-op protocol. It reports `hot_operation_missing` separately. Stale
command-specific fallback is opt-in with `--allow-stale-command-fallback`.

Wake proof diagnostics should prefer compact Wake Word state from
`/native/android/wake-word-state` before reading the larger native diagnostics
snapshot. The classifier accepts `model_source: "openwakeword_bundle"` when
ONNX Runtime and the wake engine are ready, even though the legacy personalized
Hermes model SHA fields may be empty or mismatched.

For fully autonomous wake-loop tests, the source tree includes a bounded Windows
speaker primitive under native-control command `play_wake_phrase_probe`. It uses
the fixed Windows SpeechSynthesizer path with phrase/rate/volume inputs only.
Source also adds `play_audio_stimulus` for non-speech hard negatives such as
system sounds, beeps, and silence. Use `play_wake_phrase_probe` first when the
installed shell already proves it; do not claim `play_audio_stimulus` is live in
an installed app until the native shell containing that handler is rebuilt,
installed, and proven through `get_native_kernel_status` or a successful command
result.

The downloaded hot operation `inspect_windows_audio_loopback` inventories at
most 32 Windows AudioEndpoint devices through one fixed bounded PowerShell
query. It classifies ready, disabled, missing, and non-default loopback capture
routes without changing Windows settings. Run its production harness promise
before acoustic browser-transcription tests:

```bash
python3 tools/windows/prove-audio-loopback.py --origin https://wa.colmeio.com
```

If the endpoint route passes but transcription reports `no-speech`, measure the
actual default-capture samples while the same hot operation synthesizes speech:

```bash
python3 tools/windows/prove-audio-signal.py --origin https://wa.colmeio.com
```

The compact proof reports `peak`, `rms`, and `signalPresent`, separating a
silent render/cable path from a downstream browser recognition failure without
an installer rebuild.

The proof passes only when a ready loopback endpoint such as Stereo Mix,
Mixagem estéreo, VB-CABLE, VoiceMeeter Output, or a monitor endpoint is already
the default recording route. A missing or disabled endpoint is runtime evidence
for the next action, not permission to install a driver or mutate the user's
audio defaults.

After explicit user authorization, the downloaded hot operation
`set_windows_audio_capture_default` can select one exact, ready capture endpoint
for the current user's console, multimedia, and communications roles. It
requires both the endpoint instance ID and its expected friendly name, supports
dry-run, and returns bounded change evidence. Rerun the read-only loopback
promise immediately after the change; the action result alone is not proof.

Use `python3 tools/windows/set-audio-capture-default.py` with the exact endpoint
ID and expected name. The wrapper is dry-run by default and requires `--apply`
after explicit user authorization.

Common diagnoses:

| Status | Meaning |
| --- | --- |
| `bridge_update_required` | Installed bridge lacks the generic hot-op/list/protocol contract; rebuild/reinstall proof is required. |
| `hot_operation_missing` | Bridge is new enough, but the requested manifest is not visible in `list_hot_operations`. Use a registered op or publish/register the missing manifest. |
| `hot_operation_sha_mismatch` | Expected or manifest SHA does not match the loaded entry. |
| `hot_operation_capability_denied` | The manifest did not grant a helper capability the op attempted to use. |
| `hot_operations_disabled` | `WASM_AGENT_DISABLE_HOT_OPS=1` is active. |
| `hot_operation_timeout` | The op exceeded the stricter of payload timeout and manifest timeout. Hermes wake proof manifests may request up to 180 seconds and timeout envelopes include `timeoutMs`, `elapsedMs`, `lastPhase`, and phase-specific `failureClassification`. |

The Windows installable should remain the stable shell: Electron startup,
backend validation, local bridge server/control polling, self-update,
hot-operation loader/helpers, diagnostics/result upload, and bundled base ops.
Do not bundle Android APKs, reports, simulator fixtures, datasets, logs, docs,
or dev-only scripts unless a reviewed runtime path requires them.

Production packaging excludes old Windows installers, blockmaps, Android APK
payloads, logs, screenshots, maps, and proof artifacts from the Electron
resources. Android APKs are resolved from the native release feed and downloaded
into app data when needed for proof/install flows.

## Durable Next Step

Trigger Go Native / Check Update, install/restart the feed-published Windows
hot-op shell, then prove the installed local bridge with:

```bash
python3 tools/windows/prove-hot-shell.py
python3 tools/doctor/wasm-agent-doctor.py
python3 tools/voice/run-hermes-wake-proof.py --dry-run
python3 tools/voice/run-hermes-wake-proof.py --debug
```

Do not claim installed Windows shell proof from source tests, build success,
`win-unpacked`, or feed presence. The installed bridge must pass
`prove-hot-shell.py` before Hermes wake proof/debug results are treated as
Android wake evidence.

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
