#!/usr/bin/env bash
set -euo pipefail

origin="${WASM_AGENT_ORIGIN:-https://wa.colmeio.com}"
dataset_zip="${HERMES_WAKE_DATASET_ZIP:-/tmp/hermes-dataset.zip}"
dataset_dir="${HERMES_WAKE_DATASET_DIR:-data/voice/hermes}"
model_out="${HERMES_WAKE_MODEL_OUT:-build/voice/hermes.onnx}"
threshold_out="${HERMES_WAKE_THRESHOLD_OUT:-build/voice/hermes-threshold.json}"
epochs="${HERMES_WAKE_EPOCHS:-30}"

cd "$(dirname "$0")/../.."

python3 tools/voice/request-hermes-wake-dataset-export.py \
  --origin "$origin" \
  --out "$dataset_zip" \
  --wait-sec "${HERMES_WAKE_EXPORT_WAIT_SEC:-180}"

python3 tools/voice/import-hermes-dataset.py "$dataset_zip" --out "$dataset_dir"
python3 tools/voice/verify-hermes-dataset.py "$dataset_dir"

uv run \
  --with numpy \
  --with torch \
  --with onnx \
  --with onnxruntime \
  python tools/voice/train-hermes-wake.py \
    --dataset "$dataset_dir" \
    --out "$model_out" \
    --epochs "$epochs" \
    --threshold-out "$threshold_out"

uv run \
  --with numpy \
  --with onnx \
  --with onnxruntime \
  python tools/voice/verify-hermes-wake-model.py \
    --model "$model_out" \
    --validation-dir "$dataset_dir/validation"

sha256sum "$model_out"
curl -fsS "$origin/native/android/hermes-wake-model/latest.json"
