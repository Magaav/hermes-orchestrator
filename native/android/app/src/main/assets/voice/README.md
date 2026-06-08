# Hermes Android Wake Model Contract

Place the production Hermes wake-word ONNX model here as:

  hermes.onnx

The Android service copies assets/voice/hermes.onnx into the app-private
files/voice/hermes.onnx path on first start. Do not add a placeholder or fake
ONNX file: when the model is absent, diagnostics must report
hermes_wake_model_missing and production wake detection must remain inactive.

Current production engine:

- engine: OpenWakeWordOnnxEngine
- asset path: assets/voice/hermes.onnx
- copied app-private path: files/voice/hermes.onnx
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

- hermes_wake_model_missing: files/voice/hermes.onnx does not exist
- hermes_wake_model_load_error: ONNX Runtime cannot open the file or model
  metadata cannot be read
- hermes_wake_model_incompatible: the model loads but input/output metadata does
  not match the raw PCM contract above

Real wake-on-Hermes is not complete until a genuine Hermes-trained hermes.onnx is
present and verified against positive and negative audio fixtures.

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
