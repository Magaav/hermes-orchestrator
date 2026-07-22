# Verification Commands

Run the smallest command that proves the claim being made. Record proof paths in
`CLAIMS.md` or the nearest owner README.

## Context

```bash
python3 tools/context/check-context-sync.py
python3 tools/context/check-harness-promises.py
python3 tools/context/check-monolith-growth.py
python3 tools/context/watch-loop-copilot.py
make context-check
rg -n "127\\.0\\.0\\.1:8877|localhost:8877|0\\.0\\.0\\.0:8877|10\\.0\\.2\\.2:8877|win-unpacked|Durable Next Step|current next action|TODO|FIXME|proposal|future|verified|unverified|stale|unknown|fixed|done|complete" \
  README.md AGENTS.md docs/context docs/README.md docs/roadmap plugins/wasm-agent native scripts/public
```

Expected use: inspect every match for unsafe production claims, stale next
actions, proofless success language, and roadmap/current blending.

The context sync checker reads `docs/context/ACTIVE_STATE.json`, scans owned
durable docs, verifies the current hot-shell proof order, and writes:

```text
reports/context/latest/context-sync-result.json
```

The harness promise registry validator reads
`docs/context/HARNESS_PROMISES.json` and writes:

```text
reports/context/latest/harness-promises-result.json
```

The monolith growth guard checks the current diff for frozen-monolith growth,
new route branches in `static_server.py`, and oversized new source files. It
writes:

```text
reports/context/latest/monolith-growth-result.json
```

The loop copilot watcher reads cheap local process, git, and harness evidence
and writes:

```text
reports/context/latest/loop-copilot-signals.json
reports/context/latest/loop-copilot-signals.jsonl
```

It is a checkpoint aid only. A pass means no blocker was emitted by this cheap
scan; it does not prove runtime behavior, installed packages, production auth,
or Android wake success.

Use conservative generated-block repair only when the durable active state
changes:

```bash
python3 tools/context/check-context-sync.py --fix
make context-fix
```

## Fresh-Agent Structured Test

Use `REVIEW.md` to answer the JSON test from docs only. If any field requires
guessing, update the route map, claim registry, or nearest child docs.

## Harness Promises

Before repeated manual investigation, run or compose the smallest promise from
`docs/context/HARNESS_PROMISES.json`. If no promise exists, use the Harness
Factory Reflection in `HARNESS.md` and harvest useful repeated inference after
the loop.

```bash
python3 tools/context/check-harness-promises.py
python3 tools/context/check-monolith-growth.py
python3 tools/context/prove-master-frontier-production.py
```

The command emits one `MF_PROOF/1` JSON summary capped at 2048 UTF-8 bytes.
Full per-command stdout/stderr is pull-only in:

```text
reports/context/latest/master-frontier-production-proof.json
```

Expected report:

```text
reports/context/latest/harness-promises-result.json
reports/context/latest/monolith-growth-result.json
reports/context/latest/master-frontier-production-proof.json
```

The registry validator proves only registry structure. The Master:frontier
production gate composes the focused planner, envelope, dispatch, protocol,
route-contract, code-memory, provider-proxy, and smoke checks; it proves the
static/behavioral contract layer only. Run
`python3 tools/context/prove-master-frontier-production.py --include-runtime`
before claiming live node-brain availability.

The automatic watcher replays compact route/tool contract quests without
provider calls. Static fixtures can promote only through L4. Independently
produced avatar proof may promote to L5, and fresh avatar plus node proof may
promote to L6. The watcher must not write source fixtures, manufacture edit
receipts, or promote a quest it authored during the same run:

```bash
python3 tools/context/watch-master-frontier-loop.py
python3 tools/context/watch-master-frontier-loop.py --require-proof-artifacts
python3 tools/context/run-master-frontier-autonomy-loop.py
```

## Loop-Aware Evidence

For meaningful native, bridge, wake-word, hot-op, runtime-control, release, or
rebuild-heavy work, verification should include prime checkpoints and, whenever
possible, the 3 x evidence triangle.

Prime checkpoint quality:

| Requirement | Meaning |
| --- | --- |
| Atomic | Checks one clear behavior or fact. |
| Independent | Does not depend only on the Builder's claim. |
| Falsifiable | Can produce a pass/fail or matching/missing result. |
| Observable | Has command output, report path, log, counter, runtime state, or diagnostic evidence. |
| Non-redundant | Does not duplicate another checkpoint under a different name. |

