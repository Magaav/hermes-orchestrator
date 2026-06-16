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
| Account auth allowlist | implemented-unverified | auth tests; `conf/README.md` | `ADMIN_EMAIL` and optional `USER_EMAILS`; empty allowlists reject all Google accounts. |
| Native release feed | implemented-unverified | `plugins/wasm-agent/public/native/releases/latest.json`; `reports/windows/latest/windows-release-feed-check.json` | Current local Windows feed guard fails without `native/windows/release/VERIFY.json`; feed publication is not installed runtime proof. |
| Downloaded native runtime feed | implemented-unverified | `artifacts.runtime.launcher` in release feed; `node plugins/wasm-agent/tests/native_release_feed.test.js` | Requires installed native shells with downloaded-runtime sync before runtime IDs/SHAs are installed evidence. |
| Windows trusted hot-op feed | implemented-unverified | `artifacts.hotOps.android.hermesWakeProof` in release feed; `node plugins/wasm-agent/tests/native_release_feed.test.js`; `npm run test:windows-hot-ops` | Requires an installed Windows shell with downloaded-hot-op sync before proof can report `hotOpSource=downloaded`. |
| Frontier operator loop | implemented-unverified | focused server/control tests or gated curl proof | Commands must remain authenticated, audited, bounded, and operation-based. |
| Dev HMR | implemented-unverified | `horc simulate web`; JS smoke tests | Local developer convenience, not production sync contract. |
| Hermes Wake data/model loop | implemented-unverified | Android bridge/model tests and device proof | Prefer dataset/model iteration over APK rebuilds. |
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
| Web simulation | `horc simulate web` |
| Android simulation | `horc simulate android` |
| Native feed build | `horc build all` |
| Windows feed guard | `python3 tools/windows/check-windows-release-feed.py` |
| Hermes Wake proof | `python3 tools/voice/run-hermes-wake-proof.py --dry-run`; `python3 tools/voice/run-hermes-wake-proof.py --debug` |

## Native Release Feed

The feed is the native evolution control point. It publishes installer/APK
artifacts plus server-downloadable runtime and operation bundles:

| Feed key | URL prefix | Purpose |
| --- | --- | --- |
| `artifacts.runtime.launcher` | `/native/releases/runtime/launcher/` | Downloaded launcher/runtime UI, diagnostics schema, runtime config, model metadata, and operation routing. |
| `artifacts.hotOps.android.hermesWakeProof` | `/native/releases/hot-ops/android/` | Hermes wake proof/debug operation with server-controlled `wakeThreshold` policy. |
| `artifacts.hotOps.diagnostics.nativeDiagnosticsClassifier` | `/native/releases/hot-ops/diagnostics/` | Non-Hermes diagnostics classifier proving the generic hot-op path. |

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
