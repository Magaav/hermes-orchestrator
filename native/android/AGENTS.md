# Android Native Context Contract

## Purpose

`native/android` owns the Android APK shell, WebView/native bridge, foreground
service, voice wake pipeline, sideload/update metadata, and Android OAuth proof
lane for WASM Agent Native.

## Ownership

- Owns Kotlin app code, Gradle build, Android resources/icons, release scripts,
  APK verification, and Android simulator/device evidence.
- Shared PWA/product behavior remains in `/local/plugins/wasm-agent`.
- Cross-platform native rules come from `/local/native/AGENTS.md` and
  `/local/native/NATIVE_SHELL_CONTRACT.md`.

## Local Contracts

- Production APKs are cloud-only and may package only `https://wa.colmeio.com`
  as the production backend candidate.
- Localhost, emulator, and debug backend candidates are debug-only and must not
  appear in release APKs.
- APKs must not contain account secrets or pre-minted device tokens.
- Google/OAuth success requires return to the installed app and authenticated
  WebView/session evidence, not just a browser/PWA callback.
- Voice wake model iteration should prefer dataset export, model training, and
  model download/install over rebuilding the APK for every model.

## Work Guidance

- Before editing, read `/local/AGENTS.md`, `/local/README.md`,
  `/local/docs/context/MAP.md`, `/local/native/AGENTS.md`,
  `/local/native/NATIVE_SHELL_CONTRACT.md`, this file, and `README.md`.
- Use the repo-wide Verified Loop-Aware Engineering doctrine for Android
  native, wake-word, bridge, foreground-service, model, and rebuild-heavy work:
  separate Builder intent, Watcher evidence, and Gatekeeper decision; prefer
  static, runtime, and behavioral evidence when possible.
- First reasoning pass: ask whether a small architecture change would shorten
  the Android iteration loop, such as moving behavior behind server/native
  control policy, downloaded model/runtime metadata, hot-op, HMR, or another
  live-updatable seam instead of hard-coding another APK rebuild path.
- Feature architecture gate: before implementing any Android feature, classify
  each behavior as either `native primitive required` or
  `live policy/downloaded operation capable`. Put only stable OS/hardware
  primitives, permissions, services, native libraries, package identity, and
  security bootstrap in compiled Kotlin when possible. Put tunable sequencing,
  thresholds, engine selection, routing, retry order, labels, grammar, model
  metadata, diagnostics shape, and command mapping behind live policy,
  downloaded operations/runtime, server config, or PWA code.
- If compiled Kotlin is required for a feature whose behavior is likely to
  change during proof, first expose the smallest stable configurable primitive
  and diagnostic envelope that lets future behavior changes happen through
  native-control policy or downloaded operations. Example: expose bounded audio
  capture plus configurable transcript attempt plans instead of hard-coding one
  SpeechRecognizer/Vosk order.
- Treat a feature implementation that hard-codes tunable behavior in Kotlin
  without a live-plan boundary as a loop-time regression unless the Builder
  report explicitly proves the behavior cannot be represented safely through
  existing live policy, downloaded runtime/hot-op, model metadata, or server/PWA
  routing.
- Before patching any component that appears to require a rebuild, explicitly
  check whether the same outcome can be reached through live policy, native
  control, server/PWA HMR, downloaded runtime/hot-op, model install, diagnostics
  upload, or another faster loop. Rebuild only after that route is ruled out or
  is more complex/risky than the native change.
- Before every Android rebuild, pause for an observability/accessibility pass:
  identify whether a watcher, flattened state field, diagnostic event, command
  result, or script would make the next runtime proof easier and reduce another
  rebuild cycle. Add the smallest useful observability improvement before the
  rebuild when it materially shortens the loop.
- After every Android rebuild, do a speed/reflection pass: inspect benchmark
  output, selected build mode, cache reuse, package proof, and runtime access.
  Decide whether the build loop has another practical optimization or is already
  limited by required update identity, package signing, APK size, device install,
  or runtime proof.
- Keep UI/module evolution server-driven through the validated backend where
  possible; rebuild only for OS shell, permissions, service, bridge, icon, or
  bundled native capability changes.
- Preserve fitted system-window behavior so content does not render behind the
  Android status or navigation bars.

## Verification

- Build/release: `HORC_ANDROID_BUILD_MODE=auto horc build android-apk`.
- APK proof: `apksigner verify --verbose <apk>` plus production string scan for
  forbidden localhost/dev origins.
- Runtime proof: `horc simulate android` with an authorized device/emulator, or
  `horc simulate android --local-report <path>` for copied evidence.
- Icon proof after artwork changes:
  `python3 native/android/scripts/verify-launcher-icon.py`.

## Child Context Index

- `README.md`: build lane, release metadata, OAuth proof expectations, current
  verified APK evidence, and durable next step.
- `app/`: Kotlin application source, resources, tests, and bundled assets.
- `scripts/`: release, icon generation, and APK inspection helpers.
- `release/`: generated APK artifacts and release manifests.
