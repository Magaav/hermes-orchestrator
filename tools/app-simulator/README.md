# WASM Agent App Simulator

`horc simulate` writes runtime evidence under `reports/sim/<platform>/latest/`.

- `web` drives the PWA/browser surface with Playwright. It is browser proof only.
- `android --emulator` attempts a cloud/CI Android runtime, checking KVM,
  nested virtualization, SDK/AVD state, and Docker viability.
- `android --device` installs and launches the real APK with `adb`, observes
  the UI with UIAutomator, captures screenshots/logcat/activity/window dumps,
  taps `Sign in with Google`, and can collect full OAuth proof when a human
  completes Google login during the configured wait window.
- `android --local-report <path>` validates a copied USB-phone report when
  Frontier cloud cannot see Victor's local device directly.
- `all` runs web, runs Android when a usable `adb device` exists, and leaves
  Windows pending until an installed-app simulator exists.

Simulator reports, not source/build success, are the runtime source of truth.
The loop is `boot -> observe -> act -> assert -> collect evidence -> score ->
report -> patch`.

## Authenticated Avatar-Chat Live Profiles

`node tools/app-simulator/avatar-paracelsus-live.js` preserves the two-turn
Paracelsus profile. For the one-turn V5 source-critique regression, run:

```bash
WASM_AGENT_SIM_LIVE_PROFILE=source-critique \
WASM_AGENT_SIM_LIVE_PROMPT='critisize meta-analysis widget inside realure space' \
WASM_AGENT_SIM_LIVE_FOLLOWUP_PROMPT='' \
node tools/app-simulator/avatar-paracelsus-live.js
```

The source profile writes `reports/sim/avatar-source-critique-live/latest/`
and requires V5 source evidence, search/read-only tool receipts, exact bounded
provider usage, no Hermes/runtime-inspect failure, and no changed files. This is
a local-development live-provider check: it incurs provider usage and creates
the deterministic simulator admin in the local auth database. It is not
production proof.

Useful Android overrides:

```bash
WASM_AGENT_SIM_ADB=/path/to/adb horc simulate android
WASM_AGENT_ANDROID_APK=/path/to/WASM-Agent-arm64.apk horc simulate android
WASM_AGENT_SIM_ROOT_DIR=/path/to/report-root horc simulate android
WASM_AGENT_SIM_ANDROID_PRESERVE_DATA=1 horc simulate android
WASM_AGENT_SIM_ANDROID_OAUTH_WAIT_MS=180000 horc simulate android --device
```

The installed Windows diagnostics console sets `WASM_AGENT_SIM_ROOT_DIR` to an
app-owned user-data diagnostics directory and `WASM_AGENT_ANDROID_APK` to the
APK bundled inside Electron resources before invoking the local horc runner.

Useful backend commands:

```bash
horc simulate android --emulator
horc simulate android --device --interactive-oauth
horc simulate android --local-report /path/to/result.json
```

The full Android OAuth pass requires all of these to be true: first tap opens
Google directly, no Android resolver chooser appears, no external
`wa.colmeio.com/native/android/auth/start` or browser/PWA `/home` handoff is
observed, OAuth completion returns through the native return path, the installed
app resumes, the WebView redeems the native auth session and becomes
authenticated, and cancel/retry remains usable.

The emulator backend is for CI/regression. Docker is attempted only when it can
actually access the needed virtualization/device support; missing KVM or nested
virtualization remains a real blocker. Real-device OAuth/app-link/chooser claims
require `--device` or a `--local-report` copied from a local-device run.

Classifier fixtures are available for simulator development only:

```bash
WASM_AGENT_SIM_ANDROID_FIXTURE=external-auth-start horc simulate android
WASM_AGENT_SIM_ANDROID_FIXTURE=google-oauth-direct horc simulate android
WASM_AGENT_SIM_ANDROID_FIXTURE=post-auth-pwa-redirect horc simulate android
WASM_AGENT_SIM_ANDROID_FIXTURE=stale-cancel-retry horc simulate android
```

The `external-auth-start` fixture must fail because it models the old Android
resolver chooser with Chrome/WASM Agent options and an external
`wa.colmeio.com/native/android/auth/start` intent.
The `post-auth-pwa-redirect` fixture must fail because it models the browser/PWA
redirect bug after Google authorization. The `stale-cancel-retry` fixture must
fail because it models the stuck `Opening Google sign-in...` retry state.

Post-auth OAuth reports include a machine-readable
`postAuthRedirectClassification` value. Current values are
`auth_completed_but_returned_to_browser`,
`auth_completed_but_landed_on_pwa_home`, `native_return_intent_missing`,
`native_return_received_but_session_missing`, and
`native_return_received_and_authenticated`. A passing Android OAuth proof
requires the final value, plus authenticated WebView/session evidence.
