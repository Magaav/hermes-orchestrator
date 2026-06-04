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

```bash
horc build
```

Or run the underlying release script directly:

```bash
cd native/windows/src
npm run release:win:x64:prod
```

Native Windows is the preferred and trusted production build host. Linux x86_64
with Wine/NSIS is a supported CI cross-build path, but the resulting installer
must pass a real Windows smoke test before release. Linux aarch64 uses a Docker
`--platform linux/amd64` Wine builder by default and is an experimental
cross-build path that also requires a Windows smoke test. Linux aarch64 direct
Wine is debug-only and requires `HORC_ALLOW_CROSS_WIN_BUILD=1`.

On Linux aarch64, `horc build` checks whether Docker can execute
`linux/amd64` containers. If QEMU/binfmt is missing and automatic repair is not
disabled, it runs:

```bash
docker run --privileged --rm tonistiigi/binfmt --install amd64
```

Then it re-tests `docker run --rm --platform linux/amd64 alpine:3.20 uname -m`
and proceeds only when the result is `x86_64`. Use `horc build doctor` to print
the host/build readiness report without starting the installer build.
If the amd64 Docker builder itself fails under QEMU, `horc build` in `auto`
mode can fall back to a Linux ARM64 native NSIS build with Windows executable
resource editing disabled. That fallback is labeled
`linux-arm64-native-nsis-no-rcedit` and requires a Windows smoke test.

For repeated Linux ARM64 release builds, prepare the reusable amd64 Wine builder
once:

```bash
horc build prepare-docker
```

That creates `horc/electron-builder-wine-nsis:jammy` with NSIS and `unar`
preinstalled. Future `horc build` runs auto-use the local prepared image when
`HORC_DOCKER_IMAGE` is unset, so the disposable build container does not fetch
Ubuntu package indexes and install NSIS on every release attempt.

`horc build` writes `/local/native/windows/release/horc-build-manifest.json`
with the host OS/arch, target, build mode, installer path, app.asar path,
`trusted_production`, and `requires_windows_smoke_test`.

Installed Windows verification:

1. Install the exact `release/WASM-Agent-Setup-x64-*.exe` artifact on Windows.
2. Start the installed `WASM Agent` app and wait until it loads the cloud PWA
   or shows native diagnostics.
3. Run the verifier from PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File native\windows\scripts\verify-installed-app.ps1 -Pause
```

Or double-click `native\windows\scripts\verify-installed-app.cmd`. The wrapper
keeps the console open so pass/fail output remains visible.

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
The native shell now writes renderer auth diagnostics, runtime diagnostics, and
native upload attempts, and the source includes a bounded native control poller.
After the next installer build/install, the app can receive server-queued
diagnostics commands from `/native/control/poll` and report command results to
`/native/control/result`, making client-log fetches possible without asking the
Windows user to manually refresh.
On Linux build hosts, `scripts/prepare-native-assets.js` prepares a local NSIS
shim around system `makensis` for the Wine/electron-builder path. On Linux
aarch64, `horc build` prefers Docker amd64 emulation over direct Wine.

Durable Next Step: Build and install the next Windows artifact containing the
native control poller, then from localhost queue a `status` or
`upload_diagnostics` command through `/native/control/command` for the installed
device and verify the result through `/native/control/clients` and
`/native/diagnostics/latest`.
