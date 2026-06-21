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
| Reply loop | Generic copilotability rule is discoverable: use live introspection/control before guessing, and end substantive replies with a concrete next-step phase. |
| Loop-aware doctrine | Meaningful native/bridge/wake/hot-op/rebuild-heavy work has Builder, Watcher, Gatekeeper, prime checkpoints, and static/runtime/behavioral evidence where possible. |
| Active state | `docs/context/ACTIVE_STATE.json` matches generated blocks and current next actions. |
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
7. Can I find the generic live-introspection rule and the reply next-step requirement without reading Android feature docs?
8. Does `python3 tools/context/check-context-sync.py` pass and write
   `reports/context/latest/context-sync-result.json`?
9. Do latest reports agree with `docs/context/ACTIVE_STATE.json`, and do I
   refuse stale next actions if narrative docs disagree?
10. Can I find the loop-aware report structure and tell whether evidence is
    static, runtime, behavioral, or missing?

Demote or rewrite any ambiguous answer.

## Loop-Aware Report Template

Use this compact template in task summaries, PR summaries, or significant
implementation reports for native, bridge, wake-word, hot-op, runtime-control,
release, or rebuild-heavy work.

```md
## Verified Loop-Aware Engineering Report

### Phase 0 - Architecture Loop Reflection
- Loop speed improvement considered:
- Decision:

### Phase 1 - Rebuild Avoidance
- Rebuild-heavy files touched:
- Hot-op/HMR/config/runtime alternative considered:
- Decision:
- If rebuild is required, why:

### Phase 2 - Observability
- Logs/counters/state available before validation:
- Missing observability:
- Added diagnostics:
- Human inspection required:

### Phase 3 - Rebuild Metadata
- Rebuild required:
- Command:
- Target:
- Duration:
- Was it avoidable:
- Validation command:

### Phase 4 - Post-Rebuild Loop Learning
- What made this iteration slow:
- What can make the next loop faster:
- Follow-up loop-shortening opportunity:

### Phase 5 - Nested Verification
#### Builder
- Claim:
- Patch/shortcut proposed:
- Expected effect:

#### Watcher
- Independent verification performed:
- Evidence:
- Contradictions or risks:

#### Gatekeeper
- Decision:
- Reason:
- Rollback needed:
- Human approval needed:

### Rule of Three / Prime Checkpoints
- Static evidence:
- Runtime evidence:
- Behavioral evidence:
- Prime checkpoints atomic, independent, falsifiable, observable, non-redundant:
```

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

Also read `docs/context/ACTIVE_STATE.json` before following narrative next
actions. If the checker fails, treat the failing line as suspect until it is
updated or explicitly marked historical/stale/superseded.

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
