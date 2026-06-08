# Android Hermes Voice Wake

Hermes Voice Wake is an Android-native orchestration input layer for WASM Agent. It is not a WebView-only microphone feature.

## Enablement

The service runs only after explicit opt-in from the Android native debug/settings surface. The APK requests `RECORD_AUDIO` and, on Android 13+, `POST_NOTIFICATIONS` at runtime before starting a foreground microphone service with the persistent notification:

`WASM Agent listening for Hermes`

Disable it from the same debug card when you do not want always-on wake listening.

## Privacy

- Continuous background audio is not uploaded.
- Wake-word detection runs locally first.
- After local wake detection, Android opens a bounded command recognition window only.
- The emitted orchestration payload contains the transcript and metadata, not retained audio.
- `audio_retained` is always `false` by default.

The structured event sent to `/native/events` is:

```json
{
  "type": "voice_command",
  "wake_word": "hermes",
  "transcript": "open my current run logs",
  "confidence": 0.82,
  "started_at": 1780833600000,
  "ended_at": 1780833607800,
  "source": "android_native_hermes_voice_wake",
  "build_id": "android-build",
  "session_id": "voice-session",
  "privacy_mode": "wake-word-local-transcript-only",
  "audio_retained": false
}
```

## Engines

Wake engines are abstracted as `WakeWordEngine`:

- `OpenWakeWordOnnxEngine`
- `StubWakeWordEngine` for tests and simulator evidence

Transcription engines are abstracted as `TranscriptionEngine`:

- `AndroidSpeechRecognizerEngine` for MVP
- `VoskOfflineEngine` optional
- `WhisperCppEngine` optional/future

To replace the Hermes wake model, place a compatible Hermes wake ONNX model at:

`files/voice/hermes.onnx`

The APK bundles ONNX Runtime Android and `OpenWakeWordOnnxEngine` loads the model locally from that path. If the APK later ships `assets/voice/hermes.onnx`, the service copies it into the app-private `files/voice/hermes.onnx` location on first start.

The current native runtime accepts a single-file raw PCM contract:

- Asset path: `assets/voice/hermes.onnx`
- App-private path: `files/voice/hermes.onnx`
- Input name: first graph input; diagnostics use `first_input` only when no model metadata can be read.
- Input format: signed PCM16 mono at 16 kHz converted to float32 by `sample / Short.MAX_VALUE`, clamped to `[-1.0, 1.0]`.
- Input shape: rank 1 to 3 with only single batch/channel dimensions before the final audio window, for example `[16000]`, `[1, 16000]`, or `[1, 1, 16000]`.
- Frame/window length: final input dimension, accepted from 4000 to 32000 samples; dynamic dimensions resolve to 16000 samples.
- Preprocessing: no mel, filterbank, melspectrogram, embedding, or separate classifier pipeline is run by the Android engine.
- Output name: first graph output.
- Output shape: scalar or small confidence vector with no concrete dimension greater than 2.
- Confidence: first numeric output value, clamped to `[0.0, 1.0]`.
- Threshold: `0.58`.

The service reports:

- `hermes_wake_model_missing` when the model file is absent.
- `hermes_wake_model_load_error` when ONNX Runtime cannot load the file.
- `hermes_wake_model_incompatible` when the ONNX input/output shape is not compatible with this raw-audio contract.

Many stock OpenWakeWord exports are multi-stage models that expect melspectrogram features, embeddings, or a separate preprocessing pipeline rather than raw PCM. Those models should either be exported as one raw-PCM pipeline model or paired with a future engine implementation that runs the same feature/embedding stages locally before the classifier. The service refuses always-on listening until the local model contract is explicit.

`StubWakeWordEngine` is for JVM tests and simulator fixtures only, not production wake detection.

Android's platform `SpeechRecognizer` does not accept arbitrary PCM buffers. For the MVP Android engine, the service releases the local wake-listening `AudioRecord` after Hermes is detected, then starts a bounded live recognition session for the command. Offline PCM transcription remains pluggable through Vosk or whisper.cpp.

## Diagnostics

Native diagnostics include `voice_wake` with:

- enabled state
- permission state
- service state
- wake/transcription engine names
- wake model path, input shape, compatibility contract, and load error
- last wake event
- last transcript
- last error
- battery warning

The Android native debug modal renders these fields and provides enable/disable controls.

## Simulator

Positive proof:

```bash
horc simulate android --voice-wake fixture-hermes-command.wav
```

Negative fixtures:

```bash
horc simulate android --voice-wake false-wake
horc simulate android --voice-wake permission-denied
horc simulate android --voice-wake service-killed
horc simulate android --voice-wake no-transcription-engine
horc simulate android --voice-wake missing-model
```

