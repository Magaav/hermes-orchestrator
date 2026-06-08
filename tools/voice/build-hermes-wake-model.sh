#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

dataset="${HERMES_WAKE_DATASET:-data/voice/hermes}"
output="${HERMES_WAKE_OUTPUT:-build/voice/hermes.onnx}"
python_bin="${HERMES_WAKE_PYTHON:-python3}"

if [[ -x "${HERMES_WAKE_VENV:-$repo_root/.venv-hermes-wake}/bin/python" ]]; then
  python_bin="${HERMES_WAKE_VENV:-$repo_root/.venv-hermes-wake}/bin/python"
fi

"$python_bin" tools/voice/train-hermes-wake-model.py \
  --dataset "$dataset" \
  --output "$output"

echo "Validated baseline candidate staged at: $output"
