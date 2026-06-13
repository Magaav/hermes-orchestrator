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
| Native release feed | implemented-unverified | `plugins/wasm-agent/public/native/releases/latest.json` | Feed presence is not runtime proof. |
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
| Ship Hermes Wake model | `WASM_AGENT_NATIVE_CONTROL_KEY=... tools/voice/ship-hermes-wake.sh` |

## Native Release Feed

| Platform | Current local feed/evidence | Status | Missing proof |
| --- | --- | --- | --- |
| Windows | `win-x64-20260612T152322Z`, shell SHA `c77a542d6444f16afbcdd556b704f59a6176238bd886c5d9901ae6c2a1f6608b`, feed includes `supportedHotOpsProtocol: 1` | implemented-unverified | New shell rebuild/install plus final NSIS/app.asar verification and installed runtime proof |
| Android | `android-universal-20260612T201043Z`, SHA `15d49526bf556368597796a8ac4c6991376088b4dbd709d36a25f47cb753ad06` in `native/android/release/release-manifest.json` and feed | implemented-unverified | Package signer/string proof and OAuth runtime proof |
| Web | `web-20260612T131334Z` in feed | implemented-unverified | `horc simulate web` |

## Durable Next Step

Current next action: continue the Hermes Wake data/model loop without an APK
rebuild. Run `tools/voice/ship-hermes-wake.sh` with
`WASM_AGENT_NATIVE_CONTROL_KEY` set. The script queues the installed Win11
wasm-agent bridge command `export_hermes_wake_dataset`, downloads the protected
uploaded `hermes-dataset.zip`, imports it into `data/voice/hermes`, trains and
verifies `build/voice/hermes.onnx`, then prints the model metadata from
`/native/android/hermes-wake-model/latest.json`. Do not use terminal ADB from
this workspace for this workflow. Install the model through the Android bridge
with `installHermesWakeModel("/native/android/hermes-wake-model/latest",
"<sha256>")`.

After the hot-op shell update is installed once, Hermes proof/debug logic lives
outside the Windows installer. Edit `native/windows/ops/android/hermes-wake-proof.js`
or stage an updated module into `%APPDATA%/WASM-Agent/bridge-ops`, then run
`python3 tools/voice/run-hermes-wake-proof.py`. The helper queues
`run_hot_operation`; `bridge_update_required` means the installed Windows shell
does not yet support the generic hot-op runner.

Secondary queue: after the wake-model loop, verify the current Windows feed
installer with `verify:win-installer`, then run real Windows installed-app login
persistence proof. Do not claim Windows login persistence is fixed until the
installed app proof passes.

## Claim Boundaries

- Build success is not runtime proof.
- Release feed publication is not installed-app proof.
- Web simulation is not Android or Windows native proof.
- Android package proof is not OAuth proof.
- Roadmap claims stay in `docs/roadmap` until implemented and verified here.
- Generated reports, diagnostics, uploaded datasets, pid files, and mutable
  caches stay under `state/` or `reports/` unless a reviewed fixture is needed.
