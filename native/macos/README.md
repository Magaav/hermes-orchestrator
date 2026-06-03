# wasm-agent macOS Native

This lane owns the macOS desktop body for wasm-agent.

Target output:

- `release/WASM-Agent.dmg`
- `release/WASM-Agent.pkg`

Contract:

- Follows the shared native shell contract in `../NATIVE_SHELL_CONTRACT.md`.
- Uses the shared Electron host from `../windows/src` until a macOS-specific
  shell is needed.
- Loads a validated backend PWA `/home` origin for Google login and HMR, with
  bundled app-shell assets as fallback/setup only.

Build:

```bash
cd native/windows/src
npm install
npm run build:mac:x64
npm run build:mac:arm64
```

Build status: shared Electron macOS `dmg` packaging lane is configured; release
artifacts are not built yet in this workspace.
