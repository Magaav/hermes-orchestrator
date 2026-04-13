#!/usr/bin/env bash
set -euo pipefail

IMAGE="${WASM_UI_BUILDER_IMAGE:-hermes-wasm-ui-builder:latest}"

docker build -f /local/apps/wasm-ui/Dockerfile.build -t "${IMAGE}" /local

docker run --rm -v /local:/workspace -w /workspace/apps/wasm-ui "${IMAGE}" \
  "for f in /workspace/apps/wasm-ui/api.js /workspace/apps/wasm-ui/app.js /workspace/apps/wasm-ui/analyzer/js-fallback.js /workspace/apps/wasm-ui/analyzer/wasm-runtime.js /workspace/apps/wasm-ui/analyzer/log-analyzer.js /workspace/apps/wasm-ui/analyzer/analysis.worker.js /workspace/apps/wasm-ui/scripts/benchmark-log-parser.mjs; do echo Checking \$f; node --check \$f; done"

docker run --rm -v /local:/workspace -w /workspace/apps/wasm-ui/wasm/log-worker "${IMAGE}" \
  "wasm-pack build --target web --out-dir ../pkg"

docker run --rm -v /local:/workspace -w /workspace/apps/wasm-ui "${IMAGE}" \
  "node /workspace/apps/wasm-ui/scripts/benchmark-log-parser.mjs --input /workspace/logs/nodes/orchestrator/runtime.log --lines 120000 --iterations 6"
