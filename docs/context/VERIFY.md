# Verification Commands

Run the smallest command that proves the claim being made. Record proof paths in
`CLAIMS.md` or the nearest owner README.

## Context

```bash
python3 tools/context/check-context-sync.py
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

Use conservative generated-block repair only when the durable active state
changes:

```bash
python3 tools/context/check-context-sync.py --fix
make context-fix
```

## Fresh-Agent Structured Test

Use `REVIEW.md` to answer the JSON test from docs only. If any field requires
guessing, update the route map, claim registry, or nearest child docs.

## wasm-agent

```bash
horc simulate web
/local/plugins/wasm-agent/scripts/doctor.sh
```

Use focused tests under `plugins/wasm-agent/tests` when touching one behavior.
`horc simulate web` proves browser/PWA behavior only.

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
```

The report must name the behavior proven. Voice wake PASS is not OAuth PASS.

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