The passing fixture proves foreground service evidence, microphone permission state, wake detection, transcription, `voice_command` delivery to wasm-agent, visible timeline evidence, and redacted logs.

## Model Artifact Next Step

There are two separate ONNX artifact types.

Dev/test fixture model:

- Generated by `native/android/scripts/generate-wake-test-onnx.py`.
- Default output: `native/android/build/generated/voice/hermes-test-only.onnx`.
- Contract: raw mono 16 kHz float32 `[1, 16000]` input to `[1, 1]` confidence output.
- Behavior: confidence is `mean(abs(waveform))`, so loud synthetic audio crosses the `0.58` threshold and silence does not.
- Purpose: proves ONNX file generation, Android contract shape, explicit installation, APK packaging, and mechanical evaluation paths only.
- It is not trained on the Hermes wake word and must not be described as real wake detection.

Production Hermes model:

- File name: `hermes.onnx`.
- Required location when intentionally supplied: `native/android/app/src/main/assets/voice/hermes.onnx`.
- Must be trained on positive "Hermes" wake samples and negative non-wake audio.
- Must satisfy the Android raw PCM ONNX contract or ship with a matching Android preprocessing engine.

Generate and verify the dev/test fixture:

```bash
native/android/scripts/generate-wake-test-onnx.py
native/android/scripts/verify-wake-test-onnx.py
```

If Python ONNX Runtime is available in a virtual environment, load and evaluate
the generated model directly:

```bash
native/android/scripts/run-wake-test-onnx-ort.py
```

Install a model only when explicitly requested:

```bash
native/android/scripts/install-wake-model.sh --model path/to/hermes.onnx
```

For an explicit package-mechanics proof using the non-production fixture:

```bash
native/android/scripts/prove-wake-test-model-packaging.sh
```

That script temporarily installs `hermes-test-only.onnx` as the asset model with `--allow-test-model`, builds the debug APK, verifies `assets/voice/hermes.onnx` is packaged, and restores the prior asset state.

For a real production model, create or export a genuine Hermes wake-word model that includes any required audio preprocessing inside the ONNX graph and satisfies the raw PCM contract above. Place it at:

`native/android/app/src/main/assets/voice/hermes.onnx`

Then build the APK and run package inspection with model expectation enabled:

```bash
native/android/scripts/inspect-wake-apk.sh native/android/app/build/outputs/apk/debug/app-debug.apk --expect-model
```

Production training/export plan:

Dataset layout:

```text
data/voice/hermes/
  positive/*.wav
  negative/silence/*.wav
  negative/speech/*.wav
  negative/noise/*.wav
  validation/hermes-positive.wav
  validation/hermes-negative-silence.wav
  validation/hermes-negative-speech.wav
  validation/hermes-negative-noise.wav
```

Expected positive samples:

- Multiple speakers saying "Hermes".
- Varied distance, device microphones, accents, room tone, and speaking pace.
- 16 kHz mono WAV, or source audio converted reproducibly to that format.

Expected negative samples:

- Silence and low-level room noise.
- Speech that does not contain "Hermes".
- Similar-sounding non-wake words and common Android command phrases.
- Environmental noise and media playback that should not trigger wake.

Prepare the dataset skeleton:

```bash
tools/voice/prepare-hermes-wake-dataset.sh
```

External training/export scaffold:

```bash
tools/voice/train-hermes-wake-model.py --dataset data/voice/hermes --output build/voice/hermes.onnx
tools/voice/export-hermes-wake-onnx.py \
  --candidate path/to/hermes.onnx \
  --validation-dir data/voice/hermes/validation \
  --stage-to build/voice/hermes.onnx
```

The training command is a scaffold until real samples and an external wake-word
training pipeline are supplied. The export command validates the candidate
against the documented Android contract before use.

Final wake proof needs at least these fixtures:

- `tools/app-simulator/fixtures/android/voice/hermes-positive.wav`
- `tools/app-simulator/fixtures/android/voice/hermes-negative-silence.wav`
- `tools/app-simulator/fixtures/android/voice/hermes-negative-speech.wav`
- `tools/app-simulator/fixtures/android/voice/hermes-negative-noise.wav`

Acceptance criteria:

- `hermes-positive.wav` wakes with confidence >= `0.58`.
- `hermes-negative-silence.wav` does not wake.
- `hermes-negative-speech.wav` does not wake.
- The APK contains ONNX Runtime native libs and `assets/voice/hermes.onnx`.
- Real wake-on-Hermes is claimed only after those positive and negative real-audio checks pass with a genuine Hermes-trained model.
