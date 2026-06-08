#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dataset="${1:-$repo_root/data/voice/hermes}"

mkdir -p \
  "$dataset/positive" \
  "$dataset/negative/silence" \
  "$dataset/negative/speech" \
  "$dataset/negative/noise" \
  "$dataset/validation"

touch \
  "$dataset/validation/hermes-positive.wav" \
  "$dataset/validation/hermes-negative-silence.wav" \
  "$dataset/validation/hermes-negative-speech.wav" \
  "$dataset/validation/hermes-negative-noise.wav"

cat > "$dataset/README.md" <<'EOF'
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

- 100 positive "Hermes" samples.
- 300 negatives split across silence, speech, and noise.
- At least 3 microphones/devices, including a real Android phone before any
  production wake claim.
- Keep at least 20% held out for validation; do not train on the four fixed
  validation WAVs.
EOF

echo "Prepared Hermes wake dataset skeleton: $dataset"
echo "Replace zero-byte validation placeholders with real WAV fixtures before validation."
