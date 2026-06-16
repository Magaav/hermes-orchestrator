# wasm-agent Windows Native

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
| Proof floor | Final extracted NSIS installer and installed `app.asar` verification |
| Runtime proof floor | Real installed app with Google login, close/reopen, route, cookie, expiration metadata, and `/auth/session` |

Read first: `/local/AGENTS.md`, `/local/README.md`, `docs/context/MAP.md`,
`native/AGENTS.md`, `native/NATIVE_SHELL_CONTRACT.md`, this directory's
`AGENTS.md`, then this file.

## Current Evidence

| Evidence | Status | Notes |
| --- | --- | --- |
| Local verified installer `WASM-Agent-Setup-x64-0.1.0-20260615T135340Z.exe` | verified | Built with `WASM_AGENT_SKIP_WIN_RESOURCE_EDIT=1`; verifier extracted final NSIS payload and `app.asar`. Installer SHA `77811e7d3f2a778a0d9adcbc45cef14f92194719a35fc2b02856d3c83575f20d`; `app.asar` SHA `cbaa3e22ffee82630558cab8c481e91e3c5c5f9bca0c5d8cb267a80441c4021f`. Package proof only; installed runtime proof still required after install/reopen. |
| `native/windows/release/VERIFY.json` | verified | Present for build `win-x64-20260615T135340Z`; package proof only, not installed runtime proof. |
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
    "native.capabilities.capabilityManifest.v1"
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
**Active goal:** Install the feed-published Windows hot-op shell, prove the installed bridge, then use hot ops to classify why spoken Hermes does not trigger an action.

**Canonical proof order:**

1. `cd native/windows/src && npm run verify:win-installer -- /local/native/windows/release/WASM-Agent-Setup-x64-0.1.0-20260613T003310Z.exe`
2. `python3 tools/windows/check-windows-release-feed.py`
3. `python3 tools/windows/prove-hot-shell.py`
4. `python3 tools/doctor/wasm-agent-doctor.py`
5. `python3 tools/voice/run-hermes-wake-proof.py --dry-run`
6. `python3 tools/voice/run-hermes-wake-proof.py --debug`

**Windows hot-op shell protocol:** `shellProtocolVersion: 2`, `hotOpsProtocolVersion: 1`

**Required shell capabilities:** `get_bridge_status`, `list_hot_operations`, `run_shell_self_test`, `run_hot_operation`, `canary_echo`

**Hermes wake question:** Does spoken Hermes fail because threshold is not crossed, wake event is not emitted, or command capture/UI routing does not start?

**Proof guards:**

- Do not claim installed Windows shell proof from source tests, build success, or win-unpacked.
- Build success is not update availability; package verification is not feed publication.
- Go Native / Check Update depends on the Windows release feed, and same-semver Windows updates must compare buildId.
- Do not claim Android runtime proof from APK package proof alone.
- Do not treat bridge_update_required or hot_operation_missing as Android wake failures.
- Do not use old command-specific Windows bridge handlers as the canonical Hermes wake proof path.
<!-- END ACTIVE_STATE -->
