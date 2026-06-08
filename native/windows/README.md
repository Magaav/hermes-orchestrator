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

`horc build all` runs the concrete Windows and Android lanes, then writes the
local native update feed to
`/local/plugins/wasm-agent/public/native/releases/latest.json`. Windows
artifacts are copied under
`/local/plugins/wasm-agent/public/native/releases/windows/` and are served as
`/native/releases/windows/<installer>`. The Go Native modal compares the
installed Electron metadata (`appVersion`, `installableVersion`, and `buildId`)
with that feed. Until electron-builder updater metadata is wired end to end,
Windows Update is a guided installer update: download the installer, verify the
SHA-256 from the feed, launch the installer, and do not silently overwrite the
running app.

Installed Windows verification:

1. Install the exact `release/WASM-Agent-Setup-x64-*.exe` artifact on Windows.
2. Start the installed `WASM Agent` app and wait until it loads the cloud PWA
   or shows native diagnostics.
3. Run the lifecycle verifier from PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File native\windows\scripts\verify-installed-app.ps1 -Launch -InteractiveLogin -Pause
```

Or double-click `native\windows\scripts\verify-installed-app.cmd`. The wrapper
keeps the console open so pass/fail output remains visible.

Android OAuth real-phone verification:

1. Open the installed `WASM Agent` Windows app.
2. Go to `Diagnostics`.
3. Select `Verify Android OAuth on real phone`.
4. Click `Start Android OAuth verification`.

This is the preferred path: `Open wasm-agent Windows app -> Diagnostics ->
Verify Android OAuth`. The app checks `adb version`, polls `adb devices`, tells
the user when the phone is missing, offline, or unauthorized, and only runs
the bundled local horc runner with fixed arguments
`simulate android --device --interactive-oauth` after a USB phone is in the
authorized `device` state. Production installs resolve
`resources/horc/horc-local.js` and the bundled Android APK from Electron
resources first; PATH `horc` is only a `WASM_AGENT_ALLOW_LOCAL_DEV=1` fallback.
Reports are written under the app-owned user-data diagnostics root, and the UI
links the latest `summary.md` or `result.json` when available. Do not claim
Android OAuth is fixed unless the local runner exits successfully and the latest
report status is PASS/PASSED.

Fallback scripts are available for users who cannot launch the Windows app:

```powershell
tools\windows\verify-android-oauth.ps1
```

```cmd
tools\windows\verify-android-oauth.cmd
```

The verifier launches or detects the installed app, confirms
`https://wa.colmeio.com/home?native=electron`, probes
`https://wa.colmeio.com/config.json`, detects an existing Google login or waits
for interactive login when `-InteractiveLogin` is passed, verifies
`authCookie.hasWaUid: true`, verifies authenticated `/auth/session`, fully
closes the app, reopens from the installed exe, verifies the session survives,
and writes `installed-app-VERIFY-*.json`. Failures are classified as one of:
`cookie missing`, `cookie wrong domain`, `cookie wrong partition`,
`frontend bootstrap crash`, `backend/config discovery failure`,
`Google redirect/code redemption failure`, `cloud asset stale/cache issue`,
`native shell issue`, or `installer packaging issue`.

Packaged artifact verification:

```bash
cd native/windows/src
npm run verify:win-installer
```

This extracts the final NSIS installer, inspects the installed `app.asar`,
confirms cloud-only URL defaults, patched `app.js` and `dev-hmr.js`, the
boot-time fatal trap, icon resources, and native/preload bridge compatibility,
then writes `native/windows/release/VERIFY.json`. Source tests and
`win-unpacked` are useful early signals but are not release proof by
themselves.

## Frontier Operator Commands

The cloud backend exposes a gated Frontier surface:

- `GET /native/frontier/status`
- `POST /native/frontier/command`

Authorization requires an admin session, localhost operator access, or
`X-Wasm-Agent-Native-Control-Key: $WASM_AGENT_NATIVE_CONTROL_KEY`. Calls without
that gate return HTTP 403. A successful command queue returns HTTP 200 with a
structured JSON body and `queuedCount`.

