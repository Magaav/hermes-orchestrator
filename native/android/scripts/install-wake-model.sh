#!/usr/bin/env bash
set -euo pipefail

target="native/android/app/src/main/assets/voice/hermes.onnx"
model=""
allow_test_model=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)
      model="${2:-}"
      shift 2
      ;;
    --allow-test-model)
      allow_test_model=1
      shift
      ;;
    *)
      echo "Usage: $0 --model path/to/model.onnx [--allow-test-model]" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$model" ]]; then
  echo "Missing --model path/to/model.onnx" >&2
  exit 2
fi

if [[ ! -f "$model" ]]; then
  echo "Model file not found: $model" >&2
  exit 1
fi

case "$model" in
  *.onnx) ;;
  *)
    echo "Refusing non-ONNX model path: $model" >&2
    exit 1
    ;;
esac

base="$(basename "$model")"
case "$base" in
  hermes.onnx)
    if strings "$model" | grep -Eq 'NON_PRODUCTION|hermes-test-only|hermes-dev-fixture'; then
      echo "Refusing to install hermes.onnx because it contains a non-production fixture marker." >&2
      exit 1
    fi
    ;;
  hermes-test-only.onnx|hermes-dev-fixture.onnx)
    if [[ "$allow_test_model" != "1" ]]; then
      echo "Refusing to install non-production test model without --allow-test-model: $base" >&2
      exit 1
    fi
    echo "Installing NON-PRODUCTION test fixture for packaging mechanics only." >&2
    ;;
  *)
    echo "Refusing ambiguous model name: $base" >&2
    echo "Use hermes.onnx for production or hermes-test-only.onnx/hermes-dev-fixture.onnx with --allow-test-model." >&2
    exit 1
    ;;
esac

mkdir -p "$(dirname "$target")"
cp "$model" "$target"
echo "Installed wake model:"
echo "$target"
