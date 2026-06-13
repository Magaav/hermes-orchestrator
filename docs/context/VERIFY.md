# Verification Commands

Run the smallest command that proves the claim being made. Record proof paths in
`CLAIMS.md` or the nearest owner README.

## Context

```bash
rg -n "127\\.0\\.0\\.1:8877|localhost:8877|0\\.0\\.0\\.0:8877|10\\.0\\.2\\.2:8877|win-unpacked|Durable Next Step|current next action|TODO|FIXME|proposal|future|verified|unverified|stale|unknown|fixed|done|complete" \
  README.md AGENTS.md docs/context docs/README.md docs/roadmap plugins/wasm-agent native scripts/public
```

Expected use: inspect every match for unsafe production claims, stale next
actions, proofless success language, and roadmap/current blending.

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

## Windows Native

```bash
cd native/windows/src
npm run verify:win-installer -- /local/plugins/wasm-agent/public/native/releases/windows/WASM-Agent-Setup-x64-0.1.0-20260609T220027Z.exe
```

Writes `native/windows/release/VERIFY.json` when final NSIS extraction and
installed `app.asar` checks pass. This is still not installed-app login proof.

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

Do not use terminal ADB from this Linux workspace and do not use the Win11
bridge export path for Hermes Wake. The supported path is direct Android PWA
bridge control:

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

Android's installed wake runtime uses a fixed 0.58 confidence threshold, so the
served ONNX must pass validation at `--threshold 0.58`.

Real wake-on-Hermes is verified only after the Android bridge installs the
served model with the returned SHA and a runtime proof shows wake detection plus
voice command dispatch. A trained ONNX file alone is implemented-unverified.

Current blocker as of 2026-06-12: model install is queued, but the installed
Android WebView is still running the older PWA bundle without the install
poller. Force/observe reload to `app.js?v=20260612-hermes-wake-install`, then
poll:

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
sha256sum plugins/wasm-agent/public/native/releases/windows/*.exe
sha256sum native/android/release/*.apk
```

Feed presence is publication evidence, not runtime proof.

## Public Scripts

```bash
horc status
horc build doctor
```

Use a script-specific `--help`, doctor, or focused smoke path for scoped edits.
