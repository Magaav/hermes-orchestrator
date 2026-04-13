#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${WASM_UI_API_TOKEN:-}" ]]; then
  echo "Set WASM_UI_API_TOKEN before running this script."
  exit 1
fi

WASM_UI_EXPERIMENTAL=1 python3 /local/scripts/ui-gateway/run.py
