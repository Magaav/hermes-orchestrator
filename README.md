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
| `docs/context` | Context protocol, route map, claims, verification, review loop | `docs/context/README.md` | verified | docs smell scan in `docs/context/VERIFY.md` |
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
| Windows release feed points at `win-x64-20260609T220027Z` | implemented-unverified | `plugins/wasm-agent/public/native/releases/latest.json`; package/runtime proof still required |
| Windows login persistence fix status | implemented-unverified | Must not be claimed fixed until installed-app proof passes |
| Android build `android-universal-20260612T131155Z` exists | implemented-unverified | `native/android/release/release-manifest.json` and SHA; `apksigner` unavailable in this session |
| Latest Android simulation report proves voice wake fixture behavior | verified | `reports/sim/android/latest/summary.md`; does not prove current APK OAuth |
| Roadmap current-software claims | unknown | Roadmap docs are proposal/future/status unless reconciled with code and product docs |

## Verification Matrix

| Behavior | Command or proof |
| --- | --- |
| Context smell scan | See `docs/context/VERIFY.md` |
| Fresh-agent structured test | See `docs/context/REVIEW.md` |
| PWA/browser behavior | `horc simulate web` |
| wasm-agent focused checks | `/local/plugins/wasm-agent/scripts/doctor.sh` or focused tests under `plugins/wasm-agent/tests` |
| Windows final installer extraction | `cd native/windows/src && npm run verify:win-installer -- <final-nsis-installer>` |
| Windows installed login persistence | `native\windows\scripts\verify-installed-app.ps1 -Launch -InteractiveLogin` on Windows |
| Windows hot-op shell preflight | Queue `list_hot_operations` and `run_shell_self_test` through the installed local bridge before Hermes/Android proofs. |
| Android package | `apksigner verify --verbose native/android/release/WASM-Agent-arm64.apk` plus forbidden-origin scan |
| Android runtime | `horc simulate android` or `horc simulate android --local-report <path>` |
| Public script smoke | `horc status`, `horc build doctor`, or the script's focused doctor/help mode |

Build success is not runtime proof. Missing proof demotes the claim.

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

The Windows native app is a minimal bridge shell for live Android/Hermes proof
iteration. It exposes stable primitives and manifest-scanned hot ops instead of
embedding workflow logic in the installed shell. Use
`WASM_AGENT_BRIDGE_OPS_DIR=/local/native/windows/ops` for dev ops, queue
`list_hot_operations` to confirm the active root/mode and visible manifests,
then queue `run_shell_self_test` before `tools/voice/run-hermes-wake-proof.py`.

Do not treat `bridge_update_required`, `hot_operation_missing`,
`hot_operation_sha_mismatch`, `hot_operation_capability_denied`, or
`hot_operations_disabled` as runtime proof failures for Android itself; they are
Windows bridge/hot-op loading classifications to resolve before wake proof.

## Human Links

| Topic | Link |
| --- | --- |
| Command reference | `docs/commands/horc.md` |
| Feature docs | `docs/features/README.md` |
| Roadmap tracks | `docs/roadmap/README.md` |
| Plugin root | `plugins/README.md` |
| Script root | `scripts/README.md` |
