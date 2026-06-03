# wasm-agent Linux Native

This lane owns the Linux desktop body for wasm-agent.

Target output:

- `release/WASM-Agent.AppImage`
- `release/WASM-Agent-x64.deb` / `release/WASM-Agent-arm64.deb`
- `release/WASM-Agent-x64.rpm` / `release/WASM-Agent-arm64.rpm`

Contract:

- Follows the shared native shell contract in `../NATIVE_SHELL_CONTRACT.md`.
- Uses the shared Electron host from `../windows/src` until a Linux-specific
  shell is needed.
- Loads a validated backend PWA `/home` origin for Google login and HMR, with
  bundled app-shell assets as fallback/setup only.

Build:

```bash
cd native/windows/src
npm install
npm run build:linux:x64
npm run build:linux:arm64
```

Build status: shared Electron Linux `AppImage` packaging lane is configured.
`npm run pack:linux:arm64` has produced an unpacked Electron app at
`native/windows/release/linux-arm64-unpacked`; release AppImage artifacts are not
built yet in this workspace.
