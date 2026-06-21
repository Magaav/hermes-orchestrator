# Native Context Contract

## Purpose

`native` owns shared WASM Agent Native shell policy for Windows, Android, macOS,
and Linux.

## Ownership

- Cross-platform native entrance, backend validation, Google login policy,
  diagnostics expectations, and live-evolution rules live here.
- Platform implementations live under `native/windows`, `native/android`,
  `native/macos`, and `native/linux`.
- Product PWA/backend contracts live in `plugins/wasm-agent`.

## Local Contracts

- Production native shells are cloud-only: `https://wa.colmeio.com`.
- Windows production route is `https://wa.colmeio.com/home?native=electron`.
- Localhost, emulator, source-tree assets, and dev ports are debug-only and
  forbidden as production defaults or production success claims.
- Native shells must validate backend identity before opening the app surface.
- Downloadable installers/APKs must not contain account secrets or pre-minted
  device tokens.
- Build success is package evidence only; runtime claims require runtime proof.

## Work Guidance

- Read `/local/AGENTS.md`, `/local/README.md`, `docs/context/MAP.md`, this
  file, and `NATIVE_SHELL_CONTRACT.md` before platform native edits.
- Then read the platform child `AGENTS.md` and README.
- For native shell, bridge, installer/APK, permission, service, hot-op, or
  runtime-proof work, use Verified Loop-Aware Engineering: separate Builder
  intent, Watcher evidence, and Gatekeeper decision; prefer static, runtime, and
  behavioral evidence when possible.
- Before implementing a native feature, classify behavior into stable native
  primitives versus live-updatable policy/downloaded operations. Native shells
  should expose durable primitives and diagnostics; tunable sequencing,
  thresholds, provider choice, retry order, command mapping, model metadata, and
  proof strategy should live in server/PWA policy, downloaded runtime/hot-op
  bundles, or native-control inputs whenever the installed capability surface
  can support it.
- Hard-coding tunable feature behavior in compiled native code is a loop-time
  regression unless the Builder report states why a live policy/downloaded-op
  boundary would be unsafe, missing a required primitive, or more complex/risky
  than the native change.
- Keep shared product behavior in `plugins/wasm-agent`; rebuild native shells
  only for OS shell, packaging, bridge, permission, service, icon, installer, or
  bundled native capability changes.

## Verification

- Windows package: `cd native/windows/src && npm run verify:win-installer -- <installer>`.
- Windows runtime: `native\windows\scripts\verify-installed-app.ps1 -Launch -InteractiveLogin`.
- Android package: `apksigner verify --verbose native/android/release/WASM-Agent-arm64.apk`.
- Android runtime: `horc simulate android` or `horc simulate android --local-report <path>`.

## Child Context Index

- `NATIVE_SHELL_CONTRACT.md`: shared backend, login, live-evolution, diagnostics,
  and platform status contract.
- `NATIVE_EVOLUTION_CONTRACT.md`: shared native capability kernel,
  downloaded-runtime, hot-op, sync, rollback, and no-rebuild contract.
- `windows/AGENTS.md`: Windows Electron/NSIS contract.
- `windows/README.md`: Windows build, proof, artifact, and next action.
- `android/AGENTS.md`: Android APK/WebView/voice contract.
- `android/README.md`: Android build, proof, artifact, and next action.
- `macos/README.md`: macOS packaging notes.
- `linux/README.md`: Linux packaging notes.
