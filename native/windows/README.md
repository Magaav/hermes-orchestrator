# wasm-agent Windows Native

This lane owns the Windows desktop body for wasm-agent.

Target output:

- `release/WASM-Agent-Setup-x64.exe` or `release/WASM-Agent-x64.msi`
- `release/WASM-Agent-Setup-arm64.exe` or `release/WASM-Agent-arm64.msi`

Contract:

- Follows the shared native shell contract in `../NATIVE_SHELL_CONTRACT.md`.
- Runs as a real desktop app process, not Edge or Chrome app mode.
- Electron is acceptable for v1 when packaged as `WASM Agent.exe`.
- Stores persistent local config outside the installer artifact.
- Registers the current account/device after launch and receives a pairing or device token at activation time.
- Emits `device.register`, `device.status`, `device.heartbeat`, `native.capabilities`, and `native.install_status`.
- Connects to wasm-agent through the native bridge; downloadable installers must not contain account secrets or device tokens.

Build:

```powershell
cd native/windows
./scripts/build-installer.ps1
```

On non-Windows build hosts with PowerShell unavailable, run the equivalent from
`native/windows/src`:

```bash
npm install
npm run build:win:x64
```

Build status: Electron plus Windows x64 NSIS installer lane is present. The
primary artifact is built by electron-builder, matching the Space Agent-style
desktop packaging direction. The installer embeds the packaged Electron app,
creates Start Menu/Desktop shortcuts, uses a bundled icon generated from the PWA
`public/icons/icon.svg` for the window and shortcuts, persists config under the
Electron user-data directory, writes shortcut creation diagnostics to
`%LOCALAPPDATA%\\WASM Agent Native\\shortcut-report.txt`, and leaves
account/device tokens to runtime pairing instead of embedding secrets in the
artifact. On launch, the desktop app clears stale service-worker and Cache
Storage data, probes configured backend candidates in parallel through
`/config.json`, prefers a candidate whose config reports
`auth.googleClientIdConfigured`, and opens the validated backend's real PWA
`/home?native=electron` URL. The packaged fallback is only a backend-missing
screen; it must not run the real app shell or Google login from bundled assets.
Startup diagnostics log the resolved backend, Google config state, final loaded
URL, app root, UI source, current route, candidate origins, and selected backend
origin. Origins that expose the old Colmeio Admin identity or unavailable/invalid
`/config.json` are rejected instead of being used as the native backend. In
remote-PWA mode, normal PWA dev-HMR
comes from the backend through `/modules/hmr/events`; the native shell adds
browser-like `Ctrl+R` refresh and `Ctrl+Shift+R` hard refresh so UI/module
changes can be picked up without reinstalling the desktop app. Google auth URLs
remain inside the Electron session, and the shell strips Electron-specific user
agent markers before loading the PWA so the installed app behaves like a browser
PWA for login.
On Linux/aarch64 build hosts, `scripts/prepare-native-assets.js` prepares a
local NSIS shim around system `makensis` so electron-builder can still produce
the Windows x64 NSIS artifact.
