#!/usr/bin/env bash
set -euo pipefail

variant="${1:-release}"
asset_model="native/android/app/src/main/assets/voice/hermes.onnx"

if [[ ! -f "$asset_model" ]]; then
  echo "Wake asset guard passed: no bundled Hermes model."
  exit 0
fi

if strings "$asset_model" | grep -Eq 'NON_PRODUCTION|hermes-test-only|hermes-dev-fixture'; then
  echo "Refusing to package non-production Hermes wake fixture as assets/voice/hermes.onnx ($variant)." >&2
  exit 1
fi

echo "Wake asset guard passed: bundled model does not contain known non-production markers."
