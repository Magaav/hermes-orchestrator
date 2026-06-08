#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
venv="${HERMES_WAKE_VENV:-$repo_root/.venv-hermes-wake}"
python_bin="${PYTHON:-python3}"

"$python_bin" -m venv "$venv"
"$venv/bin/python" -m pip install --upgrade pip
"$venv/bin/python" -m pip install numpy torch onnx onnxruntime sounddevice

cat <<EOF
Hermes wake training environment ready:
  source "$venv/bin/activate"

This installs the repo-local raw-PCM baseline trainer dependencies. For
openWakeWord-style training, use its upstream training/export flow separately,
then import the resulting single-graph raw-PCM ONNX only if it satisfies:
  tools/voice/verify-hermes-wake-model.py --model build/voice/hermes.onnx
EOF
