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

Build status: Android lane scaffolded; release APK artifacts are not built yet.
The current `MainActivity` validates candidate backend identity, then opens the
validated backend's `/home` route through AndroidX Browser Custom Tabs so Google
login runs in a browser-compatible session on the same origin as the PWA. It
keeps a WebView fallback for development and backup hosting: tap retries origin
selection or relaunches the Custom Tabs entrance, long-press opens the WebView
fallback after an origin validates, and hardware-keyboard `Ctrl+R` /
`Ctrl+Shift+R` reload the fallback WebView for HMR-style development sessions.
If production Android needs tighter install-surface integration, graduate this
lane from Custom Tabs to Trusted Web Activity while keeping the same validated
wasm-agent origin selection.

Local verification note: this workspace currently has no Java runtime, Gradle,
or Android SDK, so APK build verification has not run here.
