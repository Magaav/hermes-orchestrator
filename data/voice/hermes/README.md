# Hermes Wake Dataset

Expected layout:

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

Audio contract:

- WAV, mono, 16 kHz, PCM16 preferred.
- Positive samples contain the wake word "Hermes".
- Negative speech samples must not contain "Hermes".
- Validation files must be real audio, not zero-byte placeholders, before a
  production candidate can pass validation.

Minimum baseline collection:

- Tiny smoke threshold: at least 5 positive "Hermes" samples and 10 negative
  samples. This is only enough to exercise the training/export/Android path.
- Useful baseline threshold: at least 50 positive samples and 150 negative
  samples.
- Production candidate threshold: around 100+ positive samples and 300+
  negative samples split across silence, speech, and noise.
- At least 3 microphones/devices, including a real Android phone before any
  production wake claim.
- Keep at least 20% held out for validation; do not train on the four fixed
  validation WAVs.

Record samples on this machine:

```bash
python3 tools/voice/record-hermes-samples.py --kind positive --count 10 --seconds 1.2 --speaker "$USER" --device-label desktop
python3 tools/voice/record-hermes-samples.py --kind negative-silence --count 5 --seconds 1.2 --speaker "$USER" --device-label desktop
python3 tools/voice/record-hermes-samples.py --kind negative-speech --count 5 --seconds 1.2 --speaker "$USER" --device-label desktop
python3 tools/voice/record-hermes-samples.py --kind negative-noise --count 5 --seconds 1.2 --speaker "$USER" --device-label desktop
```

Import existing WAVs. Files are copied as unique names when already mono 16 kHz
PCM16, or converted automatically when `ffmpeg` is installed:

```bash
tools/voice/import-hermes-samples.sh --positive --from /path/to/hermes-positive-wavs --speaker "$USER" --device-label desktop
tools/voice/import-hermes-samples.sh --negative-speech --from /path/to/non-hermes-speech-wavs --speaker "$USER" --device-label desktop
```

Later, capture Android phone microphone samples because the phone mic, AGC,
noise suppression, distance, and room acoustics can differ sharply from a
desktop mic. Put phone training samples under the same category directories
with a phone `--device-label`, and keep phone-only held-out samples in
`validation/` until they are used to prove generalization.
