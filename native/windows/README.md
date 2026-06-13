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
| Release feed installer `WASM-Agent-Setup-x64-0.1.0-20260612T152322Z.exe` | implemented-unverified | Feed SHA `c77a542d6444f16afbcdd556b704f59a6176238bd886c5d9901ae6c2a1f6608b`; built via `linux-arm64-native-nsis-no-rcedit`, so Windows smoke proof remains required. |
| `native/windows/release/VERIFY.json` | verified | Final NSIS extraction and `app.asar` verification passed for build `win-x64-20260612T152322Z`. |
| Win11 staged update | implemented-unverified | Old app staged `C:\Users\Victor\AppData\Local\WASM Agent Native\staged\windows-updates\WASM-Agent-Setup-x64-0.1.0-20260612T152322Z.exe`; guided installer approval/install still required. |
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
`/local/plugins/wasm-agent/public/native/releases/`. Feed publication is not
installer/runtime verification.

## Verification

Final NSIS/app.asar proof:

```bash
cd native/windows/src
npm run verify:win-installer -- /local/plugins/wasm-agent/public/native/releases/windows/WASM-Agent-Setup-x64-0.1.0-20260609T220027Z.exe
```

Expected proof artifact:

```text
native/windows/release/VERIFY.json
```

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
| `WASM_AGENT_BRIDGE_OPS_DIR` | Dev override; modules reload on every run. |
| `%APPDATA%/WASM-Agent/bridge-ops` | User-staged ops; modules reload on every run. |
| Installed `bridge-ops/` resource | Bundled emergency/base ops. |

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
version, SHA-256, capabilities, timeout, and loaded source. Set
`WASM_AGENT_BRIDGE_OPS_DIR=/local/native/windows/ops` for dev override;
`WASM_AGENT_HOT_OPS_DEV_RELOAD=1` forces cache clearing on every run,
`WASM_AGENT_DISABLE_HOT_OPS=1` returns `hot_operations_disabled`,
`WASM_AGENT_HOT_OPS_REQUIRE_SHA=1` requires SHA metadata for non-bundled ops,
and `WASM_AGENT_ENABLE_VERBOSE_BRIDGE_LOGS=1` includes verbose `logsTail`
details.

Use `run_shell_self_test` before Hermes wake proof. It checks bridge liveness,
root readability, manifest scanning, path traversal/absolute-path rejection,
missing-op classification, SHA mismatch classification, capability denial, ADB
discovery, authorized-device presence when connected, and result-upload
availability or local-mode skip.

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
  "hotOpsProtocolVersion": 1,
  "minimumRunnerVersion": "20260612",
  "capabilities": [
    "get_bridge_status",
    "list_hot_operations",
    "run_shell_self_test",
    "run_hot_operation"
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
| `hot_operation_missing` | Bridge is new enough, but the manifest is not visible in the active root. Check `WASM_AGENT_BRIDGE_OPS_DIR` and bundled resources. |
| `hot_operation_sha_mismatch` | Expected or manifest SHA does not match the loaded entry. |
| `hot_operation_capability_denied` | The manifest did not grant a helper capability the op attempted to use. |
| `hot_operations_disabled` | `WASM_AGENT_DISABLE_HOT_OPS=1` is active. |
| `hot_operation_timeout` | The op exceeded the stricter of payload timeout and manifest timeout. |

The Windows installable should remain the stable shell: Electron startup,
backend validation, local bridge server/control polling, self-update,
hot-operation loader/helpers, diagnostics/result upload, and bundled base ops.
Do not bundle Android APKs, reports, simulator fixtures, datasets, logs, docs,
or dev-only scripts unless a reviewed runtime path requires them.

## Durable Next Step

Install the staged Win11 update
`WASM-Agent-Setup-x64-0.1.0-20260612T152322Z.exe`, confirm the native-control
heartbeat reports `win-x64-20260612T152322Z` or newer, then rerun the Hermes
Wake export/train loop. After installation, run
`native\windows\scripts\verify-installed-app.ps1 -Launch -InteractiveLogin` for
Windows runtime/login proof.
