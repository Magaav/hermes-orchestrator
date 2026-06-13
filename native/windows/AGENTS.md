# Windows Native Context Contract

## Purpose

`native/windows` owns the Windows desktop installer and Electron shell for WASM
Agent Native.

## Ownership

- Owns Electron main/preload code, electron-builder config, Windows packaging,
  installer verification, installed-app verification scripts, and Windows-side
  native diagnostics.
- Shared web/PWA behavior remains in `/local/plugins/wasm-agent`.
- Cross-platform native rules come from `/local/native/AGENTS.md` and
  `/local/native/NATIVE_SHELL_CONTRACT.md`.

## Local Contracts

- Production Windows native is cloud-only and must load
  `https://wa.colmeio.com/home?native=electron` after backend validation.
- `127.0.0.1:8877`, localhost, source-tree assets, and dev fallbacks are
  development-only and forbidden as production defaults.
- Never claim the Windows installer is fixed from source tests, `win-unpacked`,
  or build success. The final extracted NSIS installer and installed
  `app.asar` must pass verification, and login persistence requires a real
  installed-app pass.
- Installers must not embed account secrets or pre-minted device tokens.

## Work Guidance

- Before editing, read `/local/AGENTS.md`, `/local/README.md`,
  `/local/docs/context/MAP.md`, `/local/native/AGENTS.md`,
  `/local/native/NATIVE_SHELL_CONTRACT.md`, this file, and `README.md`.
- Keep backend probing, Google login, cookie persistence, service-worker cache
  clearing, and preload bridge changes aligned with the cloud PWA contract.
- Keep diagnostics bridges bounded to named operations with fixed arguments and
  audited outputs.

## Verification

- Packaged installer extraction/app.asar proof:
  `cd native/windows/src && npm run verify:win-installer`.
- Installed app proof on Windows:
  `native\windows\scripts\verify-installed-app.ps1 -Launch -InteractiveLogin`.
- Android OAuth phone proof through Windows app:
  `Open WASM Agent -> Diagnostics -> Verify Android OAuth`.

## Child Context Index

- `README.md`: build lanes, release feed behavior, verification steps, Frontier
  commands, and current Windows status.
- `src/`: Electron app source, build config, packaged defaults, and tests.
- `scripts/`: installer, installed-app, and diagnostics verification helpers.
- `release/`: generated artifacts and verification JSON; treat as build output
  unless the task explicitly concerns release promotion.