Preferred evidence triangle:

| Evidence class | Examples |
| --- | --- |
| Static | Type check, lint, unit test, build output, syntax check, source/feed contract test. |
| Runtime | App/native status, service state, bridge status, diagnostics, permissions, model path/SHA, counters, recent events, ADB/logcat. |
| Behavioral | Simulator pass, hot-op result, UI flow, wake simulation, command execution, replay, regression check. |

Do not use vague checkpoints such as "looks good", "probably works", "agent
verified it", or "it compiled, so it works". Build success is static evidence
only; it is not runtime proof.

## wasm-agent

```bash
node plugins/wasm-agent/tests/android_lite_performance_budget.test.js
horc simulate web
horc simulate web --avatar-quest
/local/plugins/wasm-agent/scripts/doctor.sh
```

Use focused tests under `plugins/wasm-agent/tests` when touching one behavior.
`horc simulate web` proves browser/PWA behavior only.
`horc simulate web --avatar-quest` proves a two-turn avatar-chat UI quest
against an isolated local backend and provider stub: route-before-provider on
each turn, objective-only `route_contract_missing`, exact token ledger rows by
quest/turn/provider call, quest totals equal summed turn totals, no broad
Hermes fallback, and contained timeline/token-ledger UI.

Native evolution source/feed contract:

```bash
node plugins/wasm-agent/tests/native_release_feed.test.js
cd native/windows/src && npm run test:windows-hot-ops
python3 -m py_compile tools/windows/prove-hot-shell.py tools/windows/hot_shell_common.py tools/doctor/wasm-agent-doctor.py
```

These commands prove release-feed/runtime/hot-op shape and source guards only.
Installed proof still requires a shell to report active downloaded runtime and
hot-op bundle IDs/SHAs through `prove-hot-shell.py` or the doctor.

## Windows Native

```bash
cd native/windows/src
npm run verify:win-installer -- /local/native/windows/release/WASM-Agent-Setup-x64-0.1.0-20260613T003310Z.exe
```

Writes `native/windows/release/VERIFY.json` when final NSIS extraction and
installed `app.asar` checks pass. This is still not installed-app login proof.

Package verification is not feed publication. After `VERIFY.json` is written,
the normal release path must prove the Windows feed before Go Native / Check
Update can see the build:

```bash
python3 tools/windows/check-windows-release-feed.py
```

Expected report:

```text
reports/windows/latest/windows-release-feed-check.json
```

The guard compares the verified installer buildId/SHA, feed buildId/SHA,
installer filename/URL, and local published installer bytes. Same semver with a
newer Windows `buildId` must be update available; an older feed build must fail
instead of letting Check Update report up to date.

Installed runtime proof must run on Windows:

```powershell
native\windows\scripts\verify-installed-app.ps1 -Launch -InteractiveLogin
```

Required installed-app evidence: Google login, full close/reopen,
`https://wa.colmeio.com/home?native=electron`, `authCookie.hasWaUid: true`,
durable cookie expiration metadata, and authenticated `/auth/session`.

## Android Native

Rebuild UX regression gate:

```bash
python3 tools/android/check-android-ux-rebuild-gate.py
```

Expected report:

```text
reports/android/rebuild-guard/latest/android-ux-rebuild-gate.json
```

This proves Gradle rebuilds run the Android UX performance regression guard
before build work proceeds. It also checks shell-v2 size/startup budgets,
Activity launch-time budget wiring, deterministic skip-build/feed semantics,
strict install acceptance, and the explicit shell-v2 proof path. It is still
not installed runtime proof.

```bash
apksigner verify --verbose native/android/release/WASM-Agent-arm64.apk
sha256sum native/android/release/WASM-Agent-arm64.apk
unzip -p native/android/release/WASM-Agent-arm64.apk assets/wa.colmeio.com.android-native-shell.txt
```

Forbidden production literals to scan when tooling supports it:

```text
127.0.0.1:8877
localhost:8877
0.0.0.0:8877
10.0.2.2:8877
```

Runtime proof:

```bash
horc simulate android
horc simulate android --local-report <path>
python3 tools/android/prove-android-native-ux-release-loop.py
python3 tools/android/prove-android-native-ux-release-loop.py --shell-v2
```

