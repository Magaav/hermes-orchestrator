# wasm-agent Android Native

This lane owns the Android mobile and standby body for wasm-agent.

Target output:

- `release/WASM-Agent-arm64.apk`
- `release/WASM-Agent-universal.apk`
- AAB/signing lane later.

Contract:

- Follows the shared native shell contract in `../NATIVE_SHELL_CONTRACT.md`.
- Kotlin Android app project preferred.
- Includes foreground service, microphone permission, persistent notification, push-to-talk/transcription, and native bridge foundations.
- Registers account/device after launch and receives a pairing or device token at activation time.
- Emits `device.status`, `voice.partial_transcript`, `voice.final_transcript`, `voice.error`, `native.capabilities`, and `native.install_status`.
- Downloadable APKs must not contain account secrets or pre-minted device tokens.
- Uses the same native shell evolution model as desktop: validate a candidate
  backend as `appId`/`service` `wasm-agent`, then load that backend's real PWA
  `/home` URL so UI/module/HMR changes come from the server without reinstalling
  the APK. The bundled/native body remains responsible for OS capabilities such
  as foreground service, standby, microphone, and device registration.

Build status: Android APK build lane is present; release artifacts are built by
`horc build android-apk` and served by Go Native when present under `release/`.
The current `MainActivity` validates candidate backend identity, then loads the
validated backend's `/home` route inside the installed app's WebView so Android
opens as a native app surface instead of leaving the activity on a browser-host
placeholder. Release APKs are cloud-only and carry only `https://wa.colmeio.com`
as the packaged candidate. Debug builds can add emulator/local development
candidates through BuildConfig, but localhost remains forbidden in production
APKs.

Launcher icon ownership: Android uses the same WA monogram artwork as the PWA
and Electron app. The source of truth is
`plugins/wasm-agent/public/icons/icon.svg`, which is byte-identical to
`native/windows/src/build/icon.svg`. Android keeps density-specific launcher
PNGs rendered from that shared SVG under `app/src/main/res/drawable-*` and
`app/src/main/res/mipmap-*`; `mipmap-anydpi-v26/ic_launcher*.xml` wraps those
PNGs as adaptive icons. After icon changes, regenerate with
`python3 native/android/scripts/generate-launcher-icons.py` in a Python
environment that has CairoSVG, then run
`python3 native/android/scripts/verify-launcher-icon.py` from `/local`.

Build:

```bash
horc build android-apk
```

Or run the underlying release script directly:

```bash
cd native/android
node scripts/release-android.js
```

The release script reuses Gradle caches and does not clean by default. It
generates a local sideload signing key under `native/android/signing/` when no
external signing key is provided, builds `:app:assembleRelease`, verifies the APK
with `apksigner`, rejects production APKs that contain localhost backend
literals, then promotes the signed APK to:

- `release/WASM-Agent-universal.apk`
- `release/WASM-Agent-arm64.apk`

Each promoted APK receives a `.native-defaults.json` sidecar, and
`release/release-manifest.json` records the build id, version, SHA-256, size,
host, signing level, and cloud-only backend policy. `/native/resolve` and
`/native/download` use these release files for the Home `Go Native` Android APK
download.

Optional production signing environment:

```bash
export WASM_AGENT_ANDROID_KEYSTORE=/secure/path/wasm-agent-release.jks
export WASM_AGENT_ANDROID_KEYSTORE_PASSWORD=...
export WASM_AGENT_ANDROID_KEY_ALIAS=...
export WASM_AGENT_ANDROID_KEY_PASSWORD=...
horc build android-apk
```

The APK uses WebView cookies/storage and keeps hardware-keyboard `Ctrl+R` /
`Ctrl+Shift+R` reload controls for HMR-style development sessions. Google login
uses a narrow Android bridge: the WebView remains the installed app surface, but
if Google Identity fails to load inside WebView it opens the same `/home` origin
in the system browser for sign-in, then polls a short-lived
`/native/android/auth/poll` handoff and redeems the returned `auth_code` back in
the WebView.

The native Activity keeps the WebView inside Android's fitted system-window
area. It does not opt into edge-to-edge status or navigation bar drawing, so the
PWA's visual viewport starts below the status/battery bar and ends above the OS
navigation buttons instead of rendering content behind those bars.

Local verification evidence from this workspace:

- Built through `horc build android-apk` on 2026-06-06.
- Build id: `android-universal-20260606T222747Z`.
- APK SHA-256:
  `5b956284bd2a300593e725a17e31b7eeb029fdb956dc05f2dae511b4e71409e0`.
- `apksigner verify --verbose` passed with APK Signature Scheme v2.
- Production string scan found `https://wa.colmeio.com` and no
  `127.0.0.1:8877`, `localhost:8877`, `0.0.0.0:8877`, or `10.0.2.2:8877`.
- Android auth-code redemption is gated on the matching
  `wasm-agent://android-auth-return` intent reaching `MainActivity`; a completed
  Google callback that strands the user in Chrome/PWA is classified as
  `auth_completed_but_landed_on_pwa_home`, not success.
- Local release metadata is written to
  `native/android/release/release-manifest.json`; verify deployment separately
  before claiming `/native/download` serves this exact build.

Durable Next Step: connect a real Android device/emulator in `adb device` state
and run `horc simulate android` against
`/local/native/android/release/WASM-Agent-arm64.apk`. Use
`reports/sim/android/latest/result.json` and `summary.md` as the Android APK
source of truth: the installed app must render `https://wa.colmeio.com/home`,
the app content must fit above Android's OS navigation buttons and below the
status/battery bar,
the first Google sign-in tap must open Google/account evidence directly with no
Android resolver chooser or external
`wa.colmeio.com/native/android/auth/start` handoff, cancel/return must make the
button retryable instead of leaving `Opening Google sign-in...`, and the report
must include screenshots/logcat/UIAutomator/activity/window evidence. If it
stalls, copy the `android_auth_session` value from the WebView URL and inspect
`/native/android/auth/debug?session=<id>`; it reports started, callback,
completed, delivered, redeemed, expired, and last error without exposing tokens
or auth codes.
