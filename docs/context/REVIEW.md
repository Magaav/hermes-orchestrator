# Context Review Protocol

Use this after context edits and before claiming the engine is good enough for a
future empty-context agent.

## Writer Pass

| Check | Action |
| --- | --- |
| Safety | Root guards are short, visible, and not contradicted downstream. |
| Routing | Every durable boundary has a read-first path. |
| Claims | Every success word maps to `verified` or is demoted. |
| Verification | Commands name exact path/artifact and proof boundary. |
| Next actions | One durable next action per active area. |
| Compression | Delete diary text, repeated philosophy, and stale debug history. |

## Watcher Pass

Attack the docs as if starting from zero context:

1. Can I find production backend and native URL in under 30 seconds?
2. Can I route `plugins/wasm-agent/public/app.js`, `native/windows/src/main.js`,
   and `native/android/app` to owners and read-first docs?
3. Can I tell verified from implemented-unverified?
4. Can I prove Windows installer status without trusting build success?
5. Can I find the exact next action for wasm-agent, Windows, and Android?
6. Can I identify generated/runtime state that should not be edited as source?

Demote or rewrite any ambiguous answer.

## Fresh-Agent Structured Test

Answer from docs only:

```json
{
  "production_backend": "https://wa.colmeio.com",
  "production_native_url": "https://wa.colmeio.com/home?native=electron",
  "localhost_allowed_in_production": false,
  "windows_installer_proof": [
    "cd native/windows/src && npm run verify:win-installer -- <final-nsis-installer>",
    "native/windows/release/VERIFY.json after extraction"
  ],
  "windows_login_persistence_proof": [
    "native\\windows\\scripts\\verify-installed-app.ps1 -Launch -InteractiveLogin",
    "Google login",
    "full close/reopen",
    "https://wa.colmeio.com/home?native=electron",
    "authCookie.hasWaUid: true",
    "durable cookie expiration metadata",
    "authenticated /auth/session"
  ],
  "area_owner_for_plugins_wasm_agent_public_app_js": "plugins/wasm-agent",
  "read_before_editing_plugins_wasm_agent_public_app_js": [
    "AGENTS.md",
    "README.md",
    "docs/context/MAP.md",
    "plugins/wasm-agent/AGENTS.md",
    "plugins/wasm-agent/README.md",
    "plugins/wasm-agent/DESIGN.md"
  ],
  "area_owner_for_native_windows_src_main_js": "native/windows",
  "read_before_editing_native_windows_src_main_js": [
    "AGENTS.md",
    "README.md",
    "docs/context/MAP.md",
    "native/AGENTS.md",
    "native/NATIVE_SHELL_CONTRACT.md",
    "native/windows/AGENTS.md",
    "native/windows/README.md"
  ],
  "area_owner_for_native_android_app": "native/android",
  "read_before_editing_native_android_app": [
    "AGENTS.md",
    "README.md",
    "docs/context/MAP.md",
    "native/AGENTS.md",
    "native/NATIVE_SHELL_CONTRACT.md",
    "native/android/AGENTS.md",
    "native/android/README.md"
  ],
  "status_of_windows_login_persistence": "implemented-unverified",
  "verify_android_apk": "apksigner verify --verbose native/android/release/WASM-Agent-arm64.apk; then run forbidden-origin scan and behavior-specific horc simulate android",
  "next_action_wasm_agent": "Continue Hermes Wake data/model loop: fetch/export latest dataset, train and verify build/voice/hermes.onnx, serve /native/android/hermes-wake-model/latest, then install through Android bridge.",
  "next_action_windows_native": "Run final NSIS/app.asar verification for the feed installer, then run real Windows installed-app login persistence proof.",
  "next_action_android_native": "Run current APK package proof with apksigner, then connected-device/emulator horc simulate android for the behavior being claimed."
}
```

## Scorecard

Score 0-5:

| Criterion | Target |
| --- | --- |
| Safety discoverability | 5 |
| Routing clarity | 5 |
| Claim honesty | 5 |
| Verification precision | 5 |
| Token efficiency | 5 |
| Fresh-agent readiness | 5 |
| Drift resistance | 4+ |
| Automation support | 4+ |

If any score is below 4, make the smallest context fix before ending.
