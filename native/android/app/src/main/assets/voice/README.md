# Hermes Android Wake Model Contract

Place the production Hermes wake-word ONNX model here as:

  base_hermes.onnx

The Android service copies assets/voice/base_hermes.onnx into the app-private
files/voice/base_hermes.onnx path on first start when the bundled asset exists
and the runtime copy is missing or stale. Do not add a placeholder or fake ONNX
file: when no validated personalized or base model is available, diagnostics
must report hermes_wake_model_missing and production wake detection must remain
inactive.

Current production engine:

- engine: OpenWakeWordOnnxEngine
- base asset path: assets/voice/base_hermes.onnx
- copied base path: files/voice/base_hermes.onnx
- personalized path: files/voice/hermes.onnx
- model priority: personalized, then base, then no-model safe scaffold
- input name: first ONNX graph input is used; diagnostics report first_input
  only when no model metadata can be read
- input type/format: float32 normalized raw audio, derived from signed PCM16
  mono samples by sample / Short.MAX_VALUE and clamped to [-1.0, 1.0]
- sample rate: 16000 Hz
- input shape: rank 1 to 3, single batch/channel dimensions before the final
  audio window; accepted examples are [16000], [1, 16000], [1, 1, 16000]
- window length: final input dimension, minimum 4000 samples, maximum 32000
  samples; dynamic dimensions resolve to 16000 samples
- preprocessing: none beyond PCM16-to-float normalization; mel/filterbank,
  melspectrogram, embedding, or multi-stage OpenWakeWord classifier exports are
  incompatible unless exported as one raw-PCM pipeline model
- output name: first ONNX graph output is consumed
- output shape: scalar or small confidence vector with no concrete dimension
  greater than 2; the first numeric value is interpreted as Hermes confidence
- confidence threshold: 0.58

Diagnostics:

- hermes_wake_model_missing: no non-empty files/voice/hermes.onnx or
  files/voice/base_hermes.onnx is available
- hermes_wake_model_load_error: ONNX Runtime cannot open the file or model
  metadata cannot be read
- hermes_wake_model_incompatible: the model loads but input/output metadata does
  not match the raw PCM contract above

Real wake-on-Hermes is not complete until a genuine Hermes-trained hermes.onnx is
present and verified against positive and negative audio fixtures.

Training sample persistence:

- Manual `Train Hermes Wake` recordings are written by the installed Android app
  to app-private storage at files/voice/hermes-dataset.
- The browser/PWA does not persist WAV clips. Current Android builds upload
  `files/voice/exports/hermes-dataset.zip` to
  `/native/android/hermes-wake-dataset` when `Export Hermes Dataset` is clicked.
  If the protected cloud download is not available to the current operator, use
  the installed Win11 wasm-agent bridge command `export_hermes_wake_dataset`.
  Do not use terminal ADB from this workspace for this workflow; ADB access for
  this device/export path is only expected through the installed Win11 bridge.
- Clearing Android app data, uninstalling with data removal, or testing in a
  different app profile can make the modal show zero counts even if a prior APK
  session had recordings.
- Use the uploaded/exported `hermes-dataset.zip`, import it into
  `data/voice/hermes`, train and verify `build/voice/hermes.onnx`, then install
  the model into app-private storage at `files/voice/hermes.onnx` through the
  Android bridge method `installHermesWakeModel(modelUrl, sha256)`. This avoids
  APK rebuilds for wake-model iteration.
- The Android wizard is expected to collect a balanced personalized dataset:
  50 Hermes positives across normal, soft, farther-away, phone-on-desk, and
  noisy-room prompts; 20 silence/background negatives; 20 normal-speech
  negatives; and 10 similar-word/confuser negatives. Each accepted sample
  exports duration, RMS dB, peak dB, clipping ratio, silence ratio, estimated
  SNR, category, accepted/rejected state, and rejection reason.
- `metadata.json` uses schema
  `hermes.wasm_agent.android_hermes_wake_dataset.v2` and includes build/device
  fields, sample-rate/channel contract, category counts, accepted/rejected
  counts, per-sample quality metrics, wizard version, hash-only session field,
  creation time, and model target wake word `hermes`.
- Preferred automation: run `tools/voice/ship-hermes-wake.sh` with
  `WASM_AGENT_NATIVE_CONTROL_KEY` set. It queues the Win11 bridge export,
  downloads the uploaded zip, imports, trains, validates, writes
  `build/voice/hermes-calibration.json`, and prints the model SHA from
  `/native/android/hermes-wake-model/latest.json`.

Model acceptance is stricter than crossing 0.58 once: median positive
confidence should be at least 0.75, p10 positive at least 0.60, max
negative/confuser at most 0.40, and the threshold recommendation should retain
at least 0.15 margin. Final acceptance still requires Android live proof showing
clear Hermes crosses threshold and emits wake/command-capture events while
silence and normal speech do not trigger.

Artifact types:

- Dev/test model: generated as hermes-test-only.onnx by
  native/android/scripts/generate-wake-test-onnx.py. It uses mean absolute
  waveform amplitude as confidence, so it proves ONNX loader, evaluator, and APK
  packaging mechanics only. It is not trained on the Hermes wake word.
- Production model: named hermes.onnx and trained/exported for the Hermes wake
  word. This is required before real wake-on-Hermes can be claimed.

Use native/android/scripts/install-wake-model.sh --model path/to/hermes.onnx to
install a production model into this directory. Installing a dev/test fixture
requires the explicit --allow-test-model flag and must be used only for package
mechanics proof.
