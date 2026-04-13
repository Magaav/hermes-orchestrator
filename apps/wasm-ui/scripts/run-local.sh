#!/usr/bin/env bash
set -euo pipefail

WASM_UI_EXPERIMENTAL=1 python3 /local/scripts/ui-gateway/run.py
