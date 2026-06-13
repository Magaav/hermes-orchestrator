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
