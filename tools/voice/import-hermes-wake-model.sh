#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

candidate=""
install_asset=0
validation_dir="${HERMES_WAKE_VALIDATION:-data/voice/hermes/validation}"
stage_to="${HERMES_WAKE_STAGE_TO:-build/voice/hermes.onnx}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --candidate)
      candidate="${2:-}"
      shift 2
      ;;
    --install-asset)
      install_asset=1
      shift
      ;;
    --validation-dir)
      validation_dir="${2:-}"
      shift 2
      ;;
    *)
      echo "Usage: $0 --candidate path/to/hermes.onnx [--validation-dir dir] [--install-asset]" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$candidate" ]]; then
  echo "Missing --candidate path/to/hermes.onnx" >&2
  exit 2
fi

args=(--candidate "$candidate" --validation-dir "$validation_dir" --stage-to "$stage_to")
if [[ "$install_asset" == "1" ]]; then
  args+=(--install-asset)
fi

python3 tools/voice/export-hermes-wake-onnx.py "${args[@]}"
echo "Imported and validated Hermes wake candidate at: $stage_to"
