# WASM Agent Native Shell Contract

This contract applies to every native platform lane: Windows, Android, macOS,
and Linux.

## Entrance

Native shells must prefer the live PWA after validating backend identity:

1. Build a candidate origin list from packaged defaults, persisted user config,
   environment/platform settings, and local-development fallbacks.
2. Probe candidates with `/config.json`, `/health`, and `/healthz`.
3. Accept only origins that identify as `appId`, `service`, or `name`
   `wasm-agent`.
4. Reject origins that identify as another product, including Colmeio Admin, or
   expose a server-configuration failure shell such as `GOOGLE_LOGIN_CLIENT_ID`.
5. Open the selected origin's real `/home` URL as the main app entrance.
6. Use bundled app-shell assets only as fallback/setup when no backend validates
   or the remote PWA cannot load.

## Google Login

Google login must run on the validated backend web origin, not on a custom
native protocol such as `wasm-agent://app`. That keeps the Electron/WebView/TWA
experience aligned with the browser PWA origin and the Google Cloud OAuth
authorized origin/callback configuration.

When a web-based native shell is hosting the validated PWA origin, Google auth
navigation and popup URLs must stay inside that native web session instead of
being opened in an unrelated external browser window. Otherwise the login
callback can succeed in the wrong cookie jar and the native app remains signed
out. Desktop shells should also avoid advertising an Electron-specific user
agent to Google auth pages when they are acting as a browser-compatible PWA host.

If a platform cannot safely run Google login in its embedded web view, it must
use a browser-compatible native path such as Trusted Web Activity, Custom Tabs,
external browser handoff, or loopback/pairing. It must not pretend the bundled
fallback shell can perform the normal PWA Google login.

## Live Evolution

Native shells should be installed rarely. Product UI, feature modules, and PWA
runtime changes should flow from the validated backend:

- PWA HMR comes from `/modules/hmr/events`.
- CSS-only changes may refresh stylesheets in place.
- JS, HTML, manifest, or backend changes may reload the page.
- Native shells should expose browser-like refresh controls where the platform
  supports it, such as soft reload and hard reload.
- Native shell, installer, executable icon, OS integration, preload, protocol,
  foreground service, tray/menu bar, and standby changes still require a native
  rebuild/reinstall.

## Diagnostics

Every implemented native shell should log or expose:

- Packaged app root or bundle id.
- Start URL.
- UI source: `remote-pwa`, bundled assets, or source-tree/dev assets.
- Candidate origins considered.
- Final selected origin.
- Current route.
- Config source: bundled native config or validated remote server config.
- Reason when a candidate origin is rejected.

Native shells that expose host diagnostics must keep the bridge operation-based
and platform-gated. The Windows Android OAuth verifier is allowed only in the
native Windows Electron shell, resolves its bundled local horc runner and APK
from app resources before any development fallback, and runs fixed simulator
arguments only after `adb devices` reports an authorized USB phone. Browser,
PWA, and cloud-only modes must not receive arbitrary local command execution.

## Platform Status

- Windows: Electron implementation exists and follows this contract.
- Android: Custom Tabs entrance exists for browser-compatible Google login after
  backend identity validation, with a WebView fallback for development/backup
  hosting. Release APKs are cloud-only and package `https://wa.colmeio.com` as
  the candidate backend; emulator/local candidates are debug-only. Graduate to
  Trusted Web Activity when production install-surface integration needs it.
- macOS: shared Electron packaging lane is configured; release artifact
  verification still needs a macOS-capable builder.
- Linux: shared Electron implementation exists and an ARM64 unpacked package has
  been verified from this workspace.