The report must name the behavior proven. Voice wake PASS is not OAuth PASS.
The deterministic release loop writes:

```text
reports/android/responsiveness/latest-android-native-ux-release-loop.json
reports/android/responsiveness/*-android-native-ux-release-loop.json
```

Use `--skip-build` only when the promoted APK/feed already contains the source
change under test. It reuses the existing feed unless `--publish-feed` is
explicit.

The release loop install path uses the Android UI input hot-op `install_apk`
action, not the legacy voice-tuning reinstall command that force-stops and
monkey-launches the default Activity. `--shell-v2` intentionally stops after
build/install by default so the harness does not perform a second ADB
relaunch/input pass.
Use `--run-shell-v2-adb-proof` only when that explicit component launch is
acceptable; the opt-in path is launch-only and avoids force-stop, synthetic
swipe, and gfxinfo probes.

### Copilotability / Live Introspection

Agents should use available live runtime channels before asking the user to
describe app state or before proposing rebuild/reinstall work. Prefer compact
state snapshots, capability reports, visible-action/UI summaries, diagnostics,
and live policy/config/control commands. Heavy outputs such as screenshots, log
bundles, full diagnostics, or UI trees must be explicit, bounded, redacted, and
idle-gated when the runtime supports it.

Every substantive reply should end with a next-step phase: one concrete next
action, its proof/control class, and the reason a rebuild is or is not required.

The local Master:frontier V5 coding/continuity evolution is composed by:

```bash
python3 tools/context/prove-master-frontier-v5-evolution.py
```

This checks compact context economics, evidence-modality and route/task
authority coherence, per-call head limits plus advisory/explicit input-reserved
hard provider budgets, exact runtime entity scope, immediate same-route grounded
follow-up action lineage, host-enforced completion-only synthesis,
modality-aware completion/retry recovery, streaming late-range reads and route-owned search
coverage, durable recoverable transactional patches, registered argv execution
with bounded leak handling, untracked-aware diff receipts, route-wide
revision-bound proof, compact capacity-checked restart ledgers, bounded startup
recovery, browser checkpoint preservation, monolith delegation, deterministic
agent-trajectory normalization, and fail-closed strategy-candidate ranking. It
is local static/behavioral proof only; it does not prove deployed provider
behavior, production operation, or real external-agent trajectory quality.

The registered generic runtime snapshot boundary is validated with:

```bash
python3 plugins/wasm-agent/tests/master_frontier_runtime_snapshot.test.py
python3 plugins/wasm-agent/tests/master_frontier_runtime_snapshot_collector.test.py
python3 plugins/wasm-agent/tests/master_frontier_runtime_proof.test.py
python3 plugins/wasm-agent/tests/master_frontier_runtime_actions.test.py
python3 tools/context/prove-runtime-snapshot-contract.py
```

This proves schema bounds, redaction, freshness trust, digest binding, compact
projection, read-only user/route-scoped run-history aggregation, opaque proof
resolution, and the bounded runtime-action contracts used by `kernel.inspect`.
It does not prove current live state, a deployed authenticated invocation, host
control, or production behavior.

### Android Live Control Example

After an APK/WebView bundle that contains the Android native control agent is
installed, use the live loop before asking the user to describe the screen or
before proposing another Android rebuild.

Preferred first reads/actions:

```text
native control command: get_runtime_snapshot
GET https://wa.colmeio.com/native/android/wake-word-state
native control command: open_wake_word
native control command: start_voice_wake
native control command: apply_wake_word_policy
```

`get_runtime_snapshot` is intentionally compact: active panel, open modals,
Wake Word status, capabilities, recent redacted events, recent interaction
trace, and at most 30 visible controls. It is UX-budgeted and may return a
skipped result during active touch/typing/scrolling. Treat skipped as a reason
to retry later, not as a user-facing failure.

Live policy fields include:

```text
wakeThreshold
vadRmsThreshold
vadPeakThreshold
transcriptTimeoutMs
transcriptMinLengthMs
transcriptCompleteSilenceMs
transcriptPossibleSilenceMs
transcriptAcceptPartial
```

The cloud Wake Word state may include `diagnosis` and `policy_presets`.
Treat them as loop-shortening guidance, not installed runtime proof. A preset
still needs a native control `apply_wake_word_policy` result and a fresh
post-speech upload to prove behavior.

