# Android Hermes Wake Training

Real wake-on-Hermes is still blocked until a genuine Hermes-trained ONNX model
exists. The Android wake path is already ONNX-only and intentionally does not
wake when `hermes.onnx` is absent.

## Evaluated Paths

### Chosen: repo-local raw-audio PyTorch baseline

Use `tools/voice/train-hermes-wake-model.py` to train a tiny binary CNN directly
from WAV files and export one ONNX graph at `build/voice/hermes.onnx`.

Why this is the best fit for this repo now:

- reproducible and scriptable from checked-in tooling;
- open enough for repo usage, with no vendor account or runtime key;
- exports a single ONNX graph compatible with Android ONNX Runtime;
- preserves the existing raw mono 16 kHz float32 `[1, 16000]` contract;
- keeps packaging guards unchanged: a model is installed only after validation.

This is a **baseline candidate** path. It can produce a real trained model from
real Hermes recordings, but it should not be treated as production quality until
it passes a larger positive/negative validation set on target Android devices.

### openWakeWord-style training/export

openWakeWord is the stronger wake-word-quality direction: it is open-source,
exports ONNX classifier models, and is widely used for on-device assistants.
Its common custom wake-word models are not a direct drop-in for this app because
the runtime normally uses audio feature extraction and an embedding model around
the custom classifier. That conflicts with this repo's current single ONNX
raw-PCM artifact contract unless the complete preprocessing plus wake head is
exported as one graph, or Android is changed to host the full openWakeWord
pipeline. That is a larger runtime migration, not the shortest real model path.

### Existing local audio/ML path

The repo has voice mode, STT/TTS docs, Android microphone capture, and wake
state-machine tests, but no existing checked-in wake-word training stack that
can be adapted into a production Hermes detector. The new baseline trainer is
therefore intentionally small and local.

### Picovoice/Porcupine

Porcupine is unsuitable for this mission because custom wake words use Picovoice
assets such as `.ppn` with the Porcupine SDK and AccessKey flow. That does not
fit the current `assets/voice/hermes.onnx` raw-PCM ONNX contract or the repo's
open validation/install guard flow.

## Dataset Layout

```text
data/voice/hermes/
  positive/
  negative/silence/
  negative/speech/
  negative/noise/
  validation/hermes-positive.wav
  validation/hermes-negative-silence.wav
  validation/hermes-negative-speech.wav
  validation/hermes-negative-noise.wav
```

Prepare the skeleton:

```bash
tools/voice/prepare-hermes-wake-dataset.sh
```

## Sample Collection Protocol

Minimum baseline candidate:

- 100 positive samples saying exactly "Hermes".
- 300 negative samples total: at least 100 speech, 100 noise, and 100 silence or
  non-wake ambient samples.
- At least 3 speakers if possible; at minimum, collect one primary developer
  speaker plus one non-primary speaker before calling it anything beyond a
  personal baseline.
- At least 3 microphones/devices: developer machine mic, wired or Bluetooth
  headset, and real Android phone mic.
- Validation split: keep at least 20% of samples out of training. The four
  fixed validation files must be real examples not used for training.
- Record now from the developer machine: desktop/laptop mic positives, silence,
  room noise, and negative speech that does not include "Hermes".
- Must wait for real Android capture: phone mic positives and negatives in the
  real unlock/wake posture, because the production wake path runs there.

Naming convention:

```text
positive/hermes_<speaker>_<device>_<YYYYMMDDThhmmssZ>_<index>.wav
negative/speech/nohermes_<speaker>_<device>_<YYYYMMDDThhmmssZ>_<index>.wav
negative/noise/noise_<source>_<device>_<YYYYMMDDThhmmssZ>_<index>.wav
negative/silence/silence_<room>_<device>_<YYYYMMDDThhmmssZ>_<index>.wav
```

All WAVs should be mono 16 kHz PCM16. The trainer can resample PCM16 WAV files,
but collecting in the target format reduces accidental preprocessing drift.

## Recording And Importing Samples

Record from the developer machine:

```bash
tools/voice/fetch-or-setup-wake-training.sh
source .venv-hermes-wake/bin/activate
tools/voice/record-hermes-samples.py --kind positive --count 25 --speaker alice --device-label laptop
tools/voice/record-hermes-samples.py --kind negative-speech --count 25 --speaker alice --device-label laptop
tools/voice/record-hermes-samples.py --kind negative-noise --count 25 --speaker room --device-label laptop
tools/voice/record-hermes-samples.py --kind negative-silence --count 25 --speaker room --device-label laptop
```

Import existing WAVs:

```bash
tools/voice/import-hermes-samples.sh --positive --from ~/hermes-positive-wavs
tools/voice/import-hermes-samples.sh --negative-speech --from ~/hermes-negative-speech-wavs
```

Replace these validation placeholders with held-out real files:

```text
data/voice/hermes/validation/hermes-positive.wav
data/voice/hermes/validation/hermes-negative-silence.wav
data/voice/hermes/validation/hermes-negative-speech.wav
data/voice/hermes/validation/hermes-negative-noise.wav
```

## Model Contract

The Android engine accepts one ONNX graph with:

- raw mono 16 kHz audio normalized to float32;
- one input shaped like `[16000]`, `[1, 16000]`, or `[1, 1, 16000]`;
- final input window from 4000 to 32000 samples;
- first output as scalar/small confidence;
- no separate mel, embedding, or classifier stage outside the ONNX graph;
- wake threshold `0.58`.

## Build, Validate, And Install

After recording enough samples and replacing validation placeholders:

```bash
tools/voice/fetch-or-setup-wake-training.sh
source .venv-hermes-wake/bin/activate
tools/voice/build-hermes-wake-model.sh
tools/voice/import-hermes-wake-model.sh --candidate build/voice/hermes.onnx --install-asset
native/android/scripts/verify-wake-assets.sh release
```

Build and inspect the APK with model expectation enabled:

```bash
cd native/android
./.gradle-dist/gradle-8.9/bin/gradle :app:assembleDebug --no-daemon
cd ../..
native/android/scripts/inspect-wake-apk.sh native/android/app/build/outputs/apk/debug/app-debug.apk --expect-model
```

Real wake-on-Hermes can be claimed only after a genuine trained model passes
positive and negative validation and is packaged into a fresh APK.
