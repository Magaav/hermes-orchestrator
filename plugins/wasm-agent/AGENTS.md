# wasm-agent Context Contract

## Purpose

`plugins/wasm-agent` owns the active WASM Agent PWA, cloud/local backend,
native bridge API, Frontier controls, native release feed, client-first account
state, and product UI surfaces.

## Ownership

- Product UI, browser/workspace, account, relay, native download/update, and
  Frontier backend work belongs here by default.
- Native OS shells live in `/local/native`; keep platform packaging and OS
  integration there, and keep shared web/runtime contracts here.
- Local runtime state under `state/` is gitignored deployment state, not source.

## Local Contracts

- Production native clients must use `https://wa.colmeio.com`; never route
  production behavior to `127.0.0.1:8877`, `localhost`, `0.0.0.0`, or emulator
  dev origins.
- Keep the app client-first where possible. Server work should be explicit:
  auth, presence/relay, sync, backup, provisioning, native diagnostics, or
  release metadata.
- Frontier/control routes must stay authenticated, audited, bounded, and
  operation-based. Do not add arbitrary shell execution or unauthenticated
  global reload controls.
- For Frontier, native bridge, release feed, hot-op, diagnostics, and runtime
  control changes, use the repo-wide Verified Loop-Aware Engineering doctrine:
  separate Builder intent, Watcher evidence, and Gatekeeper decision; prefer
  static, runtime, and behavioral evidence when possible.
- Generated reports, diagnostics, uploaded datasets, pid files, and mutable
  caches stay under `state/` or `reports/` unless a reviewed fixture is needed.

## Work Guidance

- Read `/local/docs/context/MAP.md`, this file, then `README.md` for current
  status, release handoff, and local verification.
- For frontend/UI work, also read `DESIGN.md`.
- For server/API work, also read `server/README.md`.
- For config defaults, also read `conf/README.md`.
- For generated/local state handling, also read `state/README.md`.
- Before rebuild-heavy or runtime-control work, prefer live introspection,
  HMR, hot-op, runtime config, downloaded runtime/model metadata, or a small
  diagnostic probe when that safely shortens the loop.
- Keep durable next actions short and actionable. If the handoff grows into a
  log, move details to the nearest focused doc and leave a pointer.

## Verification

- Web/PWA proof: `horc simulate web`.
- Android APK proof: `horc simulate android` with an authorized device/emulator,
  or `horc simulate android --local-report <path>` for copied evidence.
- Broad native feed/build proof: `horc build all` when touching release feed
  generation or cross-platform artifact publication.
- Server tests live under `tests/`; prefer focused smoke/unit checks before
  broad runs.

## Child Context Index

- `README.md`: current behavior, Frontier loop, durable next action, and active
  evidence.
- `server/README.md`: Python backend ownership and runtime notes.
- `conf/README.md`: configuration defaults and deployment knobs.
- `state/README.md`: gitignored runtime state layout.
- `public/native/`: generated native release feed and artifacts; do not edit by
  hand unless explicitly repairing release metadata.