Supported commands are `status`, `screenshot`, `collect_logs`,
`collect_adb_diagnostics`, `read_latest_android_report`,
`verify_android_oauth`, `reload`, `reload_ignore_cache`, `clear_cache`,
`restart_app`, `verify_session`, `verify_installed_app`, `open_devtools`, and
`export_diagnostics`. Unknown commands are refused. `clear_cache` and
`restart_app` require
`enable_destructive: true` or `X-Wasm-Agent-Destructive-Allowed: 1`.

One-device reload:

```bash
curl -X POST "https://wa.colmeio.com/native/frontier/command" \
  -H "Content-Type: application/json" \
  -H "X-Wasm-Agent-Native-Control-Key: $WASM_AGENT_NATIVE_CONTROL_KEY" \
  --data '{"device_id":"<device-id>","command":"reload_ignore_cache","reason":"verify fresh cloud build"}'
```

Test cohort reload is intentionally explicit: inspect
`/native/control/clients`, filter the desired test devices, then pass
`device_ids: [...]` to `/native/frontier/command`, or pass `allow_cohort: true`
with a narrow `cohort` filter such as `build_id` or `route_contains`. Do not add
or use a global unauthenticated reload endpoint.

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
changes can be picked up without reinstalling the desktop app. Remote HTTPS
Google login uses the registered browser redirect flow; the JS credential
callback is reserved for the bundled `wasm-agent://` fallback only. Google popup
URLs are allowed as popup windows instead of replacing the primary app window,
same-origin auth completions are routed back into the primary window, and the
auth-code preloader waits briefly for the durable `wa_uid` cookie before
flushing Electron's cookie store after redemption so restart persistence can be
verified. The shell strips Electron-specific user agent markers before loading
the PWA so the installed app behaves like a browser PWA for login.
The native shell now writes renderer auth diagnostics, runtime diagnostics, and
native upload attempts, and the source includes a bounded native control poller.
Runtime and status diagnostics include `authCookie.hasWaUid`, cookie session and
expiration metadata, domain/path, current route, and an Electron-session-backed
`/auth/session` status for close/reopen verification.
The cloud PWA must also preserve Electron's read-only preload globals during
bootstrap. The app-owned HMR deferral hook lives at `__wasmAgentAppDevHmr`, while
the preload-provided native reload bridge remains available for fallback HMR
reloads.
After installing the verified `win-x64-20260605T115715Z` artifact, the app can
receive server-queued diagnostics commands from `/native/control/poll` and
report command results to `/native/control/result`, making client-log fetches
possible without asking the Windows user to manually refresh.
The Windows installer also packages a local Android OAuth verifier under
Electron resources: `horc/horc-local.js`, `horc/app-simulator/`, and the current
`android/WASM-Agent-arm64.apk` plus metadata sidecar. The installed app uses
that local verifier for `verify_android_oauth`, so cloud Frontier can queue the
operation while ADB/USB access and OAuth proof execute on the user's Windows
machine.
On Linux build hosts, `scripts/prepare-native-assets.js` prepares a local NSIS
shim around system `makensis` for the Wine/electron-builder path. On Linux
aarch64, `horc build` prefers Docker amd64 emulation over direct Wine.

Durable Next Step: Install
`/local/native/windows/release/WASM-Agent-Setup-x64-0.1.0-20260606T193120Z.exe`
on the Windows host, then queue `verify_android_oauth` through Frontier or click
`Diagnostics -> Verify Android OAuth on real phone`. The currently connected
Windows app is still `win-x64-20260606T191516Z`; it resolves the bundled runner
but reports PENDING because the bundled simulator misclassified a real ADB phone
line containing `transport_id` as an emulator. Do not claim Android OAuth is
fixed until the installed `win-x64-20260606T193120Z` app resolves the bundled
local horc runner, detects the authorized USB phone as a device, runs the local
simulator, uploads/saves the generated report, and the report status is
PASS/PASSED.