Rebuild only when the missing change is a native primitive: permissions,
manifest/service lifecycle, native library/engine replacement, package identity,
signing, or a bridge method/capability not already exposed by the installed APK.

## Hermes Wake Shipping

Historical superseded model-shipping proof used direct Android PWA bridge
control:

```bash
curl -fsS -X POST http://127.0.0.1:8877/native/android/hermes-wake-export/request
cat plugins/wasm-agent/state/native-diagnostics/android-hermes-wake-export/result.json
cat plugins/wasm-agent/state/native-diagnostics/latest-android-hermes-wake-dataset.json
```

Expected dataset proof: `result.upload.ok: true`, origin
`https://wa.colmeio.com`, source `android-native-export`, and a non-empty
archive under `plugins/wasm-agent/state/native-diagnostics/android-hermes-wake-datasets/`.

Then train/verify using the latest local uploaded dataset:

```bash
python3 tools/voice/request-hermes-wake-dataset-export.py --origin http://127.0.0.1:8877 --out /tmp/hermes-dataset.zip --no-queue --wait-sec 5
python3 tools/voice/import-hermes-dataset.py /tmp/hermes-dataset.zip --out data/voice/hermes
python3 tools/voice/verify-hermes-dataset.py data/voice/hermes
uv run --with numpy --with torch --with onnx --with onnxruntime python tools/voice/train-hermes-wake.py --dataset data/voice/hermes --out build/voice/hermes.onnx --epochs 30 --threshold-out build/voice/hermes-threshold.json
uv run --with numpy --with onnx --with onnxruntime python tools/voice/verify-hermes-wake-model.py --model build/voice/hermes.onnx --validation-dir data/voice/hermes/validation --threshold 0.58
curl -fsS https://wa.colmeio.com/native/android/hermes-wake-model/latest.json
```

Historical model candidates were validated at `--threshold 0.58`. Current
Android native shells can accept `wakeThreshold` / `wake_threshold` from the
downloaded Hermes proof operation and must report the active value plus
`threshold_policy_source` in native diagnostics.

Real wake-on-Hermes is verified only after the Android bridge installs the
served model with the returned SHA and a runtime proof shows wake detection plus
voice command dispatch. A trained ONNX file alone is implemented-unverified.

Historical superseded blocker as of 2026-06-12: model install was queued, but
the installed Android WebView was still running the older PWA bundle without
the install poller. The current proof order is the installed Windows hot-op
shell proof, doctor, Hermes wake dry-run, then Hermes wake debug classifier.
The older poll path was:

```bash
curl -fsS -X POST http://127.0.0.1:8877/native/android/hermes-wake-install/request
cat plugins/wasm-agent/state/native-diagnostics/android-hermes-wake-install/result.json
```

Expected install proof: `result.ok: true`, matching SHA from
`/native/android/hermes-wake-model/latest.json`, and native status reporting
`model_status: installed`.

## Release Feed

```bash
jq '.' plugins/wasm-agent/public/native/releases/latest.json
python3 tools/windows/check-windows-release-feed.py
sha256sum plugins/wasm-agent/public/native/releases/windows/*.exe
sha256sum native/android/release/*.apk
```

Feed presence is publication evidence, not runtime proof.
Downloaded runtime feed presence is not active-runtime proof; installed
diagnostics must report active runtime ID/SHA after sync.

## Public Scripts

```bash
horc status
horc build doctor
```

Use a script-specific `--help`, doctor, or focused smoke path for scoped edits.
# Master:frontier V4 source investigation

```bash
python3 plugins/wasm-agent/tests/master_frontier_v4_source_investigation.test.py
python3 tools/context/evaluate-master-frontier-v4.py
python3 plugins/wasm-agent/tests/agent_run_store.test.py
python3 tools/context/check-harness-promises.py
python3 tools/context/check-monolith-growth.py
```

These are deterministic static/behavioral and recorded-provider replay proofs.
They do not prove a live frontier provider or production behavior.

When provider access is configured, the separate dev-only source check is
`python3 tools/context/run-master-frontier-v4-live.py`. Treat V4 as
live-frontier verified only when
`reports/master-frontier-v4/live-evaluation.json` has `ok: true`; this never
constitutes production proof.
